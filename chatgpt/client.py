"""ChatGPT browser tab interaction — single conversation, text-only."""

from __future__ import annotations

from typing import TYPE_CHECKING

from config.prompts import MASTER_INSTRUCTIONS, build_profile_submission
from src.errors import ChatGPTError
from src.logger import get_logger
from src.utils import human_delay

if TYPE_CHECKING:
    from playwright.sync_api import Page

    from config.settings import Settings

from chatgpt.parser import ParsedResponse, parse_chatgpt_response
from chatgpt.waiter import _count_assistant_messages, _is_generating, wait_for_generation_complete

logger = get_logger()

COMPOSER_ROOT_SELECTORS = [
    "form[data-type='unified-composer']",
    "[data-testid='composer-parent']",
    "#thread-bottom",
    "main form",
]

TEXT_INPUT_SELECTORS = [
    "#prompt-textarea",
    "textarea#prompt-textarea",
    'div#prompt-textarea[contenteditable="true"]',
    '[data-testid="composer-textarea"]',
    "div.ProseMirror[contenteditable='true']",
]

SUBMIT_SELECTORS = [
    'button[data-testid="send-button"]',
    'button[aria-label="Send prompt"]',
    'button[aria-label="Send message"]',
]

NEW_CHAT_SELECTORS = [
    '[data-testid="create-new-chat-button"]',
    'a[href="/"]',
    'button:has-text("New chat")',
    '[aria-label="New chat"]',
]

VOICE_BUTTON_SELECTORS = [
    'button[data-testid="composer-speech-button"]',
    'button[aria-label*="Voice"]',
    'button[aria-label*="Dictate"]',
    'button[aria-label*="speech"]',
    'button[aria-label*="microphone"]',
    'button[aria-label*="Start voice"]',
    'button[aria-label*="Stop dictation"]',
]


