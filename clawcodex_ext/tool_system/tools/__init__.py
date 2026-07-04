"""Tool system tools package.

Re-exports all built-in tool classes and ``ALL_STATIC_TOOLS``.
"""

from __future__ import annotations

from ..build_tool import Tool

from .advisor import AdvisorTool
from .agent import make_agent_tool
from .ask_user_question import AskUserQuestionTool
from .bash import BashTool
from .brief import BriefTool
from .config import ConfigTool
from .cron import CronCreateTool, CronDeleteTool, CronListTool
from .edit import EditTool
from .execute import ExecuteTool
from .glob import GlobTool
from .grep import GrepTool
from .lsp import LSPTool
from .mcp import MCPTool
from .notebook_edit import NotebookEditTool
from .mcp_resources import ListMcpResourcesTool, ReadMcpResourceTool
from .misc import ClipboardReadTool, ClipboardWriteTool, StatusTool
from .plan_mode import EnterPlanModeTool, ExitPlanModeTool
from .read import ReadTool
from .remote_trigger import RemoteTriggerTool
from .send_message import SendMessageTool
from .send_user_message import SendUserMessageTool
from .skill import SkillTool
from .snip import SnipTool
from .sleep import SleepTool
from .structured_output import StructuredOutputTool
from .task_stop import TaskStopTool
from .tasks_v2 import (
    TaskCreateTool,
    TaskGetTool,
    TaskListTool,
    TaskOutputTool,
    TaskUpdateTool,
)
from .team import TeamCreateTool, TeamDeleteTool
from .team_memory import TeamMemoryTool
from .todo_write import TodoWriteTool
from .tool_search import make_tool_search_tool
from .web_browser import WebBrowserTool
from .web_fetch import WebFetchTool
from .web_search import WebSearchTool
from .worktree import EnterWorktreeTool, ExitWorktreeTool
from .write import WriteTool

ALL_STATIC_TOOLS: list[Tool] = [
    AdvisorTool,
    AskUserQuestionTool,
    BashTool,
    BriefTool,
    ClipboardReadTool,
    ClipboardWriteTool,
    ConfigTool,
    CronCreateTool,
    CronDeleteTool,
    CronListTool,
    EditTool,
    EnterPlanModeTool,
    EnterWorktreeTool,
    ExecuteTool,
    ExitPlanModeTool,
    ExitWorktreeTool,
    GlobTool,
    GrepTool,
    LSPTool,
    ListMcpResourcesTool,
    MCPTool,
    NotebookEditTool,
    ReadMcpResourceTool,
    ReadTool,
    RemoteTriggerTool,
    SendMessageTool,
    SendUserMessageTool,
    SkillTool,
    SleepTool,
    SnipTool,
    StatusTool,
    StructuredOutputTool,
    TaskCreateTool,
    TaskGetTool,
    TaskListTool,
    TaskOutputTool,
    TaskStopTool,
    TaskUpdateTool,
    TeamCreateTool,
    TeamDeleteTool,
    TeamMemoryTool,
    TodoWriteTool,
    WebBrowserTool,
    WebFetchTool,
    WebSearchTool,
    WriteTool,
]

__all__ = [
    "ALL_STATIC_TOOLS",
    "AdvisorTool",
    "AskUserQuestionTool",
    "BashTool",
    "BriefTool",
    "ClipboardReadTool",
    "ClipboardWriteTool",
    "ConfigTool",
    "CronCreateTool",
    "CronDeleteTool",
    "CronListTool",
    "EditTool",
    "EnterPlanModeTool",
    "EnterWorktreeTool",
    "ExecuteTool",
    "ExitPlanModeTool",
    "ExitWorktreeTool",
    "GlobTool",
    "GrepTool",
    "LSPTool",
    "ListMcpResourcesTool",
    "MCPTool",
    "NotebookEditTool",
    "ReadMcpResourceTool",
    "ReadTool",
    "RemoteTriggerTool",
    "SendMessageTool",
    "SendUserMessageTool",
    "SkillTool",
    "SleepTool",
    "SnipTool",
    "StatusTool",
    "StructuredOutputTool",
    "TaskCreateTool",
    "TaskGetTool",
    "TaskListTool",
    "TaskOutputTool",
    "TaskStopTool",
    "TaskUpdateTool",
    "TeamCreateTool",
    "TeamDeleteTool",
    "TeamMemoryTool",
    "TodoWriteTool",
    "WebBrowserTool",
    "WebFetchTool",
    "WebSearchTool",
    "WriteTool",
    "make_agent_tool",
    "make_tool_search_tool",
]
