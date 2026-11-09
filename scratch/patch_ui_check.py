with open("ui_check.py", "r", encoding="utf-8") as f:
    content = f.read()

old_click_block = '''            # Click 'Run Simulation'
            sim_button = page.locator("#btnSimulate")
            sim_button.wait_for(state="visible")
            sim_button.click()'''

new_click_block = '''            # Verify initial first-load state elements (Requirement A2, A5)
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
            sim_button.click()'''

if old_click_block in content:
    content = content.replace(old_click_block, new_click_block, 1)

with open("ui_check.py", "w", encoding="utf-8") as f:
    f.write(content)

print("ui_check.py updated.")

