"""Config persistence for feature flags.

Stores and loads feature states to/from ``~/.clawcodex/features.json``.
Supports JSON format only (YAML support can be added later if PyYAML is
available).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Default location for the feature-gate config file.
_DEFAULT_CONFIG_DIR = Path.home() / ".clawcodex"
_DEFAULT_CONFIG_FILE = _DEFAULT_CONFIG_DIR / "features.json"


class ConfigStore:
    """Read/write feature-flag states to a JSON file.

    All operations are best-effort: file I/O errors are logged but
    never raised so that the feature-gate system never blocks the CLI.
    """

    def __init__(
        self,
        config_dir: Path | None = None,
        config_file: Path | None = None,
    ) -> None:
        self._config_dir = config_dir or _DEFAULT_CONFIG_DIR
        self._config_file = config_file or (self._config_dir / "features.json")
        self._cache: dict[str, Any] = {}
        self._loaded = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get(self, name: str) -> bool | None:
        """Return the persisted value for *name*, or ``None`` if absent."""
        self._ensure_loaded()
        return self._cache.get(name)

    def save(self, states: dict[str, bool]) -> None:
        """Persist *states* to disk.

        Args:
            states: Mapping of feature name → enabled state.
        """
        try:
            self._config_dir.mkdir(parents=True, exist_ok=True)
            with open(self._config_file, "w", encoding="utf-8") as fh:
                json.dump(states, fh, indent=2, sort_keys=True)
            # Update cache so subsequent reads are instant.
            self._cache.update(states)
            self._loaded = True
            logger.debug("Saved feature states to %s", self._config_file)
        except OSError as exc:
            logger.warning("Failed to save feature config to %s: %s", self._config_file, exc)

    def reload(self) -> None:
        """Force-reload the config file from disk."""
        self._loaded = False
        self._cache.clear()
        self._ensure_loaded()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ensure_loaded(self) -> None:
        """Load the config file lazily on first access."""
        if self._loaded:
            return
        try:
            if self._config_file.exists():
                with open(self._config_file, "r", encoding="utf-8") as fh:
                    self._cache = json.load(fh)
                self._loaded = True
                logger.debug("Loaded feature config from %s", self._config_file)
            else:
                self._loaded = True  # No file yet; considered empty.
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to load feature config from %s: %s", self._config_file, exc)
            self._cache.clear()
            self._loaded = True

    @property
    def config_file(self) -> Path:
        """Path to the persisted config file."""
        return self._config_file

    @property
    def config_dir(self) -> Path:
        """Path to the config directory."""
        return self._config_dir
