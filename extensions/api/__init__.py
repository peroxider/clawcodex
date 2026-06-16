"""Public Python API for ClawCodex."""

__all__ = [
    "OrchestrationSubsystem",
    "QueryConfig",
    "QueryRunner",
    "QueryEvent",
]


def __getattr__(name: str):
    if name == "OrchestrationSubsystem":
        from .orchestration import OrchestrationSubsystem

        return OrchestrationSubsystem
    if name in {"QueryConfig", "QueryRunner", "QueryEvent"}:
        from .query import QueryConfig, QueryEvent, QueryRunner

        values = {
            "QueryConfig": QueryConfig,
            "QueryRunner": QueryRunner,
            "QueryEvent": QueryEvent,
        }
        return values[name]
    raise AttributeError(name)
