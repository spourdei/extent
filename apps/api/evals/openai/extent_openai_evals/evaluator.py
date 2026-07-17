"""Deterministic OpenAI Evals grader for Extent publication results."""

from __future__ import annotations

import json
import os
from pathlib import Path
from statistics import fmean
from typing import Any

from evals.api import CompletionFn
from evals.record import RecorderBase

import evals
from evals import record
from extent_openai_evals.completion import ExtentEvalRequestError
from extent_openai_evals.contracts import (
    MetricName,
    SourceCorpusError,
    load_casebook,
    load_source_corpus,
    score_completion,
)

_DEFAULT_CASEBOOK = "extent_evidence_answering/samples.jsonl"
_METRICS: tuple[MetricName, ...] = (
    "pass_rate",
    "answer_accuracy",
    "citation_integrity",
    "uncertainty_handling",
    "policy_compliance",
)


class ExtentEvidenceEval(evals.Eval):
    """Evaluate the observable product contract without a second model judge."""

    def __init__(
        self,
        completion_fns: list[CompletionFn],
        *args: Any,
        samples_jsonl: str = _DEFAULT_CASEBOOK,
        **kwargs: Any,
    ) -> None:
        configured_casebook = os.environ.get("EXTENT_EVAL_CASES_PATH", samples_jsonl)
        super().__init__(
            completion_fns,
            *args,
            samples_jsonl=configured_casebook,
            **kwargs,
        )
        self._samples = load_casebook(self._get_samples_path())
        configured_source_root = os.environ.get("EXTENT_EVAL_SOURCE_ROOT")
        try:
            self._source_corpus = (
                load_source_corpus(Path(configured_source_root).expanduser().resolve())
                if configured_source_root
                else None
            )
        except SourceCorpusError as error:
            raise ValueError(str(error)) from error

    def get_samples(self) -> list[dict[str, Any]]:
        return self._samples

    def eval_sample(self, sample: Any, *_: object) -> None:
        if not isinstance(sample, dict):
            raise TypeError("validated Extent eval samples must be objects")
        request_error: ExtentEvalRequestError | None = None
        try:
            result = self.completion_fn(prompt=sample["input"], temperature=0.0)
            sampled = result.get_completions()[0]
            try:
                completion = json.loads(sampled)
            except json.JSONDecodeError:
                completion = {}
        except ExtentEvalRequestError as error:
            request_error = error
            completion = {}
        scores = score_completion(
            completion,
            sample["ideal"],
            source_corpus=self._source_corpus,
        )
        if request_error is not None:
            record.record_error(
                "Extent sample request failed",
                request_error,
                case_id=sample["case_id"],
            )
        record.record_match(
            scores["pass_rate"],
            expected=sample["ideal"],
            picked=completion,
            case_id=sample["case_id"],
        )
        record.record_metrics(**{key: float(value) for key, value in scores.items()})
        record.record_extra(
            {
                "case_id": sample["case_id"],
                "metrics": scores,
            }
        )

    def run(self, recorder: RecorderBase) -> dict[str, float]:
        self.eval_all_samples(recorder, self.get_samples())
        return {metric: fmean(recorder.get_scores(metric)) for metric in _METRICS}
