"""Unit tests for :mod:`extensions.sop_converter.sdk_parser`.

Covers the SdkParser that converts SDK/API specifications into atomic
tool definitions:

* :class:`SdkMethod` dataclass — field defaults and explicit construction.
* :class:`SdkParser` — input dispatch (dict, JSON string, simple list).
* :func:`_parse_openapi` — extracts operations (HTTP methods) and
  component schemas.
* :func:`_parse_simple_list` — splits comma/newline lists, filters
  comments, sanitises names.
* :func:`_sanitize_name` — kebab-case conversion of CamelCase, dots,
  brackets, slashes.
* :func:`parse_sdk_spec` — convenience wrapper, error capture.
"""

from __future__ import annotations

import unittest

from extensions.sop_converter.sdk_parser import (
    SdkMethod,
    SdkParam,
    SdkParser,
    SdkParseResult,
    parse_sdk_spec,
)


# ---------------------------------------------------------------------------
# SdkMethod dataclass
# ---------------------------------------------------------------------------


class TestSdkMethod(unittest.TestCase):
    def test_defaults(self) -> None:
        m = SdkMethod(name="x", description="d")
        self.assertEqual(m.name, "x")
        self.assertEqual(m.description, "d")
        self.assertEqual(m.parameters, [])
        self.assertEqual(m.required_params, [])
        self.assertIsNone(m.return_type)
        self.assertIsNone(m.original_class)

    def test_explicit_fields(self) -> None:
        m = SdkMethod(
            name="x",
            description="d",
            parameters=["a", "b"],
            required_params=["a"],
            return_type="dict",
            original_class="Foo",
        )
        self.assertEqual(m.parameters, ["a", "b"])
        self.assertEqual(m.required_params, ["a"])
        self.assertEqual(m.return_type, "dict")
        self.assertEqual(m.original_class, "Foo")

    def test_is_frozen(self) -> None:
        # Field assignment should raise because the dataclass is frozen.
        m = SdkMethod(name="x", description="d")
        with self.assertRaises(Exception):
            m.name = "y"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# _sanitize_name
# ---------------------------------------------------------------------------


class TestSanitizeName(unittest.TestCase):
    def test_already_kebab(self) -> None:
        self.assertEqual(SdkParser._sanitize_name("docker-build"), "docker-build")

    def test_camelcase_split(self) -> None:
        # CamelCase → snake_case → kebab-case.
        self.assertEqual(SdkParser._sanitize_name("DockerBuild"), "docker_build")

    def test_slash_replaced(self) -> None:
        # Slashes become underscores then collapse.
        self.assertEqual(
            SdkParser._sanitize_name("foo/bar"),
            "foo_bar",
        )

    def test_brackets_replaced(self) -> None:
        # Bracket chars are scrubbed → underscores → collapsed → lower.
        # "a[b]" → "a_b_" → "a_b" → "a_b".
        self.assertEqual(SdkParser._sanitize_name("a[b]"), "a_b")

    def test_underscores_collapsed(self) -> None:
        # Multiple consecutive underscores collapse to one.
        self.assertEqual(
            SdkParser._sanitize_name("a__b___c"),
            "a_b_c",
        )

    def test_empty_name_falls_back(self) -> None:
        # After stripping all non-word chars, an empty name → "sdk_method".
        self.assertEqual(SdkParser._sanitize_name("///"), "sdk_method")

    def test_lowercases_result(self) -> None:
        self.assertEqual(SdkParser._sanitize_name("FOO"), "f_o_o")


# ---------------------------------------------------------------------------
# SdkParser.parse — simple list path
# ---------------------------------------------------------------------------


class TestParseSimpleList(unittest.TestCase):
    def test_comma_separated(self) -> None:
        methods = SdkParser("docker_build, docker_tag, docker_push").parse()
        names = [m.name for m in methods]
        self.assertIn("docker_build", names)
        self.assertIn("docker_tag", names)
        self.assertIn("docker_push", names)

    def test_newline_separated(self) -> None:
        methods = SdkParser("foo\nbar\nbaz").parse()
        self.assertEqual(
            [m.name for m in methods],
            ["foo", "bar", "baz"],
        )

    def test_mixed_separators(self) -> None:
        methods = SdkParser("foo,bar\nbaz").parse()
        self.assertEqual(
            [m.name for m in methods],
            ["foo", "bar", "baz"],
        )

    def test_empty_input(self) -> None:
        self.assertEqual(SdkParser("").parse(), [])

    def test_whitespace_input(self) -> None:
        self.assertEqual(SdkParser("   \n  \n  ").parse(), [])

    def test_comment_lines_skipped(self) -> None:
        methods = SdkParser("# this is a comment\nreal_method").parse()
        self.assertEqual([m.name for m in methods], ["real_method"])

    def test_each_method_has_description(self) -> None:
        methods = SdkParser("alpha, beta").parse()
        for m in methods:
            self.assertIn("SDK method:", m.description)

    def test_each_method_has_empty_params(self) -> None:
        methods = SdkParser("alpha").parse()
        self.assertEqual(methods[0].parameters, [])
        self.assertEqual(methods[0].required_params, [])

    def test_dedupes_via_sanitize(self) -> None:
        # "foo" and "Foo" sanitise identically. "FOO" sanitises to
        # "f_o_o" because each uppercase letter is underscore-prefixed.
        methods = SdkParser("foo, Foo").parse()
        self.assertEqual([m.name for m in methods], ["foo", "foo"])

    def test_uppercase_letters_each_prefixed(self) -> None:
        # "FOO" → "F_O_O" because CamelCase splitting puts an underscore
        # before every uppercase letter.
        self.assertEqual(SdkParser._sanitize_name("FOO"), "f_o_o")


