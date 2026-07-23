"""Built-in acceptance-template seeds for F-155."""

from __future__ import annotations

from .acceptance_template import AcceptanceTemplate

ACCEPTANCE_TEMPLATE_SEEDS: tuple[AcceptanceTemplate, ...] = (
    AcceptanceTemplate(
        template_id="T-test-passes-001",
        description="A pytest target exits successfully.",
        assertion_template="TestPasses({test_path})",
        proof_template="pytest {test_path} exit code == 0",
        applies_to_roles=("test", "impl"),
    ),
    AcceptanceTemplate(
        template_id="T-coverage-threshold-001",
        description="Coverage meets or exceeds a requested threshold.",
        assertion_template="CoverageAtLeast({coverage_target}, {threshold})",
        proof_template="coverage report shows {coverage_target} >= {threshold}",
        applies_to_roles=("test", "review"),
    ),
    AcceptanceTemplate(
        template_id="T-lint-clean-001",
        description="Ruff linting completes without findings.",
        assertion_template="LintClean({path})",
        proof_template="ruff check {path} exit code == 0",
        applies_to_roles=("impl", "review"),
    ),
    AcceptanceTemplate(
        template_id="T-type-check-clean-001",
        description="Strict type checking completes successfully.",
        assertion_template="TypeCheckClean({path})",
        proof_template="mypy --strict {path} exit code == 0",
        applies_to_roles=("impl", "review"),
    ),
    AcceptanceTemplate(
        template_id="T-docs-section-exists-001",
        description="A named Markdown section exists in documentation.",
        assertion_template="DocsSectionExists({doc_path}, {section})",
        proof_template="{doc_path} contains markdown section {section}",
        applies_to_roles=("docs", "review"),
    ),
    AcceptanceTemplate(
        template_id="T-config-file-exists-001",
        description="A required configuration file exists.",
        assertion_template="ConfigFileExists({config_path})",
        proof_template="{config_path} exists",
        applies_to_roles=("impl", "deploy"),
    ),
    AcceptanceTemplate(
        template_id="T-deploy-success-001",
        description="A deployment command or script completes successfully.",
        assertion_template="DeploySucceeded({environment})",
        proof_template="{deploy_command} exit code == 0 for {environment}",
        applies_to_roles=("deploy",),
    ),
    AcceptanceTemplate(
        template_id="T-migration-applied-001",
        description="A database migration version is present after applying migrations.",
        assertion_template="MigrationApplied({migration_version})",
        proof_template="database schema history contains {migration_version}",
        applies_to_roles=("deploy", "impl"),
    ),
    AcceptanceTemplate(
        template_id="T-metrics-emitted-001",
        description="A named metric is registered and emitted.",
        assertion_template="MetricEmitted({metric_name})",
        proof_template="metrics registry contains {metric_name}",
        applies_to_roles=("impl", "review"),
    ),
    AcceptanceTemplate(
        template_id="T-security-scan-clean-001",
        description="Security scanner exits cleanly.",
        assertion_template="SecurityScanClean({path})",
        proof_template="security scan {path} exit code == 0",
        applies_to_roles=("review", "impl"),
    ),
    AcceptanceTemplate(
        template_id="T-no-new-vulnerabilities-001",
        description="No high or critical dependency vulnerabilities are introduced.",
        assertion_template="NoNewHighCriticalVulnerabilities({path})",
        proof_template="pip-audit {path} reports 0 high or critical vulnerabilities",
        applies_to_roles=("review", "impl"),
    ),
    AcceptanceTemplate(
        template_id="T-api-contract-valid-001",
        description="API contract validates against its schema.",
        assertion_template="ApiContractValid({schema_path})",
        proof_template="OpenAPI validation succeeds for {schema_path}",
        applies_to_roles=("test", "review", "impl"),
    ),
    AcceptanceTemplate(
        template_id="T-build-succeeds-001",
        description="Project build command succeeds.",
        assertion_template="BuildSucceeds({build_target})",
        proof_template="{build_command} exit code == 0",
        applies_to_roles=("impl", "deploy"),
    ),
    AcceptanceTemplate(
        template_id="T-changelog-updated-001",
        description="The changelog contains the current version or change entry.",
        assertion_template="ChangelogUpdated({version})",
        proof_template="CHANGELOG.md contains {version}",
        applies_to_roles=("docs", "review"),
    ),
    AcceptanceTemplate(
        template_id="T-rollback-tested-001",
        description="Rollback path passes a smoke test.",
        assertion_template="RollbackTested({environment})",
        proof_template="rollback smoke test passes in {environment}",
        applies_to_roles=("deploy", "review"),
    ),
    AcceptanceTemplate(
        template_id="T-feature-flag-rolled-out-001",
        description="Feature flag is fully rolled out and stable in the target environment.",
        assertion_template="FeatureFlagRolledOut({flag_name}, {environment})",
        proof_template="{flag_name} enabled_for_all_users=true in {environment}",
        applies_to_roles=("impl", "deploy", "review"),
    ),
)

__all__ = ["ACCEPTANCE_TEMPLATE_SEEDS"]
