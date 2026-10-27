"""Conservative IDs and exact decimal-to-minute parsing, without inference."""

import re
from dataclasses import asdict, dataclass
from fractions import Fraction
from typing import Any


@dataclass(frozen=True)
class Rating:
    state: str
    minutes: int | None
    reason: str

    def as_dict(self) -> dict:
        return asdict(self)


_RATING = re.compile(r"([0-9]+(?:\.[0-9]+)?|\.[0-9]+)\s*(min|mins|minute|minutes|h|hr|hrs|hour|hours)?", re.I)
_HOURS = {"h", "hr", "hrs", "hour", "hours"}


def normalize_id(raw: Any) -> str | None:
    """Preserve case, punctuation and leading zeros; never coerce numeric IDs."""
    return (raw.strip() or None) if isinstance(raw, str) else None


def normalize_rating(raw: Any, numeric_unit: str = "minutes") -> Rating:
    if numeric_unit not in ("minutes", "hours"):
        raise ValueError("numeric_unit must be minutes or hours")
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return Rating("missing", None, "Rating is absent from the supplied data.")
    if isinstance(raw, bool) or not isinstance(raw, (str, int, float)):
        return Rating("unsupported", None, "Rating must be a scalar number or supported text.")
    value = str(raw).strip()
    match = _RATING.fullmatch(value) if len(value) <= 128 else None
    if not match:
        return Rating("unsupported", None, "Unsupported format; no classification or unit inference applied.")
    number, unit = match.groups()
    hours = unit.lower() in _HOURS if unit else numeric_unit == "hours"
    minutes = Fraction(number) * (60 if hours else 1)
    if minutes.denominator != 1:
        return Rating("unsupported", None, "Rating does not represent an exact integer number of minutes.")
    return Rating("ok", minutes.numerator, "Explicit comparable duration.")
