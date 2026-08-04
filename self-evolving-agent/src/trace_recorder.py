"""Trace recorder: persists execution traces to disk."""

from __future__ import annotations

import os
import json
from dataclasses import asdict
from typing import Optional

from src.models import ExecutionTrace, dataclass_to_dict
from src.utils import read_json, write_json


class TraceRecorder:
    """Records and retrieves execution traces from disk storage."""

    def __init__(self, storage_dir: str = "./data/traces") -> None:
        self.storage_dir = storage_dir

    def save(self, trace: ExecutionTrace) -> str:
        """Persist a trace to disk. Returns the file path."""
        data = dataclass_to_dict(trace)
        path = os.path.join(self.storage_dir, f"{trace.trace_id}.json")
        write_json(path, data)
        return path

    def load(self, trace_id: str) -> Optional[ExecutionTrace]:
        """Load a trace by ID."""
        path = os.path.join(self.storage_dir, f"{trace_id}.json")
        data = read_json(path)
        if data is None:
            return None
        return self._from_dict(data)

    def list_traces(self) -> list[str]:
        """List all stored trace IDs (by filename, no .json)."""
        if not os.path.isdir(self.storage_dir):
            return []
        return [f.replace(".json", "") for f in os.listdir(self.storage_dir)
                if f.endswith(".json")]

    def delete(self, trace_id: str) -> bool:
        """Delete a trace file. Returns True if deleted."""
        path = os.path.join(self.storage_dir, f"{trace_id}.json")
        if os.path.isfile(path):
            os.remove(path)
            return True
        return False

    @staticmethod
    def _from_dict(data: dict) -> ExecutionTrace:
        """Reconstruct an ExecutionTrace from a dict."""
        from src.models import TraceStep, ExecutionMetrics
        # Convert nested lists of steps
        if "steps" in data:
            data["steps"] = [TraceStep(**s) for s in data["steps"]]
        if "execution_metrics" in data and isinstance(data["execution_metrics"], dict):
            data["execution_metrics"] = ExecutionMetrics(**data["execution_metrics"])
        return ExecutionTrace(**data)
