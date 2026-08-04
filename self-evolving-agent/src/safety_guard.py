from __future__ import annotations
import ast
from typing import Any, Dict, List
from src.models import ComparisonResult, OptimizationProposal, ProposalType
from src.utils import setup_logger

logger = setup_logger('safety_guard')


class SafetyGuard:
    def __init__(self, config):
        self.config = config
        self.protected_prompts = ['safety_prompt', 'identity_prompt']
        self.max_consecutive_failures = config.get('system', {}).get('max_consecutive_failures', 3)

    def check_proposal_safety(self, proposal):
        """Check whether a proposal is safe to apply."""
        if proposal.proposal_type == ProposalType.PROMPT_OPTIMIZATION:
            if proposal.target in self.protected_prompts:
                return False
            if not self._validate_prompt_content(proposal.proposed_content):
                return False
        if not proposal.proposed_content.strip():
            return False
        if not proposal.target.strip():
            return False
        if proposal.priority < 1 or proposal.priority > 5:
            return False
        if proposal.proposal_type == ProposalType.PLUGIN_GENERATION:
            safe, _reason = self.check_generated_code(proposal.proposed_content)
            if not safe:
                return False
        if proposal.proposal_type in (ProposalType.SKILL_ADDITION, ProposalType.SKILL_MODIFICATION):
            if not self._validate_skill_content(proposal.proposed_content):
                return False
        return True

    @staticmethod
    def _validate_prompt_content(content: str) -> bool:
        """Validate prompt text for common syntax issues."""
        stripped = content.strip()
        if not stripped or len(stripped) < 10:
            return False
        # Balanced curly braces
        depth = 0
        for ch in content:
            if ch == chr(123):
                depth += 1
            elif ch == chr(125):
                depth -= 1
            if depth < 0:
                return False
        if depth != 0:
            return False
        # Balanced square brackets
        bd = 0
        for ch in content:
            if ch == chr(91):
                bd += 1
            elif ch == chr(93):
                bd -= 1
            if bd < 0:
                return False
        # Detect unclosed double-quote combined with template syntax
        in_string = False
        escaped = False
        for ch in content:
            if escaped:
                escaped = False
                continue
            if ch == chr(92):
                escaped = True
                continue
            if ch == chr(34):
                in_string = not in_string
        if in_string and (chr(123) in content or '}}' in content):
            return False
        return True

    @staticmethod
    def _validate_skill_content(content: str) -> bool:
        """Validate skill content: non-empty, parseable if JSON."""
        if not content.strip():
            return False
        import json as _json
        maybe = content.strip()
        if maybe.startswith('{') or maybe.startswith('['):
            try:
                _json.loads(maybe)
            except _json.JSONDecodeError:
                return False
        return True

    def should_pause_optimization(self, recent_results):
        if len(recent_results) < self.max_consecutive_failures:
            return False
        tail = recent_results[-self.max_consecutive_failures:]
        cr = sum(1 for r in tail if r.decision == 'reject')
        if cr >= self.max_consecutive_failures:
            return True
        return False

    @staticmethod
    def check_generated_code(code):
        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            return (False, 'Syntax error: ' + str(e))
        cl = [l for l in code.split(chr(10)) if l.strip() and not l.strip().startswith('#')]
        if len(cl) > 80:
            return (False, 'Too many code lines')
        has_fn = any(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) for n in ast.walk(tree))
        if not has_fn:
            return (False, 'No function definition found')
        DM = frozenset(['os', 'subprocess', 'shutil', 'sys', 'ctypes', 'socket', 'pickle', 'pathlib', 'signal'])
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.split('.')[0] in DM:
                        return (False, 'Blocked import: ' + alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module and node.module.split('.')[0] in DM:
                    return (False, 'Blocked import from: ' + node.module)
        DA = frozenset(['environ', 'system', 'popen', 'fork', 'exec', 'remove', 'unlink', 'rmdir', 'chmod', 'chown'])
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute):
                if node.attr in DA:
                    return (False, 'Blocked attribute: .' + node.attr)
        for node in ast.walk(tree):
            if isinstance(node, ast.While):
                has_exit = any(isinstance(n, (ast.Break, ast.Return, ast.Raise)) for n in ast.walk(node))
                if not has_exit:
                    return (False, 'while loop without break/return/raise')
        return (True, 'ok')
