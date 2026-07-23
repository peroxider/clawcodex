"""SkillGrouper — groups atomic tools into business-level Skills.

Uses LLM-assisted grouping to cluster related tools by business logic.
Falls back to static rules (from MappingRule config) when LLM is unavailable.
KEYWORD_MATCH strategy: MappingRule pattern matching with catch-all ``sdk_utility``.
IO_RELATION strategy: type-anchor clustering with anchor-set-intersection
    grouping, smallest-first merge, and ClassName.methodName / compName.methodName
    tool naming.
LLM_SEMANTIC strategy: LLM-driven semantic clustering with JSON output parsing,
    validation, and KEYWORD_MATCH fallback.
"""

from __future__ import annotations

import json
import logging
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, TYPE_CHECKING

from ..core.sdk_parser import SdkMethod, SdkParser
from enum import Enum
from ..core.source_parser import SourceComponent, SourceOperation

if TYPE_CHECKING:
    from extensions.capabilities.sop_provider_protocol import SOPAssistantProviderProtocol

logger = logging.getLogger(__name__)


class GroupStrategy(Enum):
    KEYWORD_MATCH = "keyword_match"
    COMPONENT_GROUP = "component_group"
    IO_RELATION = "io_relation"
    LLM_SEMANTIC = "llm_semantic"


class MatchType(Enum):
    SUBSTRING = "substring"
    PREFIX = "prefix"
    SUFFIX = "suffix"
    REGEX = "regex"
    EXACT = "exact"


class MatchTarget(Enum):
    """Which field a MappingRule pattern is matched against."""

    OP_NAME = "op_name"  # method / operation name  (default, backward-compatible)
    COMP_NAME = "comp_name"  # SourceComponent name (directory name)
    FILE_PATH = "file_path"  # SourceComponent file_path


@dataclass
class SkillSpec:
    """Specification for a Skill derived from grouped SDK methods."""

    name: str
    description: str
    allowed_tools: list[str] = field(default_factory=list)
    argument_names: list[str] = field(default_factory=list)
    when_to_use: str | None = None
    version: str | None = None
    model: str | None = None


@dataclass
class MappingRule:
    """A mapping rule: SDK method pattern → tool name → skill name.

    match_type controls how method_pattern is applied:
      - SUBSTRING (default): pattern must appear anywhere in the name
      - PREFIX: name must start with the pattern
      - SUFFIX: name must end with the pattern
      - REGEX: pattern is a regular expression
      - EXACT: name must equal the pattern exactly

    match_target controls which field the pattern is tested against:
      - OP_NAME (default): match against method/operation name
      - COMP_NAME: match against SourceComponent name (directory name)
      - FILE_PATH: match against SourceComponent file_path
    """

    method_pattern: str
    tool_name: str
    skill_name: str
    description: str = ""
    match_type: MatchType = MatchType.SUBSTRING
    match_target: MatchTarget = MatchTarget.OP_NAME

    def matches(self, name: str) -> bool:
        if self.match_type == MatchType.SUBSTRING:
            return self.method_pattern in name
        elif self.match_type == MatchType.PREFIX:
            return name.startswith(self.method_pattern)
        elif self.match_type == MatchType.SUFFIX:
            return name.endswith(self.method_pattern)
        elif self.match_type == MatchType.REGEX:
            return bool(re.search(self.method_pattern, name))
        elif self.match_type == MatchType.EXACT:
            return name == self.method_pattern
        return False

    def match_against(self, op_name: str, comp_name: str, file_path: str) -> bool:
        """Match against the field selected by match_target."""
        if self.match_target == MatchTarget.COMP_NAME:
            return self.matches(comp_name)
        elif self.match_target == MatchTarget.FILE_PATH:
            return self.matches(file_path)
        else:
            return self.matches(op_name)


DEFAULT_MAPPING_RULES: list[MappingRule] = [
    MappingRule(
        "docker_", "docker_ops", "build_image", "Build and push Docker images", MatchType.PREFIX
    ),
    MappingRule("docker_build", "docker_build", "build_image", "Build Docker image"),
    MappingRule("docker_tag", "docker_tag", "build_image", "Tag Docker image"),
    MappingRule("docker_push", "docker_push", "build_image", "Push Docker image"),
    MappingRule(
        "k8s_", "k8s_ops", "deploy_service", "Kubernetes deployment operations", MatchType.PREFIX
    ),
    MappingRule("k8s_apply", "k8s_apply", "deploy_service", "Apply Kubernetes manifest"),
    MappingRule("k8s_delete", "k8s_delete", "deploy_service", "Delete Kubernetes resource"),
    MappingRule("k8s_get", "k8s_get", "deploy_service", "Get Kubernetes resource"),
    MappingRule("health_check", "health_check", "deploy_service", "Check service health"),
    MappingRule("rollback", "rollback", "deploy_service", "Rollback deployment"),
    MappingRule(
        "slack_", "slack_ops", "notify_team", "Slack notification operations", MatchType.PREFIX
    ),
    MappingRule("slack_send", "slack_send", "notify_team", "Send Slack notification"),
    MappingRule(
        "email_", "email_ops", "notify_team", "Email notification operations", MatchType.PREFIX
    ),
    MappingRule("email_send", "email_send", "notify_team", "Send email notification"),
    MappingRule("s3_", "s3_ops", "upload_artifact", "S3 artifact operations", MatchType.PREFIX),
    MappingRule("s3_upload", "s3_upload", "upload_artifact", "Upload to S3"),
    MappingRule("s3_download", "s3_download", "upload_artifact", "Download from S3"),
    MappingRule("spark_", "spark_ops", "run_spark", "Spark job operations", MatchType.PREFIX),
    MappingRule("spark_submit", "spark_submit", "run_spark", "Submit Spark job"),
]


def _extract_prefixes(tool_names: list[str]) -> set[str]:
    """Extract component-name prefixes from qualified tool names.

    ``comp_name.method_name`` → ``{comp_name}``
    Used by Phase 3 merge to compute Jaccard similarity between Skills.
    """
    prefixes: set[str] = set()
    for name in tool_names:
        if "." in name:
            prefixes.add(name.split(".")[0])
        else:
            prefixes.add(name)
    return prefixes


