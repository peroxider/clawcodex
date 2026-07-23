"""Paths to versioned macro authoring templates."""

from __future__ import annotations

from pathlib import Path

TEMPLATES_DIR = Path(__file__).resolve().parent

HANDWRITTEN_MACRO_TEMPLATE = TEMPLATES_DIR / "macro.definition.yaml.template"

__all__ = [
    "TEMPLATES_DIR",
    "HANDWRITTEN_MACRO_TEMPLATE",
]