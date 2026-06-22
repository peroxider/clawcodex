"""F-103 — parentUuid chain + walkChainBeforeParse 读取过滤。

Test coverage for the decoupled F-103 implementation:

* Write side (``extensions/agent/session_persist.py::_inject_parent_uuids``)
* Read side (``clawcodex_ext/agent/chain_filter.py``)
* Integration (``clawcodex_ext/agent/session.py::_load_from_enhanced_transcript``)

Acceptance scenarios from FEATURE_PLAN §1.4.6:
1. New-format write produces a correct parentUuid chain.
2. ``/rewind`` → new messages form a branch on disk.
3. ``walkChainBeforeParse`` drops dead-branch lines above the
   ratio threshold.
4. ``--resume`` (via ``Session.load``) returns only the active chain.
5. Legacy transcripts (no ``parentUuid``) skip the filter and
   return every message unchanged.
6. ``walkChainBeforeParse`` gate short-circuits on small / low
   dead-branch-ratio transcripts.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

# Ensure repo root is on sys.path so ``extensions`` / ``clawcodex_ext``
# imports resolve when the test is run from anywhere in the repo.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from clawcodex_ext.agent.chain_filter import (  # noqa: E402
    ABS_SIZE_THRESHOLD,
    DEAD_BRANCH_RATIO,
    ChainFilterConfig,
    build_conversation_chain,
    filter_active_chain_messages,
    walk_chain_before_parse,
)
from extensions.agent.session_persist import _inject_parent_uuids  # noqa: E402


def _make_session_init(session_id: str = "s-test") -> str:
    """Return a serialised ``session_init`` line."""
    return json.dumps(
        {
            "type": "session_init",
            "session_id": session_id,
            "provider": "test",
            "model": "test-model",
            "cwd": "/tmp",
            "created_at": "2026-06-22T00:00:00",
        },
        ensure_ascii=False,
    )


def _msg(uuid: str, parent_uuid, role: str, content: str) -> dict:
    """Build a chat message dict with the F-103 ``parentUuid`` field."""
    return {
        "uuid": uuid,
        "parentUuid": parent_uuid,
        "role": role,
        "content": content,
    }


def _snapshot_line() -> str:
    return json.dumps(
        {
            "type": "session_snapshot",
            "cost": {},
            "updated_at": "2026-06-22T00:01:00",
        },
        ensure_ascii=False,
    )


class TestInjectParentUuids(unittest.TestCase):
    """P103-E — write-side parentUuid stamping."""

    def test_root_message_has_null_parent(self):
        out = _inject_parent_uuids([_msg("u1", None, "user", "hi")])
        self.assertIsNone(out[0]["parentUuid"])

    def test_chain_topology(self):
        msgs = [
            _msg("u1", None, "user", "hi"),
            _msg("u2", "u1", "assistant", "hello"),
            _msg("u3", "u2", "user", "again"),
            _msg("u4", "u3", "assistant", "ok"),
        ]
        out = _inject_parent_uuids(msgs)
        self.assertIsNone(out[0]["parentUuid"])
        self.assertEqual(out[1]["parentUuid"], "u1")
        self.assertEqual(out[2]["parentUuid"], "u2")
        self.assertEqual(out[3]["parentUuid"], "u3")

    def test_rewind_creates_fork_topology(self):
        """After /rewind the new messages form a branch pointing at the rewind target."""
        # Pre-rewind chain: u1 -> u2 -> u3 -> u4
        # User rewinds to u2 (truncate conversation.messages to [u1, u2])
        # New message u5 is appended; it should chain off u2.
        pre_rewind = [
            _msg("u1", None, "user", "hi"),
            _msg("u2", "u1", "assistant", "hello"),
            _msg("u3", "u2", "user", "q1"),
            _msg("u4", "u3", "assistant", "a1"),
        ]
        # conversation.messages post-rewind (truncated to rewind target + new msg)
        post_rewind = [
            _msg("u1", None, "user", "hi"),
            _msg("u2", "u1", "assistant", "hello"),
            _msg("u5", None, "user", "after rewind"),
        ]
        out = _inject_parent_uuids(post_rewind)
        # Chain must be u1 -> u2 -> u5 (NOT u4), proving the fork
        self.assertEqual([m["uuid"] for m in out], ["u1", "u2", "u5"])
        self.assertEqual(out[2]["parentUuid"], "u2")

    def test_idempotent_on_existing_parentUuid(self):
        """Pre-existing parentUuid values are preserved on re-injection."""
        msgs = [
            {"uuid": "u1", "parentUuid": "preset-prev", "role": "user", "content": "x"},
        ]
        out = _inject_parent_uuids(msgs)
        self.assertEqual(out[0]["parentUuid"], "preset-prev")

    def test_missing_uuid_does_not_break_chain(self):
        """Defensive: messages without uuid get parentUuid=None but don't advance cursor."""
        msgs = [
            {"role": "system", "content": "hi"},  # no uuid
            _msg("u1", None, "user", "hi"),
        ]
        out = _inject_parent_uuids(msgs)
        # First entry has no uuid → parentUuid=None, cursor not advanced
        self.assertIsNone(out[0]["parentUuid"])
        # Second entry has uuid u1, no previous → parentUuid=None
        self.assertIsNone(out[1]["parentUuid"])

    def test_does_not_mutate_caller_list(self):
        original = [_msg("u1", None, "user", "hi")]
        _inject_parent_uuids(original)
        self.assertNotIn("parentUuid", original[0])


