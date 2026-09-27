"""
Unit tests for terrain.py (DEM construction, slope, D8 flow accumulation).

CSD: Testing Strategy + Algorithms and Complexity (these tests pin down
the *correctness* of the flow-accumulation algorithm on a small, hand-
verifiable grid, which is exactly what you want covered before trusting
it on a real, much larger DEM).
"""

import numpy as np
import pytest

from src.analysis.contour_parser import ContourSample
from src.analysis.terrain import (
    DEM,
    build_dem,
    compute_flow_accumulation,
    compute_invalid_mask,
    compute_slope_percent,
)


def test_build_dem_interpolates_a_simple_plane():
    # A gently tilted plane: elevation increases 1m per 0.001 deg latitude.
    samples = [
        ContourSample(lon=77.100, lat=21.200, elevation=100.0),
        ContourSample(lon=77.110, lat=21.200, elevation=100.0),
        ContourSample(lon=77.100, lat=21.205, elevation=105.0),
        ContourSample(lon=77.110, lat=21.205, elevation=105.0),
    ]
    dem = build_dem(samples, cell_size=5.0)
    assert isinstance(dem, DEM)
    assert dem.z.shape[0] > 0 and dem.z.shape[1] > 0
    # Interior of the grid should have real (non-NaN) elevations.
    assert not np.isnan(dem.z[dem.z.shape[0] // 2, dem.z.shape[1] // 2])


def test_slope_is_zero_on_a_perfectly_flat_grid():
    flat = np.full((5, 5), 42.0)
    dem = DEM(x=np.arange(5), y=np.arange(5), z=flat, cell_size=1.0,
              transformer_to_lonlat=None, transformer_to_utm=None, utm_crs=None)
    slope = compute_slope_percent(dem)
    assert np.allclose(slope, 0.0)


def test_invalid_mask_flags_nan_elevations():
    z = np.array([[1.0, 2.0], [np.nan, 4.0]])
    dem = DEM(x=np.arange(2), y=np.arange(2), z=z, cell_size=1.0,
              transformer_to_lonlat=None, transformer_to_utm=None, utm_crs=None)
    slope = compute_slope_percent(dem)
    invalid = compute_invalid_mask(dem, slope)
    assert invalid[1, 0]  # the NaN cell itself


def test_flow_accumulation_drains_toward_a_single_low_point():
    # A simple 3x3 bowl: the center cell is the lowest point, so every
    # other cell's flow should eventually accumulate there.
    z = np.array([
        [3.0, 3.0, 3.0],
        [3.0, 0.0, 3.0],
        [3.0, 3.0, 3.0],
    ])
    dem = DEM(x=np.arange(3), y=np.arange(3), z=z, cell_size=1.0,
              transformer_to_lonlat=None, transformer_to_utm=None, utm_crs=None)
    invalid = np.zeros_like(z, dtype=bool)
    accumulation = compute_flow_accumulation(dem, invalid)
    center = accumulation[1, 1]
    # The center must have accumulated flow from all 8 neighbors + itself.
    assert center == pytest.approx(9.0)
    # No other cell can have more accumulation than the lowest point.
    assert center == accumulation.max()
