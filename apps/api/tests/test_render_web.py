"""Tests for the Render web-service entrypoint."""

import os
import sys
from unittest.mock import MagicMock, patch

from extent_api.render_web import main


@patch("extent_api.render_web.os.execv")
@patch("extent_api.render_web.subprocess.run")
def test_render_web_migrates_before_starting_api(
    run: MagicMock,
    execv: MagicMock,
) -> None:
    with patch.dict(os.environ, {"PORT": "12345"}):
        main()

    run.assert_called_once_with(
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
    execv.assert_called_once_with(
        sys.executable,
        [
            sys.executable,
            "-m",
            "uvicorn",
            "extent_api.main:app",
            "--host",
            "0.0.0.0",
            "--port",
            "12345",
        ],
    )
