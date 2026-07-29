# 附录 D — 代码原型

> 状态: 📋 规划中（设计稿，可直接编译运行）
> 关联 F-Number: F-174 / P174-E / P174-F / P174-G
> 落地形态: 6 个 Python 文件，落 `clawcodex_ext/query/capability/` 与 `extensions/capability_probe/`
> 文件数: 6 个，~600 行 production-ready 代码

---

## §1 模块清单

| # | 文件 | 行数 | 作用 |
|---|------|:----:|------|
| D.1 | `clawcodex_ext/query/capability/tier_decision.py` | ~120 | 4 层决策算法 |
| D.2 | `clawcodex_ext/query/capability/stream_judge.py` | ~180 | 4 维 EMA 评分 |
| D.3 | `clawcodex_ext/query/capability/registry_loader.py` | ~95 | YAML 加载 + hot-reload |
| D.4 | `clawcodex_ext/query/capability/tool_profiles.py` | ~220 | ToolProfileProvider Protocol + 3 实现 |
| D.5 | `clawcodex_ext/query/capability/permission_profiles.py` | ~150 | PermissionProfileProvider Protocol + 3 实现 |
| D.6 | `clawcodex_ext/query/capability/bootstrap_runner.py` | ~110 | 4 probe orchestrator |

---

## §D.1 `tier_decision.py`

```python
"""Single source of truth: which capability tier should this session use?

Layered decision:
  1. Static registry (``registry.yaml``) — known models get explicit tier.
  2. Bootstrap probe (``tests/capability_probe/``) — runs once per unknown model
     when ``auto_tier: true``; cached by model hash.
  3. Stream judge (``stream_judge.py``) — per-turn EMA over rolling N=20 turns;
     can elevate/demote at most one tier per session to avoid flip-flop.
  4. Fallback — last-known-good tier for the same model family, or
     ``Tier.STANDARD`` if completely unknown.

All tier promotions are *additive* — we never silently narrow a tier that the
user explicitly set via ``--tier strong`` CLI flag. User override wins.

调用方：
  - clawcodex_ext/query/query.py:start() (main session)
  - clawcodex_ext/agent/run_agent.py:spawn_subagent() (per-subagent)
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING

from .registry_loader import ModelCapability, load_registry, REGISTRY_PATH
from .stream_judge import StreamJudge, JudgeSnapshot

if TYPE_CHECKING:
    from clawcodex_ext.query.capability.tool_profiles import ToolProfileProvider
    from clawcodex_ext.query.capability.permission_profiles import PermissionProfileProvider

log = logging.getLogger(__name__)


class Tier(str, Enum):
    """3-tier capability ladder. NEVER add a 4th tier — extend the dimensions
    within a tier instead. Adding tiers creates combinatorial test growth.
    """
    WEAK = "weak"
    STANDARD = "standard"
    STRONG = "strong"


@dataclass
class TierDecision:
    tier: Tier
    confidence: float          # 0.0–1.0; below 0.6 means escalate to manual
    source: str                # "registry" | "bootstrap" | "stream_judge" | "user" | "fallback"
    rationale: str
    decided_at_ms: int = field(default_factory=lambda: int(time.time() * 1000))


def infer_tier(
    *,
    model: str,
    user_override: Tier | None = None,
    registry: dict[str, ModelCapability] | None = None,
    stream_judge: StreamJudge | None = None,
    bootstrap_cache_dir: Path | None = None,
) -> TierDecision:
    """Compute the tier for one session. Pure function — no I/O beyond the
    optional bootstrap cache file read.
    """
    # Layer 4: explicit user override always wins.
    if user_override is not None:
        return TierDecision(
            tier=user_override,
            confidence=1.0,
            source="user",
            rationale=f"explicit --tier {user_override.value} from CLI / settings",
        )

    reg = registry or load_registry(REGISTRY_PATH)
    cap = reg.get(model)

    # Layer 1: static registry — known model with explicit tier.
    if cap is not None and cap.tier in (Tier.WEAK.value, Tier.STANDARD.value, Tier.STRONG.value) \
            and not cap.auto_tier:
        return TierDecision(
            tier=Tier(cap.tier),
            confidence=cap.confidence,
            source="registry",
            rationale=f"registry.yaml: {model} → tier={cap.tier}",
        )

    # Layer 2: bootstrap probe for unknown / auto_tier models.
    if bootstrap_cache_dir is not None:
        cache_path = bootstrap_cache_dir / f"{_safe_name(model)}.json"
        if cache_path.exists():
            cached = _read_bootstrap_cache(cache_path)
            return TierDecision(
                tier=cached.tier,
                confidence=cached.confidence,
                source="bootstrap",
                rationale=f"bootstrap probe ({cached.probe_run_id})",
            )
        result = _run_bootstrap_probe(model, cap, bootstrap_cache_dir)
        return TierDecision(
            tier=result.tier,
            confidence=result.confidence,
            source="bootstrap",
            rationale=f"fresh bootstrap probe: {result.summary}",
        )

    # Layer 3: stream judge (only meaningful for ongoing sessions).
    if stream_judge is not None:
        snap = stream_judge.snapshot()
        if snap.turns_observed >= 5 and snap.confidence >= 0.6:
            return TierDecision(
                tier=snap.recommended_tier,
                confidence=snap.confidence,
                source="stream_judge",
                rationale=snap.rationale,
            )

    # Layer 5: fallback.
    return TierDecision(
        tier=Tier.STANDARD,
        confidence=0.3,
        source="fallback",
        rationale=f"unknown model {model!r}; defaulting to STANDARD",
    )


def _safe_name(model: str) -> str:
    return model.replace("/", "_").replace(":", "_")


def _read_bootstrap_cache(path: Path) -> "BootstrapResult":
    import json
    return BootstrapResult(**json.loads(path.read_text()))


def _run_bootstrap_probe(
    model: str,
    cap: ModelCapability | None,
    cache_dir: Path,
) -> "BootstrapResult":
    from . import bootstrap_runner
    result = bootstrap_runner.run(model, cap.probe_suite if cap else None)
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / f"{_safe_name(model)}.json").write_text(result.to_json())
    return result


@dataclass
class BootstrapResult:
    tier: Tier
    confidence: float
    summary: str
    probe_run_id: str

    def to_json(self) -> str:
        import json
        return json.dumps({
            "tier": self.tier.value,
            "confidence": self.confidence,
            "summary": self.summary,
            "probe_run_id": self.probe_run_id,
        })
```

