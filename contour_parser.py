"""
contour_parser.py
------------------
Parses a contour map file (.kml or .kmz) and extracts elevation-labeled
sample points from contour LineStrings.

Design note (generalization):
We deliberately do NOT rely on folder names like "lines" / "land" / "sources"
staying the same across different contour-generator outputs. Instead we walk
every <Placemark> in the document and keep the ones where:
    - it contains a <LineString> (a contour line, as opposed to a polygon
      bounding box or a point marker), AND
    - its <name> can be parsed as a number (the elevation value contour
      generators conventionally use to label each line).
This makes the parser tolerant of differently-structured KML exports from
other contour tools in future phases, as long as that naming convention
(elevation-as-name on a LineString) holds -- which is the de-facto standard
for contour-line KML/KMZ exports (Google Earth, QGIS, contour-generator
web tools, etc).
"""
import io
import re
import zipfile
from dataclasses import dataclass

from lxml import etree

KML_NS = "http://www.opengis.net/kml/2.2"
NSMAP = {"k": KML_NS}

_NUMERIC_RE = re.compile(r"^-?\d+(\.\d+)?$")

@dataclass
class ContourSample:
    lon: float
    lat: float
    elevation: float

def _strip_ns(tag: str) -> str:
    return tag.split("}", 1)[-1] if "}" in tag else tag

def load_kml_bytes(file_bytes: bytes, filename: str) -> bytes:
    """Return raw KML bytes, unzipping if the upload is a KMZ."""
    if filename.lower().endswith(".kmz") or file_bytes[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(file_bytes)) as zf:
            kml_names = [n for n in zf.namelist() if n.lower().endswith(".kml")]
            if not kml_names:
                raise ValueError("KMZ archive does not contain a .kml file")

            preferred = [n for n in kml_names if n.lower().endswith("doc.kml")]
            target = preferred[0] if preferred else kml_names[0]
            return zf.read(target)
    return file_bytes

def _find_name(placemark) -> str | None:
    for child in placemark:
        if _strip_ns(child.tag) == "name" and child.text:
            return child.text.strip()
    return None

def _find_linestring_coords(placemark) -> str | None:
    for el in placemark.iter():
        if _strip_ns(el.tag) == "coordinates":

            parent_tags = {_strip_ns(a.tag) for a in el.iterancestors()}
            if "LineString" in parent_tags:
                return el.text
    return None

def parse_contours(file_bytes: bytes, filename: str) -> list[ContourSample]:
    """
    Parse a KML/KMZ file and return a flat list of (lon, lat, elevation)
    sample points harvested from every vertex of every elevation-labeled
    contour LineString.
    """
    kml_bytes = load_kml_bytes(file_bytes, filename)

    parser = etree.XMLParser(recover=True, huge_tree=True)
    root = etree.fromstring(kml_bytes, parser=parser)

    samples: list[ContourSample] = []

    for placemark in root.iter():
        if _strip_ns(placemark.tag) != "Placemark":
            continue

        name = _find_name(placemark)
        if not name or not _NUMERIC_RE.match(name):
            continue

        coords_text = _find_linestring_coords(placemark)
        if not coords_text:
            continue

        elevation = float(name)
        for pair in coords_text.strip().split():
            parts = pair.split(",")
            if len(parts) < 2:
                continue
            lon, lat = float(parts[0]), float(parts[1])
            samples.append(ContourSample(lon=lon, lat=lat, elevation=elevation))

    if not samples:
        raise ValueError(
            "No elevation-labeled contour LineStrings found in this file. "
            "Expected Placemarks with a numeric <name> (the contour elevation) "
            "and a <LineString> geometry."
        )

    return samples