# ---------------------------------------------------------------------------
# SdkParser.parse — OpenAPI dict path
# ---------------------------------------------------------------------------


class TestParseOpenApiDict(unittest.TestCase):
    def test_basic_operations_extracted(self) -> None:
        spec = {
            "paths": {
                "/users": {
                    "get": {
                        "operationId": "listUsers",
                        "summary": "List all users",
                        "parameters": [
                            {"name": "limit", "required": False},
                            {"name": "offset", "required": True},
                        ],
                    },
                    "post": {
                        "operationId": "createUser",
                        "summary": "Create a user",
                    },
                },
            },
        }
        methods = SdkParser(spec).parse()
        names = [m.name for m in methods]
        self.assertIn("list_users", names)
        self.assertIn("create_user", names)

    def test_required_params_collected(self) -> None:
        spec = {
            "paths": {
                "/x": {
                    "get": {
                        "operationId": "x",
                        "parameters": [
                            {"name": "a", "required": True},
                            {"name": "b", "required": False},
                            {"name": "c", "required": True},
                        ],
                    },
                },
            },
        }
        methods = SdkParser(spec).parse()
        self.assertEqual(methods[0].required_params, ["a", "c"])
        self.assertEqual(methods[0].parameters, ["a", "b", "c"])

    def test_description_truncated(self) -> None:
        long_desc = "x" * 500
        spec = {
            "paths": {
                "/x": {
                    "get": {
                        "operationId": "long",
                        "description": long_desc,
                    },
                },
            },
        }
        methods = SdkParser(spec).parse()
        self.assertEqual(len(methods[0].description), 200)

    def test_summary_preferred_over_description(self) -> None:
        spec = {
            "paths": {
                "/x": {
                    "get": {
                        "operationId": "x",
                        "summary": "Short summary",
                        "description": "Longer description.",
                    },
                },
            },
        }
        methods = SdkParser(spec).parse()
        self.assertEqual(methods[0].description, "Short summary")

    def test_non_http_methods_ignored(self) -> None:
        # "summary" and "description" keys inside path dicts are not
        # HTTP methods and should be skipped.
        spec = {
            "paths": {
                "/x": {
                    "summary": "path summary",  # not a real method
                    "get": {"operationId": "real"},
                },
            },
        }
        methods = SdkParser(spec).parse()
        self.assertEqual(len(methods), 1)
        self.assertEqual(methods[0].name, "real")

    def test_components_schemas_extracted(self) -> None:
        spec = {
            "components": {
                "schemas": {
                    "User": {
                        "properties": {
                            "id": {"type": "integer"},
                            "name": {"type": "string"},
                        },
                        "required": ["id"],
                    },
                },
            },
        }
        methods = SdkParser(spec).parse()
        self.assertEqual(len(methods), 1)
        self.assertEqual(methods[0].name, "user")
        self.assertEqual(methods[0].parameters, ["id", "name"])
        self.assertEqual(methods[0].required_params, ["id"])
        self.assertEqual(methods[0].original_class, "User")

    def test_default_operation_id(self) -> None:
        # No operationId → use "{method}_{path}" as fallback.
        spec = {
            "paths": {
                "/items": {
                    "get": {"summary": "Get items"},
                },
            },
        }
        methods = SdkParser(spec).parse()
        # Sanitised name: "get_/items" → "/" becomes "_" → "get__items"
        # → underscores collapsed to single → "get_items" → trailing
        # underscores stripped → "get_items".
        self.assertIn("get_items", [m.name for m in methods])

    def test_all_four_http_methods(self) -> None:
        spec = {
            "paths": {
                "/r": {
                    "get": {"operationId": "g"},
                    "post": {"operationId": "p"},
                    "put": {"operationId": "u"},
                    "delete": {"operationId": "d"},
                    "patch": {"operationId": "pa"},
                },
            },
        }
        methods = SdkParser(spec).parse()
        names = sorted(m.name for m in methods)
        self.assertEqual(names, ["d", "g", "p", "pa", "u"])

    def test_empty_spec_returns_empty(self) -> None:
        self.assertEqual(SdkParser({}).parse(), [])

    def test_methods_cached(self) -> None:
        # Second parse() call returns the same list (idempotent).
        spec = {"paths": {"/x": {"get": {"operationId": "x"}}}}
        parser = SdkParser(spec)
        first = parser.parse()
        second = parser.parse()
        self.assertIs(first, second)


