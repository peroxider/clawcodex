"""Main entry point: SelfEvolvingSystem with the full optimization loop."""

from __future__ import annotations
import sys
import os
import time
from typing import Any, Callable, Dict, List, Optional

from src.models import (
    Task,
    ExecutionTrace,
    ComparisonResult,
    OptimizationProposal,
)
from src.task_queue import TaskQueue
from src.execution_engine import ExecutionEngine
from src.trace_recorder import TraceRecorder
from src.trace_analyzer import TraceAnalyzer
from src.proposal_generator import ProposalGenerator
from src.evaluator import EvaluatorAgent
from src.version_manager import VersionManager
from src.safety_guard import SafetyGuard
from src.utils import load_config, read_json, setup_logger
from src.debugger import ProposalDebugger
from src.skill_creator import SkillCreator
import os as _os
import shutil as _shutil
import json as _json
from datetime import datetime as _datetime

logger = setup_logger("self_evolving_system")

SKILL_EXTRACT_PROMPT = """你正在分析一次成功的 Agent 执行轨迹，目的是提取一个可复用的技能（Skill）。

## 执行轨迹

任务描述：{task_description}

对话记录：
{conversation_text}

## 提取要求

请从该轨迹中提取以下 5 个维度，生成一个结构化的技能定义：

1. **name**（必填）：技能名称，英文 snake_case，简洁准确
   例：astapi_crud_setup、python_pytest_debug、git_commit_squash

2. **trigger_condition**（必填）：触发条件（中文，一句话）
   例：“当用户要求创建一个 FastAPI CRUD 项目时”

3. **summary**（必填）：技能摘要（中文，一句话）

4. **sop**（必填）：标准操作流程（3-6 步，中文）
   每步是一个具体的可执行指令

5. **pitfalls**（可选）：常见陷阱（2-4 项，中文）

## 输出格式（仅 JSON）
{{"name": "...", "trigger_condition": "...", "summary": "...", "sop": ["..."], "pitfalls": ["..."]}}

请只输出 JSON，不要其它内容。"""



