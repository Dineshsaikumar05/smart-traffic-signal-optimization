"""
app.py - AI-Based Smart Traffic Signal Optimization Flask Server

Serves the interactive dashboard, manages file uploads for 4-way junctions,
triggers AI vehicle detection with night-mode / low-light enhancement,
computes adaptive signal timings, and exposes REST APIs for real-time
traffic signal monitoring, simulation, pipeline telemetry, emergency
override, and performance summaries.
"""

import os
import time
import json
import random
import logging
import datetime
import io
import csv
import hashlib
import copy
from typing import Optional
import cv2
from werkzeug.utils import secure_filename
from flask import Flask, render_template, request, jsonify, url_for, Response

from detector import (
    count_vehicles,
    generate_sample_images,
    _draw_synthetic_road,
    get_detection_metadata,
)
from signal_logic import calculate_signal_timings

# ---------------------------------------------------------------------------
# Logging configuration
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("traffic_app")

# ---------------------------------------------------------------------------
# Flask application
# ---------------------------------------------------------------------------
app = Flask(__name__)
app.config["SECRET_KEY"] = "smart-traffic-signal-secret-key-2026"
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024  # 50 MB max upload limit

# ---------------------------------------------------------------------------
# Directory setup
# ---------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
UPLOAD_FOLDER = os.path.join(STATIC_DIR, "uploads")
PROCESSED_FOLDER = os.path.join(STATIC_DIR, "processed")
SAMPLES_FOLDER = os.path.join(STATIC_DIR, "samples")

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(PROCESSED_FOLDER, exist_ok=True)
os.makedirs(SAMPLES_FOLDER, exist_ok=True)

# Generate synthetic samples (day, dusk, and night) if not already present
generate_sample_images(SAMPLES_FOLDER)

ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".avif", ".mp4", ".avi", ".mov", ".webm", ".mkv"}

# Constants
ROADS = ["north", "south", "east", "west"]
STALE_FILE_AGE_SECS = 300  # 5 minutes

# Global in-memory cache of the latest computed traffic state
latest_result: dict = {}

# ---------------------------------------------------------------------------
# Run History Management (Stores last 20 runs, persisted to JSON)
# ---------------------------------------------------------------------------
def get_history_file() -> str:
    return os.environ.get("TRAFFIC_HISTORY_FILE", os.path.join(BASE_DIR, "run_history.json"))

HISTORY_FILE = get_history_file()
run_history: list = []

def _load_run_history() -> list:
    """Loads run history from disk if exists, otherwise returns empty list."""
    target_file = get_history_file()
    if os.path.exists(target_file):
        try:
            with open(target_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return data[-20:]
        except Exception as exc:
            logger.warning("Could not read history file %s: %s", target_file, exc)
    return []

def _save_run_history() -> None:
    """Saves the in-memory run_history list (max 20 items) to disk."""
    global run_history
    target_file = get_history_file()
    try:
        with open(target_file, "w", encoding="utf-8") as f:
            json.dump(run_history[-20:], f, indent=2)
    except Exception as exc:
        logger.warning("Could not save history to %s: %s", target_file, exc)

last_analyzed_state: Optional[dict] = None

def record_run_history(timing_data: dict) -> None:
    """
    Appends a run entry to run_history, keeping at most 20 records.
    Only records Simulation, Upload, Emergency, and Test runs where total_vehicles > 0.
    Does NOT record Initial Samples or Reset.
    Entry format:
      timestamp: str
      mode: str
      lighting: str ("N:day, S:dusk, E:night, W:day")
      counts: {road: count}
      green_times: {road: seconds}
      total_vehicles: int
      wait_reduction_pct: float
      emergency_road: str or None
    """
    global run_history
    if not timing_data or "roads" not in timing_data:
        return

    mode = timing_data.get("history_mode") or timing_data.get("mode", "Unknown")
    is_allowed_mode = any(kw in mode for kw in ["Simulation", "Upload", "Emergency", "Test"])
    if not is_allowed_mode or "Default fixed timer" in mode:
        return

    roads = timing_data.get("roads", {})
    counts = {r: roads[r].get("count") for r in ROADS if r in roads}
    total_veh = timing_data.get("total_vehicles", sum(c for c in counts.values() if c is not None))

    # Do not log a run where total vehicles is 0
    if total_veh <= 0:
        return

    green_times = {r: roads[r].get("green_time", 0) for r in ROADS if r in roads}
    
    # Requirement 13: Unambiguous lighting text in history ("N:day, S:dusk, E:night, W:day")
    lighting_summary = ", ".join(
        f"{r[0].upper()}:{roads[r].get('lighting_mode', 'day')}" for r in ROADS if r in roads
    )

    comp = timing_data.get("comparison", {})
    is_emergency = bool(timing_data.get("emergency_road"))
    wait_red = None if is_emergency else comp.get("wait_reduction_pct", 0.0)

    entry = {
        "id": int(time.time() * 1000),
        "timestamp": timing_data.get("timestamp") or datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "mode": mode,
        "lighting": lighting_summary,
        "counts": counts,
        "green_times": green_times,
        "total_vehicles": total_veh,
        "wait_reduction_pct": wait_red,
        "emergency_road": timing_data.get("emergency_road"),
        "uploaded_files": timing_data.get("uploaded_filenames", {}),
        "accuracy_report": timing_data.get("accuracy_report"),
    }

    run_history.append(entry)
    run_history = run_history[-20:]
    _save_run_history()

# Initialise run history on module load
run_history = _load_run_history()
 
# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------

def is_allowed_file(filename: str) -> bool:
    """Checks if an uploaded file has a supported image or video extension."""
    if not filename:
        return False
    ext = os.path.splitext(filename)[1].lower()
    return ext in ALLOWED_EXTENSIONS


def _purge_stale_files(folder: str, max_age_secs: int = STALE_FILE_AGE_SECS) -> int:
    """
    Deletes files in *folder* that are older than *max_age_secs* seconds.
    Returns the number of files removed.
    Skips any file whose removal raises an OSError.
    """
    removed = 0
    cutoff = time.time() - max_age_secs
    try:
        for fname in os.listdir(folder):
            fpath = os.path.join(folder, fname)
            if not os.path.isfile(fpath):
                continue
            try:
                if os.path.getmtime(fpath) < cutoff:
                    os.remove(fpath)
                    removed += 1
                    logger.debug("Purged stale file: %s", fpath)
            except OSError as exc:
                logger.warning("Could not remove stale file %s: %s", fpath, exc)
    except OSError as exc:
        logger.warning("Could not list folder %s for purge: %s", folder, exc)
    if removed:
        logger.info("Purged %d stale file(s) from %s", removed, folder)
    return removed


def _cleanup_before_analysis() -> None:
    """
    Called at the start of every upload / simulate / emergency run.
    Removes files older than STALE_FILE_AGE_SECS from uploads and processed
    directories to prevent unbounded disk growth.
    Samples folder is intentionally left untouched.
    """
    _purge_stale_files(UPLOAD_FOLDER)
    _purge_stale_files(PROCESSED_FOLDER)


DEFAULT_SAMPLE_COUNTS = {"north": 16, "south": 7, "east": 27, "west": 4}

def _safe_count_vehicles(
    image_path: str,
    road: str,
    conf_threshold: float = 0.30,
    model_name: str = "yolov8s",
    lighting_override: Optional[str] = None
):
    """
    Wraps count_vehicles() with a try/except so that a single corrupt or
    unreadable file never crashes the server.

    Returns:
        (count, proc_rel_path, lighting_mode, brightness)
        count is None if detection/decoding failed completely.
    """
    try:
        count, proc_rel_path, lighting_mode, brightness = count_vehicles(
            image_path,
            PROCESSED_FOLDER,
            conf_threshold=conf_threshold,
            model_name=model_name,
            lighting_override=lighting_override
        )
        return count, proc_rel_path, lighting_mode, brightness
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "Detection failed for road=%s file=%s: %s", road, image_path, exc
        )
        return None, None, "day", 128.0


