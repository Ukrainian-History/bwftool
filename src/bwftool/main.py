from pathlib import Path
import hashlib
import subprocess
from os import path
from datetime import datetime, timezone

from cyclopts import App
from loguru import logger
import requests
from glom import glom
import yaml
from rich.prompt import Confirm

from bwfIO import get_bwf_tech
from bwfIO import get_bwf_core

app = App(help="CLI tool for working with Broadcast Wav files.")


yaml_path = Path.home() / ".bwftool"

data = {}
if yaml_path.exists():
    with open(yaml_path, "r") as file:
        data = yaml.safe_load(file)
else:
    logger.info(f"YAML config file {yaml_path.absolute()} not found. Some functionality may be missing.")

doc_id = data.get("doc_id")
key = data.get("key")

if doc_id and key:
    grist_base_url = "https://docs.getgrist.com/api"
    grist_tables_url = f"{grist_base_url}/docs/{doc_id}/tables"
    grist_api_headers = {"Authorization": f"Bearer {key}"}
else:
    grist_base_url = None


def md5(path: Path, chunk_size: int = 8192) -> str:
    h = hashlib.md5()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(chunk_size), b""):
            h.update(chunk)
    return h.hexdigest()


def pretty_print(thing):
    for name, val in thing.items():
        print(f'{name:20} => {val}')


