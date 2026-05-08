from pathlib import Path
import hashlib
import sys
import subprocess
from os import path
from datetime import datetime, timezone
from typing import Literal, Any, Annotated
import xml.etree.ElementTree
import csv as csvmod  # to avoid collision with the csv() function

from cyclopts import App, Parameter
from loguru import logger
import requests
from glom import glom
import yaml
from rich.prompt import Confirm

from bwftool.bwfIO import get_bwf_tech
from bwftool.bwfIO import get_bwf_core
from bwftool.bwfIO import get_xmp
from bwftool.aws_s3 import upload_s3

app = App(help="CLI tool for working with Broadcast Wav files.")

yaml_path = Path.home() / ".bwftool"

data = {}
if yaml_path.exists():
    with open(yaml_path, "r") as file:
        data = yaml.safe_load(file)
else:
    logger.info(f"YAML config file {yaml_path.absolute()} not found. Some functionality may be missing.")

grist_doc_id = data.get("grist_doc_id")
grist_key = data.get("grist_key")
s3_bucket = data.get("s3_bucket")

if grist_doc_id and grist_key:
    grist_base_url = "https://docs.getgrist.com/api"
    grist_tables_url = f"{grist_base_url}/docs/{grist_doc_id}/tables"
    grist_api_headers = {"Authorization": f"Bearer {grist_key}"}
else:
    grist_base_url = None


