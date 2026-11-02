"""
Languages: English, Spanish, Hindi, Urdu.

Every word a person reads comes from one catalog per language in
dtr/static/locales/<code>.json. The screens and the server read the same
files, so a message never exists in only one place.

The server never builds a sentence in English and sends it. It sends a
`Msg` (a message key plus its blanks), and `tr()` fills it in the reader's
language just before the reply leaves. The browser says which language it
wants in the X-Lang header.

Records people type (a complaint, a correction) stay in the language they
were typed in. Only the software's own words are translated.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi import Request

LOCALES = Path(__file__).parent / "static" / "locales"
LANGUAGES = {"en": "English", "es": "Español", "hi": "हिन्दी", "ur": "اردو"}
RTL = {"ur"}
DEFAULT = "en"


@lru_cache(maxsize=None)
def catalog(lang: str) -> dict[str, str]:
    path = LOCALES / f"{lang}.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


class Msg(dict):
    """A message to be translated: {"key": ..., plus the values for blanks}."""

    def __init__(self, key: str, **params: Any):
        super().__init__(key=key, **params)


def text(key: str, lang: str = DEFAULT, **params: Any) -> str:
    """One message in one language. Falls back to English, then to the key."""
    s = catalog(lang).get(key) or catalog(DEFAULT).get(key) or key
    params = {k: tr(v, lang) for k, v in params.items()}
    try:
        return s.format(**params)
    except (KeyError, IndexError, ValueError):
        return s


def tr(value: Any, lang: str = DEFAULT) -> Any:
    """Translate every Msg inside a reply, however deeply nested."""
    if isinstance(value, Msg):
        params = {k: v for k, v in value.items() if k != "key"}
        return text(value["key"], lang, **params)
    if isinstance(value, dict):
        return {k: tr(v, lang) for k, v in value.items()}
    if isinstance(value, list):
        return [tr(v, lang) for v in value]
    return value


def pick(lang: str | None) -> str:
    lang = (lang or "").strip().lower()[:2]
    return lang if lang in LANGUAGES else DEFAULT


def lang_of(request: Request) -> str:
    """FastAPI dependency: the language this request wants."""
    return pick(request.headers.get("x-lang"))


class Problem(Exception):
    """
    Refuse a request with a translated message.

        raise Problem(403, Msg("err.not_allowed"))
        raise Problem(400, {"errors": [Msg(...)], "warnings": [...]})
    """

    def __init__(self, status: int, detail: Any):
        self.status = status
        self.detail = detail
