"""Per-request instruction blocks for the Coach quick-action request kinds.

A playbook is appended to the instructions of its own turn only; it never joins
the global prompt. A playbook never authorizes writes.

References (only author and year appear in the model text):
- Kiely 2012, IJSPP 7(3):242-250, periodization paradigms.
- Frandsen et al. 2025, BJSM 59:1203-1210, session distance relative to the
  longest run of the prior 30 days and overuse injury (observational).
- Ronnestad & Mujika 2014, Scand J Med Sci Sports 24:603-612; Blagrove et al.
  2018, Sports Med; heavy strength and endurance performance.
- Robineau et al. 2016, J Strength Cond Res, recovery between
  concurrent strength and aerobic sessions.
- Bosquet et al. 2007, Med Sci Sports Exerc, tapering meta-analysis.
- Kiviniemi et al. 2007, Eur J Appl Physiol; Javaloyes et al. 2019,
  IJSPP, HRV-guided training.
- Impellizzeri et al. 2020, IJSPP 15:907-913, acute:chronic workload ratio.
"""

from __future__ import annotations

_COMMON = """\
REQUEST PLAYBOOK (this turn only).
- Separate measured facts from inference, name the data coverage, and label evidence strength as strong, moderate, limited or practice-based. Missing data is unknown, never zero or rest.
- Never use ACWR (acute:chronic workload ratio; methodologically discredited, Impellizzeri 2020). CTL, ATL and TSB are model estimates, not individual predictions. Rule 8f on session-RPE load stays.
- The athlete's target intensity distribution is training_model in durable_profile (pyramidal, polarized, threshold or sweet_spot); use pyramidal when it is absent or unrecognized. It is the reference for plans and progress evaluation. You may note when data argues against it, but never change it."""

_PLAN_RULES = """\
Planning science:
- Use a periodized structure with progressive overload and a lighter week every 3rd to 4th week (practice-based). No single periodization model is clearly superior (Kiely 2012).
- Alternate hard and easy days; no back-to-back hard days. Distribute intensity according to training_model.
- Do not plan a single run much longer than the longest run of the last 30 days (Frandsen 2025; observational, moderate).
- Heavy strength 2 times per week improves running economy and cycling performance (Ronnestad & Mujika 2014; Blagrove 2018); 1 time per week maintains it in the competition phase. Separate it from hard endurance by at least 6 h (Robineau 2016), or place it on hard days after endurance or on easy days.
- Taper about 2 weeks before a competition: cut volume by 40-60 %, keep intensity and frequency (Bosquet 2007).
- When HRV or readiness data exist, adjust load to it (Kiviniemi 2007; Javaloyes 2019; moderate).
- Respect availability (rule 8b), illness (rule 2a), calendar events and competitions.
- Running, cycling and strength can share one plan. Create local planned units only; no Intervals.icu write."""

_TASKS = {
    "session_analysis": """\
Task: analyze the last completed session.
- Load it with get_activity_details; rules 6d and 8c-8e stay.
- Cover plan versus actual, load and intensity, pacing, HR drift and decoupling when available, and notable findings.
- End with the consequence for the next session.""",
    "progress_review": """\
Task: review progress over the requested period.
- Use get_training_report over the period. days is 7 or 28 per call; for longer periods make consecutive 28-day calls with start dates.
- Report weekly volume and load per sport (run, ride, strength), the intensity distribution against training_model, consistency, and performance indicators with source labels.
- State the data coverage per week; incomplete weeks are unknown.""",
    "plan_week": """\
Task: plan the requested next week.
- Rule 5a format stays, plus at most one line on the week's intensity logic.""",
    "plan_block": """\
Task: plan the requested multi-week block.
- Before the table give a short week-by-week rationale (focus, load trend, lighter week). This relaxes rule 5a for this turn only; the table format stays.""",
}

REQUEST_KINDS = frozenset(_TASKS)


def playbook_for(request_kind: str | None) -> str:
    """Return the instruction block for a request kind, or an empty string."""
    task = _TASKS.get(request_kind or "")
    if task is None:
        return ""
    parts = [_COMMON, task]
    if request_kind in {"plan_week", "plan_block"}:
        parts.append(_PLAN_RULES)
    return "\n\n" + "\n".join(parts) + "\n"