class ChatGPTClient:
    """Single ChatGPT tab — one conversation for the entire run."""

    def __init__(self, page: Page, settings: Settings) -> None:
        self.page = page
        self.settings = settings
        self._conversation_ready = False

    def setup_conversation(self) -> None:
        """Open a new chat and paste master instructions once."""
        self.page.bring_to_front()
        human_delay(self.settings)
        self._start_new_chat()
        self._focus_text_input()
        self._clear_text_input()
        self._type_prompt(MASTER_INSTRUCTIONS)
        baseline = _count_assistant_messages(self.page)
        self._submit_once(baseline_messages=baseline)
        wait_for_generation_complete(
            self.page,
            self.settings,
            baseline_message_count=baseline,
            require_marker=None,
        )
        self._conversation_ready = True
        logger.info("ChatGPT conversation initialized with master instructions")

    def submit_profile(self, profile_data: str) -> tuple[ParsedResponse, str, str]:
        """Paste profile data only, submit once, wait for CONNECTION_REQUEST."""
        if not self._conversation_ready:
            raise ChatGPTError("ChatGPT conversation not initialized — run setup_conversation first")

        message = build_profile_submission(profile_data)
        self.page.bring_to_front()
        human_delay(self.settings)
        self._focus_text_input()
        self._clear_text_input()
        self._type_prompt(message)

        baseline = _count_assistant_messages(self.page)
        logger.info("ChatGPT profile submitted (%d chars)", len(message))
        self._submit_once(baseline_messages=baseline)

        raw_response = wait_for_generation_complete(
            self.page,
            self.settings,
            baseline_message_count=baseline,
            require_marker="CONNECTION_REQUEST",
        )
        logger.info("ChatGPT CONNECTION_REQUEST received")
        return parse_chatgpt_response(raw_response), message, raw_response

    def generate_outreach(
        self,
        profile_data: str,
        *,
        custom_prompt: str | None = None,
    ) -> tuple[ParsedResponse, str, str]:
        """Legacy single-shot path (audits). Uses submit_profile when conversation is ready."""
        if self._conversation_ready and custom_prompt is None:
            return self.submit_profile(profile_data)

        from config.prompts import build_prompt

        prompt = custom_prompt or build_prompt(profile_data)
        self._focus_text_input()
        self._clear_text_input()
        self._type_prompt(prompt)
        baseline = _count_assistant_messages(self.page)
        self._submit_once(baseline_messages=baseline)
        raw_response = wait_for_generation_complete(
            self.page,
            self.settings,
            baseline_message_count=baseline,
            require_marker="CONNECTION_REQUEST",
        )
        return parse_chatgpt_response(raw_response), prompt, raw_response

    def is_voice_mode_active(self) -> bool:
        for selector in VOICE_BUTTON_SELECTORS:
            try:
                btn = self.page.locator(selector).first
                if not btn.is_visible(timeout=300):
                    continue
                pressed = btn.get_attribute("aria-pressed")
                if pressed == "true":
                    return True
                label = (btn.get_attribute("aria-label") or "").lower()
                if "stop" in label and ("dictat" in label or "voice" in label):
                    return True
            except Exception:
                continue

        for text in ("Listening", "Stop dictation", "Voice mode"):
            try:
                if self.page.get_by_text(text, exact=False).first.is_visible(timeout=200):
                    return True
            except Exception:
                continue
        return False

    def _start_new_chat(self) -> None:
        for selector in NEW_CHAT_SELECTORS:
            try:
                el = self.page.locator(selector).first
                if el.is_visible(timeout=2000):
                    el.click(timeout=3000)
                    self.page.wait_for_timeout(1500)
                    logger.info("Started new ChatGPT chat via %s", selector)
                    return
            except Exception:
                continue
        logger.warning("New chat button not found — using current conversation")

    def _composer(self):
        for selector in COMPOSER_ROOT_SELECTORS:
            try:
                root = self.page.locator(selector).first
                if root.count() and root.is_visible(timeout=1000):
                    return root
            except Exception:
                continue
        return self.page.locator("main").first

    def _find_text_input(self):
        composer = self._composer()
        for selector in TEXT_INPUT_SELECTORS:
            try:
                input_el = composer.locator(selector).first
                if input_el.count() and input_el.is_visible(timeout=2000):
                    return input_el
            except Exception:
                continue

        try:
            input_el = composer.get_by_role("textbox").first
            if input_el.is_visible(timeout=2000):
                return input_el
        except Exception:
            pass

        raise ChatGPTError("Could not find ChatGPT text input field")

    def _focus_text_input(self) -> None:
        if self.is_voice_mode_active():
            logger.warning("Voice mode active — using focus() only, never mic controls")

        input_el = self._find_text_input()
        input_el.focus(timeout=3000)
        logger.info("ChatGPT text input focused")

    def _clear_text_input(self) -> None:
        input_el = self._find_text_input()
        tag = input_el.evaluate("el => el.tagName.toLowerCase()")
        if tag == "textarea":
            input_el.fill("")
        else:
            input_el.evaluate("el => { el.innerHTML = ''; el.textContent = ''; }")

    def _type_prompt(self, prompt: str) -> None:
        input_el = self._find_text_input()
        tag = input_el.evaluate("el => el.tagName.toLowerCase()")
        if tag == "textarea":
            input_el.fill(prompt)
        else:
            input_el.focus()
            self.page.keyboard.insert_text(prompt)

    def _submit_once(self, *, baseline_messages: int) -> None:
        """Submit exactly once — send button OR Enter, never both."""
        composer = self._composer()

        for selector in SUBMIT_SELECTORS:
            try:
                button = composer.locator(selector).first
                if not button.is_visible(timeout=2000) or not button.is_enabled():
                    continue
                button.click(timeout=5000)
                human_delay(self.settings)
                logger.info("Submitted via %s", selector)
                if self.is_voice_mode_active():
                    raise ChatGPTError("Voice mode activated after send click")
                return
            except ChatGPTError:
                raise
            except Exception as exc:
                if _is_generating(self.page) or _count_assistant_messages(self.page) > baseline_messages:
                    logger.info("Submit succeeded (generation detected) despite: %s", exc)
                    return
                logger.debug("Send button %s failed: %s", selector, exc)

        input_el = self._find_text_input()
        logger.info("Submitting via Enter on text input")
        input_el.press("Enter")
        human_delay(self.settings)
        if self.is_voice_mode_active():
            raise ChatGPTError("Voice mode activated after Enter submit")
