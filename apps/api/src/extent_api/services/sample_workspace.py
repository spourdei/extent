"""Load the fixed synthetic sample through the same strict public contract as live data."""

from functools import lru_cache
from importlib.resources import files

from extent_api.models import SampleWorkspaceProjection


@lru_cache(maxsize=1)
def get_sample_workspace() -> SampleWorkspaceProjection:
    fixture = files("extent_api.fixtures").joinpath("northstar_workspace.json")
    return SampleWorkspaceProjection.model_validate_json(fixture.read_text(encoding="utf-8"))