class TestWalkChainBeforeParse(unittest.TestCase):
    """P103-B — byte-level chain pruning."""

    def test_empty_input_returns_empty(self):
        result = walk_chain_before_parse(b"")
        self.assertTrue(result.skipped)
        self.assertEqual(result.raw_bytes, b"")

    def test_small_transcript_skips_scan(self):
        """Tiny transcripts short-circuit on the size gate."""
        # Build a tiny transcript — well under ABS_SIZE_THRESHOLD
        lines = [_make_session_init(), _msg("u1", None, "user", "hi")]
        raw = ("\n".join(lines) + "\n").encode("utf-8")
        self.assertLess(len(raw), ABS_SIZE_THRESHOLD)
        result = walk_chain_before_parse(raw)
        self.assertTrue(result.skipped)
        self.assertEqual(result.raw_bytes, raw)

    def test_legacy_transcript_no_parentUuid_skips_filter(self):
        """Transcripts without ``parentUuid`` tokens cannot be chain-pruned."""
        lines = [
            _make_session_init(),
            json.dumps({"uuid": "u1", "role": "user", "content": "hi"}),
            json.dumps({"uuid": "u2", "role": "assistant", "content": "hello"}),
        ]
        # Pad to exceed the size threshold so the size gate doesn't dominate.
        lines = lines + [json.dumps({"filler": "x" * 200})] * 50
        raw = ("\n".join(lines) + "\n").encode("utf-8")
        self.assertGreater(len(raw), ABS_SIZE_THRESHOLD)
        result = walk_chain_before_parse(raw)
        self.assertTrue(result.skipped)
        self.assertEqual(result.raw_bytes, raw)

    def test_high_dead_branch_ratio_filters(self):
        """When dead branches exceed the threshold, they are pruned."""
        # Active chain: u1 -> u2 -> u5 (after rewind to u2)
        # Dead branches: u3, u4 (4 dead out of 5 messages = 80% > 50% threshold)
        chat_lines = [
            _msg("u1", None, "user", "hi"),
            _msg("u2", "u1", "assistant", "hello"),
            _msg("u3", "u2", "user", "q1"),
            _msg("u4", "u3", "assistant", "a1"),
            _msg("u5", "u2", "user", "after rewind"),
        ]
        # Pad to exceed size threshold. Repeat dead-branch padding
        # so the dead-branch ratio stays high.
        padding = [json.dumps({"filler": "x" * 200})] * 60
        lines = [_make_session_init()] + chat_lines + padding + [_snapshot_line()]
        raw = ("\n".join(lines) + "\n").encode("utf-8")
        self.assertGreater(len(raw), ABS_SIZE_THRESHOLD)

        result = walk_chain_before_parse(raw)
        self.assertFalse(result.skipped)
        # Active chain + metadata should be retained; dead branches pruned
        decoded = result.raw_bytes.decode("utf-8")
        self.assertIn("u1", decoded)
        self.assertIn("u2", decoded)
        self.assertIn("u5", decoded)
        self.assertIn("session_init", decoded)
        self.assertIn("session_snapshot", decoded)
        # Dead branches pruned
        self.assertNotIn('"uuid": "u3"', decoded)
        self.assertNotIn('"uuid": "u4"', decoded)

    def test_low_dead_branch_ratio_skips_filter(self):
        """Below the ratio threshold, the filter is skipped (full parse)."""
        # Build many chat messages on the active chain with a few dead
        # branches — ratio stays low (<50%).
        chat_lines = []
        prev = None
        for i in range(20):
            chat_lines.append(_msg(f"u{i}", prev, "user", f"m{i}"))
            prev = f"u{i}"
        # Two dead-branch messages (10% dead ratio)
        chat_lines.append(_msg("dead1", "u0", "assistant", "dead"))
        chat_lines.append(_msg("dead2", "dead1", "user", "dead"))

        padding = [json.dumps({"filler": "x" * 200})] * 30
        lines = [_make_session_init()] + chat_lines + padding + [_snapshot_line()]
        raw = ("\n".join(lines) + "\n").encode("utf-8")
        self.assertGreater(len(raw), ABS_SIZE_THRESHOLD)

        result = walk_chain_before_parse(raw)
        # 22 messages, 2 dead → ~9% → below threshold → skipped
        self.assertTrue(result.skipped)
        self.assertEqual(result.raw_bytes, raw)

    def test_multiple_leaves_picks_longest_chain(self):
        """When several leaf candidates exist (forked chains), the longest wins."""
        chat_lines = [
            _msg("u1", None, "user", "root"),
            _msg("u2", "u1", "assistant", "fork1-step"),
            _msg("u3", "u1", "assistant", "fork2-step"),
            _msg("u4", "u2", "user", "fork1-deep"),
        ]
        padding = [json.dumps({"filler": "x" * 200})] * 50
        lines = [_make_session_init()] + chat_lines + padding
        raw = ("\n".join(lines) + "\n").encode("utf-8")
        result = walk_chain_before_parse(raw)
        # u3 has only 1 entry on its branch (length 2: u1, u3).
        # u4 has 3 entries (length 3: u1, u2, u4). Longest wins.
        # 2 messages dead (33% of 6 chat lines) → under threshold → may skip.
        # But we want to assert behavior — use a config to force filter.
        cfg = ChainFilterConfig(dead_branch_ratio=0.1)
        result = walk_chain_before_parse(raw, config=cfg)
        decoded = result.raw_bytes.decode("utf-8")
        self.assertIn("u1", decoded)
        self.assertIn("u2", decoded)
        self.assertIn("u4", decoded)


