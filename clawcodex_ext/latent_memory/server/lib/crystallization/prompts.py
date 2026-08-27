"""Prompts and JSON Schemas used for semantic crystallization."""

import re

# Language detection: determine the dominant language of the input by character proportion.
# Chinese: CJK unified ideograph range
_CJK_PATTERN = re.compile(r"[\u4e00-\u9fff]")
# English words (contiguous Latin letter sequences)
_LATIN_WORD_PATTERN = re.compile(r"[A-Za-z]+")


def detect_dominant_language(*texts: str) -> str:
    """Detect the overall dominant language of multiple texts.

    Chinese characters are counted per "character" (each hanzi is an independent semantic unit),
    English is counted per "word" (space-separated words), not by letter count.
    Returns "zh" or "en". Empty texts do not participate in counting; if all are empty, defaults to "zh".
    """
    zh_count = 0
    en_count = 0
    for text in texts or ():
        if not isinstance(text, str):
            continue
        zh_count += len(_CJK_PATTERN.findall(text))
        # Count English by word: extract contiguous Latin letter sequences as words
        en_count += len(_LATIN_WORD_PATTERN.findall(text))
    if en_count > zh_count:
        return "en"
    return "zh"


CLUSTER_QUALITY_SYSTEM_PROMPT = """You are the admission reviewer for long-term memory crystallization. Vector clustering only indicates textual similarity; it does not mean the items are worth crystallizing. You must filter item by item and have the authority to reject some items or the entire candidate cluster.

Crystallization goal: keep only high-quality knowledge that remains understandable, retrievable, and reusable after being separated from the original conversation, original context, and short-term state.

Conditions for accepting each item:
1. The item contains stable preferences, long-term facts, explicit relations, reusable rules/skills, or significant events with a clear absolute time anchor
2. The item can support the cluster's shared knowledge claim, not just superficial textual similarity
3. After removing context such as "this time, here, then, he/it, the above content", the subject, object, and meaning are still clear
4. If it contains relative time such as "yesterday, last week, recently, last month" (excluding regular time like every day, every week), it is acceptable only when observed_at is sufficient to unambiguously convert it to an absolute date; otherwise reject, and never guess dates

Cases that should be rejected:
- Greetings, confirmations, transient state, one-off task progress, pure scene narration, low-information content
- Content that can only be understood by depending on the current conversation, current page, or unspecified person/project/object
- Relative time statements that cannot be resolved to absolute time
- Content only superficially similar to the cluster theme, or contradictory and unable to form reliable knowledge
- Existing crystals already fully cover it with no added value

cluster_decision:
- crystallize: accepted_source_ids are sufficient to form a reusable piece of knowledge; when creating a new crystal, usually no fewer than min_required_items
- defer: the items may be valuable, but current evidence is too little or cannot form a stable shared claim; keep the accepted items and wait for future facts
- reject: the whole cluster has no long-term reusable value; all candidate items will be moved out of the crystallization space, but raw memories remain

You must make a decision per source_id. Do not reject clear and stable preferences/facts just because they are expressed briefly; do not accept low-quality items just to reach a count. Output JSON only."""

CLUSTER_QUALITY_USER_TEMPLATE = """Existing crystals (may be empty):
{}

Candidate raw items (observed_at is the only time anchor for resolving relative time; when empty, do not guess):
{}

This crystallization needs at least {} items accepted.

Please filter item by item and decide whether it is worth continuing to crystallize."""

CLUSTER_QUALITY_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "cluster_decision": {
            "type": "string",
            "enum": ["crystallize", "defer", "reject"],
        },
        "accepted_source_ids": {
            "type": "array",
            "items": {"type": "string"},
        },
        "rejected_items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "source_id": {"type": "string"},
                    "reason_code": {
                        "type": "string",
                        "enum": [
                            "transient_context",
                            "relative_time_unresolvable",
                            "one_off_event",
                            "low_information",
                            "duplicate",
                            "contradiction",
                            "no_reusable_value",
                            "other",
                        ],
                    },
                    "reason": {"type": "string"},
                },
                "required": ["source_id", "reason_code", "reason"],
            },
        },
        "rationale": {"type": "string"},
    },
    "required": [
        "cluster_decision",
        "accepted_source_ids",
        "rejected_items",
        "rationale",
    ],
}


