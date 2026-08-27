"""Salience gating - filters noise before the mem0 extraction LLM call.

Tier 1: regex + exact phrase matching, skips only turns that are unambiguously noise.
Tier 1.5: regex detection of high-value signals (dates/numbers/proper nouns), passes through directly.
Tier 2: local Ollama small model, message-level salience judgment (keep or skip the whole turn).

Design principle: prove noise, not prove salience. If it cannot be proven -> pass through.
Killing one fact is far worse than letting one noise item through.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("memory-server.gate")


# ─── Data types ──────────────────────────────────────────────────────────────


@dataclass
class GateResult:
    """Result of a single add_memories request after gate filtering."""

    original_messages: list[dict[str, Any]]
    filtered_messages: list[dict[str, Any]]
    skipped: bool = False
    stats: dict[str, int] = field(default_factory=dict)


# ─── Sentence splitter ──────────────────────────────────────────────────────


_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z])")

_ABBREV_PERIODS = frozenset(
    {
        "Dr.",
        "Mr.",
        "Mrs.",
        "Ms.",
        "Prof.",
        "St.",
        "Sr.",
        "Jr.",
        "U.S.",
        "vs.",
        "etc.",
        "e.g.",
        "i.e.",
        "Inc.",
        "Ltd.",
        "Co.",
    }
)


def split_sentences(text: str) -> list[str]:
    """Split into sentences on .!? boundaries (uppercase-first-word heuristic + abbreviation protection), keeping punctuation.

    Only splits when punctuation is followed by a space and an uppercase letter, to avoid cutting abbreviations.
    Abbreviation protection: the period of common abbreviations is temporarily replaced, then restored after splitting.
    """
    protected = text
    for abbrev in _ABBREV_PERIODS:
        protected = protected.replace(abbrev, abbrev[:-1] + "\x00")
    parts = _SPLIT_RE.split(protected)
    return [s.replace("\x00", ".").strip() for s in parts if s.strip()]


# ─── Tier 1: Rule-based filter ──────────────────────────────────────────────

# Noise detection has only two mechanisms:
#   Anchored regex: matches the whole text (^...$), used only for patterns with a predictable structure (greetings/farewells/thanks + optional name).
#   Short-phrase exact matching: exact comparison after lowercasing + stripping punctuation.


class RuleBasedFilter:
    """Tier 1: zero-cost noise filter. Skips only turns that are unambiguously noise.

    Two detection mechanisms:
      Mechanism A - anchored regex (greetings/farewells/thanks + optional name)
      Mechanism B - exact phrase matching

    If noise cannot be proven, pass through. Killing one fact is far worse than letting one noise item through.
    """

    _SPEAKER_PREFIX_RE = re.compile(r"^[A-Z][a-zA-Z\-]+:\s*")

    _PURE_GREETING_RE = re.compile(
        r"^(?:hey|hi|hello|yo|good\s+morning|good\s+evening|morning|howdy|sup|greetings"
        r"|你好|您好|哈喽|嗨|早|早上好|晚上好|下午好|嗨呀)"
        r"\b(?:[,\s]+[A-Z][a-z]+)?[!\.\s。！]*$",
        re.I,
    )

    _PURE_BYE_RE = re.compile(
        r"^(?:bye|goodbye|good\s+night|see\s+you(?:\s+soon|\s+later|\s+around|\s+tomorrow)?|see\s+ya|"
        r"take\s+care|talk\s+later|talk\s+soon|catch\s+you\s+later|ttyl|cya|later|cheers|night"
        r"|再见|拜拜|拜|晚安|明天见|回头见|下次见|走啦|撤了)"
        r"\b(?:[,\s]+[A-Z][a-z]+)?[!\.\s。！]*$",
        re.I,
    )

    _PURE_THANKS_RE = re.compile(
        r"^(?:thanks|thank\s+you|thx|ty|cheers|appreciated|much\s+appreciated|many\s+thanks"
        r"|谢谢|感谢|多谢|谢了|辛苦了|麻烦你了)"
        r"\b(?:[,\s]+[A-Z][a-z]+)?[!\.\s。！]*$",
        re.I,
    )

    _NOISE_CANDIDATE_RE = re.compile(
        r"^(?:hey|hi|hello|yo|thanks?|thank\s+you|thx|bye|goodbye|good\s+(?:morning|evening|night)|"
        r"see\s+you|take\s+care|wow|awesome|cool|great|nice|amazing|haha|lol|hmm|"
        r"ok(?:ay)?|alright|sure|yep|yeah|nope|agreed|exactly|sounds?\s+(?:good|great)|"
        r"got\s+it|will\s+do|you(?:'re| are)\s+welcome|that(?:'s| is)\s+(?:great|cool|nice|exciting)|"
        r"\u4f60\u597d|\u60a8\u597d|\u54c8\u55bd|\u55e8|\u8c22\u8c22|\u611f\u8c22|\u518d\u89c1|\u62dc\u62dc|"
        r"\u665a\u5b89|\u597d\u7684|\u597d|\u55ef|\u54e6|\u54c8\u54c8|\u660e\u767d|\u77e5\u9053\u4e86|"
        r"\u6536\u5230|\u6ca1\u95ee\u9898|\u4e0d\u5ba2\u6c14)",
        re.I,
    )

    _NOISE_PHRASES: frozenset[str] = frozenset(
        {
            "hey",
            "hi",
            "hello",
            "yo",
            "howdy",
            "sup",
            "greetings",
            "good morning",
            "good evening",
            "morning",
            "bye",
            "goodbye",
            "good night",
            "see you",
            "see ya",
            "take care",
            "talk later",
            "talk soon",
            "ttyl",
            "cya",
            "later",
            "night",
            "cheers",
            "thanks",
            "thank you",
            "thx",
            "ty",
            "much appreciated",
            "many thanks",
            "appreciated",
            "thanks again",
            "wow",
            "awesome",
            "cool",
            "great",
            "nice",
            "amazing",
            "sweet",
            "fantastic",
            "wonderful",
            "incredible",
            "bravo",
            "kudos",
            "congrats",
            "yay",
            "whoa",
            "haha",
            "lol",
            "lmao",
            "rofl",
            "hmm",
            "huh",
            "oh",
            "ah",
            "aha",
            "ugh",
            "ooh",
            "ok",
            "okay",
            "alright",
            "sure",
            "yep",
            "yup",
            "yeah",
            "nah",
            "nope",
            "no doubt",
            "for sure",
            "of course",
            "agreed",
            "exactly",
            "absolutely",
            "definitely",
            "indeed",
            "sounds good",
            "sounds great",
            "looks good",
            "will do",
            "got it",
            # Chinese noise
            "你好",
            "您好",
            "哈喽",
            "嗨",
            "早",
            "早上好",
            "晚上好",
            "下午好",
            "再见",
            "拜拜",
            "拜",
            "晚安",
            "明天见",
            "回头见",
            "下次见",
            "谢谢",
            "感谢",
            "多谢",
            "谢了",
            "辛苦了",
            "麻烦你了",
            "好的",
            "好",
            "嗯",
            "哦",
            "啊",
            "诶",
            "唉",
            "是的",
            "对的",
            "没错",
            "可以",
            "行",
            "没问题",
            "不是",
            "不对",
            "不行",
            "不可以",
            "哈哈",
            "呵呵",
            "嘿嘿",
            "嘻",
            "嘻嘻",
            "哇",
            "哇塞",
            "天哪",
            "我的天",
            "明白",
            "明白啦",
            "知道了",
            "收到",
            "了解",
            "好的呀",
            "好嘞",
            "妥了",
            "搞定",
            "继续",
            "请继续",
            "说下去",
            "对",
            "是",
            "嗯嗯",
            "嗯哼",
            "没问题",
            "没事",
            "没关系",
            "不客气",
            "算了",
            "罢了",
        }
    )

    def should_skip_turn(self, messages: list[dict[str, Any]]) -> bool:
        """All messages are unambiguously noise -> True (the whole LLM call can be skipped).
        Any message is not noise -> False (pass through)."""
        if not messages:
            return True

        for msg in messages:
            if not self._is_noise(msg.get("content", "")):
                return False

        return True

    def _is_noise(self, text: str) -> bool:
        """Whether it is unambiguously noise. If it cannot be proven -> False (pass through)."""
        s = self._strip_speaker_prefix(text).strip()
        if not s:
            return True

        if (
            self._PURE_GREETING_RE.match(s)
            or self._PURE_BYE_RE.match(s)
            or self._PURE_THANKS_RE.match(s)
        ):
            return True

        if len(s) <= 30:
            s_bare = s.lower().strip().rstrip("!?.。！？～~…")
            if s_bare in self._NOISE_PHRASES:
                return True

        return False

    def is_noise_candidate(self, text: str) -> bool:
        """Return whether Tier 2 may review this text as social pleasantries."""
        s = self._strip_speaker_prefix(text).strip()
        if not s or len(s) > 200:
            return False
        return self._is_noise(s) or bool(self._NOISE_CANDIDATE_RE.match(s))

    def _strip_speaker_prefix(self, text: str) -> str:
        """Strip the leading 'speaker name: ' prefix from a message's content. Only used by the evaluation pipeline (locomo concatenates the speaker into content); normal user messages do not have this format."""
        m = self._SPEAKER_PREFIX_RE.match(text)
        return text[m.end() :] if m else text


