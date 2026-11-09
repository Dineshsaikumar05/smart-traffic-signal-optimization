"""
test_suite.py - Comprehensive End-to-End Test Suite for Smart Traffic Signal Optimization
"""
import os
import sys
import atexit
import tempfile

TEST_HIST_PATH = os.path.abspath(f"test_run_history_{os.getpid()}.json")
os.environ["TRAFFIC_HISTORY_FILE"] = TEST_HIST_PATH

def _cleanup_test_history():
    if os.path.exists(TEST_HIST_PATH):
        try:
            os.remove(TEST_HIST_PATH)
        except OSError:
            pass

atexit.register(_cleanup_test_history)

import io
import json
import cv2
import numpy as np

from app import app, SAMPLES_FOLDER, UPLOAD_FOLDER, PROCESSED_FOLDER

client = app.test_client()

failures = []

def test(name, fn):
    print(f"\n---> RUNNING TEST: {name}")
    try:
        fn()
        print(f" [PASS] {name}")
    except Exception as e:
        print(f" [FAIL] {name}: {e}")
        import traceback
        traceback.print_exc()
        failures.append((name, str(e)))

# -------------------------------------------------------------
# 1. Simulation with Day, Dusk, Night, Random, Mixed
# -------------------------------------------------------------
def test_sim_day():
    res = client.post('/api/simulate', json={"lighting": "day"})
    assert res.status_code == 200, f"Expected 200, got {res.status_code}"
    data = res.get_json()
    assert data["success"] is True
    assert "Simulation (Day)" in data["data"]["mode"]
    for r in ["north", "south", "east", "west"]:
        assert data["data"]["roads"][r]["lighting_mode"] == "day"
test("Simulation with Day lighting", test_sim_day)

def test_sim_dusk():
    res = client.post('/api/simulate', json={"lighting": "dusk"})
    assert res.status_code == 200
    data = res.get_json()
    assert data["success"] is True
    assert "Simulation (Dusk)" in data["data"]["mode"]
    for r in ["north", "south", "east", "west"]:
        assert data["data"]["roads"][r]["lighting_mode"] == "dusk"
test("Simulation with Dusk lighting", test_sim_dusk)

def test_sim_night():
    res = client.post('/api/simulate', json={"lighting": "night"})
    assert res.status_code == 200
    data = res.get_json()
    assert data["success"] is True
    assert "Simulation (Night)" in data["data"]["mode"]
    assert data["data"]["is_night_mode"] is True
    for r in ["north", "south", "east", "west"]:
        assert data["data"]["roads"][r]["lighting_mode"] == "night"
test("Simulation with Night lighting", test_sim_night)

def test_sim_random():
    res = client.post('/api/simulate', json={"lighting": "random"})
    assert res.status_code == 200
    data = res.get_json()
    assert data["success"] is True
    # In random mode, all roads share the same chosen junction lighting
    road_modes = [data["data"]["roads"][r]["lighting_mode"] for r in ["north", "south", "east", "west"]]
    assert len(set(road_modes)) == 1, f"Random mode must choose one lighting condition for whole junction: {road_modes}"
test("Simulation with Random lighting (Whole Junction)", test_sim_random)

def test_sim_mixed():
    res = client.post('/api/simulate', json={"lighting": "mixed"})
    assert res.status_code == 200
    data = res.get_json()
    assert data["success"] is True
    assert "Simulation (Mixed)" in data["data"]["mode"]
test("Simulation with Mixed lighting (Per Road)", test_sim_mixed)

# -------------------------------------------------------------
# 2. Emergency simulation on each road (without modifying counts!)
# -------------------------------------------------------------
# First test Requirement A5: Emergency blocked before first analyze / simulation
def test_emerg_blocked_first_load():
    client.get('/api/reset')
    res = client.post('/api/emergency', json={"road": "north"})
    assert res.status_code == 400
    assert "Analyze traffic first" in res.get_json()["error"]
test("Emergency blocked before analyze or simulation", test_emerg_blocked_first_load)

# Run simulation to populate test counts for emergency corridor test
client.post('/api/simulate', json={"lighting": "day"})

