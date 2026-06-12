"""Result record model."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime


COLUMNS = [
    "Timestamp",
    "Name",
    "Title",
    "Company",
    "Location",
    "Profile URL",
    "Connection Request",
    "Status",
]


@dataclass
class ProspectResult:
    """A single processed prospect result row."""

    timestamp: str
    name: str
    title: str
    company: str
    location: str
    profile_url: str
    connection_request: str
    status: str

    @classmethod
    def create(
        cls,
        *,
        name: str,
        title: str,
        company: str,
        location: str,
        profile_url: str,
        connection_request: str = "",
        status: str = "success",
    ) -> ProspectResult:
        return cls(
            timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            name=name,
            title=title,
            company=company,
            location=location,
            profile_url=profile_url,
            connection_request=connection_request,
            status=status,
        )

    def to_row(self) -> dict[str, str]:
        """Convert to column-keyed dict matching export headers."""
        data = asdict(self)
        return {
            "Timestamp": data["timestamp"],
            "Name": data["name"],
            "Title": data["title"],
            "Company": data["company"],
            "Location": data["location"],
            "Profile URL": data["profile_url"],
            "Connection Request": data["connection_request"],
            "Status": data["status"],
        }
