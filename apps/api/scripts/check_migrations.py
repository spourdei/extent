"""Fail when Alembic has branches, multiple heads, or no baseline."""

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

API_ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    config = Config(API_ROOT / "alembic.ini")
    scripts = ScriptDirectory.from_config(config)
    heads = scripts.get_heads()
    if heads != ["20260717_0021"]:
        raise SystemExit(f"Expected one known migration head, received {heads!r}")
    if scripts.get_base() != "20260715_0001":
        raise SystemExit("The identity migration must remain the single baseline revision.")


if __name__ == "__main__":
    main()
