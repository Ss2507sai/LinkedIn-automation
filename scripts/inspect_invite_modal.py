#!/usr/bin/env python3
"""One-off: inspect LinkedIn SN invite modal DOM for note field selectors."""

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import get_settings
from scrapers.linkedin_connect import LinkedInConnectSender
from scrapers.sales_navigator import SalesNavigatorScraper
from src.browser import BrowserManager


def main() -> None:
    settings = get_settings()
    browser = BrowserManager(settings)
    browser.connect()
    page = browser.find_page_by_url_pattern(settings.sales_nav_url_pattern)
    browser.bring_to_front(page)
    scraper = SalesNavigatorScraper(page, settings)
    prospects = scraper.get_visible_prospects()
    if not prospects:
        print("No prospects found")
        return
    prospect = prospects[0]
    sender = LinkedInConnectSender(page, settings)
    sender.open_connect_dialog(prospect)
    info = page.evaluate(
        """() => {
        const modals = [...document.querySelectorAll(
            '[role="dialog"], .artdeco-modal, .send-invite'
        )];
        const modal = modals.find(m =>
            m.textContent && m.textContent.includes('Send invitation')
        ) || modals[modals.length - 1];
        if (!modal) return { error: 'no modal' };
        const fields = [...modal.querySelectorAll(
            'textarea, input, [contenteditable="true"]'
        )].map(el => ({
            tag: el.tagName,
            id: el.id,
            name: el.name,
            className: el.className,
            placeholder: el.placeholder || el.getAttribute('placeholder') || '',
            ariaLabel: el.getAttribute('aria-label') || '',
            visible: !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length),
            value: (el.value || el.textContent || '').slice(0, 80),
        }));
        return {
            modalTag: modal.tagName,
            modalRole: modal.getAttribute('role'),
            modalClass: modal.className,
            fields,
            modalText: modal.textContent.slice(0, 200),
        };
    }"""
    )
    print(json.dumps(info, indent=2))
    sender.close_dialog()
    browser.close()


if __name__ == "__main__":
    main()
