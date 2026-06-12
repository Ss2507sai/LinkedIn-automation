"""Unified storage facade for immediate per-prospect saves."""

from __future__ import annotations

from config.settings import Settings
from src.logger import get_logger
from storage.csv_writer import CSVWriter
from storage.database import ProspectDatabase
from storage.excel_writer import ExcelWriter
from storage.processed import ProcessedProfilesStore
from storage.results import ProspectResult
from storage.status import CONNECTION_SENT

logger = get_logger()


class ResultStorage:
    """Saves results to Excel, CSV, SQLite, and processed profiles store."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.excel = ExcelWriter(settings.results_xlsx)
        self.csv = CSVWriter(settings.results_csv)
        self.processed = ProcessedProfilesStore(settings.processed_profiles_json)
        self.database = ProspectDatabase(settings.database_path)

    def is_connection_sent(self, profile_url: str) -> bool:
        return self.database.is_connection_sent(profile_url)

    def save_generated(
        self,
        *,
        name: str,
        title: str,
        company: str,
        location: str,
        profile_url: str,
        connection_request: str,
    ) -> None:
        self.database.save_generated(
            name=name,
            title=title,
            company=company,
            location=location,
            profile_url=profile_url,
            connection_request=connection_request,
        )

    def save_connection_sent(
        self,
        *,
        name: str,
        title: str,
        company: str,
        location: str,
        profile_url: str,
        connection_request: str,
    ) -> None:
        self.database.save_connection_sent(
            name=name,
            title=title,
            company=company,
            location=location,
            profile_url=profile_url,
            connection_request=connection_request,
        )

    def save_success(
        self,
        result: ProspectResult,
        profile_url: str,
        *,
        mark_processed: bool = True,
    ) -> None:
        """Save successful result immediately."""
        self.excel.append(result)
        self.csv.append(result)
        if mark_processed:
            self.processed.mark_processed(profile_url)
        logger.info("Results saved for %s (%s)", result.name, result.status)

    def save_failure(
        self,
        result: ProspectResult,
        profile_url: str,
        mark_processed: bool = True,
    ) -> None:
        """Save failed result and optionally mark as processed to avoid retry loops."""
        self.excel.append(result)
        self.csv.append(result)
        if mark_processed:
            self.processed.mark_processed(profile_url)
        logger.info("Failure recorded for %s", result.name)
