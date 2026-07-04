from __future__ import annotations

import importlib


def _load_module(monkeypatch):
    monkeypatch.syspath_prepend("scripts/ci")
    return importlib.import_module("docs_check")


def test_candidate_paths_skip_raw_snapshot_docs(tmp_path, monkeypatch):
    docs_check = _load_module(monkeypatch)
    monkeypatch.setattr(docs_check, "ROOT", tmp_path)

    raw_doc = tmp_path / "docs" / "i18n.raw" / "README_ZH.md"
    raw_doc.parent.mkdir(parents=True)
    raw_doc.write_text("[missing](../missing.md)\n", encoding="utf-8")
    curated_doc = tmp_path / "docs" / "README.md"
    curated_doc.write_text("# Docs\n", encoding="utf-8")

    paths = docs_check._candidate_paths(
        ["docs/i18n.raw/README_ZH.md", "docs/README.md"],
        all_docs=False,
    )

    assert paths == [curated_doc]