# ─── Tier 1.5: High-value signal detector ───────────────────────────────────


class HighValueSignalDetector:
    """Tier 1.5: regex detection of high-value signals.

    Detects messages containing:
    - year/month/relative time
    - number + context (amount/percentage/duration)
    - proper nouns (non-first words starting with uppercase)
    - URL/email
    - first-person facts, preferences, plans, and long-term interaction instructions
    """

    _YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")

    _MONTH_RE = re.compile(
        r"\b(?:January|February|March|April|May|June|July|August|"
        r"September|October|November|December)\b",
        re.I,
    )

    _RELATIVE_TIME_RE = re.compile(
        r"\b(?:last\s+(?:week|month|year|night|summer|spring|fall|winter)|"
        r"yesterday|today|tomorrow|"
        r"\d+\s+(?:days?|weeks?|months?|years?)\s+ago|"
        r"since\s+\w+)\b",
        re.I,
    )

    _NUMBER_CONTEXT_RE = re.compile(
        r"(?:\$\d+|\d+%|"
        r"\d+\s*(?:years?|months?|weeks?|days?|hours?|minutes?|times?|"
        r"people|kids?|children|cats?|dogs?|books?|miles?|kg|lbs?)\b)",
        re.I,
    )

    _PROPER_NOUN_RE = re.compile(r"\b[A-Z][a-z]{2,}\b")

    _URL_RE = re.compile(r"https?://|www\.|\S+@\S+\.\S+", re.I)

    _FIRST_PERSON_RE = re.compile(
        r"\b(?:i|i'm|i’ve|i've|i'd|i’ll|i'll|my|mine|we|we're|we've|our|ours)\b",
        re.I,
    )

    _ZH_FIRST_PERSON_RE = re.compile(r"(?:我|我的|我们|咱们)")

    _DURABLE_INSTRUCTION_RE = re.compile(
        r"\b(?:remember|from\s+now\s+on|in\s+future|for\s+future|always|never|"
        r"prefer|preference|call\s+me|address\s+me)\b|"
        r"(?:记住|以后|今后|往后|总是|永远|不要再|称呼我|叫我|回答.{0,8}(?:简洁|详细|中文|英文))",
        re.I,
    )

    _SPEAKER_PREFIX_RE = re.compile(r"^[A-Z][a-zA-Z\-]+:\s*")

    def has_high_value_signal(self, text: str, role: str | None = None) -> bool:
        """Whether the message contains a high-value signal. Any rule hit -> True (pass through directly)."""
        s = self._strip_speaker_prefix(text).strip()
        if not s:
            return False

        # First-person expressions by the user usually carry facts, preferences, constraints, or intent.
        # Here we prefer to pass through rather than hand low-entity-density but highly personal
        # information to the small model to be wrongly deleted.
        if role != "assistant" and (
            self._FIRST_PERSON_RE.search(s) or self._ZH_FIRST_PERSON_RE.search(s)
        ):
            return True
        if self._DURABLE_INSTRUCTION_RE.search(s):
            return True

        if self._YEAR_RE.search(s):
            return True
        if self._MONTH_RE.search(s):
            return True
        if self._RELATIVE_TIME_RE.search(s):
            return True
        if self._NUMBER_CONTEXT_RE.search(s):
            return True
        if self._URL_RE.search(s):
            return True

        words = s.split()
        if len(words) > 1:
            for word in words[1:]:
                clean_word = word.strip("'\"''()[]{}.,!?;:")
                if self._PROPER_NOUN_RE.match(clean_word):
                    return True

        return False

    def _strip_speaker_prefix(self, text: str) -> str:
        m = self._SPEAKER_PREFIX_RE.match(text)
        return text[m.end() :] if m else text