for road in ["north", "south", "east", "west"]:
    def make_emerg_test(r):
        def _test():
            # Reset to fresh simulation before each emergency test
            client.post('/api/simulate', json={"lighting": "day"})
            status_res = client.get('/api/status')
            pre_counts = {k: status_res.get_json()["data"]["roads"][k]["count"] for k in ["north", "south", "east", "west"]}

            res = client.post('/api/emergency', json={"road": r, "lighting": "day"})
            assert res.status_code == 200
            data = res.get_json()
            assert data["success"] is True
            assert data["data"]["emergency_road"] == r

            # Priority green: emergency road served first with 60s
            assert data["data"]["order"][0] == r
            assert data["data"]["roads"][r]["green_time"] == 60
            assert data["data"]["roads"][r]["is_emergency"] is True

            # CRITICAL: Counts must NOT be altered or forced to 60!
            post_counts = {k: data["data"]["roads"][k]["count"] for k in ["north", "south", "east", "west"]}
            assert pre_counts == post_counts, f"Counts must stay unchanged: pre={pre_counts}, post={post_counts}"

            # Total cycle time must be preserved at 120s
            total_green = sum(data["data"]["roads"][k]["green_time"] for k in ["north", "south", "east", "west"])
            assert total_green == 120, f"Total green must equal 120s, got {total_green}s"
        return _test
    test(f"Emergency simulation on {road.upper()}", make_emerg_test(road))

# -------------------------------------------------------------
# 3. Emergency + Night mode at the same time
# -------------------------------------------------------------
def test_emerg_night():
    # Set simulation to night
    client.post('/api/simulate', json={"lighting": "night"})
    res = client.post('/api/emergency', json={"road": "north", "lighting": "night"})
    assert res.status_code == 200
    data = res.get_json()
    assert data["success"] is True
    assert data["data"]["emergency_road"] == "north"
    assert data["data"]["is_night_mode"] is True
    assert data["data"]["order"][0] == "north"
    assert data["data"]["roads"]["north"]["green_time"] == 60
test("Emergency + Night mode at the same time", test_emerg_night)

# -------------------------------------------------------------
# 3b. Clear Emergency endpoint
# -------------------------------------------------------------
def test_clear_emergency():
    client.post('/api/emergency', json={"road": "east"})
    res = client.post('/api/emergency/clear')
    assert res.status_code == 200
    data = res.get_json()
    assert data["success"] is True
    assert data["data"]["emergency_road"] is None
    for r in ["north", "south", "east", "west"]:
        assert data["data"]["roads"][r]["is_emergency"] is False
test("Clear emergency endpoint (/api/emergency/clear)", test_clear_emergency)

# -------------------------------------------------------------
# 4. Upload of 4 images (mixed day and night) & short video
# -------------------------------------------------------------
def test_upload_mixed_images():
    north_img = open(os.path.join(SAMPLES_FOLDER, "sample_north.jpg"), "rb")
    south_img = open(os.path.join(SAMPLES_FOLDER, "sample_night.jpg"), "rb")
    east_img = open(os.path.join(SAMPLES_FOLDER, "sample_dusk.jpg"), "rb")
    west_img = open(os.path.join(SAMPLES_FOLDER, "sample_west.jpg"), "rb")

    data = {
        "north": (north_img, "sample_north.jpg"),
        "south": (south_img, "sample_night.jpg"),
        "east": (east_img, "sample_dusk.jpg"),
        "west": (west_img, "sample_west.jpg")
    }

    res = client.post('/api/upload', data=data, content_type='multipart/form-data')
    north_img.close()
    south_img.close()
    east_img.close()
    west_img.close()

    assert res.status_code == 200
    res_data = res.get_json()
    assert res_data["success"] is True
    assert res_data["data"]["is_night_mode"] is True
    assert res_data["data"]["roads"]["south"]["lighting_mode"] == "night"
    assert res_data["data"]["roads"]["east"]["lighting_mode"] == "dusk"
test("Upload 4 mixed images (Day, Night, Dusk)", test_upload_mixed_images)

def test_upload_short_video():
    vid_path = os.path.join(UPLOAD_FOLDER, "test_short_vid.avi")
    fourcc = cv2.VideoWriter_fourcc(*'XVID')
    out = cv2.VideoWriter(vid_path, fourcc, 10.0, (640, 480))
    for _ in range(10):
        frame = np.full((480, 640, 3), 130, dtype=np.uint8)
        out.write(frame)
    out.release()

    with open(vid_path, "rb") as vid_file:
        res = client.post('/api/upload', data={"north": (vid_file, "test_short_vid.avi")}, content_type='multipart/form-data')

    if os.path.exists(vid_path):
        os.remove(vid_path)

    assert res.status_code == 200
    res_data = res.get_json()
    assert res_data["success"] is True
    assert res_data["data"]["roads"]["north"]["count"] >= 0
test("Upload of short video", test_upload_short_video)

# -------------------------------------------------------------
# 5. Missing road file, wrong file type, and file over 50 MB
# -------------------------------------------------------------
def test_upload_missing_road():
    north_img = open(os.path.join(SAMPLES_FOLDER, "sample_north.jpg"), "rb")
    res = client.post('/api/upload', data={"north": (north_img, "sample_north.jpg")}, content_type='multipart/form-data')
    north_img.close()

    assert res.status_code == 200
    res_data = res.get_json()
    assert res_data["success"] is True
    assert "east" in res_data["data"]["roads"]
    assert "west" in res_data["data"]["roads"]