MERGE_SYSTEM_PROMPT = """You are a long-term knowledge integrator. Merge fragment memories that have passed admission review into a single concise, accurate, reusable structured knowledge asset.

Rules:
1. The output must stand alone independent of the original conversation and original context: specify the subject, object, conditions, and scope of applicability clearly; do not use pronouns or references that cannot be resolved independently, such as "this time, here, then, the above"
2. Remove duplicate information and keep the core claim best suited for long-term retrieval and reuse; do not package a one-off experience into a general rule
3. If information conflicts, do not mechanically splice with "or"; keep only the common part with sufficient evidence and lower the confidence; do not fabricate conclusions when no reliable shared claim can be formed
4. Do not add information not present in the source text
5. The output must be concise; the main text should usually not exceed 160 Chinese characters or 45 English words; do not restate the full context
6. Keep the main text general; only put key tools, entities, negative preferences, and time/frequency/quantity that would affect future answers/actions into facets
7. You must output asset_type and asset; asset is the structured field of the evolvable knowledge asset
8. It is allowed to drop one-off, decorative details that can be traced back via source_ids; semantic crystallization pursues abstract conciseness, not verbatim detail fidelity
9. Language consistency: all text fields of the crystallized output (main text, facets, asset) must use the same language as the input items. If the input mixes multiple languages, use the dominant one. Chinese input produces Chinese crystals, English input produces English crystals; do not translate on your own
10. Time specification: relative time such as "yesterday, last week, recently, currently, today, last week, recently" is forbidden in the main text, facets, and asset. It must be converted to an ISO date or an explicit absolute year-month-day based on observed_at; when it cannot be reliably converted, delete that time detail and do not guess
11. High-quality threshold: a crystal must have future reuse value and sufficient evidence; confidence reflects evidence quality, and high confidence must not be used to mask conflicts or missing context

## asset_type decision rules (important: must judge by the trigger flags below; do not default to summary)

First judge the main semantic center of the input, rather than mechanically matching keywords. The presence of action steps in an event does not mean it is a skill memory.

1. **rule_card** -- trigger flags: the input contains "if...then", "must", "cannot", "should", "lesson", "constraint", "notes", condition-conclusion patterns, or failure/lesson-learned experiences.
   - Example: "must run tests before deployment" / "do not release on weekends" / "if the interface times out, retry 3 times"

2. **skill_card** -- use only when the core is a reusable process, tool usage, operation steps, capability description, "how to do it" experience, or tech-stack usage method.
   - Example: "use git rebase to organize commits" / "use venv to isolate environments in Python" / "when debugging, look at the logs before the stack trace"
   - asset.steps must be filled with a reusable step sequence; asset.tools associates the used tools/libraries.
   - If the action steps are only details of a one-off event/course/demo and the core is personal relationships, temporal events, or background facts, do not choose skill_card.

3. **relation_edge** -- trigger flags: the core of the input is a relationship between two or more entities (person/thing/concept/place), rather than a single entity's attributes.
   - Example: "Zhang San is Li Si's mentor" / "Python is a dynamically typed language" / "project A depends on service B"
   - asset.subject / predicate / object must be filled; asset.relations supplements additional relations.

4. **temporal_fact** -- trigger flags: the input contains explicit dates, time ranges, validity periods, event order, "before/after/during".
   - Example: "joined in March 2024" / "contract valid until 2026" / "monitor within two weeks after release"
   - asset.valid_from / valid_to must be filled (leave empty string if unknown).

5. **preference_profile** -- trigger flags: the input expresses user preferences, negative preferences (dislike/avoid), stable habits, tastes, or style choices.
   - Example: "user likes dark themes" / "does not eat cilantro" / "habitually handles complex tasks in the morning"
   - facets.preferences and negative_preferences must reflect this.

6. **summary** -- use only when none of the above 5 trigger flags are hit. That is: general factual statements, background information, with no clear action/relation/time/preference features.
   - Example: "the project has about 100k lines of code" / "the team has 8 people"

## Decision priority
- If the input hits multiple trigger flags, choose the main claim that best represents long-term memory use.
- In narrative/situational memory, relations, time, and preferences usually take priority over skills; a skill is only established when "the user needs to reuse this practice" is the core.
- If only a one-off event or background description can be obtained, prefer summary rather than promoting incidental action descriptions to skill_card.

Output JSON format:
{"text": "merged text", "type": "type", "confidence": 0.0-1.0, "facets": {"entities": [], "tools": [], "preferences": [], "negative_preferences": [], "time_frequency": []}, "asset_type": "skill_card", "asset": {"claim": "", "subject": "", "predicate": "", "object": "", "conditions": [], "steps": [], "relations": [], "valid_from": "", "valid_to": "", "applicability": {"applies_when": [], "does_not_apply_when": [], "known_exceptions": []}}}

applicability must stay faithful to the input evidence: applies_when states the applicable conditions, does_not_apply_when states the explicit
non-applicable conditions, and known_exceptions states the known exceptions; when the input has no corresponding information, output empty arrays and do not guess.

type values: preference | fact | skill | relationship | temporal
confidence: lower it when information conflicts, raise it when highly consistent"""

