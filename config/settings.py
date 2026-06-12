"""Application configuration loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")


def _env_bool(key: str, default: bool = False) -> bool:
    value = os.getenv(key, str(default)).strip().lower()
    return value in {"1", "true", "yes", "on"}


def _env_int(key: str, default: int) -> int:
    try:
        return int(os.getenv(key, str(default)))
    except ValueError:
        return default


def _env_float(key: str, default: float) -> float:
    try:
        return float(os.getenv(key, str(default)))
    except ValueError:
        return default


@dataclass
class Settings:
    """Runtime configuration for the Wavity LinkedIn automation."""

    # Browser
    cdp_url: str = "http://127.0.0.1:9222"
    chrome_user_data_dir: str = str(
        Path.home() / "Library/Application Support/Google/ChromeForAutomation"
    )
    chrome_profile_directory: str = "Default"
    chrome_automation_profile_dir: Path = field(
        default_factory=lambda: PROJECT_ROOT / ".chrome-automation-profile"
    )
    headless: bool = False
    browser_channel: str = "chrome"

    # Timing (seconds)
    delay_min: float = 1.0
    delay_max: float = 3.0
    page_load_timeout_ms: int = 60_000
    chatgpt_response_timeout_sec: int = 180
    chatgpt_stability_checks: int = 3
    chatgpt_stability_interval_sec: float = 2.0

    # Retries
    retry_count: int = 1
    max_pagination_retries: int = 3

    # Modes
    test_mode: bool = False
    test_mode_limit: int = 3
    approval_mode: bool = False
    use_control_panel: bool = False
    connect_dry_run: bool = False
    profile_extraction_retries: int = 3
    browser_reconnect_retries: int = 3

    # URLs / tab matching
    sales_nav_url_pattern: str = "linkedin.com/sales"
    chatgpt_url_pattern: str = "chatgpt.com"

    # File paths
    project_root: Path = field(default_factory=lambda: PROJECT_ROOT)
    results_xlsx: Path = field(
        default_factory=lambda: PROJECT_ROOT / "results.xlsx"
    )
    results_csv: Path = field(default_factory=lambda: PROJECT_ROOT / "results.csv")
    processed_profiles_json: Path = field(
        default_factory=lambda: PROJECT_ROOT / "processed_profiles.json"
    )
    database_path: Path = field(
        default_factory=lambda: PROJECT_ROOT / "prospects.db"
    )
    logs_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "logs")
    screenshots_dir: Path = field(
        default_factory=lambda: PROJECT_ROOT / "screenshots"
    )
    log_file: Path = field(default_factory=lambda: PROJECT_ROOT / "logs" / "automation.log")
    pinned_tabs_json: Path = field(
        default_factory=lambda: PROJECT_ROOT / "pinned_tabs.json"
    )

    def ensure_directories(self) -> None:
        """Create output directories if they do not exist."""
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.screenshots_dir.mkdir(parents=True, exist_ok=True)


def get_settings() -> Settings:
    """Build settings from environment variables with sensible defaults."""
    root = PROJECT_ROOT
    logs_dir = Path(os.getenv("LOGS_DIR", str(root / "logs")))
    screenshots_dir = Path(os.getenv("SCREENSHOTS_DIR", str(root / "screenshots")))

    return Settings(
        cdp_url=os.getenv("CDP_URL", "http://127.0.0.1:9222"),
        chrome_user_data_dir=os.getenv(
            "CHROME_USER_DATA_DIR",
            str(Path.home() / "Library/Application Support/Google/ChromeForAutomation"),
        ),
        chrome_profile_directory=os.getenv("CHROME_PROFILE_DIRECTORY", "Default"),
        chrome_automation_profile_dir=Path(
            os.getenv(
                "CHROME_AUTOMATION_PROFILE_DIR",
                str(root / ".chrome-automation-profile"),
            )
        ),
        headless=_env_bool("HEADLESS", False),
        browser_channel=os.getenv("BROWSER_CHANNEL", "chrome"),
        delay_min=_env_float("DELAY_MIN", 1.0),
        delay_max=_env_float("DELAY_MAX", 3.0),
        page_load_timeout_ms=_env_int("PAGE_LOAD_TIMEOUT_MS", 60_000),
        chatgpt_response_timeout_sec=_env_int("CHATGPT_RESPONSE_TIMEOUT_SEC", 180),
        chatgpt_stability_checks=_env_int("CHATGPT_STABILITY_CHECKS", 3),
        chatgpt_stability_interval_sec=_env_float(
            "CHATGPT_STABILITY_INTERVAL_SEC", 2.0
        ),
        retry_count=_env_int("RETRY_COUNT", 1),
        max_pagination_retries=_env_int("MAX_PAGINATION_RETRIES", 3),
        test_mode=_env_bool("TEST_MODE", False),
        test_mode_limit=_env_int("TEST_MODE_LIMIT", 3),
        approval_mode=_env_bool("APPROVAL_MODE", False),
        use_control_panel=_env_bool("USE_CONTROL_PANEL", False),
        connect_dry_run=_env_bool("CONNECT_DRY_RUN", False),
        profile_extraction_retries=_env_int("PROFILE_EXTRACTION_RETRIES", 3),
        browser_reconnect_retries=_env_int("BROWSER_RECONNECT_RETRIES", 3),
        sales_nav_url_pattern=os.getenv("SALES_NAV_URL_PATTERN", "linkedin.com/sales"),
        chatgpt_url_pattern=os.getenv("CHATGPT_URL_PATTERN", "chatgpt.com"),
        project_root=root,
        results_xlsx=Path(os.getenv("RESULTS_XLSX", str(root / "results.xlsx"))),
        results_csv=Path(os.getenv("RESULTS_CSV", str(root / "results.csv"))),
        processed_profiles_json=Path(
            os.getenv("PROCESSED_PROFILES_JSON", str(root / "processed_profiles.json"))
        ),
        database_path=Path(os.getenv("DATABASE_PATH", str(root / "prospects.db"))),
        logs_dir=logs_dir,
        screenshots_dir=screenshots_dir,
        log_file=Path(os.getenv("LOG_FILE", str(logs_dir / "automation.log"))),
        pinned_tabs_json=Path(
            os.getenv("PINNED_TABS_JSON", str(root / "pinned_tabs.json"))
        ),
    )
