"""Facade — src/skills/bundled/ has been moved to clawcodex_ext/skills/bundled.

Re-exports the public API so existing
``from src.skills.bundled import ...`` callers keep working.
"""

from clawcodex_ext.skills.bundled import (  # noqa: F401
    init_bundled_skills,
    register_debug_skill,
    register_loop_skill,
    register_orchestrator_skill,
    register_simplify_skill,
    register_spec_audit_skill,
    register_stuck_skill,
    register_verify_content_skill,
    reset_bundled_skills_init_flag,
)
