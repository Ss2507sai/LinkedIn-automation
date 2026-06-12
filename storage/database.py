"""SQLite storage for prospect connection tracking."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from src.logger import get_logger
from src.utils import normalize_linkedin_url
from storage.status import CONNECTION_SENT, GENERATED

logger = get_logger()

SCHEMA = """
CREATE TABLE IF NOT EXISTS prospects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    name TEXT NOT NULL,
    title TEXT,
    company TEXT,
    location TEXT,
    profile_url TEXT NOT NULL,
    connection_request TEXT,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_prospects_profile_url ON prospects(profile_url);
"""


@dataclass
class ProspectRecord:
    name: str
    title: str
    company: str
    location: str
    profile_url: str
    connection_request: str
    status: str


class ProspectDatabase:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript(SCHEMA)

    def upsert_prospect(self, record: ProspectRecord) -> None:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        normalized = normalize_linkedin_url(record.profile_url)
        with sqlite3.connect(self.db_path) as conn:
            existing = conn.execute(
                "SELECT id FROM prospects WHERE profile_url = ?",
                (normalized,),
            ).fetchone()
            if existing:
                conn.execute(
                    """
                    UPDATE prospects SET
                        timestamp = ?, name = ?, title = ?, company = ?, location = ?,
                        connection_request = ?, status = ?, updated_at = ?
                    WHERE profile_url = ?
                    """,
                    (
                        now,
                        record.name,
                        record.title,
                        record.company,
                        record.location,
                        record.connection_request,
                        record.status,
                        now,
                        normalized,
                    ),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO prospects (
                        timestamp, name, title, company, location, profile_url,
                        connection_request, status, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        now,
                        record.name,
                        record.title,
                        record.company,
                        record.location,
                        normalized,
                        record.connection_request,
                        record.status,
                        now,
                        now,
                    ),
                )
            conn.commit()
        logger.info("Database saved: %s — %s", record.name, record.status)

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
        self.upsert_prospect(
            ProspectRecord(
                name=name,
                title=title,
                company=company,
                location=location,
                profile_url=profile_url,
                connection_request=connection_request,
                status=GENERATED,
            )
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
        self.upsert_prospect(
            ProspectRecord(
                name=name,
                title=title,
                company=company,
                location=location,
                profile_url=profile_url,
                connection_request=connection_request,
                status=CONNECTION_SENT,
            )
        )

    def is_connection_sent(self, profile_url: str) -> bool:
        normalized = normalize_linkedin_url(profile_url)
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT status FROM prospects WHERE profile_url = ?",
                (normalized,),
            ).fetchone()
        return bool(row and row[0] == CONNECTION_SENT)

    def update_status(self, profile_url: str, status: str) -> None:
        normalized = normalize_linkedin_url(profile_url)
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE prospects SET status = ?, updated_at = ? WHERE profile_url = ?",
                (status, now, normalized),
            )
            conn.commit()
