"""账本核心不变式测试。

覆盖：append-only、幂等、head 指针、血缘、边派生、并发写、时间旅行、三级回滚。
全部使用临时 SQLite 文件，无外部依赖，可离线运行。

用法：
    python clawcodex_ext.latent_memory.server/lib/solidification/tests/test_ledger.py
    python -m unittest clawcodex_ext.latent_memory.server.lib.solidification.tests.test_ledger
"""

from __future__ import annotations

import shutil
import tempfile
import threading
import unittest
from pathlib import Path

from clawcodex_ext.latent_memory.server.lib.solidification.hashing import content_hash
from clawcodex_ext.latent_memory.server.lib.solidification import ledger as ledger_module
from clawcodex_ext.latent_memory.server.lib.solidification.ledger import CrystalLedger, LedgerError
from clawcodex_ext.latent_memory.server.lib.solidification.models import (
    RevisionInput,
    derive_edges,
    new_batch_id,
    new_crystal_id,
)


def make_entry(
    crystal_id: str,
    *,
    batch_id: str,
    body: str = "用户偏好 pytest fixture 作用域显式声明",
    op: str = "create",
    status: str = "active",
    asset: dict | None = None,
    facets: dict | None = None,
    source_ids: list[str] | None = None,
    **kwargs,
) -> RevisionInput:
    return RevisionInput(
        crystal_id=crystal_id,
        batch_id=batch_id,
        op=op,
        status=status,
        body=body,
        asset=asset
        if asset is not None
        else {
            "claim": body,
            "subject": "pytest-fixtures",
            "predicate": "preference",
            "object": "显式声明作用域",
            "conditions": [],
            "steps": [],
            "relations": [],
            "valid_from": "",
            "valid_to": "",
        },
        facets=facets if facets is not None else {"tools": ["pytest"]},
        knowledge_type="preference",
        asset_type="preference_profile",
        subject="pytest-fixtures",
        confidence=0.81,
        source_ids=source_ids if source_ids is not None else ["raw-1", "raw-2"],
        scope={"user_id": "alice"},
        **kwargs,
    )


class LedgerTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp(prefix="solidify-test-")
        self.db_path = str(Path(self.tmpdir) / "ledger.db")
        self.ledger = CrystalLedger(self.db_path)
        self.batch = new_batch_id()

    def tearDown(self) -> None:
        self.ledger.close()
        shutil.rmtree(self.tmpdir, ignore_errors=True)


class SchemaTest(LedgerTestCase):
    def test_migrate_is_idempotent(self) -> None:
        first = self.ledger.stats()["schema_version"]
        reopened = CrystalLedger(self.db_path)
        try:
            self.assertEqual(reopened.stats()["schema_version"], first)
        finally:
            reopened.close()

    def test_projection_watermarks_initialized(self) -> None:
        state = self.ledger.projection_state()
        self.assertEqual(set(state), {"vector", "graph", "document"})
        for projection in state.values():
            self.assertEqual(projection["through_rev"], 0)