# ─── Tier 2: Ollama salience gate ───────────────────────────────────────────

SALIENCE_SYSTEM_PROMPT = """你是个人记忆提取的保守型前置过滤器。你的任务不是判断信息是否足够重要，而是判断它能否被确定为纯噪声。

保留 (salient=true)：
- 包含任何个人事实、偏好、事件、经历、关系、计划
- 包含具体细节：人名、地名、日期、数字、品牌
- 包含提问者的个人信息或经历
- 包含用户对回答方式、称呼、语言、格式的长期偏好或约束
- 包含实质性的解释、建议、决定、纠正或后续可能引用的上下文
- 如果你不确定，回答 true

丢弃 (salient=false)：
- 纯粹的寒暄问候，不含任何新信息
- 纯粹的感叹/应答，不含任何事实
- 纯粹的告别，不含任何事实

只有当整条消息可以被明确改写为“问候/感谢/告别/无信息应答”且不损失任何事实、偏好、意图、约束或上下文时，才能回答 false。
重要：误删一个事实的代价远大于多保留一条噪声。如果不确定，必须回答 true。

输出JSON格式：{"salient": true/false, "reason": "简短原因"}"""

SALIENCE_USER_TEMPLATE = """判断以下对话消息是否包含值得长期记住的个人信息：

{}

输出显著性判定JSON。"""

