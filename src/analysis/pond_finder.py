"""
pond_finder.py
--------------
Searches the DEM for candidate pond sites of a given footprint (default
10m x 10m) and ranks them by estimated catchment (upstream contributing
area from D8 flow accumulation), subject to a strict flatness/slope
constraint.

Optimization notes (why this is fast on a ~1M-cell grid):
  1. A cheap, whole-grid slope mask is computed once and reused to reject
     steep terrain -- this doubles as our "avoid gullies / incised channels"
     filter, since we have no separate river layer to consult (see
     contour_parser.py docstring).
  2. The flat-window search uses scipy.ndimage min/max filters, which are
     vectorized C implementations -- no per-window Python loop over the
     ~1M candidate positions.
  3. Flow accumulation (the expensive O(n) hydrology step) is computed once
     on the masked grid, not per-candidate.
  4. Only the final top-N surviving candidates get their exact geometry /
     stats computed (cheap, since N is small).
"""
from dataclasses import dataclass

import numpy as np
from scipy import ndimage

from .terrain import DEM

@dataclass
class PondCandidate:
    center_lon: float
    center_lat: float
    corner_lonlat: list
    footprint_m: float
    min_elevation_m: float
    max_elevation_m: float
    elevation_range_m: float
    mean_slope_percent: float
    catchment_area_m2: float
    catchment_area_hectares: float
    catchment_cell_count: float

def find_pond_candidates(
    dem: DEM,
    slope: np.ndarray,
    flow_accumulation: np.ndarray,
    footprint_m: float = 10.0,
    mask_slope_threshold_percent: float = 8.0,
    flatness_max_range_m: float = 0.3,
    window_mean_slope_max_percent: float = 5.0,
    top_n: int = 5,
) -> list[PondCandidate]:
    window_cells = max(1, round(footprint_m / dem.cell_size))
    if window_cells % 2 == 0:
        window_cells += 1
    actual_footprint_m = window_cells * dem.cell_size
    half = window_cells

    z = dem.z

    invalid = np.isnan(z) | np.isnan(slope)

    steep_or_invalid = invalid | (slope > mask_slope_threshold_percent)

    z_for_min = np.where(invalid, np.inf, z)
    z_for_max = np.where(invalid, -np.inf, z)
    local_min = ndimage.minimum_filter(
        z_for_min, size=window_cells, mode="constant", cval=np.inf
    )
    local_max = ndimage.maximum_filter(
        z_for_max, size=window_cells, mode="constant", cval=-np.inf
    )
    elevation_range = local_max - local_min

    bad_presence = ndimage.maximum_filter(
        steep_or_invalid.astype(np.float32), size=window_cells,
        mode="constant", cval=1.0,
    ) > 0

    slope_for_mean = np.where(invalid, 0.0, slope)
    window_mean_slope = ndimage.uniform_filter(
        slope_for_mean, size=window_cells, mode="constant", cval=0.0
    )

    acc_for_max = np.where(invalid, -np.inf, flow_accumulation)
    window_catchment_cells = ndimage.maximum_filter(
        acc_for_max, size=window_cells, mode="constant", cval=-np.inf
    )

    candidate_mask = (
        (~bad_presence)
        & (elevation_range <= flatness_max_range_m)
        & (window_mean_slope <= window_mean_slope_max_percent)
    )

    candidate_mask[:half, :] = False
    candidate_mask[-half:, :] = False
    candidate_mask[:, :half] = False
    candidate_mask[:, -half:] = False

    if not np.any(candidate_mask):
        return []

    rows, cols = np.where(candidate_mask)
    scores = window_catchment_cells[rows, cols]
    ranking = np.argsort(-scores)

    min_separation_cells = window_cells * 1.5
    selected: list[tuple[int, int]] = []
    for idx in ranking:
        r, c = int(rows[idx]), int(cols[idx])
        if all(
            np.hypot(r - sr, c - sc) >= min_separation_cells
            for sr, sc in selected
        ):
            selected.append((r, c))
        if len(selected) >= top_n:
            break

    candidates: list[PondCandidate] = []
    for r, c in selected:
        r0, r1 = r - half, r + half + 1
        c0, c1 = c - half, c + half + 1
        window_z = dem.z[r0:r1, c0:c1]
        window_slope = slope[r0:r1, c0:c1]

        x0, x1 = dem.x[c0], dem.x[c1 - 1] + dem.cell_size
        y0, y1 = dem.y[r0], dem.y[r1 - 1] + dem.cell_size
        cx, cy = dem.x[c], dem.y[r]

        corner_xy = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
        corner_lonlat = [
            tuple(round(v, 7) for v in dem.transformer_to_lonlat.transform(px, py))
            for px, py in corner_xy
        ]
        center_lon, center_lat = dem.transformer_to_lonlat.transform(cx, cy)

        catchment_cells = float(window_catchment_cells[r, c])
        cell_area = dem.cell_size ** 2

        candidates.append(PondCandidate(
            center_lon=round(float(center_lon), 7),
            center_lat=round(float(center_lat), 7),
            corner_lonlat=[(round(lo, 7), round(la, 7)) for lo, la in corner_lonlat],
            footprint_m=actual_footprint_m,
            min_elevation_m=round(float(np.min(window_z)), 3),
            max_elevation_m=round(float(np.max(window_z)), 3),
            elevation_range_m=round(float(np.max(window_z) - np.min(window_z)), 3),
            mean_slope_percent=round(float(np.mean(window_slope)), 3),
            catchment_area_m2=round(catchment_cells * cell_area, 1),
            catchment_area_hectares=round(catchment_cells * cell_area / 10000.0, 4),
            catchment_cell_count=catchment_cells,
        ))

    return candidates
