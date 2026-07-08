"""Seed entries for the LKB engineering method library (F-150).

This file ships the canonical :data:`SEED_METHODS` tuple referenced by
:mod:`clawcodex_ext.logical_kanban.method_library`.  Each method is a
reusable decomposition template covering a common software-engineering
pattern. Methods are deliberately technology-agnostic — they describe a
*pattern* (e.g. "add a CLI command"), not a concrete technology stack.

This module is intentionally dependency-light — it does not import
:mod:`method_library` directly, which would create a circular import.
Instead, :mod:`method_library` calls :func:`build_seed_methods` after
its dataclasses have been defined.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from .method_library import AcceptanceTemplate, EngineeringMethod, SubtaskTemplate


# Helpers are defined inside build_seed_methods below to avoid a circular
# import with method_library.py.


def build_seed_methods(  # type: ignore[no-untyped-def]
    engineering_method_cls,
    subtask_template_cls,
    acceptance_template_cls,
) -> tuple:
    """Construct the canonical seed library.

    Parameters are the dataclass types from :mod:`method_library`. The function
    returns a tuple of :class:`EngineeringMethod` instances and is called from
    :mod:`method_library` after the dataclasses are defined, which keeps both
    modules free of circular imports.
    """

    EngineeringMethod = engineering_method_cls
    SubtaskTemplate = subtask_template_cls
    AcceptanceTemplate = acceptance_template_cls

    def _t(
        template_id,
        role,
        subject_template,
        description_template="",
        acceptance_template="",
        default_blocked_by=(),
    ):
        return SubtaskTemplate(
            template_id=template_id,
            role=role,
            subject_template=subject_template,
            description_template=description_template,
            acceptance_template=acceptance_template,
            default_blocked_by=default_blocked_by,
        )

    def _a(assertion_template, proof_template="", strict_acceptance=False):
        return AcceptanceTemplate(
            assertion_template=assertion_template,
            proof_template=proof_template,
            strict_acceptance=strict_acceptance,
        )

    # ---------------------------------------------------------------------------
    # add_* — additive patterns (5)
    # ---------------------------------------------------------------------------

    _M_ADD_API_ENDPOINT = EngineeringMethod(
        method_id="M-add-api-endpoint-001",
        pattern="add_api_endpoint",
        description=(
            "Add a new HTTP endpoint to an existing service: design the contract, "
            "implement the handler, document and verify it."
        ),
        tags=("additive", "api", "http"),
        preconditions=("route_registry_exists",),
        assumptions=("framework_supports_routes", "auth_layer_present"),
        subtask_templates=(
            _t(
                "endpoint-design",
                "design",
                "Design endpoint contract",
                "Decide HTTP method, path, request/response schema, status codes, "
                "auth requirements, and rate-limit policy. Update the OpenAPI spec.",
                "OpenAPI spec entry exists with stable schema.",
                default_blocked_by=(),
            ),
            _t(
                "endpoint-impl",
                "impl",
                "Implement endpoint handler",
                "Wire the route into the router, implement the handler, validate "
                "inputs, and emit structured errors.",
                "Endpoint responds 200 on the happy path and 4xx/5xx with a "
                "structured error body on failure.",
                default_blocked_by=("endpoint-design",),
            ),
            _t(
                "endpoint-test",
                "test",
                "Add endpoint tests",
                "Cover happy path, validation errors, auth failures, and the "
                "documented rate-limit boundary.",
                "Test suite passes; coverage of the new route ≥ 90%.",
                default_blocked_by=("endpoint-impl",),
            ),
            _t(
                "endpoint-docs",
                "docs",
                "Document endpoint",
                "Update API reference, changelog, and any client examples.",
                "Reference page published; changelog entry added.",
                default_blocked_by=("endpoint-test",),
            ),
        ),
        acceptance_template=_a(
            assertion_template="EndpointContractStable({route})",
            proof_template="OpenAPI entry matches handler output for {route}",
            strict_acceptance=True,
        ),
    )

    _M_ADD_MIDDLEWARE = EngineeringMethod(
        method_id="M-add-middleware-001",
        pattern="add_middleware",
        description=(
            "Add a middleware/interceptor to an existing service: pick the hook "
            "points, wire the implementation, verify ordering, and document the "
            "lifecycle."
        ),
        tags=("additive", "middleware", "lifecycle"),
        preconditions=("middleware_chain_exists",),
        assumptions=("framework_supports_middleware",),
        subtask_templates=(
            _t(
                "middleware-design",
                "design",
                "Design middleware contract",
                "Define inputs, outputs, short-circuit semantics, error handling, "
                "and ordering constraints.",
                "Design doc lists hook point and ordering invariants.",
                default_blocked_by=(),
            ),
            _t(
                "middleware-impl",
                "impl",
                "Implement middleware",
                "Add the middleware module, register it at the chosen hook point, "
                "and emit structured logs/metrics.",
                "Middleware is registered and emits at least one log line / metric.",
                default_blocked_by=("middleware-design",),
            ),
            _t(
                "middleware-test",
                "test",
                "Add middleware tests",
                "Cover the happy path, short-circuit, ordering, and error propagation.",
                "Tests pass; ordering regression test exists.",
                default_blocked_by=("middleware-impl",),
            ),
            _t(
                "middleware-docs",
                "docs",
                "Document middleware",
                "Document the hook point, ordering, configuration knobs, and failure modes.",
                "Docs published with at least one example.",
                default_blocked_by=("middleware-test",),
            ),
        ),
        acceptance_template=_a(
            assertion_template="MiddlewareOrderingPreserved({hook})",
            strict_acceptance=True,
        ),
    )

    _M_ADD_CLI_COMMAND = EngineeringMethod(
        method_id="M-add-cli-command-001",
        pattern="add_cli_command",
        description=(
            "Add a new command to an existing CLI: design flags, wire the handler, "
            "exercise it, and document usage."
        ),
        tags=("additive", "cli"),
        preconditions=("cli_dispatcher_exists",),
        assumptions=("help_text_generated_automatically",),
        subtask_templates=(
            _t(
                "cli-design",
                "design",
                "Design command surface",
                "Decide subcommand name, flags, positional args, exit codes, and "
                "stderr vs stdout usage.",
                "Design doc covers flags and exit codes.",
                default_blocked_by=(),
            ),
            _t(
                "cli-impl",
                "impl",
                "Implement command handler",
                "Wire the subcommand, parse arguments, and return a documented exit code.",
                "Command exits 0 on success and non-zero with stderr on error.",
                default_blocked_by=("cli-design",),
            ),
            _t(
                "cli-test",
                "test",
                "Add command tests",
                "Cover happy path, missing-flag errors, and the failure exit path.",
                "Test suite covers all flag combinations.",
                default_blocked_by=("cli-impl",),
            ),
            _t(
                "cli-docs",
                "docs",
                "Document command",
                "Add usage examples and reference the new subcommand in the command index.",
                "Reference page published with at least one example invocation.",
                default_blocked_by=("cli-test",),
            ),
        ),
        acceptance_template=_a(
            assertion_template="CliCommandRegistered({name})",
            strict_acceptance=False,
        ),
    )

    _M_ADD_CONFIG_OPTION = EngineeringMethod(
        method_id="M-add-config-option-001",
        pattern="add_config_option",
        description=(
            "Add a new configuration option: define schema, wire load logic, "
            "add tests, document defaults."
        ),
        tags=("additive", "config"),
        preconditions=("config_loader_exists",),
        assumptions=("schema_validation_present",),
        subtask_templates=(
            _t(
                "config-design",
                "design",
                "Design config option",
                "Decide key, type, default, validation rule, and where the option is read.",
                "Schema entry exists with default + validator.",
                default_blocked_by=(),
            ),
            _t(
                "config-impl",
                "impl",
                "Wire config option",
                "Surface the option through the loader and any consumer code.",
                "Option is read at the documented hook point.",
                default_blocked_by=("config-design",),
            ),
            _t(
                "config-test",
                "test",
                "Add config tests",
                "Cover default, valid override, and invalid value rejection.",
                "Tests pass; rejection test asserts non-zero exit / 4xx response.",
                default_blocked_by=("config-impl",),
            ),
            _t(
                "config-docs",
                "docs",
                "Document config option",
                "Document the option in the configuration reference with default "
                "and example value.",
                "Reference page published.",
                default_blocked_by=("config-test",),
            ),
        ),
        acceptance_template=_a(
            assertion_template="ConfigOptionLoaded({key})",
            strict_acceptance=False,
        ),
    )

    _M_ADD_METRIC = EngineeringMethod(
        method_id="M-add-metric-001",
        pattern="add_metric",
        description=(
            "Add a new metric (counter / gauge / histogram): design labels, wire "
            "the instrumentation, verify dashboards, document SLOs."
        ),
        tags=("additive", "observability", "metric"),
        preconditions=("metrics_registry_exists",),
        assumptions=("metric_backend_is_prometheus",),
        subtask_templates=(
            _t(
                "metric-design",
                "design",
                "Design metric",
                "Pick type, name, label cardinality, units, and bucket layout (for histograms).",
                "Design doc lists name, type, labels, and rationale.",
                default_blocked_by=(),
            ),
            _t(
                "metric-impl",
                "impl",
                "Instrument metric",
                "Register the metric, emit it at the documented hook points, and "
                "guard label cardinality.",
                "Metric shows up in the scrape endpoint with the expected type.",
                default_blocked_by=("metric-design",),
            ),
            _t(
                "metric-test",
                "test",
                "Add metric tests",
                "Cover that the metric is emitted under documented conditions "
                "and NOT emitted in the negation path.",
                "Test asserts metric value changes after the documented trigger.",
                default_blocked_by=("metric-impl",),
            ),
            _t(
                "metric-docs",
                "docs",
                "Document metric",
                "Document the metric name, type, labels, and any associated SLO.",
                "Runbook / dashboard updated.",
                default_blocked_by=("metric-test",),
            ),
        ),
        acceptance_template=_a(
            assertion_template="MetricEmitted({name})",
            strict_acceptance=False,
        ),
    )

    # ---------------------------------------------------------------------------
    # fix_* — corrective patterns (4)
    # ---------------------------------------------------------------------------

    _M_FIX_BUG = EngineeringMethod(
        method_id="M-fix-bug-001",
        pattern="fix_bug",
        description=(
            "Fix a reported bug: reproduce it, isolate the root cause, write a "
            "regression test, ship the fix."
        ),
        tags=("corrective", "bug"),
        preconditions=("reproduction_steps_documented",),
        assumptions=(),
        subtask_templates=(
            _t(
                "bug-reproduce",
                "test",
                "Reproduce the bug",
                "Write a failing test or a step-by-step script that exhibits the bug.",
                "Reproduction exists and consistently fails on the buggy code.",
                default_blocked_by=(),
            ),
            _t(
                "bug-rootcause",
                "design",
                "Identify root cause",
                "Trace the bug to the responsible code path; document the offending condition.",
                "Root-cause note committed with code/line reference.",
                default_blocked_by=("bug-reproduce",),
            ),
            _t(
                "bug-fix",
                "impl",
                "Implement the fix",
                "Apply the minimum-impact fix that resolves the bug for the "
                "documented reproduction case.",
                "Reproduction test passes after the fix.",
                default_blocked_by=("bug-rootcause",),
            ),
            _t(
                "bug-regression",
                "test",
                "Add regression tests",
                "Promote the reproduction into a permanent regression test and "
                "cover adjacent failure modes.",
                "Regression test is part of the canonical test suite.",
                default_blocked_by=("bug-fix",),
            ),
        ),
        acceptance_template=_a(
            assertion_template="BugFixed({issue_id})",
            proof_template="Regression test for {issue_id} passes",
            strict_acceptance=True,
        ),
    )

    _M_FIX_PERFORMANCE = EngineeringMethod(
        method_id="M-fix-performance-001",
        pattern="fix_performance",
        description=(
            "Fix a performance regression: measure baseline, profile, identify "
            "hotspot, optimize, prove the gain."
        ),
        tags=("corrective", "performance"),
        preconditions=("baseline_measurement_exists",),
        assumptions=("profiler_available",),
        subtask_templates=(
            _t(
                "perf-measure",
                "test",
                "Measure baseline",
                "Capture reproducible before-numbers (latency / throughput / "
                "memory) on the documented workload.",
                "Baseline numbers recorded in the issue or commit message.",
                default_blocked_by=(),
            ),
            _t(
                "perf-profile",
                "design",
                "Profile and locate hotspot",
                "Run a profiler under the same workload and locate the dominant function or query.",
                "Profile report links the hotspot to a concrete code/query site.",
                default_blocked_by=("perf-measure",),
            ),
            _t(
                "perf-optimize",
                "impl",
                "Implement optimization",
                "Apply the optimization and keep behavior identical.",
                "Optimization merged; behavior-preserving test still passes.",
                default_blocked_by=("perf-profile",),
            ),
            _t(
                "perf-verify",
                "test",
                "Verify performance gain",
                "Re-measure the same workload and document the delta against the baseline.",
                "Post-fix numbers recorded and meet the documented target.",
                default_blocked_by=("perf-optimize",),
            ),
        ),
        acceptance_template=_a(
            assertion_template="PerformanceTargetMet({metric})",
            proof_template="Re-measured {metric} meets the documented target",
            strict_acceptance=True,
        ),
    )

    _M_FIX_SECURITY_VULNERABILITY = EngineeringMethod(
        method_id="M-fix-security-vulnerability-001",
        pattern="fix_security_vulnerability",
        description=(
            "Patch a security vulnerability: assess impact, ship a fix, add a "
            "regression test, and disclose if required."
        ),
        tags=("corrective", "security"),
        preconditions=("vulnerability_advisory_exists",),
        assumptions=("cve_or_advisory_id_assigned",),
        subtask_templates=(
            _t(
                "sec-assess",
                "design",
                "Assess impact",
                "Determine affected versions, exposure surface, and exploit prerequisites.",
                "Impact note lists affected versions and exposure surface.",
                default_blocked_by=(),
            ),
            _t(
                "sec-fix",
                "impl",
                "Implement the patch",
                "Apply the minimum-impact patch that closes the vulnerability "
                "across affected call sites.",
                "Patched code merges; existing tests still pass.",
                default_blocked_by=("sec-assess",),
            ),
            _t(
                "sec-regression",
                "test",
                "Add security regression test",
                "Cover the vulnerable input/path so it cannot regress silently.",
                "Regression test passes against patched code and fails without it.",
                default_blocked_by=("sec-fix",),
            ),
            _t(
                "sec-disclose",
                "docs",
                "Document / disclose",
                "Update the changelog, advisory, or security note with the fix and credit.",
                "Advisory / changelog entry published.",
                default_blocked_by=("sec-regression",),
            ),
        ),
        acceptance_template=_a(
            assertion_template="VulnerabilityPatched({cve})",
            proof_template="Regression test for {cve} passes",
            strict_acceptance=True,
        ),
    )

    _M_FIX_RACE_CONDITION = EngineeringMethod(
        method_id="M-fix-race-condition-001",
        pattern="fix_race_condition",
        description=(
            "Fix a concurrency / race-condition bug: capture a flaky reproduction, "
            "isolate the synchronization gap, fix it, harden with stress tests."
        ),
        tags=("corrective", "concurrency"),
        preconditions=("reproduction_is_flaky",),
        assumptions=("concurrency_test_harness_available",),
        subtask_templates=(
            _t(
                "race-reproduce",
                "test",
                "Reproduce race",
                "Turn the flake into a deterministic stress test (e.g. with "
                "threaded / async loops).",
                "Stress test reproduces the race on the buggy code.",
                default_blocked_by=(),
            ),
            _t(
                "race-isolate",
                "design",
                "Isolate the gap",
                "Identify the missing synchronization primitive or shared-state "
                "read-modify-write gap.",
                "Root-cause note references the missing lock / atomic operation.",
                default_blocked_by=("race-reproduce",),
            ),
            _t(
                "race-fix",
                "impl",
                "Implement the fix",
                "Add the synchronization primitive and verify deadlock-freedom.",
                "Stress test passes after the fix.",
                default_blocked_by=("race-isolate",),
            ),
            _t(
                "race-stress",
                "test",
                "Add stress test",
                "Promote the stress test into the canonical suite with an "
                "iteration count that previously triggered the flake.",
                "Stress test runs in CI and stays green.",
                default_blocked_by=("race-fix",),
            ),
        ),
        acceptance_template=_a(
            assertion_template="RaceConditionClosed({site})",
            strict_acceptance=True,
        ),
    )

    # ---------------------------------------------------------------------------
    # refactor_* — restructure patterns (3)
    # ---------------------------------------------------------------------------

    _M_REFACTOR_MODULE = EngineeringMethod(
        method_id="M-refactor-module-001",
        pattern="refactor_module",
        description=(
            "Refactor an existing module: capture current behavior as tests, "
            "restructure, keep behavior identical."
        ),
        tags=("restructure", "refactor"),
        preconditions=("module_has_test_coverage",),
        assumptions=("behavior_preserved_invariant",),
        subtask_templates=(
            _t(
                "refactor-baseline",
                "test",
                "Lock down current behavior",
                "Run existing tests; add characterization tests for any untested branch.",
                "Test suite green; characterization tests added for the targeted module.",
                default_blocked_by=(),
            ),
            _t(
                "refactor-design",
                "design",
                "Design new structure",
                "Decide on the target shape: extract functions, split files, "
                "introduce abstractions.",
                "Design doc enumerates the rename / split / extract operations.",
                default_blocked_by=("refactor-baseline",),
            ),
            _t(
                "refactor-apply",
                "impl",
                "Apply the refactor",
                "Mechanically apply the design, keeping the public surface identical.",
                "Refactor merged; public API unchanged.",
                default_blocked_by=("refactor-design",),
            ),
            _t(
                "refactor-review",
                "review",
                "Review and clean up",
                "Review the diff, remove dead code, update docstrings, ensure no "
                "test was modified to make it pass.",
                "No tests were weakened to make them pass.",
                default_blocked_by=("refactor-apply",),
            ),
        ),
        acceptance_template=_a(
            assertion_template="BehaviorPreserved({module})",
            proof_template="All existing tests still pass for {module}",
            strict_acceptance=True,
        ),
    )

    _M_REFACTOR_EXTRACT_SERVICE = EngineeringMethod(
        method_id="M-refactor-extract-service-001",
        pattern="refactor_extract_service",
        description=(
            "Extract logic out of an oversized function/module into a dedicated "
            "service: define the contract, extract, migrate callers, retire the "
            "old path."
        ),
        tags=("restructure", "refactor"),
        preconditions=("callers_are_identified",),
        assumptions=("service_can_be_instantiated",),
        subtask_templates=(
            _t(
                "extract-contract",
                "design",
                "Define service contract",
                "Decide the service surface, return types, error semantics, and "
                "dependency injection points.",
                "Contract doc published with method signatures.",
                default_blocked_by=(),
            ),
            _t(
                "extract-impl",
                "impl",
                "Implement the service",
                "Create the new module/class and migrate the canonical logic into it.",
                "Service module merged.",
                default_blocked_by=("extract-contract",),
            ),
            _t(
                "extract-migrate",
                "impl",
                "Migrate callers",
                "Replace inline implementations with calls to the new service "
                "across all call sites.",
                "All call sites migrated; old inline implementation removed.",
                default_blocked_by=("extract-impl",),
            ),
            _t(
                "extract-verify",
                "test",
                "Verify behavior",
                "Run the full test suite and confirm no behavior change.",
                "Full test suite green.",
                default_blocked_by=("extract-migrate",),
            ),
        ),
        acceptance_template=_a(
            assertion_template="ServiceExtracted({name})",
            strict_acceptance=True,
        ),
    )

    _M_REFACTOR_RENAME = EngineeringMethod(
        method_id="M-refactor-rename-001",
        pattern="refactor_rename",
        description=(
            "Rename a symbol / module / file safely: locate all references, "
            "perform an atomic rename, verify no stragglers."
        ),
        tags=("restructure", "refactor"),
        preconditions=("scope_is_identified",),
        assumptions=("language_tool_supports_rename",),
        subtask_templates=(
            _t(
                "rename-scope",
                "design",
                "Locate references",
                "Find all references in code, docs, configs, and tests.",
                "Reference list produced and reviewed.",
                default_blocked_by=(),
            ),
            _t(
                "rename-apply",
                "impl",
                "Apply the rename",
                "Use a project-wide rename (IDE refactor or scripted rewrite).",
                "Rename committed; no broken references remain.",
                default_blocked_by=("rename-scope",),
            ),
            _t(
                "rename-verify",
                "test",
                "Verify rename",
                "Run the full test suite and grep for the old name.",
                "Tests pass; old name absent from the tree.",
                default_blocked_by=("rename-apply",),
            ),
        ),
        acceptance_template=_a(
            assertion_template="SymbolRenamed({old_name}, {new_name})",
            strict_acceptance=False,
        ),
    )

    # ---------------------------------------------------------------------------
    # add_test_* — test-coverage patterns (3)
    # ---------------------------------------------------------------------------

    _M_ADD_UNIT_TEST = EngineeringMethod(
        method_id="M-add-unit-test-001",
        pattern="add_unit_test",
        description=(
            "Add unit tests for an existing unit: pick boundary cases, write "
            "tests, verify coverage."
        ),
        tags=("test", "unit"),
        preconditions=("target_unit_is_pure",),
        assumptions=("unit_test_runner_present",),
        subtask_templates=(
            _t(
                "unit-enumerate",
                "design",
                "Enumerate cases",
                "List boundary, negative, and equivalence-class inputs for the target unit.",
                "Case list documented.",
                default_blocked_by=(),
            ),
            _t(
                "unit-write",
                "test",
                "Write unit tests",
                "Implement the cases as canonical unit tests with arrange / act / assert.",
                "All listed cases have a corresponding test.",
                default_blocked_by=("unit-enumerate",),
            ),
            _t(
                "unit-verify",
                "review",
                "Verify coverage",
                "Run the test suite and review coverage of the target unit.",
                "Coverage of the target unit meets the documented bar.",
                default_blocked_by=("unit-write",),
            ),
        ),
        acceptance_template=_a(
            assertion_template="UnitTestCoverageMet({unit})",
            strict_acceptance=False,
        ),
    )

    _M_ADD_INTEGRATION_TEST = EngineeringMethod(
        method_id="M-add-integration-test-001",
        pattern="add_integration_test",
        description=(
            "Add an integration test that exercises two or more components "
            "together against a real or in-memory backend."
        ),
        tags=("test", "integration"),
        preconditions=("integration_harness_exists",),
        assumptions=("fixture_strategy_known",),
        subtask_templates=(
            _t(
                "integ-scope",
                "design",
                "Define integration scope",
                "Pick the components and the realistic backend to exercise.",
                "Scope doc lists components + backend.",
                default_blocked_by=(),
            ),
            _t(
                "integ-write",
                "test",
                "Write integration test",
                "Build fixtures and the test body using the harness.",
                "Test body merged with stable fixtures.",
                default_blocked_by=("integ-scope",),
            ),
            _t(
                "integ-verify",
                "review",
                "Verify reliability",
                "Run the test repeatedly to confirm it is not flaky.",
                "Test passes ≥ N consecutive runs.",
                default_blocked_by=("integ-write",),
            ),
        ),
        acceptance_template=_a(
            assertion_template="IntegrationTestReliable({name})",
            strict_acceptance=True,
        ),
    )

    _M_ADD_E2E_TEST = EngineeringMethod(
        method_id="M-add-e2e-test-001",
        pattern="add_e2e_test",
        description=(
            "Add an end-to-end test that drives the system through the public "
            "entrypoint (CLI / HTTP / UI)."
        ),
        tags=("test", "e2e"),
        preconditions=("e2e_harness_exists",),
        assumptions=("environment_is_ephemeral",),
        subtask_templates=(
            _t(
                "e2e-scenario",
                "design",
                "Define scenario",
                "Describe the user-visible scenario and the success criteria.",
                "Scenario doc published.",
                default_blocked_by=(),
            ),
            _t(
                "e2e-script",
                "test",
                "Script the scenario",
                "Implement the scenario through the public entrypoint.",
                "Script merged and runs against the ephemeral environment.",
                default_blocked_by=("e2e-scenario",),
            ),
            _t(
                "e2e-stabilize",
                "review",
                "Stabilize the test",
                "Tune waits and asserts so the test is not flaky in CI.",
                "Test stable in CI for ≥ N runs.",
                default_blocked_by=("e2e-script",),
            ),
        ),
        acceptance_template=_a(
            assertion_template="E2EScenarioCovered({name})",
            strict_acceptance=True,
        ),
    )

    # ---------------------------------------------------------------------------
    # add_doc_* — documentation patterns (3)
    # ---------------------------------------------------------------------------

    _M_ADD_README_SECTION = EngineeringMethod(
        method_id="M-add-readme-section-001",
        pattern="add_readme_section",
        description=(
            "Add a section to the project README: pick the topic, draft content, render, link."
        ),
        tags=("docs", "readme"),
        preconditions=("readme_exists",),
        assumptions=("rendered_markdown_supported",),
        subtask_templates=(
            _t(
                "readme-outline",
                "design",
                "Outline section",
                "Decide heading, target audience, and required subsections.",
                "Outline reviewed.",
                default_blocked_by=(),
            ),
            _t(
                "readme-write",
                "docs",
                "Draft section",
                "Write the section content with at least one example.",
                "Section merged with example.",
                default_blocked_by=("readme-outline",),
            ),
            _t(
                "readme-review",
                "review",
                "Review and link",
                "Cross-link to existing docs and run a markdown linter.",
                "Lint passes; cross-links resolve.",
                default_blocked_by=("readme-write",),
            ),
        ),
        acceptance_template=_a(
            assertion_template="ReadmeSectionPublished({topic})",
            strict_acceptance=False,
        ),
    )

    _M_ADD_API_DOC = EngineeringMethod(
        method_id="M-add-api-doc-001",
        pattern="add_api_doc",
        description=(
            "Add API reference docs for a symbol: gather signature, write the reference, render."
        ),
        tags=("docs", "api"),
        preconditions=("doc_generator_present",),
        assumptions=("signature_is_stable",),
        subtask_templates=(
            _t(
                "apidoc-source",
                "design",
                "Gather signature",
                "Capture the canonical signature, params, return type, and exceptions.",
                "Signature block drafted.",
                default_blocked_by=(),
            ),
            _t(
                "apidoc-write",
                "docs",
                "Write reference",
                "Write the reference page with at least one usage example.",
                "Reference page published.",
                default_blocked_by=("apidoc-source",),
            ),
            _t(
                "apidoc-verify",
                "review",
                "Verify examples",
                "Run each documented example to ensure it works.",
                "All examples execute without error.",
                default_blocked_by=("apidoc-write",),
            ),
        ),
        acceptance_template=_a(
            assertion_template="ApiReferencePublished({symbol})",
            strict_acceptance=False,
        ),
    )

    _M_ADD_CHANGELOG = EngineeringMethod(
        method_id="M-add-changelog-001",
        pattern="add_changelog",
        description=(
            "Add a changelog entry for a release: list user-visible changes, credit contributors."
        ),
        tags=("docs", "changelog"),
        preconditions=("release_version_known",),
        assumptions=("keep_a_changelog_format",),
        subtask_templates=(
            _t(
                "changelog-collect",
                "design",
                "Collect changes",
                "Aggregate merged PRs / commits into Added / Changed / Fixed buckets.",
                "Buckets drafted.",
                default_blocked_by=(),
            ),
            _t(
                "changelog-write",
                "docs",
                "Write entry",
                "Compose the version section with credit and links.",
                "Entry merged under the version heading.",
                default_blocked_by=("changelog-collect",),
            ),
            _t(
                "changelog-review",
                "review",
                "Review entry",
                "Review for clarity, scope, and accurate attribution.",
                "Entry reviewed and merged.",
                default_blocked_by=("changelog-write",),
            ),
        ),
        acceptance_template=_a(
            assertion_template="ChangelogEntryMerged({version})",
            strict_acceptance=False,
        ),
    )

    # ---------------------------------------------------------------------------
    # migrate_* — migration patterns (3)
    # ---------------------------------------------------------------------------

    _M_MIGRATE_DEPENDENCY = EngineeringMethod(
        method_id="M-migrate-dependency-001",
        pattern="migrate_dependency",
        description=(
            "Migrate from one dependency to another (e.g. library swap): "
            "pin both, dual-write / shadow, fully cut over."
        ),
        tags=("migration", "dependency"),
        preconditions=("target_library_is_compatible",),
        assumptions=("lockfile_present",),
        subtask_templates=(
            _t(
                "dep-plan",
                "design",
                "Plan migration",
                "Decide dual-write window, removal criteria, and rollback policy.",
                "Migration plan doc merged.",
                default_blocked_by=(),
            ),
            _t(
                "dep-impl",
                "impl",
                "Adopt new dependency",
                "Add the new library, wrap the call sites, and keep the old "
                "library behind a feature flag.",
                "New library wired behind a flag; old library still active.",
                default_blocked_by=("dep-plan",),
            ),
            _t(
                "dep-cutover",
                "impl",
                "Cut over",
                "Switch the default to the new library and remove the old one "
                "after the soak period.",
                "Old dependency removed; tests still green.",
                default_blocked_by=("dep-impl",),
            ),
            _t(
                "dep-verify",
                "test",
                "Verify migration",
                "Run the full test suite and any canary scenarios.",
                "Full test suite green; canary passes.",
                default_blocked_by=("dep-cutover",),
            ),
        ),
        acceptance_template=_a(
            assertion_template="DependencyMigrated({old}, {new})",
            strict_acceptance=True,
        ),
    )

    _M_MIGRATE_DATABASE_SCHEMA = EngineeringMethod(
        method_id="M-migrate-database-schema-001",
        pattern="migrate_database_schema",
        description=(
            "Apply a database schema migration: write the migration script, "
            "test it, deploy, verify."
        ),
        tags=("migration", "database"),
        preconditions=("schema_change_is_reviewed",),
        assumptions=("down_migration_supported",),
        subtask_templates=(
            _t(
                "schema-write",
                "impl",
                "Write migration script",
                "Author the up/down migration with idempotency guards.",
                "Migration script merged.",
                default_blocked_by=(),
            ),
            _t(
                "schema-test",
                "test",
                "Test migration",
                "Run the migration against a representative dataset and verify down-migration.",
                "Up + down migrations succeed against the fixture.",
                default_blocked_by=("schema-write",),
            ),
            _t(
                "schema-deploy",
                "deploy",
                "Deploy migration",
                "Roll the migration through the documented deployment pipeline.",
                "Migration applied in target environment.",
                default_blocked_by=("schema-test",),
            ),
            _t(
                "schema-verify",
                "review",
                "Verify post-migration state",
                "Run schema diff and confirm downstream queries still work.",
                "Schema diff is empty; downstream checks pass.",
                default_blocked_by=("schema-deploy",),
            ),
        ),
        acceptance_template=_a(
            assertion_template="SchemaMigrated({version})",
            proof_template="Schema diff matches target for {version}",
            strict_acceptance=True,
        ),
    )

    _M_MIGRATE_API_VERSION = EngineeringMethod(
        method_id="M-migrate-api-version-001",
        pattern="migrate_api_version",
        description=(
            "Bump an API to a new major version: design the new contract, "
            "support both, sunset the old."
        ),
        tags=("migration", "api"),
        preconditions=("versioning_policy_exists",),
        assumptions=("clients_can_pin_versions",),
        subtask_templates=(
            _t(
                "apiver-design",
                "design",
                "Design new contract",
                "Define breaking changes, the new contract, and the sunset timeline.",
                "Contract doc published.",
                default_blocked_by=(),
            ),
            _t(
                "apiver-impl",
                "impl",
                "Implement new version",
                "Land the new version behind a version selector.",
                "New version reachable via the selector.",
                default_blocked_by=("apiver-design",),
            ),
            _t(
                "apiver-communicate",
                "docs",
                "Communicate",
                "Publish migration notes for clients.",
                "Migration notes published.",
                default_blocked_by=("apiver-impl",),
            ),
            _t(
                "apiver-sunset",
                "deploy",
                "Sunset old version",
                "Disable the old version on the documented sunset date.",
                "Old version returns 410 Gone.",
                default_blocked_by=("apiver-communicate",),
            ),
        ),
        acceptance_template=_a(
            assertion_template="ApiVersionShipped({version})",
            strict_acceptance=True,
        ),
    )

    # ---------------------------------------------------------------------------
    # add_ci_* — CI / automation patterns (2)
    # ---------------------------------------------------------------------------

    _M_ADD_GITHUB_ACTION = EngineeringMethod(
        method_id="M-add-github-action-001",
        pattern="add_github_action",
        description=(
            "Add a GitHub Actions workflow: design triggers, author the workflow file, verify runs."
        ),
        tags=("ci", "automation"),
        preconditions=("repo_has_actions_enabled",),
        assumptions=("runner_images_meet_needs",),
        subtask_templates=(
            _t(
                "action-design",
                "design",
                "Design workflow",
                "Decide triggers, jobs, runners, secrets, and concurrency.",
                "Workflow design doc merged.",
                default_blocked_by=(),
            ),
            _t(
                "action-impl",
                "impl",
                "Author workflow file",
                "Write the YAML in .github/workflows/.",
                "Workflow file merged.",
                default_blocked_by=("action-design",),
            ),
            _t(
                "action-verify",
                "test",
                "Verify runs",
                "Trigger the workflow on a test branch and confirm green.",
                "Workflow run is green on the test branch.",
                default_blocked_by=("action-impl",),
            ),
        ),
        acceptance_template=_a(
            assertion_template="WorkflowGreen({name})",
            strict_acceptance=True,
        ),
    )

    _M_ADD_PRE_COMMIT_HOOK = EngineeringMethod(
        method_id="M-add-pre-commit-hook-001",
        pattern="add_pre_commit_hook",
        description=(
            "Add a pre-commit hook: pick the formatter/linter, wire the hook "
            "config, verify on a sample commit."
        ),
        tags=("ci", "automation"),
        preconditions=("pre_commit_framework_installed",),
        assumptions=("hook_id_is_known",),
        subtask_templates=(
            _t(
                "hook-design",
                "design",
                "Design hook set",
                "Decide which hooks to enable and which files they target.",
                "Hook set doc published.",
                default_blocked_by=(),
            ),
            _t(
                "hook-impl",
                "impl",
                "Configure hooks",
                "Update .pre-commit-config.yaml with the chosen hook IDs.",
                "Config file merged.",
                default_blocked_by=("hook-design",),
            ),
            _t(
                "hook-verify",
                "test",
                "Verify hook",
                "Run the hook on a sample dirty repo and confirm it blocks bad changes.",
                "Hook blocks a known-bad sample.",
                default_blocked_by=("hook-impl",),
            ),
        ),
        acceptance_template=_a(
            assertion_template="PreCommitHookActive({hook_id})",
            strict_acceptance=False,
        ),
    )

    # ---------------------------------------------------------------------------
    # release_* — release patterns (3)
    # ---------------------------------------------------------------------------

    _M_RELEASE_MINOR = EngineeringMethod(
        method_id="M-release-minor-001",
        pattern="release_minor",
        description=("Cut a minor release: aggregate changes, bump version, tag, publish."),
        tags=("release", "minor"),
        preconditions=("release_branch_ready",),
        assumptions=("semver_strict",),
        subtask_templates=(
            _t(
                "minor-changelog",
                "docs",
                "Finalize changelog",
                "Lock the changelog entries for the release.",
                "Changelog frozen.",
                default_blocked_by=(),
            ),
            _t(
                "minor-version",
                "impl",
                "Bump version",
                "Bump the minor version number across manifest files.",
                "Version bumped in all manifests.",
                default_blocked_by=("minor-changelog",),
            ),
            _t(
                "minor-tag",
                "deploy",
                "Tag and publish",
                "Create the version tag and push the publish pipeline.",
                "Tag pushed and artifact published.",
                default_blocked_by=("minor-version",),
            ),
            _t(
                "minor-announce",
                "docs",
                "Announce release",
                "Publish the release notes / announcement.",
                "Announcement published.",
                default_blocked_by=("minor-tag",),
            ),
        ),
        acceptance_template=_a(
            assertion_template="MinorReleaseShipped({version})",
            strict_acceptance=True,
        ),
    )

    _M_RELEASE_MAJOR = EngineeringMethod(
        method_id="M-release-major-001",
        pattern="release_major",
        description=(
            "Cut a major release: aggregate breaking changes, write migration "
            "guide, bump version, tag, publish."
        ),
        tags=("release", "major"),
        preconditions=("breaking_changes_consolidated",),
        assumptions=("migration_guide_supported",),
        subtask_templates=(
            _t(
                "major-migration",
                "docs",
                "Write migration guide",
                "Document each breaking change and the upgrade path.",
                "Migration guide published.",
                default_blocked_by=(),
            ),
            _t(
                "major-changelog",
                "docs",
                "Finalize changelog",
                "Lock the changelog entries grouped by breaking / feature / fix.",
                "Changelog frozen.",
                default_blocked_by=("major-migration",),
            ),
            _t(
                "major-version",
                "impl",
                "Bump version",
                "Bump the major version number across manifest files.",
                "Version bumped in all manifests.",
                default_blocked_by=("major-changelog",),
            ),
            _t(
                "major-tag",
                "deploy",
                "Tag and publish",
                "Create the version tag and push the publish pipeline.",
                "Tag pushed and artifact published.",
                default_blocked_by=("major-version",),
            ),
            _t(
                "major-announce",
                "docs",
                "Announce release",
                "Publish release notes highlighting breaking changes.",
                "Announcement published.",
                default_blocked_by=("major-tag",),
            ),
        ),
        acceptance_template=_a(
            assertion_template="MajorReleaseShipped({version})",
            strict_acceptance=True,
        ),
    )

    _M_HOTFIX = EngineeringMethod(
        method_id="M-hotfix-001",
        pattern="hotfix",
        description=(
            "Ship an out-of-band hotfix: branch from the release tag, patch, backport, tag."
        ),
        tags=("release", "hotfix"),
        preconditions=("incident_is_open",),
        assumptions=("hotfix_branch_policy_defined",),
        subtask_templates=(
            _t(
                "hotfix-branch",
                "impl",
                "Branch hotfix",
                "Create the hotfix branch from the release tag.",
                "Hotfix branch created.",
                default_blocked_by=(),
            ),
            _t(
                "hotfix-fix",
                "impl",
                "Apply minimal patch",
                "Apply the minimal-impact patch that resolves the incident.",
                "Patch applied; targeted regression test passes.",
                default_blocked_by=("hotfix-branch",),
            ),
            _t(
                "hotfix-tag",
                "deploy",
                "Tag and publish",
                "Tag the patch as a patch release and publish.",
                "Patch release published.",
                default_blocked_by=("hotfix-fix",),
            ),
            _t(
                "hotfix-backport",
                "impl",
                "Backport",
                "Merge the hotfix back into the main development branch.",
                "Backport merged into main.",
                default_blocked_by=("hotfix-tag",),
            ),
        ),
        acceptance_template=_a(
            assertion_template="HotfixShipped({version})",
            proof_template="Incident regression test passes for {version}",
            strict_acceptance=True,
        ),
    )

    # ---------------------------------------------------------------------------
    # Master tuple
    # ---------------------------------------------------------------------------

    SEED_METHODS: Final[tuple[EngineeringMethod, ...]] = (
        # add_*
        _M_ADD_API_ENDPOINT,
        _M_ADD_MIDDLEWARE,
        _M_ADD_CLI_COMMAND,
        _M_ADD_CONFIG_OPTION,
        _M_ADD_METRIC,
        # fix_*
        _M_FIX_BUG,
        _M_FIX_PERFORMANCE,
        _M_FIX_SECURITY_VULNERABILITY,
        _M_FIX_RACE_CONDITION,
        # refactor_*
        _M_REFACTOR_MODULE,
        _M_REFACTOR_EXTRACT_SERVICE,
        _M_REFACTOR_RENAME,
        # add_test_*
        _M_ADD_UNIT_TEST,
        _M_ADD_INTEGRATION_TEST,
        _M_ADD_E2E_TEST,
        # add_doc_*
        _M_ADD_README_SECTION,
        _M_ADD_API_DOC,
        _M_ADD_CHANGELOG,
        # migrate_*
        _M_MIGRATE_DEPENDENCY,
        _M_MIGRATE_DATABASE_SCHEMA,
        _M_MIGRATE_API_VERSION,
        # add_ci_*
        _M_ADD_GITHUB_ACTION,
        _M_ADD_PRE_COMMIT_HOOK,
        # release_*
        _M_RELEASE_MINOR,
        _M_RELEASE_MAJOR,
        _M_HOTFIX,
    )

    return SEED_METHODS


__all__ = ["build_seed_methods"]