SALIENCE_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "salient": {"type": "boolean"},
        "reason": {"type": "string"},
    },
    "required": ["salient"],
}


class OllamaSalienceGate:
    """Tier 2: a local Ollama small model performs message-level salience judgment.

    Uses Ollama API's JSON schema constraint for structured output.
    Failure fallback: the message is marked salient (prefer waste over a kill).
    """

    def __init__(self, model: str = "qwen2.5:1.5b", base_url: str = "http://localhost:11434"):
        self.model = model
        self.base_url = base_url.rstrip("/")
        self._session: Any = None

    async def _get_session(self):
        """Lazily initialize the aiohttp session (only needed for async calls)."""
        if self._session is None or self._session.closed:
            import aiohttp

            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=15),
            )
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    def judge_message_sync(self, message: str) -> dict[str, Any]:
        """Synchronous call - judge whether a single message is salient. Returns {"salient": bool, "reason": str}."""
        if not message.strip():
            return {"salient": True, "reason": "空消息，默认放行"}

        user_prompt = SALIENCE_USER_TEMPLATE.format(message)

        try:
            import urllib.request
            import urllib.error

            payload = json.dumps(
                {
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": SALIENCE_SYSTEM_PROMPT},
                        {"role": "user", "content": user_prompt},
                    ],
                    "format": SALIENCE_JSON_SCHEMA,
                    "stream": False,
                    "options": {"temperature": 0.1},
                }
            ).encode("utf-8")

            url = f"{self.base_url}/api/chat"
            req = urllib.request.Request(
                url, data=payload, headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                body = json.loads(resp.read().decode("utf-8"))

            raw = body.get("message", {}).get("content", "")
            if not raw:
                logger.warning("Ollama 门控：空响应，默认放行")
                return {"salient": True, "reason": "兜底: 空响应"}

            return self._parse_response(raw)

        except Exception as exc:
            logger.warning(
                "Ollama 门控调用失败 (%s)，默认放行: %s", type(exc).__name__, str(exc)[:120]
            )
            return {"salient": True, "reason": f"兜底: {type(exc).__name__}"}

    async def judge_message_async(self, message: str) -> dict[str, Any]:
        """Asynchronous call - judge whether a single message is salient. Returns {"salient": bool, "reason": str}."""
        if not message.strip():
            return {"salient": True, "reason": "空消息，默认放行"}

        user_prompt = SALIENCE_USER_TEMPLATE.format(message)

        try:
            session = await self._get_session()
            payload = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": SALIENCE_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                "format": SALIENCE_JSON_SCHEMA,
                "stream": False,
                "options": {"temperature": 0.1},
            }
            async with session.post(f"{self.base_url}/api/chat", json=payload) as resp:
                resp.raise_for_status()
                body = await resp.json()

            raw = body.get("message", {}).get("content", "")
            if not raw:
                logger.warning("Ollama 门控：空响应，默认放行")
                return {"salient": True, "reason": "兜底: 空响应"}

            return self._parse_response(raw)

        except Exception as exc:
            logger.warning("Ollama 门控异步调用失败，默认放行: %s", str(exc)[:120])
            return {"salient": True, "reason": f"兜底: {type(exc).__name__}"}

    def _parse_response(self, raw: str) -> dict[str, Any]:
        """Parse the Ollama JSON response into a message-level salience judgment."""
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            json_match = re.search(r"\{[\s\S]*\}", raw)
            if json_match:
                try:
                    data = json.loads(json_match.group())
                except json.JSONDecodeError:
                    logger.warning("Ollama 门控：无法解析响应，默认放行")
                    return {"salient": True, "reason": "兜底: JSON 解析失败"}
            else:
                return {"salient": True, "reason": "兜底: 无 JSON"}

        salient = data.get("salient", True)
        reason = data.get("reason", "")
        return {"salient": bool(salient), "reason": reason}


