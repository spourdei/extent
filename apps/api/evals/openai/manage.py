"""Set up, validate, and run the isolated OpenAI Evals harness."""

from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import NoReturn

from extent_openai_evals.contracts import (
    CasebookError,
    SourceCorpusError,
    load_casebook,
    load_source_corpus,
)

OPENAI_EVAL_ROOT = Path(__file__).resolve().parent
REPOSITORY_ROOT = OPENAI_EVAL_ROOT.parents[3]
REGISTRY_ROOT = OPENAI_EVAL_ROOT / "registry"
DEFAULT_CASEBOOK = REGISTRY_ROOT / "data" / "extent_evidence_answering" / "samples.jsonl"
VIRTUAL_ENV = OPENAI_EVAL_ROOT / ".venv"
REQUIRED_FIXTURES = {
    "activity_log.csv",
    "controlled_summary.md",
    "external_note.md",
    "work_items.csv",
}
REPORT_METRICS = (
    "pass_rate",
    "answer_accuracy",
    "citation_integrity",
    "uncertainty_handling",
    "policy_compliance",
)
SAFE_RUNTIME_ENVIRONMENT = frozenset(
    {
        "LANG",
        "LC_ALL",
        "PATH",
        "SSL_CERT_DIR",
        "SSL_CERT_FILE",
        "SYSTEMROOT",
        "TEMP",
        "TMP",
        "TMPDIR",
        "TZ",
        "WINDIR",
    }
)
PASSTHROUGH_EVAL_ENVIRONMENT = frozenset(
    {
        "EXTENT_EVAL_API_BASE_URL",
        "EXTENT_EVAL_ORIGIN",
        "EXTENT_EVAL_SESSION_COOKIE_NAME",
        "EXTENT_EVAL_SESSION_COOKIE_VALUE",
        "EXTENT_EVAL_SOURCE_ROOT",
        "EXTENT_EVAL_TIMEOUT_SECONDS",
        "EXTENT_EVAL_WORKSPACE_ID",
    }
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("run", "setup", "validate"))
    parser.add_argument("--max-samples", type=_positive_integer)
    parser.add_argument(
        "--min-score",
        type=_unit_interval,
        default=1.0,
        help="minimum required value for every reported metric (default: 1.0)",
    )
    parser.add_argument("--record-path", type=Path)
    arguments = parser.parse_args()

    if arguments.command == "setup":
        _setup()
        return
    casebook = _casebook_path()
    cases = _validate(casebook)
    if arguments.command == "validate":
        print(f"Validated {len(cases)} OpenAI Evals cases in {casebook}.")
        return
    _run(
        casebook=casebook,
        max_samples=arguments.max_samples,
        min_score=arguments.min_score,
        record_path=arguments.record_path,
    )


def _setup() -> None:
    executable = os.environ.get("EXTENT_EVAL_PYTHON", sys.executable)
    version = _python_version(executable)
    if version[:2] != (3, 12):
        _exit(
            "The isolated OpenAI Evals environment is standardized on Python 3.12. "
            "Set EXTENT_EVAL_PYTHON to a Python 3.12 executable."
        )
    if VIRTUAL_ENV.exists() and _python_version(str(_venv_python()))[:2] != (3, 12):
        _exit(f"Existing eval environment is not Python 3.12: {VIRTUAL_ENV}")
    if not VIRTUAL_ENV.exists():
        subprocess.run([executable, "-m", "venv", str(VIRTUAL_ENV)], check=True)
    subprocess.run(
        [
            str(_venv_python()),
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "-r",
            str(OPENAI_EVAL_ROOT / "requirements.txt"),
        ],
        check=True,
    )
    print(f"Installed the isolated OpenAI Evals harness in {VIRTUAL_ENV}.")


def _validate(casebook: Path) -> list[dict[str, object]]:
    try:
        cases = load_casebook(casebook)
    except CasebookError as error:
        _exit(str(error))
    if casebook == DEFAULT_CASEBOOK:
        source_root = OPENAI_EVAL_ROOT / "golden_workspace"
        fixture_names = {path.name for path in source_root.iterdir() if path.is_file()}
        if fixture_names != REQUIRED_FIXTURES:
            _exit("The golden workspace must contain exactly its four declared source files.")
        try:
            corpus = load_source_corpus(source_root)
        except SourceCorpusError as error:
            _exit(str(error))
        for case in cases:
            ideal = case["ideal"]
            if not isinstance(ideal, dict):
                _exit("Validated eval ideal unexpectedly changed type.")
            required_sources = set(ideal.get("required_sources", []))
            if not required_sources <= set(corpus):
                _exit(f"Eval case {case['case_id']} names an unknown required source.")
            candidate_sources = required_sources or set(corpus)
            source_text = "\n".join(
                block.text for name in candidate_sources for block in corpus[name]
            ).casefold()
            if any(
                fragment.casefold() not in source_text
                for fragment in ideal.get("citation_quote_includes", [])
            ):
                _exit(
                    f"Eval case {case['case_id']} expects a citation fragment "
                    "that is absent from its required sources."
                )
    return cases


