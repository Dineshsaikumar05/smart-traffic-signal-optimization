# 🚦 AI-Based Smart Traffic Signal Optimization

A real-time, AI-powered 4-way junction traffic signal control system built with **Python (Flask + OpenCV + YOLOv8)** and a responsive web UI. The signal plan (green times, service order, junction animation, phase timeline, charts, summary, and history) is driven **strictly by computer vision detection counts** analyzed from uploaded corridor camera feeds.

Includes advanced low-light enhancement, a 4-tier image/video decoding hierarchy, duplicate media cross-checking, ground truth accuracy tracking (MAE & MPE), automated detection recovery, model architecture selection (YOLOv8s / YOLOv8n / YOLOv8m), and a live multi-threshold confidence sweep tool.

---

## 🖥️ System Architecture & Workflow

### 1. Detected Counts Exclusively Drive the Signal Plan
- The signal timing schedule, phase timeline, junction lights, and performance summary are **strictly driven by actual counts detected through "Analyze Traffic"**.
- Simulations and synthetic benchmark tools live inside a separate, collapsible **Test tools (random data, for testing only)** container and do not overwrite verified camera analysis.
- Once analyzed, measured counts persist across emergency overrides and clearing phases until the next **Analyze Traffic** or **Reset**.

### 2. First-Load State
- On launch or Reset, the dashboard displays a clear notice:  
  `"Waiting for photos: upload one image or video per road and click Analyze Traffic"`
- Traffic signals run on a neutral, equal fixed plan (30 seconds per corridor), clearly labeled `"Default fixed timer (no data yet)"`.
- Vehicle count fields display `"—"` rather than unmeasured or synthetic numbers.
- Emergency corridor overrides remain securely disabled with an `"Analyze traffic first"` tooltip until real traffic feeds have been analyzed.

### 3. Partial Corridor Uploads
- When camera feeds are uploaded for a subset of approaches, the system analyzes those approaches with AI vision.
- For non-uploaded approaches:
  - If a previous analyzed count exists, it is retained and marked **"Previous"**.
  - If no prior count exists, the corridor is treated as **"no data"**, assigned the minimum green duration (10s), excluded from traffic share calculations, and badged **"No data"**.

---

## ⚡ Detection & Computer Vision Capabilities

| Capability | Details |
|---|---|
| **Primary AI Models** | **YOLOv8s** (default), **YOLOv8n**, and **YOLOv8m** supporting COCO vehicle classes (`car`, `motorcycle`, `bus`, `truck`). |
| **Detection Recovery** | If an uploaded image yields $\le 1$ detected vehicle at the user's confidence setting, an automatic recovery retry runs at confidence `0.15` and resolution `1280px`. The system adopts the superior result and logs the recovery parameters. |
| **4-Tier Media Decoder** | Decodes images and video through `OpenCV` $\to$ `Pillow + AVIF` $\to$ `pillow-heif` $\to$ `FFmpeg`. Corrupt or unsupported files report clear inline error banners without crashing or blocking other valid corridors. |
| **Supported Formats** | Images: `.jpg`, `.jpeg`, `.png`, `.bmp`, `.webp`, `.avif`, `.heic`, `.heif`.<br>Videos: `.mp4`, `.avi`, `.mov`, `.webm`. |
| **Dual-Cue Lighting Analysis** | Automatically classifies scenes into **Day** ($\ge 100$), **Dusk** ($60\text{--}100$), or **Night** ($< 60$) using mean brightness corroborated by dark-pixel ratio and color saturation. Per-road manual override (`Auto / Day / Dusk / Night`) supported. |
| **Low-Light Night Boost** | LAB-space CLAHE, adaptive gamma boost, and dual-headlight blob pairing algorithms. Applied strictly during dusk or night. |
| **Duplicate Media Detection** | Computes cryptographic image hashes; flags identical media across corridors and warns if disparate ground truth actual counts are entered. |
| **Confidence Sweep Tool** | In Detection Settings, click **Run confidence sweep** to automatically benchmark detections across thresholds (`0.20`, `0.30`, `0.40`, `0.50`), rendering a side-by-side comparison table against ground truth counts. |