# ─── Orchestrator ───────────────────────────────────────────────────────────


class SalienceGate:
    """
    Salience gate orchestrator.
    """

    def __init__(
        self,
        rule_filter: RuleBasedFilter | None = None,
        signal_detector: HighValueSignalDetector | None = None,
        ollama_gate: OllamaSalienceGate | None = None,
    ):
        self.rule_filter = rule_filter or RuleBasedFilter()
        self.signal_detector = signal_detector or HighValueSignalDetector()
        self.ollama_gate = ollama_gate

    @classmethod
    def from_config(cls, gate_config: dict[str, Any]) -> SalienceGate | None:
        """Create a SalienceGate from the config dict. Returns None when disabled.

        When ollama_model is "none"/"disabled"/"off"/empty string, only Tier 1 + Tier 1.5 are enabled.
        """
        if not gate_config.get("enabled", True):
            logger.info("Salience gate 已禁用 (SALIENCE_GATE_ENABLED=false)")
            return None

        ollama_gate = None
        ollama_model = gate_config.get("ollama_model", "qwen2.5:1.5b")
        ollama_base_url = gate_config.get("ollama_base_url", "http://localhost:11434")

        if (
            ollama_model
            and ollama_model.lower() not in ("none", "disabled", "off", "")
            and ollama_base_url
        ):
            ollama_gate = OllamaSalienceGate(model=ollama_model, base_url=ollama_base_url)
            logger.info(
                "Salience gate: Tier2 Ollama model=%s, base_url=%s", ollama_model, ollama_base_url
            )

        gate = cls(ollama_gate=ollama_gate)
        logger.info(
            "Salience gate 初始化: Tier1=RuleBasedFilter, Tier1.5=HighValueSignalDetector, Tier2=%s",
            type(ollama_gate).__name__ if ollama_gate else "None",
        )
        return gate

    def filter_messages(self, messages: list[dict[str, Any]]) -> GateResult:
        """Apply gating to a message list.

        The returned GateResult contains:
          - skipped=True -> the whole request is noise, returns an empty result
        """
        stats: dict[str, int] = {
            "rule_turns_skipped": 0,
            "signal_passthrough": 0,
            "ollama_kept": 0,
            "ollama_skipped": 0,
            "ollama_calls": 0,
            "atomic_passthrough": 0,
            "conservative_passthrough": 0,
        }

        if not messages:
            return GateResult(messages, [], skipped=True, stats=stats)

        # ── Step 1: Tier 1 turn-level skip ──
        if self.rule_filter.should_skip_turn(messages):
            stats["rule_turns_skipped"] = 1
            logger.debug("门控 Tier1: 跳过整条 turn (%d 条消息)", len(messages))
            return GateResult(messages, [], skipped=True, stats=stats)

        # No Ollama -> pass through unchanged
        if not self.ollama_gate:
            return GateResult(messages, messages, skipped=False, stats=stats)

        # ── Step 2: if any message has a high-value signal, pass the whole turn through unchanged ──
        # mem0's extraction depends on user/assistant context; deleting per-message would turn a
        # complete turn into semantic fragments. Therefore gating only makes request-level
        # decisions, not message-level trimming.
        for msg in messages:
            content = msg.get("content", "")
            if not content.strip():
                continue

            if self.signal_detector.has_high_value_signal(content, role=msg.get("role")):
                stats["signal_passthrough"] += 1
                stats["atomic_passthrough"] = 1
                logger.debug("门控 Tier1.5: 高价值信号，整条 turn 放行 '%s'", content[:60])
                return GateResult(messages, messages, skipped=False, stats=stats)

        # ── Step 3: skip only when all messages are explicitly judged noise by Tier 2 ──
        # If any message is kept, restore the full turn to avoid context breaks.
        if any(
            msg.get("content", "").strip()
            and not self.rule_filter.is_noise_candidate(msg.get("content", ""))
            for msg in messages
        ):
            stats["conservative_passthrough"] = 1
            stats["atomic_passthrough"] = 1
            return GateResult(messages, messages, skipped=False, stats=stats)

        for msg in messages:
            content = msg.get("content", "")
            if not content.strip():
                continue

            stats["ollama_calls"] += 1
            judgment = self.ollama_gate.judge_message_sync(content)
            salient = judgment.get("salient", True)
            reason = judgment.get("reason", "")

            if salient:
                stats["ollama_kept"] += 1
                stats["atomic_passthrough"] = 1
                logger.debug(
                    "门控 Tier2: 消息显著，整条 turn 放行 '%s' (原因: %s)", content[:60], reason
                )
                return GateResult(messages, messages, skipped=False, stats=stats)
            else:
                stats["ollama_skipped"] += 1
                logger.debug("门控 Tier2: 候选噪声 '%s' (原因: %s)", content[:60], reason)

        logger.info(
            "门控: Tier2 确认整条 turn 为噪声 | 消息=%d ollama跳过=%d ollama调用=%d",
            len(messages),
            stats["ollama_skipped"],
            stats["ollama_calls"],
        )
        return GateResult(messages, [], skipped=True, stats=stats)
