"""
detector.py - Vehicle Detection Module with Night-Mode / Low-Light Detection

Detects vehicles in image (.jpg, .jpeg, .png, .bmp, .webp, .avif) and video (.mp4, .avi, .mov, .webm) feeds.
Includes intelligent lighting analysis (Day, Dusk, Night), low-light enhancement
(adaptive gamma, LAB CLAHE, and bilateral denoising), and specialized dual-blob
headlight / motorcycle detection for dark nighttime scenes.
Supports YOLOv8 when ultralytics is installed, with an optimized OpenCV vision pipeline fallback.
Unsupported image formats are decoded via Pillow (with pillow-avif-plugin for AVIF) before detection.
"""

import os
import time
import uuid
import random
from typing import Tuple, Optional, List, Dict, Any
import cv2
import numpy as np

# Optional Pillow import for format fallback (webp, avif, bmp, etc.)
try:
    from PIL import Image as _PilImage
    # Register AVIF plugin if available
    try:
        import pillow_avif  # noqa: F401
    except ImportError:
        pass
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

# Optional pillow-heif import for HEIF/HEIC support
try:
    import pillow_heif
    pillow_heif.register_heif_opener()
    HEIF_AVAILABLE = True
except ImportError:
    HEIF_AVAILABLE = False

# Configurable lighting thresholds (Mean V channel in HSV: 0-255)
# Requirement 12: Day >= 100, Dusk 60-100, Night < 60
BRIGHTNESS_THRESHOLD_DAY = 100.0
BRIGHTNESS_THRESHOLD_DUSK = 60.0

# Check if ultralytics is installed
try:
    # pyrefly: ignore [missing-import]
    from ultralytics import YOLO
    YOLO_AVAILABLE = True
    _YOLO_MODEL = None
except ImportError:
    YOLO_AVAILABLE = False
    _YOLO_MODEL = None

# COCO vehicle class IDs for YOLO: 2: car, 3: motorcycle, 5: bus, 7: truck
VEHICLE_CLASSES = {2: "Car", 3: "Motorcycle", 5: "Bus", 7: "Truck"}

# In-memory metadata cache for detailed road view inspection (original vs enhanced vs pipeline)
DETECTION_METADATA: Dict[str, Dict[str, Any]] = {}


# Multi-model YOLO cache (yolov8s, yolov8n, yolov8m)
_YOLO_MODELS: Dict[str, Any] = {}


def get_yolo_model(model_name: str = "yolov8s"):
    """
    Lazily loads the requested YOLOv8 model (yolov8s, yolov8n, or yolov8m).
    Defaults to yolov8s. If ultralytics is not available or loading fails,
    attempts fallbacks before returning None for OpenCV fallback.
    """
    global _YOLO_MODELS, YOLO_AVAILABLE
    if not YOLO_AVAILABLE:
        return None

    clean = (model_name or "yolov8s").lower().strip()
    if "yolov8m" in clean or clean == "m":
        key = "yolov8m"
    elif "yolov8n" in clean or clean == "n":
        key = "yolov8n"
    else:
        key = "yolov8s"

    if key in _YOLO_MODELS and _YOLO_MODELS[key] is not None:
        return _YOLO_MODELS[key]

    target_pt = f"{key}.pt"
    if os.path.exists(target_pt):
        try:
            _YOLO_MODELS[key] = YOLO(target_pt)
            return _YOLO_MODELS[key]
        except Exception as e:
            print(f"[detector.py] Error loading {target_pt}: {e}")

    # Fallbacks: try yolov8s, then yolov8n
    for fb in ["yolov8s.pt", "yolov8n.pt"]:
        if os.path.exists(fb):
            try:
                fb_key = os.path.splitext(fb)[0]
                if fb_key not in _YOLO_MODELS or _YOLO_MODELS[fb_key] is None:
                    _YOLO_MODELS[fb_key] = YOLO(fb)
                return _YOLO_MODELS[fb_key]
            except Exception as e:
                print(f"[detector.py] Fallback load {fb} failed: {e}")

    return None


def get_yolo_engine_name(model_name: str = "yolov8s") -> str:
    """Returns canonical display name for the model (e.g. YOLOv8s, YOLOv8n, YOLOv8m)."""
    clean = (model_name or "yolov8s").lower().strip()
    if "yolov8m" in clean or clean == "m":
        return "YOLOv8m"
    elif "yolov8n" in clean or clean == "n":
        return "YOLOv8n"
    return "YOLOv8s"


def analyze_lighting(frame: np.ndarray, override: Optional[str] = None) -> Tuple[str, float, bool]:
    """
    Computes ambient scene brightness and evaluates whether low-light enhancement
    pipeline should be engaged.

    Classification (Requirement 12):
      - Day: brightness >= 100.0
      - Dusk: 60.0 <= brightness < 100.0
      - Night: brightness < 60.0
    Second cue:
      - dark_pixel_ratio: share of pixels with V < 50
      - mean_saturation: mean S channel in HSV
      Confirms low-light pipeline when mode is dusk or night.
    Override:
      'day', 'dusk', 'night', or 'auto'/None.

    Parameters:
        frame (np.ndarray): Input image frame in BGR format.
        override (str, optional): User override ("auto", "day", "dusk", "night").

    Returns:
        tuple: (mode: str ["day", "dusk", "night"], brightness: float, apply_low_light: bool)
    """
    if frame is None or frame.size == 0:
        return "day", 140.0, False

    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    v_channel = hsv[:, :, 2]
    s_channel = hsv[:, :, 1]
    mean_v = float(np.mean(v_channel))
    mean_s = float(np.mean(s_channel))
    dark_pixel_ratio = float(np.mean(v_channel < 50))

    clean_override = (override or "auto").lower().strip()
    if clean_override in ("day", "dusk", "night"):
        mode = clean_override
        # Low-light enhancement applied only for dusk or night
        apply_low_light = (mode in ("dusk", "night"))
    else:
        # Automatic classification based on thresholds and second cues
        if mean_v >= BRIGHTNESS_THRESHOLD_DAY:
            mode = "day"
            apply_low_light = False
        elif mean_v >= BRIGHTNESS_THRESHOLD_DUSK:
            mode = "dusk"
            # Second cue for dusk: confirmed by dark pixel ratio >= 0.08 or lower saturation
            apply_low_light = (dark_pixel_ratio >= 0.08 or mean_s < 130)
        else:
            mode = "night"
            # Night is always low-light
            apply_low_light = True

    return mode, round(mean_v, 1), apply_low_light