def _build_road_meta(
    road: str,
    proc_rel_path,
    lighting_mode: str,
    brightness: float,
    is_sample: bool = False,
    data_source: str = "sample",
    conf_threshold: float = 0.30,
    model_name: str = "yolov8s"
) -> dict:
    """Constructs the per-road metadata dict that is merged into timing_data."""
    meta = get_detection_metadata(proc_rel_path) if proc_rel_path else {}
    img_url = "/" + (proc_rel_path or f"static/samples/sample_{road}.jpg").replace("\\", "/")
    
    if data_source == "simulation":
        engine_name = "Simulated"
    elif data_source == "sample" or is_sample:
        engine_name = "Sample images"
    else:
        engine_name = meta.get("engine")
        if not engine_name:
            from detector import get_yolo_model, get_yolo_engine_name
            engine_name = get_yolo_engine_name(model_name) if get_yolo_model(model_name) is not None else "OpenCV fallback"

    return {
        "image_url": img_url,
        "lighting_mode": lighting_mode,
        "brightness": brightness,
        "pipeline": meta.get("pipeline", "Standard Vision Pipeline"),
        "original_image_url": meta.get("original_url", img_url),
        "enhanced_image_url": meta.get("enhanced_url", img_url),
        "engine": engine_name,
        "data_source": data_source,
        "conf_threshold": conf_threshold,
        "is_video": meta.get("is_video", False),
        "video_avg_count": meta.get("video_avg_count"),
        "video_max_count": meta.get("video_max_count"),
        "is_sample": is_sample,
        "recovery_applied": meta.get("recovery_applied", False),
        "recovery_attempted": meta.get("recovery_attempted", False),
        "initial_count": meta.get("initial_count"),
        "final_conf": meta.get("final_conf", conf_threshold),
        "final_imgsz": meta.get("final_imgsz", 960),
    }


def _lighting_log_line(road: str, lighting_mode: str, brightness: float, suffix: str = "") -> str:
    """Produces a standardised log line for a road's detection result."""
    if lighting_mode in ("night", "dusk"):
        detail = "low-light enhancement applied"
    else:
        detail = "standard vision pipeline"
    extra = f" - {suffix}" if suffix else ""
    return (
        f"{road.upper()}: {lighting_mode} detected "
        f"(brightness {int(brightness)}) - {detail}{extra}"
    )


# ---------------------------------------------------------------------------
# State initialisation
# ---------------------------------------------------------------------------

def initialize_default_traffic_state() -> None:
    """
    Initialises traffic state to the first-load waiting state (Requirement A2):
    - Signals run on an equal fixed plan (30 s per road)
    - Labelled 'Default fixed timer (no data yet)'
    - Notice: 'Waiting for photos: upload one image or video per road and click Analyze Traffic'
    - No made-up vehicle counts (None, displayed as '—')
    - has_analyzed_data: False
    """
    global latest_result, last_analyzed_state
    last_analyzed_state = None

    road_results = {}
    for road in ROADS:
        road_results[road] = {
            "count": None,
            "density": "—",
            "green_time": 30,
            "share_pct": 25.0,
            "is_emergency": False,
            "no_data": True,
            "image_url": f"/static/samples/sample_{road}.jpg",
            "lighting_mode": "day",
            "brightness": 120.0,
            "pipeline": "Waiting for photos",
            "original_image_url": f"/static/samples/sample_{road}.jpg",
            "enhanced_image_url": f"/static/samples/sample_{road}.jpg",
            "engine": "—",
            "data_source": "none",
            "conf_threshold": 0.30,
            "is_video": False,
            "is_sample": False,
            "is_previous": False,
            "is_test_data": False,
            "upload_failed": False,
        }

    latest_result = {
        "roads": road_results,
        "order": ["north", "south", "east", "west"],
        "total_vehicles": 0,
        "cycle_time": 120,
        "min_green": 10,
        "max_green": 60,
        "emergency_road": None,
        "mode": "Default fixed timer (no data yet)",
        "underlying_mode": "Default fixed timer (no data yet)",
        "data_source": "none",
        "has_analyzed_data": False,
        "notice": "Waiting for photos: upload one image or video per road and click Analyze Traffic",
        "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "is_night_mode": False,
        "logs": ["Waiting for photos: upload one image or video per road and click Analyze Traffic."],
        "errors": [],
        "comparison": {
            "fixed_avg_wait_sec": 45.0,
            "adaptive_avg_wait_sec": 45.0,
            "wait_reduction_pct": 0.0,
            "total_wait_fixed_sec": 0,
            "total_wait_adaptive_sec": 0,
            "congestion_index_fixed": 1.0,
            "congestion_index_adaptive": 1.0,
            "clearance_efficiency_pct": 100.0
        }
    }
    logger.info("Default traffic state initialised to first-load waiting state.")