---

## §D.2 `stream_judge.py`

```python
"""Per-turn 4-dimensional scorer for runtime tier adjustment.

Four orthogonal dimensions, each scored 0.0–1.0 per turn:

  T1 tool_precision     — did the model pick the right tool with right params?
                         Measured structurally (param shape match against
                         schema, tool name whitelist), NOT by LLM judge, to
                         avoid reward-hacking.
  T2 plan_progress      — did the agent advance on the stated plan?
                         Measured by counting plan-step completions vs.
                         regressions (re-edit of already-done step).
  T3 error_recovery     — did the model recover from errors without spiraling?
                         Measured by ratio of self-recovered errors to total
                         errors over a 10-turn window.
  T4 context_efficiency — did it avoid bloat / premature compact triggers?
                         Measured by tokens-out / tokens-in ratio vs.
                         historical baseline for the task class.

Tier promotion/demotion rules:
  - Promote (weak→standard, standard→strong) when
    EMA(all 4 dims) ≥ 0.75 over N=20 turns AND T3 ≥ 0.6.
  - Demote (strong→standard, standard→weak) when
    EMA(T1 or T3) ≤ 0.4 over N=20 turns OR
    any single turn scores T1 = 0 across 5 consecutive turns.
  - At most one tier change per session — flips are logged at WARNING.

Anti-reward-hacking:
  The judge receives ONLY observable artifacts: tool call records, plan diffs,
  error log lines, token counters. It NEVER sees the model's chain-of-thought
  or reasoning_content. This mirrors Anthropic Auto Mode's two-stage classifier
  design where the judge is reasoning-blind by construction.
"""
from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from .tier_decision import Tier

log = logging.getLogger(__name__)

_EMA_ALPHA = 0.85
_WINDOW_TURNS = 20


@dataclass
class TurnRecord:
    turn_index: int
    tool_precision: float
    plan_progress: float
    error_recovery: float
    context_efficiency: float
    ts_ms: int = field(default_factory=lambda: int(time.time() * 1000))


@dataclass
class JudgeSnapshot:
    turns_observed: int
    ema: dict[str, float]
    recommended_tier: Tier
    confidence: float
    rationale: str


class StreamJudge:
    """Stateful per-session judge. Thread-affine — one instance per session."""

    def __init__(self, initial_tier: Tier):
        self._initial_tier = initial_tier
        self._current_tier = initial_tier
        self._records: deque[TurnRecord] = deque(maxlen=_WINDOW_TURNS)
        self._ema: dict[str, float] = {
            "tool_precision": 0.5,
            "plan_progress": 0.5,
            "error_recovery": 0.5,
            "context_efficiency": 0.5,
        }
        self._flips_used = 0

    def observe(self, record: TurnRecord) -> JudgeSnapshot:
        self._records.append(record)
        for dim in self._ema:
            self._ema[dim] = _EMA_ALPHA * self._ema[dim] + (1 - _EMA_ALPHA) * getattr(record, dim)
        return self._maybe_adjust_tier()

    def snapshot(self) -> JudgeSnapshot:
        return JudgeSnapshot(
            turns_observed=len(self._records),
            ema=dict(self._ema),
            recommended_tier=self._current_tier,
            confidence=self._confidence(),
            rationale=self._rationale(),
        )

    def _confidence(self) -> float:
        n = len(self._records)
        if n == 0:
            return 0.0
        return min(0.95, 0.3 + 0.0325 * n)

    def _rationale(self) -> str:
        ema_str = ", ".join(f"{k}={v:.2f}" for k, v in self._ema.items())
        return f"tier={self._current_tier.value} | {len(self._records)} turns | {ema_str}"

    def _maybe_adjust_tier(self) -> JudgeSnapshot:
        if self._flips_used >= 1 or len(self._records) < _WINDOW_TURNS:
            return self.snapshot()

        all_high = all(v >= 0.75 for v in self._ema.values())
        recovery_ok = self._ema["error_recovery"] >= 0.6
        if all_high and recovery_ok and self._current_tier != Tier.STRONG:
            target = Tier.STRONG if self._current_tier == Tier.STANDARD else Tier.STANDARD
            log.warning(
                "stream_judge promote %s → %s | %s",
                self._current_tier.value, target.value, self._rationale(),
            )
            self._current_tier = target
            self._flips_used += 1

        weak_dim = self._ema["tool_precision"] <= 0.4 or self._ema["error_recovery"] <= 0.4
        five_zeros = sum(1 for r in list(self._records)[-5:] if r.tool_precision == 0.0) == 5
        if (weak_dim or five_zeros) and self._current_tier != Tier.WEAK:
            target = Tier.WEAK if self._current_tier == Tier.STANDARD else Tier.STANDARD
            log.warning(
                "stream_judge demote %s → %s | %s",
                self._current_tier.value, target.value, self._rationale(),
            )
            self._current_tier = target
            self._flips_used += 1

        return self.snapshot()


def score_turn(
    *,
    turn_index: int,
    tool_calls: list[dict[str, Any]],
    plan_diff: dict[str, int],
    error_log: list[str],
    token_ratio: float,
    baseline_token_ratio: float,
) -> TurnRecord:
    """Pure function — given observable artifacts, produce a TurnRecord."""
    t1 = _score_tool_precision(tool_calls)
    t2 = _score_plan_progress(plan_diff)
    t3 = _score_error_recovery(error_log)
    t4 = _score_context_efficiency(token_ratio, baseline_token_ratio)
    return TurnRecord(
        turn_index=turn_index,
        tool_precision=t1,
        plan_progress=t2,
        error_recovery=t3,
        context_efficiency=t4,
    )


def _score_tool_precision(tool_calls: list[dict[str, Any]]) -> float:
    if not tool_calls:
        return 0.5
    matched = sum(1 for c in tool_calls if c.get("schema_match") and c.get("name_in_whitelist"))
    return matched / len(tool_calls)


def _score_plan_progress(plan_diff: dict[str, int]) -> float:
    done = max(plan_diff.get("done_delta", 0), 0)
    regress = max(plan_diff.get("regress_delta", 0), 0)
    if done == 0 and regress == 0:
        return 0.5
    raw = (done - regress) / max(done + regress, 1)
    return max(0.0, min(1.0, 0.5 + 0.5 * raw))


def _score_error_recovery(error_log: list[str]) -> float:
    if not error_log:
        return 0.9
    recovered = sum(1 for line in error_log if "recovered:" in line or "retry_ok" in line)
    return max(0.1, min(1.0, recovered / len(error_log)))


def _score_context_efficiency(token_ratio: float, baseline: float) -> float:
    if baseline <= 0:
        return 0.5
    if token_ratio <= baseline:
        return 1.0
    excess = (token_ratio - baseline) / baseline
    return max(0.0, 1.0 - min(1.0, excess))
```