class AppendTest(LedgerTestCase):
    def test_genesis_revision(self) -> None:
        crystal_id = new_crystal_id()
        result = self.ledger.append_revision(make_entry(crystal_id, batch_id=self.batch))

        self.assertFalse(result.skipped)
        revision = result.revision
        self.assertIsNotNone(revision)
        self.assertEqual(revision.version, 1)
        self.assertIsNone(revision.parent_rev)
        self.assertEqual(revision.op, "create")
        self.assertEqual(revision.crystal_id, crystal_id)
        self.assertEqual(revision.scope, {"user_id": "alice"})
        self.assertEqual(revision.source_ids, ["raw-1", "raw-2"])

        head = self.ledger.head(crystal_id)
        self.assertEqual(head.rev_id, revision.rev_id)

    def test_second_revision_chains_parent_and_version(self) -> None:
        crystal_id = new_crystal_id()
        first = self.ledger.append_revision(make_entry(crystal_id, batch_id=self.batch))
        second = self.ledger.append_revision(
            make_entry(
                crystal_id,
                batch_id=self.batch,
                op="absorb",
                body="用户偏好 pytest fixture 作用域显式声明，且倾向 module 级",
            )
        )

        self.assertEqual(second.revision.version, 2)
        self.assertEqual(second.revision.parent_rev, first.rev_id)
        self.assertEqual(self.ledger.head(crystal_id).rev_id, second.rev_id)

    def test_history_preserves_every_body(self) -> None:
        """append-only 的全部意义：v1 的正文在 v3 之后仍然存在。"""
        crystal_id = new_crystal_id()
        bodies = ["版本一正文", "版本二正文", "版本三正文"]
        for index, body in enumerate(bodies):
            self.ledger.append_revision(
                make_entry(
                    crystal_id,
                    batch_id=self.batch,
                    body=body,
                    op="create" if index == 0 else "absorb",
                )
            )

        history = self.ledger.history(crystal_id)
        self.assertEqual([rev.body for rev in history], bodies)
        self.assertEqual([rev.version for rev in history], [1, 2, 3])

    def test_idempotent_when_content_hash_unchanged(self) -> None:
        crystal_id = new_crystal_id()
        first = self.ledger.append_revision(make_entry(crystal_id, batch_id=self.batch))
        repeat = self.ledger.append_revision(
            make_entry(crystal_id, batch_id=new_batch_id(), op="absorb")
        )

        self.assertTrue(repeat.skipped)
        self.assertEqual(repeat.reason, "content_hash_unchanged")
        self.assertEqual(repeat.rev_id, first.rev_id)
        self.assertEqual(len(self.ledger.history(crystal_id)), 1)

    def test_source_ids_only_change_appends_without_changing_hash(self) -> None:
        """新增来源必须留痕；hash 不变供投影复用 embedding。"""
        crystal_id = new_crystal_id()
        first = self.ledger.append_revision(make_entry(crystal_id, batch_id=self.batch))
        repeat = self.ledger.append_revision(
            make_entry(
                crystal_id,
                batch_id=self.batch,
                op="absorb",
                source_ids=["raw-1", "raw-2", "raw-3", "raw-4"],
            )
        )
        self.assertFalse(repeat.skipped)
        self.assertEqual(repeat.revision.content_hash, first.revision.content_hash)
        self.assertEqual(len(self.ledger.history(crystal_id)), 2)
        self.assertEqual(repeat.revision.source_ids, ["raw-1", "raw-2", "raw-3", "raw-4"])

    def test_status_transition_is_never_skipped(self) -> None:
        """正文未变但状态迁移必须留痕，否则"这条被撤回了"就丢了。"""
        crystal_id = new_crystal_id()
        self.ledger.append_revision(make_entry(crystal_id, batch_id=self.batch))
        result = self.ledger.mark_status(
            crystal_id,
            status="superseded",
            op="supersede",
            batch_id=self.batch,
            rationale="absorbed into target",
        )

        self.assertFalse(result.skipped)
        self.assertEqual(result.revision.status, "superseded")
        self.assertEqual(result.revision.version, 2)
        self.assertEqual(result.revision.body, "用户偏好 pytest fixture 作用域显式声明")

    def test_no_update_or_delete_on_revision_table(self) -> None:
        """静态不变式：ledger.py 不含针对 crystal_revision 的 UPDATE / DELETE。

        reset() 是唯一例外（工厂重置），故排除该方法体。
        """
        source = Path(ledger_module.__file__).resolve()
        text = source.read_text(encoding="utf-8")
        body = text.split("def reset(")[0]
        lowered = body.lower()
        self.assertNotIn("update crystal_revision", lowered)
        self.assertNotIn("delete from crystal_revision", lowered)

    def test_rejects_invalid_input(self) -> None:
        crystal_id = new_crystal_id()
        with self.assertRaises(ValueError):
            self.ledger.append_revision(make_entry(crystal_id, batch_id=self.batch, op="bogus_op"))
        with self.assertRaises(ValueError):
            self.ledger.append_revision(make_entry(crystal_id, batch_id=self.batch, body="   "))
        with self.assertRaises(ValueError):
            self.ledger.append_revision(
                make_entry(crystal_id, batch_id=self.batch, status="unknown_status")
            )

    def test_mark_status_on_unknown_crystal_raises(self) -> None:
        with self.assertRaises(LedgerError):
            self.ledger.mark_status(
                "cr_missing", status="superseded", op="supersede", batch_id=self.batch
            )


