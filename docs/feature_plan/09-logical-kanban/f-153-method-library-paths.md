# F-153 Method Library Paths

## Overview

Methods and proposals are stored as **human-readable JSON files** on the
filesystem.  No database is required.

## Directory Layout

```
~/.cache/clawcodex/lkb/
├── methods/                    # User-level method library files
│   ├── my_team_methods.json    # Any *.json file is loaded
│   └── custom_variants.json
├── proposals/                  # Method proposals (one .json per proposal)
│   ├── P-ABC12345.json
│   └── P-DEF67890.json
```

## Loading Order (Priority)

When the system starts, methods are loaded in three layers,
**last writer wins**:

| Layer | Path | Priority |
|-------|------|----------|
| **Built-in seeds** | `METHOD_LIBRARY` in `method_library.py` | Lowest |
| **User-level** | `~/.cache/clawcodex/lkb/methods/*.json` | Medium |
| **Project-level** | `<project-dir>/.lkb/methods/*.json` | Highest |

### Conflict Resolution

If two layers define a method with the same `method_id`, the
higher-priority layer's version replaces the lower one:

- Project-level **overrides** user-level.
- User-level **overrides** built-in seeds.

This allows teams to ship custom method variants in the project repo
and individual developers to override them locally.

## Proposals

Each proposal is persisted as a single JSON file:

```
~/.cache/clawcodex/lkb/proposals/{proposal_id}.json
```

Proposals are loaded at CLI startup into the in-memory proposal store.
Corrupt or unparseable proposal files are silently skipped.

## Error Handling

- Missing directories are **not** an error — they are simply skipped.
- Corrupt JSON files produce a warning (via logging) but do **not** crash
  the startup process.  The corrupt file is skipped.
- If both user-level and project-level directories exist, the merge
  proceeds with the priority rules above.

## Creating Default Directories

```python
from clawcodex_ext.logical_kanban.method_library import ensure_default_dirs
ensure_default_dirs()
```

This creates `~/.cache/clawcodex/lkb/methods/` and
`~/.cache/clawcodex/lkb/proposals/` if they don't exist.

## Example: Save a Custom Method

```python
from pathlib import Path
from clawcodex_ext.logical_kanban.method_library import (
    EngineeringMethod, SubtaskTemplate, save_method_library,
)

method = EngineeringMethod(
    method_id="M-custom-001",
    pattern="my_custom_pattern",
    description="My team's custom pattern",
    subtask_templates=(
        SubtaskTemplate(template_id="ST-1", role="impl",
                        subject_template="Do {thing}"),
    ),
    version="0.1.0",
    status="draft",
)

# Save to user-level layer
user_path = Path.home() / ".cache" / "clawcodex" / "lkb" / "methods" / "custom.json"
save_method_library([method], user_path)

# Or save to project-level (overrides user-level)
project_path = Path.cwd() / ".lkb" / "methods" / "custom.json"
save_method_library([method], project_path)
```