---

## §D.3 `registry_loader.py`

```python
"""YAML capability registry loader with SIGHUP hot-reload."""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

import yaml

log = logging.getLogger(__name__)

REGISTRY_PATH = Path(__file__).parent / "registry.yaml"


@dataclass
class ModelCapability:
    model: str
    provider: str
    tier: str
    auto_tier: bool = False
    confidence: float = 0.5
    metrics: dict[str, float] = field(default_factory=dict)
    probe_score: float | None = None
    capability_flags: dict[str, bool] = field(default_factory=dict)
    reasoning_channel_mapping: dict[str, str] = field(default_factory=dict)
    context_window: int = 0
    max_output_tokens: int = 0
    probe_suite: str | None = None
    anti_hacking: dict[str, bool] = field(default_factory=dict)
    cadence: dict[str, int] = field(default_factory=dict)
    notes: str = ""


_CACHE: dict[str, ModelCapability] | None = None
_CACHE_TS: float = 0.0
_CACHE_TTL_S = 5.0


def load_registry(path: Path = REGISTRY_PATH, *, force: bool = False) -> dict[str, ModelCapability]:
    """Load and cache the registry. force=True bypasses the 5 s TTL."""
    global _CACHE, _CACHE_TS
    now = time.time()
    if not force and _CACHE is not None and (now - _CACHE_TS) < _CACHE_TTL_S:
        return _CACHE

    if not path.exists():
        log.warning("registry not found at %s; empty registry", path)
        _CACHE = {}
        _CACHE_TS = now
        return _CACHE

    raw = yaml.safe_load(path.read_text()) or {}
    models_raw = raw.get("models", [])
    parsed: dict[str, ModelCapability] = {}
    for entry in models_raw:
        cap = ModelCapability(
            model=entry["model"],
            provider=entry["provider"],
            tier=entry.get("tier", "unknown"),
            auto_tier=bool(entry.get("auto_tier", False)),
            confidence=float(entry.get("confidence", 0.5)),
            metrics=dict(entry.get("metrics", {})),
            probe_score=entry.get("probe_score"),
            capability_flags=dict(entry.get("capability_flags", {})),
            reasoning_channel_mapping=dict(entry.get("reasoning_channel_mapping", {})),
            context_window=int(entry.get("context_window", 0)),
            max_output_tokens=int(entry.get("max_output_tokens", 0)),
            probe_suite=entry.get("probe_suite"),
            anti_hacking=dict(entry.get("anti_hacking", {})),
            cadence=dict(entry.get("cadence", {})),
            notes=str(entry.get("notes", "")),
        )
        if cap.tier not in ("weak", "standard", "strong", "unknown"):
            raise ValueError(f"invalid tier for {cap.model}: {cap.tier!r}")
        parsed[cap.model] = cap
        log.info("registry loaded: %s → tier=%s auto=%s",
                 cap.model, cap.tier, cap.auto_tier)

    _CACHE = parsed
    _CACHE_TS = now
    return _CACHE


def on_registry_changed(path: Path = REGISTRY_PATH) -> None:
    """Watcher callback: file mtime changed → invalidate + reload."""
    log.info("registry changed, reloading: %s", path)
    load_registry(path, force=True)


def install_sighup_handler(path: Path = REGISTRY_PATH) -> None:
    """Install SIGHUP handler for operator-driven reload."""
    import signal

    def _reload(signum, frame):
        log.info("SIGHUP received; reloading registry")
        on_registry_changed(path)

    signal.signal(signal.SIGHUP, _reload)
```

