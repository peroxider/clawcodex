"""Tests for Pydantic- and dataclass-aware JSON Schema generation in pos convert."""

from __future__ import annotations

import tempfile
import textwrap
import unittest
from pathlib import Path

from extensions.sop_converter.source_parser import ParamSpec, SourceOperation
from extensions.sop_converter.tool_registry_bridge import operation_to_spec
from extensions.sop_converter.type_schema import (
    param_to_json_schema_property,
    pydantic_schema_for_type,
)

_JIUWEN_AGENT_ROOT = Path(__file__).resolve().parents[2].parent / "JiuwenAgent"


class TestTypeSchemaPydantic(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self._tmpdir.name)
        pkg = self.root / "demo_models"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("", encoding="utf-8")
        (pkg / "team.py").write_text(
            textwrap.dedent(
                '''
                from pydantic import BaseModel, Field


                class TeamCard(BaseModel):
                    id: str = Field(description="Team id")
                    name: str
                    description: str = ""
                '''
            ),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    def test_pydantic_schema_includes_properties_and_example(self) -> None:
        schema = pydantic_schema_for_type(str(self.root), "TeamCard")
        self.assertIsNotNone(schema)
        assert schema is not None
        self.assertIn("properties", schema)
        self.assertIn("id", schema["properties"])
        self.assertIn("examples", schema)
        self.assertEqual(schema["examples"][0]["id"], "")

    def test_operation_to_spec_uses_pydantic_schema(self) -> None:
        op = SourceOperation(
            name="make_team",
            description="Make a team session.",
            parameters=[
                ParamSpec(
                    name="card",
                    type_hint="TeamCard",
                    required=True,
                    description="Team identity card",
                )
            ],
            file_stem="teams",
        )
        spec = operation_to_spec(
            op,
            source_dir=str(self.root),
            script_path="/tmp/fake_script.py",
            comp_name="demo",
        )
        card = spec.input_schema["properties"]["card"]
        self.assertIn("properties", card)
        self.assertIn("examples", card)
        self.assertEqual(card["properties"]["name"]["type"], "string")


class TestTypeSchemaDataclass(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self._tmpdir.name)
        pkg = self.root / "demo_models"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("", encoding="utf-8")
        (pkg / "config.py").write_text(
            textwrap.dedent(
                '''
                from dataclasses import dataclass, field

                from pydantic import BaseModel, Field


                class EndpointInfo(BaseModel):
                    api_key: str = Field(default="")
                    api_base: str = Field(min_length=1)
                    model_name: str = Field(default="", alias="model")


                @dataclass
                class ModelConfig:
                    model_provider: str
                    model_info: EndpointInfo = field(default_factory=EndpointInfo)
                '''
            ),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    def test_dataclass_schema_includes_nested_pydantic_fields(self) -> None:
        schema = pydantic_schema_for_type(str(self.root), "ModelConfig")
        self.assertIsNotNone(schema)
        assert schema is not None
        self.assertEqual(schema["type"], "object")
        self.assertIn("model_provider", schema["properties"])
        self.assertIn("model_info", schema["properties"])
        self.assertEqual(schema["required"], ["model_provider"])
        model_info = schema["properties"]["model_info"]
        self.assertIn("properties", model_info)
        self.assertIn("api_base", model_info["properties"])
        self.assertIn("examples", schema)
        self.assertEqual(schema["examples"][0]["model_provider"], "")

    def test_param_model_config_is_object_not_string(self) -> None:
        prop = param_to_json_schema_property(
            type_hint="ModelConfig",
            source_dir=str(self.root),
            fallback_json_type="string",
        )
        self.assertEqual(prop["type"], "object")
        self.assertIn("properties", prop)
        self.assertIn("model_provider", prop["properties"])
        self.assertNotEqual(prop.get("type"), "string")

    def test_operation_to_spec_model_param_is_structured(self) -> None:
        op = SourceOperation(
            name="create_agent_config",
            description="Create agent config.",
            parameters=[
                ParamSpec(
                    name="model",
                    type_hint="ModelConfig",
                    required=True,
                    description="LLM model configuration",
                )
            ],
            file_stem="config",
        )
        spec = operation_to_spec(
            op,
            source_dir=str(self.root),
            script_path="/tmp/fake_script.py",
            comp_name="demo",
        )
        model = spec.input_schema["properties"]["model"]
        self.assertEqual(model["type"], "object")
        self.assertIn("model_info", model["properties"])


@unittest.skipUnless(
    (_JIUWEN_AGENT_ROOT / "openjiuwen" / "core" / "foundation" / "llm" / "schema" / "mode_info.py").is_file(),
    "JiuwenAgent checkout not available",
)
class TestJiuwenModelConfigSchema(unittest.TestCase):
    def test_jiuwen_model_config_schema(self) -> None:
        prop = param_to_json_schema_property(
            type_hint="ModelConfig",
            source_dir=str(_JIUWEN_AGENT_ROOT),
            fallback_json_type="string",
        )
        self.assertEqual(prop["type"], "object")
        self.assertIn("model_provider", prop["properties"])
        self.assertIn("model_info", prop["properties"])
        model_info = prop["properties"]["model_info"]
        self.assertIn("properties", model_info)
        self.assertIn("api_base", model_info["properties"])


if __name__ == "__main__":
    unittest.main()
