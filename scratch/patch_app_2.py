with open("app.py", "r", encoding="utf-8") as f:
    content = f.read()

# 1. Fix engine_used casing in /api/upload
old_engine_code = '''            engine_used = road_meta.get("engine")
            if not engine_used or "yolo" in engine_used.lower():
                engine_used = model_choice.upper() if "yolo" in model_choice.lower() else f"YOLOv8{model_choice[-1]}"
            road_meta["engine"] = engine_used'''

new_engine_code = '''            engine_used = road_meta.get("engine")
            model_map = {"yolov8n": "YOLOv8n", "yolov8s": "YOLOv8s", "yolov8m": "YOLOv8m"}
            if not engine_used or "yolo" in engine_used.lower():
                engine_used = model_map.get(model_choice, f"YOLOv8{model_choice[-1]}")
            road_meta["engine"] = engine_used'''

if old_engine_code in content:
    content = content.replace(old_engine_code, new_engine_code, 1)
else:
    print("WARNING: old_engine_code not found")

# 2. Fix simulate data_source and mode
old_sim_mode = '''    timing_data["mode"] = "Test (random data)"
    timing_data["underlying_mode"] = "Test (random data)"
    timing_data["data_source"] = "test"
    timing_data["history_mode"] = "Test"'''

new_sim_mode = '''    timing_data["mode"] = f"Test (random data) - Simulation ({selected_lighting.capitalize()})"
    timing_data["underlying_mode"] = "Simulation"
    timing_data["data_source"] = "simulation"
    timing_data["history_mode"] = "Simulation"'''

if old_sim_mode in content:
    content = content.replace(old_sim_mode, new_sim_mode, 1)
else:
    print("WARNING: old_sim_mode not found")

# 3. In emergency endpoint, check source_state
old_emerg_check = '''    # Requirement A5: Emergency buttons use last analyzed counts.
    # Block if no analyze has run yet.
    if not last_analyzed_state or not last_analyzed_state.get("has_analyzed_data"):
        return jsonify({
            "success": False,
            "error": "Analyze traffic first",
        }), 400

    current_counts: dict = {}
    for r in ROADS:
        current_counts[r] = last_analyzed_state["roads"][r].get("count")'''

new_emerg_check = '''    # Requirement A5: Emergency buttons use last analyzed counts.
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
        current_counts[r] = source_state["roads"][r].get("count")'''

if old_emerg_check in content:
    content = content.replace(old_emerg_check, new_emerg_check, 1)
else:
    print("WARNING: old_emerg_check not found")

# Also in emergency road metadata copy:
old_meta_copy = 'old_road_meta = copy.deepcopy(last_analyzed_state["roads"].get(r, {}))'
new_meta_copy = 'old_road_meta = copy.deepcopy(source_state["roads"].get(r, {}))'
if old_meta_copy in content:
    content = content.replace(old_meta_copy, new_meta_copy)

old_underlying = 'timing_data["underlying_mode"] = last_analyzed_state.get("underlying_mode", "Upload")'
new_underlying = 'timing_data["underlying_mode"] = source_state.get("underlying_mode", "Upload")'
if old_underlying in content:
    content = content.replace(old_underlying, new_underlying)

with open("app.py", "w", encoding="utf-8") as f:
    f.write(content)

print("app.py patch applied.")

