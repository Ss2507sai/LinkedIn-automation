"""Validation rules for extracted prospect profile data."""

from __future__ import annotations

from dataclasses import dataclass

from src.control import is_valid_profile_name


@dataclass
class ValidationResult:
    valid: bool
    errors: list[str]

    def message(self) -> str:
        return "; ".join(self.errors)


def validate_profile_data(profile) -> ValidationResult:
    errors: list[str] = []

    name = (profile.full_name or "").strip()
    if not name:
        errors.append("empty name")
    elif not is_valid_profile_name(name):
        errors.append(f"invalid name: {name!r}")
    elif name.lower() == "sales navigator lead page":
        errors.append("rejected name: Sales Navigator Lead Page")

    if not (profile.current_job_title or "").strip():
        errors.append("empty job title")

    if not (profile.company_name or "").strip():
        errors.append("empty company name")

    return ValidationResult(valid=len(errors) == 0, errors=errors)