@app.command
def di(*files: str, file_digest = False, yes = False):
    """Extract BWF metadata and create/update a Digital Instantiation in Grist.

        Parameters
        ----------
        file_digest : bool, optional
            Calculate the MD5 digest of the entire WAV file and store result in the DI. Slow for large files!
        yes: bool, optional
            Answer 'yes' to all questions. May cause unintended overwriting of DI metadata in Grist.
        files: str
            Path(s) to BWF file(s).
    """

    if grist_base_url is None:
        logger.error("Grist table ID and/or key has not been provided")
        exit(1)

    full_field_mapping = {"OriginalFilename": "Digital_instantiation_identifier", "FileUse": "FileUse",
                     "Duration": "Duration",
                     "ICMT": "Digitization_comment", "MD5Stored": "MD5Stored", "OriginationDate": "OriginationDate",
                     "OriginationTime": "OriginationTime", "CodingHistory": "CodingHistory", "ITCH": "Technician",
                     "ISFT": "Creating_software", "Channels": "Channels", "SampleRate": "SampleRate",
                     "BitPerSample": "BitPerSample", "FileSize": "File_Size", "Description": "Description"}

    grist_out = requests.get(f"{grist_tables_url}/Digital_instantiations/columns", headers=grist_api_headers)
    if grist_out.status_code >= 400:
        logger.error(f'Grist API call failed. {grist_out.text}')
        exit(1)
    if grist_out.status_code != 200:
        logger.error(f'Grist API problem. {grist_out.text}')
        exit(1)

    grist_columns = glom(grist_out.json(), ('columns', ['id']))
    field_mapping = {key: value for key, value in full_field_mapping.items() if value in grist_columns}
    if len(field_mapping) < len(full_field_mapping):
        logger.info(f'Some columns for valid BWF data are missing in the Grist DI table')

    for infile in files:
        try:
            metadata = get_bwf_core(infile)
        except subprocess.CalledProcessError:
            logger.error(f'BWF file {infile} could not be opened')
            continue

        metadata["filename"] = infile  # Why??
        metadata.update(get_bwf_tech(infile))

        if metadata["OriginalFilename"] != "":
            if metadata["filename"] != metadata["OriginalFilename"]:
                logger.warning('Current (%s) and original (%s) filenames do not match',
                               infile, metadata["OriginalFilename"])

            identifier = metadata["OriginalFilename"]
        else:
            identifier = Path(metadata["filename"]).name
            metadata["OriginalFilename"] = identifier

        metadata["FileSize"] = path.getsize(infile)

        # remap BWFfileIO field names to Grist field names, and get rid of the unused ones
        metadata = {field_mapping[k]: metadata[k] for k in metadata.keys() if k in field_mapping.keys()}

        grist_records = requests.get(f"{grist_tables_url}/Digital_instantiations/records", headers=grist_api_headers,
                                     params={"filter": f'{{"Digital_instantiation_identifier": ["{identifier}"]}}'})
        records = grist_records.json()["records"]

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
            metadata["FileMD5"] = md5(infile)

        if len(records) == 0:
            logger.debug("creating new digital instantiation %s", identifier)
            grist_out = requests.post(f"{grist_tables_url}/Digital_instantiations/records", headers=grist_api_headers,
                                      json={"records": [{"fields": metadata}]})

            if grist_out.status_code == requests.codes.ok:
                logger.info("digital instantiation %s successfully created", identifier)
            elif grist_out.ok:
                logger.warning("digital instantiation creation returned a status > 200 but < 400")
            else:
                logger.error("digital instantiation %s could not be created", identifier)
                print(grist_out.text)
        elif len(records) > 1:
            message = ("the identifier %s has more than one digital instantiation record in Grist"
                       " -- this isn't supposed to happen")
            logger.error(message, identifier)
            continue
        else:
            grist_data = records[0]['fields']
            row_id = records[0]['id']
            logger.debug("updating digital instantiation %s, record id %d", identifier, row_id)

            differences = {k: metadata[k] for k in metadata.keys()
                           if metadata[k] != "" and grist_data[k] and metadata[k] != grist_data[k]}

            new_fields = {k: metadata[k] for k in metadata.keys()
                          if metadata[k] != "" and (grist_data[k] == "" or grist_data[k] is None)}

            if new_fields:
                print("the BWF file has the following fields that are not in Grist:")
                pretty_print(new_fields)
                if Confirm('Do you want to update the metadata in Grist?'):
                    grist_out = requests.patch(f"{grist_tables_url}/Digital_instantiations/records", headers=grist_api_headers,
                                               json={"records": [{"id": row_id, "fields": new_fields}]})

                    if grist_out.status_code == requests.codes.ok:
                        logger.info("digital instantiation %s successfully updated", identifier)
                    elif grist_out.ok:
                        logger.warning("digital instantiation update returned a status > 200 but < 400")
                    else:
                        logger.error("digital instantiation %s could not be updated", identifier)

            if differences:
                print("the following fields in the BWF file differ from those in Grist:")
                pretty_print(differences)
                if Confirm('Do you want to update the metadata in Grist?'):
                    grist_out = requests.patch(f"{grist_tables_url}/Digital_instantiations/records", headers=grist_api_headers,
                                               json={"records": [{"id": row_id, "fields": differences}]})

                    if grist_out.status_code == requests.codes.ok:
                        logger.info("digital instantiation %s successfully updated", identifier)
                    elif grist_out.ok:
                        logger.warning("digital instantiation update returned a status > 200 but < 400")
                    else:
                        logger.error("digital instantiation %s could not be updated", identifier)

            if not new_fields and not differences:
                print("the metadata in the BWF file match those in Grist")


@app.command
def mp3():
    """Generate MP3 access file and (optionally) upload metadata as a new Digital Instantiation in Grist.

       Parameters
       ----------
    """
    logger.warning("Not yet implemented")


@app.command
def csv():
    """Extract BWF metadata to a CSV file.

       Parameters
       ----------
    """
    logger.warning("Not yet implemented")


@app.command
def splice():
    """Generate a derivative WAV file from an EDL and (optionally) upload metadata as a Digital Instantiation in Grist.

       Parameters
       ----------
    """
    logger.warning("Not yet implemented")


@app.command
def validate():
    """Verify that the audio chunk (or file) MD5 digest for fixity.

       Parameters
       ----------
    """
    logger.warning("Not yet implemented")


if __name__ == "__main__":
    app()