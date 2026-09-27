"""
Unit tests for contour_parser.py.

CSD: Testing Strategy. Uses a tiny hand-built KML string (two elevation-
labeled LineStrings) instead of a real survey file, so the test is fast,
deterministic, and doesn't depend on any fixture file on disk.
"""

import pytest

from contour_parser import parse_contours

SAMPLE_KML = b"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <Placemark>
      <name>100</name>
      <LineString>
        <coordinates>
          77.10,21.20,0 77.11,21.21,0 77.12,21.20,0
        </coordinates>
      </LineString>
    </Placemark>
    <Placemark>
      <name>105</name>
      <LineString>
        <coordinates>
          77.10,21.22,0 77.11,21.23,0
        </coordinates>
      </LineString>
    </Placemark>
    <Placemark>
      <name>Not a contour</name>
      <Point>
        <coordinates>77.10,21.20,0</coordinates>
      </Point>
    </Placemark>
  </Document>
</kml>
"""


def test_parses_all_vertices_from_elevation_labeled_linestrings():
    samples = parse_contours(SAMPLE_KML, "village.kml")
    assert len(samples) == 5  # 3 vertices + 2 vertices
    elevations = {s.elevation for s in samples}
    assert elevations == {100.0, 105.0}


def test_skips_non_numeric_named_placemarks():
    samples = parse_contours(SAMPLE_KML, "village.kml")
    # The Point placemark named "Not a contour" must not leak into results.
    assert all(s.elevation in (100.0, 105.0) for s in samples)


def test_raises_on_file_with_no_valid_contours():
    empty_kml = b"""<?xml version="1.0"?>
    <kml xmlns="http://www.opengis.net/kml/2.2"><Document/></kml>"""
    with pytest.raises(ValueError):
        parse_contours(empty_kml, "empty.kml")


def test_unzips_kmz_wrapper():
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("doc.kml", SAMPLE_KML)
    kmz_bytes = buf.getvalue()

    samples = parse_contours(kmz_bytes, "village.kmz")
    assert len(samples) == 5
