from __future__ import annotations

from typing import Any


_OBJECTIVE_MARKERS = (
    "pytest",
    "test",
    "assert",
    "returncode",
    "exit code",
    "status code",
    "validate",
    "verification",
    "verify",
    "pass",
    "fail",
    "output",
)

_RISK_CATEGORY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "safety": ("safety", "safe", "guard", "risk", "validate", "validation"),
    "boundaries": ("boundary", "boundaries", "path", "workspace", "scope", "allow-list", "allowlist"),
    "rollback": ("rollback", "revert", "recover", "fallback", "preview", "approval"),
    "limits": ("timeout", "limit", "limits", "max", "size", "bytes"),
    "testing_gate": ("test", "pytest", "assert", "pass", "fail", "green", "red"),
}


def score_plan_quality(plan: dict[str, Any], *, tdd_mode: bool = False) -> dict[str, Any]:
    """Return deterministic quality scoring for a plan payload."""

    payload = plan if isinstance(plan, dict) else {}
    steps_raw = payload.get("steps")
    criteria_raw = payload.get("success_criteria")
    steps = [item for item in steps_raw if isinstance(item, dict)] if isinstance(steps_raw, list) else []
    criteria = [str(item).strip() for item in criteria_raw if str(item).strip()] if isinstance(criteria_raw, list) else []

    step_count = len(steps)
    criteria_count = len(criteria)

    titles = [str(item.get("title", "")).strip() for item in steps]
    details = [str(item.get("details", "")).strip() for item in steps]
    checks = [str(item.get("success_check", "")).strip() for item in steps]
    ids = [str(item.get("id", "")).strip() for item in steps]

    clarity = _score_clarity(step_count=step_count, ids=ids, titles=titles, details=details, checks=checks)
    testability = _score_testability(criteria=criteria, checks=checks, details=details)
    risk_coverage = _score_risk_coverage(criteria=criteria, details=details, checks=checks, tdd_mode=tdd_mode)

    score = int(round((clarity * 0.4) + (testability * 0.35) + (risk_coverage * 0.25)))
    score = max(0, min(100, score))

    objective_criteria = sum(1 for item in criteria if _contains_any(item, _OBJECTIVE_MARKERS))
    risk_category_hits = _risk_category_hits(criteria=criteria, details=details, checks=checks)
    first_step_tests_first = bool(steps and _contains_any(f"{titles[0]} {details[0]} {checks[0]}", ("test", "pytest")))

    recommendations: list[str] = []
    if step_count < 3:
        recommendations.append("Add more explicit steps (target 3-7) with ordered implementation phases.")
    if objective_criteria == 0:
        recommendations.append("Add objective success criteria (tests, exit codes, or explicit verification signals).")
    if risk_category_hits < 2:
        recommendations.append("Add explicit risk/safety controls (boundaries, limits, rollback/approval checks).")
    if tdd_mode and not first_step_tests_first:
        recommendations.append("In TDD mode, make the first step explicitly tests-first.")

    summary = (
        f"Plan quality score {score}/100 "
        f"(clarity={clarity}, testability={testability}, risk_coverage={risk_coverage})."
    )

    return {
        "score": score,
        "subscores": {
            "clarity": clarity,
            "testability": testability,
            "risk_coverage": risk_coverage,
        },
        "signals": {
            "step_count": step_count,
            "criteria_count": criteria_count,
            "step_count_ok": 3 <= step_count <= 7,
            "objective_criteria_count": objective_criteria,
            "has_objective_criteria": objective_criteria > 0,
            "risk_category_hits": risk_category_hits,
            "tdd_mode": bool(tdd_mode),
            "tdd_tests_first": (first_step_tests_first if tdd_mode else None),
        },
        "recommendations": recommendations[:6],
        "summary": summary,
    }


