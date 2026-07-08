"""Tests for clawcodex_ext/llm.py — lightweight LLM completion interface."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_provider(return_content: str = "mock reply") -> MagicMock:
    """Build a fake BaseProvider whose chat_async returns *return_content*."""
    provider = MagicMock()
    provider.chat_async = AsyncMock(
        return_value=MagicMock(content=return_content, finish_reason="stop")
    )
    return provider


# ---------------------------------------------------------------------------
# llm_complete 基本功能
# ---------------------------------------------------------------------------


class TestLlmComplete:
    """使用 mock provider 验证 llm_complete 的调用行为。"""

    @pytest.mark.asyncio
    async def test_basic_completion(self) -> None:
        """llm_complete 返回 provider.chat_async 的 content 字段。"""
        with patch("clawcodex_ext.llm.build_provider_from_config", return_value=_make_provider()):
            with patch("clawcodex_ext.llm._get_default_provider", return_value="p"):
                with patch("clawcodex_ext.llm._get_default_model", return_value="m"):
                    from clawcodex_ext.llm import llm_complete

                    result = await llm_complete("hello")
        assert result == "mock reply"

    @pytest.mark.asyncio
    async def test_passes_provider_and_model(self) -> None:
        """provider_name 和 model 被转发到 build_provider_from_config。"""
        with patch("clawcodex_ext.llm.build_provider_from_config") as mock_build:
            with patch("clawcodex_ext.llm._get_default_provider", return_value="fallback-p"):
                with patch("clawcodex_ext.llm._get_default_model", return_value="fallback-m"):
                    mock_build.return_value = _make_provider()
                    from clawcodex_ext.llm import llm_complete

                    await llm_complete("hi", provider_name="my-p", model="my-m")
        mock_build.assert_called_once_with("my-p", "my-m")

    @pytest.mark.asyncio
    async def test_uses_defaults_when_not_specified(self) -> None:
        """不传 provider_name/model 时使用默认值。"""
        with patch("clawcodex_ext.llm.build_provider_from_config") as mock_build:
            with patch("clawcodex_ext.llm._get_default_provider", return_value="default-p"):
                with patch("clawcodex_ext.llm._get_default_model", return_value="default-m"):
                    mock_build.return_value = _make_provider()
                    from clawcodex_ext.llm import llm_complete

                    await llm_complete("hi")
        mock_build.assert_called_once_with("default-p", "default-m")

    @pytest.mark.asyncio
    async def test_sends_system_prompt(self) -> None:
        """system_prompt 作为 system role message 发送。"""
        provider = _make_provider()
        with patch("clawcodex_ext.llm.build_provider_from_config", return_value=provider):
            with patch("clawcodex_ext.llm._get_default_provider", return_value="p"):
                with patch("clawcodex_ext.llm._get_default_model", return_value="m"):
                    from clawcodex_ext.llm import llm_complete

                    await llm_complete("hello", system_prompt="be brief")
        call = provider.chat_async.await_args
        messages = call.args[0] if call.args else call.kwargs.get("messages")
        roles = [m.role for m in messages]
        assert "system" in roles
        assert "user" in roles

    @pytest.mark.asyncio
    async def test_no_system_when_empty(self) -> None:
        """system_prompt 为空时不发 system message。"""
        provider = _make_provider()
        with patch("clawcodex_ext.llm.build_provider_from_config", return_value=provider):
            with patch("clawcodex_ext.llm._get_default_provider", return_value="p"):
                with patch("clawcodex_ext.llm._get_default_model", return_value="m"):
                    from clawcodex_ext.llm import llm_complete

                    await llm_complete("hello")
        call = provider.chat_async.await_args
        messages = call.args[0] if call.args else call.kwargs.get("messages")
        roles = [m.role for m in messages]
        assert "system" not in roles
        assert roles == ["user"]

    @pytest.mark.asyncio
    async def test_forwards_temperature_and_max_tokens(self) -> None:
        """temperature 和 max_tokens 被转发到 chat_async。"""
        provider = _make_provider()
        with patch("clawcodex_ext.llm.build_provider_from_config", return_value=provider):
            with patch("clawcodex_ext.llm._get_default_provider", return_value="p"):
                with patch("clawcodex_ext.llm._get_default_model", return_value="m"):
                    from clawcodex_ext.llm import llm_complete

                    await llm_complete("hello", temperature=0.5, max_tokens=200)
        _, kwargs = provider.chat_async.await_args
        assert kwargs.get("temperature") == 0.5
        assert kwargs.get("max_tokens") == 200

    @pytest.mark.asyncio
    async def test_strips_whitespace(self) -> None:
        """返回结果的前后空白被 strip。"""
        provider = _make_provider("  \n  reply text  \n  ")
        with patch("clawcodex_ext.llm.build_provider_from_config", return_value=provider):
            with patch("clawcodex_ext.llm._get_default_provider", return_value="p"):
                with patch("clawcodex_ext.llm._get_default_model", return_value="m"):
                    from clawcodex_ext.llm import llm_complete

                    result = await llm_complete("hi")
        assert result == "reply text"

    @pytest.mark.asyncio
    async def test_empty_response(self) -> None:
        """返回空字符串时不报错。"""
        provider = _make_provider("")
        with patch("clawcodex_ext.llm.build_provider_from_config", return_value=provider):
            with patch("clawcodex_ext.llm._get_default_provider", return_value="p"):
                with patch("clawcodex_ext.llm._get_default_model", return_value="m"):
                    from clawcodex_ext.llm import llm_complete

                    result = await llm_complete("hi")
        assert result == ""


# ---------------------------------------------------------------------------
# 默认值解析
# ---------------------------------------------------------------------------


class TestDefaultResolution:
    """验证默认 provider/model 的解析与缓存行为。"""

    def setUp(self) -> None:
        import clawcodex_ext.llm as llm_mod

        llm_mod._DEFAULT_PROVIDER = None
        llm_mod._DEFAULT_MODEL = None

    @patch("src.config.get_default_provider", return_value="cfg-provider")
    def test_resolve_default_provider(self, _mock) -> None:
        """_get_default_provider 委托给 src.config.get_default_provider。"""
        from clawcodex_ext.llm import _get_default_provider

        assert _get_default_provider() == "cfg-provider"

    @patch("src.config.get_provider_config", return_value={"default_model": "cfg-model"})
    def test_resolve_default_model(self, _mock) -> None:
        """_get_default_model 委托给 src.config.get_provider_config。"""
        from clawcodex_ext.llm import _get_default_model

        assert _get_default_model("test-p") == "cfg-model"


# ---------------------------------------------------------------------------
# 错误处理
# ---------------------------------------------------------------------------


class TestLlmErrors:
    @pytest.mark.asyncio
    async def test_raises_on_missing_api_key(self) -> None:
        """API key 未配置时抛出 RuntimeError。"""
        with patch(
            "clawcodex_ext.llm.build_provider_from_config",
            side_effect=RuntimeError("API key not configured"),
        ):
            with patch("clawcodex_ext.llm._get_default_provider", return_value="p"):
                with patch("clawcodex_ext.llm._get_default_model", return_value="m"):
                    from clawcodex_ext.llm import llm_complete

                    with pytest.raises(RuntimeError, match="API key"):
                        await llm_complete("hi")
