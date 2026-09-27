"""
parsers.py
----------
Factory that maps an uploaded file's extension to the function that
knows how to turn it into a list of ContourSample points.

Design pattern (CSD: Design Patterns -- Factory):
Today there is exactly one input format (KML/KMZ, handled by
contour_parser.parse_contours). The assignment brief and real village
surveys already hint at more formats arriving later (GeoJSON contour
exports, raw GPS point CSVs, a different vendor's proprietary export).
Rather than growing a chain of "if ext == '.kml': ... elif ext == '.csv':
..." inside app.py, app.py asks this factory for "the parser for this
extension" and calls it uniformly. Adding a format means writing one
function with the ContourSample-list signature and adding one line to
_PARSERS -- app.py and contour_parser.py do not change.
"""

from contour_parser import ContourSample, parse_contours

ParserFunc = "Callable[[bytes, str], list[ContourSample]]"


def _parse_kml_or_kmz(file_bytes: bytes, filename: str) -> list[ContourSample]:
    return parse_contours(file_bytes, filename)


# Extend this table (and add the function above it) to support a new
# input format without touching app.py or contour_parser.py.
_PARSERS = {
    ".kml": _parse_kml_or_kmz,
    ".kmz": _parse_kml_or_kmz,
}

SUPPORTED_EXTENSIONS = frozenset(_PARSERS)


def get_parser(extension: str):
    """Return the parser function registered for this file extension."""
    try:
        return _PARSERS[extension.lower()]
    except KeyError:
        supported = ", ".join(sorted(SUPPORTED_EXTENSIONS))
        raise ValueError(
            f"Unsupported file type '{extension}'. Expected one of: {supported}."
        )
