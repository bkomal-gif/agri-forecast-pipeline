from conftest import RUN_DATE, make_days
from pipeline.channels import (LLMContextAdapter, SMSAdapter, VoiceAdapter, expires_at,
                               headline, sms_encoding, sms_segments)
from pipeline.messages import compose
from pipeline.rules import evaluate


def test_gsm7_vs_ucs2_detection():
    assert sms_encoding("Heavy rain tomorrow")[0] == "GSM-7"
    assert sms_encoding("कल भारी बारिश")[0] == "UCS-2"
    # The degree sign is not in GSM-7: it alone flips the whole SMS to UCS-2.
    assert sms_encoding("max 45°C")[0] == "UCS-2"
    assert sms_encoding("price [x]")[1] == len("price [x]") + 2   # extension chars cost 2


def test_segment_boundaries():
    assert sms_segments("a" * 160) == ("GSM-7", 1)
    assert sms_segments("a" * 161) == ("GSM-7", 2)
    assert sms_segments("क" * 70) == ("UCS-2", 1)
    assert sms_segments("क" * 71) == ("UCS-2", 2)


def _msg(loc, templates, rules_cfg, lang=None):
    days = make_days(d0={"tmax_c": 46.0, "wind_max_kmh": 45.0},
                     d1={"precip_mm": 80.0, "precip_prob_pct": 90})
    advs = evaluate(days, RUN_DATE, rules_cfg)
    return compose(loc, advs, RUN_DATE, templates, language=lang), days


def test_sms_headline_mode_keeps_every_warning(loc, templates, rules_cfg):
    # Regression: a tight Hindi budget used to drop "heavy rain tomorrow".
    days = make_days(d1={"precip_mm": 78.0}, d2={"precip_mm": 132.0})
    advs = evaluate(days, RUN_DATE, rules_cfg)
    msg = compose(loc, advs, RUN_DATE, templates, language="hi")
    c = SMSAdapter(max_segments=3).render(msg, "r", RUN_DATE)["content"]
    assert c["mode"] == "headline" and c["dropped_advisories"] == 0
    assert "कल भारी बारिश" in c["text"] and "परसों बहुत भारी बारिश" in c["text"]
    assert not c["over_budget"]


def test_sms_drops_lowest_priority_last_and_never_cuts_sentences(loc, templates, rules_cfg):
    msg, _ = _msg(loc, templates, rules_cfg)
    p = SMSAdapter(max_segments=1, substitutions={"°C": " C"}).render(msg, "r", RUN_DATE)
    c = p["content"]
    assert c["encoding"] == "GSM-7" and c["segments"] == 1
    assert c["text"].endswith(")") or c["text"].endswith(".")   # whole sentences only
    assert headline(msg.lines[0]).replace("°C", " C") in c["text"]   # top priority kept


def test_message_id_is_stable_for_idempotent_retries(loc, templates, rules_cfg):
    msg, _ = _msg(loc, templates, rules_cfg)
    a = SMSAdapter().render(msg, "run-1", RUN_DATE)
    b = SMSAdapter().render(msg, "run-2", RUN_DATE)
    assert a["message_id"] == b["message_id"]


def test_messages_expire_at_end_of_run_day():
    assert expires_at(RUN_DATE) == "2026-10-14T23:59:00+05:30"


def test_voice_repeats_top_advisory(loc, templates, rules_cfg):
    msg, _ = _msg(loc, templates, rules_cfg)
    script = VoiceAdapter().render(msg, "r", RUN_DATE)["content"]["tts_text"]
    assert script.count(msg.lines[0]) == 2


def test_llm_context_is_traceable(loc, templates, rules_cfg):
    msg, days = _msg(loc, templates, rules_cfg)
    c = LLMContextAdapter().render(msg, "r", RUN_DATE, location=loc, forecast=days,
                                   source="synthetic")["content"]
    assert len(c["forecast"]) == 7
    assert all(a["rule_id"] and a["approved_text"] for a in c["advisories"])


def test_missing_language_falls_back_to_english_with_warning(loc, templates, rules_cfg):
    msg, _ = _msg(loc, templates, rules_cfg, lang="mr")
    assert msg.language == "en" and msg.warnings


def test_degree_substitution_only_when_it_keeps_gsm7(loc, templates, rules_cfg):
    sms = SMSAdapter(max_segments=3, substitutions={"°C": " C"})
    hi, _ = _msg(loc, templates, rules_cfg, lang="hi")
    en, _ = _msg(loc, templates, rules_cfg, lang="en")
    assert "°C" in sms.render(hi, "r", RUN_DATE)["content"]["text"]
    en_c = sms.render(en, "r", RUN_DATE)["content"]
    assert "°" not in en_c["text"] and en_c["encoding"] == "GSM-7"
