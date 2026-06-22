"""Small dotenv loader for CI helper scripts.

The CI helpers are intentionally stdlib-only so they can run before optional
developer dependencies are installed. This loader supports the simple
``KEY=value`` format used by release tokens and leaves existing environment
variables untouched by default.
"""

from __future__ import annotations

import os
import re
import shlex
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
ENV_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _parse_value(raw: str) -> str:
    raw = raw.strip()
    if not raw:
        return ""
    if raw[0] in {"'", '"'}:
        try:
            parts = shlex.split(raw, comments=False, posix=True)
        except ValueError:
            return raw.strip("'\"")
        return parts[0] if parts else ""
    return raw.split(" #", 1)[0].strip()


def load_dotenv(path: Path | None = None, *, override: bool = False) -> Path | None:
    env_path = path or ROOT / ".env"
    if not env_path.exists():
        return None

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line.removeprefix("export ").strip()
        if "=" not in line:
            continue

        key, raw_value = line.split("=", 1)
        key = key.strip()
        if not ENV_KEY.match(key):
            continue
        if override or key not in os.environ:
            os.environ[key] = _parse_value(raw_value)

    return env_path


def ensure_dotenv(path: Path | None = None, example_path: Path | None = None) -> tuple[Path, bool]:
    env_path = path or ROOT / ".env"
    if env_path.exists():
        return env_path, False

    template_path = example_path or ROOT / ".env.example"
    if template_path.exists():
        env_path.write_text(template_path.read_text(encoding="utf-8"), encoding="utf-8")
    else:
        env_path.write_text(
            "\n".join(
                [
                    "# Local F-73 release credentials. Never commit real token values.",
                    "GITCODE_TOKEN=",
                    "TEST_PYPI_TOKEN=",
                    "# PYPI_TOKEN=",
                    "GITCODE_OWNER=",
                    "GITCODE_REPO=",
                    "GITCODE_API_ROOT=https://api.gitcode.com",
                    "",
                ]
            ),
            encoding="utf-8",
        )
    return env_path, True
