"""Stage 3e — REPL 配色 / Rich Theme Markup 渲染测试（< 2 秒）。

验证使用 OKLCH 调色板的 Rich Theme 不会抛出 MarkupError。
每种自定义语义名称（error/success/warning/info/等）都独立测试，
确保其作为独立标签和嵌套标签（如 [bold][error]）都能正确渲染。

注意：此测试不依赖 Console 的终端宽度或颜色支持，使用
``force_terminal=True`` 确保 ANSI 序列始终生成，从而触发
完整的 Rich markup 解析路径。输出写入 ``io.StringIO`` 而非
真实终端，避免测试噪音。
"""

from __future__ import annotations

import io

import pytest
from rich.console import Console
from rich.theme import Theme

from clawcodex_ext.repl.color_scheme import DARK, build_rich_theme


# ── 共享 Theme 和 Console ──────────────────────────────────────────────

_OKLCH_THEME = Theme(build_rich_theme(DARK))


def _console() -> Console:
    """Return a Console with the OKLCH Theme, writing to a StringIO buffer."""
    return Console(
        file=io.StringIO(),
        force_terminal=True,
        width=80,
        theme=_OKLCH_THEME,
    )


# 每个语义名都要测试的 markup 模式
_SEMANTIC_NAMES = ["error", "success", "warning", "info", "primary",
                   "secondary", "muted", "agent", "tool", "call",
                   "result", "spinner", "user_bg", "diff_add", "diff_remove"]


class TestStage3eReplColors:
    """REPL 配色渲染 — 各类 semantic 标签不抛 MarkupError。"""

    # ── 独立标签 ──────────────────────────────────────────────────────

    @pytest.mark.parametrize("name", _SEMANTIC_NAMES)
    def test_standalone_tag(self, name: str) -> None:
        """``[name]text[/name]`` 渲染无异常。"""
        c = _console()
        c.print(f"[{name}]sample text[/{name}]")

    @pytest.mark.parametrize("name", _SEMANTIC_NAMES)
    def test_bold_nested(self, name: str) -> None:
        """``[bold][name]text[/name][/bold]`` 渲染无异常。"""
        c = _console()
        c.print(f"[bold][{name}]bolded text[/{name}][/bold]")

    # ── 复合场景 ──────────────────────────────────────────────────────

    def test_error_message_like_exception(self) -> None:
        """模拟 ``chat()`` 中异常输出的 markup 模式。"""
        c = _console()
        c.print("\n[error]Error: something went wrong[/error]")

    def test_success_status(self) -> None:
        c = _console()
        c.print("[success]✓ Task completed[/success]")

    def test_warning_banner(self) -> None:
        c = _console()
        c.print("[bold][warning]⚠ Warning[/warning][/bold]")

    def test_info_label(self) -> None:
        c = _console()
        c.print("[bold][info]Info label[/info][/bold]")

    def test_tool_call_line(self) -> None:
        """模拟工具调用行 ``● ToolName(args)``。"""
        c = _console()
        c.print("[success]●[/success] [bold][info]Read[/info][/bold] [call](file.txt)[/call]")

    def test_tool_result_preview(self) -> None:
        c = _console()
        c.print("[muted]  ⎿  some result[/muted]")

    def test_tool_error(self) -> None:
        c = _console()
        c.print("[error]  ⎿  command failed[/error]")

    def test_muted_text_with_bold(self) -> None:
        c = _console()
        c.print("[bold][muted]dim header[/muted][/bold]")

    def test_agent_label(self) -> None:
        c = _console()
        c.print("[bold][agent]Assistant[/agent][/bold]")

    def test_mixed_standalone_and_nested(self) -> None:
        """混合场景：同一 ``print()`` 中既有独立标签也有嵌套标签。"""
        c = _console()
        c.print(
            "[bold][agent]Assistant[/agent][/bold]\n"
            "[muted]  ⎿  done[/muted]"
        )

    # ── 边界情况 ──────────────────────────────────────────────────────

    def test_long_text_no_markup_error(self) -> None:
        """长文本中嵌入语义标签不应导致 MarkupError。"""
        c = _console()
        c.print(
            "[error]Error: This is a very long error message that might "
            "trigger edge cases in the markup parser when combined with "
            "other text elements and nested formatting.[/error]"
        )

    def test_multiple_tags_same_line(self) -> None:
        c = _console()
        c.print(
            "[success]✓[/success] [bold][info]Task[/info][/bold] "
            "[muted](2 done, 1 in progress)[/muted]"
        )

    def test_tag_inside_fstring_interpolation(self) -> None:
        """模拟 chat() 中 ``f\"\\n[error]Error: {e}[/error]\"`` 的模式。"""
        c = _console()
        err_msg = "permission denied"
        c.print(f"\n[error]Error: {err_msg}[/error]")
        c.print(f"\n[warning]Warning: {err_msg}[/warning]")
        c.print(f"\n[success]Success: {err_msg}[/success]")
