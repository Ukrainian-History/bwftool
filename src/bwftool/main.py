from cyclopts import App
from loguru import logger

app = App(help="CLI tool for working with Broadcast Wav files.")


@app.command
def di():
    """Extract BWF metadata and create/update a Digital Instantiation in Grist.

       Parameters
       ----------
    """
    logger.warning("Not yet implemented")


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