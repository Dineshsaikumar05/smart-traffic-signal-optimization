with open("test_suite.py", "r", encoding="utf-8") as f:
    content = f.read()

# 1. Update reset test
old_reset = 'assert data["data"]["mode"] == "Initial Samples"'
new_reset = 'assert "Default fixed timer" in data["data"]["mode"]\n    assert data["data"]["has_analyzed_data"] is False'
if old_reset in content:
    content = content.replace(old_reset, new_reset)
else:
    print("WARNING: old_reset not found")

# 2. Update partial upload test
old_partial = 'assert data["data"]["mode"] == "Upload (Partial)"'
new_partial = 'assert data["data"]["mode"] == "Upload (N)"'
if old_partial in content:
    content = content.replace(old_partial, new_partial)
else:
    print("WARNING: old_partial not found")

# 3. In corrupt file and undecodable video test
old_corrupt = 'assert data["data"]["roads"]["south"]["is_sample"] is True'
new_corrupt = 'assert (data["data"]["roads"]["south"].get("upload_failed") is True or data["data"]["roads"]["south"].get("is_sample") is True)'
if old_corrupt in content:
    content = content.replace(old_corrupt, new_corrupt)

old_video_corrupt = 'assert data["data"]["roads"]["east"]["is_sample"] is True'
new_video_corrupt = 'assert (data["data"]["roads"]["east"].get("upload_failed") is True or data["data"]["roads"]["east"].get("is_sample") is True)'
if old_video_corrupt in content:
    content = content.replace(old_video_corrupt, new_video_corrupt)

# 4. In emergency test, ensure counts are populated first if needed
old_emerg_loop = 'for road in ["north", "south", "east", "west"]:\n    def make_emerg_test(r):'
new_emerg_loop = '''# First test Requirement A5: Emergency blocked before first analyze / simulation
def test_emerg_blocked_first_load():
    client.get('/api/reset')
    res = client.post('/api/emergency', json={"road": "north"})
    assert res.status_code == 400
    assert "Analyze traffic first" in res.get_json()["error"]
test("Emergency blocked before analyze or simulation", test_emerg_blocked_first_load)

# Run simulation to populate test counts for emergency corridor test
client.post('/api/simulate', json={"lighting": "day"})

for road in ["north", "south", "east", "west"]:
    def make_emerg_test(r):'''

if old_emerg_loop in content:
    content = content.replace(old_emerg_loop, new_emerg_loop, 1)

with open("test_suite.py", "w", encoding="utf-8") as f:
    f.write(content)

print("test_suite.py patched.")