def enhance_low_light(frame: np.ndarray, brightness: Optional[float] = None) -> np.ndarray:
    """
    Enhances low-light and nighttime frames using:
    1. Adaptive Gamma correction (lower gamma for darker scenes to boost shadow detail).
    2. CLAHE (Contrast Limited Adaptive Histogram Equalization) on L-channel in LAB space.
    3. Mild denoising via bilateral filtering to suppress sensor noise while preserving vehicle edges.

    Parameters:
        frame (np.ndarray): Input BGR image.
        brightness (float, optional): Pre-computed mean brightness. If None, computed automatically.

    Returns:
        np.ndarray: Contrast-enhanced and denoised BGR image.
    """
    if frame is None or frame.size == 0:
        return frame

    if brightness is None:
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        brightness = float(np.mean(hsv[:, :, 2]))

    # 1. Adaptive Gamma Correction: gamma < 1.0 brightens underexposed pixels
    # For dark night (brightness < 60): gamma in [0.35, 0.65]
    # For dusk (brightness 60-120): gamma in [0.65, 0.90]
    gamma = float(np.clip(0.35 + (brightness / 120.0) * 0.50, 0.32, 0.95))
    lut = np.array([np.clip(((i / 255.0) ** gamma) * 255.0, 0, 255) for i in range(256)]).astype(np.uint8)
    gamma_corrected = cv2.LUT(frame, lut)

    # 2. CLAHE on L channel in LAB color space
    lab = cv2.cvtColor(gamma_corrected, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=2.8, tileGridSize=(8, 8))
    cl = clahe.apply(l)
    enhanced_lab = cv2.merge((cl, a, b))
    enhanced_bgr = cv2.cvtColor(enhanced_lab, cv2.COLOR_LAB2BGR)

    # 3. Mild denoising using bilateral filter (preserves crisp vehicle contours)
    denoised = cv2.bilateralFilter(enhanced_bgr, d=5, sigmaColor=32, sigmaSpace=32)
    return denoised


