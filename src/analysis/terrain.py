"""
terrain.py
----------
Turns a scattered cloud of (lon, lat, elevation) contour-vertex samples into
a regular-grid DEM in metric coordinates, and derives slope + D8 flow
accumulation (a standard hydrology method for estimating, per cell, how much
upstream area drains through it -- i.e. its catchment).

Nothing here is specific to the sample map: the UTM zone, grid extent,
resolution and thresholds are all derived from the input data / request
parameters.
"""
from dataclasses import dataclass

import numpy as np
from pyproj import CRS, Transformer
from scipy.interpolate import LinearNDInterpolator

from .contour_parser import ContourSample

def _utm_crs_for(lon: float, lat: float) -> CRS:
    zone = int((lon + 180) / 6) + 1
    epsg = 32600 + zone if lat >= 0 else 32700 + zone
    return CRS.from_epsg(epsg)

@dataclass
class DEM:
    x: np.ndarray
    y: np.ndarray
    z: np.ndarray
    cell_size: float
    transformer_to_lonlat: Transformer
    transformer_to_utm: Transformer
    utm_crs: CRS

def build_dem(samples: list[ContourSample], cell_size: float = 3.0) -> DEM:
    """
    Reproject contour samples to UTM meters, then interpolate a regular-grid
    DEM using a Delaunay-triangulation-based linear interpolant (standard
    TIN -> raster conversion for elevation contour data).
    """
    lons = np.array([s.lon for s in samples])
    lats = np.array([s.lat for s in samples])
    elevs = np.array([s.elevation for s in samples])

    centroid_lon, centroid_lat = float(lons.mean()), float(lats.mean())
    utm_crs = _utm_crs_for(centroid_lon, centroid_lat)
    wgs84 = CRS.from_epsg(4326)

    to_utm = Transformer.from_crs(wgs84, utm_crs, always_xy=True)
    to_lonlat = Transformer.from_crs(utm_crs, wgs84, always_xy=True)

    xs, ys = to_utm.transform(lons, lats)

    x_min, x_max = xs.min(), xs.max()
    y_min, y_max = ys.min(), ys.max()

    grid_x = np.arange(x_min, x_max, cell_size)
    grid_y = np.arange(y_min, y_max, cell_size)
    gx, gy = np.meshgrid(grid_x, grid_y)

    interpolator = LinearNDInterpolator(list(zip(xs, ys)), elevs)
    gz = interpolator(gx, gy)

    return DEM(
        x=grid_x, y=grid_y, z=gz, cell_size=cell_size,
        transformer_to_lonlat=to_lonlat, transformer_to_utm=to_utm,
        utm_crs=utm_crs,
    )

def compute_slope_percent(dem: DEM) -> np.ndarray:
    """Slope magnitude in percent (rise/run * 100) at every cell."""
    dzdy, dzdx = np.gradient(dem.z, dem.cell_size, dem.cell_size)
    slope = np.sqrt(dzdx ** 2 + dzdy ** 2) * 100.0
    return slope

def compute_invalid_mask(dem: DEM, slope: np.ndarray) -> np.ndarray:
    """
    True for any cell that can't be trusted for analysis: no interpolated
    elevation (outside the contour data's convex hull), or no slope (the
    finite-difference gradient used for slope is also NaN on cells adjacent
    to that same hull boundary, not just on the NaN cells themselves).
    """
    return np.isnan(dem.z) | np.isnan(slope)

_NEIGHBORS = [
    (-1, -1, np.sqrt(2)), (-1, 0, 1.0), (-1, 1, np.sqrt(2)),
    (0, -1, 1.0),                       (0, 1, 1.0),
    (1, -1, np.sqrt(2)),  (1, 0, 1.0),  (1, 1, np.sqrt(2)),
]

def compute_flow_accumulation(dem: DEM, invalid_mask: np.ndarray) -> np.ndarray:
    """
    Standard D8 flow accumulation:
      1. Every cell drains to whichever of its 8 neighbors has the steepest
         downhill drop.
      2. Process cells from HIGHEST to LOWEST elevation, adding each cell's
         accumulated value to its downhill neighbor. Because flow only ever
         moves downhill (a DAG), by the time we reach a given cell every
         upstream cell that drains into it has already been added.

    Returns a grid where accumulation[r, c] = number of grid cells (including
    itself) whose runoff passes through cell (r, c). Multiply by cell area
    to get catchment / contributing area in square meters.

    invalid_mask: True for cells to exclude entirely (no DEM data, or masked
    out as too steep -- see pond_finder). Excluded cells neither accumulate
    flow nor receive it, so they don't distort catchment estimates for valid
    candidate sites.
    """
    z = dem.z
    rows, cols = z.shape
    accumulation = np.ones((rows, cols), dtype=np.float64)
    accumulation[invalid_mask] = 0.0

    valid = ~invalid_mask & ~np.isnan(z)
    z_filled = np.where(valid, z, np.nan)

    best_drop = np.zeros((rows, cols), dtype=np.float64)
    best_dr = np.zeros((rows, cols), dtype=np.int32)
    best_dc = np.zeros((rows, cols), dtype=np.int32)
    has_target = np.zeros((rows, cols), dtype=bool)

    padded = np.pad(z_filled, 1, mode="constant", constant_values=np.nan)
    padded_valid = np.pad(valid, 1, mode="constant", constant_values=False)

    for dr, dc, dist in _NEIGHBORS:
        neighbor_z = padded[1 + dr:1 + dr + rows, 1 + dc:1 + dc + cols]
        neighbor_valid = padded_valid[1 + dr:1 + dr + rows, 1 + dc:1 + dc + cols]
        drop = (z_filled - neighbor_z) / dist
        candidate = valid & neighbor_valid & (drop > best_drop)
        best_drop = np.where(candidate, drop, best_drop)
        best_dr = np.where(candidate, dr, best_dr)
        best_dc = np.where(candidate, dc, best_dc)
        has_target |= candidate

    rr, cc = np.meshgrid(np.arange(rows), np.arange(cols), indexing="ij")
    flow_to = np.full((rows, cols, 2), -1, dtype=np.int32)
    flow_to[..., 0] = np.where(has_target, rr + best_dr, -1)
    flow_to[..., 1] = np.where(has_target, cc + best_dc, -1)

    order = np.dstack(np.unravel_index(
        np.argsort(-np.where(valid, z, -np.inf), axis=None), z.shape
    ))[0]

    for r, c in order:
        if not valid[r, c]:
            continue
        tr, tc = flow_to[r, c]
        if tr >= 0:
            accumulation[tr, tc] += accumulation[r, c]

    accumulation[~valid] = np.nan
    return accumulation
