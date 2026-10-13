"""Stage 5 - Channel adapters: one composed message -> vendor-ready payloads.

Each dissemination channel ingests data differently (160-character SMS segments,
pre-approved WhatsApp templates, text-to-speech scripts, structured context for
an LLM advisor). Adapters isolate those differences: the upstream pipeline
produces one ComposedMessage, and each adapter renders it for its channel.
Adding a vendor = adding one adapter class and one line in channels config.

The pipeline writes payloads to an outbox (JSONL) rather than calling vendor APIs
directly. A sender process consumes the outbox; `message_id` is a content hash,
so a retried run cannot double-send the same message.
"""
from __future__ import annotations

import hashlib
import re
import json
from datetime import date, datetime, time, timedelta, timezone

from .messages import ComposedMessage
from .models import DailyForecast, Location

IST = timezone(timedelta(hours=5, minutes=30))

# GSM 03.38 basic character set; the extension set costs 2 septets per char.
GSM7_BASIC = set(
    "@£$¥èéùìòÇ\nØø\rÅåΔ_ΦΓΛΩΠΨΣΘΞÆæßÉ !\"#¤%&'()*+,-./0123456789:;<=>?"
    "¡ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÑÜ§¿abcdefghijklmnopqrstuvwxyzäöñüà"
)
GSM7_EXT = set("^{}\\[~]|€")


def sms_encoding(text: str) -> tuple[str, int]:
    """Return (encoding, length in encoding units)."""
    if all(c in GSM7_BASIC or c in GSM7_EXT for c in text):
        return "GSM-7", sum(2 if c in GSM7_EXT else 1 for c in text)
    # UCS-2: Devanagari etc. Characters outside the BMP take 2 units.
    return "UCS-2", sum(2 if ord(c) > 0xFFFF else 1 for c in text)


_SENTENCE_END = re.compile(r"(?<=[.।])\s+")   # Latin full stop or Devanagari danda


def headline(line: str) -> str:
    """First sentence of an advisory: by template convention, the forecast itself."""
    return _SENTENCE_END.split(line, maxsplit=1)[0]


