# Extent system evals with OpenAI Evals

This optional harness uses the official
[`openai/evals`](https://github.com/openai/evals) framework to evaluate Extent as a system.
Its custom `CompletionFn` sends each sample to the authenticated
`POST /api/v1/workspaces/{workspace_id}/messages` endpoint—the same backend boundary used by the
frontend—and returns a stable projection of the published result.

The grader is deterministic. It measures:

- answer accuracy against explicit golden expectations;
- citation presence, source coverage, exact-quote spans, locator shape, and—in the checked-in
  corpus—independent quote/line verification against the local source files;
- visible abstention or uncertainty when support is unavailable;
- conformance to the publication policy selected by Extent;
- an all-dimensions pass rate.

This harness does not call a separate judge model. The running application keeps its configured
provider split: semantic embeddings, answer generation, deterministic parsing and analysis, and
the publication verifier all execute inside Extent exactly as configured. OpenAI Evals only
orchestrates samples, records observations, and calculates metrics.

## Why it is separate

`evals==3.0.1.post1` has a large dependency graph. It is pinned in `requirements.txt` and
installed into `apps/api/evals/openai/.venv`; it is intentionally absent from the API's production
lock and the default `pnpm check`. The existing `pnpm eval:check` remains the fast, credential-free
publication-policy regression gate. This system suite is opt-in because it uses a live workspace
and can make paid provider requests.

Use Python 3.12 for the isolated environment, matching the repository's CI baseline:

```bash
EXTENT_EVAL_PYTHON=python3.12 pnpm eval:openai:setup
```

If `python3` already resolves to Python 3.12, `pnpm eval:openai:setup` is sufficient.

## Prepare the golden workspace

1. Upload only the four files inside `golden_workspace/` to one Google Drive folder. Keep the
   filenames unchanged.
2. Connect that folder through Extent and wait until all four sources are ready.
3. Keep the API and worker running with the desired live provider configuration.

The corpus is fictional and generic, and is designed to exercise schema-neutral routing and
execution. It covers controlled versus superseded narrative evidence, exact aggregation,
filtering, grouping, a universal check, key reconciliation, exhaustive extraction, a no-support
abstention, and trusted connector state. It deliberately contains no user documents or private
source material.

## Configure the live run

Set non-secret connection values in the shell:

```bash
export EXTENT_EVAL_API_BASE_URL=http://127.0.0.1:8000
export EXTENT_EVAL_ORIGIN=http://localhost:3000
export EXTENT_EVAL_WORKSPACE_ID=replace-with-the-ready-workspace-uuid
```

Read the `HttpOnly` Extent session cookie value from the browser developer tools' cookie
inspector, then enter it without putting it in shell history:

```bash
printf "Extent session cookie: "
read -r -s EXTENT_EVAL_SESSION_COOKIE_VALUE
printf "\n"
export EXTENT_EVAL_SESSION_COOKIE_VALUE
```

The default cookie name is `extent_session`. Override
`EXTENT_EVAL_SESSION_COOKIE_NAME` only if the running API uses another configured name. Never
put the cookie in a JSONL case, YAML registry, command argument, screenshot, or committed file.
Before attaching the cookie, the adapter requires HTTPS except for loopback and refuses redirects.
The isolated runner receives an environment allowlist, so model, embedding, Google, database, and
queue credentials remain in the already-running application processes rather than entering the
third-party evaluation environment.
The adapter's 750-second request timeout covers the bounded embedding, generation-retry, and
authority-recovery path. Override `EXTENT_EVAL_TIMEOUT_SECONDS` only when the running API has a
different provider-timeout envelope.

Validate the checked-in casebook without making a request:

```bash
pnpm eval:openai:validate
```

This credential-free validation also checks that required sources and expected quote fragments
still exist in the four normalized golden files, and it runs as part of `pnpm check`.

Run the complete suite serially:

```bash
pnpm eval:openai
```

The wrapper requires every final metric to equal `1.0` by default and exits nonzero otherwise;
the JSONL record is retained for diagnosis. For an explicitly exploratory run, lower the gate for
every metric with `--min-score`, for example:

```bash
python3 apps/api/evals/openai/manage.py run --min-score 0.8
```

For a one-sample transport smoke:

```bash
python3 apps/api/evals/openai/manage.py run --max-samples 1
```

OpenAI Evals records are written beneath the ignored `tmp/openai-evals/` directory. These logs
contain questions, published values, and exact quotes, so they must be reviewed and sanitized
before being shared.

## Private or additional casebooks

Set `EXTENT_EVAL_CASES_PATH` to a local JSONL file to run another workspace without changing
the checked-in registry:

```bash
export EXTENT_EVAL_CASES_PATH=/absolute/path/to/local-cases.jsonl
pnpm eval:openai:validate
pnpm eval:openai
```

Custom casebooks always receive the citation contract checks. To also verify each exact quote and
line against local UTF-8 text, Markdown, or CSV copies of the evaluated files, set
`EXTENT_EVAL_SOURCE_ROOT` to their absolute directory. The checked-in golden suite enables this
source-content check automatically.

Each line has an OpenAI Evals `input`, a stable `case_id`, and deterministic `ideal` constraints:

```json
{
  "case_id": "structured-total",
  "input": [{ "role": "user", "content": "Sum Amount across all records." }],
  "ideal": {
    "status": "evidence_supported",
    "policy_version": "structured-analysis-policy-v1",
    "generation_status": "completed",
    "claim_values_exact": ["420"],
    "coverage_gap_reasons": [],
    "min_claims": 1,
    "max_claims": 1,
    "citation_mode": "required",
    "passage_mode": "forbidden",
    "required_sources": ["records.csv"]
  }
}
```

Volatile answer IDs, question IDs, timestamps, and Drive IDs are never graded. Model wording can
be constrained with `claim_text_includes` rather than exact prose, while values, statuses,
coverage gaps, evidence requirements, and policy selection remain deterministic.
Each case contains one standalone user question. Extent supplies prior answer history to the
generation model only for a genuinely referential follow-up, so these explicit samples do not
inherit unrelated answers persisted by earlier eval cases or runs.

The registry follows OpenAI Evals' documented
[custom-eval layout](https://github.com/openai/evals/blob/main/docs/build-eval.md), uses its
[`CompletionFn` interface](https://github.com/openai/evals/blob/main/docs/completion-fns.md), and
is passed with `--registry_path`. The local launcher calls the official `evals.cli.oaieval` engine
while skipping its unrelated public-API model discovery; the evaluated completion is always
`extent/http`.
