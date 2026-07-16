"""Generate or verify the deterministic FastAPI OpenAPI artifact."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from extent_api.main import app

TARGET = Path(__file__).resolve().parents[1] / "openapi.json"


def rendered_openapi() -> str:
    return f"{json.dumps(app.openapi(), indent=2, sort_keys=True)}\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    arguments = parser.parse_args()
    rendered = rendered_openapi()

    if arguments.check:
        if not TARGET.exists() or TARGET.read_text(encoding="utf-8") != rendered:
            parser.error("apps/api/openapi.json is stale; run pnpm openapi:generate")
        return 0

    TARGET.write_text(rendered, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
