# Village Pond Planning System

An AI/geospatial-assisted web service that helps identify suitable
locations for rainwater-harvesting village ponds. Upload a contour map
(`.kml`/`.kmz`), and the backend builds a Digital Elevation Model (DEM),
runs a D8 hydrological flow-accumulation analysis, and returns ranked
candidate pond sites with their estimated catchment area, slope,
flatness, and assumed storage volume.

## How it works

1. **`contour_parser.py`** parses the uploaded `.kml`/`.kmz` file into a
   flat list of `(lon, lat, elevation)` sample points, by walking every
   elevation-labeled contour `LineString` — no assumptions about the
   generating tool's folder layout.
2. **`terrain.py`** reprojects those points into UTM meters and
   interpolates a regular-grid DEM (Delaunay/TIN → raster), then derives
   per-cell slope and D8 flow accumulation (a standard hydrology method
   for estimating each cell's upstream contributing/catchment area).
3. **`pond_finder.py`** searches the DEM for flat, low-slope windows of
   the requested pond footprint, scores them by catchment area, and
   returns the top-N well-separated candidates.
4. **`app.py`** is the Flask layer tying this together behind a REST API.

## What's new in this change set

The base pipeline above was already solid on the "Terrain and Catchment
Analysis" side. This change set adds the surrounding engineering that a
production-leaning service needs, in five small, independently testable
modules — **none of `contour_parser.py`, `terrain.py`, or
`pond_finder.py` were touched**:

| File | Adds | CSD Theme |
|---|---|---|
| `cache.py` | SQLite-backed cache of full analysis responses, keyed by a hash of (file bytes + parameters), with an explicit secondary index for eviction queries | Caching, Database Indexing / Query Optimization |
| `jobs.py` | Thread-pool-backed background job runner so a slow analysis doesn't block the request thread; polled via `/jobs/<id>` | Concurrency / Asynchronous Processing |
| `strategies.py` | Strategy pattern for re-ranking candidates (`catchment`, `flatness`, `balanced`) + a small factory (`get_strategy`) | Design Patterns |
| `parsers.py` | Factory pattern mapping file extension → parser function, so a future input format is one new function + one table entry | Design Patterns |
| `auth.py` | Opt-in `X-API-Key` gate (via `POND_API_KEY`) on the compute-heavy endpoints | Authentication / Authorization |
| `tests/` | 31 pytest unit + integration tests across every module above, plus the existing pipeline | Testing Strategy |
| `.github/workflows/ci.yml` | Runs the full test suite on every push/PR | Version Control / CI-CD |
| `app.py` | Rewired to call all of the above; `_analyze()`/`run_analysis()` split into a pure, Flask-independent compute function reused by both the sync and async endpoints | API Design, Error Handling and Resilience *(already present, preserved)* |

Combined with what the original pipeline already demonstrated (**REST
API Design**, **Error Handling and Resilience** — extension/size
validation, structured 400/422/500 responses — and **Algorithms and
Complexity** — the D8 flow-accumulation algorithm itself, plus the
vectorized-filter optimization notes in `pond_finder.py`), this project
now covers **7 of the 13** CSD themes in the assignment's theme table.

`Microservices vs. Monolith` is also addressed as a conscious decision:
the service stays a single Flask app (a monolith). At this scale — one
compute pipeline, one team, one deployable artifact — splitting into
microservices would add network hops and deployment complexity for no
real benefit; `jobs.py`'s thread pool already gives horizontal headroom
within the process, and `gunicorn --workers` gives it across processes.

Left out on purpose, with the reasoning: **Load Balancing** (a single
`gunicorn` instance behind a reverse proxy is enough for this scale; a
load balancer only pays off once you're running multiple instances) and
**Database Indexing beyond the cache** (there's no persistent business
data yet — sites aren't saved — so a full relational schema would be
speculative; `cache.py`'s indexed table is the one place indexing
currently applies).

## Project structure

```
.
├── app.py                  # Flask routes + the pure run_analysis() pipeline
├── contour_parser.py       # KML/KMZ → ContourSample points (unmodified)
├── terrain.py               # DEM, slope, D8 flow accumulation (unmodified)
├── pond_finder.py           # Candidate site search (unmodified)
├── cache.py                 # SQLite result cache + indexing
├── jobs.py                  # Background job runner (async analysis)
├── strategies.py             # Candidate ranking strategies (Strategy pattern)
├── parsers.py                # Input-format factory (Factory pattern)
├── auth.py                   # API-key auth decorator
├── requirements.txt
├── pytest.ini
├── .github/workflows/ci.yml
├── templates/index.html
└── tests/
    ├── test_app.py
    ├── test_cache.py
    ├── test_contour_parser.py
    ├── test_jobs.py
    ├── test_pond_finder.py
    ├── test_strategies_and_parsers.py
    └── test_terrain.py
```

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python3 app.py          # listens on 0.0.0.0:5000
```

Set `POND_API_KEY` in your environment to require the `X-API-Key` header on the compute endpoints; leave it unset for open/local access.

## Running the tests

```bash
pytest -v
```

31 tests across unit tests for each module and an integration suite for
the Flask app (`tests/test_app.py`), run automatically on every push via
`.github/workflows/ci.yml`.

## API

| Method & Path | Purpose |
|---|---|
| `POST /analyzeContour` (alias `/findCatchment`) | Synchronous analysis. Multipart field `contour_map` (`.kml`/`.kmz`) + optional form/query params below. |
| `POST /analyzeContourAsync` | Same input, returns `{"job_id": "..."}` immediately (HTTP 202) instead of blocking. |
| `GET /jobs/<job_id>` | Poll an async job: `{"status": "pending"\|"running"}`, `{"status": "done", "result": {...}}`, or `{"status": "error", "error": "..."}`. |
| `GET /health` | Liveness check. |

**Optional parameters** (form fields or query string):

| Param | Default | Meaning |
|---|---|---|
| `pond_footprint_m` | `10.0` | Target pond footprint (square, meters/side). |
| `cell_size_m` | `2.0` | DEM raster resolution. |
| `mask_slope_threshold_percent` | `8.0` | Cells steeper than this are excluded from analysis entirely. |
| `flatness_max_range_m` | `0.3` | Max elevation range allowed inside a candidate footprint. |
| `window_mean_slope_max_percent` | `5.0` | Max mean slope allowed inside a candidate footprint. |
| `top_n` | `5` | Number of ranked candidates to return. |
| `ranking` | `catchment` | Re-ranking strategy: `catchment`, `flatness`, or `balanced` (see `strategies.py`). |

Every response includes `"cache_hit": true/false` (see `cache.py`).

If `POND_API_KEY` is set, send it as the `X-API-Key` header on every
route above except `/health`.

### Example

```bash
curl -X POST http://localhost:5000/analyzeContour \
  -H "X-API-Key: $POND_API_KEY" \
  -F "contour_map=@village_survey.kml" \
  -F "top_n=3" \
  -F "ranking=balanced"
```

## AI Tool Usage Declaration

Claude (Anthropic) was used to: review the existing codebase and map it
against the assignment's CSD-themes checklist; design and implement the
five new modules (`cache.py`, `jobs.py`, `strategies.py`, `parsers.py`,
`auth.py`) and the corresponding test suite and CI workflow; and draft this README. All generated code was
run against a real test suite (31 passing tests, including a regression
test for a genuine race condition found during development in
`jobs.py`) and reviewed line-by-line before inclusion — nothing here was
accepted unread. `contour_parser.py`, `terrain.py`, and `pond_finder.py`
(the core terrain/catchment algorithms) were not modified.
