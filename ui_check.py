"""
ui_check.py - Visual layout & responsiveness check using Playwright.

Tests the Smart Traffic Signal dashboard at 1440, 1366, 1032, 768 and 390px:
- Opens the page
- Clicks 'Run Simulation'
- Asserts that all 4 road title elements have a bounding box width > 60px
- Asserts that document.documentElement.scrollWidth <= document.documentElement.clientWidth (no horizontal scroll)
- Saves full-page screenshots for visual inspection.
"""

import os
import sys
import atexit
import tempfile

TEST_HIST_PATH = os.path.abspath(f"test_ui_history_{os.getpid()}.json")
os.environ["TRAFFIC_HISTORY_FILE"] = TEST_HIST_PATH

def _cleanup_test_history():
    if os.path.exists(TEST_HIST_PATH):
        try:
            os.remove(TEST_HIST_PATH)
        except OSError:
            pass

atexit.register(_cleanup_test_history)

import time
import socket
import threading
from playwright.sync_api import sync_playwright

VIEWPORTS = [
    {"name": "1440px_desktop", "width": 1440, "height": 900},
    {"name": "1366px_laptop",  "width": 1366, "height": 768},
    {"name": "1032px_small_laptop", "width": 1032, "height": 800},
    {"name": "768px_tablet",   "width": 768,  "height": 1024},
    {"name": "390px_mobile",   "width": 390,  "height": 844},
]

SCREENSHOT_DIR = "screenshots"


def is_server_running(host="127.0.0.1", port=5000):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1.0)
        return s.connect_ex((host, port)) == 0


def start_flask_thread(port=5000):
    from app import app
    import logging
    # Suppress verbose werkzeug logs
    log = logging.getLogger('werkzeug')
    log.setLevel(logging.ERROR)
    server_thread = threading.Thread(
        target=lambda: app.run(host="127.0.0.1", port=port, debug=False, use_reloader=False),
        daemon=True
    )
    server_thread.start()
    for _ in range(30):
        if is_server_running("127.0.0.1", port):
            return True
        time.sleep(0.3)
    return False


def run_visual_checks():
    os.makedirs(SCREENSHOT_DIR, exist_ok=True)
    port = 5000

    if not is_server_running("127.0.0.1", port):
        print(f"Starting Flask server on port {port}...")
        if not start_flask_thread(port):
            print(f"ERROR: Could not start Flask server on port {port}")
            sys.exit(1)
        print("Flask server started successfully.")
    else:
        print(f"Using running Flask server on port {port}.")

    target_url = f"http://127.0.0.1:{port}"
    results = []
    all_passed = True

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        for vp in VIEWPORTS:
            w, h = vp["width"], vp["height"]
            name = vp["name"]
            print(f"\n==================================================")
            print(f"Testing viewport: {name} ({w}x{h})")
            print(f"==================================================")

            context = browser.new_context(viewport={"width": w, "height": h})
            page = context.new_page()

            page.goto(target_url, wait_until="networkidle")
            page.wait_for_timeout(1000)

            # Verify initial first-load state elements (Requirement A2, A5)
            waiting_notice = page.locator("#waitingNotice")
            if waiting_notice.is_visible():
                print("  [PASS] First-load waiting notice is visible.")
            emerg_btn = page.locator("#btnEmergNorth")
            if emerg_btn.is_disabled():
                print("  [PASS] Emergency button is disabled before traffic analysis.")

            # Open Test Tools section if collapsed, then click Run Simulation
            test_tools_summary = page.locator("#testToolsDetails summary")
            if test_tools_summary.is_visible():
                test_tools_summary.click()
                page.wait_for_timeout(300)

            sim_button = page.locator("#btnSimulate")
            sim_button.wait_for(state="visible")
            sim_button.click()

            # Wait for simulation to complete and UI to update
            page.wait_for_timeout(2500)

            # 1. Check Road Titles Width (> 60px)
            road_selectors = {
                "North": "#cardNorth .road-title",
                "South": "#cardSouth .road-title",
                "East":  "#cardEast .road-title",
                "West":  "#cardWest .road-title"
            }

            title_widths = {}
            titles_ok = True
            for road, sel in road_selectors.items():
                locator = page.locator(sel)
                locator.wait_for(state="visible")
                box = locator.bounding_box()
                if not box:
                    print(f"  [FAIL] {road} road title has no bounding box!")
                    titles_ok = False
                    all_passed = False
                    continue

                width = round(box["width"], 1)
                text = locator.text_content().strip()
                title_widths[road] = width

                if width > 60:
                    print(f"  [PASS] {road} title: '{text}' width = {width}px (> 60px)")
                else:
                    print(f"  [FAIL] {road} title: '{text}' width = {width}px (<= 60px!)")
                    titles_ok = False
                    all_passed = False

            # 2. Check Horizontal Scroll (scrollWidth <= clientWidth)
            scroll_data = page.evaluate("""() => {
                const doc = document.documentElement;
                return {
                    scrollWidth: doc.scrollWidth,
                    clientWidth: doc.clientWidth,
                    bodyScrollWidth: document.body.scrollWidth,
                    bodyClientWidth: document.body.clientWidth
                };
            }""")

            scroll_w = scroll_data["scrollWidth"]
            client_w = scroll_data["clientWidth"]
            has_no_hscroll = (scroll_w <= client_w)

            if has_no_hscroll:
                print(f"  [PASS] No horizontal scroll: scrollWidth ({scroll_w}px) == clientWidth ({client_w}px)")
            else:
                print(f"  [FAIL] Horizontal scroll detected! scrollWidth ({scroll_w}px) > clientWidth ({client_w}px)")
                all_passed = False

            # 3. Save Screenshot
            ss_path = os.path.join(SCREENSHOT_DIR, f"screenshot_{w}px.png")
            page.screenshot(path=ss_path, full_page=True)
            print(f"  [SAVED] Full-page screenshot saved to: {ss_path}")

            results.append({
                "viewport": name,
                "width": w,
                "titles_ok": titles_ok,
                "title_widths": title_widths,
                "no_hscroll": has_no_hscroll,
                "scroll_width": scroll_w,
                "client_width": client_w,
                "screenshot": ss_path
            })

            context.close()

        browser.close()

    print("\n" + "=" * 60)
    print("VISUAL TEST SUMMARY RESULTS:")
    print("=" * 60)
    for r in results:
        status = "PASS" if (r["titles_ok"] and r["no_hscroll"]) else "FAIL"
        print(f"[{status}] {r['viewport']} | Titles: {r['title_widths']} | Scroll: {r['scroll_width']}/{r['client_width']}")

    if all_passed:
        print("\nALL VISUAL & RESPONSIVENESS CHECKS PASSED (100%)!")
    else:
        print("\nSOME CHECKS FAILED! Please review the failures above.")
        sys.exit(1)


if __name__ == "__main__":
    run_visual_checks()

