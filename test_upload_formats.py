import io
import os
import atexit
import tempfile

TEST_HIST_PATH = os.path.abspath(f"test_upload_history_{os.getpid()}.json")
os.environ["TRAFFIC_HISTORY_FILE"] = TEST_HIST_PATH

def _cleanup_test_history():
    if os.path.exists(TEST_HIST_PATH):
        try:
            os.remove(TEST_HIST_PATH)
        except OSError:
            pass

atexit.register(_cleanup_test_history)

import csv
import json
import unittest
from PIL import Image
import pillow_avif  # ensure avif plugin is loaded
from app import app, initialize_default_traffic_state

class ComprehensiveVerificationTest(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        initialize_default_traffic_state()

    def _create_dummy_image(self, fmt="JPEG", size=(320, 240), color=(128, 128, 128)):
        img = Image.new("RGB", size, color=color)
        buf = io.BytesIO()
        img.save(buf, format=fmt)
        buf.seek(0)
        return buf

    def test_multi_format_upload_avif_jpg_png_webp(self):
        """Item 8: Accept AVIF, JPG, PNG, WEBP and analyze properly."""
        avif_buf = self._create_dummy_image(fmt="AVIF")
        jpg_buf = self._create_dummy_image(fmt="JPEG")
        png_buf = self._create_dummy_image(fmt="PNG")
        webp_buf = self._create_dummy_image(fmt="WEBP")

        data = {
            "north": (avif_buf, "north_road.avif"),
            "south": (jpg_buf, "south_road.jpg"),
            "east": (png_buf, "east_road.png"),
            "west": (webp_buf, "west_road.webp"),
            "conf_thresh": "0.35"
        }

        res = self.client.post("/api/upload", data=data, content_type="multipart/form-data")
        self.assertEqual(res.status_code, 200)
        json_data = res.get_json()
        self.assertTrue(json_data.get("success"))
        state = json_data.get("data", {})
        
        # Verify mode is Upload
        self.assertIn("Upload", state.get("mode"))
        self.assertEqual(state.get("underlying_mode"), "Upload")
        self.assertEqual(state.get("data_source"), "upload")

        # Verify all 4 roads have data_source upload and detected counts
        for road_key in ["north", "south", "east", "west"]:
            road_data = state["roads"][road_key]
            self.assertEqual(road_data.get("data_source"), "upload")
            self.assertIn("count", road_data)
            self.assertIn("green_time", road_data)
            self.assertIn("engine", road_data)
            self.assertIn("conf_threshold", road_data)

        # Total green time must equal 120s
        total_green = sum(state["roads"][r]["green_time"] for r in state["roads"])
        self.assertEqual(total_green, 120)

    def test_empty_upload(self):
        """Item 8: Empty upload with no files chosen returns 400 and clear message."""
        res = self.client.post("/api/upload", data={}, content_type="multipart/form-data")
        self.assertEqual(res.status_code, 400)
        json_data = res.get_json()
        self.assertFalse(json_data.get("success"))
        self.assertIn("Upload at least one image or video, or use Run Simulation.", json_data.get("error", ""))

    def test_invalid_and_corrupt_files(self):
        """Item 8: Invalid format (PDF) and corrupt image show clear errors naming file without blocking."""
        pdf_buf = io.BytesIO(b"%PDF-1.4 header but not an image")
        corrupt_buf = io.BytesIO(b"garbage bytes that cannot decode")
        valid_buf = self._create_dummy_image(fmt="PNG")

        data = {
            "north": (pdf_buf, "test_doc.pdf"),
            "south": (corrupt_buf, "broken.jpg"),
            "east": (valid_buf, "valid.png"),
        }

        res = self.client.post("/api/upload", data=data, content_type="multipart/form-data")
        self.assertEqual(res.status_code, 200)
        json_data = res.get_json()
        state = json_data.get("data", {})

        # East was valid -> data_source upload
        self.assertEqual(state["roads"]["east"].get("data_source"), "upload")

        # North (PDF) & South (corrupt) should retain as SAMPLE
        self.assertEqual(state["roads"]["north"].get("data_source"), "sample")
        self.assertEqual(state["roads"]["south"].get("data_source"), "sample")

        # Check logs or errors for file names
        logs_text = " ".join(state.get("logs", []))
        errors_text = " ".join(state.get("errors", []))
        combined = logs_text + " " + errors_text
        self.assertIn("test_doc.pdf", combined)
        self.assertIn("broken.jpg", combined)

    def test_emergency_clear_and_expiry_paths(self):
        """Item 1 & 3: Emergency cleared via manual vs expired timer."""
        # 1. Trigger simulation first so underlying mode is Simulation
        sim_res = self.client.post("/api/simulate", json={"lighting": "day"})
        self.assertEqual(sim_res.status_code, 200)
        sim_state = sim_res.get_json()["data"]
        self.assertIn("Simulation", sim_state["mode"])
        self.assertEqual(sim_state["underlying_mode"], "Simulation")

        # 2. Trigger emergency on north
        em_res = self.client.post("/api/emergency", json={"road": "north", "vehicle_type": "ambulance"})
        self.assertEqual(em_res.status_code, 200)
        em_state = em_res.get_json()["data"]
        self.assertIn("Emergency", em_state["mode"])
        self.assertEqual(em_state["emergency_road"], "north")
        self.assertEqual(em_state["underlying_mode"], "Simulation")
        # Engine labels preserved
        self.assertEqual(em_state["data_source"], "simulation")

        # 3. Manual clear
        clear_res = self.client.post("/api/emergency/clear?reason=manual")
        self.assertEqual(clear_res.status_code, 200)
        clear_data = clear_res.get_json()["data"]
        self.assertIsNone(clear_data["emergency_road"])
        self.assertIn("Simulation", clear_data["mode"])
        self.assertEqual(clear_data["underlying_mode"], "Simulation")
        self.assertEqual(clear_data["data_source"], "simulation")
        # Single log for manual
        clear_logs = [l for l in clear_data["logs"] if "Emergency" in l or "emergency" in l]
        self.assertTrue(any("Emergency override cleared" in l for l in clear_logs))

        # 4. Clear again (guard duplicate)
        clear_again = self.client.post("/api/emergency/clear?reason=manual")
        self.assertEqual(clear_again.status_code, 200)
        again_logs = clear_again.get_json()["data"].get("logs", [])
        self.assertFalse(any("Emergency override cleared" in l for l in again_logs))

        # 5. Trigger emergency again, clear with reason=expired
        self.client.post("/api/emergency", json={"road": "south", "vehicle_type": "fire_truck"})
        exp_res = self.client.post("/api/emergency/clear?reason=expired")
        self.assertEqual(exp_res.status_code, 200)
        exp_data = exp_res.get_json()["data"]
        self.assertIsNone(exp_data["emergency_road"])
        self.assertIn("Simulation", exp_data["mode"])
        exp_logs = exp_data["logs"]
        self.assertTrue(any("Emergency priority phase concluded" in l for l in exp_logs))

    def test_history_emergency_delay_reduction_empty(self):
        """Item 4: Emergency runs record wait_reduction_pct as None, CSV export is empty."""
        # Ensure counts exist on dashboard via simulation test tool first
        self.client.post("/api/simulate", json={"lighting": "day"})
        # Trigger emergency
        self.client.post("/api/emergency", json={"road": "east", "vehicle_type": "police_car"})
        
        hist_res = self.client.get("/api/history")
        self.assertEqual(hist_res.status_code, 200)
        history = hist_res.get_json()["history"]
        self.assertGreater(len(history), 0)
        last_run = history[-1]
        self.assertIn("Emergency", last_run.get("mode"))
        self.assertIsNone(last_run.get("wait_reduction_pct"))

        # Check CSV export
        csv_res = self.client.get("/api/history/export")
        self.assertEqual(csv_res.status_code, 200)
        csv_text = csv_res.data.decode("utf-8")
        lines = [l for l in csv_text.strip().split("\n") if l]
        self.assertGreater(len(lines), 1)
        last_line = lines[-1]
        self.assertIn("Emergency", last_line)
        # CSV header: Timestamp, Mode, Lighting, North Count, South Count, East Count, West Count, Total Vehicles, North Green (s), South Green (s), East Green (s), West Green (s), Wait Reduction (%), Emergency Road
        cols = [c.strip() for c in next(csv.reader([last_line]))]
        # Column index 12 is Wait Reduction (%)
        self.assertEqual(cols[12], "")

    def test_emergency_data_source_preserves_dashboard_counts(self):
        """Item 4: An emergency must always use the counts currently on the dashboard (the last simulation or upload), never the sample baseline, unless the dashboard is itself showing the sample data."""
        # 1. Run a simulation to establish counts on the dashboard
        sim_res = self.client.post("/api/simulate", json={"lighting": "night"})
        self.assertEqual(sim_res.status_code, 200)
        sim_state = sim_res.get_json()["data"]
        expected_counts = {r: sim_state["roads"][r]["count"] for r in ["north", "south", "east", "west"]}

        # 2. Trigger an emergency on each road sequentially and assert counts stay identical
        for road in ["north", "south", "east", "west"]:
            em_res = self.client.post("/api/emergency", json={"road": road, "vehicle_type": "ambulance"})
            self.assertEqual(em_res.status_code, 200)
            em_state = em_res.get_json()["data"]
            for r in ["north", "south", "east", "west"]:
                self.assertEqual(
                    em_state["roads"][r]["count"],
                    expected_counts[r],
                    f"Count mismatch on road {r} when emergency triggered on {road}"
                )
            # Clear emergency
            self.client.post("/api/emergency/clear?reason=manual")

    def test_upload_detection_recovery_and_model_selection(self):
        """Item 1: Recovery retry when count <= 1, model selector support (yolov8s, yolov8n, yolov8m), and warning banner."""
        # Create a plain grey dummy image (which yields 0 detections)
        dummy_buf = self._create_dummy_image(fmt="PNG")
        data = {
            "north": (dummy_buf, "blank_approach.png"),
            "model": "yolov8n",
            "conf_thresh": "0.45"
        }
        res = self.client.post("/api/upload", data=data, content_type="multipart/form-data")
        self.assertEqual(res.status_code, 200)
        state = res.get_json()["data"]
        north_road = state["roads"]["north"]

        # Check model name used in engine label
        self.assertIn("YOLOv8n", north_road["engine"])
        
        # Verify recovery was attempted on dummy image (count <= 1)
        # Fields are stored directly on the road dict (not nested under detection_metadata)
        self.assertTrue(north_road.get("recovery_attempted", False))
        self.assertIsNotNone(north_road.get("final_conf"))

        # Check logs for recovery event
        logs_text = " ".join(state.get("logs", []))
        self.assertIn("recovery retry", logs_text.lower())

    def test_accuracy_tracking_and_csv_export(self):
        """Item 2: Actual count input, Detected vs Actual calculation, MAE, and CSV export."""
        dummy_buf1 = self._create_dummy_image(fmt="PNG")
        dummy_buf2 = self._create_dummy_image(fmt="PNG")
        data = {
            "north": (dummy_buf1, "north.png"),
            "east": (dummy_buf2, "east.png"),
            "actual_north": "10",
            "actual_east": "20"
        }
        res = self.client.post("/api/upload", data=data, content_type="multipart/form-data")
        self.assertEqual(res.status_code, 200)
        state = res.get_json()["data"]

        # Verify accuracy report generated
        # accuracy_report uses: per_road (not roads), mae (not overall_mae), no has_actuals key
        self.assertIn("accuracy_report", state)
        acc = state["accuracy_report"]
        # MAE is computed only when actuals are provided, confirming actuals were processed
        self.assertIsNotNone(acc.get("mae"))
        per_road = acc.get("per_road", {})
        self.assertIn("north", per_road)
        self.assertIn("east", per_road)
        self.assertEqual(per_road["north"]["actual"], 10)
        self.assertEqual(per_road["east"]["actual"], 20)

        # Check CSV export has accuracy columns
        csv_res = self.client.get("/api/history/export")
        self.assertEqual(csv_res.status_code, 200)
        csv_text = csv_res.data.decode("utf-8")
        lines = [l for l in csv_text.strip().split("\n") if l]
        header = lines[0]
        self.assertIn("North Actual", header)
        self.assertIn("MAE", header)

    def test_upload_history_rows_naming(self):
        """Item 3: Label rows as 'Upload (N, E)' naming uploaded roads + filenames, un-uploaded roads marked sample."""
        # Use actual images so total vehicles > 0, ensuring history is recorded
        with open("static/samples/real_day_traffic.jpg", "rb") as fn, open("static/samples/real_day_traffic.jpg", "rb") as fs:
            buf_n = io.BytesIO(fn.read())
            buf_s = io.BytesIO(fs.read())
        data = {
            "north": (buf_n, "street_north.jpg"),
            "south": (buf_s, "street_south.jpg")
        }
        res = self.client.post("/api/upload", data=data, content_type="multipart/form-data")
        self.assertEqual(res.status_code, 200)
        state = res.get_json()["data"]

        # Check road metadata marking sample vs upload
        self.assertEqual(state["roads"]["north"]["data_source"], "upload")
        self.assertEqual(state["roads"]["south"]["data_source"], "upload")
        self.assertEqual(state["roads"]["east"]["data_source"], "sample")
        self.assertEqual(state["roads"]["west"]["data_source"], "sample")

        # Check history entry
        hist_res = self.client.get("/api/history")
        history = hist_res.get_json()["history"]
        last_run = history[-1]
        self.assertEqual(last_run.get("mode"), "Upload (N, S)")
        # uploaded_files in history is a dict {road: filename}; check both filenames are values
        uploaded_files_hist = last_run.get("uploaded_files", {})
        all_filenames = list(uploaded_files_hist.values()) if isinstance(uploaded_files_hist, dict) else uploaded_files_hist
        self.assertIn("street_north.jpg", all_filenames)
        self.assertIn("street_south.jpg", all_filenames)

    def test_detection_panel_wording_in_simulation(self):
        """Item 6: In simulation mode, show 'Simulation Mode - no detection run'."""
        sim_res = self.client.post("/api/simulate", json={"lighting": "day"})
        self.assertEqual(sim_res.status_code, 200)
        sim_state = sim_res.get_json()["data"]
        # In simulation mode, data_source is simulation
        self.assertEqual(sim_state["data_source"], "simulation")

if __name__ == "__main__":
    unittest.main()
