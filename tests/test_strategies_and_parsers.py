"""
Unit tests for strategies.py (Strategy pattern) and parsers.py (Factory
pattern). CSD: Testing Strategy + Design Patterns.
"""

import pytest

from src.analysis.pond_finder import PondCandidate
from src.analysis.strategies import get_strategy
from src.analysis.parsers import get_parser, SUPPORTED_EXTENSIONS


def _candidate(catchment_area_m2, elevation_range_m):
    return PondCandidate(
        center_lon=0, center_lat=0, corner_lonlat=[], footprint_m=10.0,
        min_elevation_m=0, max_elevation_m=elevation_range_m,
        elevation_range_m=elevation_range_m, mean_slope_percent=0,
        catchment_area_m2=catchment_area_m2,
        catchment_area_hectares=catchment_area_m2 / 10000,
        catchment_cell_count=catchment_area_m2,
    )


def test_catchment_strategy_ranks_largest_area_first():
    candidates = [_candidate(100, 0.1), _candidate(500, 0.2), _candidate(300, 0.05)]
    ranked = get_strategy("catchment").rank(candidates)
    assert [c.catchment_area_m2 for c in ranked] == [500, 300, 100]


def test_flatness_strategy_ranks_smallest_range_first():
    candidates = [_candidate(100, 0.3), _candidate(500, 0.05), _candidate(300, 0.2)]
    ranked = get_strategy("flatness").rank(candidates)
    assert [c.elevation_range_m for c in ranked] == [0.05, 0.2, 0.3]


def test_unknown_strategy_name_raises():
    with pytest.raises(ValueError):
        get_strategy("not-a-real-strategy")


def test_default_strategy_is_catchment():
    strat = get_strategy(None)
    assert strat.name == "catchment"


def test_parser_factory_returns_kml_parser_for_known_extensions():
    for ext in SUPPORTED_EXTENSIONS:
        assert callable(get_parser(ext))


def test_parser_factory_raises_for_unknown_extension():
    with pytest.raises(ValueError):
        get_parser(".geojson")