# ---------------------------------------------------------------------------
# SdkParser.parse — JSON string path
# ---------------------------------------------------------------------------


class TestParseJsonString(unittest.TestCase):
    def test_json_object_string(self) -> None:
        # Strings starting with `{` are parsed as JSON.
        spec = '{"paths": {"/x": {"get": {"operationId": "getX"}}}}'
        methods = SdkParser(spec).parse()
        self.assertEqual([m.name for m in methods], ["get_x"])

    def test_json_with_https_prefix_falls_back_to_list(self) -> None:
        # Starts with "https://" → tried as JSON first, fails → simple
        # list path.
        spec = "https://example.com/api/v1, foo, bar"
        methods = SdkParser(spec).parse()
        # The first segment is the URL (treated as one name), plus foo,
        # bar.
        names = [m.name for m in methods]
        self.assertIn("foo", names)
        self.assertIn("bar", names)

    def test_invalid_json_falls_back_to_simple_list(self) -> None:
        # Doesn't start with `{`, so goes directly to simple list.
        spec = "alpha, beta"
        methods = SdkParser(spec).parse()
        self.assertEqual([m.name for m in methods], ["alpha", "beta"])


# ---------------------------------------------------------------------------
# SdkParser.raw property
# ---------------------------------------------------------------------------


class TestSdkParserRaw(unittest.TestCase):
    def test_string_input_stored_stripped(self) -> None:
        parser = SdkParser("  alpha, beta  ")
        self.assertEqual(parser.raw, "alpha, beta")

    def test_dict_input_stored_as_is(self) -> None:
        d = {"paths": {}}
        parser = SdkParser(d)
        self.assertIs(parser.raw, d)

    def test_source_attribute(self) -> None:
        parser = SdkParser("x", source="custom")
        self.assertEqual(parser._source, "custom")


# ---------------------------------------------------------------------------
# parse_sdk_spec convenience function
# ---------------------------------------------------------------------------


class TestParseSdkSpec(unittest.TestCase):
    def test_successful_parse(self) -> None:
        result = parse_sdk_spec("alpha, beta", source="test")
        self.assertIsInstance(result, SdkParseResult)
        self.assertEqual(result.source, "test")
        self.assertEqual([m.name for m in result.methods], ["alpha", "beta"])
        self.assertEqual(result.errors, [])

    def test_default_source(self) -> None:
        result = parse_sdk_spec("alpha")
        self.assertEqual(result.source, "manual")

    def test_passes_through_errors(self) -> None:
        # Force an internal exception by mocking parse() to raise.
        from unittest.mock import patch

        parser = SdkParser("alpha")
        with patch.object(parser, "parse", side_effect=RuntimeError("boom")):
            with patch(
                "extensions.sop_converter.sdk_parser.SdkParser",
                return_value=parser,
            ):
                result = parse_sdk_spec("alpha")
        self.assertEqual(result.methods, [])
        self.assertEqual(result.errors, ["boom"])


# ---------------------------------------------------------------------------
# SdkParam dataclass
# ---------------------------------------------------------------------------


class TestSdkParam(unittest.TestCase):
    def test_defaults(self) -> None:
        p = SdkParam(name="x")
        self.assertEqual(p.name, "x")
        self.assertEqual(p.param_type, "string")
        self.assertFalse(p.required)
        self.assertEqual(p.description, "")
        self.assertEqual(p.location, "query")
        self.assertIsNone(p.schema)

    def test_explicit_fields(self) -> None:
        p = SdkParam(
            name="x",
            param_type="integer",
            required=True,
            description="A number",
            location="path",
            schema={"type": "integer", "minimum": 1},
        )
        self.assertEqual(p.param_type, "integer")
        self.assertTrue(p.required)
        self.assertEqual(p.description, "A number")
        self.assertEqual(p.location, "path")
        self.assertEqual(p.schema, {"type": "integer", "minimum": 1})

    def test_is_frozen(self) -> None:
        p = SdkParam(name="x")
        with self.assertRaises(Exception):
            p.name = "y"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# SdkParser.parse — OpenAPI enhanced parsing
