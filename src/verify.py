"""Project verification — static checks and functional smoke tests (no live browser)."""

from __future__ import annotations

import importlib
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

MODULES = [
    "config.settings",
    "config.prompts",
    "config",
    "src.errors",
    "src.utils",
    "src.logger",
    "src.screenshots",
    "src.browser",
    "src.orchestrator",
    "src.session_setup",
    "src.tab_registry",
    "src.main",
    "scrapers.linkedin_profile",
    "scrapers.linkedin_connect",
    "scrapers.sales_navigator",
    "scrapers",
    "storage.database",
    "storage.status",
    "chatgpt.parser",
    "chatgpt.waiter",
    "chatgpt.client",
    "chatgpt",
    "storage.results",
    "storage.processed",
    "storage.csv_writer",
    "storage.excel_writer",
    "storage.result_storage",
    "storage",
]

SYMBOL_CHECKS = [
    ("config", ("Settings", "get_settings")),
    ("scrapers", ("LinkedInProfileScraper", "ProfileData", "ProspectCard", "SalesNavigatorScraper")),
    ("chatgpt", ("ChatGPTClient", "ParsedResponse", "parse_chatgpt_response", "wait_for_generation_complete")),
    ("storage", ("CSVWriter", "ExcelWriter", "ProcessedProfilesStore", "ProspectResult", "ResultStorage")),
    ("src.orchestrator", ("AutomationOrchestrator", "install_signal_handlers")),
    (
        "config.prompts",
        (
            "build_prompt",
            "build_profile_submission",
            "MASTER_INSTRUCTIONS",
            "CONNECTION_REQUEST_PROMPT_TEMPLATE",
        ),
    ),
    (
        "src.errors",
        (
            "AutomationError",
            "BrowserConnectionError",
            "TabNotFoundError",
            "ScrapingError",
            "ChatGPTError",
            "ChatGPTTimeoutError",
            "ParseError",
            "PaginationError",
        ),
    ),
]


def verify_imports() -> list[str]:
    """Import every project module; return error messages."""
    errors: list[str] = []
    for module in MODULES:
        try:
            importlib.import_module(module)
        except Exception as exc:
            errors.append(f"Import failed: {module}: {exc}")
    return errors


def verify_symbols() -> list[str]:
    """Verify exported public symbols exist."""
    errors: list[str] = []
    for module_name, names in SYMBOL_CHECKS:
        module = importlib.import_module(module_name)
        for name in names:
            if not hasattr(module, name):
                errors.append(f"Missing symbol: {module_name}.{name}")
    return errors


def verify_parser() -> list[str]:
    """Test ChatGPT response parsing."""
    from chatgpt.parser import parse_chatgpt_response

    sample = """
CONNECTION_REQUEST:
Hi John, loved your work at Acme.

MESSAGE_1:
Thanks for connecting!
"""
    try:
        parsed = parse_chatgpt_response(sample)
        if not parsed.connection_request.startswith("Hi John"):
            return ["Parser: connection_request mismatch"]
        if "Thanks for connecting" in parsed.connection_request:
            return ["Parser: did not trim extra sections"]
        if len(parsed.connection_request) > 300:
            return ["Parser: connection request exceeds 300 chars"]
    except Exception as exc:
        return [f"Parser test failed: {exc}"]
    return []


def verify_prompt() -> list[str]:
    """Test prompt template rendering."""
    from config.prompts import MASTER_INSTRUCTIONS, build_profile_submission, build_prompt

    try:
        prompt = build_prompt("Name: Jane Doe")
        if "Jane Doe" not in prompt or "Wavity" not in prompt:
            return ["Prompt template missing expected content"]
        profile_msg = build_profile_submission("Name: Jane Doe")
        if "Jane Doe" not in profile_msg or "Wavity" in profile_msg:
            return ["Profile submission should contain data only, not master instructions"]
        if "CONNECTION_REQUEST" not in MASTER_INSTRUCTIONS:
            return ["Master instructions missing CONNECTION_REQUEST format"]
    except Exception as exc:
        return [f"Prompt test failed: {exc}"]
    return []


def verify_storage() -> list[str]:
    """Test CSV, Excel, and processed-profile persistence."""
    from storage.csv_writer import CSVWriter
    from storage.excel_writer import ExcelWriter
    from storage.processed import ProcessedProfilesStore
    from storage.results import ProspectResult
    from src.utils import normalize_linkedin_url

    try:
        assert (
            normalize_linkedin_url("https://www.linkedin.com/in/john/?trk=foo")
            == "https://www.linkedin.com/in/john"
        )

        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            processed_path = base / "processed.json"
            store = ProcessedProfilesStore(processed_path)
            store.mark_processed("https://www.linkedin.com/in/test/")
            if not store.is_processed("https://www.linkedin.com/in/test?x=1"):
                return ["Processed store: duplicate detection failed"]

            store2 = ProcessedProfilesStore(processed_path)
            if not store2.is_processed("https://www.linkedin.com/in/test"):
                return ["Processed store: reload failed"]

            result = ProspectResult.create(
                name="Test User",
                title="CEO",
                company="Acme",
                location="NYC",
                profile_url="https://linkedin.com/in/test",
                connection_request="hi",
                status="Connection Sent",
            )
            CSVWriter(base / "results.csv").append(result)
            ExcelWriter(base / "results.xlsx").append(result)

            if not (base / "results.csv").exists():
                return ["CSV writer did not create file"]
            if not (base / "results.xlsx").exists():
                return ["Excel writer did not create file"]
    except Exception as exc:
        return [f"Storage test failed: {exc}"]
    return []


def run_verification() -> tuple[bool, list[str]]:
    """Run all verification checks. Returns (success, issues)."""
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))

    issues: list[str] = []
    issues.extend(verify_imports())
    issues.extend(verify_symbols())
    issues.extend(verify_parser())
    issues.extend(verify_prompt())
    issues.extend(verify_storage())
    return len(issues) == 0, issues
