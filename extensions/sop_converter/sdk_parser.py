"""SdkParser — parses SDK interfaces into atomic tool specifications."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class SdkParam:
    """A parameter with type information extracted from OpenAPI spec."""

    name: str
    param_type: str = "string"
    required: bool = False
    description: str = ""
    location: str = "query"
    schema: dict | None = None


@dataclass(frozen=True)
class SdkMethod:
    """A single SDK method that maps to one atomic tool."""

    name: str
    description: str
    parameters: list[str] = field(default_factory=list)
    required_params: list[str] = field(default_factory=list)
    return_type: str | None = None
    original_class: str | None = None
    http_method: str | None = None
    http_path: str | None = None
    params: list[SdkParam] = field(default_factory=list)
    request_body: dict | None = None
    responses: dict[str, dict] = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)


@dataclass
class SdkParser:
    """Parse SDK/API specifications into a list of atomic tools.

    Supports multiple input formats:
      - OpenAPI/Swagger dict (from json.load or yaml.safe_load)
      - Python docstring format (Google or NumPy style)
      - Simple method list: "method1, method2, method3"

    The parser uses LLM-assisted extraction when the input is complex,
    otherwise falls back to regex-based extraction.
    """

    def __init__(self, sdk_spec: str | dict[str, Any], *, source: str = "manual") -> None:
        if isinstance(sdk_spec, str):
            self._raw = sdk_spec.strip()
        else:
            self._raw = sdk_spec
        self._source = source
        self._parsed: list[SdkMethod] | None = None
        self._openapi_base_url: str = ""

    @property
    def raw(self) -> str | dict[str, Any]:
        return self._raw

    @property
    def openapi_base_url(self) -> str:
        return self._openapi_base_url

    def parse(self) -> list[SdkMethod]:
        """Parse the SDK spec and return atomic tool specifications."""
        if self._parsed is not None:
            return self._parsed

        if isinstance(self._raw, dict):
            self._parsed = self._parse_openapi(self._raw)
        elif self._raw.startswith("http://") or self._raw.startswith("https://"):
            import json
            import urllib.request

            try:
                with urllib.request.urlopen(self._raw, timeout=30) as resp:
                    spec = json.loads(resp.read())
                self._parsed = self._parse_openapi(spec)
            except Exception:
                self._parsed = self._parse_simple_list(self._raw)
        elif self._raw.startswith("{"):
            import json

            try:
                spec = json.loads(self._raw)
                self._parsed = self._parse_openapi(spec)
            except json.JSONDecodeError:
                self._parsed = self._parse_simple_list(self._raw)
        else:
            from pathlib import Path

            file_path = Path(self._raw)
            if file_path.exists():
                import json

                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        spec = json.load(f)
                    self._parsed = self._parse_openapi(spec)
                except json.JSONDecodeError:
                    try:
                        import yaml

                        with open(file_path, "r", encoding="utf-8") as f:
                            spec = yaml.safe_load(f)
                        self._parsed = self._parse_openapi(spec)
                    except Exception:
                        self._parsed = self._parse_simple_list(self._raw)
            else:
                self._parsed = self._parse_simple_list(self._raw)

        return self._parsed

    def _parse_openapi(self, spec: dict[str, Any]) -> list[SdkMethod]:
        """Parse OpenAPI dict into SdkMethods with full schema information.
        
        Supports both OpenAPI 3.0 and Swagger 2.0 formats.
        """
        methods: list[SdkMethod] = []
        paths = spec.get("paths", {})
        components = spec.get("components", {})
        schemas = components.get("schemas", {})
        
        if not schemas:
            schemas = spec.get("definitions", {})
        
        base_url = self._extract_base_url(spec)
        self._openapi_base_url = base_url

        for path, path_methods in paths.items():
            for method_name, operation in path_methods.items():
                http_method = method_name.upper()
                if http_method not in ("GET", "POST", "PUT", "DELETE", "PATCH"):
                    continue

                operation_id = operation.get("operationId", f"{method_name}_{path}")
                safe_name = self._sanitize_name(operation_id)
                params = operation.get("parameters", [])
                sdk_params = self._parse_parameters(params, schemas)
                param_names = [p.name for p in sdk_params]
                required_params = [p.name for p in sdk_params if p.required]

                request_body = self._parse_request_body(operation, schemas)
                if not request_body:
                    request_body = self._parse_swagger_request_body(params, schemas)
                    
                responses = self._parse_responses(operation, schemas)
                tags = operation.get("tags", [])

                full_path = f"{base_url}{path}" if base_url else path

                methods.append(
                    SdkMethod(
                        name=safe_name,
                        description=operation.get("summary")
                        or operation.get("description", "")[:200],
                        parameters=param_names,
                        required_params=required_params,
                        return_type="json",
                        http_method=http_method,
                        http_path=full_path,
                        params=sdk_params,
                        request_body=request_body,
                        responses=responses,
                        tags=tags,
                    )
                )

        if not methods and schemas:
            for schema_name, schema in schemas.items():
                safe_name = self._sanitize_name(schema_name)
                properties = schema.get("properties", {})
                param_names = list(properties.keys())
                required_params = schema.get("required", [])

                methods.append(
                    SdkMethod(
                        name=safe_name,
                        description=f"Schema: {schema_name}",
                        parameters=param_names,
                        required_params=required_params,
                        original_class=schema_name,
                    )
                )

        return methods

    @staticmethod
    def _parse_swagger_request_body(
        params: list[dict[str, Any]], schemas: dict[str, Any]
    ) -> dict | None:
        """Parse request body from Swagger 2.0 parameters (in: body)."""
        body_params = [p for p in params if p.get("in") == "body"]
        if not body_params:
            return None

        body_param = body_params[0]
        schema = body_param.get("schema", {})
        resolved_schema = SdkParser._resolve_schema(schema, schemas)

        return {
            "description": body_param.get("description", ""),
            "required": body_param.get("required", False),
            "content": {
                "application/json": resolved_schema,
            },
        }

    @staticmethod
    def _extract_base_url(spec: dict[str, Any]) -> str:
        """Extract the base URL from OpenAPI spec.
        
        Supports both OpenAPI 3.0 (servers[0].url) and Swagger 2.0 (host + basePath + schemes).
        """
        servers = spec.get("servers", [])
        if servers:
            return servers[0].get("url", "")

        host = spec.get("host")
        base_path = spec.get("basePath", "")
        schemes = spec.get("schemes", ["http"])
        
        if host:
            scheme = schemes[0] if schemes else "http"
            return f"{scheme}://{host}{base_path}"
        
        return ""

    @staticmethod
    def _parse_parameters(
        params: list[dict[str, Any]], schemas: dict[str, Any]
    ) -> list[SdkParam]:
        """Parse OpenAPI/Swagger parameters into SdkParam objects with full type info.
        
        Supports both OpenAPI 3.0 (schema inside parameter) and Swagger 2.0 (type directly on parameter).
        """
        sdk_params: list[SdkParam] = []
        for param in params:
            name = param.get("name", "")
            location = param.get("in", "query")
            required = param.get("required", False)
            description = param.get("description", "")
            
            schema = param.get("schema", {})
            if not schema:
                schema = {k: v for k, v in param.items() if k in ("type", "format", "enum", "minimum", "maximum", "items", "$ref")}

            param_type = SdkParser._resolve_schema_type(schema, schemas)
            resolved_schema = SdkParser._resolve_schema(schema, schemas)

            sdk_params.append(
                SdkParam(
                    name=name,
                    param_type=param_type,
                    required=required,
                    description=description,
                    location=location,
                    schema=resolved_schema,
                )
            )
        return sdk_params

    @staticmethod
    def _parse_request_body(
        operation: dict[str, Any], schemas: dict[str, Any]
    ) -> dict | None:
        """Parse requestBody from operation."""
        request_body = operation.get("requestBody")
        if not request_body:
            return None

        content = request_body.get("content", {})
        schema_info = {}

        for media_type, media_info in content.items():
            schema = media_info.get("schema", {})
            resolved_schema = SdkParser._resolve_schema(schema, schemas)
            schema_info[media_type] = resolved_schema

        return {
            "description": request_body.get("description", ""),
            "required": request_body.get("required", False),
            "content": schema_info,
        }

    @staticmethod
    def _parse_responses(
        operation: dict[str, Any], schemas: dict[str, Any]
    ) -> dict[str, dict]:
        """Parse responses from operation."""
        responses = operation.get("responses", {})
        parsed: dict[str, dict] = {}

        for status_code, response in responses.items():
            content = response.get("content", {})
            schema_info = {}

            for media_type, media_info in content.items():
                schema = media_info.get("schema", {})
                resolved_schema = SdkParser._resolve_schema(schema, schemas)
                schema_info[media_type] = resolved_schema

            parsed[status_code] = {
                "description": response.get("description", ""),
                "content": schema_info,
            }

        return parsed

    @staticmethod
    def _resolve_schema_type(schema: dict[str, Any], schemas: dict[str, Any]) -> str:
        """Resolve the type of a schema, handling references."""
        if "$ref" in schema:
            ref_path = schema["$ref"].split("/")[-1]
            if ref_path in schemas:
                return SdkParser._resolve_schema_type(schemas[ref_path], schemas)

        if "type" in schema:
            return schema["type"]

        if "oneOf" in schema or "anyOf" in schema:
            return "object"

        if "items" in schema:
            return "array"

        return "string"

    @staticmethod
    def _resolve_schema(schema: dict[str, Any], schemas: dict[str, Any]) -> dict:
        """Resolve a schema recursively, expanding references."""
        if not isinstance(schema, dict):
            return {}

        result = dict(schema)

        if "$ref" in result:
            ref_path = result["$ref"].split("/")[-1]
            if ref_path in schemas:
                resolved = SdkParser._resolve_schema(schemas[ref_path], schemas)
                result.pop("$ref")
                result.update(resolved)

        if "items" in result and isinstance(result["items"], dict):
            result["items"] = SdkParser._resolve_schema(result["items"], schemas)

        if "properties" in result and isinstance(result["properties"], dict):
            for prop_name, prop_schema in result["properties"].items():
                result["properties"][prop_name] = SdkParser._resolve_schema(
                    prop_schema, schemas
                )

        if "allOf" in result:
            combined: dict[str, Any] = {}
            for sub_schema in result["allOf"]:
                resolved = SdkParser._resolve_schema(sub_schema, schemas)
                combined.update(resolved)
            result.pop("allOf")
            result.update(combined)

        return result

    def _parse_simple_list(self, spec: str) -> list[SdkMethod]:
        """Parse simple comma/newline separated method list."""
        methods: list[SdkMethod] = []
        method_names = re.split(r"[,\n]+", spec)
        for raw in method_names:
            name = raw.strip()
            if not name or name.startswith("#"):
                continue
            safe_name = self._sanitize_name(name)
            methods.append(
                SdkMethod(
                    name=safe_name,
                    description=f"SDK method: {name}",
                    parameters=[],
                    required_params=[],
                )
            )
        return methods

    @staticmethod
    def _sanitize_name(name: str) -> str:
        """Convert a method name to a valid tool name (kebab-case)."""
        name = re.sub(r"[/{}<>\[\]]", "_", name)
        name = re.sub(r"([A-Z])", lambda m: f"_{m.group(1).lower()}", name)
        name = re.sub(r"_+", "_", name)
        name = name.strip("_").lower()
        if not name:
            return "sdk_method"
        return name


@dataclass
class SdkParseResult:
    """Result of parsing an SDK spec."""

    methods: list[SdkMethod]
    source: str
    errors: list[str] = field(default_factory=list)


def parse_sdk_spec(spec: str | dict[str, Any], *, source: str = "manual") -> SdkParseResult:
    """Convenience function to parse an SDK spec and return structured result."""
    parser = SdkParser(spec, source=source)
    try:
        methods = parser.parse()
        return SdkParseResult(methods=methods, source=source)
    except Exception as exc:
        return SdkParseResult(methods=[], source=source, errors=[str(exc)])
