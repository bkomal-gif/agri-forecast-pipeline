"""Stage 4 - Message composition: advisories -> localized sentences.

Wording lives in config/templates.yaml, keyed by language and advisory code, so
adding a language or revising wording to meet field-research standards is a
content change, not a code change. If a translation is missing, the pipeline
falls back to English and records a warning, rather than failing silently or
sending nothing.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from .models import Advisory, Location


@dataclass
class ComposedMessage:
    location_id: str
    language: str
    header: str
    lines: list[str]                    # one sentence per advisory, priority order
    advisories: list[Advisory]
    warnings: list[str] = field(default_factory=list)


def day_phrase(adv: Advisory, run_date: date, lang_tpl: dict) -> str:
    if adv.day_offset is None:
        return ""
    words = lang_tpl["day_words"]
    if adv.day_offset in (0, 1, 2) and str(adv.day_offset) in words:
        return words[str(adv.day_offset)]
    return words["other"].format(date=adv.date.strftime("%d/%m"))


def compose(location: Location, advisories: list[Advisory], run_date: date,
            templates: dict, language: str | None = None) -> ComposedMessage:
    lang = language or location.language
    warnings: list[str] = []
    if lang not in templates:
        warnings.append(f"no templates for language '{lang}', fell back to 'en'")
        lang = "en"
    tpl = templates[lang]

    header = tpl["header"].format(place=location.display_name(lang))
    lines = []
    for adv in advisories:
        text_tpl = tpl["advisories"].get(adv.code)
        used = tpl
        if text_tpl is None:
            warnings.append(f"no '{lang}' template for '{adv.code}', used 'en'")
            used = templates["en"]
            text_tpl = used["advisories"][adv.code]
        sentence = text_tpl.format(day=day_phrase(adv, run_date, used), **adv.params)
        lines.append(sentence[0].upper() + sentence[1:] if sentence else sentence)
    if not advisories:
        lines.append(tpl["no_advisory"])
    return ComposedMessage(location.id, lang, header, lines, advisories, warnings)