class LineageAndEdgeTest(LedgerTestCase):
    def test_lineage_written_in_same_transaction(self) -> None:
        target = new_crystal_id()
        obsolete = new_crystal_id()
        self.ledger.append_revision(make_entry(target, batch_id=self.batch))
        self.ledger.append_revision(make_entry(obsolete, batch_id=self.batch, body="旧结晶正文"))

        result = self.ledger.mark_status(
            obsolete,
            status="superseded",
            op="supersede",
            batch_id=self.batch,
            lineage=[(obsolete, target, "absorbed_into")],
        )

        links = self.ledger.lineage_for_crystal(obsolete)
        self.assertEqual(len(links), 1)
        self.assertEqual(links[0].from_crystal_id, obsolete)
        self.assertEqual(links[0].to_crystal_id, target)
        self.assertEqual(links[0].relation, "absorbed_into")
        self.assertEqual(links[0].rev_id, result.rev_id)

    def test_obsolete_crystal_body_survives_supersede(self) -> None:
        """当前实现硬删除后 B 彻底消失；账本里 B 的正文和去向都还在。"""
        obsolete = new_crystal_id()
        target = new_crystal_id()
        self.ledger.append_revision(make_entry(target, batch_id=self.batch))
        self.ledger.append_revision(make_entry(obsolete, batch_id=self.batch, body="B 的原始正文"))
        self.ledger.mark_status(
            obsolete,
            status="superseded",
            op="supersede",
            batch_id=self.batch,
            lineage=[(obsolete, target, "absorbed_into")],
        )

        history = self.ledger.history(obsolete)
        self.assertEqual(history[0].body, "B 的原始正文")
        self.assertEqual(history[-1].status, "superseded")
        self.assertEqual(
            [link.to_crystal_id for link in self.ledger.lineage_for_crystal(obsolete)],
            [target],
        )

    def test_rejects_unknown_relation(self) -> None:
        crystal_id = new_crystal_id()
        self.ledger.append_revision(make_entry(crystal_id, batch_id=self.batch))
        with self.assertRaises(ValueError):
            self.ledger.mark_status(
                crystal_id,
                status="superseded",
                op="supersede",
                batch_id=self.batch,
                lineage=[(crystal_id, "cr_other", "not_a_relation")],
            )

    def test_edges_derived_from_asset(self) -> None:
        crystal_id = new_crystal_id()
        result = self.ledger.append_revision(make_entry(crystal_id, batch_id=self.batch))
        edges = self.ledger.edges_for_revision(result.rev_id)
        self.assertEqual(len(edges), 1)
        self.assertEqual(edges[0].subject, "pytest-fixtures")
        self.assertEqual(edges[0].predicate, "preference")
        self.assertEqual(edges[0].object, "显式声明作用域")
        self.assertEqual(edges[0].status, "active")

    def test_incomplete_asset_yields_no_edge(self) -> None:
        """宁缺勿造：object 缺失时不派生半条边。"""
        crystal_id = new_crystal_id()
        result = self.ledger.append_revision(
            make_entry(
                crystal_id,
                batch_id=self.batch,
                asset={"claim": "x", "subject": "alice", "predicate": "likes", "object": ""},
            )
        )
        self.assertEqual(self.ledger.edges_for_revision(result.rev_id), [])

    def test_derive_edges_parses_structured_relations(self) -> None:
        edges = derive_edges(
            {
                "subject": "alice",
                "predicate": "works_at",
                "object": "acme",
                "relations": ["alice|mentors|bob", "reports_to -> carol", "自由文本无法解析"],
            }
        )
        self.assertIn(("alice", "works_at", "acme"), edges)
        self.assertIn(("alice", "mentors", "bob"), edges)
        self.assertIn(("alice", "reports_to", "carol"), edges)
        self.assertEqual(len(edges), 3)


