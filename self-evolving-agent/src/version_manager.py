"""Version manager: handles configuration versioning and proposal application."""

from __future__ import annotations

import os
import copy
import json
import shutil
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from src.models import (
    OptimizationProposal,
    ProposalStatus,
    ProposalType,
    VersionSnapshot,
    dataclass_to_dict,
)
from src.skill_creator import SkillCreator, is_skill_duplicate
from src.utils import load_available_skills
from src.utils import read_json, write_json, setup_logger

logger = setup_logger("version_manager")


class VersionManager:
    """Manages versioned snapshots of the agent configuration."""

    def __init__(self, storage_path: str, cx_root: str = None) -> None:
        self.storage_path = storage_path
        self.current_version: Optional[str] = None
        self._version_counter = 0
        self._skill_creator = SkillCreator()
        import os as _os
        self._cx_root = cx_root or _os.path.normpath(
            _os.path.join(_os.path.dirname(__file__), "..", "..")
        )
        self.PROMPTS_DIR = _os.path.normpath(
            _os.path.join(_os.path.dirname(__file__), "..", "config", "prompts")
        )

    def create_snapshot(self, config: Dict[str, Any], description: str = "") -> str:
        """Snapshot the current configuration and return a version string."""
        self._version_counter += 1
        date_part = datetime.now(timezone.utc).strftime("%Y%m%d")
        version = f"v{date_part}-{self._version_counter:04d}"

        snapshot = VersionSnapshot(
            version=version,
            parent_version=self.current_version or "",
            config=copy.deepcopy(config),
            description=description,
        )
        self._save_snapshot(snapshot)
        self.current_version = version
        return version

    def apply_proposal(self, proposal: OptimizationProposal) -> str:
        """Apply a proposal to create a new version.

        Reads the current config, modifies the relevant component,
        snapshots, and returns the new version string.
        """
        current_config = self._load_current_config()

        if proposal.proposal_type == ProposalType.PROMPT_OPTIMIZATION:
            self._modify_prompt(current_config, proposal.target, proposal.proposed_content)

        elif proposal.proposal_type == ProposalType.SKILL_ADDITION:
            self._add_skill(current_config, proposal.target, proposal.proposed_content)

        elif proposal.proposal_type == ProposalType.SKILL_MODIFICATION:
            self._modify_skill(current_config, proposal.target, proposal.proposed_content)

        elif proposal.proposal_type == ProposalType.CONFIG_ADJUSTMENT:
            self._modify_config_value(current_config, proposal.target, proposal.proposed_content)

        elif proposal.proposal_type == ProposalType.WORKFLOW_OPTIMIZATION:
            self._apply_workflow_change(current_config, proposal.proposed_content)

        elif proposal.proposal_type == ProposalType.PLUGIN_GENERATION:
            self._install_plugin(proposal)

        current_config["_version"] = self._next_version()
        new_version = self.create_snapshot(
            current_config,
            description=f"Applied: {proposal.proposal_type.value} - {proposal.target}"
        )
        proposal.status = ProposalStatus.DEPLOYED
        self._save_proposal(proposal)
        logger.info("Proposal %s applied → version %s", proposal.proposal_id, new_version)
        return new_version

    def rollback(self, target_version: str) -> bool:
        """Roll back to a specific version."""
        snapshot = self._load_snapshot(target_version)
        if snapshot is None:
            logger.warning("Version %s not found for rollback; skipping.", target_version)
            return True  # non-fatal: no snapshot to restore

        self._write_current_config(snapshot.config)
        self.current_version = target_version
        # Clean up plugin files if rolling back a plugin-related version
        self._cleanup_plugins_in_version(target_version)
        logger.info("Rolled back to version %s", target_version)
        return True

    def set_current_version(self, version: str) -> None:
        """Set the active version pointer without modifying config files."""
        self.current_version = version
        logger.info("Current version set to %s", version)

    def get_current_config(self) -> Dict[str, Any]:
        """Load and return the current configuration."""
        return self._load_current_config()

    def list_versions(self) -> List[str]:
        """List all stored version strings."""
        if not os.path.isdir(self.storage_path):
            return []
        versions = []
        for f in os.listdir(self.storage_path):
            if f.startswith("v") and f.endswith(".json"):
                versions.append(f.replace(".json", ""))
        return sorted(versions)

    # ── Private helpers ──────────────────────────────────────────────────

    def _cleanup_plugins_in_version(self, version: str) -> None:
        """Remove plugin files that were added in the rolled-back version."""
        snap = self._load_snapshot(version)
        if snap is None:
            return
        plugins_dir = self._plugins_dir()
        from src.utils import read_text
        for desc in snap.applied_proposals:
            if "recovery_strategy:" in desc or "loop_hook:" in desc:
                name = desc.replace(":", "_").replace("/", "_")
                file_path = os.path.join(plugins_dir, f"{name}.py")
                if os.path.isfile(file_path):
                    os.remove(file_path)
                    logger.info("Cleaned up plugin file: %s", file_path)

    def _next_version(self) -> str:
        return datetime.now(timezone.utc).strftime("v%Y%m%d-%H%M%S")

    def _save_snapshot(self, snapshot: VersionSnapshot) -> str:
        path = os.path.join(self.storage_path, f"{snapshot.version}.json")
        write_json(path, dataclass_to_dict(snapshot))
        return path

    def _load_snapshot(self, version: str) -> Optional[VersionSnapshot]:
        path = os.path.join(self.storage_path, f"{version}.json")
        data = read_json(path)
        if data is None:
            return None
        return VersionSnapshot(**data)

    def _load_current_config(self) -> Dict[str, Any]:
        if self.current_version:
            snap = self._load_snapshot(self.current_version)
            if snap:
                return copy.deepcopy(snap.config)
        return {}

    def _write_current_config(self, config: Dict[str, Any]) -> None:
        curr = self.current_version
        if curr:
            snap = self._load_snapshot(curr)
            if snap:
                snap.config = config
                self._save_snapshot(snap)

    def _save_proposal(self, proposal: OptimizationProposal) -> None:
        path = os.path.join(self.storage_path, f"proposal_{proposal.proposal_id}.json")
        write_json(path, dataclass_to_dict(proposal))

    @staticmethod
    def _plugins_dir(self) -> str:
        """Return the absolute path to the ClawCodex plugins directory."""
        return os.path.normpath(
            os.path.join(self._cx_root, "clawcodex_ext", "query", "plugins")
        )

    def _install_plugin(self, proposal: OptimizationProposal) -> bool:
        """Write generated plugin code to the plugins directory."""
        name = proposal.target.replace(":", "_").replace("/", "_")
        if not name or not proposal.proposed_content.strip():
            return False
        plugins_dir = self._plugins_dir()
        os.makedirs(plugins_dir, exist_ok=True)
        file_path = os.path.join(plugins_dir, f"{name}.py")
        from src.utils import write_text
        write_text(file_path, proposal.proposed_content)
        logger.info("Installed plugin: %s -> %s", name, file_path)
        return True

    def _modify_prompt(self, config: Dict, target: str, new_content: str) -> None:
        if "prompts" not in config:
            config["prompts"] = {}
        config["prompts"][target] = new_content
        
        # AST-guided surgical replace in prompt_assembly.py for ClawCodex sections
        from src.utils import replace_prompt_section_in_file
        try:
            replaced = replace_prompt_section_in_file(new_content, target)
            if replaced:
                logger.info("Surgically replaced section '%s' in prompt_assembly.py", target)
        except Exception as e:
            logger.warning("Failed to replace section '%s' in prompt_assembly.py: %s", target, e)
        
        # Legacy: .md file write for self-evolving-agent prompt templates
        if target.endswith(".md"):
            file_path = os.path.join(self.PROMPTS_DIR, target)
            if os.path.isfile(file_path):
                logger.info("Writing modified prompt to %s", file_path)
                from src.utils import write_text
                write_text(file_path, new_content)
            else:
                logger.warning("Prompt file not found at %s", file_path)

    def _add_skill(self, config: Dict, target: str, content: str) -> None:
        """Add a new skill via SkillCreator, then register in config."""
        # Try to parse structured JSON; fall back to plain-text storage
        try:
            params = json.loads(content)
        except (json.JSONDecodeError, TypeError):
            params = {"name": target, "summary": content, "sop": [], "pitfalls": []}

        # Check if skill already exists (safety net)
        dup, match = is_skill_duplicate(params, load_available_skills())
        if dup:
            logger.info("Skipping creation of redundant skill '%s' (similar to '%s')", target, match)
            config["skills"] = config.get("skills", {})
            config["skills"][target] = {"source": "auto_generated", "status": "skipped_duplicate"}
            return
        success, msg = self._skill_creator.create_skill(params)
        if not success:
            logger.warning("Skill creation had issues: %s", msg)

        if "skills" not in config:
            config["skills"] = {}
        config["skills"][target] = {"source": "auto_generated", "status": "registered" if success else "failed"}

    @staticmethod
    def _modify_skill(config: Dict, target: str, content: str) -> None:
        if "skills" not in config:
            config["skills"] = {}
        config["skills"][target] = content

    @staticmethod
    def _modify_config_value(config: Dict, target: str, content: str) -> None:
        config[target] = content

    @staticmethod
    def _apply_workflow_change(config: Dict, content: str) -> None:
        config["workflow_modifications"] = config.get("workflow_modifications", []) + [content]