def sha256(file: str) -> str:
    h = hashlib.sha256()
    with open(file, "rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def pretty_print(thing):
    for name, val in thing.items():
        print(f'{name:20} => {val}')


def get_from_grist(table: Literal['di', 'columns'], identifier):
    if table == 'di':
        grist_out = requests.get(f"{grist_tables_url}/Digital_instantiations/records", headers=grist_api_headers,
                                     params={"filter": f'{{"Digital_instantiation_identifier": ["{identifier}"]}}'})
    elif table == 'columns':
        grist_out = requests.get(f"{grist_tables_url}/Digital_instantiations/columns", headers=grist_api_headers)
    else:
        logger.error(f"table {table} not supported.")
        exit(1)

    if grist_out.status_code >= 400:
        logger.error(f'Grist API call failed. {grist_out.text}')
        return None
    if grist_out.status_code != 200:
        logger.error(f'Grist API problem. {grist_out.text}')
        return None

    if table == 'di':
        records = grist_out.json()["records"]
        if len(records) > 1:
            message = (f"the identifier {identifier} has more than one digital instantiation record in Grist"
                       " -- this isn't supposed to happen!")
            logger.error(message)
            return None

        return records

    if table == 'columns':
        return grist_out

    return None


def put_to_grist(identifier, metadata, yes=False):
    records = get_from_grist('di', identifier)
    if records is None:
        exit(1)

    if len(records) == 0:
        logger.trace(f"creating new digital instantiation {identifier}")
        grist_out = requests.post(f"{grist_tables_url}/Digital_instantiations/records",
                                  headers=grist_api_headers, json={"records": [{"fields": metadata}]})

        if grist_out.status_code == requests.codes.ok:
            logger.info(f"digital instantiation {identifier} successfully created")
        elif grist_out.ok:
            logger.warning("digital instantiation creation returned a status > 200 but < 400")
        else:
            logger.error(f"digital instantiation {identifier} could not be created. {grist_out.text}")
    else:
        grist_data = records[0]['fields']
        row_id = records[0]['id']
        logger.trace(f"updating digital instantiation {identifier}, record id {row_id}")

        differences = {k: metadata[k] for k in metadata.keys()
                       if metadata[k] != "" and grist_data[k] != "" and metadata[k] != grist_data[k]}

        new_fields = {k: metadata[k] for k in metadata.keys()
                      if metadata[k] != "" and (grist_data[k] == "" or grist_data[k] is None)}

        if new_fields:
            print("The following metadata fields are currently not in Grist:")
            pretty_print(new_fields)
            if yes or Confirm.ask('Do you want to update the metadata in Grist?', default=True):
                grist_out = requests.patch(f"{grist_tables_url}/Digital_instantiations/records",
                                           headers=grist_api_headers,
                                           json={"records": [{"id": row_id, "fields": new_fields}]})

                if grist_out.status_code == requests.codes.ok:
                    logger.info(f"digital instantiation {identifier} successfully updated")
                elif grist_out.ok:
                    logger.warning("digital instantiation update returned a status > 200 but < 400")
                else:
                    logger.error(f"digital instantiation {identifier} could not be updated")

        if differences:
            print("the following fields in the BWF file differ from those in Grist:")
            pretty_print(differences)
            if yes or Confirm.ask('Do you want to update the metadata in Grist?', default=True):
                grist_out = requests.patch(f"{grist_tables_url}/Digital_instantiations/records",
                                           headers=grist_api_headers,
                                           json={"records": [{"id": row_id, "fields": differences}]})

                if grist_out.status_code == requests.codes.ok:
                    logger.info(f"digital instantiation {identifier} successfully updated")
                elif grist_out.ok:
                    logger.warning("digital instantiation update returned a status > 200 but < 400")
                else:
                    logger.error(f"digital instantiation {identifier} could not be updated")

        if not new_fields and not differences:
            print("the metadata in the BWF file match those in Grist")


@app.command
def di(*files: str, file_digest = False, yes = False):
    """Extract BWF metadata and create/update a Digital Instantiation in Grist.

        Parameters
        ----------
        file_digest : bool, optional
            Calculate the SHA256 digest of the entire WAV file and store result in the DI. Slow for large files!
        yes: bool, optional
            Answer 'yes' to all questions. May cause unintended overwriting of DI metadata in Grist.
        files: str
            Path(s) to BWF file(s).
    """

    if grist_base_url is None:
        logger.error("Grist table ID and/or key has not been provided")
        exit(1)

    full_field_mapping = {"OriginalFilename": "Digital_instantiation_identifier", "FileUse": "FileUse",
                          "Duration": "Duration", "ICMT": "Digitization_comment", "MD5Stored": "MD5Stored",
                          "OriginationDate": "OriginationDate", "OriginationTime": "OriginationTime",
                          "CodingHistory": "CodingHistory", "ITCH": "Technician", "ISFT": "Creating_software",
                          "Channels": "Channels", "SampleRate": "SampleRate", "BitPerSample": "BitPerSample",
                          "FileSize": "File_Size", "Description": "Description"}

    grist_out = get_from_grist('columns', None)
    if grist_out is None:
        exit(1)

    grist_columns = glom(grist_out.json(), ('columns', ['id']))
    field_mapping = {key: value for key, value in full_field_mapping.items() if value in grist_columns}
    if len(field_mapping) < len(full_field_mapping):
        logger.info(f'Some columns for valid BWF data are missing in the Grist DI table')

    for infile in files:
        infile = Path(infile)
        try:
            metadata = get_bwf_core(infile)
        except subprocess.CalledProcessError:
            logger.error(f'BWF file {infile} could not be opened or is not a WAV file')
            continue

        # TODO allow for MP3 DI creation

        metadata["filename"] = infile  # TODO Why is this necessary????
        metadata.update(get_bwf_tech(infile))

        if metadata["OriginalFilename"] != "":
            if metadata["filename"] != metadata["OriginalFilename"]:
                logger.warning(
                    f'Mismatch in current ({infile}) and original ({metadata["OriginalFilename"]}) filenames')

            identifier = metadata["OriginalFilename"]
        else:
            identifier = Path(metadata["filename"]).name
            metadata["OriginalFilename"] = identifier

        metadata["FileSize"] = path.getsize(infile)

        # remap BWFfileIO field names to Grist field names, and get rid of the unused ones
        metadata = {field_mapping[k]: metadata[k] for k in metadata.keys() if k in field_mapping.keys()}

        records = get_from_grist('di', identifier)
        if records is None:
            continue

        # convert the OriginationDate from ISO to unix timestamp to match how Grist encodes dates
        if metadata["OriginationDate"] != "":
            date_obj = datetime.strptime(metadata["OriginationDate"], '%Y-%m-%d')
            date_obj = date_obj.replace(tzinfo=timezone.utc)
            metadata["OriginationDate"] = int(date_obj.timestamp())

        # convert the fields which are integers in Grist into integers
        metadata["Channels"] = int(metadata["Channels"])
        metadata["SampleRate"] = int(metadata["SampleRate"])
        metadata["BitPerSample"] = int(metadata["BitPerSample"])

        if file_digest:
            if len(records) == 1 and records[0]['fields']['SHA256']:
                logger.warning('SHA256 already exists in Grist DI table. Skipping digest calculation.')
            else:
                metadata["SHA256"] = sha256(infile)

        put_to_grist(identifier, metadata, yes)


@app.command
def s3upload(*files: str, skip_checksum: bool = False, store_sha: bool = True, verify_sha: bool = False,
             threshold_mb: int = 100, chunk_mb: int = 10, concurrency: int = 8,
             storage_class: Literal["STANDARD", "INTELLIGENT_TIERING", "STANDARD_IA", "ONEZONE_IA",
                                    "GLACIER_IR", "GLACIER", "DEEP_ARCHIVE"] = "DEEP_ARCHIVE"):
    """Upload file(s) to an S3 bucket. Bucket information must be in the bwftool config file, and AWS credentials
        for boto3 must be in the '~/.aws' directory.

        Parameters
        ----------
        files:
            One or more files to upload.
        skip_checksum:
            By default, a SHA256 checksum is retreived from Grist (or calculated if missing) and included in the S3
            payload to verify the integrity of the uploaded file. This flag disables this behavoir.
        store_sha:
            Store the SHA256 checksum generated as part of the upload process in Grist. Use --no-store-sha to not save
            to Grist.
        verify_sha:
            Retrieve SHA256 checksum from Grist and verify local file before attempting to upload.
        threshold_mb:
            File size above which multipart upload will be used.
        chunk_mb:
            Size of multipart chunks.
        concurrency:
            Maximum number of simultaneous uploads.
        storage_class:
            AWS S3 storage class to which the uploaded file(s) should be assigned.
    """

    threshold = threshold_mb * 1024 * 1024
    chunk = chunk_mb * 1024 * 1024

    if not s3_bucket:
        logger.error("No bucket provided in config file")
        exit(1)

    for file in files:
        file = Path(file)
        if not path.exists(file):
            logger.error(f"File {file} does not exist")
            continue

        identifier = file.name

        if not skip_checksum:
            records = get_from_grist('di', identifier)
            if len(records) == 1 and records[0]['fields']['SHA256']:
                expected_sha = records[0]['fields']['SHA256']
                sha_just_calculated = False
            else:
                expected_sha = sha256(file)
                sha_just_calculated = True
                if store_sha:
                    put_to_grist(identifier, {"SHA256": expected_sha}, yes=True)

            if verify_sha:
                if not sha_just_calculated:
                    local = sha256(file)
                    if local != expected_sha:
                        logger.error(f"File {file} has local SHA256 checksum mismatch")
                        continue
        else:
            expected_sha = None

        resp, head, status = upload_s3(bucket=s3_bucket, path=str(file.resolve()), key=identifier,
                                       expected_checksum_hex=expected_sha, storage_class=storage_class,
                                       threshold=threshold, part_size=chunk, concurrency=concurrency)
        if status is None:
            logger.error(f"File {file} had checksum mismatch on S3 after upload. File was deleted on S3.")
            continue
        else:
            put_to_grist(identifier, {"uploaded_to_S3": True}, yes=True)

        # TODO clean up

        # results are in
        #     "s3_checksum_sha256": head.get("ChecksumSHA256", ""),
        #     "etag": head.get("ETag", ""),
        #     "storage_class": head.get("StorageClass", ""),


@app.command
def mp3(*infile: Annotated[str, Parameter(required=True)], outfile: str | None = None,
        vbr_level: Literal[0, 1, 2, 3, 4, 5, 6, 7, 8, 9] | None = 7,
        cbr: Literal[32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320] | None = None):
    """Generate MP3 access file and (optionally) upload metadata as a new Digital Instantiation in Grist.

        Parameters
        ----------
        infile:
            Input WAV file(s) to be converted to MP3
        outfile:
            Output filename to save the MP3 to. Can only be used if there is only one input file. By default, the
            output filename will be the original file name with '.wav' changed to '.mp3'
        vbr_level:
            The MP3 VBR encoding level. 'vbr_level' and 'cbr' cannot both be specified.
        cbr:
            The MP3 bitrate for Constant Bit Rate encoding. 'vbr_level' and 'cbr' cannot both be specified.

    """

    if outfile is not None and len(infile) > 1:
        logger.error("Can only have one input file if output file is specified.")
        exit(1)
    if vbr_level and cbr:
        logger.error("vbr-level and cbr cannot both be specified.")
        exit(1)
    if vbr_level is None and cbr is None:
        logger.error("Either vbr_level or cbr must be specified.")

    for input_file in infile:
        input_file = Path(input_file)

        if outfile is None:
            outfile = input_file.stem + '.mp3'

        metadata = get_bwf_core(input_file)
        metadata.update(get_xmp(input_file))

        ffmpeg_command = ["ffmpeg", "-y",
                          "-i", str(input_file.resolve()),
                          "-c:a", "libmp3lame",
                          ]
        if cbr:
            ffmpeg_command.extend(["-b:a", f"{cbr}k"])
        else:
            ffmpeg_command.extend(["-q:a", str(vbr_level)])

        # TODO add ID3v2 metadata

        ffmpeg_command.extend(["-id3v2_version", "3"])
        ffmpeg_command.append(str(input_file.parent / outfile))

        subprocess.run(ffmpeg_command, check=True)

    # for ID3 tags:

    # ffmpeg -i input.wav -c:a libmp3lame -q:a 2 \
    #   -metadata TIT1="My Grouping" \
    #   output.mp3


@app.command
def csv(*files: Annotated[str, Parameter(required=True)], verify_digest=False, outfile=""):
    """Extract BWF metadata to a CSV file.

        Parameters
        ----------
        files:
            One or more files to upload.
        verify_digest:
            Verify the MD5 digest of the audio data chunk.
        outfile:
            Name of the CSV output file. Use "" to output to STDOUT.
    """

    output_fields = ["filename", "OriginalFilename", "FileContent", "FileUse", "INAM", "ICRD", "form", "Duration",
                     "language", "ISRC", "creator", "xmp_description", "interviewer", "interviewee", "host", "speaker",
                     "performer", "topics", "names", "events", "places", "owner", "ICOP", "ICMT", "MD5Stored",
                     "OriginationDate", "OriginationTime"]

    if verify_digest:
        output_fields.extend(["MD5Generated", "Errors"])

    if outfile:
        if path.isfile(outfile):
            # if file exists, assume that it is a pre-existing CSV output file generated by 'bwftool csv' and append
            # rows without generating a header
            output = csvmod.DictWriter(open(outfile, 'a'), output_fields)
        else:
            # otherwise, create new file and generate header
            output = csvmod.DictWriter(open(outfile, 'w'), output_fields)
            output.writeheader()
    else:
        output = csvmod.DictWriter(sys.stdout, output_fields)
        output.writeheader()

    for infile in files:
        try:
            metadata = get_bwf_core(infile)
            metadata["filename"] = infile
            if verify_digest:
                metadata.update(get_bwf_tech(infile, verify_digest=True))
            else:
                metadata.update(get_bwf_tech(infile))
            metadata.update(get_xmp(infile))
            output.writerow({k: metadata[k] for k in output_fields})
        except xml.etree.ElementTree.ParseError:
            print("while parsing {}".format(infile))
            raise


@app.command
def splice():
    """Generate a derivative WAV file from an EDL and (optionally) upload metadata as a Digital Instantiation in Grist.

       Parameters
       ----------
    """
    logger.warning("Not yet implemented")


@app.command
def validate(*files: str, quiet=False):
    """Verify that the audio chunk MD5 digest for fixity.

        Parameters
        ----------
        files: str
            Audio files to verify MD5 digest for fixity.
        quiet: bool
            Suppress messages about successful validation.
    """

    for infile in files:
        infile = Path(infile)
        try:
            metadata = get_bwf_tech(infile, verify_digest=True)
        except subprocess.CalledProcessError:
            logger.error(f'BWF file {infile} could not be opened or is not a WAV file')
            continue

        if metadata is None:
            logger.error(f'{infile} does not have BWF metadata or failed validation ')
            # TODO can we disentangle these?
            continue

        if metadata['MD5Stored'] == "":
            logger.warning(f'{infile} does not have a MD5 stored value')
            continue


def main():
    app()


if __name__ == "__main__":
    main()