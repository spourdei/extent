"""Render web-service entrypoint with an idempotent migration boundary."""

import os
import subprocess
import sys


def main() -> None:
    """Apply migrations, then replace this process with the public API server."""

    subprocess.run(
        [
            sys.executable,
            "-m",
            "alembic",
            "-c",
            "apps/api/alembic.ini",
            "upgrade",
            "head",
        ],
        check=True,
    )
    os.execv(
        sys.executable,
        [
            sys.executable,
            "-m",
            "uvicorn",
            "extent_api.main:app",
            "--host",
            "0.0.0.0",
            "--port",
            os.environ.get("PORT", "10000"),
        ],
    )


if __name__ == "__main__":
    main()
