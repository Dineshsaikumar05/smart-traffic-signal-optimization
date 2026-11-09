with open("app.py", "r", encoding="utf-8") as f:
    content = f.read()

# 1. In /api/upload error branches, set data_source = "sample", is_sample = True
content = content.replace(
'''                    "engine": "Upload failed",
                    "data_source": "none",
                    "upload_failed": True,
                    "error_reason": f"Unsupported format '{fname}'",
                    "is_sample": False,''',
'''                    "engine": "Upload failed",
                    "data_source": "sample",
                    "upload_failed": True,
                    "error_reason": f"Unsupported format '{fname}'",
                    "is_sample": True,'''
)

content = content.replace(
'''                    "engine": "Upload failed",
                    "data_source": "none",
                    "upload_failed": True,
                    "error_reason": f"Save failed: {exc}",
                    "is_sample": False,''',
'''                    "engine": "Upload failed",
                    "data_source": "sample",
                    "upload_failed": True,
                    "error_reason": f"Save failed: {exc}",
                    "is_sample": True,'''
)

content = content.replace(
'''                    "engine": "Upload failed",
                    "data_source": "none",
                    "upload_failed": True,
                    "error_reason": f"Undecodable media '{fname}'",
                    "is_sample": False,''',
'''                    "engine": "Upload failed",
                    "data_source": "sample",
                    "upload_failed": True,
                    "error_reason": f"Undecodable media '{fname}'",
                    "is_sample": True,'''
)

# 2. In /api/emergency, set data_source and is_test_data from source_state
old_emerg_timing = '''    timing_data["mode"] = f"Emergency Override ({road.capitalize()})"
    timing_data["underlying_mode"] = source_state.get("underlying_mode", "Upload")
    timing_data["data_source"] = "upload"
    timing_data["has_analyzed_data"] = True'''

new_emerg_timing = '''    timing_data["mode"] = f"Emergency Override ({road.capitalize()})"
    timing_data["underlying_mode"] = source_state.get("underlying_mode", "Upload")
    timing_data["data_source"] = source_state.get("data_source", "simulation" if source_state.get("is_test_data") else "upload")
    timing_data["has_analyzed_data"] = source_state.get("has_analyzed_data", False)
    timing_data["is_test_data"] = source_state.get("is_test_data", False)'''

if old_emerg_timing in content:
    content = content.replace(old_emerg_timing, new_emerg_timing, 1)

# 3. In /api/emergency/clear, fix source_state handling
old_clear_code = '''    if last_analyzed_state and last_analyzed_state.get("has_analyzed_data"):
        current_counts = {r: last_analyzed_state["roads"][r].get("count") for r in ROADS}
        timing_data = calculate_signal_timings(current_counts, emergency_road=None)
        for r in ROADS:
            old_meta = copy.deepcopy(last_analyzed_state["roads"].get(r, {}))
            timing_data["roads"][r].update(old_meta)
            timing_data["roads"][r]["is_emergency"] = False
        timing_data["mode"] = last_analyzed_state.get("mode", "Upload")
        timing_data["underlying_mode"] = source_state.get("underlying_mode", "Upload")
        timing_data["data_source"] = "upload"
        timing_data["has_analyzed_data"] = True
        timing_data["emergency_road"] = None
        timing_data["timestamp"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        timing_data["is_night_mode"] = any(
            r.get("lighting_mode") == "night" for r in timing_data["roads"].values()
        )
    else:
        initialize_default_traffic_state()
        timing_data = latest_result'''

new_clear_code = '''    source_state = last_analyzed_state if (last_analyzed_state and last_analyzed_state.get("has_analyzed_data")) else None
    if not source_state and latest_result and latest_result.get("is_test_data"):
        source_state = latest_result

    if source_state and any(source_state.get("roads", {}).get(r, {}).get("count") is not None for r in ROADS):
        current_counts = {r: source_state["roads"][r].get("count") for r in ROADS}
        timing_data = calculate_signal_timings(current_counts, emergency_road=None)
        for r in ROADS:
            old_meta = copy.deepcopy(source_state["roads"].get(r, {}))
            timing_data["roads"][r].update(old_meta)
            timing_data["roads"][r]["is_emergency"] = False
        timing_data["mode"] = source_state.get("mode", "Upload")
        timing_data["underlying_mode"] = source_state.get("underlying_mode", "Upload")
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
        timing_data = latest_result'''

if old_clear_code in content:
    content = content.replace(old_clear_code, new_clear_code, 1)

with open("app.py", "w", encoding="utf-8") as f:
    f.write(content)

print("app.py updated.")

# Now update test_upload_history_rows_naming in test_upload_formats.py
with open("test_upload_formats.py", "r", encoding="utf-8") as f:
    tf_content = f.read()

# In test_upload_history_rows_naming, use sample images with vehicle counts > 0
old_tf_history = '''    def test_upload_history_rows_naming(self):
        """Item 3: Label rows as 'Upload (N, E)' naming uploaded roads + filenames, un-uploaded roads marked sample."""
        buf_n = self._create_dummy_image(fmt="JPEG")
        buf_s = self._create_dummy_image(fmt="JPEG")
        data = {
            "north": (buf_n, "street_north.jpg"),
            "south": (buf_s, "street_south.jpg")
        }'''

new_tf_history = '''    def test_upload_history_rows_naming(self):
        """Item 3: Label rows as 'Upload (N, E)' naming uploaded roads + filenames, un-uploaded roads marked sample."""
        # Use actual images so total vehicles > 0, ensuring history is recorded
        with open("static/samples/sample_north.jpg", "rb") as fn, open("static/samples/sample_south.jpg", "rb") as fs:
            buf_n = io.BytesIO(fn.read())
            buf_s = io.BytesIO(fs.read())
        data = {
            "north": (buf_n, "street_north.jpg"),
            "south": (buf_s, "street_south.jpg")
        }'''

if old_tf_history in tf_content:
    tf_content = tf_content.replace(old_tf_history, new_tf_history, 1)

with open("test_upload_formats.py", "w", encoding="utf-8") as f:
    f.write(tf_content)

print("test_upload_formats.py updated.")