def detect_headlights(frame: np.ndarray) -> Tuple[int, List[Dict[str, Any]], np.ndarray]:
    """
    Detects vehicles in night scenes by analyzing headlight signatures:
    - Thresholds intense bright pixels.
    - Matches blob pairs of similar size at similar vertical positions (treated as 1 vehicle).
    - Detects single large bright blobs as motorcycles.

    Parameters:
        frame (np.ndarray): Input image (original or low-light frame).

    Returns:
        tuple: (count: int, vehicles: List[dict], annotated_frame: np.ndarray)
    """
    annotated = frame.copy()
    h, w = frame.shape[:2]

    # Road corridor margins (exclude sidewalks/curbs to avoid street lamps)
    curb_margin = 28
    road_x1 = curb_margin
    road_x2 = w - curb_margin

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

    # Threshold very bright pixels (headlight cores)
    _, thresh = cv2.threshold(gray, 195, 255, cv2.THRESH_BINARY)

    # Morphological opening to eliminate isolated noise flecks
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    cleaned = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, kernel, iterations=1)

    contours, _ = cv2.findContours(cleaned, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    blobs = []
    for cnt in contours:
        area = cv2.contourArea(cnt)
        if 6 <= area <= 2500:
            x, y, bw, bh = cv2.boundingRect(cnt)
            cx = x + bw / 2.0
            cy = y + bh / 2.0
            # Ensure candidate lights are on the active road surface
            if (road_x1 <= cx <= road_x2) and (35 <= cy <= h - 25):
                blobs.append({
                    "x": x, "y": y, "w": bw, "h": bh,
                    "cx": cx, "cy": cy, "area": area,
                    "paired": False
                })

    # Sort blobs horizontally
    blobs.sort(key=lambda b: b["cx"])

    vehicles = []

    # 1. Pair matching for dual-headlight vehicles (Cars, Trucks, Buses)
    for i in range(len(blobs)):
        if blobs[i]["paired"]:
            continue
        b1 = blobs[i]
        best_j = -1
        min_dx = 9999.0

        for j in range(i + 1, len(blobs)):
            if blobs[j]["paired"]:
                continue
            b2 = blobs[j]

            dx = abs(b1["cx"] - b2["cx"])
            dy = abs(b1["cy"] - b2["cy"])

            # Must be vertically aligned (similar elevation on roadway)
            if dy > 14:
                continue

            # Must have standard vehicle headlight separation (12px to 55px)
            if 12 <= dx <= 55:
                area_ratio = min(b1["area"], b2["area"]) / max(b1["area"], b2["area"])
                if area_ratio >= 0.22:
                    if dx < min_dx:
                        min_dx = dx
                        best_j = j

        if best_j != -1:
            b2 = blobs[best_j]
            b1["paired"] = True
            b2["paired"] = True

            vx1 = max(0, int(min(b1["x"], b2["x"]) - 4))
            vy1 = max(0, int(min(b1["y"], b2["y"]) - 18))
            vx2 = min(w, int(max(b1["x"] + b1["w"], b2["x"] + b2["w"]) + 4))
            vy2 = min(h, int(max(b1["y"] + b1["h"], b2["y"] + b2["h"]) + 14))

            vehicles.append({
                "type": "Car (Headlights)",
                "box": (vx1, vy1, vx2, vy2),
                "is_pair": True
            })

    # 2. Unpaired large bright blobs counted as motorcycles
    for b in blobs:
        if not b["paired"]:
            if b["area"] >= 18 or (b["w"] >= 5 and b["h"] >= 5):
                vx1 = max(0, int(b["x"] - 5))
                vy1 = max(0, int(b["y"] - 14))
                vx2 = min(w, int(b["x"] + b["w"] + 5))
                vy2 = min(h, int(b["y"] + b["h"] + 10))
                vehicles.append({
                    "type": "Motorcycle (Light)",
                    "box": (vx1, vy1, vx2, vy2),
                    "is_pair": False
                })

    return len(vehicles), vehicles, annotated


def count_vehicles(
    file_path: str,
    output_dir: str = "static/processed",
    conf_threshold: float = 0.30,
    iou_threshold: float = 0.5,
    imgsz: int = 960,
    model_name: str = "yolov8s",
    lighting_override: Optional[str] = None
) -> Tuple[int, Optional[str], str, float]:
    """
    Analyzes an image or video file:
    - Calls analyze_lighting to classify ambient scene into Day, Dusk, or Night.
    - Day: normal detection pipeline (YOLOv8 primary with conf_threshold, iou_threshold, imgsz).
    - Dusk: enhance_low_light, then detection pipeline.
    - Night: enhance_low_light, then detection AND detect_headlights (final count is max of both).
    - Detection Recovery: for uploaded images returning 0 or 1 vehicles, automatically retries
      at conf 0.15 and imgsz 1280 and adopts the superior count.
    - Annotates bounding boxes, HUD telemetry, and lighting/night-mode tags.
    - Saves annotated output to output_dir.

    Parameters:
        file_path (str): Path to input image or video file.
        output_dir (str): Directory where processed images are saved.
        conf_threshold (float): Detection confidence threshold (0.10 to 0.70, default: 0.30).
        iou_threshold (float): NMS IoU threshold (default: 0.50).
        imgsz (int): Image size for YOLO inference (default: 960 for dense scenes).
        model_name (str): YOLOv8 model variant: 'yolov8s' (default), 'yolov8n', 'yolov8m'.
        lighting_override (str, optional): 'auto', 'day', 'dusk', 'night'.

    Returns:
        tuple: (count: int, processed_image_path: str or None, lighting_mode: str, brightness: float)
    """
    os.makedirs(output_dir, exist_ok=True)

    if not file_path or not os.path.exists(file_path):
        print(f"[detector.py] Error: File not found -> {file_path}")
        return 0, None, "day", 140.0

    ext = os.path.splitext(file_path)[1].lower()
    is_video = ext in [".mp4", ".avi", ".mov", ".mkv", ".webm"]
    if is_video:
        return _process_video(
            file_path, output_dir, conf_threshold=conf_threshold, iou_threshold=iou_threshold,
            imgsz=imgsz, model_name=model_name, lighting_override=lighting_override
        )
    else:
        return _process_image(
            file_path, output_dir, conf_threshold=conf_threshold, iou_threshold=iou_threshold,
            imgsz=imgsz, model_name=model_name, lighting_override=lighting_override
        )


def get_detection_metadata(proc_path: str) -> Dict[str, Any]:
    """Retrieves cached metadata (original URL, enhanced URL, pipeline used) for a processed output."""
    if not proc_path:
        return {}
    clean = proc_path.replace("\\", "/").lstrip("/")
    for k, v in DETECTION_METADATA.items():
        if k.replace("\\", "/").lstrip("/") == clean:
            return v
    return {}


def _resize_to_width(image: np.ndarray, target_width: int = 640) -> np.ndarray:
    """Resizes an image to specified width maintaining aspect ratio."""
    h, w = image.shape[:2]
    if w == 0 or h == 0:
        return image
    target_height = int(h * (target_width / float(w)))
    return cv2.resize(image, (target_width, target_height), interpolation=cv2.INTER_AREA)


def _read_image_with_fallback(file_path: str) -> np.ndarray:
    """
    Decodes an image using a 4-tier decoder hierarchy (Requirement 8):
    1. OpenCV (cv2.imread)
    2. Pillow (with pillow-avif-plugin)
    3. pillow-heif (HEIF/HEIC support)
    4. FFmpeg (via imageio-ffmpeg subprocess pipe)
    Raises ValueError with file name and reason if all fail.
    """
    fname = os.path.basename(file_path)

    # 1. OpenCV
    try:
        img = cv2.imread(file_path)
        if img is not None and img.size > 0:
            return img
    except Exception:
        pass

    # 2. Pillow with pillow-avif-plugin
    if PIL_AVAILABLE:
        try:
            with _PilImage.open(file_path) as pil_img:
                pil_img = pil_img.convert("RGB")
                arr = np.array(pil_img, dtype=np.uint8)
                return cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
        except Exception:
            pass

    # 3. pillow-heif
    if HEIF_AVAILABLE:
        try:
            import pillow_heif
            heif_file = pillow_heif.open_heif(file_path)
            pil_img = _PilImage.frombytes(
                heif_file.mode, heif_file.size, heif_file.data, "raw"
            ).convert("RGB")
            arr = np.array(pil_img, dtype=np.uint8)
            return cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
        except Exception:
            pass

    # 4. FFmpeg
    try:
        from imageio_ffmpeg import get_ffmpeg_exe
        import subprocess
        ffmpeg_exe = get_ffmpeg_exe()
        cmd = [
            ffmpeg_exe, "-v", "error", "-i", file_path,
            "-vframes", "1", "-f", "image2pipe", "-vcodec", "png", "-"
        ]
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=8)
        if proc.returncode == 0 and len(proc.stdout) > 0:
            img = cv2.imdecode(np.frombuffer(proc.stdout, np.uint8), cv2.IMREAD_COLOR)
            if img is not None and img.size > 0:
                return img
    except Exception:
        pass

    raise ValueError(
        f"Upload failed: Could not decode '{fname}' using OpenCV, Pillow (AVIF), pillow-heif, or FFmpeg."
    )


