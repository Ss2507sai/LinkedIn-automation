"""Browser smoke test — verifies CDP connection and tab discovery."""

from __future__ import annotations

import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

from config.settings import Settings
from src.browser import BrowserManager
from src.errors import TabNotFoundError
from src.logger import get_logger

logger = get_logger()

CHROME_PATH = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
SMOKE_CDP_PORT = 9223


def _launch_chrome_for_smoke(profile_dir: Path, port: int) -> subprocess.Popen | None:
    """Launch a dedicated Chrome instance for smoke testing."""
    if not Path(CHROME_PATH).exists():
        return None

    profile_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        CHROME_PATH,
        f"--remote-debugging-port={port}",
        f"--user-data-dir={profile_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        "about:blank",
    ]
    return subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _wait_for_cdp(url: str, timeout_sec: float = 20.0) -> bool:
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"{url}/json/version", timeout=2) as resp:
                if resp.status == 200:
                    return True
        except (urllib.error.URLError, TimeoutError, OSError):
            time.sleep(0.5)
    return False


def run_browser_smoke(settings: Settings) -> tuple[bool, list[str]]:
    """
    Launch isolated Chrome, open required tabs, verify BrowserManager can find them.
    Uses port 9223 to avoid conflicting with user Chrome on 9222.
    """
    cdp_url = f"http://127.0.0.1:{SMOKE_CDP_PORT}"
    smoke_profile = settings.chrome_automation_profile_dir / "smoke-test"
    chrome_proc: subprocess.Popen | None = None
    manager: BrowserManager | None = None
    issues: list[str] = []

    try:
        chrome_proc = _launch_chrome_for_smoke(smoke_profile, SMOKE_CDP_PORT)
        if chrome_proc is None:
            return False, [f"Chrome not found at {CHROME_PATH}"]

        if not _wait_for_cdp(cdp_url):
            return False, [f"Chrome CDP did not become ready at {cdp_url}"]

        smoke_settings = Settings(
            cdp_url=cdp_url,
            sales_nav_url_pattern=settings.sales_nav_url_pattern,
            chatgpt_url_pattern=settings.chatgpt_url_pattern,
            chrome_automation_profile_dir=settings.chrome_automation_profile_dir,
        )
        manager = BrowserManager(smoke_settings)
        context = manager.connect()

        sales_page = context.new_page()
        sales_page.goto(
            "https://www.linkedin.com/sales/search/people",
            wait_until="domcontentloaded",
            timeout=30_000,
        )
        chat_page = context.new_page()
        chat_page.goto(
            "https://chatgpt.com/",
            wait_until="domcontentloaded",
            timeout=30_000,
        )

        for label, pattern in (
            ("Sales Navigator", smoke_settings.sales_nav_url_pattern),
            ("ChatGPT", smoke_settings.chatgpt_url_pattern),
        ):
            try:
                manager.find_page_by_url_pattern(pattern)
                logger.info("Smoke: %s tab found", label)
            except TabNotFoundError as exc:
                issues.append(str(exc))

    except Exception as exc:
        issues.append(f"Browser smoke test failed: {exc}")
    finally:
        if manager:
            manager.close()
        if chrome_proc and chrome_proc.poll() is None:
            chrome_proc.terminate()
            try:
                chrome_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                chrome_proc.kill()

    return len(issues) == 0, issues
