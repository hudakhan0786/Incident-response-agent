"""
Drafts a postmortem straight from an incident's own timeline and root
causes - no external API call, so it works offline and produces the same
output twice in a row (useful for a live demo where you don't want an LLM
call to time out or hallucinate in front of judges).

It is intentionally a *draft*: real postmortems need a human's judgment
about blast radius, customer impact and blame-free framing. This function's
job is to save the first twenty minutes of staring at a blank page by
turning structured incident data into readable prose.
"""
from __future__ import annotations

from app import models

CATEGORY_PHRASING = {
    "deploy": "a recent deployment introduced the regression",
    "config": "a configuration change had an unintended side effect",
    "capacity": "the system ran out of headroom under load",
    "dependency": "a downstream dependency degraded or became unavailable",
    "human-error": "a manual operational step went wrong",
    "hardware": "underlying infrastructure or hardware failed",
    "unknown": "the exact trigger was not conclusively identified",
}


def _duration_phrase(mttr_minutes: int | None) -> str:
    if not mttr_minutes:
        return "an as-yet-unrecorded duration"
    if mttr_minutes < 60:
        return f"{mttr_minutes} minute" + ("" if mttr_minutes == 1 else "s")
    hours = mttr_minutes / 60
    return f"{hours:.1f} hours"


def generate_postmortem(incident: "models.Incident") -> dict:
    severity = getattr(incident.severity, "value", incident.severity)
    duration = _duration_phrase(incident.mttr_minutes)

    # --- summary ---
    summary_lines = [
        f"{incident.title} affected {incident.service} at {severity} severity "
        f"and was open for {duration}."
    ]
    if incident.error_signature:
        summary_lines.append(
            f"The incident was first identified by the signature `{incident.error_signature}`."
        )
    summary = " ".join(summary_lines)

    # --- contributing factors, from root causes ---
    if incident.root_causes:
        factor_sentences = []
        for rc in incident.root_causes:
            phrasing = CATEGORY_PHRASING.get(rc.category, CATEGORY_PHRASING["unknown"])
            detail = f" ({rc.summary})" if rc.summary else ""
            factor_sentences.append(f"In the {rc.category} category, {phrasing}{detail}.")
        contributing_factors = " ".join(factor_sentences)
    else:
        contributing_factors = (
            "No root cause was recorded for this incident yet - add one so future "
            "lookalikes can be matched with more confidence."
        )

    # --- lessons learned, from the step timeline ---
    steps = sorted(incident.steps, key=lambda s: s.minute_offset)
    if steps:
        detection_steps = [s for s in steps if s.step_type == "detection"]
        fix_steps = [s for s in steps if s.step_type in ("fix", "mitigation", "resolution")]
        lessons = []
        if detection_steps:
            lessons.append(
                f"Detection happened at T+{detection_steps[0].minute_offset} min via "
                f"{detection_steps[0].actor} - review whether earlier signals were available."
            )
        if fix_steps:
            first_fix = fix_steps[0]
            time_to_fix = first_fix.minute_offset
            lessons.append(
                f"The first mitigating action landed at T+{time_to_fix} min "
                f"({first_fix.action_text[:80]}). Consider whether this step could be "
                "automated or triggered earlier next time."
            )
        if len(steps) >= 4:
            lessons.append(
                f"{len(steps)} discrete response steps were logged - a healthy sign of "
                "documentation, but also worth checking whether any were redundant."
            )
        lessons_learned = " ".join(lessons) if lessons else (
            "Timeline was recorded but is too sparse to extract lessons automatically."
        )
    else:
        lessons_learned = (
            "No timeline steps were recorded. Logging steps as they happen (even roughly) "
            "makes future incidents in this fingerprint easier to resolve quickly."
        )

    # --- action items ---
    action_items = []
    if incident.root_causes:
        for rc in incident.root_causes:
            if rc.category == "deploy":
                action_items.append("Add a canary or staged rollout gate for this deploy path.")
            elif rc.category == "capacity":
                action_items.append("Raise or auto-scale the relevant capacity limit.")
            elif rc.category == "dependency":
                action_items.append("Add a circuit breaker / fallback for the failing dependency.")
            elif rc.category == "config":
                action_items.append("Add validation or review gating for this configuration surface.")
            elif rc.category == "human-error":
                action_items.append("Turn the manual step that failed into a checked, scripted one.")
    if not action_items:
        action_items = ["Confirm and record a root cause so this incident strengthens future matching."]
    action_items.append(f"Link or write a runbook for `{incident.error_signature or incident.service}` if one doesn't exist yet.")

    return {
        "summary": summary,
        "contributing_factors": contributing_factors,
        "action_items": action_items,
        "lessons_learned": lessons_learned,
        "auto_generated": True,
    }
