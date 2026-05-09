"""Perform IO on BWF files.

Convenience functions for reading from and writing to BWF files using bwfmetaedit subprocess calls.

Attributes:
    bwfmetaedit (list): List of strings to be passed to subprocess.run(). This list should be appended to (after
        copy()-ing) in order to perform the needed function. Its primary role is to keep track of whether
        the "--accept-nopadding" option is or is not to be used. It may be modified by other modules
        (such as autoBWF.py) that import this module.

    namespaces (dict): Dict of XMP namespace URIs
"""

import subprocess
import io
import csv
import re
import os
import xml.etree.ElementTree as ET

bwfmetaedit = ["bwfmetaedit", "--specialchars"]

namespaces = {'dc': 'http://purl.org/dc/elements/1.1/',
              'xmp': 'http://ns.adobe.com/xap/1.0/',
              'xmpRights': "http://ns.adobe.com/xap/1.0/rights/",
              'xmpDM': "http://ns.adobe.com/xmp/1.0/DynamicMedia/",
              'autoBWF': "http://ns.ukrhec.org/autoBWF/0.1",
              'rdf': "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
              'x': "adobe:ns:meta/",
              "xml": "http://www.w3.org/XML/1998/namespace"}


def get_bwf_tech(file, verify_digest=False):
    """Runs bwfmetaedit to extract BWF technical metadata from a BWF file.

    Args:
        file (str | Path): The name of the target BWF file.
        verify_digest (bool): If True, add "--MD5-verify" to the bwfmetaedit call.

    Returns:
        dict: Metadata values indexed by the field name. If field is empty, the value is an empty string.
    """

    import io
    import csv

    command = bwfmetaedit.copy()
    command.append("--out-tech")
    if verify_digest:
        command.extend(["--MD5-verify", file])
    else:
        command.append(file)

    try:
        tech_csv = subprocess.check_output(command, universal_newlines=True)
    except subprocess.CalledProcessError:
        return None

    f = io.StringIO(tech_csv)
    reader = csv.DictReader(f, delimiter=',')
    md = next(reader)

    if md["Errors"] == "":
        return md
    else:
        return None


def parse_bwf_description(description):
    """Parses a BWF Description string based on a hard-coded pre-defined convention.

    Args:
        description (str): The BWF Description string.

    Returns:
        dict: Metadata values indexed by the field name. If field is empty, the value is an empty string.
    """

    md = {}

    m = re.compile(r'File content: (.+); File use: (.+); Original filename: (.+)').match(description)
    if m:
        matches = m.groups()
        md["FileContent"] = matches[0]
        md["FileUse"] = matches[1]
        md["OriginalFilename"] = matches[2]
    else:
        md["FileContent"] = ""
        md["FileUse"] = ""
        md["OriginalFilename"] = ""

    return md


def get_bwf_core(file):
    """Runs bwfmetaedit to extract BWF core metadata from a BWF file.

    Args:
        file (str | Path): The name of the target BWF file.

    Returns:
        dict: Metadata values indexed by the field name. If field is empty, the value is an empty string.
    """

    command = bwfmetaedit.copy()
    command.extend(["--out-core", file])

    core_csv = subprocess.check_output(command, universal_newlines=True)
    f = io.StringIO(core_csv)
    reader = csv.DictReader(f, delimiter=',')
    core = next(reader)
    for key in core.keys():
        if core[key] is None:
            core[key] = ""

    core.update(parse_bwf_description(core["Description"]))
    return core


def get_xmp(filename):
    """Runs bwfmetaedit to extract XMP metadata from a BWF file. This is to support files created using the legacy
    UHEC workflow that embedded descriptive metadata in the BWF file itself.

    Args:
        filename (str | Path): The name of the target BWF file.

    Returns:
        dict:  Dict of metadata values indexed by the field name. If field is empty, the value is an empty string.
    """

    command = bwfmetaedit.copy()
    command.extend(["--out-XMP-xml", filename])
    subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    outfile = str(filename) + ".XMP.xml"
    try:
        tree = ET.parse(outfile)
    except FileNotFoundError:
        md = {"interviewer": "", "interviewee": "", "owner": "",
              "metadataDate": "", "language": "", "xmp_description": "",
              "form": "", "host": "", "speaker": "", "performer": "",
              "topics": "", "names": "", "events": "", "places": "", "creator": ""
              }
        return md
    root = tree.getroot()

    def check_li_child(element, xpath):
        """Provides backwards compatibility for XMP saved using exempi and python-metadata-toolkit"""
        node = element.find(xpath + "//rdf:li", namespaces)
        if node is not None:
            return node
        else:
            return element.find(xpath, namespaces)

    md = {
        "owner": check_li_child(root, './/xmpRights:Owner'),
        "metadataDate": root.find('.//xmp:MetadataDate', namespaces),
        "language": root.findall('.//dc:language//rdf:li', namespaces),
        "xmp_description": check_li_child(root, './/dc:description'),
        "interviewer": check_li_child(root, './/autoBWF:Interviewer'),
        "interviewee": check_li_child(root, './/autoBWF:Interviewee'),
        "form": check_li_child(root, './/autoBWF:Form'),
        "host": check_li_child(root, './/autoBWF:Host'),
        "speaker": check_li_child(root, './/autoBWF:Speaker'),
        "performer": check_li_child(root, './/autoBWF:Performer'),
        "topics": check_li_child(root, './/autoBWF:Topics'),
        "names": check_li_child(root, './/autoBWF:Names'),
        "events": check_li_child(root, './/autoBWF:Events'),
        "places": check_li_child(root, './/autoBWF:Places'),
        "creator": check_li_child(root, './/dc:creator'),
    }

    for field in md:
        if md[field] is not None:
            if field == "language":
                md[field] = ";".join([node.text for node in md[field]])
            else:
                md[field] = md[field].text
        else:
            md[field] = ""

    os.remove(outfile)
    return md


if __name__ == "__main__":
    pass