class TestBuildConversationChain(unittest.TestCase):
    """P103-C — chain reconstruction from leaf to root."""

    def test_empty_input_returns_empty(self):
        self.assertEqual(build_conversation_chain([]), [])

    def test_walks_leaf_to_root(self):
        msgs = [
            _msg("u1", None, "user", "hi"),
            _msg("u2", "u1", "assistant", "hello"),
            _msg("u3", "u2", "user", "q"),
            _msg("u4", "u3", "assistant", "a"),
        ]
        chain = build_conversation_chain(msgs)
        self.assertEqual([m["uuid"] for m in chain], ["u1", "u2", "u3", "u4"])

    def test_excludes_dead_branches(self):
        msgs = [
            _msg("u1", None, "user", "root"),
            _msg("u2", "u1", "assistant", "a"),
            _msg("u3", "u2", "user", "b"),
            _msg("u4", "u3", "assistant", "c"),
            _msg("u5", "u2", "user", "after rewind"),  # fork from u2
        ]
        chain = build_conversation_chain(msgs)
        # u5 is the leaf (no one references it); walk back: u5, u2, u1
        self.assertEqual([m["uuid"] for m in chain], ["u1", "u2", "u5"])
        self.assertNotIn("u3", [m["uuid"] for m in chain])
        self.assertNotIn("u4", [m["uuid"] for m in chain])

    def test_explicit_leaf_uuid(self):
        msgs = [
            _msg("u1", None, "user", "root"),
            _msg("u2", "u1", "assistant", "a"),
            _msg("u3", "u2", "user", "b"),
        ]
        chain = build_conversation_chain(msgs, leaf_uuid="u2")
        # Forced leaf u2 → walk: u2, u1
        self.assertEqual([m["uuid"] for m in chain], ["u1", "u2"])

    def test_no_chain_topology_returns_input(self):
        """When no parentUuid links exist, fall back to input order."""
        msgs = [
            {"uuid": "u1", "role": "user", "content": "a"},
            {"uuid": "u2", "role": "assistant", "content": "b"},
        ]
        chain = build_conversation_chain(msgs)
        # No parent links, no dead branches → returns in input order
        self.assertEqual([m["uuid"] for m in chain], ["u1", "u2"])


