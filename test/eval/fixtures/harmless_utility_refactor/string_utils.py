"""String manipulation helpers.

Extracted from inline usage across the codebase. Pure utility
functions with no security implications.
"""


def slugify(text: str) -> str:
    """Convert text to URL-safe slug."""
    return (
        text.lower()
        .replace(" ", "-")
        .replace("_", "-")
        .strip("-")
    )


def truncate(text: str, max_length: int = 100, suffix: str = "...") -> str:
    """Truncate text to max_length, adding suffix if truncated."""
    if len(text) <= max_length:
        return text
    return text[: max_length - len(suffix)] + suffix


def strip_html(text: str) -> str:
    """Remove basic HTML tags from text (not security-relevant)."""
    import re
    return re.sub(r"<[^>]+>", "", text)
