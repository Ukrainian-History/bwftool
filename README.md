# bwftool
## A CLI tool for working with Broadcast Wave files

This tool is meant to be a partial replacement and extension of [the CLI tools in `autoBWF`](https://autobwf.readthedocs.io/en/release/splicelame.html).

It is being tested in a production situation, but is not completely ready for general use.

Not all tools are implemented yet.

## Table of Contents

- [`di`](#bwftool-di)
- [`s3upload`](#bwftool-s3upload)
- [`mp3`](#bwftool-mp3)
- [`csv`](#bwftool-csv)
- [`splice`](#bwftool-splice)
- [`validate`](#bwftool-validate)

**Commands**:

* [`csv`](#bwftool-csv): Extract BWF metadata to a CSV file.
* [`di`](#bwftool-di): Extract BWF metadata and create/update a Digital Instantiation in Grist.
* [`mp3`](#bwftool-mp3): Generate MP3 access file and (optionally) upload metadata as a new Digital Instantiation in Grist.
* [`s3upload`](#bwftool-s3upload): Upload file(s) to an S3 bucket. Bucket information must be in the bwftool config file, and AWS credentials for boto3 must be in the '~/.aws' directory.
* [`splice`](#bwftool-splice): Generate a derivative WAV file from an EDL and (optionally) upload metadata as a Digital Instantiation in Grist.
* [`validate`](#bwftool-validate): Verify that the audio chunk MD5 digest for fixity.

## bwftool di

```console
bwftool di [OPTIONS] [ARGS...]
```

Extract BWF metadata and create/update a Digital Instantiation in Grist.

**Arguments**:

* `FILES`: Path(s) to BWF file(s).

**Parameters**:

* `--file-digest`: Calculate the SHA256 digest of the entire WAV file and store result in the DI. Slow for large files!  *[default: False]*
* `--yes`: Answer 'yes' to all questions. May cause unintended overwriting of DI metadata in Grist.  *[default: False]*

## bwftool s3upload

```console
bwftool s3upload [OPTIONS] [ARGS...]
```

Upload file(s) to an S3 bucket. Bucket information must be in the bwftool config file, and AWS credentials for boto3 must be in the '~/.aws' directory.

**Arguments**:

* `FILES`: One or more files to upload.

**Parameters**:

* `--skip-checksum, --no-skip-checksum`: By default, a SHA256 checksum is retreived from Grist (or calculated if missing) and included in the S3
    payload to verify the integrity of the uploaded file. This flag disables this behavoir.  *[default: False]*
* `--store-sha, --no-store-sha`: Store the SHA256 checksum generated as part of the upload process in Grist. Use --no-store-sha to not save
    to Grist.  *[default: True]*
* `--verify-sha, --no-verify-sha`: Retrieve SHA256 checksum from Grist and verify local file before attempting to upload.  *[default: False]*
* `--threshold-mb`: File size above which multipart upload will be used.  *[default: 100]*
* `--chunk-mb`: Size of multipart chunks.  *[default: 10]*
* `--concurrency`: Maximum number of simultaneous uploads.  *[default: 8]*
* `--storage-class`: AWS S3 storage class to which the uploaded file(s) should be assigned.  *[choices: STANDARD, INTELLIGENT_TIERING, STANDARD_IA, ONEZONE_IA, GLACIER_IR, GLACIER, DEEP_ARCHIVE]*  *[default: DEEP_ARCHIVE]*

## bwftool mp3

```console
bwftool mp3
```

Generate MP3 access file and (optionally) upload metadata as a new Digital Instantiation in Grist.

Parameters
----------

## bwftool csv

```console
bwftool csv
```

Extract BWF metadata to a CSV file.

Parameters
----------

## bwftool splice

```console
bwftool splice
```

Generate a derivative WAV file from an EDL and (optionally) upload metadata as a Digital Instantiation in Grist.

Parameters
----------

## bwftool validate

```console
bwftool validate [OPTIONS] [ARGS...]
```

Verify that the audio chunk MD5 digest for fixity.

**Arguments**:

* `FILES`: Audio files to verify MD5 digest for fixity.

**Parameters**:

* `--quiet`: Suppress messages about successful validation.  *[default: False]*