class SelfEvolvingSystem:
    def __init__(
        self,
        config_path: str,
        agent_callback: Optional[Callable] = None,
        llm_caller: Optional[Callable] = None,
        clawcodex_agents_dir: str = None,
    ) -> None:
        self.config = load_config(config_path)
        self.task_queue = TaskQueue()
        self.execution_engine = ExecutionEngine(self.config, agent_callback=agent_callback)
        _searoot = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
        self.trace_recorder = TraceRecorder(os.path.join(_searoot, self.config["storage"]["traces_dir"]))
        self.trace_analyzer = TraceAnalyzer(self.config, llm_caller=llm_caller)
        self.proposal_generator = ProposalGenerator(self.config, llm_caller=llm_caller)
        self.evaluator = EvaluatorAgent(self.config, llm_caller=llm_caller)
        self.version_manager = VersionManager(os.path.join(_searoot, self.config["storage"]["versions_dir"]), cx_root=os.path.normpath(os.path.join(_searoot, "..")))
        self.safety_guard = SafetyGuard(self.config)
        self.clawcodex_agents_dir = clawcodex_agents_dir
        self._total_cycles = 0
        self._approvals = 0
        self._rejections = 0
        sys.stderr.write("  [Auto-Debug] \u529f\u80fd\u5df2\u52a0\u8f7d\n")

    @staticmethod
    def _execution_degraded(old: ExecutionTrace, new: ExecutionTrace) -> bool:
        old_m = old.execution_metrics
        new_m = new.execution_metrics
        if new_m.error_count > old_m.error_count:
            return True
        if old_m.overall_score > 0 and new_m.overall_score == 0:
            return True
        if old_m.total_steps > 0 and new_m.total_steps > old_m.total_steps * 2:
            return True
        old_out = (old.final_output or "").strip()
        new_out = (new.final_output or "").strip()
        if len(old_out) > 100 and len(new_out) < 50:
            return True
        if old_m.tool_call_count > 0 and new_m.tool_call_count == 0:
            return True
        return False

    def run(self, poll_interval=10.0, max_idle_cycles=3):
        logger.info("SelfEvolvingSystem started (poll_interval=%ss)", poll_interval)
        idle = 0
        while True:
            try:
                task = self.task_queue.get_next_task()
                if task is None:
                    idle += 1
                    if idle >= max_idle_cycles:
                        break
                    time.sleep(poll_interval)
                    continue
                idle = 0
                self._process_task(task)
            except KeyboardInterrupt:
                break
            except Exception as e:
                logger.error("Main loop error: %s", e, exc_info=True)
        self._print_summary()

    def submit_task(self, description, priority=5):
        task = Task(description=description, priority=priority)
        self.task_queue.add_task(task)
        return task

    def _process_task(self, task):
        self._total_cycles += 1
        logger.info("[Cycle %d] Executing task %s...", self._total_cycles, task.task_id)

        trace = self.execution_engine.execute(task)
        self.trace_recorder.save(trace)

        analysis = self.trace_analyzer.analyze(trace)
        if not analysis.needs_optimization:
            logger.info("No optimization needed.")
            self.task_queue.requeue_for_retry(task)
            return

        proposals = self.proposal_generator.generate(analysis)
        if not proposals:
            logger.info("No proposals generated.")
            self.task_queue.requeue_for_retry(task)
            return

        proposals = [p for p in proposals if self.safety_guard.check_proposal_safety(p)]
        mp = self.config.get("system", {}).get("max_proposals_per_cycle", 3)
        if len(proposals) > mp:
            proposals = proposals[:mp]
        if not proposals:
            logger.info("All proposals failed safety checks.")
            self.task_queue.requeue_for_retry(task)
            return

        new_version = None
        for proposal in proposals:
            v = self.version_manager.apply_proposal(proposal)
            if new_version is None:
                new_version = v
        if new_version is None:
            return

        new_config = self.version_manager.get_current_config()
        self.execution_engine.set_version_config(new_config)
        new_trace = self.execution_engine.execute(task)

        comparison = self.evaluator.compare_executions(task.description, trace, new_trace)

        if comparison.decision == "reject":
            print(f"  [DBG] decision={comparison.decision} llm={self.proposal_generator.llm_caller is not None} orig_score={trace.execution_metrics.overall_score}", flush=True)
            degraded = self._execution_degraded(trace, new_trace)
            # Trigger debug if:
            # 1. Metrics show degradation, OR
            # 2. LLM evaluator says reject AND original was successful
            llm_available = self.proposal_generator.llm_caller is not None
            orig_success = trace.execution_metrics.overall_score > 0
            should_debug = (degraded or (llm_available and orig_success))
            if should_debug and llm_available:
                sys.stderr.write('  [Auto-Debug] \\u65b0\\u7248\\u672c\\u6267\\u884c\\u9000\\u5316\\uff0c\\u5f00\\u59cbdebug...' + chr(10))
                debugger = ProposalDebugger(llm_caller=self.proposal_generator.llm_caller)
                fixed = debugger.debug(proposals, trace, new_trace)
                if fixed:
                    fixed = [p for p in fixed if self.safety_guard.check_proposal_safety(p)]
                if fixed:
                    sys.stderr.write('  [Auto-Debug] \\u5e94\\u7528\\u4fee\\u6b63\\u65b9\\u6848\\uff0c\\u91cd\\u65b0\\u6267\\u884c...' + chr(10))
                    self.version_manager.rollback(trace.agent_version)
                    self.execution_engine.set_version_config(self.version_manager.get_current_config())
                    for fp in fixed:
                        self.version_manager.apply_proposal(fp)
                    fixed_config = self.version_manager.get_current_config()
                    self.execution_engine.set_version_config(fixed_config)
                    new_trace2 = self.execution_engine.execute(task)
                    comparison2 = self.evaluator.compare_executions(task.description, trace, new_trace2)
                    if comparison2.decision == "approve":
                        sys.stderr.write('  [Auto-Debug] OK debug\\u6210\\u529f\\uff01\\u4fee\\u6b63\\u7248\\u5df2\\u91c7\\u7eb3' + chr(10))
                        self.version_manager.set_current_version(self.version_manager.current_version)
                        self._approvals += 1
                        return
                    else:
                        sys.stderr.write('  [Auto-Debug] X debug\\u5931\\u8d25\\uff0c\\u56de\\u6eda' + chr(10))
                else:
                    sys.stderr.write('  [Auto-Debug] \\u672a\\u80fd\\u751f\\u6210\\u6709\\u6548\\u4fee\\u590d\\uff0c\\u8df3\\u8fc7' + chr(10))
            else:
                sys.stderr.write('  [Auto-Debug] \\u65e0\\u9700debug\\uff08\\u6307\\u6807\\u672a\\u663e\\u8457\\u9000\\u5316\\u6216\\u65e0LLM\\uff09' + chr(10))

            logger.info("Rejected. Rolling back to %s", trace.agent_version)
            self.version_manager.rollback(trace.agent_version)
            self._rejections += 1
        else:
            logger.info("Approved! Version %s", new_version)
            self.version_manager.set_current_version(new_version)
            self._approvals += 1

        self.execution_engine.set_version_config(None)

        recent = self._gather_recent_comparisons(10)
        if self.safety_guard.should_pause_optimization(recent):
            logger.warning("Too many failures. Pausing.")
            self._print_summary()
            return

    def _gather_recent_comparisons(self, n):
        import os as _os
        comp_dir = self.config.get("storage", {}).get("comparisons_dir", os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "comparisons"))
        if not _os.path.isdir(comp_dir):
            return []
        files = sorted([f for f in _os.listdir(comp_dir) if f.endswith(".json")], reverse=True)[:n]
        results = []
        for f in files:
            data = read_json(_os.path.join(comp_dir, f))
            if data:
                results.append(ComparisonResult(**data))
        return results

    def _print_summary(self):
        logger.info("=" * 50)
        logger.info("Session Summary")
        logger.info("  Cycles: %d", self._total_cycles)
        logger.info("  Approvals: %d", self._approvals)
        logger.info("  Rejections: %d", self._rejections)
        logger.info("  Version: %s", self.version_manager.current_version or "N/A")
        logger.info("=" * 50)


    # --- Conversation analysis pipeline ---

    def _messages_to_trace(self, messages: list[dict], tool_events: list = None) -> ExecutionTrace:
        """Build ExecutionTrace from conversation messages and optional tool_events."""
        from src.models import TraceStep, StepType, ExecutionMetrics, ToolCall
        steps = []
        last_user = ""
        error_count = 0

        # If tool_events are available, build steps from them
        if tool_events:
            # Group: for each tool_use, find matching tool_result
            result_map = {}
            for evt in tool_events:
                if evt.get("type") == "tool_result":
                    tid = evt.get("tool_use_id", "")
                    result_map[tid] = evt

            for idx, evt in enumerate(tool_events):
                if evt.get("type") != "tool_use":
                    continue
                tid = evt.get("tool_use_id", "")
                name = evt.get("name", "unknown")
                inp = evt.get("input", {})

                res = result_map.get(tid, {})
                out = res.get("output", "")
                is_error = res.get("is_error", False)
                if is_error:
                    error_count += 1

                # Determine StepType from tool name
                st = StepType.COMMAND_EXECUTION
                if name in ("Write", "Edit", "FileWrite", "FileEdit", "WriteIfNotExists"):
                    st = StepType.FILE_OPERATION
                elif name in ("Read", "Glob", "Grep", "ListFiles"):
                    st = StepType.CODE_GENERATION
                elif name in ("Bash", "Execute", "Run", "Python"):
                    st = StepType.COMMAND_EXECUTION
                elif name in ("Think", "AskUser", "Plan"):
                    st = StepType.PLANNING

                action = str(inp.get("file_path", inp.get("command", name)))[:200]
                tc = ToolCall(
                    tool_name=name,
                    arguments=inp if isinstance(inp, dict) else {"input": str(inp)},
                    result=str(out)[:500],
                    error="Error" if is_error else None,
                    duration_ms=0,
                )
                steps.append(TraceStep(
                    step_index=idx + 1, step_type=st,
                    action=action,
                    input_data=json.dumps(inp, ensure_ascii=False)[:500],
                    output_data=str(out)[:500],
                    tool_calls=[tc],
                    errors=[str(out)[:200]] if is_error else [],
                ))

            # Add a final step if the last message has meaningful content
            for m in reversed(messages):
                if m.get("role") == "assistant" and len((m.get("content") or "").strip()) > 50:
                    steps.append(TraceStep(
                        step_index=len(steps) + 1,
                        step_type=StepType.FINAL_OUTPUT,
                        action=(m.get("content") or "")[:200],
                        output_data=(m.get("content") or "")[:1000],
                    ))
                    break

        else:
            # Fallback: reconstruct from message content (original behavior)
            for i, m in enumerate(messages):
                role = m.get("role", "")
                content = (m.get("content") or "")[:2000]
                if role == "user":
                    last_user = content
                    continue
                if role != "assistant":
                    continue
                has_code = "```" in content
                has_error = any(k in content.lower() for k in
                    ["error", "exception", "traceback", "syntaxerror", "timeout"])
                has_retry = any(k in content.lower() for k in
                    ["let me try", "retrying", "try again", "attempt"])
                if has_error or has_retry:
                    st = StepType.DEBUGGING
                elif has_code:
                    st = StepType.CODE_GENERATION
                else:
                    st = StepType.TASK_UNDERSTANDING
                if has_error:
                    error_count += 1
                steps.append(TraceStep(
                    step_index=i, step_type=st,
                    action=content[:200],
                    output_data=content,
                    errors=[content[:200]] if has_error else [],
                ))

        # Determine task_description and final_output
        for m in messages:
            if m.get("role") == "user" and not last_user:
                last_user = (m.get("content") or "")[:200]
        final_output = messages[-1].get("content", "")[-3:] if messages else ""

        return ExecutionTrace(
            task_description=last_user,
            steps=steps,
            final_output=final_output,
            execution_metrics=ExecutionMetrics(
                total_steps=len(steps),
                error_count=error_count,
                tool_call_count=sum(len(s.tool_calls) for s in steps) if tool_events else 0,
            ),
        )
    def _is_full_json_message(self, messages: list) -> bool:
        """Detect if messages are full JSON dicts (from transcript) or truncated str-based dicts."""
        if not messages or not isinstance(messages[0], dict):
            return False
        sample = messages[0]
        return bool(sample.get("uuid")) and bool(sample.get("type"))

    def _transcript_to_trace(self, messages: list[dict]) -> "ExecutionTrace":
        """Build ExecutionTrace from full JSON message dicts (raw transcript format).
        
        Extracts:
        - duration_ms from assistant messages -> TraceStep.duration_ms
        - stop_reason -> StepType
        - usage -> ExecutionMetrics
        - tool_use/tool_result blocks -> ToolCall with name, input, result, error
        - text blocks -> TraceStep.thinking
        - apiError/error -> TraceStep.errors
        """
        from src.models import TraceStep, StepType, ExecutionMetrics, ToolCall
        import uuid as _uuid
        
        steps = []
        pending_tool_calls = {}
        step_index = 0
        total_duration = 0
        total_errors = 0
        total_tool_calls = 0
        last_user_msg = ""
        
        for msg in messages:
            role = msg.get("role", "")
            if msg.get("isMeta"):
                continue
            content_blocks = msg.get("content", [])
            if not isinstance(content_blocks, list):
                continue
            
            if role == "assistant":
                msg_duration = msg.get("duration_ms", 0) or 0
                total_duration += msg_duration
                api_error = msg.get("apiError") or msg.get("error") or ""
                
                step_count_in_msg = 0
                for block in content_blocks:
                    btype = block.get("type", "")
                    if btype == "tool_use":
                        tc = ToolCall(
                            tool_name=block.get("name", "unknown"),
                            arguments=block.get("input", {}),
                        )
                        step = TraceStep(
                            step_index=step_index,
                            step_type=StepType.COMMAND_EXECUTION,
                            action=block.get("name", "tool_call"),
                            tool_calls=[tc],
                            duration_ms=0,
                            input_data=str(block.get("input", {}))[:500],
                        )
                        tid = block.get("id", "")
                        if tid:
                            pending_tool_calls[tid] = step
                        if api_error:
                            step.errors.append(str(api_error)[:200])
                        steps.append(step)
                        step_index += 1
                        step_count_in_msg += 1
                        total_tool_calls += 1
                    elif btype == "text":
                        step = TraceStep(
                            step_index=step_index,
                            step_type=StepType.FINAL_OUTPUT,
                            action="assistant_response",
                            thinking=block.get("text", ""),
                        )
                        steps.append(step)
                        step_index += 1
                        step_count_in_msg += 1
                
                if step_count_in_msg > 0 and msg_duration > 0:
                    per_step = msg_duration // step_count_in_msg
                    for s in steps[-step_count_in_msg:]:
                        s.duration_ms = per_step
            
            elif role == "user":
                for block in content_blocks:
                    if block.get("type") == "tool_result":
                        tid = block.get("tool_use_id", "")
                        if tid in pending_tool_calls:
                            step = pending_tool_calls.pop(tid)
                            if step.tool_calls:
                                tc = step.tool_calls[0]
                                tc.result = str(block.get("content", ""))[:1000]
                                step.output_data = tc.result[:500]
                                is_err = block.get("is_error", False)
                                if is_err:
                                    tc.error = str(block.get("content", ""))[:200]
                                    step.errors.append(str(block.get("content", ""))[:200])
                                    total_errors += 1
                    
                    if block.get("type") == "text":
                        txt = block.get("text", "") or ""
                        if txt.strip():
                            last_user_msg = txt
            
            text_content = msg.get("content", "")
            if isinstance(text_content, str) and text_content.strip() and role == "user":
                last_user_msg = text_content
        
        return ExecutionTrace(
            trace_id=_uuid.uuid4().hex[:12],
            task_description=last_user_msg,
            steps=steps,
            execution_metrics=ExecutionMetrics(
                total_steps=len(steps),
                total_duration_ms=total_duration,
                error_count=total_errors,
                tool_call_count=total_tool_calls,
            ),
        )


    def _conversation_is_successful(self, messages: list[dict]) -> bool:
        """Check if the task ultimately succeeded (based on final assistant reply)."""
        def _extract_text(content):
            """Extract plain text from content that may be str or list-of-blocks."""
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                texts = []
                for block in content:
                    if isinstance(block, dict):
                        if block.get("type") == "text":
                            texts.append(block.get("text", ""))
                        elif block.get("type") == "tool_result":
                            txt = block.get("content", "")
                            texts.append(str(txt) if not isinstance(txt, str) else txt)
                    elif isinstance(block, str):
                        texts.append(block)
                return " ".join(texts)
            return str(content)

        assistant_msgs = [m for m in messages if m.get("role") == "assistant"]
        if not assistant_msgs:
            return False
        last = _extract_text(assistant_msgs[-1].get("content") or "").strip()
        if len(last) < 100:
            return False
        failure_signals = ["i cannot complete", "i'm unable to", "i can't complete",
                           "failed to", "unable to complete", "task failed",
                           "could not complete", "sorry, i couldn't"]
        for sig in failure_signals:
            if sig in last.lower():
                return False
        user_msgs = [m for m in messages if m.get("role") == "user"]
        if user_msgs:
            reject = ["\u4e0d\u5bf9", "\u9519\u4e86", "\u4e0d\u884c", "\u4e0d\u662f\u8fd9\u6837",
                      "wrong", "incorrect", "not what", "still broken"]
            last_user = _extract_text(user_msgs[-1].get("content") or "").lower()
            for sig in reject:
                if sig in last_user:
                    return False
        return True

    def _llm_extract_skill_params(self, messages: list[dict]) -> dict | None:
        """LLM extracts structured skill params from a successful conversation."""
        if not self.proposal_generator.llm_caller:
            return None
        def _extract_text(content):
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                texts = []
                for block in content:
                    if isinstance(block, dict):
                        if block.get("type") == "text":
                            texts.append(block.get("text", ""))
                        elif block.get("type") == "tool_result":
                            txt = block.get("content", "")
                            texts.append(str(txt) if not isinstance(txt, str) else txt)
                    elif isinstance(block, str):
                        texts.append(block)
                return " ".join(texts)
            return str(content)

        task_desc = ""
        for m in messages:
            if m.get("role") == "user":
                task_desc = _extract_text(m.get("content") or "")[:200]
                break
        conv_parts = []
        for m in messages[-10:]:
            role = m.get("role", "?")
            content = _extract_text(m.get("content") or "")[:1500]
            conv_parts.append(f"[{role}]\n{content}\n")
        conv_text = "\n---\n".join(conv_parts)
        prompt = SKILL_EXTRACT_PROMPT.format(
            task_description=task_desc,
            conversation_text=conv_text,
        )
        from src.utils import extract_json_from_llm
        raw = self.proposal_generator.llm_caller(prompt)
        data = extract_json_from_llm(raw)
        if not data or not data.get("name") or not data.get("sop"):
            return None
        return {
            "name": data["name"],
            "trigger_condition": data.get("trigger_condition", ""),
            "summary": data.get("summary", ""),
            "sop": data["sop"] if isinstance(data["sop"], list) else [data["sop"]],
            "pitfalls": data.get("pitfalls", []),
            "scripts": {},
            "test_cases": [],
        }

    def process_conversation(self, messages: list[dict], tool_events: list = None, transcript_path: str = None, focus_areas: list[str] | None = None, multi_traces: list[dict] | None = None) -> dict:
        """Full evolution pipeline for conversation messages.

        Steps:
        1. messages -> shallow ExecutionTrace -> 7-dim structured analysis
        2. LLM judges sufficiency with full raw messages (no truncation)
        3. Section analysis
        4. ProposalGenerator.generate()
        5. SafetyGuard.check()
        6. Skill extraction (if conversation is successful)
        """
        # Auto-detect: if messages are full JSON dicts (from transcript), use _transcript_to_trace
        if self._is_full_json_message(messages):
            trace = self._transcript_to_trace(messages)
        else:
            trace = self._messages_to_trace(messages)
        report = self.trace_analyzer._analyze_structured(trace)
        if self.proposal_generator.llm_caller:
            from src.utils import extract_json_from_llm
            full_conv = []
            for m in messages:
                role = m.get("role", "?")
                raw = m.get("content") or ""
                if isinstance(raw, list):
                    texts = []
                    for block in raw:
                        if isinstance(block, dict) and block.get("type") == "text":
                            texts.append(block.get("text", ""))
                    raw = " ".join(texts)
                full_conv.append(f"[{role}]\n{raw}\n")
            conv_full = "\n---\n".join(full_conv[-15:])
            summary = self._summarize_findings(report)
            judge_prompt = (
                "# Analysis Sufficiency Check\n\n"
                "The structured analysis found these issues:\n"
                f"{summary}\n\n"
                "Full conversation:\n"
                f"{conv_full[:4000]}\n\n"
                "## Task\n"
                "1. Are the findings from structured analysis sufficient to understand what went wrong?\n"
                "2. If not, provide additional analysis based on the raw conversation.\n\n"
                "## Output Format\n"
                '{{\"sufficient\": true, \"additional_analysis\": {{\"errors\": [], \"efficiency_issues\": [], \"prompt_issues\": [], \"skill_issues\": []}}}}\n'
            )
            raw = self.proposal_generator.llm_caller(judge_prompt)
            judge = extract_json_from_llm(raw) if raw else None
            if judge and not judge.get("sufficient", True):
                extra = judge.get("additional_analysis", {})
                for key in ["errors", "efficiency_issues", "prompt_issues", "skill_issues"]:
                    for item in extra.get(key, []):
                        if isinstance(item, str):
                            getattr(report, key, []).append({"description": item} if key == "errors" else {"issue": item})
                        else:
                            getattr(report, key, []).append(item)
                if extra.get("errors") or extra.get("efficiency_issues"):
                    report.needs_optimization = True

                # Multi-trace: cross-trace pattern analysis
        if multi_traces and self.proposal_generator.llm_caller:
            from src.utils import extract_json_from_llm
            all_messages = [messages] + [t["messages"] for t in multi_traces]
            traces = []
            for msgs in all_messages:
                if self._is_full_json_message(msgs):
                    traces.append(self._transcript_to_trace(msgs))
                else:
                    traces.append(self._messages_to_trace(msgs))
            report = self._cross_trace_analysis(all_messages, traces, focus_areas)
            if report.section_analyses and any(sa.needs_optimization for sa in report.section_analyses):
                report.needs_optimization = True
        else:
            # Single-trace: structured analysis already done above.
            # Just add per-section analysis here.
            report.section_analyses = self.trace_analyzer._analyze_sections(trace, report, transcript_path=transcript_path)
            if any(sa.needs_optimization for sa in report.section_analyses):
                report.needs_optimization = True

        proposals = self.proposal_generator.generate(report, focus_areas=focus_areas)
        safe_proposals = []
        for p in proposals:
            if self.safety_guard.check_proposal_safety(p):
                safe_proposals.append(self._proposal_to_dict(p))

        extracted_skill = None
        if focus_areas is None or "skill" in focus_areas:
            if self._conversation_is_successful(messages):
                params = self._llm_extract_skill_params(messages)
                if params:
                    try:
                        creator = SkillCreator(clawcodex_agents_dir=self.clawcodex_agents_dir)
                        ok, msg = creator.create_skill(params)
                        if ok:
                            extracted_skill = {"name": params["name"], "message": msg}
                            logger.info("Skill extracted: %s - %s", params["name"], msg)
                    except Exception as e:
                        logger.warning("Skill extraction error: %s", e)

        return {
            "proposals": safe_proposals,
            "extracted_skill": extracted_skill,
        }

    def _proposal_to_dict(self, p) -> dict:
        """Convert an OptimizationProposal to a serializable dict."""
        from src.utils import section_id_to_var_name, _find_prompt_assembly_path
        path = ""
        if hasattr(p, "proposal_type") and hasattr(p.proposal_type, "value") and p.proposal_type.value == "prompt_optimization":
            if section_id_to_var_name(p.target):
                path = _find_prompt_assembly_path()
        return {
            "type": p.proposal_type.value if hasattr(p.proposal_type, "value") else str(p.proposal_type),
            "target": p.target,
            "reason": p.reason,
            "priority": p.priority,
            "file_path": path,
            "original_content": p.current_content,
            "new_content": p.proposed_content,
        }


    @staticmethod
    def _format_messages(messages, max_msgs=0):
        """Format messages for LLM prompts. If max_msgs > 0, only take last N."""
        msgs = messages[-max_msgs:] if max_msgs > 0 else messages
        parts = []
        for m in msgs:
            role = m.get("role", "?")
            raw = m.get("content") or ""
            if isinstance(raw, list):
                texts = []
                for block in raw:
                    if isinstance(block, dict) and block.get("type") == "text":
                        texts.append(block.get("text", ""))
                raw = " ".join(texts)
            parts.append(f"[{role}]\n{raw}\n")
        return "\n---\n".join(parts)

    def _summarize_findings(self, report) -> str:
        """Summarize AnalysisReport findings for LLM briefing."""
        parts = []
        if report.errors:
            parts.append(f"Errors: {len(report.errors)}")
        if report.efficiency_issues:
            parts.append(f"Efficiency: {len(report.efficiency_issues)} issues")
        if report.skill_usage_analysis:
            parts.append(f"Skill issues: {len(report.skill_usage_analysis)}")
        if report.prompt_issues:
            parts.append(f"Prompt issues: {len(report.prompt_issues)}")
        if report.uncovered_error_patterns:
            parts.append(f"Uncovered errors: {len(report.uncovered_error_patterns)}")
        if report.hook_opportunities:
            parts.append(f"Hook opportunities: {len(report.hook_opportunities)}")
        return "; ".join(parts) or "No significant issues detected."

    # --- Application ---

    @staticmethod
    def _backup_file(file_path: str, backup_root: str = "data/versions", version: str | None = None) -> str | None:
        """Backup a single file with manifest. Returns version string or None."""
        import json as _j
        if version is None:
            ts = _datetime.now().strftime("%Y%m%d_%H%M%S")
            version = f"v{ts}"
        backup_dir = _os.path.join(backup_root, version)
        safe_name = file_path.replace(":", "_").replace("\\", "_").replace("/", "_").replace("\\", "_")
        backup_path = _os.path.join(backup_dir, safe_name)
        _os.makedirs(backup_dir, exist_ok=True)
        try:
            _shutil.copy2(file_path, backup_path)
        except Exception as e:
            logger.warning("Backup failed for %s: %s", file_path, e)
            return None
        # Append to manifest
        manifest_path = _os.path.join(backup_dir, "manifest.json")
        manifest = []
        if _os.path.isfile(manifest_path):
            try:
                manifest = _j.loads(open(manifest_path, encoding="utf-8").read())
            except Exception:
                manifest = []
        manifest.append({"original": file_path, "backup": safe_name, "op": "restore"})
        open(manifest_path, "w", encoding="utf-8").write(_j.dumps(manifest, ensure_ascii=False, indent=2))
        logger.info("Backed up %s -> %s", file_path, backup_path)
        return version

    @staticmethod
    def _record_skill_manifest(version: str, skill_name: str, skill_dir: str, is_addition: bool = True, backup_root: str = "data/versions") -> None:
        """Record a skill operation in the version manifest for rollback."""
        import json as _j
        backup_dir = _os.path.join(backup_root, version)
        manifest_path = _os.path.join(backup_dir, "manifest.json")
        _os.makedirs(backup_dir, exist_ok=True)
        manifest = []
        if _os.path.isfile(manifest_path):
            try:
                manifest = _j.loads(open(manifest_path, encoding="utf-8").read())
            except Exception:
                manifest = []
        if is_addition:
            manifest.append({"op": "delete_skill", "skill_name": skill_name, "skill_dir": skill_dir})
        open(manifest_path, "w", encoding="utf-8").write(_j.dumps(manifest, ensure_ascii=False, indent=2))

    @staticmethod
    def _collect_skill_files(name: str, clawcodex_agents_dir: str | None = None) -> list[str]:
        """Collect all files that _write_clawcodex_markdown will overwrite for a skill."""
        paths = []
        # Agents directories
        agent_dirs = []
        if clawcodex_agents_dir:
            agent_dirs.append(clawcodex_agents_dir)
        agent_dirs.append(_os.path.expanduser("~/.claude/agents"))
        _project_root = _os.path.normpath(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", ".."))
        agent_dirs.append(_os.path.join(_project_root, ".claude", "agents"))
        for d in agent_dirs:
            paths.append(_os.path.join(d, f"{name}.md"))
        # Skill directories
        _home_skill = _os.path.expanduser("~/.clawcodex/skills")
        skill_dirs = [
            _os.path.expanduser("~/.claude/skills"),
            _os.path.join(_project_root, ".claude", "skills"),
        ]
        if _os.path.isdir(_os.path.join(_home_skill, name)):
            skill_dirs.append(_home_skill)
        for d in set(skill_dirs):
            paths.append(_os.path.join(d, name, "skill.md"))
        return [p for p in paths if _os.path.isfile(p)]

    @staticmethod
    def _modify_skill(params: dict, session_version: str | None = None,
                      clawcodex_agents_dir: str | None = None) -> tuple[bool, str]:
        """Modify an existing skill in-place: backup all files, then overwrite."""
        name = params.get("name", "")
        if not name:
            return False, "Skill name is required"
        # 1. Backup each existing file before overwriting
        files = SelfEvolvingSystem._collect_skill_files(name, clawcodex_agents_dir)
        for fp in files:
            SelfEvolvingSystem._backup_file(fp, version=session_version)
        # 2. Overwrite all files with new content
        from src.skill_creator import SkillCreator
        creator = SkillCreator(clawcodex_agents_dir=clawcodex_agents_dir)
        creator._write_clawcodex_markdown(name, params)
        return True, f"Skill '{name}' modified successfully."


    def _cross_trace_analysis(self, all_messages, all_traces, focus_areas=None):
        """Two-stage cross-trace analysis with direct ProposalGenerator output.

        Stage 1: heuristic _analyze_structured per trace -> summaries.
        Stage 2: LLM finds cross-trace patterns AND produces section_analyses/skill_issues.
        Stage 3 (optional): full raw messages for traces where summary was insufficient.

        Returns an AnalysisReport with fields directly consumable by ProposalGenerator.generate().
        """
        from src.utils import extract_json_from_llm, extract_clawcodex_system_sections
        from src.models import AnalysisReport as _AR, SectionAnalysis as _SA

        # Stage 1: heuristic analysis per trace
        reports = [self.trace_analyzer._analyze_structured(t) for t in all_traces]

        summaries = []
        for i, (msgs, r) in enumerate(zip(all_messages, reports)):
            task = r.task_description or "unknown"
            error_summary = "?".join(
                f"{e.get('type','?')}:{e.get('description','')[:60]}"
                for e in r.errors[:5]
            )
            summaries.append(
                f"Trace {i}: {task}\n"
                f"  Errors: {error_summary or 'none'}\n"
                f"  Efficiency: {len(r.efficiency_issues)} issues\n"
                f"  Steps: {r.compressed_summary[:200]}\n"
                f"  Messages: {len(msgs)}\n"
            )

        cross_summary = "\n".join(summaries)

        # Build system sections info for prompt-related analysis
        sections_text = ""
        if focus_areas is None or "prompt" in focus_areas:
            try:
                sections = extract_clawcodex_system_sections()
                if sections:
                    sec_lines = []
                    for k in sorted(sections.keys()):
                        sec_lines.append(f"- {k}: {sections[k][:100]}")
                    sections_text = "\n".join(sec_lines)
            except Exception:
                sections_text = ""

        section_info = (
            f"\n## ClawCodex System Prompt Sections\n{sections_text}\n"
            if sections_text else ""
        )

        # Build additional requirements based on focus
        extra_reqs = []
        extra_fields = []
        if focus_areas is None or "prompt" in focus_areas:
            extra_reqs.append("1. If you find prompt-related patterns, output \"section_analyses\": [{{\"section_id\": \"...\", \"issues_found\": [...], \"suggested_improvement\": \"...\", \"reasoning\": \"...\"}}]\n   - section_id must be one of the existing ClawCodex system prompt sections listed above that you believe needs modification\n   - DO NOT output section_id \"_skill_extraction\"")
            extra_fields.append('"section_analyses": []')
        if focus_areas is None or "skill" in focus_areas:
            extra_reqs.append("2. If you find skill-related patterns, output \"skill_issues\": [{{\"skill_name\": \"...\", \"current_behavior\": \"...\", \"suggested_change\": \"...\", \"reason\": \"...\", \"priority\": 2}}]")
            extra_reqs.append("3. If the cross-trace analysis reveals a missing skill that would help across traces, output it as \"skill_usage_analysis\": [{{\"issue\": \"...\", \"skill_content\": {{\"name\": \"...\", \"summary\": \"...\", \"sop\": [...], \"pitfalls\": [...]}}, \"match_score\": 0.8}}]")
            extra_fields.append('"skill_issues": []')
            extra_fields.append('"skill_usage_analysis": []')
        extra_fields.append('"task_description": ""')

        extra_reqs_text = "\n\n".join(extra_reqs)
        extra_output_text = ",\n".join(extra_fields)

        # Stage 2: LLM finds cross-trace patterns + structured analysis data
        stage2_prompt = f"""# Cross-Trace Pattern Analysis

{len(all_traces)} task execution traces from the same system.

## Structured Analysis Summaries
{cross_summary}{section_info}
## Task
1. Identify issues that appear in MULTIPLE traces. Only report patterns seen in at least 2 traces.
2. For each pattern, list which traces are affected.
3. If any trace's summary is insufficient to confirm a pattern, note its index.

## Additional Requirement
Based on the cross-trace patterns above, also produce structured analysis data that can directly drive optimization proposals:

{extra_reqs_text}

## Output
{{"patterns": [
    {{"type": "error|efficiency|prompt|skill",
      "description": "...",
      "affected_traces": [0, 2],
      "priority": 1-3,
      "need_raw_traces": [],
    }}
],
{extra_output_text}
}}"""

        raw = self.proposal_generator.llm_caller(stage2_prompt)
        stage2 = extract_json_from_llm(raw) or {}
        patterns = stage2.get("patterns", [])

        # Collect trace indices that need Stage 3
        need_raw = set()
        for p in patterns:
            need_raw.update(p.get("need_raw_traces", []))

        # Stage 3: full raw messages for traces that need it
        if need_raw:
            raw_parts = []
            for idx in need_raw:
                if 0 <= idx < len(all_messages):
                    msgs_text = self._format_messages(all_messages[idx])
                    raw_parts.append(f"=== Trace {idx} Full Messages ===\n{msgs_text}")
            if raw_parts:
                stage3_prompt = stage2_prompt + "\n\n## Additional Raw Messages for Traces " + str(sorted(need_raw)) + "\n" + "\n".join(raw_parts)
                raw2 = self.proposal_generator.llm_caller(stage3_prompt)
                stage3 = extract_json_from_llm(raw2) or {}
                patterns = stage3.get("patterns", patterns)
                # Merge structured data from Stage 3 (prefer over Stage 2)
                if stage3.get("section_analyses"):
                    stage2["section_analyses"] = stage3["section_analyses"]
                if stage3.get("skill_issues"):
                    stage2["skill_issues"] = stage3["skill_issues"]
                if stage3.get("skill_usage_analysis"):
                    stage2["skill_usage_analysis"] = stage3["skill_usage_analysis"]
                if stage3.get("task_description"):
                    stage2["task_description"] = stage3["task_description"]

        # Build report
        report = _AR(
            trace_id=f"cross_{len(all_traces)}",
            needs_optimization=bool(patterns),
        )
        target_list = {
            "error": "errors", "efficiency": "efficiency_issues",
            "prompt": "prompt_issues", "skill": "skill_issues",
        }
        for p in patterns:
            key = target_list.get(p.get("type", "error"), "errors")
            getattr(report, key).append({
                "description": p.get("description", ""),
                "affected_traces": p.get("affected_traces", []),
                "priority": p.get("priority", 3),
            })

        # Fill section_analyses from Stage 2/3 output for Path 1 (_generate_from_sections)
        report.section_analyses = []
        for sa_data in stage2.get("section_analyses", []):
            report.section_analyses.append(_SA(
                section_id=sa_data.get("section_id", ""),
                section_content="",
                needs_optimization=True,
                issues_found=sa_data.get("issues_found", []),
                suggested_improvement=sa_data.get("suggested_improvement", ""),
                reasoning=sa_data.get("reasoning", ""),
            ))

        # Fill skill_issues / skill_usage_analysis for Path 2b (_generate_skill_proposals_llm)
        report.skill_issues.extend(stage2.get("skill_issues", []))
        report.skill_usage_analysis.extend(stage2.get("skill_usage_analysis", []))

        # Fill task_description
        report.task_description = stage2.get("task_description",
                                             f"Cross-trace analysis of {len(all_traces)} traces")

        # Merge uncovered_error_patterns and hook_opportunities from per-trace reports for Path 3
        seen_error_patterns = set()
        for r in reports:
            for ep in r.uncovered_error_patterns:
                key = ep.get("error_type", "") + ":" + str(ep.get("step_index", ""))
                if key not in seen_error_patterns:
                    seen_error_patterns.add(key)
                    report.uncovered_error_patterns.append(ep)
            report.hook_opportunities.extend(r.hook_opportunities)
            report.loop_termination_issues.extend(r.loop_termination_issues)

        if report.section_analyses or report.skill_issues or report.skill_usage_analysis or report.uncovered_error_patterns:
            report.needs_optimization = True

        return report
    def apply_proposal(self, proposal_dict: dict) -> str | None:
        """Apply a single proposal with safety check + version backup + optional SkillCreator."""
        from src.models import OptimizationProposal, ProposalType, ProposalStatus
        ptype_str = proposal_dict.get("type", "prompt_optimization")
        try:
            ptype = ProposalType(ptype_str)
        except ValueError:
            ptype = ProposalType.PROMPT_OPTIMIZATION
        file_path = proposal_dict.get("file_path", "")
        proposed_content = proposal_dict.get("proposed_content", "")
        current_content = proposal_dict.get("current_content", "")
        if not file_path or not proposed_content:
            return None
        proposal = OptimizationProposal(
            proposal_type=ptype,
            target=proposal_dict.get("target", ""),
            current_content=current_content,
            proposed_content=proposed_content,
            reason=proposal_dict.get("reason", ""),
            priority=proposal_dict.get("priority", 3),
            status=ProposalStatus.PENDING,
        )
        if not self.safety_guard.check_proposal_safety(proposal):
            logger.warning("Safety check failed for: %s", file_path)
            return None

        # Skill creation: route through SkillCreator
        # Skill creation: route through SkillCreator
        if ptype == ProposalType.SKILL_ADDITION:
            try:
                import json as _j
                params = _j.loads(proposed_content) if proposed_content.startswith("{") else {"name": proposal_dict.get("target", "skill"), "summary": proposed_content, "sop": [], "pitfalls": []}
                session_version = proposal_dict.get("session_version")
                creator = SkillCreator(clawcodex_agents_dir=self.clawcodex_agents_dir)
                ok, msg = creator.create_skill(params)
                if ok:
                    skill_name = params.get("name", proposal_dict.get("target", "skill"))
                    skill_dir = _os.path.expanduser(_os.path.join("~", ".clawcodex", "skills", skill_name))
                    ver = session_version or _datetime.now().strftime("v%Y%m%d_%H%M%S")
                    self._record_skill_manifest(ver, skill_name, skill_dir, is_addition=True)
                    logger.info("Skill created: %s - %s", skill_name, msg)
                    return ver
                else:
                    logger.warning("Skill creation failed: %s", msg)
                    return None
            except Exception as e:
                logger.warning("Skill creation error: %s", e)
                return None

        # Skill modification: in-place update without duplicate check
        if ptype == ProposalType.SKILL_MODIFICATION:
            try:
                import json as _j
                params = _j.loads(proposed_content) if proposed_content.startswith("{") else {"name": proposal_dict.get("target", "skill"), "summary": proposed_content, "sop": [], "pitfalls": []}
                session_version = proposal_dict.get("session_version")
                ok, msg = self._modify_skill(params, session_version, self.clawcodex_agents_dir)
                if ok:
                    logger.info("Skill modified: %s - %s", params.get("name", ""), msg)
                    return session_version or _datetime.now().strftime("v%Y%m%d_%H%M%S")
                else:
                    logger.warning("Skill modification failed: %s", msg)
                    return None
            except Exception as e:
                logger.warning("Skill modification error: %s", e)
                return None


        # Prompt optimization: AST-guided surgical replace in prompt_assembly.py
        if ptype == ProposalType.PROMPT_OPTIMIZATION:
            from src.utils import replace_prompt_section_in_file
            target_id = proposal_dict.get("target", "")
            session_version = proposal_dict.get("session_version")
            try:
                self._backup_file(file_path, version=session_version)
                if replace_prompt_section_in_file(proposed_content, target_id, file_path):
                    version = session_version or _datetime.now().strftime("v%Y%m%d_%H%M%S")
                    logger.info("Replaced prompt section '%s' in %s", target_id, file_path)
                    return version
            except Exception as e:
                logger.warning("AST replace failed for %s section %s: %s", file_path, target_id, e)

        # File backup before write (use _backup_file for consistency)
        version = proposal_dict.get("session_version")
        if _os.path.isfile(file_path):
            version = self._backup_file(file_path, version=version)
        else:
            if version is None:
                ts = _datetime.now().strftime("%Y%m%d_%H%M%S")
                version = f"v{ts}"

        # Write file - snippet replacement (only change targeted part)
        try:
            _os.makedirs(_os.path.dirname(file_path), exist_ok=True)
            if _os.path.isfile(file_path):
                with open(file_path, "r", encoding="utf-8") as f:
                    disk_content = f.read()
            else:
                disk_content = ""
            if current_content and current_content in disk_content:
                # Exact match: replace snippet in-place
                final_content = disk_content.replace(current_content, proposed_content, 1)
                changed = True
            elif current_content:
                # Fuzzy match: try to find similar block
                import difflib
                lines = disk_content.splitlines(True)
                old_lines = current_content.splitlines()
                best_match = None
                best_ratio = 0.0
                for i in range(len(lines) - len(old_lines) + 1):
                    chunk = ''.join(lines[i:i+len(old_lines)])
                    ratio = difflib.SequenceMatcher(None, chunk, current_content).ratio()
                    if ratio > best_ratio:
                        best_ratio = ratio
                        best_match = i
                if best_match is not None and best_ratio > 0.6:
                    before = ''.join(lines[:best_match])
                    after = ''.join(lines[best_match+len(old_lines):])
                    final_content = before + proposed_content + after
                    changed = True
                else:
                    # No match found, write full content
                    final_content = proposed_content
                    changed = True
            else:
                final_content = proposed_content
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(final_content)
            logger.info("Applied (snippet replace): %s", file_path)
        except Exception as e:
            logger.error("Write failed for %s: %s", file_path, e)
            return None

        return version

    def rollback(self, version: str) -> bool:
        """Restore files from a version backup using manifest. Supports op: restore / delete_skill."""
        import json as _j
        backup_dir = _os.path.join("data", "versions", version)
        if not _os.path.isdir(backup_dir):
            logger.warning("Backup version not found: %s", version)
            return False
        manifest_path = _os.path.join(backup_dir, "manifest.json")
        if _os.path.isfile(manifest_path):
            # New style: read manifest
            try:
                manifest = _j.loads(open(manifest_path, encoding="utf-8").read())
            except Exception:
                manifest = []
            restored = 0
            deleted_skills = 0
            for entry in manifest:
                op = entry.get("op", "restore")
                if op == "delete_skill":
                    # Delete a skill that was added
                    skill_dir = entry.get("skill_dir", "")
                    if skill_dir and _os.path.isdir(skill_dir):
                        _shutil.rmtree(skill_dir, ignore_errors=True)
                        deleted_skills += 1
                        logger.info("Deleted skill dir: %s", skill_dir)
                elif op == "restore":
                    orig_path = entry.get("original", "")
                    backup_name = entry.get("backup", "")
                    if not orig_path or not backup_name:
                        continue
                    backup_path = _os.path.join(backup_dir, backup_name)
                    if not _os.path.isfile(backup_path):
                        continue
                    try:
                        _shutil.copy2(backup_path, orig_path)
                        restored += 1
                    except Exception as e:
                        logger.warning("Restore failed for %s: %s", orig_path, e)
            if restored or deleted_skills:
                logger.info("Rolled back %s: restored %d file(s), deleted %d skill(s)", version, restored, deleted_skills)
            return restored > 0 or deleted_skills > 0
        # Legacy: no manifest, try name-based restoration (broken path reconstruction)
        logger.warning("No manifest found in %s; falling back to legacy name-based rollback (may be incorrect)", version)
        restored = 0
        for fname in _os.listdir(backup_dir):
            backup_path = _os.path.join(backup_dir, fname)
            if not _os.path.isfile(backup_path) or fname == "manifest.json":
                continue
            orig_path = fname.replace("_", ":", 1) if ":" in fname else fname
            try:
                _shutil.copy2(backup_path, orig_path)
                restored += 1
            except Exception as e:
                logger.warning("Restore failed for %s: %s", orig_path, e)
        if restored:
            logger.info("Rolled back %d file(s) from version %s (legacy)", restored, version)
        return restored > 0
