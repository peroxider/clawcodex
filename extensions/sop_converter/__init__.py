"""SOP converter — transforms professional workflows into reusable Agents.

Three-layer mapping:
    SOP (Standard Operating Procedure)     → Agent
    workflow steps                → Skill
    SDK interfaces               → atomic tools

Architecture::

    SDK Spec + Requirements
         │
         ▼
    SdkParser ──────────────────► atomic_tools: list[str]
         │
         ▼
    SkillGrouper ────────────────► skills: list[SkillSpec]
         │
         ▼
    AgentBuilder ────────────────► agent: AgentDefinition
         │
         ▼
    Persistence / Registration
"""

from .sdk_parser import SdkParser, SdkMethod
from .skill_grouper import (
    SkillGrouper,
    SkillSpec,
    GroupStrategy,
    MatchType,
    MatchTarget,
    group_source_components,
)
from .agent_builder import AgentBuilder, AgentBuildResult
from .templates import (
    AGENT_TEMPLATE,
    SKILL_TEMPLATE,
    MappingRule,
    AGENT_MD_TEMPLATE,
    SKILL_MD_TEMPLATE_JINJA,
    OVERVIEW_AGENT_TEMPLATE,
)
from .source_parser import SourceCodeParser, SourceComponent, SourceOperation, ParamSpec
from .agent_md_writer import AgentMarkdownWriter, AgentComponentInfo, WorkflowStage
from .default_agent import resolve_default_agent, resolve_agent_by_type
from .tool_registry_bridge import register_component_tools
from .resource_catalog import (
    ResourceCatalog,
    ResourceRecord,
    get_resource_record,
    resolve_resource_catalog_path,
)
from .resource_handlers import (
    ResourceHandler,
    get_resource_handler,
    register_resource_handler,
    require_resource_handler,
)
from .tool_retrieval import (
    MacroCoverage,
    ToolRetrievalIndex,
    ToolRetrievalProfile,
    load_tool_retrieval_index,
)
from .workflow_mode import (
    WorkflowDiscriminator,
    DiscriminationResult,
    discriminate_and_extract,
    extract_workflow,
)


def register_composite_tools(*args, **kwargs):
    from .composite_tools import register_composite_tools as _register

    return _register(*args, **kwargs)


def emit_composite_workflow_yaml(*args, **kwargs):
    from .composite_tools import emit_composite_workflow_yaml as _emit

    return _emit(*args, **kwargs)


__all__ = [
    "SdkParser",
    "SdkMethod",
    "SkillGrouper",
    "SkillSpec",
    "GroupStrategy",
    "MatchType",
    "MatchTarget",
    "group_source_components",
    "AgentBuilder",
    "AgentBuildResult",
    "AGENT_TEMPLATE",
    "SKILL_TEMPLATE",
    "MappingRule",
    "AGENT_MD_TEMPLATE",
    "SKILL_MD_TEMPLATE_JINJA",
    "OVERVIEW_AGENT_TEMPLATE",
    "SourceCodeParser",
    "SourceComponent",
    "SourceOperation",
    "ParamSpec",
    "AgentMarkdownWriter",
    "AgentComponentInfo",
    "WorkflowStage",
    "resolve_default_agent",
    "resolve_agent_by_type",
    "register_component_tools",
    "ResourceCatalog",
    "ResourceRecord",
    "get_resource_record",
    "resolve_resource_catalog_path",
    "ResourceHandler",
    "get_resource_handler",
    "register_resource_handler",
    "require_resource_handler",
    "MacroCoverage",
    "ToolRetrievalIndex",
    "ToolRetrievalProfile",
    "load_tool_retrieval_index",
    "register_composite_tools",
    "emit_composite_workflow_yaml",
    "WorkflowDiscriminator",
    "DiscriminationResult",
    "discriminate_and_extract",
    "extract_workflow",
]
