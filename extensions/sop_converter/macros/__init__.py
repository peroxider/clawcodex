"""Small in-process catalog for executable workflow definitions and routes."""

from .catalog import (
    DEFAULT_MACRO_CATALOG,
    MacroCatalog,
    ensure_builtin_macros,
    register_macro,
    resolve_macro,
)
from .convert import MacroConvertResult, convert_handwritten_macros
from .errors import MacroConvertError
from .loader import discover_macro_sources, load_macro_definitions, load_macro_yaml
from .models import MacroDefinition, MacroRoute
from .overview_intent import (
    assign_macros_to_owner_skills,
    format_overview_macro_intent_block,
    pick_owner_skill,
    resolve_macro_delegate_agent,
)
from .routing import (
    DEFAULT_MACRO_ROUTE_CATALOG,
    MacroRouteCatalog,
    ensure_builtin_routes,
    match_macro_routes,
    register_macro_route,
    resolve_macro_route,
    resolve_macro_route_details,
)
from .templates import HANDWRITTEN_MACRO_TEMPLATE, TEMPLATES_DIR
from ..tool_retrieval import (
    MacroCoverage,
    ToolRetrievalIndex,
    ToolRetrievalProfile,
    load_tool_retrieval_index,
    write_tool_retrieval_index,
)

__all__ = [
    "DEFAULT_MACRO_CATALOG",
    "MacroCatalog",
    "ensure_builtin_macros",
    "register_macro",
    "resolve_macro",
    "MacroDefinition",
    "MacroRoute",
    "DEFAULT_MACRO_ROUTE_CATALOG",
    "MacroRouteCatalog",
    "ensure_builtin_routes",
    "match_macro_routes",
    "register_macro_route",
    "resolve_macro_route",
    "resolve_macro_route_details",
    "MacroConvertError",
    "MacroConvertResult",
    "convert_handwritten_macros",
    "discover_macro_sources",
    "load_macro_definitions",
    "load_macro_yaml",
    "format_overview_macro_intent_block",
    "resolve_macro_delegate_agent",
    "pick_owner_skill",
    "assign_macros_to_owner_skills",
    "MacroCoverage",
    "ToolRetrievalIndex",
    "ToolRetrievalProfile",
    "load_tool_retrieval_index",
    "write_tool_retrieval_index",
    "HANDWRITTEN_MACRO_TEMPLATE",
    "TEMPLATES_DIR",
]