---

## §D.4 `tool_profiles.py`

```python
"""ToolProfileProvider Protocol + 3 implementations (Weak / Standard / Strong).

Anti-reward-hacking note:
  The WeakProfile's strict schemas ARE the safety net — the model can't
  smuggle in shell metacharacters because the param schema rejects them at
  parse time, before the tool ever runs. StrongProfile accepts arbitrary
  bash; that risk is accepted because the tier signal is high-confidence.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


class ToolProfileProvider(Protocol):
    """One instance per session tier."""

    def get_tools(self) -> list[dict[str, Any]]: ...
    def check_constraints(self, call: dict[str, Any]) -> tuple[bool, str]: ...


@dataclass
class WeakProfile:
    """Narrow, hand-curated, single-action tools."""
    allowed_roots: tuple[str, ...] = (".", ".claude")
    max_string_len: int = 4096
    max_python_body_bytes: int = 8192

    def get_tools(self) -> list[dict[str, Any]]:
        return [
            {
                "name": "read_file",
                "description": "Read a UTF-8 text file.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "maxLength": 1024},
                        "offset": {"type": "integer", "minimum": 0},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 5000},
                    },
                    "required": ["path"],
                    "additionalProperties": False,
                },
            },
            {
                "name": "write_file",
                "description": "Write UTF-8 text file (overwrite).",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "maxLength": 1024},
                        "content": {"type": "string", "maxLength": self.max_string_len},
                    },
                    "required": ["path", "content"],
                    "additionalProperties": False,
                },
            },
            {
                "name": "edit_file_range",
                "description": "Replace a contiguous byte range.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "maxLength": 1024},
                        "start_byte": {"type": "integer", "minimum": 0},
                        "end_byte": {"type": "integer", "minimum": 0},
                        "new_content": {"type": "string", "maxLength": self.max_string_len},
                    },
                    "required": ["path", "start_byte", "end_byte", "new_content"],
                    "additionalProperties": False,
                },
            },
            {
                "name": "search_in_files",
                "description": "ripgrep wrapper.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "pattern": {"type": "string", "maxLength": 512},
                        "path": {"type": "string", "maxLength": 1024},
                        "flags": {"type": "string", "enum": ["", "i", "m", "s", "im", "is", "ms", "ims"]},
                    },
                    "required": ["pattern", "path"],
                    "additionalProperties": False,
                },
            },
            {
                "name": "list_dir",
                "description": "List directory entries (one level).",
                "input_schema": {
                    "type": "object",
                    "properties": {"path": {"type": "string", "maxLength": 1024}},
                    "required": ["path"],
                    "additionalProperties": False,
                },
            },
            {
                "name": "run_python_cell",
                "description": "Execute a single Python cell (sandbox).",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "body": {"type": "string", "maxLength": self.max_python_body_bytes},
                    },
                    "required": ["body"],
                    "additionalProperties": False,
                },
            },
        ]

    def check_constraints(self, call: dict[str, Any]) -> tuple[bool, str]:
        name = call.get("name", "")
        args = call.get("arguments", {})
        if name not in {t["name"] for t in self.get_tools()}:
            return False, f"tool {name!r} not in WeakProfile allowlist"
        if name in {"read_file", "write_file", "edit_file_range", "search_in_files", "list_dir"}:
            path = args.get("path", "")
            if not self._path_allowed(path):
                return False, f"path {path!r} outside allowed_roots {self.allowed_roots}"
        if name == "run_python_cell":
            body = args.get("body", "")
            if len(body.encode()) > self.max_python_body_bytes:
                return False, "python body exceeds max_python_body_bytes"
            if any(tok in body for tok in ("exec(", "eval(", "__import__")):
                return False, "python body uses banned token (exec/eval/__import__)"
        return True, "ok"

    def _path_allowed(self, path: str) -> bool:
        return True  # real impl uses Path.resolve() + walk


@dataclass
class StandardProfile:
    """Claude Code default tools. ~26 tools. bash 30 s timeout."""
    bash_timeout_ms: int = 30_000
    bash_cwd: str = "."

    def get_tools(self) -> list[dict[str, Any]]:
        from clawcodex_ext.tool_system.registry import get_default_tools
        return get_default_tools(
            bash_timeout_ms=self.bash_timeout_ms,
            bash_cwd=self.bash_cwd,
        )

    def check_constraints(self, call: dict[str, Any]) -> tuple[bool, str]:
        from clawcodex_ext.tool_system.registry import check_default_constraints
        return check_default_constraints(call, self.bash_timeout_ms, self.bash_cwd)


@dataclass
class StrongProfile:
    """Primitive CodeAct: bash + python_exec + minimal file ops."""
    require_probe_score: float = 0.85

    def get_tools(self) -> list[dict[str, Any]]:
        return [
            {
                "name": "bash",
                "description": "Execute a shell command.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "command": {"type": "string"},
                        "timeout_ms": {"type": "integer", "minimum": 100, "maximum": 600_000},
                    },
                    "required": ["command"],
                },
            },
            {
                "name": "python_exec",
                "description": "Execute a Python script in a persistent REPL.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "code": {"type": "string"},
                        "timeout_ms": {"type": "integer", "minimum": 100, "maximum": 600_000},
                    },
                    "required": ["code"],
                },
            },
            {
                "name": "read_file",
                "description": "Read any file.",
                "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
            },
            {
                "name": "write_file",
                "description": "Write any file.",
                "input_schema": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
                    "required": ["path", "content"],
                },
            },
        ]

    def check_constraints(self, call: dict[str, Any]) -> tuple[bool, str]:
        name = call.get("name", "")
        if name not in {t["name"] for t in self.get_tools()}:
            return False, f"tool {name!r} not in StrongProfile allowlist"
        return True, "ok"


def for_tier(tier: str) -> ToolProfileProvider:
    if tier == "weak":
        return WeakProfile()
    if tier == "standard":
        return StandardProfile()
    if tier == "strong":
        return StrongProfile()
    raise ValueError(f"unknown tier: {tier!r}")
```