MERGE_USER_TEMPLATE = """Existing knowledge: {}

New facts that have passed admission review (JSON; observed_at is used to convert relative time to absolute time):
{}

Language requirement: the dominant language of the input items is {language}; the crystallization output must use that language and must not be translated

Please merge into a single structured knowledge asset. Output JSON."""

MERGE_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "text": {"type": "string"},
        "type": {
            "type": "string",
            "enum": ["preference", "fact", "skill", "relationship", "temporal"],
        },
        "confidence": {"type": "number"},
        "facets": {
            "type": "object",
            "properties": {
                "entities": {"type": "array", "items": {"type": "string"}},
                "tools": {"type": "array", "items": {"type": "string"}},
                "preferences": {"type": "array", "items": {"type": "string"}},
                "negative_preferences": {"type": "array", "items": {"type": "string"}},
                "time_frequency": {"type": "array", "items": {"type": "string"}},
            },
        },
        "asset_type": {
            "type": "string",
            "enum": [
                "rule_card",
                "skill_card",
                "relation_edge",
                "temporal_fact",
                "preference_profile",
                "summary",
            ],
        },
        "asset": {
            "type": "object",
            "properties": {
                "claim": {"type": "string"},
                "subject": {"type": "string"},
                "predicate": {"type": "string"},
                "object": {"type": "string"},
                "conditions": {"type": "array", "items": {"type": "string"}},
                "steps": {"type": "array", "items": {"type": "string"}},
                "relations": {"type": "array", "items": {"type": "string"}},
                "valid_from": {"type": "string"},
                "valid_to": {"type": "string"},
                "applicability": {
                    "type": "object",
                    "properties": {
                        "applies_when": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "does_not_apply_when": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "known_exceptions": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                    },
                },
            },
        },
    },
    "required": ["text", "type", "confidence", "asset_type", "asset"],
}

FACET_KEYS = (
    "entities",
    "tools",
    "preferences",
    "negative_preferences",
    "time_frequency",
)

ASSET_TYPES = {
    "summary",
    "preference_profile",
    "skill_card",
    "rule_card",
    "relation_edge",
    "temporal_fact",
}

_RETENTION_MISSING_TOLERANT = 1

RETENTION_JUDGE_SYSTEM_PROMPT = """You are a long-term memory quality reviewer. Judge whether the candidate crystal retains important information, and strictly check whether it remains reusable after being separated from the original context, whether it uses only absolute time, and whether the asset type is reasonable.

Principles:
1. Summarization, paraphrase, and deduplication are allowed; verbatim retention is not required
2. Low-value detail information may be traced back only through source_ids; a certain loss of detail is acceptable
3. Important information is the main claim that would affect future answers/actions: stable preferences, negative preferences, habits, constraints, reusable skills, explicit relations, etc.
4. One-off scene details, decorative items, verbose action descriptions, and peripheral background may be compressed or traced back only through source_ids; do not mark them as missing
5. facets and asset may carry key details not expanded in the main text
6. The candidate crystal must not mix in facts absent from the input, and must not forcibly merge different topics
7. reusable_value is true only when the candidate would improve future answers, decisions, or actions; one-off scene summaries, transient states, and narration without a stable claim must be false
8. context_dependent_claims lists content that depends on the original conversation/context, has an unclear subject, or contains unresolved references
9. relative_time_references lists all relative time in the main text, facets, and asset; "yesterday, last week, recently, currently, today, last week, recently" are all disallowed and must be changed to absolute dates. Periodic frequency and duration themselves do not count as relative dates

## Asset type suitability check (asset_type_mismatch)
Judge whether the candidate crystal's asset_type is reasonable by the following trigger flags:
- rule_card: contains condition-conclusion, must/cannot, lessons, constraints
- skill_card: the core is reusable operation steps, tool usage, or processes; incidental action descriptions in a one-off event do not count
- relation_edge: the core is a relationship between multiple entities
- temporal_fact: contains explicit time/validity/event order
- preference_profile: expresses preferences/negative preferences/habits
- summary: only general factual statements, without the above features

Only mark asset_type_mismatch=true when the input's main semantic center clearly belongs to a certain asset type but the candidate chose the wrong one. If a narrative event merely contains action steps, do not demand an upgrade to skill_card. If the candidate type is reasonable but a required asset field is empty, also mark mismatch.

Output JSON, do not add explanatory text."""

