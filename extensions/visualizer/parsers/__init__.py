"""Data parsers for the Multi-Session Visualizer (F-91-B).

NOTE: Several parser modules (transcript_parser, tool_events_parser) have
circular imports with the builders package.  To avoid triggering those at
package-load time, only safe (non-circular) imports are listed here.
Use direct submodule imports for the others, e.g.::

    from .orchestrator_state_parser import OrchestratorStateParser
    from .transcript_parser import TranscriptParser
"""

from .session_parser import SessionMetadataParser
from .multi_agent_parser import MultiAgentParser

# OrchestratorStateParser has no circular deps — safe to expose here.
from .orchestrator_state_parser import OrchestratorStateParser


__all__ = [
    "SessionMetadataParser",
    "MultiAgentParser",
    "OrchestratorStateParser",
]
