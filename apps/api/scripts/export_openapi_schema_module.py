"""Export the OpenAPI document as a TypeScript runtime schema module."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OPENAPI_PATH = ROOT / "apps" / "api" / "openapi.json"
OUTPUT_PATH = ROOT / "apps" / "web" / "src" / "generated" / "extent-api-schema.ts"


def render_module() -> str:
    document = json.loads(OPENAPI_PATH.read_text(encoding="utf-8"))
    payload = json.dumps(document, ensure_ascii=True, indent=2, sort_keys=True)
    return (
        "/**\n"
        " * This file is generated from the checked-in FastAPI OpenAPI document.\n"
        " * Do not edit it directly; run `pnpm openapi:generate`.\n"
        " */\n"
        f"export const extentApiSchema = {payload} as const;\n"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    expected = render_module()

    if args.check:
        if not OUTPUT_PATH.exists() or OUTPUT_PATH.read_text(encoding="utf-8") != expected:
            raise SystemExit(
                "Generated runtime OpenAPI schema is stale. Run `pnpm openapi:generate`."
            )
        return

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(expected, encoding="utf-8")


if __name__ == "__main__":
    main()
