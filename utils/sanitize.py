"""Input sanitization utilities for security hardening."""

import re


def escape_regex(s: str) -> str:
    """Escape regex metacharacters so *s* matches literally in $regex.

    Uses stdlib ``re.escape`` which escapes exactly the regex-special
    character set (``.*+?^${}()|[]\\``).  Safe to call on user-supplied
    search strings before passing them to MongoDB ``$regex`` queries.
    """
    return re.escape(s)
