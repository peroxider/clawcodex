"""Templates service layer (F-85).

This package provides a thin service layer for reusable agent
configuration templates. F-85 ships a full surface:

* :mod:`models` — :class:`Template` dataclass with strict validation
  and ``to_dict`` / ``from_dict`` round-trip.
* :mod:`schema` — the canonical schema contract: top-level shape,
  allowed keys, strict/lenient parser, single + bundle file support.
* :mod:`registry` — :class:`TemplateRegistry` for in-memory storage
  with optional disk discovery.
* :mod:`resolver` — :class:`TemplateResolver` for merging a base
  template with an inline override (deep dict merge, list-replace
  policy, shadow-key tracking).
* :mod:`persistence` — :class:`TemplateStateFile` with atomic save /
  load of the full registry, plus convenience helpers.
* :mod:`discovery` (P85-B) — path resolvers for the user / project /
  managed template directories.
* :mod:`bootstrap` (P85-B) — the public entry point that wires
  discovery into the process-wide default registry at CLI bootstrap
  time.
* :mod:`built_in` (P85-E) — the canonical 5-template catalogue
  (``general-purpose`` / ``explore`` / ``plan`` / ``fix`` /
  ``review``) that every install starts with.

P85-A: the schema module and the ``AgentDefinition.template`` field
close the gap between raw on-disk YAML/JSON and the typed in-memory
model. P85-C adds the actual template→agent resolution helper. P85-D
ships the CLI management surface (``/template list|show|create``).
P85-E ships the built-in catalogue that P85-B's bootstrap now
registers first so user / project / managed sources can shadow them.

The layer deliberately has no upstream dependencies on
:mod:`src.agent` — the dataclass model is field-driven and
permission-mode / effort / etc. are passed through as opaque strings
or values, leaving the agent integration glue for the resolver helper
in :mod:`src.agent.template_resolution`.
"""

from __future__ import annotations

from .bootstrap import (
    SOURCE_BUILT_IN,
    SOURCE_MANAGED,
    SOURCE_PROJECT,
    SOURCE_USER,
    bootstrap_default_templates,
)
from .built_in import (
    get_built_in_templates,
    register_built_in_templates,
)
from .discovery import (
    CLAWCODEX_CONFIG_DIR_ENV,
    CLAWCODEX_MANAGED_CONFIG_DIR_ENV,
    PROJECT_CONFIG_DIR,
    TEMPLATES_SUBDIR,
    get_managed_templates_dir,
    get_project_templates_dirs,
    get_user_templates_dir,
)
from .exceptions import (
    TemplateAlreadyExistsError,
    TemplateCorruptError,
    TemplateNotFoundError,
    TemplateResolutionError,
    TemplateValidationError,
    TemplatesError,
)
from .models import Template
from .persistence import (
    TemplateStateFile,
    load_registry,
    merge_registries,
    save_registry,
)
from .registry import (
    TemplateRegistry,
    get_default_template_registry,
    reset_default_template_registry,
)
from .resolver import ResolvedTemplate, TemplateResolver
from .schema import (
    SCHEMA_DESCRIPTION,
    TEMPLATE_FIELD_KEYS,
    TEMPLATE_SCHEMA_VERSION,
    TEMPLATE_TOP_LEVEL_KEYS,
    parse_template_file,
    parse_template_file_payload,
    parse_template_payload,
)

__all__ = [
    "CLAWCODEX_CONFIG_DIR_ENV",
    "CLAWCODEX_MANAGED_CONFIG_DIR_ENV",
    "PROJECT_CONFIG_DIR",
    "ResolvedTemplate",
    "SCHEMA_DESCRIPTION",
    "SOURCE_BUILT_IN",
    "SOURCE_MANAGED",
    "SOURCE_PROJECT",
    "SOURCE_USER",
    "TEMPLATE_FIELD_KEYS",
    "TEMPLATE_SCHEMA_VERSION",
    "TEMPLATE_TOP_LEVEL_KEYS",
    "TEMPLATES_SUBDIR",
    "Template",
    "TemplateAlreadyExistsError",
    "TemplateCorruptError",
    "TemplateNotFoundError",
    "TemplateRegistry",
    "TemplateResolutionError",
    "TemplateResolver",
    "TemplateStateFile",
    "TemplateValidationError",
    "TemplatesError",
    "bootstrap_default_templates",
    "get_built_in_templates",
    "get_default_template_registry",
    "get_managed_templates_dir",
    "get_project_templates_dirs",
    "get_user_templates_dir",
    "load_registry",
    "merge_registries",
    "parse_template_file",
    "parse_template_file_payload",
    "parse_template_payload",
    "register_built_in_templates",
    "reset_default_template_registry",
    "save_registry",
]
