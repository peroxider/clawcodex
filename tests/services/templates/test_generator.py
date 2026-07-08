from __future__ import annotations

from pathlib import Path

import pytest

from src.services.templates import (
    RenderedTemplate,
    TemplateGenerator,
    TemplateOverwriteError,
    TemplateUnsafePathError,
)


def test_generator_writes_file(tmp_path: Path) -> None:
    target = tmp_path / "out" / "file.md"
    rendered = RenderedTemplate(
        template_id="x",
        kind="generic",
        content="hello",
        output_path=target,
        variables_used={},
    )
    path = TemplateGenerator(workspace_root=tmp_path).generate(rendered)
    assert path == target
    assert target.read_text(encoding="utf-8") == "hello"


def test_generator_defaults_to_no_overwrite(tmp_path: Path) -> None:
    target = tmp_path / "file.md"
    target.write_text("old", encoding="utf-8")
    rendered = RenderedTemplate("x", "generic", "new", target, {})
    with pytest.raises(TemplateOverwriteError):
        TemplateGenerator(workspace_root=tmp_path).generate(rendered)
    assert target.read_text(encoding="utf-8") == "old"


def test_generator_overwrite_explicit(tmp_path: Path) -> None:
    target = tmp_path / "file.md"
    target.write_text("old", encoding="utf-8")
    rendered = RenderedTemplate("x", "generic", "new", target, {})
    TemplateGenerator(workspace_root=tmp_path).generate(rendered, overwrite=True)
    assert target.read_text(encoding="utf-8") == "new"


def test_generator_rejects_path_outside_workspace(tmp_path: Path) -> None:
    rendered = RenderedTemplate("x", "generic", "x", tmp_path.parent / "outside.md", {})
    with pytest.raises(TemplateUnsafePathError):
        TemplateGenerator(workspace_root=tmp_path).generate(rendered)
