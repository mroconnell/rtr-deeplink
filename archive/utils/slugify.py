import re
import secrets

_NON_ALNUM = re.compile(r"[^a-z0-9]+")
MAX_BASE_LENGTH = 80


def _slugify_part(text: str) -> str:
    text = (text or "").lower()
    text = _NON_ALNUM.sub("-", text)
    return text.strip("-")


def slugify_text(text: str) -> str:
    """Public form of the one slug rule this app uses everywhere (lowercase,
    runs of non-alphanumerics -> "-", trimmed) -- so a caller building a
    slug from a single string (jurisdiction_format.jurisdiction_hub_slug())
    gets byte-identical output to build_base_slug()'s per-part treatment
    of the same text, rather than a second, subtly different rule."""
    return _slugify_part(text)


def build_base_slug(jurisdiction: str = "", date: str = "", title: str = "") -> str:
    """A readable slug base from jurisdiction/date/title -- not guaranteed
    unique on its own, see random_suffix(). Falls back to "meeting" if all
    three inputs are empty (e.g. a platform that never gave us metadata),
    so callers never have to special-case an empty slug.
    """
    parts = [_slugify_part(p) for p in (jurisdiction, date, title) if p]
    base = "-".join(p for p in parts if p) or "meeting"
    if len(base) > MAX_BASE_LENGTH:
        base = base[:MAX_BASE_LENGTH].rstrip("-")
    return base


def random_suffix(length: int = 6) -> str:
    # Short, URL-safe, collision-resistant enough for a "append on the rare
    # collision" fallback -- not trying to be a UUID.
    return secrets.token_hex(length // 2 + 1)[:length]
