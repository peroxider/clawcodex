You are an Agent system optimization expert. Based on the following execution trace analysis report, generate specific optimization proposals.

## Analysis Report
{analysis_report_json}

## Current System Configuration
- Prompt Templates: {current_prompts}
- Available Skills: {current_skills}
- System Configuration: {current_config}

## Requirements
Generate specific optimization proposals for the issues detected. Each proposal should specify:
1. proposal_type: "prompt_optimization | skill_addition | skill_modification | config_adjustment | workflow_optimization"
2. target: which file or component to modify
3. current_content: the EXACT text snippet to replace (copy verbatim from the file)
4. proposed_content: the NEW text snippet (ONLY the changed part, not the full file)
5. reason: why this change helps
6. expected_improvement: what improvement is expected
7. priority: 1 (high) to 3 (low)

IMPORTANT: Keep current_content and proposed_content as short text descriptions, not full file contents. Use plain text without unescaped characters.

## Output Format (valid JSON only, no extra text)
```json
{
  "proposals": [
    {
      "proposal_type": "prompt_optimization",
      "target": "target name",
      "current_content": "exact text to replace",
      "proposed_content": "replacement text only",
      "reason": "reason for modification",
      "expected_improvement": "expected improvement effect",
      "priority": 2
    }
  ]
}
```