class HeadIntegrityTest(LedgerTestCase):
    def test_verify_heads_consistent_after_writes(self) -> None:
        for _ in range(3):
            self.ledger.append_revision(
                make_entry(new_crystal_id(), batch_id=self.batch, body=f"正文{_}")
            )
        check = self.ledger.verify_heads()
        self.assertTrue(check["consistent"])
        self.assertEqual(check["crystals"], 3)
        self.assertEqual(check["heads"], 3)

    def test_rebuild_heads_repairs_corruption(self) -> None:
        crystal_id = new_crystal_id()
        self.ledger.append_revision(make_entry(crystal_id, batch_id=self.batch))
        self.ledger.append_revision(
            make_entry(crystal_id, batch_id=self.batch, op="absorb", body="第二版正文")
        )
        latest = self.ledger.head(crystal_id).rev_id

        # 模拟 head 损坏：直接把指针写坏
        conn = self.ledger._conn()
        conn.execute("DELETE FROM crystal_head WHERE crystal_id = ?", (crystal_id,))
        self.assertIsNone(self.ledger.head(crystal_id))
        self.assertFalse(self.ledger.verify_heads()["consistent"])

        report = self.ledger.rebuild_heads()
        self.assertEqual(report["repaired"], 1)
        self.assertEqual(self.ledger.head(crystal_id).rev_id, latest)
        self.assertTrue(self.ledger.verify_heads()["consistent"])


class ConcurrencyTest(LedgerTestCase):
    def test_parallel_appends_all_land(self) -> None:
        """WAL + 进程内写锁：并发写不丢、不串号。"""
        crystal_ids = [new_crystal_id() for _ in range(12)]
        errors: list[Exception] = []

        def worker(crystal_id: str) -> None:
            try:
                self.ledger.append_revision(
                    make_entry(crystal_id, batch_id=self.batch, body=f"正文-{crystal_id[:8]}")
                )
            except Exception as exc:  # pragma: no cover - 失败时给出诊断
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(cid,)) for cid in crystal_ids]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(errors, [])
        self.assertEqual(self.ledger.stats()["revisions"], len(crystal_ids))
        self.assertTrue(self.ledger.verify_heads()["consistent"])
        rev_ids = {self.ledger.head(cid).rev_id for cid in crystal_ids}
        self.assertEqual(len(rev_ids), len(crystal_ids))

    def test_parallel_appends_same_crystal_serialize(self) -> None:
        crystal_id = new_crystal_id()
        self.ledger.append_revision(make_entry(crystal_id, batch_id=self.batch))
        errors: list[Exception] = []

        def worker(index: int) -> None:
            try:
                self.ledger.append_revision(
                    make_entry(
                        crystal_id,
                        batch_id=self.batch,
                        op="absorb",
                        body=f"并发正文 {index}",
                    )
                )
            except Exception as exc:  # pragma: no cover
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(errors, [])
        history = self.ledger.history(crystal_id)
        versions = [rev.version for rev in history]
        self.assertEqual(versions, list(range(1, len(history) + 1)))
        self.assertEqual(self.ledger.head(crystal_id).rev_id, history[-1].rev_id)


class HashingTest(unittest.TestCase):
    def test_hash_stable_across_key_order(self) -> None:
        a = content_hash("正文", {"subject": "s", "predicate": "p"}, {"tools": ["x", "y"]})
        b = content_hash("正文", {"predicate": "p", "subject": "s"}, {"tools": ["y", "x"]})
        self.assertEqual(a, b)

    def test_hash_ignores_step_reordering_only_for_unordered_fields(self) -> None:
        base = {"steps": ["先 a", "再 b"], "conditions": ["c1", "c2"]}
        reordered_steps = {"steps": ["再 b", "先 a"], "conditions": ["c1", "c2"]}
        reordered_conditions = {"steps": ["先 a", "再 b"], "conditions": ["c2", "c1"]}
        self.assertNotEqual(content_hash("t", base, {}), content_hash("t", reordered_steps, {}))
        self.assertEqual(content_hash("t", base, {}), content_hash("t", reordered_conditions, {}))

    def test_body_change_changes_hash(self) -> None:
        self.assertNotEqual(content_hash("a", {}, {}), content_hash("b", {}, {}))

    def test_whitespace_normalized(self) -> None:
        self.assertEqual(content_hash("  正文  ", {}, {}), content_hash("正文", {}, {}))


if __name__ == "__main__":
    unittest.main(verbosity=2)
