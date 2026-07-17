"""Regression checks for portable production model configuration."""

from pathlib import Path


def test_render_blueprint_keeps_provider_endpoint_out_of_source_control() -> None:
    repository = Path(__file__).resolve().parents[3]
    blueprint = (repository / "render.yaml").read_text()

    assert "EXTENT_MODEL_BASE_URL" not in blueprint
    assert "EXTENT_EMBEDDING_BASE_URL" not in blueprint
    assert "generativelanguage.googleapis.com" not in blueprint
    assert "gemini-embedding-001" not in blueprint
    assert "value: gemini-3.5-flash" in blueprint
    assert "value: text-embedding-3-large" in blueprint