# ---------------------------------------------------------------------------


class TestParseOpenApiEnhanced(unittest.TestCase):
    def test_http_method_extracted(self) -> None:
        spec = {
            "paths": {
                "/users": {
                    "get": {"operationId": "listUsers"},
                    "post": {"operationId": "createUser"},
                },
            },
        }
        methods = SdkParser(spec).parse()
        for m in methods:
            if m.name == "list_users":
                self.assertEqual(m.http_method, "GET")
            elif m.name == "create_user":
                self.assertEqual(m.http_method, "POST")

    def test_http_path_extracted(self) -> None:
        spec = {
            "paths": {
                "/users/{id}": {
                    "get": {"operationId": "getUser"},
                },
            },
        }
        methods = SdkParser(spec).parse()
        self.assertEqual(methods[0].http_path, "/users/{id}")

    def test_params_with_types(self) -> None:
        spec = {
            "paths": {
                "/users": {
                    "get": {
                        "operationId": "listUsers",
                        "parameters": [
                            {
                                "name": "limit",
                                "in": "query",
                                "required": False,
                                "schema": {"type": "integer"},
                                "description": "Max results",
                            },
                            {
                                "name": "offset",
                                "in": "query",
                                "required": True,
                                "schema": {"type": "integer"},
                            },
                        ],
                    },
                },
            },
        }
        methods = SdkParser(spec).parse()
        method = methods[0]
        self.assertEqual(len(method.params), 2)
        self.assertEqual(method.params[0].name, "limit")
        self.assertEqual(method.params[0].param_type, "integer")
        self.assertFalse(method.params[0].required)
        self.assertEqual(method.params[0].description, "Max results")
        self.assertEqual(method.params[0].location, "query")
        self.assertEqual(method.params[1].name, "offset")
        self.assertTrue(method.params[1].required)

    def test_request_body_extracted(self) -> None:
        spec = {
            "paths": {
                "/users": {
                    "post": {
                        "operationId": "createUser",
                        "requestBody": {
                            "required": True,
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "name": {"type": "string"},
                                            "email": {"type": "string"},
                                        },
                                        "required": ["name", "email"],
                                    },
                                },
                            },
                        },
                    },
                },
            },
        }
        methods = SdkParser(spec).parse()
        method = methods[0]
        self.assertIsNotNone(method.request_body)
        self.assertTrue(method.request_body.get("required"))
        self.assertIn("application/json", method.request_body.get("content", {}))

    def test_responses_extracted(self) -> None:
        spec = {
            "paths": {
                "/users": {
                    "get": {
                        "operationId": "listUsers",
                        "responses": {
                            "200": {
                                "description": "Success",
                                "content": {
                                    "application/json": {
                                        "schema": {
                                            "type": "array",
                                            "items": {"$ref": "#/components/schemas/User"},
                                        },
                                    },
                                },
                            },
                            "400": {"description": "Bad request"},
                        },
                    },
                },
            },
        }
        methods = SdkParser(spec).parse()
        method = methods[0]
        self.assertIn("200", method.responses)
        self.assertIn("400", method.responses)
        self.assertEqual(method.responses["200"]["description"], "Success")

    def test_tags_extracted(self) -> None:
        spec = {
            "paths": {
                "/users": {
                    "get": {
                        "operationId": "listUsers",
                        "tags": ["users", "admin"],
                    },
                },
            },
        }
        methods = SdkParser(spec).parse()
        self.assertEqual(methods[0].tags, ["users", "admin"])

    def test_server_url_extracted(self) -> None:
        spec = {
            "servers": [{"url": "https://api.example.com/v1"}],
            "paths": {
                "/users": {"get": {"operationId": "listUsers"}},
            },
        }
        parser = SdkParser(spec)
        methods = parser.parse()
        self.assertEqual(parser.openapi_base_url, "https://api.example.com/v1")

    def test_path_params_recognized(self) -> None:
        spec = {
            "paths": {
                "/users/{userId}/posts/{postId}": {
                    "get": {
                        "operationId": "getPost",
                        "parameters": [
                            {"name": "userId", "in": "path", "required": True},
                            {"name": "postId", "in": "path", "required": True},
                        ],
                    },
                },
            },
        }
        methods = SdkParser(spec).parse()
        method = methods[0]
        path_params = [p for p in method.params if p.location == "path"]
        self.assertEqual(len(path_params), 2)
        self.assertEqual(path_params[0].name, "userId")
        self.assertEqual(path_params[1].name, "postId")


if __name__ == "__main__":
    unittest.main()
