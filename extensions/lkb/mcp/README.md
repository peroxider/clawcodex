# lkb MCP Server

The lkb MCP server exposes 4 tools for use with any MCP client (Claude Desktop, Cline, etc.).

## Setup

### Option 1: Via `mcp` CLI

```bash
# Install the lkb package
pip install lkb

# Run the MCP server
mcp run lkb.mcp.server:server
```

### Option 2: Via stdio

```bash
python -m lkb.mcp.server
```

### Option 3: Claude Desktop config

```json
{
  "mcpServers": {
    "lkb": {
      "command": "python",
      "args": ["-m", "lkb.mcp.server"]
    }
  }
}
```

## Tools

### `decompose_task`

Decompose a natural-language goal into a validated task plan.

**Input**:
- `goal` (string, required) — The goal to decompose
- `context` (object, optional) — Context snapshot (tasks, workspace_root)
- `use_methods` (array of strings, optional) — Method library refs

**Output**: `DecompositionPlan` JSON with tasks, dependencies, assumptions, and validation results.

### `validate_task`

Validate a proposed task state transition without committing.

**Input**:
- `task_id` (string, required) — Task ID to validate
- `change` (object, required) — Change specification (kind + payload)

**Output**: `ValidationRun` JSON with result, proof trace, and any issues.

### `explain`

Explain the reasoning chain for a task.

**Input**:
- `task_id` (string, required) — Task ID to explain

**Output**: Explanation JSON with summary, proof trace, and repair suggestions.

### `audit`

Return the audit log for a task.

**Input**:
- `task_id` (string, required) — Task ID to audit
- `since` (string, optional) — ISO 8601 timestamp filter

**Output**: Array of audit events (proposals, validations, commits, denials).

## Example: Claude Desktop usage

```
User: "Break down the task of building a login system"
Claude: [calls decompose_task → returns task plan]

User: "Can you explain why task-003 is blocked?"
Claude: [calls explain → returns reasoning chain]

User: "What changes have been made to task-001?"
Claude: [calls audit → returns event history]
```