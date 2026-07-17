"""Launch the official oaieval engine without unrelated API model discovery."""

from __future__ import annotations

import logging
import os
import sys
from typing import Any, cast


def main() -> None:
    # openai/evals creates an OpenAI client while importing its registry, even for
    # private CompletionFns. This placeholder is never sent: the private registry
    # below declares that no direct API models need discovery.
    os.environ["OPENAI_API_KEY"] = "unused-by-extent-private-completion"

    from evals.cli.oaieval import OaiEvalArguments, get_parser, run
    from evals.registry import Registry

    class PrivateCompletionRegistry(Registry):
        @property
        def api_model_ids(self) -> list[str]:
            return []

    logging.basicConfig(
        format="[%(asctime)s] [%(filename)s:%(lineno)d] %(message)s",
        level=logging.INFO,
    )
    arguments = cast(OaiEvalArguments, get_parser().parse_args(sys.argv[1:]))
    run(arguments, registry=cast(Any, PrivateCompletionRegistry(registry_paths=[])))


if __name__ == "__main__":
    main()
