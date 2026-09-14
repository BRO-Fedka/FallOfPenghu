"""UI language. Missing keys fall back to English."""

from __future__ import annotations

import json
from pathlib import Path

from fall_of_penghu.paths import package_dir

ROOT = package_dir()
I18N_DIR = ROOT / "data" / "i18n"

LANGS = ("en", "ru", "es", "de", "ja", "zh")
NATIVE = {
    "en": "English",
    "ru": "Русский",
    "es": "Español",
    "de": "Deutsch",
    "ja": "日本語",
    "zh": "中文",
}

_lang = "en"
_tables: dict[str, dict[str, str]] = {}


def language() -> str:
    return _lang


def set_language(code: str) -> str:
    global _lang
    _lang = code if code in LANGS else "en"
    _tables.pop(_lang, None)
    if _lang != "en":
        _tables.pop("en", None)
    _load(_lang)
    if _lang != "en":
        _load("en")
    return _lang


def t(key: str, default: str | None = None, **kwargs: object) -> str:
    text = _tables.get(_lang, {}).get(key)
    if not text:
        text = _tables.get("en", {}).get(key)
    if not text:
        text = default if default is not None else key
    if kwargs:
        try:
            return str(text).format(**kwargs)
        except (KeyError, IndexError, ValueError):
            return str(text)
    return str(text)


def counted(n: int, word: str) -> str:
    n = int(n)
    if _lang == "ru":
        forms = {
            "minute": ("минуту", "минуты", "минут"),
            "hour": ("час", "часа", "часов"),
            "day": ("день", "дня", "дней"),
        }
        unit = _plural_ru(n, *forms[word])
        return f"{n} {unit}"
    if _lang == "ja":
        units = {"minute": "分", "hour": "時間", "day": "日"}
        return f"{n}{units[word]}"
    if _lang == "zh":
        units = {"minute": "分钟", "hour": "小时", "day": "天"}
        return f"{n} {units[word]}"
    if _lang == "es":
        forms = {
            "minute": ("minuto", "minutos"),
            "hour": ("hora", "horas"),
            "day": ("día", "días"),
        }
        one, many = forms[word]
        return f"{n} {one if n == 1 else many}"
    if _lang == "de":
        forms = {
            "minute": ("Minute", "Minuten"),
            "hour": ("Stunde", "Stunden"),
            "day": ("Tag", "Tage"),
        }
        one, many = forms[word]
        return f"{n} {one if n == 1 else many}"
    unit = word if n == 1 else f"{word}s"
    return f"{n} {unit}"


def _plural_ru(n: int, one: str, few: str, many: str) -> str:
    n = abs(int(n)) % 100
    if 11 <= n <= 14:
        return many
    k = n % 10
    if k == 1:
        return one
    if 2 <= k <= 4:
        return few
    return many


def _load(code: str) -> None:
    if code in _tables:
        return
    path = I18N_DIR / f"{code}.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        _tables[code] = {}
        return
    if not isinstance(data, dict):
        _tables[code] = {}
        return
    _tables[code] = {str(k): str(v) for k, v in data.items()}


set_language("en")