# Run once at startup
initialize_default_traffic_state()


# ---------------------------------------------------------------------------
# Error handlers
# ---------------------------------------------------------------------------

@app.errorhandler(413)
def request_entity_too_large(error):
    """Handles uploads exceeding the 50 MB file size limit."""
    logger.warning("Upload rejected – file exceeds 50 MB limit.")
    return jsonify({
        "success": False,
        "error": "File size exceeds the 50 MB limit. Please upload a smaller video or image.",
    }), 413


@app.errorhandler(404)
def not_found(error):
    return jsonify({"success": False, "error": "Endpoint not found."}), 404


@app.errorhandler(405)
def method_not_allowed(error):
    return jsonify({"success": False, "error": "Method not allowed."}), 405


@app.errorhandler(500)
def internal_error(error):
    logger.error("Internal server error: %s", error)
    return jsonify({"success": False, "error": "Internal server error."}), 500


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    """Renders the main Traffic Control Room Dashboard."""
    return render_template("index.html")


# ── /api/status ─────────────────────────────────────────────────────────────

@app.route("/api/status", methods=["GET"])
def get_status():
    """Returns the latest computed traffic, lighting, and signal timing state."""
    global latest_result
    if not latest_result:
        logger.info("/api/status: no state found – re-initialising.")
        initialize_default_traffic_state()
    return jsonify({"success": True, "data": latest_result})


# ── /api/reset ──────────────────────────────────────────────────────────────

@app.route("/api/reset", methods=["GET", "POST"])
def reset_state():
    """
    Resets the server state to defaults by re-running the sample-based
    initialisation pipeline. Useful for clearing emergency overrides or
    reverting after a bad upload.
    """
    logger.info("/api/reset called – reinitialising default traffic state.")
    try:
        initialize_default_traffic_state()
        return jsonify({
            "success": True,
            "message": "Traffic state reset to defaults successfully.",
            "data": latest_result,
        })
    except Exception as exc:  # noqa: BLE001
        logger.error("/api/reset failed: %s", exc)
        return jsonify({"success": False, "error": f"Reset failed: {exc}"}), 500


# ── /api/simulate ────────────────────────────────────────────────────────────