---

## 📊 Ground Truth Accuracy Tracking

Each road card includes an optional **Actual count** ground truth field:
- **Per-Road Feedback**: Displays `🎯 Detected X vs Actual Y (error Z%)` on the card after analysis.
- **Accuracy Report Panel**: Computes Mean Absolute Error (**MAE**) and Mean Percentage Error (**MPE**) strictly over successfully analyzed approaches.
- **History & CSV Export**: All actual counts, error percentages, and MAE values are archived to the persistent run history and exported in the CSV report.

---

## ⚙️ Setup & Installation

### 1. Prerequisites
- **Python 3.10+** (Python 3.13 tested)
- **pip** package manager

### 2. Install Dependencies
```bash
git clone <repo-url>
cd traffic_project
pip install -r requirements.txt
playwright install chromium
```

Key dependencies:
- `flask>=3.0.0`
- `opencv-python>=4.8.0`
- `ultralytics>=8.4.0` (YOLOv8)
- `pillow>=10.0.0`
- `pillow-avif-plugin>=1.4.3`
- `pillow-heif>=0.18.0`
- `imageio-ffmpeg>=0.4.9`
- `playwright>=1.40.0`

### 3. Run Application
```bash
python app.py
```
Open **[http://127.0.0.1:5000](http://127.0.0.1:5000)** in your web browser.

---

## 🧪 Automated Verification & Test Suites

The repository contains three comprehensive automated test suites:

### 1. Backend Integration Suite
```bash
python test_suite.py
```
*Validates simulation lighting, emergency preemptions, edge cases (zero counts, extreme congestion), 413 file size bounds, partial uploads, corrupt file recovery, and 120s cycle conservation with 100% pass rate.*

### 2. Multi-Format, Recovery & Accuracy Verification Suite
```bash
python -m unittest test_upload_formats.py
```
*Validates AVIF/HEIC/WebP/MP4 ingestion, 4-tier decoder fallbacks, confidence 0.15 recovery retries, model selection (YOLOv8s/n/m), ground truth MAE/MPE reporting, duplicate detection, and clean emergency transitions.*

### 3. Visual Layout & Responsiveness Suite (Playwright)
```bash
python ui_check.py
```
*Tests live rendering across 5 key viewports (`1440px desktop`, `1366px laptop`, `1032px small laptop`, `768px tablet`, `390px mobile`). Verifies first-load notices, disabled emergency buttons, bounding box widths $> 60\text{px}$ on all road titles, zero horizontal scroll, and saves screenshots to `screenshots/`.*

---

## 🔌 REST API Reference

| Endpoint | Method | Description |
|---|---|---|
| `/` | GET | Interactive Traffic Control Dashboard |
| `/api/status` | GET | Current live junction state, green times, order, and metadata |
| `/api/upload` | POST | Primary analysis endpoint: processes multipart image/video files with YOLOv8 |
| `/api/confidence_sweep` | POST | Evaluates detections across confidence thresholds (0.20, 0.30, 0.40, 0.50) |
| `/api/emergency` | POST | Triggers 60s priority override on designated corridor using analyzed counts |
| `/api/emergency/clear` | POST/GET | Reverts active emergency to underlying adaptive cycle |
| `/api/simulate` | POST | Generates random test data inside Test Tools container |
| `/api/samples` | POST | Loads synthetic test benchmarks inside Test Tools container |
| `/api/reset` | GET/POST | Re-initializes dashboard to the first-load waiting state |
| `/api/summary` | GET | Performance KPIs, wait reduction %, and clearance efficiency |
| `/api/history` | GET | Retrieves last 20 optimization history entries |
| `/api/history/clear` | POST | Clears optimization history with confirmation |
| `/api/history/export` | GET | Downloads CSV export including ground truth actual counts and MAE |

---

*AI-Based Smart Traffic Signal Optimization — 2026*
