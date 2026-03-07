"""Japanese date formatting utilities for hiburi-tools.

Provides helpers for formatting dates in Japanese era (和暦) format
and common Japanese date/time display patterns.
"""

from datetime import date, datetime
from typing import Optional

# Japanese era definitions: (start_date, era_name, era_abbreviation)
_ERAS = [
    (date(2019, 5, 1), "令和", "R"),
    (date(1989, 1, 8), "平成", "H"),
    (date(1926, 12, 25), "昭和", "S"),
    (date(1912, 7, 30), "大正", "T"),
    (date(1868, 1, 25), "明治", "M"),
]

_WEEKDAYS_JA = ["月", "火", "水", "木", "金", "土", "日"]


def to_wareki(d: date) -> str:
    """Convert a date to Japanese era (和暦) format.

    Args:
        d: The date to convert.

    Returns:
        A string like "令和7年3月7日".

    Raises:
        ValueError: If the date is before the Meiji era (1868).
    """
    for era_start, era_name, _ in _ERAS:
        if d >= era_start:
            year = d.year - era_start.year + 1
            year_str = "元" if year == 1 else str(year)
            return f"{era_name}{year_str}年{d.month}月{d.day}日"
    raise ValueError(f"Date {d} is before the Meiji era and cannot be converted.")


def to_wareki_short(d: date) -> str:
    """Convert a date to abbreviated Japanese era format.

    Args:
        d: The date to convert.

    Returns:
        A string like "R07.03.07".

    Raises:
        ValueError: If the date is before the Meiji era (1868).
    """
    for era_start, _, era_abbr in _ERAS:
        if d >= era_start:
            year = d.year - era_start.year + 1
            return f"{era_abbr}{year:02d}.{d.month:02d}.{d.day:02d}"
    raise ValueError(f"Date {d} is before the Meiji era and cannot be converted.")


def format_date_ja(d: date, include_weekday: bool = True) -> str:
    """Format a date in standard Japanese display format.

    Args:
        d: The date to format.
        include_weekday: Whether to include the day of the week.

    Returns:
        A string like "2026年3月7日(土)" or "2026年3月7日".
    """
    base = f"{d.year}年{d.month}月{d.day}日"
    if include_weekday:
        weekday = _WEEKDAYS_JA[d.weekday()]
        return f"{base}({weekday})"
    return base


def format_datetime_ja(dt: datetime, include_seconds: bool = False) -> str:
    """Format a datetime in standard Japanese display format.

    Args:
        dt: The datetime to format.
        include_seconds: Whether to include seconds in the time portion.

    Returns:
        A string like "2026年3月7日(土) 14:30" or "2026年3月7日(土) 14:30:45".
    """
    date_part = format_date_ja(dt.date())
    if include_seconds:
        time_part = f"{dt.hour:02d}:{dt.minute:02d}:{dt.second:02d}"
    else:
        time_part = f"{dt.hour:02d}:{dt.minute:02d}"
    return f"{date_part} {time_part}"


def get_era_name(d: date) -> Optional[str]:
    """Get the Japanese era name for a given date.

    Args:
        d: The date to look up.

    Returns:
        The era name (e.g. "令和"), or None if before Meiji era.
    """
    for era_start, era_name, _ in _ERAS:
        if d >= era_start:
            return era_name
    return None
