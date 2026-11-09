"""
test_detector.py - Vehicle Detection Test Script

Runs vehicle detection using YOLOv8 (with OpenCV vision fallback)
on sample traffic images and prints vehicle counts, detected lighting,
brightness levels, and active engine telemetry.
"""

import os
import sys
import time
from detector import count_vehicles, get_detection_metadata, get_yolo_model

def run_test():
    print("=" * 60)
    print("AI SMART TRAFFIC SIGNAL - VEHICLE DETECTOR TEST")
    print("=" * 60)

    # Priority test images: real day traffic, real night traffic, or sample north
    candidates = [
        "static/samples/real_day_traffic.jpg",
        "static/samples/real_night_traffic.jpg",
        "static/samples/sample_north.jpg"
    ]

    test_image = None
    for c in candidates:
        if os.path.exists(c):
            test_image = c
            break

    if not test_image:
        print("ERROR: No sample image found in static/samples/")
        sys.exit(1)

    print(f"Testing input image : {test_image}")
    start_t = time.time()

    # Test with default conf_threshold=0.30
    count, proc_path, lighting_mode, brightness = count_vehicles(
        test_image,
        output_dir="static/processed",
        conf_threshold=0.30
    )
    elapsed = time.time() - start_t

    meta = get_detection_metadata(proc_path)
    engine = meta.get("engine", "Unknown")
    pipeline = meta.get("pipeline", "Standard Vision")

    print("-" * 60)
    print(f"Vehicle Count Detected : {count}")
    print(f"Lighting Mode Detected : {lighting_mode.upper()} (Brightness: {brightness:.1f})")
    print(f"Detection Engine Used  : {engine}")
    print(f"Vision Pipeline        : {pipeline}")
    print(f"Output Annotated Feed  : {proc_path}")
    print(f"Inference Time         : {elapsed * 1000:.1f} ms")
    print("-" * 60)

    # Also test on real night traffic if present
    night_img = "static/samples/real_night_traffic.jpg"
    if os.path.exists(night_img) and night_img != test_image:
        print(f"\nTesting night input image: {night_img}")
        t0 = time.time()
        c_n, p_n, l_n, b_n = count_vehicles(night_img, output_dir="static/processed", conf_threshold=0.30)
        el_n = time.time() - t0
        meta_n = get_detection_metadata(p_n)
        print(f"Night Vehicle Count   : {c_n}")
        print(f"Night Mode Detected   : {l_n.upper()} (Brightness: {b_n:.1f})")
        print(f"Night Engine / Pipe   : {meta_n.get('engine')} | {meta_n.get('pipeline')}")
        print(f"Night Inference Time  : {el_n * 1000:.1f} ms")

    print("\n[SUCCESS] Vehicle detector test executed successfully!")
    print("=" * 60)

if __name__ == "__main__":
    run_test()

