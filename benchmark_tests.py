import io
import json
import os
import sys
import time
import threading
import urllib.request
import urllib.parse
from concurrent.futures import ThreadPoolExecutor

# Default target host, overridable via TARGET_URL environment variable
BASE_URL = os.environ.get("TARGET_URL", "http://10.1.75.79:5213")

# Small KML payload for test runs
SMALL_KML = b"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <Placemark><name>100</name><LineString>
      <coordinates>77.100,21.200,0 77.101,21.201,0 77.102,21.200,0</coordinates>
    </LineString></Placemark>
    <Placemark><name>105</name><LineString>
      <coordinates>77.100,21.202,0 77.101,21.203,0 77.102,21.202,0</coordinates>
    </LineString></Placemark>
  </Document>
</kml>
"""

def make_multipart_body(file_bytes, filename, fields=None):
    boundary = "----WebKitFormBoundary7MA4YWxkTrZu0gW"
    body = bytearray()
    
    if fields:
        for name, value in fields.items():
            body.extend(f"--{boundary}\r\n".encode())
            body.extend(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
            body.extend(f"{value}\r\n".encode())
            
    body.extend(f"--{boundary}\r\n".encode())
    body.extend(f'Content-Disposition: form-data; name="contour_map"; filename="{filename}"\r\n'.encode())
    body.extend(b"Content-Type: application/vnd.google-earth.kml+xml\r\n\r\n")
    body.extend(file_bytes)
    body.extend(b"\r\n")
    body.extend(f"--{boundary}--\r\n".encode())
    
    content_type = f"multipart/form-data; boundary={boundary}"
    return bytes(body), content_type

def post_multipart(url, file_bytes, filename, fields=None, timeout=120):
    body, content_type = make_multipart_body(file_bytes, filename, fields)
    req = urllib.request.Request(url, data=body, headers={"Content-Type": content_type}, method="POST")
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            t1 = time.time()
            data = json.loads(resp.read().decode())
            return resp.status, (t1 - t0) * 1000, data
    except urllib.error.HTTPError as e:
        t1 = time.time()
        try:
            data = json.loads(e.read().decode())
        except Exception:
            data = {}
        return e.code, (t1 - t0) * 1000, data
    except Exception as e:
        return 500, 0.0, {"error": str(e)}

def get_request(url, timeout=10):
    t0 = time.time()
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            t1 = time.time()
            content = resp.read()
            try:
                data = json.loads(content.decode())
            except Exception:
                data = content.decode()
            return resp.status, (t1 - t0) * 1000, data
    except urllib.error.HTTPError as e:
        t1 = time.time()
        try:
            data = json.loads(e.read().decode())
        except Exception:
            data = {}
        return e.code, (t1 - t0) * 1000, data
    except Exception as e:
        return 500, 0.0, {"error": str(e)}

def start_local_server_if_needed(target_url):
    """If target host is unavailable, spin up local Flask server for automated CI runs."""
    try:
        with urllib.request.urlopen(f"{target_url}/health", timeout=2) as r:
            if r.status == 200:
                print(f"Connected to live target host: {target_url}")
                return target_url, None
    except Exception:
        pass

    # Fallback to local server on port 5000
    local_url = "http://127.0.0.1:5000"
    try:
        with urllib.request.urlopen(f"{local_url}/health", timeout=2) as r:
            if r.status == 200:
                print(f"Connected to existing local server: {local_url}")
                return local_url, None
    except Exception:
        pass

    print("Target host not reachable. Starting local Flask server for benchmarks...")
    from app import app
    server_thread = threading.Thread(target=lambda: app.run(host="127.0.0.1", port=5000, debug=False, use_reloader=False), daemon=True)
    server_thread.start()
    time.sleep(1.5)
    return local_url, server_thread

def run_benchmarks():
    global BASE_URL
    BASE_URL, _ = start_local_server_if_needed(BASE_URL)
    results = []
    failed_tests = 0
    
    print(f"\n=======================================================")
    print(f" RUNNING BENCHMARK & SYSTEM INTEGRATION TESTS")
    print(f" Target Host: {BASE_URL}")
    print(f"=======================================================\n")

    # 1. Health check
    print("1. Benchmarking GET /health (50 requests)...")
    latencies, statuses = [], []
    for _ in range(50):
        status, ms, _ = get_request(f"{BASE_URL}/health")
        statuses.append(status)
        latencies.append(ms)
    latencies.sort()
    success_rate = statuses.count(200)/50*100
    if success_rate < 100: failed_tests += 1
    results.append({
        "Test Name": "GET /health (Liveness)",
        "Requests": 50,
        "Success Rate": f"{success_rate:.1f}%",
        "Min (ms)": f"{latencies[0]:.2f}",
        "Avg (ms)": f"{sum(latencies)/len(latencies):.2f}",
        "P95 (ms)": f"{latencies[int(len(latencies)*0.95)]:.2f}",
        "Max (ms)": f"{latencies[-1]:.2f}",
        "Status": "PASSED" if success_rate == 100 else "FAILED"
    })

    # 2. Frontend Dashboard
    print("2. Benchmarking GET / (Index Page, 20 requests)...")
    latencies, statuses = [], []
    for _ in range(20):
        status, ms, _ = get_request(f"{BASE_URL}/")
        statuses.append(status)
        latencies.append(ms)
    latencies.sort()
    success_rate = statuses.count(200)/20*100
    if success_rate < 100: failed_tests += 1
    results.append({
        "Test Name": "GET / (Frontend UI)",
        "Requests": 20,
        "Success Rate": f"{success_rate:.1f}%",
        "Min (ms)": f"{latencies[0]:.2f}",
        "Avg (ms)": f"{sum(latencies)/len(latencies):.2f}",
        "P95 (ms)": f"{latencies[int(len(latencies)*0.95)]:.2f}",
        "Max (ms)": f"{latencies[-1]:.2f}",
        "Status": "PASSED" if success_rate == 100 else "FAILED"
    })

    # 3. Small KML Cold Run
    print("3. Benchmarking POST /analyzeContour (Small KML - Cold run)...")
    unique_tag = str(time.time())
    status, cold_ms, data_cold = post_multipart(
        f"{BASE_URL}/analyzeContour",
        SMALL_KML,
        "small_test.kml",
        {"cell_size_m": "4.5", "top_n": "3", "tag": unique_tag}
    )
    if status != 200: failed_tests += 1
    results.append({
        "Test Name": "POST /analyzeContour (Small KML - Cold)",
        "Requests": 1,
        "Success Rate": "100%" if status == 200 else "0%",
        "Min (ms)": f"{cold_ms:.2f}",
        "Avg (ms)": f"{cold_ms:.2f}",
        "P95 (ms)": f"{cold_ms:.2f}",
        "Max (ms)": f"{cold_ms:.2f}",
        "Status": "PASSED" if status == 200 else "FAILED"
    })

    # 4. Small KML Warm Run / Cache Hit
    print("4. Benchmarking POST /analyzeContour (Small KML - Warm Cache hit)...")
    status, warm_ms, data_warm = post_multipart(
        f"{BASE_URL}/analyzeContour",
        SMALL_KML,
        "small_test.kml",
        {"cell_size_m": "4.5", "top_n": "3", "tag": unique_tag}
    )
    is_pass = status == 200 and data_warm.get("cache_hit") is True
    if not is_pass: failed_tests += 1
    results.append({
        "Test Name": "POST /analyzeContour (Small KML - Warm Cache)",
        "Requests": 1,
        "Success Rate": "100%" if is_pass else "0%",
        "Min (ms)": f"{warm_ms:.2f}",
        "Avg (ms)": f"{warm_ms:.2f}",
        "P95 (ms)": f"{warm_ms:.2f}",
        "Max (ms)": f"{warm_ms:.2f}",
        "Status": "PASSED" if is_pass else "FAILED"
    })

    # 5. Large Map (if available)
    large_kml_bytes = None
    for p in ["_untracked_archive/contour_map.kml", "contour_map.kml"]:
        if os.path.exists(p):
            with open(p, "rb") as f:
                large_kml_bytes = f.read()
            break

    if large_kml_bytes:
        print("5. Benchmarking POST /analyzeContour (6.7MB Map - Cold run)...")
        large_tag = str(time.time())
        status, l_cold_ms, l_data_cold = post_multipart(
            f"{BASE_URL}/analyzeContour",
            large_kml_bytes,
            "contour_map.kml",
            {"top_n": "5", "tag": large_tag},
            timeout=180
        )
        if status != 200: failed_tests += 1
        results.append({
            "Test Name": "POST /analyzeContour (6.7MB Map - Cold)",
            "Requests": 1,
            "Success Rate": "100%" if status == 200 else "0%",
            "Min (ms)": f"{l_cold_ms:.2f}",
            "Avg (ms)": f"{l_cold_ms:.2f}",
            "P95 (ms)": f"{l_cold_ms:.2f}",
            "Max (ms)": f"{l_cold_ms:.2f}",
            "Status": "PASSED" if status == 200 else "FAILED"
        })

        print("6. Benchmarking POST /analyzeContourAsync (6.7MB Map - Async Submission)...")
        async_tag = str(time.time())
        status, async_sub_ms, async_res = post_multipart(
            f"{BASE_URL}/analyzeContourAsync",
            large_kml_bytes,
            "contour_map.kml",
            {"top_n": "5", "tag": async_tag}
        )
        job_id = async_res.get("job_id")
        if status != 202 or not job_id: failed_tests += 1
        results.append({
            "Test Name": "POST /analyzeContourAsync (Submission)",
            "Requests": 1,
            "Success Rate": "100%" if status == 202 and job_id else "0%",
            "Min (ms)": f"{async_sub_ms:.2f}",
            "Avg (ms)": f"{async_sub_ms:.2f}",
            "P95 (ms)": f"{async_sub_ms:.2f}",
            "Max (ms)": f"{async_sub_ms:.2f}",
            "Status": "PASSED" if status == 202 and job_id else "FAILED"
        })

        if job_id:
            print("   Polling /jobs/<job_id>...")
            poll_t0 = time.time()
            job_status = "pending"
            poll_count = 0
            while job_status in ("pending", "running") and (time.time() - poll_t0) < 120:
                time.sleep(0.5)
                poll_count += 1
                _, _, job_data = get_request(f"{BASE_URL}/jobs/{job_id}")
                job_status = job_data.get("status")
            poll_total_ms = (time.time() - poll_t0) * 1000
            if job_status != "done": failed_tests += 1
            results.append({
                "Test Name": "GET /jobs/<job_id> (Polling Completion)",
                "Requests": poll_count,
                "Success Rate": "100%" if job_status == "done" else "0%",
                "Min (ms)": f"{poll_total_ms/poll_count:.2f}",
                "Avg (ms)": f"{poll_total_ms:.2f}",
                "P95 (ms)": f"{poll_total_ms:.2f}",
                "Max (ms)": f"{poll_total_ms:.2f}",
                "Status": "PASSED" if job_status == "done" else "FAILED"
            })

    # 7. Concurrency Test
    print("7. Benchmarking Concurrency (10 Parallel Requests)...")
    def worker(i):
        return post_multipart(
            f"{BASE_URL}/analyzeContour",
            SMALL_KML,
            f"small_{i}.kml",
            {"cell_size_m": "5.0", "top_n": "3", "worker": str(i)}
        )

    t0_conc = time.time()
    with ThreadPoolExecutor(max_workers=10) as executor:
        conc_res = list(executor.map(worker, range(10)))
    t1_conc = time.time()

    conc_ms_list = [r[1] for r in conc_res]
    conc_ms_list.sort()
    conc_successes = sum(1 for r in conc_res if r[0] == 200)
    if conc_successes < 10: failed_tests += 1

    results.append({
        "Test Name": "POST /analyzeContour (10 Parallel Requests)",
        "Requests": 10,
        "Success Rate": f"{conc_successes/10*100:.1f}%",
        "Min (ms)": f"{conc_ms_list[0]:.2f}",
        "Avg (ms)": f"{sum(conc_ms_list)/len(conc_ms_list):.2f}",
        "P95 (ms)": f"{conc_ms_list[int(len(conc_ms_list)*0.95)]:.2f}",
        "Max (ms)": f"{conc_ms_list[-1]:.2f}",
        "Status": "PASSED" if conc_successes == 10 else "FAILED"
    })

    # 8. Error Handling Tests
    print("8. Error Handling & Validation Tests...")
    err1_code, err1_ms, _ = get_request(f"{BASE_URL}/analyzeContour")
    is_err1 = err1_code in (400, 405)
    if not is_err1: failed_tests += 1
    results.append({
        "Test Name": "Error: Missing Upload Payload",
        "Requests": 1,
        "Success Rate": "100%" if is_err1 else "0%",
        "Min (ms)": f"{err1_ms:.2f}",
        "Avg (ms)": f"{err1_ms:.2f}",
        "P95 (ms)": f"{err1_ms:.2f}",
        "Max (ms)": f"{err1_ms:.2f}",
        "Status": "PASSED" if is_err1 else "FAILED"
    })

    err2_code, err2_ms, _ = post_multipart(f"{BASE_URL}/analyzeContour", b"hello world", "test.txt")
    is_err2 = err2_code in (400, 422)
    if not is_err2: failed_tests += 1
    results.append({
        "Test Name": "Error: Invalid File Extension (.txt)",
        "Requests": 1,
        "Success Rate": "100%" if is_err2 else "0%",
        "Min (ms)": f"{err2_ms:.2f}",
        "Avg (ms)": f"{err2_ms:.2f}",
        "P95 (ms)": f"{err2_ms:.2f}",
        "Max (ms)": f"{err2_ms:.2f}",
        "Status": "PASSED" if is_err2 else "FAILED"
    })

    err3_code, err3_ms, _ = get_request(f"{BASE_URL}/jobs/non_existent_job_12345")
    is_err3 = err3_code == 404
    if not is_err3: failed_tests += 1
    results.append({
        "Test Name": "Error: Unknown Job ID Lookup",
        "Requests": 1,
        "Success Rate": "100%" if is_err3 else "0%",
        "Min (ms)": f"{err3_ms:.2f}",
        "Avg (ms)": f"{err3_ms:.2f}",
        "P95 (ms)": f"{err3_ms:.2f}",
        "Max (ms)": f"{err3_ms:.2f}",
        "Status": "PASSED" if is_err3 else "FAILED"
    })

    print("\n=======================================================")
    print(" SUMMARY OF BENCHMARK & SYSTEM TESTS")
    print("=======================================================")
    print(f" Total Tests Run : {len(results)}")
    print(f" Total Passed    : {len(results) - failed_tests}")
    print(f" Total Failed    : {failed_tests}")
    print("=======================================================\n")

    if failed_tests > 0:
        sys.exit(1)
    return results

if __name__ == "__main__":
    run_benchmarks()