def _run_image_pipeline(
    resized: np.ndarray,
    enhanced: Optional[np.ndarray],
    lighting_mode: str,
    brightness: float,
    model: Optional[Any],
    engine_name: str,
    conf_threshold: float,
    iou_threshold: float,
    imgsz: int,
    model_name: str
) -> Tuple[int, np.ndarray, str]:
    """Runs a single forward pass through the day/dusk/night vision pipeline."""
    if lighting_mode == "day":
        pipeline_used = f"Standard Vision Pipeline ({engine_name})"
        if model is not None:
            count, annotated = _detect_with_yolo(
                resized, conf_threshold=conf_threshold, iou_threshold=iou_threshold,
                imgsz=imgsz, model=model, model_name=model_name
            )
        else:
            count, annotated = _detect_with_opencv_contour(resized)
    elif lighting_mode == "dusk":
        pipeline_used = f"Enhanced Low-Light Pipeline ({engine_name})"
        target = enhanced if enhanced is not None else resized
        if model is not None:
            count, annotated = _detect_with_yolo(
                target, conf_threshold=conf_threshold, iou_threshold=iou_threshold,
                imgsz=imgsz, model=model, model_name=model_name
            )
        else:
            count, annotated = _detect_with_opencv_contour(target)
    else:  # night
        target = enhanced if enhanced is not None else resized
        if model is not None:
            count_norm, annotated_norm = _detect_with_yolo(
                target, conf_threshold=conf_threshold, iou_threshold=iou_threshold,
                imgsz=imgsz, model=model, model_name=model_name
            )
        else:
            count_norm, annotated_norm = _detect_with_opencv_contour(target)

        count_hl, hl_vehs, _ = detect_headlights(resized)
        if count_hl >= count_norm:
            count = count_hl
            pipeline_used = "Headlight-Based Pair Detection"
            annotated = target.copy()
            for idx, veh in enumerate(hl_vehs, 1):
                vx1, vy1, vx2, vy2 = veh["box"]
                vtype = veh["type"]
                col = (0, 240, 255) if veh["is_pair"] else (0, 215, 255)
                _draw_tech_box(annotated, vx1, vy1, vx2, vy2, f"{vtype} #{idx}", col)
        else:
            count = count_norm
            pipeline_used = f"Enhanced Low-Light Pipeline ({engine_name})"
            annotated = annotated_norm

    return count, annotated, pipeline_used


def _process_image(
    file_path: str,
    output_dir: str,
    conf_threshold: float = 0.30,
    iou_threshold: float = 0.5,
    imgsz: int = 960,
    model_name: str = "yolov8s",
    lighting_override: Optional[str] = None
) -> Tuple[int, str, str, float]:
    """
    Processes a single image through the multi-stage day/dusk/night pipeline.
    Recovery mechanism: If detected count <= 1 at conf_threshold, automatically
    retries at conf 0.15 and imgsz 1280 and uses the superior count.
    """
    img = _read_image_with_fallback(file_path)
    if img is None or img.size == 0:
        raise ValueError(f"Upload failed: Could not decode image '{os.path.basename(file_path)}'.")

    # Resize to standard 640px width maintaining aspect ratio
    resized = _resize_to_width(img, target_width=640)

    # 1. Analyze Lighting with override support and second cue (Requirement 12)
    lighting_mode, brightness, apply_low_light = analyze_lighting(resized, lighting_override)

    unique_id = uuid.uuid4().hex[:10]
    orig_name = f"orig_{unique_id}.jpg"
    orig_path = os.path.join(output_dir, orig_name)
    cv2.imwrite(orig_path, resized)
    orig_rel = f"static/processed/{orig_name}"

    enh_rel = orig_rel
    enhanced = None
    if apply_low_light and lighting_mode in ("dusk", "night"):
        enhanced = enhance_low_light(resized, brightness)
        enh_name = f"enh_{unique_id}.jpg"
        cv2.imwrite(os.path.join(output_dir, enh_name), enhanced)
        enh_rel = f"static/processed/{enh_name}"

    model = get_yolo_model(model_name)
    engine_name = get_yolo_engine_name(model_name) if model is not None else "OpenCV Vision"

    count, annotated, pipeline_used = _run_image_pipeline(
        resized, enhanced, lighting_mode, brightness, model, engine_name,
        conf_threshold, iou_threshold, imgsz, model_name
    )

    initial_count = count
    recovery_applied = False
    recovery_attempted = False
    final_conf = conf_threshold
    final_imgsz = imgsz
    retry_count = count

    # Requirement 1: If detected count is 0 or 1, automatically retry at conf 0.15 and imgsz 1280
    if count <= 1 and model is not None:
        recovery_attempted = True
        r_count, r_annotated, r_pipe = _run_image_pipeline(
            resized, enhanced, lighting_mode, brightness, model, engine_name,
            conf_threshold=0.15, iou_threshold=iou_threshold, imgsz=1280, model_name=model_name
        )
        retry_count = r_count
        if r_count > count:
            count = r_count
            annotated = r_annotated
            pipeline_used = f"{r_pipe} [Recovery 0.15/1280]"
            final_conf = 0.15
            final_imgsz = 1280
            recovery_applied = True

    hud_mode = f"{engine_name} (Recovery)" if recovery_applied else (
        f"{engine_name} (Standard)" if lighting_mode == "day" else (
            f"{engine_name} (Low-Light)" if lighting_mode == "dusk" else f"Night Mode ({pipeline_used})"
        )
    )
    _draw_hud_banner(annotated, count, hud_mode, lighting_mode, brightness)

    out_name = f"proc_{unique_id}.jpg"
    out_path = os.path.join(output_dir, out_name)
    cv2.imwrite(out_path, annotated)
    proc_rel = f"static/processed/{out_name}"

    # Cache metadata for road card inspection
    DETECTION_METADATA[proc_rel] = {
        "original_url": "/" + orig_rel.replace("\\", "/"),
        "enhanced_url": "/" + enh_rel.replace("\\", "/"),
        "pipeline": pipeline_used,
        "lighting_mode": lighting_mode,
        "brightness": brightness,
        "apply_low_light": apply_low_light,
        "engine": engine_name,
        "is_video": False,
        "video_avg_count": None,
        "video_max_count": None,
        "initial_count": initial_count,
        "final_count": count,
        "retry_count": retry_count,
        "recovery_applied": recovery_applied,
        "recovery_attempted": recovery_attempted,
        "final_conf": final_conf,
        "final_imgsz": final_imgsz,
        "model_name": model_name,
        "model_used": engine_name,
    }

    return count, proc_rel, lighting_mode, brightness