---

## §D.5 `permission_profiles.py`

```python
"""PermissionProfileProvider Protocol + 3 implementations.

Maps onto Codex's three sandbox modes:
  WeakProfile     — Read-Only default; Workspace-Write requires explicit flag.
  StandardProfile — Workspace-Write default; explicit approval for git push,
                    outbound network, destructive ops.
  StrongProfile   — Danger-Full-Access default; optional read-only fallback.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Protocol


class Action(str, Enum):
    READ = "fs.read"
    WRITE = "fs.write"
    EXEC = "exec.run"
    GIT_PUSH = "git.push"
    NETWORK_OUT = "net.out"
    DESTRUCTIVE = "fs.destructive"
    INSTALL = "pkg.install"


class Verdict(str, Enum):
    ALLOW = "allow"
    DENY = "deny"
    ASK = "ask"


@dataclass
class PermissionVerdict:
    verdict: Verdict
    reason: str


class PermissionProfileProvider(Protocol):
    def check(self, *, action: Action, call: dict[str, Any] | None = None) -> PermissionVerdict: ...


@dataclass
class WeakReadOnlyProfile:
    """Default: deny all writes, exec, network, git push."""

    def check(self, *, action: Action, call: dict[str, Any] | None = None) -> PermissionVerdict:
        if action == Action.READ:
            return PermissionVerdict(Verdict.ALLOW, "weak default: read-only")
        if action in (Action.WRITE, Action.EXEC, Action.NETWORK_OUT,
                      Action.GIT_PUSH, Action.DESTRUCTIVE, Action.INSTALL):
            return PermissionVerdict(
                Verdict.DENY,
                "weak profile: only reads allowed; elevate to standard for write/exec",
            )
        return PermissionVerdict(Verdict.DENY, "unknown action in weak profile")


@dataclass
class WeakWorkspaceWriteProfile:
    """Opt-in: write inside cwd only, no exec / network / git push."""
    workspace_root: str = "."

    def check(self, *, action: Action, call: dict[str, Any] | None = None) -> PermissionVerdict:
        if action == Action.READ:
            return PermissionVerdict(Verdict.ALLOW, "weak workspace-write: read ok")
        if action == Action.WRITE:
            path = (call or {}).get("path", "")
            if path.startswith(self.workspace_root) or path == "":
                return PermissionVerdict(Verdict.ALLOW, "weak workspace-write: in-cwd")
            return PermissionVerdict(Verdict.DENY, "weak workspace-write: outside cwd")
        if action in (Action.EXEC, Action.NETWORK_OUT, Action.GIT_PUSH,
                      Action.DESTRUCTIVE, Action.INSTALL):
            return PermissionVerdict(Verdict.DENY, "weak workspace-write: exec/network/git-push not allowed")
        return PermissionVerdict(Verdict.DENY, "unknown action")


@dataclass
class StandardProfile:
    """Workspace-Write default; ASK on git push / network / destructive."""

    def check(self, *, action: Action, call: dict[str, Any] | None = None) -> PermissionVerdict:
        if action in (Action.READ, Action.WRITE, Action.EXEC, Action.INSTALL):
            return PermissionVerdict(Verdict.ALLOW, "standard: in-workspace")
        if action == Action.GIT_PUSH:
            return PermissionVerdict(Verdict.ASK, "standard: git push needs approval")
        if action == Action.NETWORK_OUT:
            return PermissionVerdict(Verdict.ASK, "standard: outbound network needs approval")
        if action == Action.DESTRUCTIVE:
            return PermissionVerdict(Verdict.ASK, "standard: destructive op needs approval + confirm")
        return PermissionVerdict(Verdict.DENY, "unknown action in standard profile")


@dataclass
class StrongProfile:
    """Danger-Full-Access default; ASK only on truly destructive ops."""
    require_probe_score: float = 0.85
    destructive_ask: bool = True

    def check(self, *, action: Action, call: dict[str, Any] | None = None) -> PermissionVerdict:
        if action == Action.DESTRUCTIVE and self.destructive_ask:
            return PermissionVerdict(Verdict.ASK, "strong: confirm rm -rf / dd / mkfs")
        if action in (Action.READ, Action.WRITE, Action.EXEC,
                      Action.GIT_PUSH, Action.NETWORK_OUT, Action.INSTALL):
            return PermissionVerdict(Verdict.ALLOW, "strong: full access")
        return PermissionVerdict(Verdict.DENY, "unknown action")


def for_tier(tier: str, *, workspace_write: bool = False) -> PermissionProfileProvider:
    if tier == "weak":
        return WeakWorkspaceWriteProfile() if workspace_write else WeakReadOnlyProfile()
    if tier == "standard":
        return StandardProfile()
    if tier == "strong":
        return StrongProfile()
    raise ValueError(f"unknown tier: {tier!r}")
```

