"""Custom exceptions for the automation pipeline."""


class AutomationError(Exception):
    """Base exception for automation failures."""


class BrowserConnectionError(AutomationError):
    """Failed to connect to or interact with the browser."""


class TabNotFoundError(AutomationError):
    """Required browser tab could not be located."""


class ScrapingError(AutomationError):
    """Failed to extract data from a page."""


class ChatGPTError(AutomationError):
    """ChatGPT interaction failed."""


class ChatGPTTimeoutError(ChatGPTError):
    """ChatGPT did not finish generating within the timeout."""


class ParseError(AutomationError):
    """Failed to parse ChatGPT response or profile data."""


class PaginationError(AutomationError):
    """Failed to navigate Sales Navigator pagination."""


class InvitationPendingError(AutomationError):
    """LinkedIn invitation is already pending for this prospect."""
