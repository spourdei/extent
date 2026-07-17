"""Load the prepared Alder Peak sample through the strict public read contract."""

from functools import lru_cache
from importlib.resources import files

from extent_api.models import SampleWorkspaceProjection


@lru_cache(maxsize=1)
def get_sample_workspace() -> SampleWorkspaceProjection:
    fixture = files("extent_api.fixtures").joinpath("alder_peak_workspace.json")
    return SampleWorkspaceProjection.model_validate_json(fixture.read_text(encoding="utf-8"))