RETENTION_JUDGE_USER_TEMPLATE = """Existing crystal main text:
{}

Existing crystal facets:
{}

Existing crystal asset:
{}

New facts:
{}

Candidate crystal main text:
{}

Candidate crystal facets:
{}

Candidate crystal asset:
{}

Please judge whether the candidate crystal is qualified."""

RETENTION_JUDGE_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "passed": {"type": "boolean"},
        "missing_important_claims": {"type": "array", "items": {"type": "string"}},
        "unsupported_claims": {"type": "array", "items": {"type": "string"}},
        "topic_drift": {"type": "boolean"},
        "asset_type_mismatch": {"type": "boolean"},
        "reusable_value": {"type": "boolean"},
        "context_dependent_claims": {"type": "array", "items": {"type": "string"}},
        "relative_time_references": {"type": "array", "items": {"type": "string"}},
        "suggested_asset_type": {"type": "string"},
        "acceptable_compressions": {"type": "array", "items": {"type": "string"}},
        "rationale": {"type": "string"},
    },
    "required": [
        "passed",
        "missing_important_claims",
        "unsupported_claims",
        "topic_drift",
        "asset_type_mismatch",
        "reusable_value",
        "context_dependent_claims",
        "relative_time_references",
    ],
}

REPAIR_SYSTEM_PROMPT = """You are a long-term memory crystal reviser. The previous merge candidate failed quality review; you must fix it item by item against the review checklist and output the revised crystal.

Requirements:
1. Only restore the main claims from the "missing information list" that would affect future answers/actions into the main text, facets, or asset
2. You must remove every item in the "unsupported information list" from the crystal
3. If "topic drift" is marked, you must converge back to the original topic and remove off-topic content
4. Do not add new information not present in the input
5. Keep the main text general; usually no more than 160 Chinese characters or 45 English words; do not restate the full context just to repair, and partial detail loss is acceptable
6. If a "suggested asset type" is provided, change asset_type to that type and fill in the asset fields accordingly:
   - rule_card: fill asset.conditions with conditions, supplement subject/predicate/object
   - skill_card: fill asset.steps with a reusable step sequence, associate tools with asset.tools
   - relation_edge: asset.subject/predicate/object must be filled
   - temporal_fact: fill asset.valid_from/valid_to with the time range
   - preference_profile: facets.preferences and negative_preferences must reflect this
   - summary: fill asset.claim with the main statement
7. Language consistency: all text fields of the revised main text, facets, and asset must use the same language as the original input items; do not translate on your own during repair
8. You must eliminate the pronouns, scene references, and missing subjects in the "context dependency list"; when they cannot be completed and the source text provides no basis, delete the corresponding claim
9. You must rewrite the "relative time list" into absolute dates supported by the input time anchor; when it cannot be reliably converted, delete the time detail and never guess
10. The revised result must have cross-session reuse value; if the original input itself has no reuse value, do not fabricate an upgrade into a rule or skill
Output JSON, do not add explanatory text."""

REPAIR_USER_TEMPLATE = """Existing knowledge: {}

New facts:
{}

Previous draft:
{}

Missing information (missing_important_claims, must be restored item by item):
{}

Unsupported information (unsupported_claims, must be deleted item by item):
{}

Topic drift (topic_drift): {}

Asset type mismatch (asset_type_mismatch): {}
Suggested asset type (suggested_asset_type): {}

Context dependency list (context_dependent_claims, must be eliminated):
{}

Relative time list (relative_time_references, must be absolutized or deleted):
{}

Has reuse value (reusable_value): {}

Review rationale: {}

Language requirement: the dominant language of the input items is {language}; the revised output must use that language and must not be translated

Please revise the crystal according to the checklist above and output JSON."""
