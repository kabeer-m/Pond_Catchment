"""
Unit tests for pond_finder.py.

CSD: Testing Strategy. Builds a small synthetic DEM/slope/flow-
accumulation triple directly (bypassing terrain.py's interpolation) so
the candidate-search logic itself -- flatness filtering, slope masking,
minimum-separation de-duplication -- is tested in isolation.
"""

import numpy as np

from src.analysis.terrain import DEM
from src.analysis.pond_finder import find_pond_candidates


def _flat_dem(size=21, cell_size=1.0):
    z = np.zeros((size, size))
    return DEM(x=np.arange(size, dtype=float), y=np.arange(size, dtype=float),
               z=z, cell_size=cell_size, transformer_to_lonlat=_IdentityTransformer(),
               transformer_to_utm=None, utm_crs=_FakeCRS())


class _IdentityTransformer:
    def transform(self, x, y):
        return x, y


class _FakeCRS:
    def to_string(self):
        return "FAKE:0000"


def test_finds_candidates_on_a_flat_low_slope_grid():
    dem = _flat_dem()
    slope = np.zeros_like(dem.z)
    flow_accumulation = np.ones_like(dem.z)

    candidates = find_pond_candidates(
        dem, slope, flow_accumulation,
        footprint_m=5.0, mask_slope_threshold_percent=8.0,
        flatness_max_range_m=0.5, window_mean_slope_max_percent=5.0,
        top_n=3,
    )
    assert len(candidates) > 0
    assert all(c.mean_slope_percent == 0.0 for c in candidates)


def test_rejects_all_candidates_when_terrain_is_too_steep():
    dem = _flat_dem()
    slope = np.full_like(dem.z, 20.0)  # well above any reasonable threshold
    flow_accumulation = np.ones_like(dem.z)

    candidates = find_pond_candidates(
        dem, slope, flow_accumulation,
        footprint_m=5.0, mask_slope_threshold_percent=8.0,
        flatness_max_range_m=0.5, window_mean_slope_max_percent=5.0,
        top_n=3,
    )
    assert candidates == []


def test_candidates_are_spatially_separated():
    dem = _flat_dem(size=41)
    slope = np.zeros_like(dem.z)
    # Two separated high-accumulation "hotspots" competing for rank.
    flow_accumulation = np.ones_like(dem.z)
    flow_accumulation[10, 10] = 1000
    flow_accumulation[30, 30] = 900

    candidates = find_pond_candidates(
        dem, slope, flow_accumulation,
        footprint_m=3.0, mask_slope_threshold_percent=8.0,
        flatness_max_range_m=0.5, window_mean_slope_max_percent=5.0,
        top_n=5,
    )
    centers = [(c.center_lon, c.center_lat) for c in candidates]
    assert len(centers) == len(set(centers))  # no duplicate/overlapping picks