def _process_video(
    file_path: str,
    output_dir: str,
    conf_threshold: float = 0.30,
    iou_threshold: float = 0.5,
    imgsz: int = 960,
    model_name: str = "yolov8s",
    lighting_override: Optional[str] = None
) -> Tuple[int, str, str, float]:
    """
    Processes video feeds by sampling ~1 frame/sec for up to 10 seconds.
    Analyzes lighting, applies enhancement if dusk/night, and reports both
    average and maximum vehicle counts.
    """
    cap = cv2.VideoCapture(file_path)
    is_open = cap.isOpened()
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) if is_open else 0

    if not is_open or total_frames <= 0:
        if is_open:
            cap.release()
        # Fallback to FFmpeg frame extraction
        try:
            from imageio_ffmpeg import get_ffmpeg_exe
            import subprocess
            ffmpeg_exe = get_ffmpeg_exe()
            cmd = [
                ffmpeg_exe, "-v", "error", "-i", file_path,
                "-vframes", "1", "-f", "image2pipe", "-vcodec", "png", "-"
            ]
            proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=8)
            if proc.returncode == 0 and len(proc.stdout) > 0:
                ff_frame = cv2.imdecode(np.frombuffer(proc.stdout, np.uint8), cv2.IMREAD_COLOR)
                if ff_frame is not None and ff_frame.size > 0:
                    return _process_image(
                        file_path, output_dir, conf_threshold, iou_threshold, imgsz, model_name, lighting_override
                    )
        except Exception:
            pass
        raise ValueError(f"Upload failed: Video file '{os.path.basename(file_path)}' could not be decoded or contains no valid frames.")

    fps = cap.get(cv2.CAP_PROP_FPS)
    if not fps or fps <= 0 or np.isnan(fps):
        fps = 25.0

    duration_sec = total_frames / fps if fps > 0 else 0

    max_samples = min(10, max(1, int(duration_sec)))
    sample_indices = set(int(i * fps) for i in range(max_samples))

    sample_counts = []
    representative_frame = None

    model = get_yolo_model(model_name)
    engine_name = get_yolo_engine_name(model_name) if model is not None else "OpenCV Vision"
    bg_subtractor = None
    if model is None:
        bg_subtractor = cv2.createBackgroundSubtractorMOG2(history=60, varThreshold=35, detectShadows=True)

    current_idx = 0
    max_idx = max(sample_indices) if sample_indices else 0

    lighting_mode = "day"
    brightness = 130.0
    apply_low_light = False

    while cap.isOpened() and current_idx <= max_idx:
        ret, frame = cap.read()
        if not ret or frame is None:
            break

        frame_resized = _resize_to_width(frame, target_width=640)

        # Inspect lighting on the initial frame
        if current_idx == 0:
            lighting_mode, brightness, apply_low_light = analyze_lighting(frame_resized, lighting_override)

        # Apply low-light enhancement if dusk or night and second cue confirmed
        if apply_low_light and lighting_mode in ["dusk", "night"]:
            frame_work = enhance_low_light(frame_resized, brightness)
        else:
            frame_work = frame_resized

        if current_idx in sample_indices:
            if model is not None:
                c, ann = _detect_with_yolo(
                    frame_work, conf_threshold=conf_threshold, iou_threshold=iou_threshold,
                    imgsz=imgsz, model=model, model_name=model_name
                )
            else:
                c, ann = _detect_with_video_bg_sub(frame_work, bg_subtractor)

            # In night mode, check headlight count as well
            if lighting_mode == "night":
                c_hl, _, _ = detect_headlights(frame_resized)
                c = max(c, c_hl)

            sample_counts.append(c)
            if representative_frame is None or len(sample_counts) == (max_samples // 2 + 1):
                representative_frame = ann

        current_idx += 1

    cap.release()

    if not sample_counts:
        sample_counts = [0]
    avg_count = int(round(sum(sample_counts) / len(sample_counts)))
    max_count = int(max(sample_counts))

    if representative_frame is None:
        representative_frame = np.zeros((480, 640, 3), dtype=np.uint8)

    _draw_hud_banner(
        representative_frame,
        count=avg_count,
        mode_str=f"{engine_name} ({len(sample_counts)}s | Avg:{avg_count} Max:{max_count})",
        lighting_mode=lighting_mode,
        brightness=brightness
    )

    unique_name = f"proc_vid_{uuid.uuid4().hex[:10]}.jpg"
    out_path = os.path.join(output_dir, unique_name)
    cv2.imwrite(out_path, representative_frame)
    proc_rel = f"static/processed/{unique_name}"

    DETECTION_METADATA[proc_rel] = {
        "original_url": "/" + proc_rel.replace("\\", "/"),
        "enhanced_url": "/" + proc_rel.replace("\\", "/"),
        "pipeline": f"Video Temporal Averaging ({engine_name})",
        "is_video": True,
        "video_avg_count": avg_count,
        "video_max_count": max_count,
        "lighting_mode": lighting_mode,
        "brightness": brightness,
        "apply_low_light": apply_low_light,
        "engine": engine_name,
        "model_name": model_name,
        "model_used": engine_name,
        "conf_threshold": conf_threshold
    }

    return avg_count, proc_rel, lighting_mode, brightness
    cv2.imwrite(out_path, representative_frame)
    proc_rel = f"static/processed/{unique_name}"

    pipeline_used = f"Video Multi-Frame ({engine_name})" if lighting_mode == "day" else (
        f"Video Low-Light Enhanced ({engine_name})" if lighting_mode == "dusk" else f"Video Night Mode Fusion ({engine_name})"
    )

    DETECTION_METADATA[proc_rel] = {
        "original_url": "/" + proc_rel.replace("\\", "/"),
        "enhanced_url": "/" + proc_rel.replace("\\", "/"),
        "pipeline": pipeline_used,
        "lighting_mode": lighting_mode,
        "brightness": brightness,
        "engine": engine_name,
        "is_video": True,
        "video_avg_count": avg_count,
        "video_max_count": max_count,
    }

    return avg_count, proc_rel, lighting_mode, brightness


def _detect_with_yolo(
    image: np.ndarray,
    conf_threshold: float = 0.30,
    iou_threshold: float = 0.5,
    imgsz: int = 960,
    model: Optional[Any] = None,
    model_name: str = "yolov8s"
) -> Tuple[int, np.ndarray]:
    """
    Infers vehicle bounding boxes using YOLOv8 for COCO classes:
    2: Car, 3: Motorcycle, 5: Bus, 7: Truck.
    Draws boxes with class labels and confidence.
    """
    if model is None:
        model = get_yolo_model(model_name)
    if model is None:
        return _detect_with_opencv_contour(image)

    annotated = image.copy()
    count = 0

    try:
        results = model(
            image,
            conf=conf_threshold,
            iou=iou_threshold,
            imgsz=imgsz,
            classes=[2, 3, 5, 7],
            verbose=False
        )
        for r in results:
            boxes = r.boxes
            if boxes is None:
                continue
            for box in boxes:
                cls_id = int(box.cls[0].item())
                conf = float(box.conf[0].item())
                count += 1
                xyxy = box.xyxy[0].cpu().numpy().astype(int)
                x1, y1, x2, y2 = xyxy
                class_label = VEHICLE_CLASSES.get(cls_id, "Vehicle")
                label = f"{class_label} {int(conf * 100)}%"
                _draw_tech_box(annotated, x1, y1, x2, y2, label, (0, 230, 115))
    except Exception as e:
        print(f"[detector.py] YOLO inference failed ({e}). Falling back to OpenCV contour.")
        return _detect_with_opencv_contour(image)

    return count, annotated


def _detect_with_opencv_contour(image: np.ndarray) -> Tuple[int, np.ndarray]:
    """
    OpenCV fallback: Resizes to 640px, grayscales, applies Gaussian blur,
    adaptive thresholding, morphological closing, and contour area filtering with NMS.
    """
    annotated = image.copy()
    h, w = image.shape[:2]

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)

    # Adaptive thresholding to segment vehicle silhouettes from asphalt
    thresh = cv2.adaptiveThreshold(
        blurred, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV, 25, 4
    )

    # Morphological closing
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    closed = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel, iterations=1)

    contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    min_area = 380
    max_area = int(w * h * 0.20)

    raw_boxes = []
    scores = []
    for cnt in contours:
        area = cv2.contourArea(cnt)
        if min_area <= area <= max_area:
            x, y, bw, bh = cv2.boundingRect(cnt)
            aspect_ratio = bw / float(bh)
            if 0.25 <= aspect_ratio <= 3.5 and bw >= 20 and bh >= 26:
                if y > 35 and (y + bh) < (h - 8):
                    raw_boxes.append([x, y, bw, bh])
                    scores.append(float(area))

    # Apply cv2.dnn.NMSBoxes
    if raw_boxes:
        indices = cv2.dnn.NMSBoxes(raw_boxes, scores, score_threshold=300.0, nms_threshold=0.3)
        picked_indices = indices.flatten() if len(indices) > 0 else []
    else:
        picked_indices = []

    count = len(picked_indices)

    for idx, i in enumerate(picked_indices, 1):
        x, y, bw, bh = raw_boxes[i]
        _draw_tech_box(annotated, x, y, x + bw, y + bh, f"Veh #{idx}", (0, 215, 255))

    return count, annotated