@app.route("/api/simulate", methods=["POST"])
def simulate_traffic():
    """
    Simulates traffic scenarios across all 4 corridors.

    Accepted JSON body (all optional):
        lighting  – 'day' | 'dusk' | 'night' | 'random'  (default: 'random')
        counts    – {road: int} override for specific roads
    """
    global latest_result

    _cleanup_before_analysis()

    req_json = request.get_json(silent=True) or {}
    custom_counts = req_json.get("counts", {})
    selected_lighting = (req_json.get("lighting") or "random").lower().strip()

    logger.info("/api/simulate called with lighting=%s", selected_lighting)

    simulated_counts: dict = {}
    road_lightings: dict = {}

    # Lighting resolution:
    # "random" chooses ONE lighting condition for the whole junction.
    # "mixed" chooses a random lighting condition per road.
    if selected_lighting == "random":
        junction_lighting = random.choice(["day", "dusk", "night"])
        for road in ROADS:
            road_lightings[road] = junction_lighting
    elif selected_lighting in ("day", "dusk", "night"):
        for road in ROADS:
            road_lightings[road] = selected_lighting
    else:  # "mixed" or any custom option
        selected_lighting = "mixed"
        for road in ROADS:
            road_lightings[road] = random.choice(["day", "dusk", "night"])

    for road in ROADS:
        road_lighting = road_lightings[road]

        if road in custom_counts and isinstance(custom_counts[road], (int, float)):
            simulated_counts[road] = max(0, min(60, int(custom_counts[road])))
        else:
            if road_lighting == "night":
                simulated_counts[road] = random.randint(2, 14)
            elif road_lighting == "dusk":
                simulated_counts[road] = random.randint(6, 25)
            else:
                simulated_counts[road] = random.randint(8, 38)

    timing_data = calculate_signal_timings(simulated_counts)
    logs: list = []

    for road in ROADS:
        cnt = simulated_counts[road]
        r_light = road_lightings[road]

        try:
            sim_frame = _draw_synthetic_road(
                cnt, f"SIMULATED {road.upper()} CORRIDOR", lighting=r_light
            )
            sim_name = f"sim_{road}_{int(time.time())}_{random.randint(100, 999)}.jpg"
            temp_raw_path = os.path.join(UPLOAD_FOLDER, f"raw_{sim_name}")
            cv2.imwrite(temp_raw_path, sim_frame)
        except Exception as exc:  # noqa: BLE001
            logger.error("Frame generation failed for road=%s: %s", road, exc)
            temp_raw_path = os.path.join(SAMPLES_FOLDER, f"sample_{road}.jpg")

        count, proc_rel_path, lighting_mode, brightness = _safe_count_vehicles(
            temp_raw_path, road
        )

        # Clean up temporary raw frame (only if it was created in uploads)
        if temp_raw_path.startswith(UPLOAD_FOLDER) and os.path.exists(temp_raw_path):
            try:
                os.remove(temp_raw_path)
            except OSError:
                pass

        road_meta = _build_road_meta(
            road, proc_rel_path, lighting_mode, brightness, data_source="simulation"
        )
        road_meta["engine"] = "Simulated"
        road_meta["pipeline"] = "Simulated Traffic Engine"
        road_meta["is_test_data"] = True
        timing_data["roads"][road].update(road_meta)

        log_line = _lighting_log_line(road, lighting_mode, brightness)
        logger.info(log_line)
        logs.append(log_line)

    timing_data["mode"] = f"Test (random data) - Simulation ({selected_lighting.capitalize()})"
    timing_data["underlying_mode"] = "Simulation"
    timing_data["data_source"] = "simulation"
    timing_data["history_mode"] = "Test (random)"
    timing_data["is_test_data"] = True
    timing_data["timestamp"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    timing_data["is_night_mode"] = any(
        r.get("lighting_mode") == "night" for r in timing_data["roads"].values()
    )
    timing_data["logs"] = logs

    latest_result = timing_data
    record_run_history(latest_result)
    return jsonify({
        "success": True,
        "data": latest_result,
        "message": "Traffic simulation successfully updated with lighting analysis.",
    })


# ── /api/samples ─────────────────────────────────────────────────────────────

@app.route("/api/samples", methods=["POST", "GET"])
def load_sample_roads():
    """
    Loads synthetic sample images for all 4 approaches.
    Part of Test tools (random data, for testing only).
    Does NOT overwrite last_analyzed_state.
    """
    global latest_result
    _cleanup_before_analysis()
    logger.info("/api/samples called (Test tools)")

    sample_counts = dict(DEFAULT_SAMPLE_COUNTS)
    timing_data = calculate_signal_timings(sample_counts)
    logs = []

    for road in ROADS:
        count = sample_counts[road]
        proc_rel_path = f"static/samples/sample_{road}.jpg"
        lighting_mode = "day" if road in ("north", "west") else ("night" if road == "south" else "dusk")
        brightness = 140.0 if lighting_mode == "day" else (45.0 if lighting_mode == "night" else 85.0)

        road_meta = _build_road_meta(
            road, proc_rel_path, lighting_mode, brightness, is_sample=True, data_source="sample"
        )
        road_meta["engine"] = "Sample images"
        road_meta["pipeline"] = "Sample Benchmark Feed"
        road_meta["is_test_data"] = True
        timing_data["roads"][road].update(road_meta)
        log_line = f"{road.upper()}: Loaded sample image (count: {count} veh, {lighting_mode})"
        logs.append(log_line)

    timing_data["mode"] = "Test (random data)"
    timing_data["underlying_mode"] = "Test (random data)"
    timing_data["data_source"] = "test"
    timing_data["history_mode"] = "Test (random)"
    timing_data["is_test_data"] = True
    timing_data["timestamp"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    timing_data["is_night_mode"] = any(
        r.get("lighting_mode") == "night" for r in timing_data["roads"].values()
    )
    timing_data["logs"] = logs
    latest_result = timing_data
    record_run_history(latest_result)
    return jsonify({
        "success": True,
        "data": latest_result,
        "message": "Sample roads loaded under Test tools."
    })


# ── /api/upload ──────────────────────────────────────────────────────────────

@app.route("/api/upload", methods=["POST"])
def upload_traffic_files():
    """
    Accepts image / video uploads for the four roads (north, south, east, west),
    saves them to uploads/, runs lighting analysis and vehicle detection,
    applies low-light enhancement where needed, optimises signals, and returns
    the updated state.

    Roads with uploads are analyzed; other roads retain their previous analyzed count
    (marked 'Previous') or are treated as 'no data' (10s min green, excluded from share).
    Does NOT fall back silently to sample data.
    """
    global latest_result, last_analyzed_state

    _cleanup_before_analysis()
    logger.info("/api/upload called.")

    # 1. Model and confidence threshold
    try:
        conf_threshold = float(request.form.get("confidence", 0.30))
        conf_threshold = max(0.10, min(0.70, conf_threshold))
    except (ValueError, TypeError):
        conf_threshold = 0.30

    model_choice = (request.form.get("model") or "yolov8s").lower().strip()
    if model_choice not in ["yolov8s", "yolov8n", "yolov8m"]:
        model_choice = "yolov8s"

    # Per-road lighting overrides
    lighting_overrides = {}
    for r in ROADS:
        ov = (request.form.get(f"lighting_{r}") or "auto").lower().strip()
        lighting_overrides[r] = ov if ov in ("day", "dusk", "night") else None

    # Optional Ground Truth Actual Counts
    actual_counts = {}
    for r in ROADS:
        val = request.form.get(f"actual_{r}")
        if val is not None and val.strip() != "":
            try:
                actual_counts[r] = max(0, int(val.strip()))
            except ValueError:
                pass

    # 2. Check for uploaded files
    uploaded_files = {}
    for r in ROADS:
        f = request.files.get(r)
        if f and f.filename and f.filename.strip() != "":
            uploaded_files[r] = f

    if not uploaded_files:
        logger.warning("/api/upload called with no files selected.")
        return jsonify({
            "success": False,
            "error": "Upload at least one image or video, or use Run Simulation.",
            "errors": ["Upload at least one image or video, or use Run Simulation."]
        }), 400

    logs: list = []
    errors_list: list = []
    timestamp_str = str(int(time.time()))

    # Duplicate file detection: compute sha256 hash of each uploaded file
    file_hashes = {}
    for r, f in uploaded_files.items():
        f.seek(0)
        h = hashlib.sha256(f.read()).hexdigest()
        f.seek(0)
        file_hashes[r] = h

    duplicate_groups = {}
    for r, h in file_hashes.items():
        matches = [other for other, oh in file_hashes.items() if oh == h]
        if len(matches) > 1:
            duplicate_groups[r] = matches

    # Check if duplicate files have differing actual counts
    warned_dups = set()
    for r, matches in duplicate_groups.items():
        key = tuple(sorted(matches))
        if key not in warned_dups:
            warned_dups.add(key)
            acts = {m: actual_counts[m] for m in matches if m in actual_counts}
            if len(set(acts.values())) > 1:
                warn_msg = f"Duplicate file warning: Identical media uploaded for approaches {', '.join([m.upper() for m in matches])}, but their Actual Counts differ ({', '.join([f'{m.upper()}={acts[m]}' for m in acts])})."
                errors_list.append(warn_msg)
                logs.append(warn_msg)
                logger.warning(warn_msg)

    detected_counts: dict = {}
    road_meta_map: dict = {}

    for road in ROADS:
        if road in uploaded_files:
            file = uploaded_files[road]
            fname = file.filename

            # Check allowed extension
            if not is_allowed_file(fname):
                err_msg = f"Upload failed for {road.capitalize()} approach: '{fname}' is an unsupported file type. Allowed images: .jpg .jpeg .png .bmp .webp .avif — videos: .mp4 .avi .mov .webm"
                logger.warning(err_msg)
                errors_list.append(err_msg)
                logs.append(f"❌ {road.upper()}: Upload failed - unsupported file format '{fname}'")
                detected_counts[road] = None
                road_meta_map[road] = {
                    "count": None,
                    "no_data": True,
                    "density": "—",
                    "green_time": 10,
                    "share_pct": 0.0,
                    "image_url": f"/static/samples/sample_{road}.jpg",
                    "lighting_mode": "day",
                    "brightness": 120.0,
                    "pipeline": "Upload failed",
                    "original_image_url": f"/static/samples/sample_{road}.jpg",
                    "enhanced_image_url": f"/static/samples/sample_{road}.jpg",
                    "engine": "Upload failed",
                    "data_source": "sample",
                    "upload_failed": True,
                    "error_reason": f"Unsupported format '{fname}'",
                    "is_sample": True,
                    "is_previous": False,
                }
                continue

            sec_name = secure_filename(fname)
            unique_filename = f"{road}_{timestamp_str}_{sec_name}"
            save_path = os.path.join(UPLOAD_FOLDER, unique_filename)

            try:
                file.save(save_path)
                logger.info("Saved upload: %s", save_path)
            except Exception as exc:
                err_msg = f"Upload failed: Could not save '{fname}' for {road.capitalize()}: {exc}"
                logger.error(err_msg)
                errors_list.append(err_msg)
                logs.append(f"❌ {road.upper()}: Upload failed - save error for '{fname}'")
                detected_counts[road] = None
                road_meta_map[road] = {
                    "count": None,
                    "no_data": True,
                    "density": "—",
                    "green_time": 10,
                    "share_pct": 0.0,
                    "image_url": f"/static/samples/sample_{road}.jpg",
                    "lighting_mode": "day",
                    "brightness": 120.0,
                    "pipeline": "Upload failed",
                    "original_image_url": f"/static/samples/sample_{road}.jpg",
                    "enhanced_image_url": f"/static/samples/sample_{road}.jpg",
                    "engine": "Upload failed",
                    "data_source": "sample",
                    "upload_failed": True,
                    "error_reason": f"Save failed: {exc}",
                    "is_sample": True,
                    "is_previous": False,
                }
                continue

            # Safe detection call with multi-format decoder fallback and recovery
            count, proc_rel_path, lighting_mode, brightness = _safe_count_vehicles(
                save_path,
                road,
                conf_threshold=conf_threshold,
                model_name=model_choice,
                lighting_override=lighting_overrides.get(road)
            )

            if count is None:
                # Decoding / analysis failed completely across all 4 decoders
                err_msg = f"Upload failed for {road.capitalize()} approach: '{fname}' could not be decoded or analyzed."
                logger.warning(err_msg)
                errors_list.append(err_msg)
                logs.append(f"❌ {road.upper()}: Upload failed - corrupt/undecodable media '{fname}'")
                detected_counts[road] = None
                road_meta_map[road] = {
                    "count": None,
                    "no_data": True,
                    "density": "—",
                    "green_time": 10,
                    "share_pct": 0.0,
                    "image_url": f"/static/samples/sample_{road}.jpg",
                    "lighting_mode": "day",
                    "brightness": 120.0,
                    "pipeline": "Upload failed",
                    "original_image_url": f"/static/samples/sample_{road}.jpg",
                    "enhanced_image_url": f"/static/samples/sample_{road}.jpg",
                    "engine": "Upload failed",
                    "data_source": "sample",
                    "upload_failed": True,
                    "error_reason": f"Undecodable media '{fname}'",
                    "is_sample": True,
                    "is_previous": False,
                }
                continue

            detected_counts[road] = count
            road_meta = _build_road_meta(
                road, proc_rel_path, lighting_mode, brightness, is_sample=False,
                data_source="upload", conf_threshold=conf_threshold, model_name=model_choice
            )
            # Model actually used (Requirement C13)
            engine_used = road_meta.get("engine")
            model_map = {"yolov8n": "YOLOv8n", "yolov8s": "YOLOv8s", "yolov8m": "YOLOv8m"}
            if not engine_used or "yolo" in engine_used.lower():
                engine_used = model_map.get(model_choice, f"YOLOv8{model_choice[-1]}")
            road_meta["engine"] = engine_used
            road_meta["model_used"] = model_choice
            road_meta["data_source"] = "upload"
            road_meta["conf_threshold"] = conf_threshold
            road_meta["upload_failed"] = False

            if road in duplicate_groups:
                other_roads = [m.upper() for m in duplicate_groups[road] if m != road]
                road_meta["is_duplicate"] = True
                road_meta["duplicate_file_note"] = f"Identical file uploaded for {', '.join(other_roads)}"

            road_meta_map[road] = road_meta

            # Format log entry
            if road_meta.get("recovery_applied"):
                init_c = road_meta.get("initial_count", count)
                log_line = (
                    f"🔄 {road.upper()}: Initial count {init_c} at conf {conf_threshold:.2f}/imgsz 960 -> "
                    f"Recovery retry at conf 0.15/imgsz 1280 yielded {count} vehicles using Engine: {engine_used}."
                )
            elif road_meta.get("recovery_attempted"):
                init_c = road_meta.get("initial_count", count)
                log_line = (
                    f"⚠️ {road.upper()}: Processed '{fname}' — {count} vehicles detected using Engine: {engine_used} "
                    f"(conf 0.15/imgsz 1280 recovery retry ran, initial was {init_c})."
                )
            else:
                log_line = (
                    f"{road.upper()}: Processed '{fname}' — {count} vehicles detected using Engine: {engine_used} "
                    f"(conf {conf_threshold:.2f}, brightness: {int(brightness)}, lighting: {lighting_mode})."
                )
            logger.info(log_line)
            logs.append(log_line)

        else:
            # Road had no upload file (Requirement A4):
            # Check if there is a previous analyzed count in last_analyzed_state
            if last_analyzed_state and road in last_analyzed_state.get("roads", {}) and last_analyzed_state["roads"][road].get("count") is not None:
                prev_road = last_analyzed_state["roads"][road]
                detected_counts[road] = prev_road["count"]
                prev_meta = copy.deepcopy(prev_road)
                prev_meta["is_previous"] = True
                prev_meta["engine"] = "Previous"
                road_meta_map[road] = prev_meta
                log_line = f"{road.upper()}: Retained previous analyzed count ({prev_road['count']} veh) - marked as Previous"
                logs.append(log_line)
                logger.info(log_line)
            else:
                # No data: use min_green and exclude from share calculation
                detected_counts[road] = None
                road_meta_map[road] = {
                    "count": None,
                    "no_data": True,
                    "density": "—",
                    "green_time": 10,
                    "share_pct": 0.0,
                    "image_url": f"/static/samples/sample_{road}.jpg",
                    "lighting_mode": "day",
                    "brightness": 120.0,
                    "pipeline": "No data",
                    "original_image_url": f"/static/samples/sample_{road}.jpg",
                    "enhanced_image_url": f"/static/samples/sample_{road}.jpg",
                    "engine": "Sample images (no upload)",
                    "data_source": "sample",
                    "is_sample": True,
                    "is_previous": False,
                    "upload_failed": False,
                }
                log_line = f"{road.upper()}: No upload provided (treated as no data, allocated minimum 10s green)"
                logs.append(log_line)
                logger.info(log_line)

    # Check if ANY uploaded files succeeded
    successful_roads = [r for r in uploaded_files if not road_meta_map.get(r, {}).get("upload_failed", False)]
    if len(successful_roads) == 0 and errors_list:
        return jsonify({
            "success": False,
            "error": errors_list[0],
            "errors": errors_list
        }), 400

    timing_data = calculate_signal_timings(detected_counts)

    # Ground Truth Accuracy Report (Requirement C9):
    # Include only roads successfully analyzed. Show 'n/a (not analyzed)' for others;
    # Calculate MAE and MPE only over analyzed roads.
    accuracy_report = {
        "per_road": {},
        "mae": None,
        "mpe": None,
    }
    abs_errors = []
    pct_errors = []

    for r in ROADS:
        is_analyzed = (r in successful_roads) and (detected_counts.get(r) is not None)
        act = actual_counts.get(r)
        det = detected_counts.get(r)

        if is_analyzed and det is not None:
            if act is not None:
                abs_err = abs(det - act)
                abs_errors.append(abs_err)
                err_pct = round((abs_err / act * 100), 1) if act > 0 else (0.0 if det == 0 else 100.0)
                pct_errors.append(err_pct)
                feedback_str = f"Detected {det} vs Actual {act} (error {err_pct}%)"
                accuracy_report["per_road"][r] = {
                    "detected": det,
                    "actual": act,
                    "abs_error": abs_err,
                    "error_pct": err_pct,
                    "feedback": feedback_str,
                    "analyzed": True
                }
                road_meta_map[r]["actual_count"] = act
                road_meta_map[r]["error_pct"] = err_pct
                road_meta_map[r]["accuracy_feedback"] = feedback_str
            else:
                accuracy_report["per_road"][r] = {
                    "detected": det,
                    "actual": None,
                    "abs_error": None,
                    "error_pct": None,
                    "feedback": None,
                    "analyzed": True
                }
        else:
            # Not analyzed (failed, previous, or no data)
            accuracy_report["per_road"][r] = {
                "detected": det,
                "actual": act,
                "abs_error": None,
                "error_pct": "n/a (not analyzed)",
                "feedback": "n/a (not analyzed)",
                "analyzed": False
            }
            road_meta_map[r]["actual_count"] = act
            road_meta_map[r]["error_pct"] = "n/a (not analyzed)"
            road_meta_map[r]["accuracy_feedback"] = "n/a (not analyzed)"

    if abs_errors:
        accuracy_report["mae"] = round(sum(abs_errors) / len(abs_errors), 2)
    if pct_errors:
        accuracy_report["mpe"] = round(sum(pct_errors) / len(pct_errors), 1)

    for road in ROADS:
        timing_data["roads"][road].update(road_meta_map[road])

    # Upload History Rows labeling (e.g. "Upload (S, E, W)")
    uploaded_letters = [r[0].upper() for r in successful_roads]
    history_mode_label = f"Upload ({', '.join(uploaded_letters)})" if uploaded_letters else "Upload"
    timing_data["history_mode"] = history_mode_label
    timing_data["mode"] = history_mode_label
    timing_data["underlying_mode"] = "Upload"
    timing_data["data_source"] = "upload"
    timing_data["has_analyzed_data"] = True
    timing_data["accuracy_report"] = accuracy_report
    timing_data["uploaded_filenames"] = {
        r: uploaded_files[r].filename for r in successful_roads if r in uploaded_files
    }
    timing_data["timestamp"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    timing_data["is_night_mode"] = any(
        r.get("lighting_mode") == "night" for r in timing_data["roads"].values()
    )
    timing_data["logs"] = logs
    timing_data["errors"] = errors_list

    last_analyzed_state = copy.deepcopy(timing_data)
    latest_result = timing_data
    record_run_history(latest_result)

    return jsonify({
        "success": True,
        "data": latest_result,
        "errors": errors_list,
        "message": "Uploads analysed, lighting conditions evaluated, and traffic signals optimised.",
    })


# ── /api/emergency ───────────────────────────────────────────────────────────

@app.route("/api/emergency", methods=["POST"])
def emergency_vehicle():
    """
    Simulates an emergency vehicle override on a specified road.
    Uses the last analyzed counts. Disabled until first Analyze has run.
    """
    global latest_result, last_analyzed_state

    _cleanup_before_analysis()

    req_json = request.get_json(silent=True) or {}
    road = (req_json.get("road") or "").lower().strip()
    lighting = (req_json.get("lighting") or "day").lower().strip()

    logger.info("/api/emergency called: road=%s lighting=%s", road, lighting)

    if road not in ROADS:
        return jsonify({
            "success": False,
            "error": f"Invalid road '{road}'. Must be one of: {', '.join(ROADS)}.",
        }), 400

    # Requirement A5: Emergency buttons use last analyzed counts.
    # Block if no analyze has run yet (allow test simulation when testing).
    source_state = last_analyzed_state if (last_analyzed_state and last_analyzed_state.get("has_analyzed_data")) else None
    if not source_state and latest_result and latest_result.get("is_test_data"):
        source_state = latest_result

    if not source_state or any(source_state.get("roads", {}).get(r, {}).get("count") is None for r in ROADS):
        return jsonify({
            "success": False,
            "error": "Analyze traffic first",
        }), 400

    current_counts: dict = {}
    for r in ROADS:
        current_counts[r] = source_state["roads"][r].get("count")

    timing_data = calculate_signal_timings(current_counts, emergency_road=road)
    logs: list = []

    for r in ROADS:
        old_road_meta = copy.deepcopy(source_state["roads"].get(r, {}))
        new_green = timing_data["roads"][r]["green_time"]
        new_density = timing_data["roads"][r]["density"]
        new_share = timing_data["roads"][r]["share_pct"]
        timing_data["roads"][r].update(old_road_meta)
        timing_data["roads"][r]["green_time"] = new_green
        timing_data["roads"][r]["density"] = new_density
        timing_data["roads"][r]["share_pct"] = new_share
        timing_data["roads"][r]["is_emergency"] = (r == road)

        if r == road:
            timing_data["roads"][r]["green_time"] = 60
            log_line = (
                f"🚨 EMERGENCY PRIORITY ACTIVATED: {r.upper()} corridor granted immediate priority green "
                f"(60s) without altering vehicle counts ({timing_data['roads'][r]['count']} veh)."
            )
        else:
            log_line = (
                f"{r.upper()}: Adaptive green adjusted to {timing_data['roads'][r]['green_time']}s "
                f"({timing_data['roads'][r]['count']} veh, {timing_data['roads'][r]['density']} density)."
            )
        logger.info(log_line)
        logs.append(log_line)

    timing_data["mode"] = f"Emergency Override ({road.capitalize()})"
    timing_data["underlying_mode"] = source_state.get("underlying_mode", "Upload")
    timing_data["data_source"] = source_state.get("data_source", "simulation" if source_state.get("is_test_data") else "upload")
    timing_data["has_analyzed_data"] = source_state.get("has_analyzed_data", False)
    timing_data["is_test_data"] = source_state.get("is_test_data", False)
    timing_data["timestamp"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    timing_data["is_night_mode"] = any(
        r.get("lighting_mode") == "night" for r in timing_data["roads"].values()
    )
    timing_data["emergency_road"] = road
    timing_data["emergency_message"] = f"Emergency vehicle priority granted to {road.upper()} approach."
    timing_data["logs"] = logs

    latest_result = timing_data
    record_run_history(latest_result)
    return jsonify({
        "success": True,
        "data": latest_result,
        "message": f"Emergency override activated for {road.capitalize()} road.",
    })


# ── /api/emergency/clear ─────────────────────────────────────────────────────

@app.route("/api/emergency/clear", methods=["POST", "GET"])
def clear_emergency():
    """
    Clears active emergency override and returns to standard adaptive cycle
    using the existing measured vehicle counts from last analyzed state.
    """
    global latest_result, last_analyzed_state
    reason = request.args.get("reason", "manual")
    logger.info("/api/emergency/clear called (reason=%s).", reason)

    if not latest_result or "roads" not in latest_result:
        initialize_default_traffic_state()
        return jsonify({
            "success": True,
            "data": latest_result,
            "message": "Emergency cleared and defaults loaded."
        })

    was_active = latest_result.get("emergency_road") is not None
    if not was_active:
        res_data = dict(latest_result)
        res_data["logs"] = []
        return jsonify({
            "success": True,
            "data": res_data,
            "message": "Emergency already cleared."
        })

    source_state = last_analyzed_state if (last_analyzed_state and last_analyzed_state.get("has_analyzed_data")) else None
    if not source_state and latest_result and latest_result.get("is_test_data"):
        source_state = latest_result

    if source_state and any(source_state.get("roads", {}).get(r, {}).get("count") is not None for r in ROADS):
        current_counts = {r: source_state["roads"][r].get("count") for r in ROADS}
        timing_data = calculate_signal_timings(current_counts, emergency_road=None)
        for r in ROADS:
            old_meta = copy.deepcopy(source_state["roads"].get(r, {}))
            new_green = timing_data["roads"][r]["green_time"]
            new_density = timing_data["roads"][r]["density"]
            new_share = timing_data["roads"][r]["share_pct"]
            timing_data["roads"][r].update(old_meta)
            timing_data["roads"][r]["green_time"] = new_green
            timing_data["roads"][r]["density"] = new_density
            timing_data["roads"][r]["share_pct"] = new_share
            timing_data["roads"][r]["is_emergency"] = False
        underlying = source_state.get("underlying_mode", "Upload")
        timing_data["mode"] = underlying
        timing_data["underlying_mode"] = underlying
        timing_data["data_source"] = source_state.get("data_source", "simulation" if source_state.get("is_test_data") else "upload")
        timing_data["has_analyzed_data"] = source_state.get("has_analyzed_data", False)
        timing_data["is_test_data"] = source_state.get("is_test_data", False)
        timing_data["emergency_road"] = None
        timing_data["timestamp"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        timing_data["is_night_mode"] = any(
            r.get("lighting_mode") == "night" for r in timing_data["roads"].values()
        )
    else:
        initialize_default_traffic_state()
        timing_data = latest_result

    if reason == "expired":
        log_line = "🟢 Emergency priority phase concluded. Resumed normal adaptive cycle."
    else:
        log_line = "🟢 Emergency override cleared. Resumed standard adaptive density-based cycle."
    timing_data["logs"] = [log_line]
    logger.info(log_line)

    latest_result = timing_data
    return jsonify({
        "success": True,
        "data": latest_result,
        "message": "Emergency cleared. Resumed normal adaptive cycle."
    })


# ── /api/confidence_sweep ───────────────────────────────────────────────────

@app.route("/api/confidence_sweep", methods=["POST"])
def run_confidence_sweep():
    """
    Tests confidence thresholds [0.20, 0.30, 0.40, 0.50] using the selected model.
    Runs detection on each road's uploaded image (or currently analyzed/saved images).
    Returns total vehicles detected and per-road error against Actual counts.
    """
    _cleanup_before_analysis()
    logger.info("/api/confidence_sweep called.")

    model_choice = (request.form.get("model") or "yolov8s").lower().strip()
    if model_choice not in ["yolov8s", "yolov8n", "yolov8m"]:
        model_choice = "yolov8s"

    actual_counts = {}
    for r in ROADS:
        val = request.form.get(f"actual_{r}")
        if val is not None and val.strip() != "":
            try:
                actual_counts[r] = max(0, int(val.strip()))
            except ValueError:
                pass

    road_image_paths = {}
    timestamp_str = str(int(time.time()))
    for r in ROADS:
        f = request.files.get(r)
        if f and f.filename and f.filename.strip() != "":
            sec_name = secure_filename(f.filename)
            save_path = os.path.join(UPLOAD_FOLDER, f"sweep_{r}_{timestamp_str}_{sec_name}")
            f.save(save_path)
            road_image_paths[r] = save_path
        elif last_analyzed_state and r in last_analyzed_state.get("roads", {}):
            img_url = last_analyzed_state["roads"][r].get("image_url", "")
            local_p = img_url.lstrip("/").split("?")[0]
            if os.path.exists(local_p):
                road_image_paths[r] = local_p

    if not road_image_paths:
        return jsonify({
            "success": False,
            "error": "No images available for sweep. Choose road files or analyze traffic first."
        }), 400

    conf_levels = [0.20, 0.30, 0.40, 0.50]
    sweep_results = []

    for conf in conf_levels:
        total_veh = 0
        roads_res = {}
        abs_errs = []
        for r, pth in road_image_paths.items():
            cnt, _, _, _ = _safe_count_vehicles(pth, r, conf_threshold=conf, model_name=model_choice)
            if cnt is None:
                cnt = 0
            total_veh += cnt
            act = actual_counts.get(r)
            if act is not None:
                abs_err = abs(cnt - act)
                abs_errs.append(abs_err)
                err_pct = round((abs_err / act * 100), 1) if act > 0 else (0.0 if cnt == 0 else 100.0)
            else:
                abs_err = None
                err_pct = None
            roads_res[r] = {
                "detected": cnt,
                "actual": act,
                "abs_error": abs_err,
                "error_pct": err_pct
            }

        mae = round(sum(abs_errs) / len(abs_errs), 2) if abs_errs else None
        sweep_results.append({
            "confidence": conf,
            "total_vehicles": total_veh,
            "roads": roads_res,
            "mae": mae
        })

    return jsonify({
        "success": True,
        "model": model_choice,
        "results": sweep_results
    })


# ── /api/summary ─────────────────────────────────────────────────────────────

@app.route("/api/summary", methods=["GET"])
def get_summary():
    """
    Returns a human-readable performance summary derived from the latest
    computed traffic state.

    Fields returned:
        total_vehicles       – total across all four roads
        avg_vehicles_per_road – mean count per road
        green_times          – per-road green allocation in seconds
        avg_green_time       – mean green time across roads
        wait_reduction_pct   – estimated wait-time saving vs fixed 30 s timing
        fixed_avg_wait_sec   – fixed-timer average wait (seconds)
        adaptive_avg_wait_sec – adaptive average wait (seconds)
        mode                 – current operating mode
        timestamp            – when the last analysis ran
        road_densities       – density classification per road
    """
    global latest_result
    if not latest_result:
        logger.info("/api/summary: no state found – re-initialising.")
        initialize_default_traffic_state()

    roads_data = latest_result.get("roads", {})
    comparison = latest_result.get("comparison", {})

    total_vehicles = latest_result.get("total_vehicles", 0)
    num_roads = len(roads_data) or 1

    green_times = {r: roads_data[r].get("green_time", 0) for r in roads_data}
    avg_green = round(sum(green_times.values()) / num_roads, 1)
    avg_vehicles = round(total_vehicles / num_roads, 1)

    road_densities = {r: roads_data[r].get("density", "Unknown") for r in roads_data}

    summary = {
        "total_vehicles": total_vehicles,
        "avg_vehicles_per_road": avg_vehicles,
        "green_times": green_times,
        "avg_green_time": avg_green,
        "wait_reduction_pct": comparison.get("wait_reduction_pct", 0.0),
        "fixed_avg_wait_sec": comparison.get("fixed_avg_wait_sec", 0.0),
        "adaptive_avg_wait_sec": comparison.get("adaptive_avg_wait_sec", 0.0),
        "mode": latest_result.get("mode", "Unknown"),
        "timestamp": latest_result.get("timestamp", "N/A"),
        "road_densities": road_densities,
    }

    return jsonify({"success": True, "summary": summary})


# ── Run History APIs ─────────────────────────────────────────────────────────

@app.route("/api/history", methods=["GET"])
def get_history():
    """Returns the last 20 recorded runs in chronological order."""
    global run_history
    return jsonify({
        "success": True,
        "history": run_history
    })


@app.route("/api/history/clear", methods=["POST"])
def clear_history():
    """Clears all stored run history in memory and on disk."""
    global run_history
    run_history = []
    _save_run_history()
    logger.info("Run history cleared by user request.")
    return jsonify({
        "success": True,
        "message": "Run history cleared successfully.",
        "history": []
    })


@app.route("/api/history/export", methods=["GET"])
def export_history_csv():
    """Exports run history as a CSV file download."""
    global run_history
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Header
    writer.writerow([
        "Timestamp",
        "Mode",
        "Lighting",
        "North Count",
        "South Count",
        "East Count",
        "West Count",
        "Total Vehicles",
        "North Green (s)",
        "South Green (s)",
        "East Green (s)",
        "West Green (s)",
        "Wait Reduction (%)",
        "Emergency Road",
        "North Actual",
        "South Actual",
        "East Actual",
        "West Actual",
        "MAE"
    ])
    
    for item in run_history:
        counts = item.get("counts", {})
        greens = item.get("green_times", {})
        is_emerg = bool(item.get("emergency_road"))
        wait_val = "" if is_emerg else (item.get("wait_reduction_pct", "") if item.get("wait_reduction_pct") is not None else "")
        acc = item.get("accuracy_report") or {}
        per_road = acc.get("per_road", {}) if isinstance(acc, dict) else {}
        mae_val = acc.get("mae", "") if isinstance(acc, dict) and acc.get("mae") is not None else ""

        writer.writerow([
            item.get("timestamp", ""),
            item.get("mode", ""),
            item.get("lighting", ""),
            counts.get("north", 0),
            counts.get("south", 0),
            counts.get("east", 0),
            counts.get("west", 0),
            item.get("total_vehicles", 0),
            greens.get("north", 0),
            greens.get("south", 0),
            greens.get("east", 0),
            greens.get("west", 0),
            wait_val,
            item.get("emergency_road") or "None",
            per_road.get("north", {}).get("actual", "") if per_road.get("north", {}).get("actual") is not None else "",
            per_road.get("south", {}).get("actual", "") if per_road.get("south", {}).get("actual") is not None else "",
            per_road.get("east", {}).get("actual", "") if per_road.get("east", {}).get("actual") is not None else "",
            per_road.get("west", {}).get("actual", "") if per_road.get("west", {}).get("actual") is not None else "",
            mae_val
        ])
    
    csv_data = output.getvalue()
    return Response(
        csv_data,
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment;filename=traffic_run_history.csv"}
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 60)
    print("  AI-Based Smart Traffic Signal Optimization Server")
    print("  Night-Mode & Low-Light Enhancement Enabled")
    print("  Running at: http://127.0.0.1:5000")
    print("=" * 60)
    app.run(host="0.0.0.0", port=5000, debug=True)
