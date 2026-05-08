from __future__ import annotations

from agent.plan_quality import score_plan_quality


def test_plan_quality_scores_strong_plan_higher_than_weak_plan() -> None:
    strong = {
        "goal": "Build CLI app",
        "steps": [
            {
                "id": "S1",
                "title": "Write failing tests",
                "details": "Create pytest cases for CLI arguments and error paths under tests/.",
                "success_check": "pytest runs and at least one test fails first.",
            },
            {
                "id": "S2",
                "title": "Implement minimal code",
                "details": "Implement argument parsing and command handlers inside src/ modules only.",
                "success_check": "All targeted pytest tests pass with exit code 0.",
            },
            {
                "id": "S3",
                "title": "Safety and regression pass",
                "details": "Run verification and confirm boundary-safe writes, limits, and rollback notes.",
                "success_check": "pytest -q returns 0 and safety checks stay within workspace boundary.",
            },
        ],
        "success_criteria": [
            "All pytest commands exit code 0.",
            "No path traversal or boundary violations occur.",
            "CLI behavior matches tests for help and invalid argument handling.",
        ],
    }
    weak = {
        "goal": "Build CLI app",
        "steps": [
            {
                "id": "S1",
                "title": "Plan",
                "details": "Do work.",
                "success_check": "Done.",
            }
        ],
        "success_criteria": ["looks good"],
    }

    strong_score = score_plan_quality(strong, tdd_mode=True)
    weak_score = score_plan_quality(weak, tdd_mode=True)

    assert int(strong_score["score"]) > int(weak_score["score"])
    assert int(strong_score["subscores"]["clarity"]) >= int(weak_score["subscores"]["clarity"])
    assert int(strong_score["subscores"]["testability"]) >= int(weak_score["subscores"]["testability"])


def test_plan_quality_tdd_mode_penalizes_missing_tests_first_signal() -> None:
    plan = {
        "goal": "Refactor module",
        "steps": [
            {
                "id": "S1",
                "title": "Implement refactor",
                "details": "Rewrite module internals and update interfaces.",
                "success_check": "Output looks correct.",
            },
            {
                "id": "S2",
                "title": "Run checks",
                "details": "Run validation after implementation.",
                "success_check": "pytest returns 0.",
            },
            {
                "id": "S3",
                "title": "Finalize",
                "details": "Document changes and risks.",
                "success_check": "docs updated.",
            },
        ],
        "success_criteria": ["pytest exits with code 0"],
    }

    normal = score_plan_quality(plan, tdd_mode=False)
    tdd = score_plan_quality(plan, tdd_mode=True)

    assert int(tdd["score"]) <= int(normal["score"])
    assert tdd["signals"]["tdd_mode"] is True
    assert tdd["signals"]["tdd_tests_first"] is False

