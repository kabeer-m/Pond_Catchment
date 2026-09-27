# Village Pond Catchment & Site Finder

An AI and geospatial-assisted web application designed to identify suitable locations for rainwater-harvesting village ponds. By uploading elevation contour maps (`.kml`/`.kmz`), the platform automatically interpolates Digital Elevation Models (DEMs), computes D8 hydrological flow accumulation, and recommends optimal pond locations based on catchment area, slope, and terrain flatness.

---

## 🌟 Key Features

- **Geospatial & Terrain Processing**: Automatically extracts elevation-labeled contours, constructs regular metric DEM rasters, and calculates slope gradients.
- **Hydrological Flow Accumulation**: Uses the D8 flow accumulation algorithm to model upstream water drainage and catchment area for any location.
- **Automated Site Selection**: Identifies flat, low-slope candidate sites matching custom pond footprint dimensions, avoiding steep gullies or severe slopes.
- **Multiple Ranking Strategies**: Offers pluggable candidate ranking options:
  - `catchment`: Prioritizes maximum contributing catchment area.
  - `flatness`: Prioritizes flattest terrain (minimizing excavation effort).
  - `balanced`: Combined scoring balancing catchment area and excavation suitability.
- **High-Performance Caching & Async Processing**:
  - SQLite-backed response caching for instant repeated queries.
  - Non-blocking background worker execution for large contour map analysis.
- **Interactive Web Interface**: Leaflet-powered visual dashboard showing candidate locations, footprint polygons, slope metrics, and exact coordinates.

---

## 🏗️ Architecture & Project Structure

The project is organized into clean, modular components:

```
.
├── app.py                      # Flask REST API entry point & route definitions
├── src/                        # Core application source code
│   ├── analysis/               # Geospatial & Hydrological engine
│   │   ├── contour_parser.py   # KML/KMZ elevation vector parser
│   │   ├── terrain.py          # DEM interpolation & D8 flow accumulation algorithm
│   │   ├── pond_finder.py      # Candidate site search & spatial separation
│   │   ├── parsers.py          # Input parser factory
│   │   └── strategies.py       # Pluggable candidate ranking strategies
│   └── services/               # System support services
│       ├── cache.py            # SQLite response caching & indexing
│       ├── jobs.py             # Asynchronous thread pool job executor
│       └── auth.py             # API Key authentication gate
├── templates/
│   └── index.html              # Leaflet-based frontend interactive UI
├── tests/                      # Automated test suite (32 unit & integration tests)
├── requirements.txt            # Python dependencies
├── pytest.ini                  # Pytest configuration
└── README.md                   # Project documentation
```

---

## 🚀 Quick Start

### 1. Requirements & Installation

Ensure Python 3.10+ is installed on your system.

```bash
# Clone the repository
git clone <repository-url>
cd Pond_Catchment

# Create and activate a virtual environment (optional)
python3 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Running the Web Application

```bash
python app.py
```
The application will launch and listen on `http://localhost:5000`. Open your browser to access the interactive upload and mapping UI.

---

## 📡 API Reference

### `POST /analyzeContour` (alias: `/findCatchment`)
Synchronous terrain analysis endpoint. Accepts a multipart contour file and returns ranked candidate pond sites.

- **Content-Type**: `multipart/form-data`
- **Parameters**:
  - `contour_map` (or `file`): Uploaded `.kml` or `.kmz` file (*Required*)
  - `pond_footprint_m`: Side length of target pond footprint in meters (Default: `10.0`)
  - `cell_size_m`: Resolution of the interpolated DEM grid in meters (Default: `2.0`)
  - `mask_slope_threshold_percent`: Maximum slope percentage allowed for terrain cells (Default: `8.0`)
  - `flatness_max_range_m`: Maximum allowed elevation range within a site footprint (Default: `0.3`)
  - `window_mean_slope_max_percent`: Maximum allowed mean slope within footprint (Default: `5.0`)
  - `top_n`: Number of ranked candidates to return (Default: `5`)
  - `ranking`: Ranking strategy (`catchment`, `flatness`, or `balanced`) (Default: `catchment`)

### `POST /analyzeContourAsync`
Asynchronous variant for processing large contour maps without HTTP timeout. Returns a `job_id` immediately (HTTP 202).

### `GET /jobs/<job_id>`
Polls the execution status of an asynchronous job (`pending`, `running`, `done`, or `error`).

### `GET /health`
Liveness health check endpoint returning `{"status": "ok"}`.

---

## 🧪 Testing

The repository contains a comprehensive suite of 32 unit and integration tests covering parser logic, DEM construction, D8 flow math, site search separation, caching, async workers, and API endpoints.

To run the test suite:

```bash
python -m pytest -v
```
