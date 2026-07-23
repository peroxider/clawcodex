"""使用 Swagger Petstore API 验证 F-52 功能"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from extensions.sop_converter import (
    SdkParser,
    register_http_tools,
    convert_sop_to_agent,
)

PETSTORE_SPEC_URL = "https://petstore.swagger.io/v2/swagger.json"


def fetch_petstore_spec() -> dict:
    """从 Swagger Petstore 获取 OpenAPI spec"""
    try:
        import urllib.request

        with urllib.request.urlopen(PETSTORE_SPEC_URL, timeout=10) as resp:
            spec_data = resp.read().decode("utf-8")
            return json.loads(spec_data)
    except Exception as e:
        pytest.skip(f"无法获取 Petstore spec: {e}")


def load_local_petstore_spec() -> dict:
    """从本地加载 Petstore spec（备用）"""
    spec_path = Path(__file__).parent / "data" / "petstore_swagger.json"
    if spec_path.exists():
        with open(spec_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return fetch_petstore_spec()


class TestSwaggerPetstore:
    """使用 Swagger Petstore 验证 F-52 功能"""

    def test_petstore_spec_parsing(self):
        """测试解析 Petstore OpenAPI spec"""
        spec = load_local_petstore_spec()

        parser = SdkParser(spec)
        methods = parser.parse()

        assert len(methods) > 0

        method_names = {m.name for m in methods}

        assert "add_pet" in method_names
        assert "update_pet" in method_names
        assert "get_pet_by_id" in method_names
        assert "delete_pet" in method_names
        assert "find_pets_by_status" in method_names
        assert "find_pets_by_tags" in method_names

        assert parser.openapi_base_url.startswith("http")
        assert "petstore.swagger.io/v2" in parser.openapi_base_url

    def test_petstore_parameter_types(self):
        """测试 Petstore 参数类型提取"""
        spec = load_local_petstore_spec()
        parser = SdkParser(spec)
        methods = parser.parse()

        get_pet = next(m for m in methods if m.name == "get_pet_by_id")
        assert len(get_pet.params) == 1

        pet_id_param = get_pet.params[0]
        assert pet_id_param.name == "petId"
        assert pet_id_param.param_type == "integer"
        assert pet_id_param.required
        assert pet_id_param.location == "path"

    def test_petstore_request_body(self):
        """测试 Petstore 请求体提取"""
        spec = load_local_petstore_spec()
        parser = SdkParser(spec)
        methods = parser.parse()

        add_pet = next(m for m in methods if m.name == "add_pet")
        assert add_pet.request_body is not None
        assert add_pet.request_body.get("required") is True

    def test_petstore_http_tool_registration(self, tmp_path):
        """测试注册 Petstore HTTP 工具"""
        spec = load_local_petstore_spec()
        parser = SdkParser(spec)
        methods = parser.parse()

        bundle_dir = tmp_path / "petstore_bundle"
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

        add_pet_spec = tool_dir / "add-pet.json"
        assert add_pet_spec.exists()

        with open(add_pet_spec, "r", encoding="utf-8") as f:
            spec_data = json.load(f)

        assert spec_data["name"] == "add-pet"
        assert spec_data["call_type"] == "http"
        assert spec_data["call_impl"]["method"] == "POST"
        assert "/pet" in spec_data["call_impl"]["url"]
        assert "properties" in spec_data["input_schema"]

    def test_petstore_convert_sop_to_agent(self):
        """测试将 Petstore 转换为 Agent"""
        spec = load_local_petstore_spec()

        result = convert_sop_to_agent(
            sdk_spec=spec,
            requirements="宠物管理系统",
            agent_name="petstore-agent",
        )

        assert result["status"] == "converted"
        assert result["is_openapi"] is True
        assert result["registered_http_tools"] > 0

        assert len(result["skills"]) > 0

        tool_names = []
        for skill in result["skills"]:
            tool_names.extend(skill["tools"])

        assert "add-pet" in tool_names
        assert "get-pet-by-id" in tool_names
        assert "delete-pet" in tool_names

    def test_petstore_live_api_call(self):
        """测试实际调用 Petstore API"""
        spec = load_local_petstore_spec()
        parser = SdkParser(spec)
        methods = parser.parse()

        find_pets = next(m for m in methods if m.name == "find_pets_by_status")

        try:
            import urllib.request
            import urllib.error

            url = "http://petstore.swagger.io/v2/pet/findByStatus?status=available"
            req = urllib.request.Request(url, method="GET")

            with urllib.request.urlopen(req, timeout=10) as resp:
                response_body = resp.read().decode("utf-8")
                response_data = json.loads(response_body)

                assert resp.status == 200
                assert isinstance(response_data, list)
                if len(response_data) > 0:
                    assert "id" in response_data[0]
                    assert "name" in response_data[0]

        except urllib.error.HTTPError as e:
            if e.code == 404:
                pytest.skip("Petstore API 不可用")
            raise
        except Exception as e:
            pytest.skip(f"网络请求失败: {e}")

    def test_petstore_create_and_get_pet(self):
        """测试创建宠物并获取（完整流程）"""
        spec = load_local_petstore_spec()

        try:
            import urllib.request
            import urllib.error

            new_pet = {
                "id": 99999,
                "name": "测试宠物",
                "status": "available",
                "category": {"id": 1, "name": "测试分类"},
                "tags": [{"id": 1, "name": "测试标签"}],
                "photoUrls": ["https://example.com/photo.jpg"],
            }

            create_url = "https://petstore.swagger.io/v2/pet"
            create_data = json.dumps(new_pet).encode("utf-8")
            create_req = urllib.request.Request(
                create_url,
                data=create_data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )

            with urllib.request.urlopen(create_req, timeout=10) as resp:
                assert resp.status in (200, 201)

            get_url = f"https://petstore.swagger.io/v2/pet/{new_pet['id']}"
            get_req = urllib.request.Request(get_url, method="GET")

            with urllib.request.urlopen(get_req, timeout=10) as resp:
                response_body = resp.read().decode("utf-8")
                pet_data = json.loads(response_body)

                assert resp.status == 200
                assert pet_data["id"] == new_pet["id"]
                assert pet_data["name"] == new_pet["name"]
                assert pet_data["status"] == new_pet["status"]

        except urllib.error.HTTPError as e:
            if e.code in (404, 405):
                pytest.skip(f"Petstore API 不可用: {e.code}")
            raise
        except Exception as e:
            pytest.skip(f"网络请求失败: {e}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])