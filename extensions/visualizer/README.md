# clawcodex-visualizer

Standalone web visualizer for ClawCodex agent sessions — Gantt charts,
timelines, performance analytics, and the live agent dashboard.

## Status

| Item | Value |
|---|---|
| **Decoupling track** | Visualizer Package Extraction — all landed on the `dev-decoupling-refactor` branch |
| **Upstream dep** | None (zero coupling to `src/`, `clawcodex_ext/`, or `extensions.capabilities`) |
| **Reverse deps** | `extensions.recording.visualizer_dashboard_source` (adapter only) |
| **Entry point** | `clawcodex.commands → viz` |
| **Install** | Currently rides in the monorepo `clawcodex-dev-mind` distribution; standalone PyPI metadata is staged in `extensions/visualizer/pyproject.toml` |

## Why this package exists

`COMMERCIALIZATION_EXECUTIVE_SUMMARY.md §4.2.2` classifies the visualizer
as a *low-cost extraction*: 25 Python files, ~6k lines, with hard
two-layer coupling only in **1 file**
(`asciicast_dashboard_source.py`, now relocated to `extensions.recording`
under the recorder adapter extraction). Every other file already depends only on `fastapi` /
`pydantic` / the standard library, so it lifts into a standalone
distribution with no surgery.

## What lives here after extraction

- `extensions/visualizer/server.py` — FastAPI app (`create_app`)
- `extensions/visualizer/ws.py` — WebSocket routers
- `extensions/visualizer/orchestrator_link.py` — orchestrator proxy
- `extensions/visualizer/import_router.py` — SSRF-protected session import
- `extensions/visualizer/cli.py` — `clawcodex viz` entry point
- `extensions/visualizer/_rendering.py` — **`panel()` helper** (private)
- `extensions/visualizer/protocols/` — **local copies of**
  `extensions.capabilities.dashboard_entry` and
  `extensions.capabilities.recorder` Protocol dataclasses
- `extensions/visualizer/builders/` — timeline / stats / agent-tree / anomaly / export
- `extensions/visualizer/parsers/` — session / transcript / orchestrator-state parsers
- `extensions/visualizer/models/viz_models.py` — pydantic models
- `extensions/visualizer/templates/` + `static/` — Jinja2 + frontend assets

## What moved out under extraction

| Path (old) | Path (new) | Component |
|---|---|---|
| `extensions/visualizer/asciicast_dashboard_source.py` | `extensions/recording/visualizer_dashboard_source.py` | recorder adapter |
| `extensions/recording/renderers.panel` | `extensions/visualizer/_rendering.panel` | `panel()` helper |
| `extensions.capabilities.dashboard_entry` (visualizer deps) | `extensions.visualizer.protocols.dashboard` | protocols |
| `extensions.capabilities.recorder` (visualizer deps) | `extensions.visualizer.protocols.recorder` | protocols |

## Running

```bash
# Today (monorepo):
clawcodex-dev viz --port 8765

# Tomorrow (standalone distribution):
pip install clawcodex-visualizer
clawcodex-dev viz --port 8765
```

## Tests

| Suite | Command |
|---|---|
| Visualizer unit (monorepo) | `python3 -m pytest tests/visualizer/ tests/test_visualizer/ -q` |
| Visualizer recording | `python3 -m pytest tests/extensions/recording/test_visualizer_source.py -q` |
| Stability gate | `python3 -m pytest tests/stability_gate/ -q` |

## Design decisions

See `docs/feature_plan/04-architecture-sdk/f-167-visualizer-package-extract.md` §9.