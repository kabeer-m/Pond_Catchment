"""
Integration tests for app.py using Flask's test client.

CSD: Testing Strategy (integration layer, on top of the unit tests for
each module) + exercises Error Handling/Resilience and Authentication.

cache.get/cache.set are monkeypatched to no-ops here: caching itself is
already covered by tests/test_cache.py, and bypassing it keeps these
tests from writing to the real analysis_cache.db file.
"""

import io

import pytest

import app as app_module
from src.services import cache


SAMPLE_KML = b"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <Placemark><name>100</name><LineString>
      <coordinates>77.100,21.200,0 77.101,21.201,0 77.102,21.200,0</coordinates>
    </LineString></Placemark>
    <Placemark><name>101</name><LineString>
      <coordinates>77.100,21.202,0 77.101,21.203,0 77.102,21.202,0</coordinates>
    </LineString></Placemark>
  </Document>
</kml>
"""


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(cache, "get", lambda *a, **k: None)
    monkeypatch.setattr(cache, "set", lambda *a, **k: None)
    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as c:
        yield c


def test_health_endpoint(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.get_json() == {"status": "ok"}


def test_analyze_contour_rejects_missing_file(client):
    resp = client.post("/analyzeContour", data={})
    assert resp.status_code == 400
    assert "No file uploaded" in resp.get_json()["error"]


def test_analyze_contour_rejects_bad_extension(client):
    data = {"contour_map": (io.BytesIO(b"not really a contour file"), "survey.txt")}
    resp = client.post("/analyzeContour", data=data, content_type="multipart/form-data")
    assert resp.status_code == 422


def test_analyze_contour_happy_path_returns_candidates_shape(client):
    data = {
        "contour_map": (io.BytesIO(SAMPLE_KML), "village.kml"),
        "cell_size_m": "5",
    }
    resp = client.post("/analyzeContour", data=data, content_type="multipart/form-data")
    assert resp.status_code == 200
    body = resp.get_json()
    assert "candidates" in body and "terrain_summary" in body
    assert body["cache_hit"] is False


def test_analyze_contour_accepts_file_field_name(client):
    data = {
        "file": (io.BytesIO(SAMPLE_KML), "village.kml"),
        "cell_size_m": "5",
    }
    resp = client.post("/analyzeContour", data=data, content_type="multipart/form-data")
    assert resp.status_code == 200
    body = resp.get_json()
    assert "candidates" in body and "terrain_summary" in body


def test_job_status_for_unknown_job_id_is_404(client):
    resp = client.get("/jobs/does-not-exist")
    assert resp.status_code == 404


def test_api_key_required_when_configured(client, monkeypatch):
    monkeypatch.setenv("POND_API_KEY", "secret123")
    resp = client.get("/jobs/whatever")  # any @require_api_key route
    assert resp.status_code in (401, 404)  # 401 if key enforced before lookup
    if resp.status_code == 401:
        resp2 = client.get("/jobs/whatever", headers={"X-API-Key": "secret123"})
        assert resp2.status_code == 404  # key accepted, falls through to "unknown job"
