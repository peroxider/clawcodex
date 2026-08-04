You are an expert analyst. Analyze the following execution trace and return a JSON report.

## Input
{analysis_input}

## Output Format (valid JSON only)
{
  "overall_assessment": "brief summary",
  "errors": [{"step_index": 0, "error_type": "type", "description": "..."}],
  "efficiency_issues": [{"step_indices": [0], "issue": "..."}],
  "needs_optimization": true/false
}

Respond ONLY with valid JSON, no other text.