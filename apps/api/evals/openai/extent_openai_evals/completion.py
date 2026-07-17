"""OpenAI Evals CompletionFn that exercises Extent through its real HTTP API."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import re
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID, uuid4

from extent_openai_evals.contracts import canonicalize_response, question_from_prompt

_COOKIE_NAME = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]{0,63}$")
_MAX_RESPONSE_BYTES = 2_000_000


class ExtentEvalConfigurationError(ValueError):
    """Raised when the live evaluation environment is incomplete or unsafe."""


class ExtentEvalRequestError(RuntimeError):
    """Raised when Extent does not return a valid published result."""


class _RejectRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: object,
        code: int,
        msg: str,
        headers: object,
        newurl: str,
    ) -> None:
        del req, fp, code, msg, headers, newurl
        return None


_DIRECT_OPENER = urllib.request.build_opener(
    urllib.request.ProxyHandler({}),
    _RejectRedirects(),
)


@dataclass(frozen=True)
class ExtentCompletionResult:
    """Minimal implementation of the OpenAI Evals CompletionResult protocol."""

    completion: str

    def get_completions(self) -> list[str]:
        return [self.completion]


class ExtentHttpCompletionFn:
    """Submit one question to the same endpoint used by the frontend."""

    def __init__(self, *, registry: object | None = None, **_: object) -> None:
        del registry
        self._endpoint = _question_endpoint(
            os.environ.get("EXTENT_EVAL_API_BASE_URL", "http://127.0.0.1:8000"),
            _required_environment("EXTENT_EVAL_WORKSPACE_ID"),
        )
        self._origin = os.environ.get("EXTENT_EVAL_ORIGIN", "http://localhost:3000").rstrip("/")
        _validate_origin(self._origin)
        self._cookie_name = os.environ.get("EXTENT_EVAL_SESSION_COOKIE_NAME", "extent_session")
        if _COOKIE_NAME.fullmatch(self._cookie_name) is None:
            raise ExtentEvalConfigurationError("eval session cookie name is invalid")
        self._session_value = _required_environment("EXTENT_EVAL_SESSION_COOKIE_VALUE")
        if len(self._session_value) > 4_096 or any(
            character in self._session_value for character in ";\r\n"
        ):
            raise ExtentEvalConfigurationError("eval session cookie value is invalid")
        self._timeout_seconds = _timeout_seconds()
        self._namespace = uuid4().hex
        self._counter = 0
        self._counter_lock = threading.Lock()

    def __call__(self, prompt: object, **_: object) -> ExtentCompletionResult:
        question = _question_from_prompt(prompt)
        request = urllib.request.Request(
            self._endpoint,
            data=json.dumps({"question": question}).encode("utf-8"),
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Cookie": f"{self._cookie_name}={self._session_value}",
                "Idempotency-Key": self._idempotency_key(question),
                "Origin": self._origin,
            },
            method="POST",
        )
        try:
            with _DIRECT_OPENER.open(request, timeout=self._timeout_seconds) as response:
                status = response.status
                raw = response.read(_MAX_RESPONSE_BYTES + 1)
        except urllib.error.HTTPError as error:
            detail = _safe_error_detail(error)
            if error.code in {401, 403, 404, 409}:
                raise ExtentEvalConfigurationError(
                    f"Extent live eval setup was rejected with HTTP {error.code}: {detail}"
                ) from error
            raise ExtentEvalRequestError(
                f"Extent returned HTTP {error.code}: {detail}"
            ) from error
        except urllib.error.URLError as error:
            raise ExtentEvalRequestError(
                f"Extent request failed: {type(error.reason).__name__}"
            ) from error
        if status != 201:
            raise ExtentEvalRequestError(f"Extent returned unexpected HTTP {status}")
        if len(raw) > _MAX_RESPONSE_BYTES:
            raise ExtentEvalRequestError("Extent response exceeded the 2 MB eval limit")
        try:
            payload = json.loads(raw)
            canonical = canonicalize_response(payload, expected_question=question)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
            raise ExtentEvalRequestError(
                "Extent returned a malformed publication result"
            ) from error
        completion = json.dumps(
            canonical, ensure_ascii=True, separators=(",", ":"), sort_keys=True
        )
        _record_sampling(prompt, completion)
        return ExtentCompletionResult(completion)

    def _idempotency_key(self, question: str) -> str:
        with self._counter_lock:
            self._counter += 1
            counter = self._counter
        digest = hashlib.sha256(question.encode("utf-8")).hexdigest()[:20]
        return f"openai-evals-{self._namespace}-{counter}-{digest}"


def _question_endpoint(base_url: str, workspace_id: str) -> str:
    try:
        normalized_workspace_id = str(UUID(workspace_id))
    except ValueError as error:
        raise ExtentEvalConfigurationError("EXTENT_EVAL_WORKSPACE_ID must be a UUID") from error
    parsed = urlsplit(base_url.rstrip("/"))
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ExtentEvalConfigurationError(
            "EXTENT_EVAL_API_BASE_URL must be an HTTP(S) origin or path without credentials"
        )
    if parsed.scheme == "http" and not _is_loopback_host(parsed.hostname):
        raise ExtentEvalConfigurationError(
            "EXTENT_EVAL_API_BASE_URL must use HTTPS unless it targets loopback"
        )
    path = parsed.path.rstrip("/")
    path += f"/api/v1/workspaces/{normalized_workspace_id}/messages"
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


def _validate_origin(origin: str) -> None:
    parsed = urlsplit(origin)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise ExtentEvalConfigurationError("EXTENT_EVAL_ORIGIN must be an HTTP(S) origin")


def _question_from_prompt(prompt: object) -> str:
    try:
        return question_from_prompt(prompt)
    except ValueError as error:
        raise ExtentEvalRequestError(
            "eval prompt must contain exactly one 3-to-2,000 character user question"
        ) from error


def _is_loopback_host(hostname: str | None) -> bool:
    if hostname is None:
        return False
    if hostname.casefold() == "localhost":
        return True
    try:
        return ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        return False


def _timeout_seconds() -> float:
    raw = os.environ.get("EXTENT_EVAL_TIMEOUT_SECONDS", "750")
    try:
        value = float(raw)
    except ValueError as error:
        raise ExtentEvalConfigurationError(
            "EXTENT_EVAL_TIMEOUT_SECONDS must be numeric"
        ) from error
    if not 1 <= value <= 900:
        raise ExtentEvalConfigurationError(
            "EXTENT_EVAL_TIMEOUT_SECONDS must be between 1 and 900"
        )
    return value


def _required_environment(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ExtentEvalConfigurationError(f"{name} is required")
    return value


def _safe_error_detail(error: urllib.error.HTTPError) -> str:
    raw = error.read(8_193)
    if len(raw) > 8_192:
        return "response body exceeded limit"
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return "non-JSON error response"
    if not isinstance(payload, dict):
        return "unexpected error response"
    code = payload.get("code")
    message = payload.get("message")
    if isinstance(code, str) and isinstance(message, str):
        return f"{code}: {message}"
    return "unstructured error response"


def _record_sampling(prompt: object, completion: str) -> None:
    # Imported lazily so casebook validation remains usable before the optional,
    # heavyweight OpenAI Evals environment is installed.
    from evals.record import record_sampling

    record_sampling(prompt=prompt, sampled=[completion], model="extent-http")
