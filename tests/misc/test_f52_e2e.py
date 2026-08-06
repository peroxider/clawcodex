"""端到端测试: OpenAPI Spec → 解析 → 工具注册 → Agent 生成"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest

from extensions.sop_converter import (
    SdkParser,
    SdkParam,
    register_http_tools,
    convert_sop_to_agent,
)


def load_test_spec() -> dict:
    """加载测试用的 OpenAPI spec"""
    spec_path = Path(__file__).parent / "data" / "test_openapi_spec.json"
    with open(spec_path, "r", encoding="utf-8") as f:
        return json.load(f)


class TestF52E2E:
    """端到端测试"""

    def test_openapi_spec_parsing(self):
        """测试 OpenAPI spec 解析"""
        spec = load_test_spec()
        parser = SdkParser(spec)
        methods = parser.parse()

        assert len(methods) > 0

        method_names = {m.name for m in methods}
        assert "list_users" in method_names
        assert "create_user" in method_names
        assert "get_user" in method_names
        assert "update_user" in method_names
        assert "delete_user" in method_names
        assert "list_products" in method_names
        assert "get_product" in method_names

        assert parser.openapi_base_url == "https://api.example.com/v1"

    def test_parameter_types_extracted(self):
        """测试参数类型提取"""
        spec = load_test_spec()
        parser = SdkParser(spec)
        methods = parser.parse()

        list_users = next(m for m in methods if m.name == "list_users")
        assert len(list_users.params) == 3

        limit_param = next(p for p in list_users.params if p.name == "limit")
        assert limit_param.param_type == "integer"
        assert not limit_param.required
        assert limit_param.description == "每页数量"
        assert limit_param.location == "query"

        offset_param = next(p for p in list_users.params if p.name == "offset")
        assert offset_param.param_type == "integer"
        assert offset_param.required

    def test_request_body_extracted(self):
        """测试请求体提取"""
        spec = load_test_spec()
        parser = SdkParser(spec)
        methods = parser.parse()

        create_user = next(m for m in methods if m.name == "create_user")
        assert create_user.request_body is not None
        assert create_user.request_body.get("required") is True
        assert "application/json" in create_user.request_body.get("content", {})

    def test_responses_extracted(self):
        """测试响应提取"""
        spec = load_test_spec()
        parser = SdkParser(spec)
        methods = parser.parse()

        get_user = next(m for m in methods if m.name == "get_user")
        assert "200" in get_user.responses
        assert "404" in get_user.responses

    def test_tags_extracted(self):
        """测试标签提取"""
        spec = load_test_spec()
        parser = SdkParser(spec)
        methods = parser.parse()

        list_users = next(m for m in methods if m.name == "list_users")
        assert "users" in list_users.tags

        list_products = next(m for m in methods if m.name == "list_products")
        assert "products" in list_products.tags

    def test_http_tool_registration(self, tmp_path):
        """测试 HTTP 工具注册"""
        spec = load_test_spec()
        parser = SdkParser(spec)
        methods = parser.parse()

        bundle_dir = tmp_path / "test_bundle"
        name_map = register_http_tools(
            methods,
            persist=True,
            bundle_dir=str(bundle_dir),
            generate_wrappers=True,
        )

        assert len(name_map) == len(methods)

        tool_dir = bundle_dir / "agent-tools"
        assert tool_dir.exists()

        spec_files = list(tool_dir.glob("*.json"))
        assert len(spec_files) == len(methods)

        scripts_dir = tool_dir / "scripts"
        assert scripts_dir.exists()

        script_files = list(scripts_dir.glob("*.py"))
        assert len(script_files) == len(methods)

        list_users_spec = tool_dir / "list-users.json"
        assert list_users_spec.exists()

        with open(list_users_spec, "r", encoding="utf-8") as f:
            spec_data = json.load(f)

        assert spec_data["name"] == "list-users"
        assert spec_data["call_type"] == "http"
        assert spec_data["call_impl"]["method"] == "GET"
        assert "/users" in spec_data["call_impl"]["url"]
        assert "properties" in spec_data["input_schema"]

    def test_convert_sop_to_agent_with_openapi(self, tmp_path):
        """测试 SOP 转换为 Agent（OpenAPI 模式）"""
        spec = load_test_spec()

        result = convert_sop_to_agent(
            sdk_spec=spec,
            requirements="用户管理和产品查询",
            agent_name="test-api-agent",
        )

        assert result["status"] == "converted"
        assert result["is_openapi"] is True
        assert result["registered_http_tools"] > 0

        assert len(result["skills"]) > 0

        tool_names = []
        for skill in result["skills"]:
            tool_names.extend(skill["tools"])

        assert "list-users" in tool_names
        assert "create-user" in tool_names
        assert "get-user" in tool_names
        assert "list-products" in tool_names

    def test_full_flow_from_json_string(self, tmp_path):
        """测试从 JSON 字符串开始的完整流程"""
        spec = load_test_spec()
        spec_json = json.dumps(spec)

        result = convert_sop_to_agent(
            sdk_spec=spec_json,
            requirements="API 测试",
        )

        assert result["status"] == "converted"
        assert result["is_openapi"] is True


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])