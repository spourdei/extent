"""Print or verify the frozen publication evaluation report."""

from __future__ import annotations

import sys
from pathlib import Path

from extent_api.evaluation import (
    FrozenEvaluationReport,
    load_frozen_manifest,
    run_frozen_evaluation,
)

API_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = API_ROOT / "evals" / "frozen_manifest.json"
REPORT_PATH = API_ROOT / "evals" / "frozen_report.json"


def main() -> None:
    arguments = sys.argv[1:]
    if arguments not in ([], ["--check"]):
        raise SystemExit("Usage: run_frozen_eval.py [--check]")
    report = run_frozen_evaluation(load_frozen_manifest(MANIFEST_PATH))
    serialized = report.model_dump_json(indent=2) + "\n"
    if arguments == ["--check"]:
        stored = FrozenEvaluationReport.model_validate_json(
            REPORT_PATH.read_text(encoding="utf-8")
        )
        if stored != report:
            raise SystemExit(
                "Frozen evaluation report is stale; print and review a new report."
            )
        if report.failed_cases:
            raise SystemExit(f"Frozen evaluation failed: {report.failed_case_ids!r}")
        return
    sys.stdout.write(serialized)


if __name__ == "__main__":
    main()
