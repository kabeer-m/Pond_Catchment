"""
app.py
------
Flask backend exposing POST /analyzeContour (alias: /findCatchment).

Accepts a contour map (.kml or .kmz) as a multipart file upload, analyzes
the terrain, and returns ranked candidate pond sites with their estimated
catchment area.

Run:
    python3 app.py
    (listens on 0.0.0.0:5000)

Nothing in this file is specific to the sample map -- extent, resolution,
UTM zone, elevation range etc. are all derived from whatever file is
uploaded, and thresholds are exposed as optional request parameters so
future contour maps (different terrain, different scale) can be tuned
without code changes.
"""
import time
import traceback

from flask import Flask, jsonify, request

from contour_parser import parse_contours
from terrain import build_dem, compute_slope_percent, compute_flow_accumulation, compute_invalid_mask
from pond_finder import find_pond_candidates

app = Flask(__name__)

MAX_UPLOAD_BYTES = 25 * 1024 * 1024  # 25 MB
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_BYTES

ALLOWED_EXTENSIONS = {".kml", ".kmz"}


def _float_param(name, default):
    val = request.form.get(name) or request.args.get(name)
    return float(val) if val is not None else default


def _int_param(name, default):
    val = request.form.get(name) or request.args.get(name)
    return int(val) if val is not None else default


def _analyze():
    if "file" not in request.files:
        return jsonify(error="No file uploaded. Send it as multipart/form-data under the 'file' field."), 400

    upload = request.files["file"]
    filename = upload.filename or ""
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in ALLOWED_EXTENSIONS:
        return jsonify(error=f"Unsupported file type '{ext}'. Expected .kml or .kmz."), 400

    file_bytes = upload.read()
    if not file_bytes:
        return jsonify(error="Uploaded file is empty."), 400

    # Optional tuning parameters (all have sensible, non-map-specific defaults)
    pond_footprint_m = _float_param("pond_footprint_m", 10.0)
    cell_size_m = _float_param("cell_size_m", 2.0)
    mask_slope_threshold_percent = _float_param("mask_slope_threshold_percent", 8.0)
    flatness_max_range_m = _float_param("flatness_max_range_m", 0.3)
    window_mean_slope_max_percent = _float_param("window_mean_slope_max_percent", 5.0)
    top_n = _int_param("top_n", 5)

    t_start = time.time()
    try:
        samples = parse_contours(file_bytes, filename)
    except ValueError as e:
        return jsonify(error=str(e)), 422

    dem = build_dem(samples, cell_size=cell_size_m)
    slope = compute_slope_percent(dem)
    invalid = compute_invalid_mask(dem, slope)
    flow_invalid = invalid | (slope > mask_slope_threshold_percent)
    flow_accumulation = compute_flow_accumulation(dem, flow_invalid)

    candidates = find_pond_candidates(
        dem, slope, flow_accumulation,
        footprint_m=pond_footprint_m,
        mask_slope_threshold_percent=mask_slope_threshold_percent,
        flatness_max_range_m=flatness_max_range_m,
        window_mean_slope_max_percent=window_mean_slope_max_percent,
        top_n=top_n,
    )

    elevs = [s.elevation for s in samples]
    lons = [s.lon for s in samples]
    lats = [s.lat for s in samples]

    response = {
        "source_file": filename,
        "processing_time_seconds": round(time.time() - t_start, 2),
        "terrain_summary": {
            "elevation_min_m": min(elevs),
            "elevation_max_m": max(elevs),
            "contour_sample_count": len(samples),
            "bounding_box": {
                "min_lon": min(lons), "max_lon": max(lons),
                "min_lat": min(lats), "max_lat": max(lats),
            },
            "dem_grid_shape": list(dem.z.shape),
            "dem_cell_size_m": dem.cell_size,
            "utm_crs": dem.utm_crs.to_string(),
        },
        "analysis_parameters": {
            "pond_footprint_requested_m": pond_footprint_m,
            "mask_slope_threshold_percent": mask_slope_threshold_percent,
            "flatness_max_elevation_range_m": flatness_max_range_m,
            "window_mean_slope_max_percent": window_mean_slope_max_percent,
        },
        "candidate_count": len(candidates),
        "candidates": [
            {
                "rank": i + 1,
                "center": {"lon": c.center_lon, "lat": c.center_lat},
                "footprint_polygon_lonlat": c.corner_lonlat,
                "footprint_m": c.footprint_m,
                "elevation_min_m": c.min_elevation_m,
                "elevation_max_m": c.max_elevation_m,
                "elevation_range_m": c.elevation_range_m,
                "mean_slope_percent": c.mean_slope_percent,
                "catchment_area_m2": c.catchment_area_m2,
                "catchment_area_hectares": c.catchment_area_hectares,
                "assumed_pond_depth_m": 3.0,
                "assumed_pond_volume_m3": round(c.footprint_m * c.footprint_m * 3.0, 1),
            }
            for i, c in enumerate(candidates)
        ],
    }

    if not candidates:
        response["message"] = (
            "No site satisfied the flatness/slope constraints. Try relaxing "
            "flatness_max_range_m or window_mean_slope_max_percent."
        )

    return jsonify(response), 200


@app.route("/analyzeContour", methods=["POST"])
def analyze_contour():
    try:
        return _analyze()
    except Exception as e:
        app.logger.error(traceback.format_exc())
        return jsonify(error=f"Internal error: {e}"), 500


# Alias, per the assignment's suggested route names
@app.route("/findCatchment", methods=["POST"])
def find_catchment():
    return analyze_contour()


@app.route("/health", methods=["GET"])
def health():
    return jsonify(status="ok"), 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