def _detect_with_video_bg_sub(image: np.ndarray, bg_subtractor) -> Tuple[int, np.ndarray]:
    """Detects moving vehicles via background subtraction and contour area."""
    annotated = image.copy()
    h, w = image.shape[:2]

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)

    fg_mask = bg_subtractor.apply(blurred)
    _, thresh = cv2.threshold(fg_mask, 190, 255, cv2.THRESH_BINARY)

    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    closed = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel, iterations=1)

    contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    raw_boxes = []
    scores = []
    for cnt in contours:
        area = cv2.contourArea(cnt)
        if 350 <= area <= int(w * h * 0.25):
            x, y, bw, bh = cv2.boundingRect(cnt)
            if bw >= 20 and bh >= 24 and (0.25 <= bw / float(bh) <= 3.5):
                if y > 35 and (y + bh) < (h - 8):
                    raw_boxes.append([x, y, bw, bh])
                    scores.append(float(area))

    if raw_boxes:
        indices = cv2.dnn.NMSBoxes(raw_boxes, scores, score_threshold=280.0, nms_threshold=0.3)
        picked_indices = indices.flatten() if len(indices) > 0 else []
    else:
        picked_indices = []

    count = len(picked_indices)

    for idx, i in enumerate(picked_indices, 1):
        x, y, bw, bh = raw_boxes[i]
        _draw_tech_box(annotated, x, y, x + bw, y + bh, f"M-Veh #{idx}", (50, 230, 255))

    return count, annotated


