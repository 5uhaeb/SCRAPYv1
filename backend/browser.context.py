from pathlib import Path
from playwright.sync_api import sync_playwright

PROFILE_DIR = Path("pw_profile")

def launch():
    p = sync_playwright().start()
    # persistent context = keeps cookies/cache like a real user
    context = p.chromium.launch_persistent_context(
        user_data_dir=str(PROFILE_DIR),
        headless=False,
        channel="chrome",
        viewport={"width": 1366, "height": 768},
        locale="en-IN",
        timezone_id="Asia/Kolkata",
        args=[
            "--disable-blink-features=AutomationControlled",
            "--start-maximized",
        ],
    )
    page = context.new_page()
    return p, context, page