def _run(
    *,
    casebook: Path,
    max_samples: int | None,
    min_score: float,
    record_path: Path | None,
) -> None:
    missing = [
        name
        for name in (
            "EXTENT_EVAL_SESSION_COOKIE_VALUE",
            "EXTENT_EVAL_WORKSPACE_ID",
        )
        if not os.environ.get(name, "").strip()
    ]
    if missing:
        _exit(f"Missing live eval environment: {', '.join(missing)}")
    python = _venv_python()
    if not python.is_file():
        _exit("OpenAI Evals is not installed. Run `pnpm eval:openai:setup` first.")

    destination = record_path or _default_record_path()
    if not destination.is_absolute():
        destination = REPOSITORY_ROOT / destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    environment = {
        name: value
        for name, value in os.environ.items()
        if name in SAFE_RUNTIME_ENVIRONMENT or name in PASSTHROUGH_EVAL_ENVIRONMENT
    }
    environment.update(
        {
            "EVALS_SEQUENTIAL": "1",
            "EVALS_SHOW_EVAL_PROGRESS": "",
            "EVALS_THREADS": "1",
            "OPENAI_API_KEY": "unused-by-extent-private-completion",
            "EXTENT_EVAL_CASES_PATH": str(casebook),
            "PYTHONPATH": _python_path(None),
        }
    )
    if casebook == DEFAULT_CASEBOOK:
        environment["EXTENT_EVAL_SOURCE_ROOT"] = str(OPENAI_EVAL_ROOT / "golden_workspace")
    command = [
        str(python),
        str(OPENAI_EVAL_ROOT / "launch_oaieval.py"),
        "extent/http",
        "extent-evidence-answering",
        "--registry_path",
        str(REGISTRY_ROOT),
        "--record_path",
        str(destination),
        "--no-cache",
    ]
    if max_samples is not None:
        command.extend(("--max_samples", str(max_samples)))
    subprocess.run(command, cwd=REPOSITORY_ROOT, env=environment, check=True)
    report = _read_final_report(destination)
    rendered = ", ".join(f"{metric}={report[metric]:.3f}" for metric in REPORT_METRICS)
    print(f"OpenAI Evals final report: {rendered}")
    print(f"OpenAI Evals record written to {destination}.")
    below_threshold = [metric for metric in REPORT_METRICS if report[metric] < min_score]
    if below_threshold:
        _exit(
            f"OpenAI Evals gate failed: {', '.join(below_threshold)} below "
            f"the required {min_score:.3f}."
        )


def _read_final_report(path: Path) -> dict[str, float]:
    reports: list[object] = []
    try:
        with path.open(encoding="utf-8") as stream:
            for line_number, raw_line in enumerate(stream, 1):
                if not raw_line.strip():
                    continue
                try:
                    event = json.loads(raw_line)
                except json.JSONDecodeError as error:
                    _exit(
                        f"OpenAI Evals record has invalid JSON on line {line_number}.",
                        cause=error,
                    )
                if isinstance(event, dict) and "final_report" in event:
                    reports.append(event["final_report"])
    except OSError as error:
        _exit(f"Unable to read OpenAI Evals record: {path}", cause=error)
    if len(reports) != 1 or not isinstance(reports[0], dict):
        _exit("OpenAI Evals record must contain exactly one final_report object.")
    report: dict[str, float] = {}
    for metric in REPORT_METRICS:
        raw_value = reports[0].get(metric)
        if (
            not isinstance(raw_value, (int, float))
            or isinstance(raw_value, bool)
            or not math.isfinite(raw_value)
            or not 0 <= raw_value <= 1
        ):
            _exit(f"OpenAI Evals final_report has an invalid {metric} metric.")
        report[metric] = float(raw_value)
    return report


def _casebook_path() -> Path:
    configured = os.environ.get("EXTENT_EVAL_CASES_PATH")
    if not configured:
        return DEFAULT_CASEBOOK
    path = Path(configured).expanduser()
    return path if path.is_absolute() else (REPOSITORY_ROOT / path).resolve()


def _default_record_path() -> Path:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return REPOSITORY_ROOT / "tmp" / "openai-evals" / f"extent-{timestamp}.jsonl"


def _python_path(existing: str | None) -> str:
    paths = [str(OPENAI_EVAL_ROOT)]
    if existing:
        paths.append(existing)
    return os.pathsep.join(paths)


def _venv_python() -> Path:
    return VIRTUAL_ENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def _python_version(executable: str) -> tuple[int, int, int]:
    try:
        result = subprocess.run(
            [
                executable,
                "-c",
                "import json,sys; print(json.dumps(list(sys.version_info[:3])))",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        value = json.loads(result.stdout)
    except (FileNotFoundError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
        _exit(f"Unable to run evaluation Python executable: {executable}", cause=error)
    if (
        not isinstance(value, list)
        or len(value) != 3
        or not all(isinstance(item, int) for item in value)
    ):
        _exit(f"Unable to read Python version from: {executable}")
    return value[0], value[1], value[2]


def _positive_integer(raw: str) -> int:
    value = int(raw)
    if value < 1:
        raise argparse.ArgumentTypeError("value must be positive")
    return value


def _unit_interval(raw: str) -> float:
    try:
        value = float(raw)
    except ValueError as error:
        raise argparse.ArgumentTypeError("value must be numeric") from error
    if not math.isfinite(value) or not 0 <= value <= 1:
        raise argparse.ArgumentTypeError("value must be between 0 and 1")
    return value


def _exit(message: str, *, cause: Exception | None = None) -> NoReturn:
    if cause is not None:
        raise SystemExit(message) from cause
    raise SystemExit(message)


if __name__ == "__main__":
    main()