def _draw_tech_box(img: np.ndarray, x1: int, y1: int, x2: int, y2: int, label: str, color=(0, 220, 255)):
    """Draws a modern HUD bounding box with corner accent brackets and badge."""
    cv2.rectangle(img, (x1, y1), (x2, y2), color, 2)

    # Corner brackets
    corner_len = min(8, max(4, (x2 - x1) // 4))
    cv2.line(img, (x1, y1), (x1 + corner_len, y1), (255, 255, 255), 2)
    cv2.line(img, (x1, y1), (x1, y1 + corner_len), (255, 255, 255), 2)
    cv2.line(img, (x2, y1), (x2 - corner_len, y1), (255, 255, 255), 2)
    cv2.line(img, (x2, y1), (x2, y1 + corner_len), (255, 255, 255), 2)
    cv2.line(img, (x1, y2), (x1 + corner_len, y2), (255, 255, 255), 2)
    cv2.line(img, (x1, y2), (x1, y2 - corner_len), (255, 255, 255), 2)
    cv2.line(img, (x2, y2), (x2 - corner_len, y2), (255, 255, 255), 2)
    cv2.line(img, (x2, y2), (x2, y2 - corner_len), (255, 255, 255), 2)

    # Label badge
    font = cv2.FONT_HERSHEY_SIMPLEX
    font_scale = 0.38
    thickness = 1
    (tw, th), _ = cv2.getTextSize(label, font, font_scale, thickness)

    badge_y1 = max(0, y1 - th - 5)
    badge_y2 = y1
    badge_x2 = min(img.shape[1], x1 + tw + 6)

    cv2.rectangle(img, (x1, badge_y1), (badge_x2, badge_y2), (20, 24, 33), -1)
    cv2.rectangle(img, (x1, badge_y1), (badge_x2, badge_y2), color, 1)
    cv2.putText(img, label, (x1 + 3, badge_y2 - 2), font, font_scale, (255, 255, 255), thickness, cv2.LINE_AA)


def _draw_hud_banner(img: np.ndarray, count: int, mode_str: str, lighting_mode: str = "day", brightness: float = 140.0):
    """Draws a sleek translucent HUD top bar with lighting badges and NIGHT MODE tag."""
    h, w = img.shape[:2]
    bar_h = 36

    overlay = img.copy()
    cv2.rectangle(overlay, (0, 0), (w, bar_h), (12, 16, 24), -1)
    cv2.addWeighted(overlay, 0.88, img, 0.12, 0, img)

    border_color = (180, 50, 255) if lighting_mode == "night" else ((0, 180, 255) if lighting_mode == "dusk" else (0, 150, 255))
    cv2.line(img, (0, bar_h), (w, bar_h), border_color, 1)

    # Left text: System mode
    cv2.putText(
        img,
        f"AI VISION HUD | {mode_str[:26]}",
        (10, 23),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.42,
        (200, 225, 255),
        1,
        cv2.LINE_AA
    )

    # Center: Lighting mode & Brightness indicator
    if lighting_mode == "night":
        l_color = (255, 110, 230)
        mode_text = f"LIGHTING: NIGHT ({int(brightness)})"
    elif lighting_mode == "dusk":
        l_color = (0, 190, 255)
        mode_text = f"LIGHTING: DUSK ({int(brightness)})"
    else:
        l_color = (80, 230, 255)
        mode_text = f"LIGHTING: DAY ({int(brightness)})"

    cv2.putText(img, mode_text, (w // 2 - 80, 23), cv2.FONT_HERSHEY_SIMPLEX, 0.40, l_color, 1, cv2.LINE_AA)

    # Prominent NIGHT MODE ACTIVE tag on night images
    if lighting_mode == "night":
        tag_x1 = w // 2 + 75
        tag_x2 = tag_x1 + 105
        cv2.rectangle(img, (tag_x1, 7), (tag_x2, 29), (50, 10, 80), -1)
        cv2.rectangle(img, (tag_x1, 7), (tag_x2, 29), (255, 80, 220), 1)
        cv2.putText(img, "NIGHT MODE", (tag_x1 + 8, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (255, 255, 255), 1, cv2.LINE_AA)

    # Right text: Vehicle Count Badge
    badge_text = f"VEHICLES: {count}"
    font = cv2.FONT_HERSHEY_SIMPLEX
    (tw, th), _ = cv2.getTextSize(badge_text, font, 0.50, 2)
    badge_x = w - tw - 12

    if count < 10:
        c_badge = (46, 204, 113)   # Green (Low)
    elif count <= 25:
        c_badge = (0, 165, 255)    # Orange (Medium)
    else:
        c_badge = (40, 60, 240)    # Red (High)

    cv2.putText(img, badge_text, (badge_x, 24), font, 0.50, c_badge, 2, cv2.LINE_AA)


def generate_sample_images(samples_dir: str = "static/samples", force_recreate: bool = False):
    """
    Auto-generates synthetic sample images:
    - 4 primary junction benchmark roads (North, South, East, West)
    - 2 additional test images (a dusk road scene and a night road scene with bright headlight dots)
    """
    os.makedirs(samples_dir, exist_ok=True)

    road_configs = [
        {"filename": "sample_north.jpg", "car_count": 16, "title": "North Corridor Approach", "lighting": "day"},
        {"filename": "sample_south.jpg", "car_count": 7,  "title": "South Sector Road", "lighting": "day"},
        {"filename": "sample_east.jpg",  "car_count": 27, "title": "East Expressway Hub", "lighting": "day"},
        {"filename": "sample_west.jpg",  "car_count": 4,  "title": "West Connecting Avenue", "lighting": "day"},
        {"filename": "sample_dusk.jpg",  "car_count": 12, "title": "Dusk Suburban Arterial", "lighting": "dusk"},
        {"filename": "sample_night.jpg", "car_count": 8,  "title": "Night Expressway Corridor", "lighting": "night"}
    ]

    for cfg in road_configs:
        file_path = os.path.join(samples_dir, cfg["filename"])
        if force_recreate or not os.path.exists(file_path):
            img = _draw_synthetic_road(cfg["car_count"], cfg["title"], lighting=cfg["lighting"])
            cv2.imwrite(file_path, img)
            print(f"[detector.py] Created synthetic sample: {file_path} ({cfg['lighting'].upper()})")


def _draw_synthetic_road(num_cars: int, road_title: str, lighting: str = "day") -> np.ndarray:
    """
    Draws a realistic multi-lane synthetic road view:
    - Day: bright daylight asphalt, clearly visible vehicle bodies.
    - Dusk: twilight ambient illumination with running lights.
    - Night: dark asphalt, headlights with bright glow halos, taillights, and streetlights.
    """
    width, height = 640, 480
    img = np.zeros((height, width, 3), dtype=np.uint8)
    lighting = lighting.lower()

    if lighting == "day":
        asphalt = (128, 132, 138)
        curb = (160, 165, 170)
        dash_white = (245, 245, 245)
        dash_yellow = (0, 215, 255)
        text_color = (255, 255, 255)
    elif lighting == "dusk":
        asphalt = (68, 72, 85)
        curb = (85, 90, 100)
        dash_white = (180, 185, 195)
        dash_yellow = (0, 160, 200)
        text_color = (220, 225, 235)
    else:  # night
        asphalt = (18, 20, 25)
        curb = (30, 32, 36)
        dash_white = (85, 90, 95)
        dash_yellow = (0, 75, 95)
        text_color = (160, 175, 190)

    # Base asphalt surface with texture noise
    img[:] = asphalt
    noise = np.random.randint(-2, 3, (height, width, 3), dtype=np.int16)
    img = np.clip(img.astype(np.int16) + noise, 0, 255).astype(np.uint8)

    # Sidewalk curbs
    curb_w = 26
    img[:, :curb_w] = curb
    img[:, width - curb_w:] = curb
    cv2.line(img, (curb_w, 0), (curb_w, height), dash_white, 2)
    cv2.line(img, (width - curb_w, 0), (width - curb_w, height), dash_white, 2)

    road_start = curb_w + 6
    road_end = width - curb_w - 6
    num_lanes = 8 if num_cars > 18 else 6
    lane_width = (road_end - road_start) // num_lanes

    # Lane markings (dashed white / yellow)
    for l_idx in range(1, num_lanes):
        x_lane = road_start + l_idx * lane_width
        is_center = (l_idx == (num_lanes // 2))
        color = dash_yellow if is_center else dash_white
        thick = 2 if is_center else 1
        for y_dash in range(45, height - 50, 36):
            cv2.line(img, (x_lane, y_dash), (x_lane, y_dash + 16), color, thick)

    # Stop line and crosswalk
    crosswalk_y = height - 42
    cv2.line(img, (road_start, crosswalk_y - 6), (road_end, crosswalk_y - 6), dash_white, 3)
    cw_color = (240, 240, 240) if lighting == "day" else ((160, 160, 160) if lighting == "dusk" else (70, 70, 70))
    for cx in range(road_start, road_end, 26):
        cv2.rectangle(img, (cx, crosswalk_y), (cx + 14, crosswalk_y + 16), cw_color, -1)

    # Streetlights on curbs at night
    if lighting == "night":
        for ly in [70, 210, 350]:
            cv2.circle(img, (curb_w - 8, ly), 4, (200, 220, 240), -1)
            cv2.circle(img, (width - curb_w + 8, ly), 4, (200, 220, 240), -1)

    lane_centers = [road_start + int((i + 0.5) * lane_width) for i in range(num_lanes)]
    y_slots = [52, 114, 176, 238, 300, 362]
    all_spots = [(lx, y) for y in y_slots for lx in lane_centers]
    selected_spots = all_spots[:num_cars]

    rng = random.Random(num_cars * 101 + 47)
    car_colors = [
        (35, 40, 215), (215, 110, 35), (45, 185, 55),
        (230, 230, 235), (25, 25, 30), (0, 185, 235),
        (165, 45, 145), (35, 125, 215)
    ]

    for idx, (lx, cy) in enumerate(selected_spots):
        is_motorcycle = (lighting == "night" and idx % 4 == 3)
        bw = 14 if is_motorcycle else 26
        bh = 26 if is_motorcycle else 38
        bx1 = lx - bw // 2
        by1 = cy
        bx2 = bx1 + bw
        by2 = by1 + bh

        if lighting == "night":
            v_color = (25, 28, 32)
            cv2.rectangle(img, (bx1, by1), (bx2, by2), v_color, -1)
            cv2.rectangle(img, (bx1, by1), (bx2, by2), (10, 12, 15), 1)

            if is_motorcycle:
                # Single headlight in center
                cv2.circle(img, (lx, by1 + 3), 3, (255, 255, 255), -1)
                cv2.circle(img, (lx, by1 + 3), 6, (180, 230, 255), 1)
                cv2.circle(img, (lx, by2 - 2), 2, (30, 30, 240), -1)
            else:
                # Pair of bright headlights
                hl1 = (bx1 + 4, by1 + 3)
                hl2 = (bx2 - 4, by1 + 3)
                cv2.circle(img, hl1, 3, (255, 255, 255), -1)
                cv2.circle(img, hl2, 3, (255, 255, 255), -1)
                cv2.circle(img, hl1, 6, (180, 230, 255), 1)
                cv2.circle(img, hl2, 6, (180, 230, 255), 1)

                # Light beam projection on pavement ahead
                cone_pts = np.array([
                    [bx1 + 2, by1 + 4],
                    [bx1 - 5, by1 + 18],
                    [bx2 + 5, by1 + 18],
                    [bx2 - 2, by1 + 4]
                ], np.int32)
                overlay = img.copy()
                cv2.fillPoly(overlay, [cone_pts], (45, 55, 65))
                cv2.addWeighted(overlay, 0.35, img, 0.65, 0, img)

                # Taillights
                cv2.circle(img, (bx1 + 4, by2 - 2), 2, (20, 20, 230), -1)
                cv2.circle(img, (bx2 - 4, by2 - 2), 2, (20, 20, 230), -1)

        elif lighting == "dusk":
            c_base = rng.choice(car_colors)
            v_color = tuple(int(c * 0.65) for c in c_base)
            cv2.rectangle(img, (bx1, by1), (bx2, by2), v_color, -1)
            cv2.rectangle(img, (bx1, by1), (bx2, by2), (20, 20, 20), 1)
            w_h = max(4, int(bh * 0.22))
            cv2.rectangle(img, (bx1 + 3, by1 + 5), (bx2 - 3, by1 + 5 + w_h), (50, 60, 75), -1)
            cv2.circle(img, (bx1 + 3, by1 + 2), 2, (220, 240, 255), -1)
            cv2.circle(img, (bx2 - 3, by1 + 2), 2, (220, 240, 255), -1)
            cv2.circle(img, (bx1 + 3, by2 - 2), 2, (30, 30, 240), -1)
            cv2.circle(img, (bx2 - 3, by2 - 2), 2, (30, 30, 240), -1)

        else:  # day
            v_color = rng.choice(car_colors)
            cv2.rectangle(img, (bx1, by1), (bx2, by2), v_color, -1)
            cv2.rectangle(img, (bx1, by1), (bx2, by2), (20, 20, 20), 1)
            w_h = max(4, int(bh * 0.22))
            cv2.rectangle(img, (bx1 + 3, by1 + 5), (bx2 - 3, by1 + 5 + w_h), (80, 100, 120), -1)
            cv2.rectangle(img, (bx1 + 3, by2 - 8), (bx2 - 3, by2 - 3), (60, 80, 100), -1)
            cv2.circle(img, (bx1 + 3, by1 + 2), 2, (180, 240, 255), -1)
            cv2.circle(img, (bx2 - 3, by1 + 2), 2, (180, 240, 255), -1)
            cv2.circle(img, (bx1 + 3, by2 - 2), 2, (30, 30, 240), -1)
            cv2.circle(img, (bx2 - 3, by2 - 2), 2, (30, 30, 240), -1)

    cv2.putText(
        img,
        road_title.upper(),
        (curb_w + 8, 26),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.46,
        text_color,
        1,
        cv2.LINE_AA
    )

    return img


if __name__ == "__main__":
    print("=== Testing detector.py ===")
    generate_sample_images("static/samples", force_recreate=True)

    test_samples = ["north", "south", "east", "west", "dusk", "night"]
    for r in test_samples:
        tpath = f"static/samples/sample_{r}.jpg"
        c, p, lmode, bright = count_vehicles(tpath, "static/processed")
        print(f"Sample {r.upper():<6} -> Count: {c:<3} Lighting: {lmode:<5} Brightness: {bright:<5} Processed: {p}")