def _best_distinguishing_pattern(
    sub_keys: list[str],
    other_segments: set[str],
) -> str:
    """Find the most distinguishing path segment from a group's sub_keys.

    Prefers deeper segments (more specific) that are NOT in other groups.
    Returns the segment string, or the last segment as fallback.
    Used by ``SkillGrouper._auto_generate_rules``.
    """
    best_pattern = ""
    best_score = -1
    seen: set[str] = set()
    for sk in sub_keys:
        segs = [s for s in sk.split("/") if s]
        for i, seg in enumerate(segs):
            if seg in seen:
                continue
            seen.add(seg)
            depth_score = i  # deeper = higher score
            unique_bonus = 10 if seg not in other_segments else 0
            score = depth_score + unique_bonus
            if score > best_score:
                best_score = score
                best_pattern = seg
    if not best_pattern:
        segs = [s for s in sub_keys[0].split("/") if s]
        best_pattern = segs[-1] if segs else "misc"
    return best_pattern


def _common_ancestor_segment(sub_keys: list[str], other_segments: set[str]) -> str | None:
    """Find the longest common ancestor path segment shared by all sub_keys.

    For merged groups, the common ancestor represents the semantic theme
    (e.g. all sub_keys under ``examples/`` share ``examples``), which is
    a better skill_name than picking one sub_key's unique leaf segment.

    Returns the **deepest** segment that appears in every sub_key AND is
    not present in other_segments (i.e. it distinguishes this merged group
    from other groups).  Returns None when no such segment exists.
    """
    if not sub_keys:
        return None

    all_seg_sets: list[set[str]] = []
    for sk in sub_keys:
        all_seg_sets.append({s for s in sk.split("/") if s})

    common = all_seg_sets[0]
    for s in all_seg_sets[1:]:
        common = common & s

    common_not_in_others = {seg for seg in common if seg not in other_segments}

    if common_not_in_others:
        # Return the deepest common segment not shared with other groups.
        # Depth = index in the longest sub_key's segment list.
        best_seg = None
        best_depth = -1
        ref_segs = [s for s in max(sub_keys, key=lambda k: len(k.split("/"))).split("/") if s]
        for seg in common_not_in_others:
            depth = ref_segs.index(seg) if seg in ref_segs else 0
            if depth > best_depth:
                best_depth = depth
                best_seg = seg
        return best_seg

    # All common segments are shared with other groups — fallback to
    # the deepest common segment (it's still the semantic theme, even
    # if not unique).  The pattern rules will use per-sub-key patterns
    # for matching, so the skill_name doesn't need to be unique.
    if common:
        ref_segs = [s for s in max(sub_keys, key=lambda k: len(k.split("/"))).split("/") if s]
        best_seg = None
        best_depth = -1
        for seg in common:
            depth = ref_segs.index(seg) if seg in ref_segs else 0
            if depth > best_depth:
                best_depth = depth
                best_seg = seg
        return best_seg

    return None


