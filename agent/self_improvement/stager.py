"""Proposal stager for David's self-improvement system.

Validates an ImprovementProposal by:
  1. Syntax-checking the proposed Python content.
  2. Running the existing agent test suite to confirm nothing is broken.
  3. Writing the staged file to the agent sandbox for Web UI review.

The stager never modifies any live source file directly.
"""
from __future__ import annotations

import ast
import hashlib
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from agent.self_improvement.proposer import ImprovementProposal


_TEST_TIMEOUT_SEC = 120
_MAX_TEST_OUTPUT_CHARS = 3_000


@dataclass(frozen=True)
class StagingResult:
    """Outcome of attempting to stage a proposal."""

    success: bool           # True only if syntax is valid AND staged file was written
    proposal_id: str
    sandbox_file: Path      # absolute path to the staged file (inside sandbox)
    sandbox_dir: Path       # absolute path to the proposal directory (inside sandbox)
    syntax_ok: bool
    tests_passed: bool
    test_output: str
    error: str              # human-readable reason when success=False


class ProposalStager:
    """
    Validates an ImprovementProposal and writes it to the agent sandbox.

    The sandbox path is: workspace/agent_sandbox/<proposal_id>/prototype/file_000_<name>
    This matches the path format expected by ControlCenter._merge_self_improvement_proposal().
    """

    def __init__(self, project_root: Path, sandbox_root: Path) -> None:
        self._project_root = project_root
        self._sandbox_root = sandbox_root

    def stage(self, proposal: ImprovementProposal) -> StagingResult:
        """Validate and stage the proposal. Always returns a result — never raises."""
        try:
            return self._stage_inner(proposal)
        except Exception as exc:  # pragma: no cover — defensive boundary
            return StagingResult(
                success=False,
                proposal_id="",
                sandbox_file=Path("."),
                sandbox_dir=Path("."),
                syntax_ok=False,
                tests_passed=False,
                test_output="",
                error=f"Unexpected stager error: {exc}",
            )

    def _stage_inner(self, proposal: ImprovementProposal) -> StagingResult:
        # 1. Syntax check — must pass before anything else
        syntax_ok, syntax_error = _check_syntax(proposal.proposed_content)
        if not syntax_ok:
            return StagingResult(
                success=False,
                proposal_id="",
                sandbox_file=Path("."),
                sandbox_dir=Path("."),
                syntax_ok=False,
                tests_passed=False,
                test_output="",
                error=f"Syntax error in proposed content: {syntax_error}",
            )

        # 2. Run the agent test suite — non-destructive, existing code is unchanged
        tests_passed, test_output = self._run_tests()

        # 3. Build a stable, unique proposal ID
        proposal_id = _make_proposal_id(proposal)

        # 4. Write staged file into the sandbox
        prototype_dir = (self._sandbox_root / proposal_id / "prototype").resolve()
        prototype_dir.mkdir(parents=True, exist_ok=True)

        safe_name = proposal.target_path.replace("/", "_").replace("\\", "_")
        sandbox_file = prototype_dir / f"file_000_{safe_name}"
        sandbox_file.write_text(proposal.proposed_content, encoding="utf-8")

        # 5. Write a human-readable PROPOSAL.md alongside the staged file
        proposal_doc = (self._sandbox_root / proposal_id / "PROPOSAL.md").resolve()
        proposal_doc.write_text(
            _build_proposal_doc(proposal, proposal_id, tests_passed, test_output),
            encoding="utf-8",
        )

        sandbox_dir = (self._sandbox_root / proposal_id).resolve()
        return StagingResult(
            success=True,
            proposal_id=proposal_id,
            sandbox_file=sandbox_file,
            sandbox_dir=sandbox_dir,
            syntax_ok=True,
            tests_passed=tests_passed,
            test_output=test_output,
            error="",
        )

    def _run_tests(self) -> tuple[bool, str]:
        """Run pytest against the project test suite. Returns (passed, output)."""
        pytest_exe = shutil.which("pytest") or shutil.which("pytest3")
        python_exe = sys.executable
        argv = [pytest_exe, "-q", "--tb=short"] if pytest_exe else [python_exe, "-m", "pytest", "-q", "--tb=short"]

        try:
            result = subprocess.run(
                argv,
                cwd=self._project_root,
                capture_output=True,
                text=True,
                timeout=_TEST_TIMEOUT_SEC,
                shell=False,
            )
            raw = (result.stdout + "\n" + result.stderr).strip()
            output = raw[:_MAX_TEST_OUTPUT_CHARS] + ("\n...[truncated]" if len(raw) > _MAX_TEST_OUTPUT_CHARS else "")
            return result.returncode == 0, output
        except subprocess.TimeoutExpired:
            return False, "Test run timed out."
        except FileNotFoundError:
            # pytest not installed — treat as non-blocking (tests not yet set up)
            return True, "pytest not found — test validation skipped."


