import csv

with open("test_upload_formats.py", "r", encoding="utf-8") as f:
    content = f.read()

# 1. Fix test_history_emergency_delay_reduction_empty CSV parsing
old_csv_split = 'cols = [c.strip() for c in last_line.split(",")]'
new_csv_split = 'cols = [c.strip() for c in next(csv.reader([last_line]))]'

if old_csv_split in content:
    content = content.replace(old_csv_split, new_csv_split)
else:
    print("WARNING: old_csv_split not found")

# 2. Fix test_upload_history_rows_naming to use real_day_traffic.jpg
old_upload_imgs = '''        with open("static/samples/sample_north.jpg", "rb") as fn, open("static/samples/sample_south.jpg", "rb") as fs:
            buf_n = io.BytesIO(fn.read())
            buf_s = io.BytesIO(fs.read())'''

new_upload_imgs = '''        with open("static/samples/real_day_traffic.jpg", "rb") as fn, open("static/samples/real_day_traffic.jpg", "rb") as fs:
            buf_n = io.BytesIO(fn.read())
            buf_s = io.BytesIO(fs.read())'''

if old_upload_imgs in content:
    content = content.replace(old_upload_imgs, new_upload_imgs)
elif 'buf_n = self._create_dummy_image(fmt="JPEG")' in content:
    content = content.replace(
'''        buf_n = self._create_dummy_image(fmt="JPEG")
        buf_s = self._create_dummy_image(fmt="JPEG")''',
'''        with open("static/samples/real_day_traffic.jpg", "rb") as fn, open("static/samples/real_day_traffic.jpg", "rb") as fs:
            buf_n = io.BytesIO(fn.read())
            buf_s = io.BytesIO(fs.read())'''
    )

with open("test_upload_formats.py", "w", encoding="utf-8") as f:
    f.write(content)

print("test_upload_formats.py updated.")