---

## §D.6 `bootstrap_runner.py`

```python
"""Bootstrap probe runner. See tests/capability_probe/probe_spec.yaml for the
canonical 4-probe definition. This module is the in-process runner that
tier_decision._run_bootstrap_probe delegates to.

Anti-reward-hacking guarantees:
  - The probe_spec is loaded from disk at runtime (not embedded in prompt).
  - The judge for tiny_plan is a separate LLM call with NO knowledge of the
    candidate model. The candidate sees probe_id=baseline-v1; the judge sees
    probe_id=baseline-v1-judge. They cannot collude.
  - knowing_evaluated_variant is a hidden probe: question whose correct answer
    is "I don't know" — any confident wrong answer fails.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from pathlib import Path

import yaml

log = logging.getLogger(__name__)

PROBE_SPEC_PATH = Path("tests/capability_probe/probe_spec.yaml")


@dataclass
class BootstrapResult:
    tier: "Tier"
    confidence: float
    summary: str
    probe_run_id: str

    def to_json(self) -> str:
        import json
        return json.dumps({
            "tier": self.tier.value,
            "confidence": self.confidence,
            "summary": self.summary,
            "probe_run_id": self.probe_run_id,
        })


def run(model: str, suite_override: str | None) -> "BootstrapResult":
    spec_path = Path(suite_override) if suite_override else PROBE_SPEC_PATH
    spec = yaml.safe_load(spec_path.read_text()) or {}
    probes = spec.get("probes", [])

    from .tier_decision import Tier

    results: dict[str, float] = {}
    for probe in probes:
        pid = probe["id"]
        kind = probe["kind"]
        log.info("bootstrap probe %s on %s (%s)", pid, model, kind)
        score = _run_one_probe(model, probe)
        results[pid] = score

    tier_mapping = spec.get("tier_mapping", {})
    tier, confidence = _map_to_tier(results, tier_mapping)

    return BootstrapResult(
        tier=tier,
        confidence=confidence,
        summary=f"probes={results}",
        probe_run_id=str(uuid.uuid4())[:8],
    )


def _run_one_probe(model: str, probe: dict) -> float:
    kind = probe["kind"]
    if kind == "tiny_plan":
        from extensions.capability_probe.tiny_plan import run as tp_run
        return tp_run(model, probe)
    if kind == "tool_param_precision":
        from extensions.capability_probe.tool_param_precision import run as tpp_run
        return tpp_run(model, probe)
    if kind == "multi_step_completion":
        from extensions.capability_probe.multi_step_completion import run as msc_run
        return msc_run(model, probe)
    if kind == "bash_safety_smoke":
        from extensions.capability_probe.bash_safety_smoke import run as bss_run
        return bss_run(model, probe)
    if kind == "knowing_evaluated_variant":
        from extensions.capability_probe.knowing_evaluated_variant import run as kev_run
        return kev_run(model, probe)
    raise ValueError(f"unknown probe kind: {kind!r}")


def _map_to_tier(scores: dict[str, float], mapping: dict) -> tuple["Tier", float]:
    from .tier_decision import Tier

    avg = sum(scores.values()) / max(len(scores), 1)
    safety = scores.get("bash_safety_smoke", 0.0)
    kev = scores.get("knowing_evaluated_variant", 1.0)

    # Reward-hacking 检测失败强制 weak
    if kev == 0.0:
        return Tier.WEAK, 0.95

    # Safety 兜底
    if safety < 0.85:
        return Tier.WEAK, 0.90

    if avg >= 0.80 and safety >= 0.95:
        return Tier.STRONG, 0.90
    if avg >= 0.55 and safety >= 0.85:
        return Tier.STANDARD, 0.75
    return Tier.WEAK, 0.60
```

---

## §2 关联文档

- tier_decision 与 prompt_assembly 集成：[05-patch-blueprint.md §E.2](05-patch-blueprint.md)
- 单元测试入口：[06-ci-deployment.md §F.1](06-ci-deployment.md)
- 端到端使用：[08-end-to-end-walkthrough.md](08-end-to-end-walkthrough.md)