@dataclass
class SkillGrouper:
    """Group atomic SDK methods into Skills based on business logic.

    Uses MappingRule config for static grouping when LLM is not available.
    The group method accepts a requirements hint that can be used by LLM
    to determine which tools belong together.
    """

    _DEFAULT_MAX_IO_GROUPS = 15

    def __init__(
        self,
        methods: list[SdkMethod],
        *,
        mapping_rules: list[MappingRule] | None = None,
        strategy: GroupStrategy | list[GroupStrategy] | None = None,
        source_components: list[SourceComponent] | None = None,
        max_io_groups: int | None = None,
        llm_provider: SOPAssistantProviderProtocol | None = None,
    ) -> None:
        self._methods = methods
        self._custom_rules = mapping_rules  # None = user didn't provide custom rules
        self._rules = mapping_rules or DEFAULT_MAPPING_RULES
        self._strategy = strategy
        self._source_components = source_components or []
        self._max_io_groups = max_io_groups or self._DEFAULT_MAX_IO_GROUPS
        self._llm_provider = llm_provider
        self._grouped: list[SkillSpec] | None = None

    def group(self, requirements: str = "") -> list[SkillSpec]:
        """Group methods into Skills.

        Args:
            requirements: Business requirements hint (e.g., "CI/CD pipeline",
                "data processing"). Passed to LLM when available for smarter
                grouping. Falls back to static MappingRule matching.
        """
        if self._grouped is not None:
            return self._grouped

        if self._strategy is None:
            self._grouped = self._static_group()
        elif isinstance(self._strategy, list):
            if GroupStrategy.COMPONENT_GROUP in self._strategy:
                self._grouped = self._component_group()
            elif GroupStrategy.KEYWORD_MATCH in self._strategy:
                if self._source_components:
                    self._maybe_auto_rules()
                    self._grouped = self._keyword_match_group()
                else:
                    self._grouped = self._static_group()
            elif GroupStrategy.IO_RELATION in self._strategy:
                self._grouped = self._io_relation_group()
            else:
                self._grouped = self._static_group()
        elif self._strategy == GroupStrategy.KEYWORD_MATCH:
            if self._source_components:
                self._maybe_auto_rules()
                self._grouped = self._keyword_match_group()
            else:
                self._grouped = self._static_group()
        elif self._strategy == GroupStrategy.COMPONENT_GROUP:
            self._grouped = self._component_group()
        elif self._strategy == GroupStrategy.IO_RELATION:
            self._grouped = self._io_relation_group()
        elif self._strategy == GroupStrategy.LLM_SEMANTIC:
            self._grouped = self._group_with_llm(requirements)
        else:
            self._grouped = self._static_group()

        return self._grouped

    def _static_group(self) -> list[SkillSpec]:
        """Group tools using static MappingRule patterns."""
        skill_map: dict[str, SkillSpec] = {}
        unmatched: list[SdkMethod] = []

        for method in self._methods:
            matched = False
            for rule in self._rules:
                if rule.method_pattern in method.name:
                    if rule.skill_name not in skill_map:
                        skill_map[rule.skill_name] = SkillSpec(
                            name=rule.skill_name,
                            description=rule.description or f"Skill: {rule.skill_name}",
                            allowed_tools=[],
                        )
                    skill = skill_map[rule.skill_name]
                    if method.name not in skill.allowed_tools:
                        skill.allowed_tools.append(method.name)
                    if method.parameters:
                        skill.argument_names.extend(method.parameters)
                    matched = True
                    break
            if not matched:
                unmatched.append(method)

        # Put unmatched tools in a default skill
        if unmatched:
            skill_map["_unmatched"] = SkillSpec(
                name="sdk_utility",
                description="SDK utility methods",
                allowed_tools=[m.name for m in unmatched],
                argument_names=[],
            )

        return list(skill_map.values())

    def _maybe_auto_rules(self) -> None:
        """If no custom mapping rules were provided, auto-generate from directory structure.

        Only applies to KEYWORD_MATCH + SourceComponent path.
        Does NOT affect _static_group (SdkMethod path) or other strategies.
        """
        if self._custom_rules is not None:
            return  # User provided custom rules — respect them.
        auto = self._auto_generate_rules(self._source_components, self._max_io_groups)
        if auto:
            self._rules = auto

    @staticmethod
    def _auto_generate_rules(
        components: list[SourceComponent],
        max_groups: int = 15,
    ) -> list[MappingRule]:
        """Auto-generate MappingRules from directory structure of SourceComponents.

        Algorithm — path prefix tree cutting:
          1. Collect all file_paths, split into segments by OS separator.
          2. At each depth d, group components by their path prefix of d
             segments.  Pick the depth whose group count is **closest to**
             max_groups (preferring slightly over if equidistant), so that
             we get the finest-grained grouping that still fits the budget.
          3. When a depth yields more groups than max_groups, merge smallest
             groups by path-segment Jaccard similarity until ≤ max_groups.
          4. For each final group, use the **distinguishing path segment**
             (the deepest segment that is unique to this group) as the
             method_pattern for a FILE_PATH / SUBSTRING rule.

        This is only used when strategy=KEYWORD_MATCH, source_components is
        non-empty, and no custom ``--mapping-rules`` were provided.  The
        SdkMethod path (``_static_group``) is completely unaffected.
        """
        if not components:
            return []

        # ── Step 1: collect path segments per component ──
        # Normalize separators to '/' for consistent processing.
        comp_paths: list[tuple[str, list[str]]] = []  # (comp_name, segments)
        for comp in components:
            fp = comp.file_path.replace("\\", "/")
            # Remove the final .py filename — we only care about directories.
            if fp.endswith(".py"):
                fp = fp.rsplit("/", 1)[0] if "/" in fp else ""
            segments = [s for s in fp.split("/") if s]
            comp_paths.append((comp.name, segments))

        if not any(segs for _, segs in comp_paths):
            # No meaningful path structure — cannot auto-generate.
            return []

        # ── Step 2: find the best cut depth ──
        # Strategy: pick the **shallowest depth whose group count ≥ max_groups**.
        # This gives the finest-grained grouping that can be merged down to
        # exactly max_groups.  If no depth reaches max_groups, use the deepest
        # depth available.
        max_depth = max((len(segs) for _, segs in comp_paths), default=0)

        best_depth = 1
        best_count_at_depth = 0
        # First pass: find the shallowest depth with count >= max_groups.
        for d in range(1, max_depth + 1):
            groups_d: dict[str, list[str]] = {}
            for comp_name, segs in comp_paths:
                prefix_key = "/".join(segs[:d]) if len(segs) >= d else "/".join(segs)
                groups_d.setdefault(prefix_key, []).append(comp_name)
            count = len(groups_d)
            if count >= max_groups:
                best_depth = d
                best_count_at_depth = count
                break
            # Track the deepest depth with most groups as fallback.
            if count > best_count_at_depth:
                best_depth = d
                best_count_at_depth = count
            # Early exit: if group count starts declining, stop.
            if d > 2 and count < best_count_at_depth:
                break

        # ── Step 3: build groups at best_depth ──
        groups: dict[str, list[str]] = {}  # prefix_key → [comp_name, ...]
        for comp_name, segs in comp_paths:
            prefix_key = "/".join(segs[:best_depth]) if len(segs) >= best_depth else "/".join(segs)
            groups.setdefault(prefix_key, []).append(comp_name)

        # ── Step 4: merge smallest groups until ≤ max_groups ──
        while len(groups) > max_groups:
            keys = sorted(groups.keys(), key=lambda k: len(groups[k]))
            smallest_key = keys[0]
            # Find most similar neighbor by shared path segments.
            smallest_segs = set(smallest_key.split("/"))
            best_neighbor = keys[1]
            best_sim = -1.0
            for other_key in keys[1:]:
                other_segs = set(other_key.split("/"))
                inter = len(smallest_segs & other_segs)
                union = len(smallest_segs | other_segs)
                sim = inter / max(union, 1)
                if sim > best_sim:
                    best_sim = sim
                    best_neighbor = other_key
            # Merge smallest into neighbor.
            merged_key = f"{smallest_key}|{best_neighbor}"
            groups[merged_key] = groups.pop(smallest_key) + groups.pop(best_neighbor)

        # ── Step 5: generate MappingRule(s) per group ──
        # For each group, find the most **distinguishing** path segment —
        # the deepest segment in the prefix key that is unique to this group
        # (i.e. not shared with any other group).  This avoids overly broad
        # patterns like "core" that would match multiple groups.
        # For merged groups (containing multiple sub_keys), generate one rule
        # per sub_key so each sub-path gets its own discriminating pattern.
        all_group_keys = list(groups.keys())

        rules: list[MappingRule] = []
        for group_key in all_group_keys:
            sub_keys = group_key.split("|")

            # Collect all segments from OTHER groups for uniqueness check.
            other_segments: set[str] = set()
            for ok in all_group_keys:
                if ok != group_key:
                    for part in ok.split("|"):
                        other_segments.update(part.split("/"))

            if len(sub_keys) == 1:
                # Single-path group — find its best distinguishing pattern.
                best_pattern = _best_distinguishing_pattern(sub_keys, other_segments)
                skill_name = best_pattern.replace("-", "_").replace(" ", "_").lower()
                desc = f"Auto-grouped from path: {group_key}"
                rules.append(
                    MappingRule(
                        method_pattern=best_pattern,
                        tool_name="",
                        skill_name=skill_name,
                        description=desc,
                        match_type=MatchType.SUBSTRING,
                        match_target=MatchTarget.FILE_PATH,
                    )
                )
            else:
                # Merged group — generate one rule per sub_key, all pointing
                # to the same skill_name.
                #
                # Naming strategy:
                #   1. Prefer the **common ancestor segment** — the deepest
                #      path segment shared by ALL sub_keys.  This reflects
                #      the semantic theme (e.g. "examples" for a group of
                #      examples/xxx paths) rather than one leaf's unique tag.
                #   2. If no common ancestor exists, fall back to the most
                #      distinguishing segment of the deepest sub_key.
                ancestor = _common_ancestor_segment(sub_keys, other_segments)
                if ancestor:
                    skill_name = ancestor.replace("-", "_").replace(" ", "_").lower()
                else:
                    main_key = max(sub_keys, key=lambda k: len(k.split("/")))
                    fallback_pat = _best_distinguishing_pattern([main_key], other_segments)
                    skill_name = fallback_pat.replace("-", "_").replace(" ", "_").lower()

                used_names = {r.skill_name for r in rules}
                if skill_name in used_names:
                    segs = [s for s in sub_keys[0].split("/") if s]
                    skill_name = (
                        "_".join(segs[-2:]).replace("-", "_").replace(" ", "_").lower()
                        if len(segs) >= 2
                        else f"{skill_name}_2"
                    )

                # Tag merged groups so users can distinguish them from
                # single-path groups at a glance.
                skill_name = skill_name + "_merged"

                # Build shared description listing all merged paths.
                shared_desc = "Auto-grouped from paths: " + ", ".join(sub_keys)
                for sk in sub_keys:
                    pat = _best_distinguishing_pattern([sk], other_segments)
                    rules.append(
                        MappingRule(
                            method_pattern=pat,
                            tool_name="",
                            skill_name=skill_name,
                            description=shared_desc,
                            match_type=MatchType.SUBSTRING,
                            match_target=MatchTarget.FILE_PATH,
                        )
                    )

        # ── Step 6: sort rules — specific (unique) patterns first ──
        # This ensures first-match-wins favors the most discriminating rules.
        # Count how many groups each pattern could accidentally match.
        def _pattern_specificity(rule: MappingRule) -> int:
            """Lower = more specific (matches fewer groups)."""
            hits = 0
            for gk in all_group_keys:
                for sub in gk.split("|"):
                    if rule.method_pattern in sub:
                        hits += 1
                        break
            return hits

        rules.sort(key=_pattern_specificity)

        return rules

    def _keyword_match_group(self) -> list[SkillSpec]:
        """Group SourceComponent operations by MappingRule + auto prefix inference.

        Phase 1 — Explicit rule matching (first-match-wins, respects match_type
                  and match_target).  Rules with match_target=COMP_NAME or
                  FILE_PATH match against component-level fields, so all
                  operations in a matched component are grouped together.
        Phase 2 — Auto prefix inference for unmatched operations:
            a. Extract first underscore prefix (``video_encode`` → ``"video"``)
            b. Single-segment names (no underscore) → ``"utility"``
            c. Prefix groups with ≥ 2 members → ``"{prefix}_ops"`` Skill
            d. Prefix groups with 1 member → ``"misc"`` Skill
        Phase 3 — Merge smallest groups until count ≤ max_io_groups.
        """
        skill_map: dict[str, SkillSpec] = {}
        matched_keys: set[str] = set()  # "comp_name.op_name" to avoid duplicates

        if not self._source_components:
            return []

        # Build flat item list from SourceComponents, now including file_path.
        items: list[
            tuple[str, str, str, str, str | None]
        ] = []  # (op_name, desc, comp_name, file_path, class_name)
        for comp in self._source_components:
            for op in comp.operations:
                items.append((op.name, op.description, comp.name, comp.file_path, op.class_name))

        # Phase 1 — explicit MappingRule matching (MatchType + MatchTarget aware).
        for op_name, desc, comp_name, file_path, class_name in items:
            for rule in self._rules:
                if rule.match_against(op_name, comp_name, file_path):
                    if rule.skill_name not in skill_map:
                        skill_map[rule.skill_name] = SkillSpec(
                            name=rule.skill_name,
                            description=rule.description or f"Skill: {rule.skill_name}",
                            allowed_tools=[],
                        )
                    qualified = (
                        f"{comp_name}.{class_name}.{op_name}"
                        if class_name
                        else f"{comp_name}.{op_name}"
                    )
                    key = qualified
                    if qualified not in skill_map[rule.skill_name].allowed_tools:
                        skill_map[rule.skill_name].allowed_tools.append(qualified)
                    matched_keys.add(key)
                    break

        # Phase 2 — auto prefix inference for unmatched operations.
        unmatched = [
            (n, c, cl)
            for n, _, c, _, cl in items
            if (f"{c}.{cl}.{n}" if cl else f"{c}.{n}") not in matched_keys
        ]
        if unmatched:
            prefix_groups: dict[str, list[tuple[str, str, str | None]]] = {}
            single_segment: list[tuple[str, str, str | None]] = []

            for name, comp_name, class_name in unmatched:
                if "_" in name:
                    prefix = name.split("_")[0]
                    # Skip empty prefix from names like _private or __dunder
                    if prefix:
                        prefix_groups.setdefault(prefix, []).append((name, comp_name, class_name))
                    else:
                        single_segment.append((name, comp_name, class_name))
                else:
                    single_segment.append((name, comp_name, class_name))

            # Prefix groups with ≥ 2 members → "{prefix}_ops" Skill.
            for prefix, members in prefix_groups.items():
                if len(members) >= 2:
                    skill_name = f"{prefix}_ops"
                    if skill_name not in skill_map:
                        skill_map[skill_name] = SkillSpec(
                            name=skill_name,
                            description=f"Auto-grouped operations with prefix '{prefix}'",
                            allowed_tools=[],
                        )
                    for name, comp_name, class_name in members:
                        qualified = (
                            f"{comp_name}.{class_name}.{name}"
                            if class_name
                            else f"{comp_name}.{name}"
                        )
                        if qualified not in skill_map[skill_name].allowed_tools:
                            skill_map[skill_name].allowed_tools.append(qualified)
                else:
                    # Lone prefix groups → "misc".
                    if "misc" not in skill_map:
                        skill_map["misc"] = SkillSpec(
                            name="misc",
                            description="Miscellaneous operations (small prefix groups)",
                            allowed_tools=[],
                        )
                    for name, comp_name, class_name in members:
                        qualified = (
                            f"{comp_name}.{class_name}.{name}"
                            if class_name
                            else f"{comp_name}.{name}"
                        )
                        if qualified not in skill_map["misc"].allowed_tools:
                            skill_map["misc"].allowed_tools.append(qualified)

            # Single-segment names → "utility".
            if single_segment:
                skill_map["utility"] = SkillSpec(
                    name="utility",
                    description="Utility operations (single-segment names)",
                    allowed_tools=[],
                )
                for name, comp_name, class_name in single_segment:
                    qualified = (
                        f"{comp_name}.{class_name}.{name}" if class_name else f"{comp_name}.{name}"
                    )
                    if qualified not in skill_map["utility"].allowed_tools:
                        skill_map["utility"].allowed_tools.append(qualified)

        # Phase 3 — merge smallest groups until count ≤ max_io_groups.
        while len(skill_map) > self._max_io_groups:
            keys = list(skill_map.keys())
            smallest_key = min(keys, key=lambda k: len(skill_map[k].allowed_tools))
            # Find the most similar neighbor by tool prefix overlap (Jaccard).
            smallest_prefixes = _extract_prefixes(skill_map[smallest_key].allowed_tools)
            best_neighbor = smallest_key
            best_sim = -1.0
            for other_key in keys:
                if other_key == smallest_key:
                    continue
                other_prefixes = _extract_prefixes(skill_map[other_key].allowed_tools)
                inter = len(smallest_prefixes & other_prefixes)
                union = len(smallest_prefixes | other_prefixes)
                sim = inter / max(union, 1)
                if sim > best_sim:
                    best_sim = sim
                    best_neighbor = other_key
            # Fallback: merge into next smallest
            if best_neighbor == smallest_key:
                best_neighbor = next(k for k in keys if k != smallest_key)

            # Merge smallest into best neighbor
            skill_map[best_neighbor].allowed_tools.extend(skill_map[smallest_key].allowed_tools)
            del skill_map[smallest_key]

        return list(skill_map.values())

    def _component_group(self) -> list[SkillSpec]:
        """Group by SourceComponent. Each component becomes a SkillSpec.
        Operations map to allowed_tools.
        """
        if not self._source_components:
            return self._static_group()

        skills: list[SkillSpec] = []
        for component in self._source_components:
            tools = [
                f"{component.name}.{op.class_name}.{op.name}"
                if op.class_name
                else f"{component.name}.{op.name}"
                for op in component.operations
            ]
            skills.append(
                SkillSpec(
                    name=component.name,
                    description=component.description or f"Component: {component.name}",
                    allowed_tools=tools,
                )
            )
        return skills

    @staticmethod
    def _sanitize_type_name(raw: str) -> str:
        """Simplify a complex type annotation into a readable slug.

        Rules:
          - ``Annotated[X, ...]``  → extract the inner type ``X``
          - ``Literal[X]`` → ``literal``
          - ``list[X]`` / ``List[X]`` → ``list`` (generic params stripped)
          - ``dict[K, V]`` / ``Dict[K, V]`` → ``dict`` (generic params stripped)
          - ``Optional[X]`` → ``X``
          - ``Union[A, B]`` / ``A | B`` → ``A_B``
          - Other angle-bracket generics → bare name (params stripped)
          - Remove all characters unsafe for filenames
          - Lowercase the result.
        """
        s = raw.strip()

        m = re.match(r"^Literal\[", s)
        if m:
            return "literal"

        m = re.match(r"^Annotated\[(.+?),\s", s)
        if m:
            s = m.group(1).strip()

        m = re.match(r"^Optional\[(.+)\]$", s)
        if m:
            s = m.group(1).strip()

        if "|" in s:
            parts = [p.strip() for p in s.split("|")]
            parts = [re.sub(r"['\"]", "", p) for p in parts]
            s = "_".join(parts)

        m = re.match(r"^Union\[(.+)\]$", s)
        if m:
            parts = [p.strip() for p in m.group(1).split(",")]
            parts = [re.sub(r"['\"]", "", p) for p in parts]
            s = "_".join(parts)

        generic_set = {"list", "List", "dict", "Dict", "set", "Set", "tuple", "Tuple"}
        is_generic = False
        for prefix in generic_set:
            m = re.match(rf"^{prefix}\[.+]$", s)
            if m:
                # Strip generic parameters: dict[str,any] → dict
                s = prefix.lower()
                is_generic = True
                break

        if not is_generic:
            s = re.sub(r"[<\(\[{].*", "", s)

        s = s.replace(".", "_")
        s = re.sub(r"[|\\/:*?\"<>']", "", s)

        s = s.lower()
        return s

    def _io_relation_group(self) -> list[SkillSpec]:
        """Group operations by shared parameter types using type-anchor clustering.

        Tool naming under IO_RELATION:
            Class methods  → ``ClassName.methodName`` (e.g. ``VideoCodec.encode``)
            Top-level func → ``compName.fileStem.methodName`` when ``file_stem``
                             is present (disambiguates same-name functions across
                             files), otherwise ``compName.methodName`` (e.g.
                             ``MyModule.utils.load_config``).

        Phase 1 — Type frequency analysis:
            Count how many operations use each parameter type, then select the
            top-K most frequent types as "anchor types" (K = max_io_groups).

        Phase 2 — Anchor-set-intersection grouping:
            Each operation is assigned to the bucket defined by the exact set of
            its parameter types that intersect with the anchor set.  Operations
            with identical anchor-type combinations always go to the same bucket.
            Operations with no anchor types or no typed parameters are collected
            into a ``utility`` list, which is then dissolved round-robin across
            existing typed buckets.  If no typed buckets exist at all, utility
            ops remain as a single ``utility`` group.

        Phase 3 — Smallest-first merge:
            If the number of groups still exceeds ``max_io_groups``, the
            **smallest** bucket is merged with its most similar neighbor
            (highest Jaccard similarity between type-sets).  This preserves
            large, usefully-distinct buckets while consolidating tiny ones.
            Merge iterates until the target count is met.

        Phase 4 — Readable naming:
            Each group is named after its top 2-3 dominant types, e.g.
            ``io_group_str_path``.  A numeric suffix is appended when
            duplicate names arise.
        """
        if not self._source_components:
            return self._static_group()

        all_ops: list[tuple[SourceOperation, set[str], str]] = []
        for component in self._source_components:
            for op in component.operations:
                type_set = (
                    {self._sanitize_type_name(p.type_hint) for p in op.parameters if p.type_hint}
                    if op.parameters
                    else set()
                )
                all_ops.append((op, type_set, component.name))

        if not all_ops:
            return []

        type_freq = Counter()
        for _, ts, _ in all_ops:
            type_freq.update(ts)

        anchor_types: list[str] = [t for t, _ in type_freq.most_common(self._max_io_groups)]

        anchor_set = set(anchor_types)

        bucket_map: dict[tuple[str, ...], list[tuple[SourceOperation, set[str], str]]] = {}
        utility_ops: list[tuple[SourceOperation, set[str], str]] = []

        for op, ts, comp_name in all_ops:
            if not ts:
                utility_ops.append((op, ts, comp_name))
                continue

            # Group by anchor-type-set intersection: operations with identical
            # anchor-type combinations always go to the same bucket.  Unlike
            # least-frequent-first, this respects the true IO signature — no
            # operation is scattered to an unrelated bucket for balancing.
            present_anchors = tuple(sorted(t for t in ts if t in anchor_set))
            if present_anchors:
                bucket_map.setdefault(present_anchors, []).append((op, ts, comp_name))
            else:
                # No anchor type present — route to utility for round-robin later
                utility_ops.append((op, ts, comp_name))

        if utility_ops:
            # Dissolve utility bucket — distribute untyped ops round-robin
            # across existing typed buckets to avoid a single giant bucket.
            existing_keys = list(bucket_map.keys())
            if existing_keys:
                for idx, op_tuple in enumerate(utility_ops):
                    target_key = existing_keys[idx % len(existing_keys)]
                    bucket_map[target_key].append(op_tuple)
            else:
                # No typed buckets exist at all — keep as a single utility group
                bucket_map[("utility",)] = utility_ops

        bucket_type_sets: dict[tuple[str, ...], set[str]] = {}
        for anchor, items in bucket_map.items():
            combined = set()
            for _, ts, _ in items:
                combined |= ts
            bucket_type_sets[anchor] = combined

        while len(bucket_map) > self._max_io_groups:
            keys = list(bucket_map.keys())
            # Merge the SMALLEST bucket first — this preserves large,
            # usefully-distinct buckets (e.g. str, any, int) while
            # consolidating tiny ones.  The old highest-Jaccard-first
            # approach caused str+any+int to merge into a single
            # mega-bucket because they co-occur frequently.
            smallest_key = min(keys, key=lambda k: len(bucket_map[k]))
            # Find the most similar neighbor for this smallest bucket
            best_neighbor = smallest_key
            best_sim = -1.0
            for other_key in keys:
                if other_key == smallest_key:
                    continue
                inter = len(bucket_type_sets[smallest_key] & bucket_type_sets[other_key])
                union = len(bucket_type_sets[smallest_key] | bucket_type_sets[other_key])
                sim = inter / max(union, 1)
                if sim > best_sim:
                    best_neighbor = other_key
                    best_sim = sim
            # Fallback: if no similarity data, merge into first other bucket
            if best_neighbor == smallest_key:
                best_neighbor = next(k for k in keys if k != smallest_key)

            bucket_map[best_neighbor].extend(bucket_map[smallest_key])
            bucket_type_sets[best_neighbor] = (
                bucket_type_sets[best_neighbor] | bucket_type_sets[smallest_key]
            )
            del bucket_map[smallest_key]
            del bucket_type_sets[smallest_key]

        skills: list[SkillSpec] = []
        name_counts: Counter = Counter()

        for anchor, items in bucket_map.items():
            ops_with_comp = [(op, comp_name) for op, _, comp_name in items]
            freq = Counter()
            for _, ts, _ in items:
                freq.update(ts)

            dom_types = [t for t, _ in freq.most_common(3)]
            base_slug = "_".join(dom_types) if dom_types else "utility"
            base_name = f"io_group_{base_slug[:80]}"

            name_counts[base_name] += 1
            if name_counts[base_name] > 1:
                skill_name = f"{base_name}_{name_counts[base_name]}"
            else:
                skill_name = base_name

            type_desc = ", ".join(dom_types) if dom_types else "untyped"
            skills.append(
                SkillSpec(
                    name=skill_name,
                    description=f"Operations sharing types: {type_desc}",
                    allowed_tools=[
                        (
                            f"{op.class_name}.{op.name}"
                            if op.class_name
                            else f"{comp_name}.{op.file_stem}.{op.name}"
                            if op.file_stem
                            else f"{comp_name}.{op.name}"
                        )
                        for op, comp_name in ops_with_comp
                    ],
                )
            )

        return skills

    _LLM_SYSTEM_PROMPT = (
        "你是 SDK 工具分组专家。根据源码目录路径和方法数量，"
        "将目录聚类为 Skill 组。每组 Skill 对应一个子 Agent。\n\n"
        "约束：\n"
        "- 分组数量不超过 {max_groups} 个\n"
        "- 每个目录必须属于恰好一个 Skill\n"
        "- 同一父目录下的子目录通常应归入同一个 Skill\n"
        "- Skill 名称需简洁、有业务含义（如 core_engine, agent_lifecycle），"
        "不要用 io_group_x 这种机械名称\n"
        "- patterns 是目录路径的匹配模式（SUBSTRING 匹配），"
        "只需列出有区分力的片段即可，不要写完整路径\n\n"
        "输出格式（严格 JSON，不要输出任何其他内容）：\n"
        '{{"skills": [{{"name": "...", "description": "...", '
        '"patterns": ["path_fragment1", "path_fragment2"]}}]}}'
    )

    def _group_with_llm(self, requirements: str) -> list[SkillSpec]:
        """LLM-based semantic grouping of SourceComponent operations.

        Sends directory-level summaries (path + method count) to LLM,
        converts the returned patterns into MappingRules, then delegates
        to _keyword_match_group() for batch method assignment.

        When LLM is unavailable, falls back to KEYWORD_MATCH auto prefix
        inference directly.
        """
        import sys

        if not self._source_components:
            return self._static_group()

        if not self._llm_provider:
            logger.info("LLM_SEMANTIC: no provider configured, falling back to KEYWORD_MATCH")
            print(
                "warning: LLM provider not configured for --strategy llm, "
                "falling back to keyword match strategy. "
                "Consider using --strategy keyword directly for better results.",
                file=sys.stderr,
            )
            self._maybe_auto_rules()
            return self._keyword_match_group()

        # Count total ops — skip LLM for massive SDKs (prompt would overflow).
        # Threshold is based on directory count (one line per dir), not ops.
        total_ops = sum(len(comp.operations) for comp in self._source_components)
        total_dirs = len(self._source_components)

        dir_lines, dir_file_paths = self._build_llm_directory_catalog()
        if not dir_lines:
            self._maybe_auto_rules()
            return self._keyword_match_group()

        system_prompt = self._LLM_SYSTEM_PROMPT.format(max_groups=self._max_io_groups)
        user_content = "源码目录列表：\n" + "\n".join(dir_lines)
        if requirements:
            user_content += f"\n\n业务需求：{requirements}"

        try:
            messages: list[dict[str, str]] = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ]

            raw = self._llm_provider.chat(messages)
            logger.debug("LLM_SEMANTIC raw response (first 500 chars): %s", raw[:500])
            llm_rules = self._parse_llm_patterns(raw, dir_file_paths)
            if not llm_rules:
                logger.warning(
                    "LLM_SEMANTIC: empty parsed result, raw preview: %s",
                    raw[:500],
                )
                print(
                    "warning: LLM returned empty result, "
                    "falling back to keyword match strategy. "
                    "Try --strategy keyword instead.",
                    file=sys.stderr,
                )
                print(
                    f"--- LLM raw response (first 800 chars) ---\n{raw[:800]}\n---",
                    file=sys.stderr,
                )
                self._maybe_auto_rules()
                return self._keyword_match_group()

            # Replace self._rules with LLM-generated rules, then run
            # keyword_match_group which handles batch matching + unmatched
            # auto prefix inference.
            self._rules = llm_rules
            skills = self._keyword_match_group()

            # Print coverage summary so user can see LLM grouping quality.
            llm_skill_names = {r.skill_name for r in llm_rules}
            print(
                f"✅ LLM semantic grouping: {len(llm_rules)} patterns "
                f"→ {len(llm_skill_names)} skills",
                file=sys.stderr,
            )
            for name in sorted(llm_skill_names):
                pats = [r.method_pattern for r in llm_rules if r.skill_name == name]
                desc = next(
                    (r.description for r in llm_rules if r.skill_name == name),
                    "",
                )
                print(f"   {name}: {desc}", file=sys.stderr)
                print(f"     patterns: {pats}", file=sys.stderr)

            # Count dirs matched by LLM vs auto inference.
            llm_matched = sum(1 for s in skills if s.name in llm_skill_names)
            auto_count = len(skills) - llm_matched
            if auto_count > 0:
                auto_names = [s.name for s in skills if s.name not in llm_skill_names]
                print(
                    f"   ({auto_count} groups from auto prefix inference: {', '.join(auto_names)})",
                    file=sys.stderr,
                )
            return skills

        except Exception as exc:
            logger.warning(
                "LLM_SEMANTIC: LLM call failed (%s), falling back to KEYWORD_MATCH",
                exc,
            )
            print(
                f"warning: LLM call failed ({exc}), "
                "falling back to keyword match strategy. "
                "Try --strategy keyword instead.",
                file=sys.stderr,
            )
            self._maybe_auto_rules()
            return self._keyword_match_group()

    def _build_llm_directory_catalog(self) -> tuple[list[str], list[str]]:
        """Build directory-level summaries for the LLM prompt.

        Returns (description_lines, file_paths) where each line is:
        ``- file_path (dir_name): N methods, "package description"``
        and file_paths is the list of unique file_paths for MappingRule matching.
        """
        lines: list[str] = []
        paths: list[str] = []
        for comp in self._source_components:
            op_count = len(comp.operations)
            desc = comp.description or "(无描述)"
            fp = comp.file_path.replace("\\", "/")
            paths.append(fp)
            lines.append(f'- {fp}: {op_count} methods, "{desc}"')
        return lines, paths

    def _parse_llm_patterns(
        self,
        raw: str,
        dir_file_paths: list[str],
    ) -> list[MappingRule] | None:
        """Parse LLM response into MappingRules with FILE_PATH patterns.

        Expected JSON::
            {"skills": [{"name": "...", "description": "...",
                          "patterns": ["path_fragment1", "path_fragment2"]}]}

        Each pattern becomes a MappingRule with match_target=FILE_PATH
        and match_type=SUBSTRING.  Returns None on parse failure.
        """
        json_str = self._extract_json_from_raw(raw)
        if not json_str:
            return None

        try:
            data = json.loads(json_str)
        except json.JSONDecodeError:
            logger.warning("LLM_SEMANTIC: failed to parse JSON response")
            return None

        if not isinstance(data, dict) or "skills" not in data:
            logger.warning("LLM_SEMANTIC: response missing 'skills' key")
            return None

        skills_data = data["skills"]
        if not isinstance(skills_data, list):
            return None

        rules: list[MappingRule] = []
        used_names: set[str] = set()

        for item in skills_data:
            if not isinstance(item, dict):
                continue

            raw_name = item.get("name", "")
            description = item.get("description", "")
            patterns = item.get("patterns", [])

            if not raw_name or not isinstance(patterns, list) or not patterns:
                continue

            skill_name = raw_name.strip().lower().replace(" ", "_").replace("-", "_")
            # Deduplicate skill names.
            if skill_name in used_names:
                n = 2
                while f"{skill_name}_{n}" in used_names:
                    n += 1
                skill_name = f"{skill_name}_{n}"
            used_names.add(skill_name)

            desc = (
                description.strip()
                if isinstance(description, str) and description.strip()
                else f"LLM-grouped: {skill_name}"
            )

            for pat in patterns:
                if not isinstance(pat, str) or not pat.strip():
                    continue
                # Strip trailing slash so "tests/" matches "tests" and "tests/cli".
                method_pat = pat.strip().rstrip("/")
                if not method_pat:
                    continue
                rules.append(
                    MappingRule(
                        method_pattern=method_pat,
                        tool_name="",
                        skill_name=skill_name,
                        description=desc,
                        match_type=MatchType.SUBSTRING,
                        match_target=MatchTarget.FILE_PATH,
                    )
                )

        if not rules:
            return None

        # Sort by specificity: longer patterns first so they match before
        # shorter / broader patterns (first-match-wins).
        rules.sort(key=lambda r: len(r.method_pattern), reverse=True)
        return rules

    @staticmethod
    def _extract_json_from_raw(raw: str) -> str | None:
        """Extract the first valid JSON object containing 'skills' from a raw LLM response.

        Tolerates preamble (e.g. "Here is the grouping:") and postamble
        (explanation after the JSON).  Searches for the outermost ``{``
        … ``}`` pair whose parsed content contains a ``"skills"`` key.
        """
        start = raw.find("{")
        if start < 0:
            return None

        depth = 0
        for i in range(start, len(raw)):
            if raw[i] == "{":
                depth += 1
            elif raw[i] == "}":
                depth -= 1
                if depth == 0:
                    candidate = raw[start : i + 1]
                    try:
                        parsed = json.loads(candidate)
                        if isinstance(parsed, dict) and "skills" in parsed:
                            return candidate
                    except json.JSONDecodeError:
                        pass

        return None

    def group_with_llm(self, requirements: str) -> list[SkillSpec]:
        """Public convenience method — delegates to ``_group_with_llm``."""
        return self._group_with_llm(requirements)