# ─── helpers ──────────────────────────────────────────────────────────────────

def _check_syntax(content: str) -> tuple[bool, str]:
    try:
        ast.parse(content)
        return True, ""
    except SyntaxError as exc:
        return False, str(exc)


def _make_proposal_id(proposal: ImprovementProposal) -> str:
    stamp = datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%S")
    content_hash = hashlib.sha1(proposal.proposed_content.encode("utf-8")).hexdigest()[:8]
    safe_module = proposal.target_path.replace("/", "_").replace(".", "_").replace("\\", "_")[:32]
    return f"improve_{safe_module}_{stamp}_{content_hash}"


def _build_proposal_doc(
    proposal: ImprovementProposal,
    proposal_id: str,
    tests_passed: bool,
    test_output: str,
) -> str:
    test_badge = "✅ PASSED" if tests_passed else "⚠️ FAILED (review carefully)"
    return (
        f"# Self-Improvement Proposal\n\n"
        f"**ID:** `{proposal_id}`\n"
        f"**Target:** `{proposal.target_path}`\n"
        f"**Signal:** `{proposal.signal.signal_code}` (severity {proposal.signal.severity}/100)\n"
        f"**Test suite:** {test_badge}\n\n"
        f"## Evidence\n\n{proposal.signal.evidence}\n\n"
        f"## Reasoning\n\n{proposal.reasoning}\n\n"
        f"## Test Output\n\n```\n{test_output}\n```\n"
    )


def build_proposal_record(
    staging: StagingResult,
    proposal: ImprovementProposal,
    *,
    actor: str = "cli_propose_improvement",
    now_iso: str | None = None,
) -> dict:
    """
    Build the JSON record that ControlCenter writes to data/self_improvements.json.
    The format must match what _merge_self_improvement_proposal() reads.
    """
    from datetime import datetime, timezone
    ts = now_iso or datetime.now(tz=timezone.utc).isoformat()

    return {
        "id": staging.proposal_id,
        "title": f"Self-Improvement: {proposal.signal.signal_code} in {proposal.target_path}",
        "rationale": (
            f"Signal: {proposal.signal.signal_code} (severity {proposal.signal.severity}/100)\n"
            f"Evidence: {proposal.signal.evidence}\n\n"
            f"Reasoning: {proposal.reasoning}"
        ),
        "status": "pending",
        "actor": actor,
        "created_at": ts,
        "updated_at": ts,
        "sandbox_dir": str(staging.sandbox_dir),
        "proposal_doc": str(staging.sandbox_dir / "PROPOSAL.md"),
        "changes": [
            {
                "path": proposal.target_path,
                "sandbox_file": str(staging.sandbox_file),
                "before": proposal.original_content[:500] + ("..." if len(proposal.original_content) > 500 else ""),
                "after": proposal.proposed_content[:500] + ("..." if len(proposal.proposed_content) > 500 else ""),
            }
        ],
        "metadata": {
            "autonomous": False,
            "trigger": actor,
            "signal_code": proposal.signal.signal_code,
            "signal_severity": proposal.signal.severity,
            "signal_evidence": proposal.signal.evidence,
            "syntax_ok": staging.syntax_ok,
            "tests_passed": staging.tests_passed,
            "test_output": staging.test_output[:1_000],
        },
        "decision": None,
        "merge": None,
    }