test("Upload with missing road files (fallback to samples)", test_upload_missing_road)

def test_upload_wrong_file_type():
    dummy_pdf = io.BytesIO(b"%PDF-1.4 dummy content")
    res = client.post('/api/upload', data={"north": (dummy_pdf, "document.pdf")}, content_type='multipart/form-data')
    assert res.status_code == 400
    res_data = res.get_json()
    assert res_data["success"] is False
    assert "unsupported file type" in res_data["error"].lower() or "invalid file type" in res_data["error"].lower()
test("Upload with wrong file type (.pdf)", test_upload_wrong_file_type)

def test_upload_over_50mb():
    large_data = {"north": (io.BytesIO(b"A" * (51 * 1024 * 1024)), "large.jpg")}
    res = client.post('/api/upload', data=large_data, content_type='multipart/form-data')
    assert res.status_code == 413
    res_data = res.get_json()
    assert res_data["success"] is False
    assert "50 MB" in res_data["error"]
test("Upload with file over 50 MB (returns 413 JSON)", test_upload_over_50mb)

# -------------------------------------------------------------
# 6. Edge cases: All counts zero, and one road very high count
# -------------------------------------------------------------
def test_all_counts_zero():
    res = client.post('/api/simulate', json={"counts": {"north": 0, "south": 0, "east": 0, "west": 0}})
    assert res.status_code == 200
    res_data = res.get_json()
    assert res_data["success"] is True
    assert res_data["data"]["total_vehicles"] == 0
    # Equal distribution of green time exactly 120s
    total_g = sum(res_data["data"]["roads"][r]["green_time"] for r in ["north", "south", "east", "west"])
    assert total_g == 120
    for r in ["north", "south", "east", "west"]:
        assert res_data["data"]["roads"][r]["green_time"] == 30
    assert res_data["data"]["comparison"]["wait_reduction_pct"] == 0.0
test("Edge case: All counts zero", test_all_counts_zero)

def test_one_road_very_high_count():
    res = client.post('/api/simulate', json={"counts": {"north": 60, "south": 1, "east": 1, "west": 1}})
    assert res.status_code == 200
    res_data = res.get_json()
    assert res_data["success"] is True
    assert res_data["data"]["order"][0] == "north"
    assert res_data["data"]["roads"]["north"]["green_time"] == 60
    assert res_data["data"]["roads"]["north"]["density"] == "High"
    total_g = sum(res_data["data"]["roads"][r]["green_time"] for r in ["north", "south", "east", "west"])
    assert total_g == 120, f"Expected 120s total, got {total_g}"
    assert res_data["data"]["comparison"]["wait_reduction_pct"] > 0
test("Edge case: One road very high count (60 vs 1)", test_one_road_very_high_count)

# -------------------------------------------------------------
# 7. Summary and Reset endpoints
# -------------------------------------------------------------
def test_summary_endpoint():
    res = client.get('/api/summary')
    assert res.status_code == 200
    data = res.get_json()
    assert data["success"] is True
    s = data["summary"]
    assert "total_vehicles" in s
    assert "avg_vehicles_per_road" in s
    assert "green_times" in s
    assert "wait_reduction_pct" in s
    assert "fixed_avg_wait_sec" in s
    assert "adaptive_avg_wait_sec" in s
test("Summary endpoint (/api/summary)", test_summary_endpoint)

def test_reset_endpoint():
    res = client.get('/api/reset')
    assert res.status_code == 200
    data = res.get_json()
    assert data["success"] is True
    assert "Default fixed timer" in data["data"]["mode"]
    assert data["data"]["has_analyzed_data"] is False
    assert data["data"]["emergency_road"] is None
test("Reset endpoint (/api/reset)", test_reset_endpoint)

# -------------------------------------------------------------
# 8. Detection Accuracy & Upload Handling Suite
# -------------------------------------------------------------
def test_empty_upload():
    res = client.post('/api/upload', data={}, content_type='multipart/form-data')
    assert res.status_code == 400
    data = res.get_json()
    assert data["success"] is False
    assert "Upload at least one image or video, or use Run Simulation." in data["error"]
test("Empty upload shows clear error without generating random counts", test_empty_upload)