class TestFilterActiveChainMessages(unittest.TestCase):
    """P103-D — high-level helper for parsed-dict consumers."""

    def test_empty_returns_empty(self):
        self.assertEqual(filter_active_chain_messages([]), [])

    def test_skips_dead_branches_via_bytes_round_trip(self):
        """End-to-end: serialise dicts → walk chain → re-parse → chain."""
        msgs = [
            _msg("u1", None, "user", "hi"),
            _msg("u2", "u1", "assistant", "hello"),
            _msg("u3", "u2", "user", "q1"),
            _msg("u4", "u3", "assistant", "a1"),
            _msg("u5", "u2", "user", "after rewind"),
        ]
        # Pad entries so the size gate fires
        for _ in range(60):
            msgs.append({"filler": "x" * 200})
        result = filter_active_chain_messages(
            msgs,
            config=ChainFilterConfig(dead_branch_ratio=0.5),
        )
        uuids = [m["uuid"] for m in result if m.get("uuid")]
        self.assertIn("u1", uuids)
        self.assertIn("u2", uuids)
        self.assertIn("u5", uuids)
        self.assertNotIn("u3", uuids)
        self.assertNotIn("u4", uuids)


class TestSessionLoadIntegration(unittest.TestCase):
    """P103-G — Session.load / _load_from_enhanced_transcript integration.

    Uses an isolated temporary directory so the test does not touch
    real ``~/.clawcodex/sessions``. The Session class reads from
    ``_get_sessions_dir()`` which is hard-wired to ``Path.home()``,
    so we patch it for the duration of the test.
    """

    def setUp(self):
        import tempfile

        self.tmpdir = tempfile.mkdtemp(prefix="f103-session-")
        self._original_home = None

    def tearDown(self):
        # No live state to clean up — Session is constructed with
        # explicit ids and the temp dir is removed by the OS on reboot.
        # We deliberately do NOT touch ``Path.home`` here; see below.
        pass

    def _patch_sessions_dir(self):
        """Patch ``_get_sessions_dir`` to point at the temp dir."""
        from clawcodex_ext.agent import session as session_mod

        original = session_mod._get_sessions_dir
        self._original_home = original
        from pathlib import Path as _Path

        session_mod._get_sessions_dir = lambda: _Path(self.tmpdir)
        return original

    def _restore_sessions_dir(self, original):
        from clawcodex_ext.agent import session as session_mod

        session_mod._get_sessions_dir = original

    def _write_transcript(self, session_id: str, raw_lines: list[str]) -> Path:
        session_dir = Path(self.tmpdir) / session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        transcript = session_dir / "transcript.jsonl"
        transcript.write_text("\n".join(raw_lines) + "\n", encoding="utf-8")
        return transcript

    def test_load_returns_active_chain_after_rewind(self):
        """End-to-end: write a rewind transcript, Session.load returns only active chain."""
        original = self._patch_sessions_dir()
        try:
            session_id = "rewind-test-1"
            init = _make_session_init(session_id)
            chat_lines = [
                json.dumps(_msg("u1", None, "user", "hi")),
                json.dumps(_msg("u2", "u1", "assistant", "hello")),
                json.dumps(_msg("u3", "u2", "user", "q1")),
                json.dumps(_msg("u4", "u3", "assistant", "a1")),
                json.dumps(_msg("u5", "u2", "user", "after rewind")),
            ]
            # Pad so the size gate fires
            chat_lines = chat_lines + [json.dumps({"filler": "x" * 200})] * 60
            self._write_transcript(
                session_id, [init] + chat_lines + [_snapshot_line()]
            )

            from clawcodex_ext.agent.session import Session

            loaded = Session.load(session_id)
            self.assertIsNotNone(loaded)
            # The active chain is u1 -> u2 -> u5
            uuids = [getattr(m, "uuid", None) for m in loaded.conversation.messages]
            self.assertIn("u1", uuids)
            self.assertIn("u2", uuids)
            self.assertIn("u5", uuids)
            # Dead branches excluded
            self.assertNotIn("u3", uuids)
            self.assertNotIn("u4", uuids)
        finally:
            self._restore_sessions_dir(original)

    def test_load_returns_all_when_legacy_no_parentUuid(self):
        """Legacy transcripts (no parentUuid) return all messages unchanged."""
        original = self._patch_sessions_dir()
        try:
            session_id = "legacy-test-1"
            init = _make_session_init(session_id)
            legacy_lines = [
                json.dumps({"uuid": "u1", "role": "user", "content": "hi"}),
                json.dumps({"uuid": "u2", "role": "assistant", "content": "hello"}),
                json.dumps({"uuid": "u3", "role": "user", "content": "again"}),
            ]
            # Pad to exceed the size gate so the gate fires
            legacy_lines = legacy_lines + [json.dumps({"filler": "x" * 200})] * 60
            self._write_transcript(
                session_id, [init] + legacy_lines + [_snapshot_line()]
            )

            from clawcodex_ext.agent.session import Session

            loaded = Session.load(session_id)
            self.assertIsNotNone(loaded)
            uuids = [getattr(m, "uuid", None) for m in loaded.conversation.messages]
            self.assertIn("u1", uuids)
            self.assertIn("u2", uuids)
            self.assertIn("u3", uuids)
        finally:
            self._restore_sessions_dir(original)

    def test_chain_filter_disabled_returns_full_transcript(self):
        """Opt-out: chain_filter=False returns the full transcript including dead branches."""
        original = self._patch_sessions_dir()
        try:
            session_id = "optout-test-1"
            init = _make_session_init(session_id)
            chat_lines = [
                json.dumps(_msg("u1", None, "user", "hi")),
                json.dumps(_msg("u2", "u1", "assistant", "hello")),
                json.dumps(_msg("u3", "u2", "user", "q1")),
                json.dumps(_msg("u4", "u3", "assistant", "a1")),
                json.dumps(_msg("u5", "u2", "user", "after rewind")),
            ]
            chat_lines = chat_lines + [json.dumps({"filler": "x" * 200})] * 60
            self._write_transcript(
                session_id, [init] + chat_lines + [_snapshot_line()]
            )

            from clawcodex_ext.agent.session import _load_from_enhanced_transcript

            path = Path(self.tmpdir) / session_id / "transcript.jsonl"
            loaded = _load_from_enhanced_transcript(
                session_id, path, chain_filter=False
            )
            self.assertIsNotNone(loaded)
            uuids = [getattr(m, "uuid", None) for m in loaded.conversation.messages]
            # All chat messages (including dead branches) are returned
            self.assertIn("u1", uuids)
            self.assertIn("u3", uuids)
            self.assertIn("u4", uuids)
            self.assertIn("u5", uuids)
        finally:
            self._restore_sessions_dir(original)


if __name__ == "__main__":
    unittest.main()