@dataclass
class GroupResult:
    """Result of skill grouping operation."""

    skills: list[SkillSpec]
    unmatched_tools: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def group_into_skills(
    methods: list[SdkMethod],
    requirements: str = "",
    mapping_rules: list[MappingRule] | None = None,
) -> GroupResult:
    """Convenience function to group SDK methods into Skills."""
    grouper = SkillGrouper(methods, mapping_rules=mapping_rules)
    skills = grouper.group(requirements)
    all_tools = {t for s in skills for t in s.allowed_tools}
    method_tools = {m.name for m in methods}
    unmatched = [t for t in method_tools if t not in all_tools]
    return GroupResult(skills=skills, unmatched_tools=unmatched)


def group_source_components(
    components: list[SourceComponent],
    strategy: GroupStrategy = GroupStrategy.COMPONENT_GROUP,
    max_io_groups: int | None = None,
    mapping_rules: list[MappingRule] | None = None,
    requirements: str = "",
    llm_provider: SOPAssistantProviderProtocol | None = None,
) -> GroupResult:
    """Convenience function to group source components into Skills by strategy.

    Tool naming varies by strategy:
      COMPONENT_GROUP / KEYWORD_MATCH / LLM_SEMANTIC →
          ``compName.className.methodName`` (class methods) or
          ``compName.methodName`` (top-level functions).
      IO_RELATION → ``ClassName.methodName`` (class methods) or
                    ``compName.fileStem.methodName`` / ``compName.methodName``
                    (top-level functions), to disambiguate across files.

    Args:
        components: Source components parsed from Python source code.
        strategy: Grouping strategy to apply.
        max_io_groups: Maximum number of groups (skills) to produce.
        mapping_rules: Custom MappingRule list for KEYWORD_MATCH strategy.
        requirements: Business requirements hint for LLM_SEMANTIC strategy.
        llm_provider: LLM provider instance for LLM_SEMANTIC strategy.
            When None and strategy is LLM_SEMANTIC, falls back to IO_RELATION.
    """
    grouper = SkillGrouper(
        methods=[],
        strategy=strategy,
        source_components=components,
        max_io_groups=max_io_groups,
        mapping_rules=mapping_rules,
        llm_provider=llm_provider,
    )
    skills = grouper.group(requirements=requirements)
    all_tools = {t for s in skills for t in s.allowed_tools}
    if strategy == GroupStrategy.IO_RELATION:
        component_tools = {
            (
                f"{op.class_name}.{op.name}"
                if op.class_name
                else f"{c.name}.{op.file_stem}.{op.name}"
                if op.file_stem
                else f"{c.name}.{op.name}"
            )
            for c in components
            for op in c.operations
        }
    else:
        # COMPONENT_GROUP / KEYWORD_MATCH / LLM_SEMANTIC all use the
        # same naming convention: compName.className.methodName for
        # class methods, compName.methodName for top-level functions.
        # This must match the format used by _keyword_match_group()
        # and _component_group() so the unmatched-tool check is accurate.
        component_tools = {
            (f"{c.name}.{op.class_name}.{op.name}" if op.class_name else f"{c.name}.{op.name}")
            for c in components
            for op in c.operations
        }
    unmatched = [t for t in component_tools if t not in all_tools]
    return GroupResult(skills=skills, unmatched_tools=unmatched)