def sms_segments(text: str) -> tuple[str, int]:
    enc, n = sms_encoding(text)
    single, multi = (160, 153) if enc == "GSM-7" else (70, 67)
    if n <= single:
        return enc, 1
    return enc, -(-n // multi)  # ceiling division


def expires_at(run_date: date) -> str:
    # Messages say "today"/"tomorrow". After midnight those words point at the
    # wrong day, so anything unsent by 23:59 IST on the run date must be dropped.
    return datetime.combine(run_date, time(23, 59), IST).isoformat()


def _envelope(channel: str, run_id: str, run_date: date, msg: ComposedMessage,
              content: dict) -> dict:
    digest = hashlib.sha256(
        json.dumps([run_date.isoformat(), msg.location_id, channel, content],
                   ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()[:16]
    return {
        "message_id": digest,
        "run_id": run_id,
        "channel": channel,
        "location_id": msg.location_id,
        "language": msg.language,
        "advisory_codes": [a.code for a in msg.advisories],
        "rule_ids": [a.rule_id for a in msg.advisories],
        "expires_at": expires_at(run_date),
        "content": content,
    }


class SMSAdapter:
    """Fits the message into a segment budget by dropping lowest-priority lines.

    Never truncates mid-sentence: a cut-off weather warning can change its meaning.
    """
    name = "sms"

    def __init__(self, max_segments: int = 2, substitutions: dict | None = None):
        self.max_segments = max_segments
        # e.g. the degree sign is NOT in GSM-7: one '°' silently turns an English
        # SMS into UCS-2 and cuts capacity from 160 to 70 chars per segment.
        self.substitutions = substitutions or {}

    def _clean(self, text: str) -> str:
        cleaned = text
        for a, b in self.substitutions.items():
            cleaned = cleaned.replace(a, b)
        # Only substitute when it buys GSM-7. A Hindi SMS is UCS-2 regardless,
        # so there '°C' costs nothing and reads better than ' C'.
        return cleaned if sms_encoding(cleaned)[0] == "GSM-7" else text

    def _fit(self, header: str, lines: list[str]) -> tuple[str, str, int]:
        text = self._clean(" ".join([header] + lines))
        enc, segs = sms_segments(text)
        return text, enc, segs

    def render(self, msg: ComposedMessage, run_id: str, run_date: date, **_) -> dict:
        # Degrade gracefully, in order of information lost:
        #   1. full text
        #   2. headline mode: keep only the first sentence of each advisory (the
        #      "what and when"), dropping the action advice. Every warning survives.
        #      Matters most for Hindi: UCS-2 gives only 70 chars per segment.
        #   3. drop whole advisories, lowest priority first.
        lines, mode, dropped = list(msg.lines), "full", 0
        text, enc, segs = self._fit(msg.header, lines)
        if segs > self.max_segments:
            lines, mode = [headline(l) for l in lines], "headline"
            text, enc, segs = self._fit(msg.header, lines)
        while segs > self.max_segments and len(lines) > 1:
            lines.pop()          # lines are priority-ordered: drop the least important
            dropped += 1
            text, enc, segs = self._fit(msg.header, lines)
        content = {"text": text, "encoding": enc, "segments": segs, "mode": mode,
                   "dropped_advisories": dropped,
                   "over_budget": segs > self.max_segments}
        return _envelope(self.name, run_id, run_date, msg, content)


class WhatsAppAdapter:
    """WhatsApp Business requires pre-approved templates for outbound messages;
    the advisory body is passed as a template parameter."""
    name = "whatsapp"

    def __init__(self, template_name: str = "weather_advisory_v1"):
        self.template_name = template_name

    def render(self, msg: ComposedMessage, run_id: str, run_date: date, **_) -> dict:
        body = "\n".join(f"• {l}" for l in msg.lines)
        content = {"type": "template", "template_name": self.template_name,
                   "language": msg.language,
                   "params": {"header": msg.header, "body": body}}
        return _envelope(self.name, run_id, run_date, msg, content)


class VoiceAdapter:
    """Script for an IVR / outbound-call text-to-speech vendor."""
    name = "voice"
    WORDS_PER_SECOND = 2.2   # typical TTS pace; used to flag scripts that run long

    def __init__(self, repeat_top: bool = True):
        self.repeat_top = repeat_top

    def render(self, msg: ComposedMessage, run_id: str, run_date: date, **_) -> dict:
        parts = [msg.header] + msg.lines
        # Listeners can't re-read a call: repeating the most important line is
        # standard IVR practice.
        if self.repeat_top and msg.advisories:
            parts.append(msg.lines[0])
        script = " ... ".join(parts)
        content = {"tts_text": script, "tts_language": msg.language,
                   "est_duration_s": round(len(script.split()) / self.WORDS_PER_SECOND)}
        return _envelope(self.name, run_id, run_date, msg, content)


class LLMContextAdapter:
    """Structured, citable context for an LLM-powered advisory assistant.

    Instead of free text, the assistant receives the numbers, the advisories and
    the rule that produced each one, so its answers can be grounded and audited.
    """
    name = "llm"

    def render(self, msg: ComposedMessage, run_id: str, run_date: date,
               location: Location | None = None, forecast: list[DailyForecast] | None = None,
               source: str = "", **_) -> dict:
        content = {
            "location": {"id": msg.location_id, "name": location.name if location else None,
                         "lat": location.lat if location else None,
                         "lon": location.lon if location else None},
            "issued_for": run_date.isoformat(),
            "forecast_source": source,
            "units": {"temp": "degC", "precip": "mm/day", "prob": "%", "wind": "km/h"},
            "forecast": [f.to_dict() for f in (forecast or [])],
            "advisories": [{"code": a.code, "severity": a.severity, "rule_id": a.rule_id,
                            "date": a.date.isoformat() if a.date else None,
                            "values": a.params, "approved_text": line}
                           for a, line in zip(msg.advisories, msg.lines)],
            "grounding_instructions": (
                "Answer farmer questions using only the forecast and advisories above. "
                "Prefer the approved_text wording for advisories. If asked about dates "
                "or places not covered, say the forecast does not cover them."),
        }
        return _envelope(self.name, run_id, run_date, msg, content)


ADAPTERS = {c.name: c for c in (SMSAdapter, WhatsAppAdapter, VoiceAdapter, LLMContextAdapter)}


def build_adapters(channels_cfg: dict) -> list:
    adapters = []
    for name, opts in channels_cfg.items():
        opts = dict(opts or {})
        if not opts.pop("enabled", True):
            continue
        if name not in ADAPTERS:
            raise ValueError(f"unknown channel '{name}'. available: {sorted(ADAPTERS)}")
        adapters.append(ADAPTERS[name](**opts))
    return adapters
