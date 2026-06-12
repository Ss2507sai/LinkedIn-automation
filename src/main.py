#!/usr/bin/env python3
"""Wavity LinkedIn Sales Navigator automation — entry point."""

from __future__ import annotations

import argparse
import sys
import threading
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import get_settings  # noqa: E402
from src.control import AutomationControl  # noqa: E402
from src.control_panel import ControlPanel  # noqa: E402
from src.errors import BrowserConnectionError, TabNotFoundError  # noqa: E402
from src.logger import setup_logging  # noqa: E402
from src.orchestrator import AutomationOrchestrator, install_signal_handlers  # noqa: E402
from src.smoke_browser import run_browser_smoke  # noqa: E402
from src.connect_test import run_connect_test  # noqa: E402
from src.debug_session import run_debug_session  # noqa: E402
from src.stability_audit import run_stability_audit  # noqa: E402
from src.verify import run_verification  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Wavity LinkedIn Sales Navigator + ChatGPT automation"
    )
    parser.add_argument("--test", action="store_true", help="Process up to 3 profiles")
    parser.add_argument("--full", action="store_true", help="No profile limit")
    parser.add_argument(
        "--limit",
        type=int,
        metavar="N",
        help="Process at most N profiles (e.g. 1, 3, 50)",
    )
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--smoke-browser", action="store_true")
    parser.add_argument("--panel", action="store_true", help="Launch desktop control panel")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Paste connection note but do not click Send",
    )
    parser.add_argument("--approval", action="store_true", help="Legacy approval mode (deprecated)")
    parser.add_argument("--auto", action="store_true", help="Auto mode (default)")
    parser.add_argument(
        "--audit",
        type=int,
        nargs="?",
        const=20,
        metavar="N",
        help="Run stability audit against N profiles (default 20)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Run single-profile debug session with maximum logging",
    )
    parser.add_argument(
        "--connect-test",
        type=int,
        nargs="?",
        const=3,
        metavar="N",
        help="Run connection workflow test on N profiles (dry run, default 3)",
    )
    return parser.parse_args()


def _run_orchestrator(settings, control: AutomationControl) -> None:
    logger = setup_logging(settings)
    orchestrator = AutomationOrchestrator(settings, control=control)
    install_signal_handlers(orchestrator)
    try:
        orchestrator.run()
    except (BrowserConnectionError, TabNotFoundError) as exc:
        logger.error("Automation failed: %s", exc)


def main() -> int:
    args = parse_args()
    settings = get_settings()
    settings.ensure_directories()

    if args.verify:
        ok, issues = run_verification()
        if ok:
            print("Verification passed: all imports, symbols, and smoke tests OK")
            return 0
        print("Verification failed:")
        for issue in issues:
            print(f"  - {issue}")
        return 1

    if args.audit is not None:
        report = run_stability_audit(limit=args.audit)
        print(f"Stability audit complete: {report}")
        return 0

    if args.debug:
        report = run_debug_session()
        print(f"Debug session complete: {report}")
        return 0

    if args.connect_test is not None:
        report = run_connect_test(limit=args.connect_test)
        print(f"Connection test complete: {report}")
        return 0

    if args.smoke_browser:
        logger = setup_logging(settings)
        ok, issues = run_browser_smoke(settings)
        if ok:
            logger.info("Browser smoke test passed")
            return 0
        for issue in issues:
            logger.error("Smoke issue: %s", issue)
        return 1

    if args.limit is not None:
        settings.test_mode = True
        settings.test_mode_limit = args.limit
    elif args.test:
        settings.test_mode = True
    elif args.full:
        settings.test_mode = False

    if args.headless:
        settings.headless = True
    if args.dry_run:
        settings.connect_dry_run = True
    if args.approval:
        settings.approval_mode = True
    if args.auto:
        settings.approval_mode = False
    if args.panel:
        settings.use_control_panel = True

    approval_mode = settings.approval_mode
    control = AutomationControl(approval_mode=approval_mode)

    if settings.use_control_panel:
        settings.ensure_directories()
        setup_logging(settings)

        def start_automation() -> None:
            _run_orchestrator(settings, control)

        panel = ControlPanel(control, on_start=start_automation)
        panel.run()
        return 0

    logger = setup_logging(settings)
    logger.info("=" * 60)
    logger.info("Wavity LinkedIn Automation")
    logger.info("Mode: %s", "TEST" if settings.test_mode else "FULL")
    logger.info("Dry run: %s", settings.connect_dry_run)
    logger.info("CDP URL: %s", settings.cdp_url)
    logger.info("=" * 60)

    orchestrator = AutomationOrchestrator(settings, control=control)
    install_signal_handlers(orchestrator)

    try:
        orchestrator.run()
        return 0
    except (BrowserConnectionError, TabNotFoundError) as exc:
        logger.error("Automation failed: %s", exc)
        return 1
    except Exception as exc:
        logger.exception("Automation failed: %s", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
