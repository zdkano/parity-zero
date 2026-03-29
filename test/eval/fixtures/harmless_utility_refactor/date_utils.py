"""Date and time utility functions.

Refactored to use consistent naming and extract common patterns
into shared helpers. No security-relevant logic.
"""

from datetime import datetime, timezone, timedelta


def utc_now() -> datetime:
    """Return current UTC time as timezone-aware datetime."""
    return datetime.now(timezone.utc)


def format_iso(dt: datetime) -> str:
    """Format a datetime as ISO 8601 string."""
    return dt.isoformat()


def parse_iso(text: str) -> datetime:
    """Parse an ISO 8601 datetime string."""
    return datetime.fromisoformat(text)


def days_ago(n: int) -> datetime:
    """Return a datetime N days in the past."""
    return utc_now() - timedelta(days=n)


def is_recent(dt: datetime, hours: int = 24) -> bool:
    """Check if a datetime is within the last N hours."""
    cutoff = utc_now() - timedelta(hours=hours)
    return dt >= cutoff


def format_relative(dt: datetime) -> str:
    """Format a datetime as a human-readable relative string."""
    delta = utc_now() - dt
    if delta.days > 365:
        return f"{delta.days // 365} year(s) ago"
    if delta.days > 30:
        return f"{delta.days // 30} month(s) ago"
    if delta.days > 0:
        return f"{delta.days} day(s) ago"
    hours = delta.seconds // 3600
    if hours > 0:
        return f"{hours} hour(s) ago"
    minutes = delta.seconds // 60
    return f"{minutes} minute(s) ago"
