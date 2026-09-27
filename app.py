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

New in this version (see each module's own docstring for the design
rationale): cache.py (result caching + indexed lookup), strategies.py
(pluggable candidate ranking), parsers.py (pluggable input formats),
jobs.py (non-blocking background analysis), auth.py (API-key gate on
the compute-heavy routes). Each concern stays in its own module; this
file only wires them together.
"""

import time
import traceback

from flask import Flask, jsonify, request, render_template

from src.services import cache, jobs
from src.services.auth import require_api_key
from src.analysis.parsers import get_parser
from src.analysis.strategies import get_strategy
from src.analysis.terrain import (
    build_dem, compute_slope_percent, compute_flow_accumulation, compute_invalid_mask,
)
from src.analysis.pond_finder import find_pond_candidates

app = Flask(__name__)


@app.route("/")
def index():
    return render_template("index.html")


MAX_UPLOAD_BYTES = 25 * 1024 * 1024  # 25 MB
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_BYTES


def _float_param(name, default):
    val = request.form.get(name) or request.args.get(name)
    return float(val) if val is not None else default


def _int_param(name, default):
    val = request.form.get(name) or request.args.get(name)
    return int(val) if val is not None else default


def _str_param(name, default):
    val = request.form.get(name) or request.args.get(name)
    return val if val is not None else default


def run_analysis(file_bytes: bytes, filename: str, params: dict) -> dict:
    """
    Pure compute pipeline: contour bytes + params in, JSON-serializable
    result dict out. No Flask `request`/`jsonify` inside, so this same
    function can be called synchronously, from a background job
    (jobs.py), or from a test -- without a Flask app/request context.
    """
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    parser = get_parser(ext)  # raises ValueError for unsupported extensions
    samples = parser(file_bytes, filename)

    pond_footprint_m = params["pond_footprint_m"]
    cell_size_m = params["cell_size_m"]
    mask_slope_threshold_percent = params["mask_slope_threshold_percent"]
    flatness_max_range_m = params["flatness_max_range_m"]
    window_mean_slope_max_percent = params["window_mean_slope_max_percent"]
    top_n = params["top_n"]
    ranking = params["ranking"]

    t_start = time.time()

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
    candidates = get_strategy(ranking).rank(candidates)

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
            "ranking_strategy": ranking,
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
    return response


def _collect_params() -> dict:
    return {
        "pond_footprint_m": _float_param("pond_footprint_m", 10.0),
        "cell_size_m": _float_param("cell_size_m", 2.0),
        "mask_slope_threshold_percent": _float_param("mask_slope_threshold_percent", 8.0),
        "flatness_max_range_m": _float_param("flatness_max_range_m", 0.3),
        "window_mean_slope_max_percent": _float_param("window_mean_slope_max_percent", 5.0),
        "top_n": _int_param("top_n", 5),
        "ranking": _str_param("ranking", "catchment"),
    }


def _read_upload():
    """Validate + read the multipart upload. Returns (file_bytes, filename) or a Flask error response."""
    upload = request.files.get("contour_map") or request.files.get("file")
    if upload is None and request.files:
        upload = next(iter(request.files.values()))

    if upload is None:
        return None, (jsonify(
            error="No file uploaded. Send it as multipart/form-data under the 'contour_map' or 'file' field."
        ), 400)
    filename = upload.filename or ""
    file_bytes = upload.read()
    if not file_bytes:
        return None, (jsonify(error="Uploaded file is empty."), 400)
    return (file_bytes, filename), None


def _analyze():
    upload, err = _read_upload()
    if err:
        return err
    file_bytes, filename = upload
    params = _collect_params()

    # Caching (see cache.py): identical (file, params) pairs are served
    # from an indexed SQLite lookup instead of re-running the pipeline.
    request_hash = cache.make_key(file_bytes, params)
    cached = cache.get(request_hash)
    if cached is not None:
        return jsonify({**cached, "cache_hit": True}), 200

    try:
        response = run_analysis(file_bytes, filename, params)
    except ValueError as e:
        return jsonify(error=str(e)), 422

    cache.set(request_hash, response)
    return jsonify({**response, "cache_hit": False}), 200


@app.route("/analyzeContour", methods=["POST"])
@require_api_key
def analyze_contour():
    try:
        return _analyze()
    except Exception as e:
        app.logger.error(traceback.format_exc())
        return jsonify(error=f"Internal error: {e}"), 500


# Alias, per the assignment's suggested route names
@app.route("/findCatchment", methods=["POST"])
@require_api_key
def find_catchment():
    return analyze_contour()


@app.route("/analyzeContourAsync", methods=["POST"])
@require_api_key
def analyze_contour_async():
    """
    Non-blocking variant of /analyzeContour: submits the pipeline to the
    background thread pool (jobs.py) and returns a job id immediately, so
    a large contour map doesn't tie up the request thread or trip a
    client-side HTTP timeout. Poll GET /jobs/<job_id> for the result.
    """
    upload, err = _read_upload()
    if err:
        return err
    file_bytes, filename = upload
    params = _collect_params()

    request_hash = cache.make_key(file_bytes, params)
    cached = cache.get(request_hash)
    if cached is not None:
        # Still hand back a job id for a uniform client-side polling flow,
        # but resolve it immediately from cache -- no thread pool needed.
        job_id = jobs.submit(lambda: {**cached, "cache_hit": True})
        return jsonify(job_id=job_id), 202

    def _job():
        response = run_analysis(file_bytes, filename, params)
        cache.set(request_hash, response)
        return {**response, "cache_hit": False}

    job_id = jobs.submit(_job)
    return jsonify(job_id=job_id), 202


@app.route("/jobs/<job_id>", methods=["GET"])
@require_api_key
def job_status(job_id):
    status = jobs.get_status(job_id)
    if status["status"] == "not_found":
        return jsonify(error="Unknown job id."), 404
    if status["status"] == "error":
        return jsonify(error=status["error"]), 500
    return jsonify(status), 200


@app.route("/health", methods=["GET"])
def health():
    return jsonify(status="ok"), 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