def build_plan_quality_replan_context(
    memory_context: str,
    plan_quality: dict[str, Any],
    *,
    threshold: int,
    tdd_mode: bool = False,
    attempt: int = 1,
    max_attempts: int = 2,
) -> str:
    """Append deterministic feedback so planner can self-correct once."""

    base = str(memory_context or "").strip() or "No prior lessons available."
    payload = plan_quality if isinstance(plan_quality, dict) else {}
    try:
        score = int(payload.get("score", 0))
    except (TypeError, ValueError):
        score = 0

    summary = str(payload.get("summary", "")).strip()
    recommendations_raw = payload.get("recommendations")
    recommendations = (
        [str(item).strip() for item in recommendations_raw if str(item).strip()]
        if isinstance(recommendations_raw, list)
        else []
    )

    lines = [
        base,
        "",
        "Planner self-correction request:",
        (
            f"- Previous plan quality score: {score}/100 (threshold {int(max(0, min(100, threshold)))})"
            f" on attempt {max(1, int(attempt))}/{max(1, int(max_attempts))}."
        ),
        "- Rebuild the plan before coding.",
        "- Keep 3-7 ordered steps with explicit file-level intent and measurable success checks.",
        "- Include concrete verification signals (pytest, exit codes, pass/fail conditions).",
        "- Include explicit safety/risk coverage (workspace boundaries, limits, rollback or approval safeguards).",
    ]
    if tdd_mode:
        lines.append("- TDD mode is on: the first step must be tests-first.")
    if summary:
        lines.append(f"- Prior summary: {summary}")
    if recommendations:
        lines.append("- Address these recommendations:")
        for item in recommendations[:6]:
            lines.append(f"  * {item}")

    return "\n".join(lines).strip()


def _score_clarity(
    *,
    step_count: int,
    ids: list[str],
    titles: list[str],
    details: list[str],
    checks: list[str],
) -> int:
    if step_count <= 0:
        return 0

    if 3 <= step_count <= 7:
        structure_points = 40
    elif step_count == 2:
        structure_points = 24
    else:
        structure_points = 10

    complete_rows = 0
    for idx in range(step_count):
        if (
            len(titles[idx]) >= 4
            and len(details[idx]) >= 18
            and len(checks[idx]) >= 10
            and bool(ids[idx])
        ):
            complete_rows += 1
    completeness_points = int(round((complete_rows / step_count) * 40))

    unique_ids = len({item.casefold() for item in ids if item})
    unique_titles = len({item.casefold() for item in titles if item})
    uniqueness_ratio = ((unique_ids / step_count) + (unique_titles / step_count)) / 2.0
    uniqueness_points = int(round(20 * uniqueness_ratio))

    return max(0, min(100, structure_points + completeness_points + uniqueness_points))


def _score_testability(*, criteria: list[str], checks: list[str], details: list[str]) -> int:
    criteria_points = int(round(min(len(criteria), 3) / 3 * 30))

    objective_criteria_hits = sum(1 for item in criteria if _contains_any(item, _OBJECTIVE_MARKERS))
    if criteria:
        objective_criteria_points = int(round((objective_criteria_hits / len(criteria)) * 35))
    else:
        objective_criteria_points = 0

    objective_checks_hits = sum(1 for item in checks if _contains_any(item, _OBJECTIVE_MARKERS))
    if checks:
        objective_checks_points = int(round((objective_checks_hits / len(checks)) * 25))
    else:
        objective_checks_points = 0

    has_validation_action = any(_contains_any(f"{detail} {check}", _OBJECTIVE_MARKERS) for detail, check in zip(details, checks))
    validation_points = 10 if has_validation_action else 0

    return max(
        0,
        min(100, criteria_points + objective_criteria_points + objective_checks_points + validation_points),
    )


def _score_risk_coverage(
    *,
    criteria: list[str],
    details: list[str],
    checks: list[str],
    tdd_mode: bool,
) -> int:
    category_hits = _risk_category_hits(criteria=criteria, details=details, checks=checks)
    base = int(round((category_hits / max(1, len(_RISK_CATEGORY_KEYWORDS))) * 90))

    if tdd_mode:
        first_line = f"{details[0]} {checks[0]}" if details and checks else ""
        tests_first = _contains_any(first_line, ("test", "pytest"))
        if tests_first:
            base += 10
        else:
            base -= 15

    return max(0, min(100, base))


def _risk_category_hits(*, criteria: list[str], details: list[str], checks: list[str]) -> int:
    text = " ".join([*criteria, *details, *checks])
    hits = 0
    for keywords in _RISK_CATEGORY_KEYWORDS.values():
        if _contains_any(text, keywords):
            hits += 1
    return hits


def _contains_any(text: str, markers: tuple[str, ...]) -> bool:
    lowered = str(text or "").casefold()
    if not lowered:
        return False
    return any(marker in lowered for marker in markers)