def test_partial_upload_with_sample_badge():
    real_day = open("static/samples/real_day_traffic.jpg", "rb")
    res = client.post(
        '/api/upload',
        data={"north": (real_day, "real_day_traffic.jpg"), "confidence": "0.35"},
        content_type='multipart/form-data'
    )
    real_day.close()
    assert res.status_code == 200
    data = res.get_json()
    assert data["success"] is True
    assert data["data"]["roads"]["north"]["is_sample"] is False
    assert data["data"]["roads"]["north"]["engine"] in ["YOLOv8n", "YOLOv8s"]
    assert (data["data"]["roads"]["south"].get("upload_failed") is True or data["data"]["roads"]["south"].get("is_sample") is True)
    assert (data["data"]["roads"]["east"].get("upload_failed") is True or data["data"]["roads"]["east"].get("is_sample") is True)
    assert data["data"]["roads"]["west"]["is_sample"] is True
    assert data["data"]["mode"] == "Upload (N)"
test("Partial upload keeps existing roads and marks them SAMPLE", test_partial_upload_with_sample_badge)

def test_corrupt_file_handling():
    real_day = open("static/samples/real_day_traffic.jpg", "rb")
    corrupt_bytes = io.BytesIO(b"NOT_AN_IMAGE_RANDOM_CORRUPTED_BYTES_123456789")
    res = client.post(
        '/api/upload',
        data={
            "north": (real_day, "real_day_traffic.jpg"),
            "south": (corrupt_bytes, "corrupt_south.jpg")
        },
        content_type='multipart/form-data'
    )
    real_day.close()
    assert res.status_code == 200
    data = res.get_json()
    assert data["success"] is True
    assert data["data"]["roads"]["north"]["is_sample"] is False
    assert (data["data"]["roads"]["south"].get("upload_failed") is True or data["data"]["roads"]["south"].get("is_sample") is True)
    assert len(data["errors"]) > 0
    assert "corrupt_south.jpg" in data["errors"][0]
test("Corrupt file does not block other valid roads and reports error", test_corrupt_file_handling)

def test_undecodable_video_handling():
    real_day = open("static/samples/real_day_traffic.jpg", "rb")
    bad_vid = io.BytesIO(b"NOT_A_VALID_MP4_HEADER_BINARY_DATA")
    res = client.post(
        '/api/upload',
        data={
            "north": (real_day, "real_day_traffic.jpg"),
            "east": (bad_vid, "broken_vid.mp4")
        },
        content_type='multipart/form-data'
    )
    real_day.close()
    assert res.status_code == 200
    data = res.get_json()
    assert data["success"] is True
    assert data["data"]["roads"]["north"]["is_sample"] is False
    assert (data["data"]["roads"]["east"].get("upload_failed") is True or data["data"]["roads"]["east"].get("is_sample") is True)
    assert any("broken_vid.mp4" in err for err in data["errors"])
test("Undecodable video does not block other roads and reports error", test_undecodable_video_handling)

def test_real_day_and_night_yolo_detection():
    day_file = open("static/samples/real_day_traffic.jpg", "rb")
    night_file = open("static/samples/real_night_traffic.jpg", "rb")
    res = client.post(
        '/api/upload',
        data={
            "north": (day_file, "real_day_traffic.jpg"),
            "south": (night_file, "real_night_traffic.jpg"),
            "confidence": "0.30"
        },
        content_type='multipart/form-data'
    )
    day_file.close()
    night_file.close()
    assert res.status_code == 200
    data = res.get_json()
    assert data["success"] is True
    assert data["data"]["roads"]["north"]["engine"] in ["YOLOv8n", "YOLOv8s"]
    assert data["data"]["roads"]["south"]["engine"] in ["YOLOv8n", "YOLOv8s"]
    assert data["data"]["roads"]["north"]["lighting_mode"] == "day"
    assert data["data"]["roads"]["south"]["lighting_mode"] in ["dusk", "night"]
test("Real day and night photos with YOLOv8n engine and auto-lighting", test_real_day_and_night_yolo_detection)

def test_partial_upload_single_road():
    from signal_logic import calculate_signal_timings
    res = calculate_signal_timings({"north": 25, "south": None, "east": None, "west": None})
    assert res["roads"]["north"]["green_time"] <= 60, f"North exceeded max_green: {res['roads']['north']['green_time']}"
    assert res["roads"]["north"]["green_time"] == 60
    assert res["roads"]["south"]["green_time"] == 10
    assert res["roads"]["east"]["green_time"] == 10
    assert res["roads"]["west"]["green_time"] == 10
    assert res["actual_cycle_time"] == 90
    assert res["unallocated_seconds"] == 30
    assert res["cycle_label"] == "Cycle: 90 s, partial data"
test("Partial upload single road max green clamp (60s) and cycle 90s partial data", test_partial_upload_single_road)

print("\n" + "="*50)
if failures:
    print(f"FAILED TESTS ({len(failures)}):")
    for name, err in failures:
        print(f" - {name}: {err}")
    sys.exit(1)
else:
    print("ALL TESTS PASSED SUCCESSFULLY! (100% PASS RATE)")
print("="*50)
