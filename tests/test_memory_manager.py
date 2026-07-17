"""
test_memory_manager.py

اختبارات لكلاس MemoryManager (SQLite) في core/memory.py
تغطي 5 نقاط حرجة غير مُختبرة حاليًا:

1. الإنشاء الأساسي (_init_db: جداول + فهارس + FTS5 + triggers)
2. مسار استرداد التلف (corruption recovery) — الأولوية القصوى
3. add_memory + _prune_if_needed (+ vacuum بعد 1000 حذف)
4. hybrid_search (دمج FTS + الأحدث + مطابقة الملف الحالي)
5. دورة حياة الاتصال (close / __del__ / __enter__ / __exit__)
"""

import json
import sqlite3
import time
import pytest

from core.storage import MemoryManager


# ---------------------------------------------------------------------------
# 1. الإنشاء الأساسي
# ---------------------------------------------------------------------------

class TestInitDB:
    def test_creates_tables_indexes_and_fts(self, tmp_path):
        db_path = tmp_path / "mem.db"
        mgr = MemoryManager(db_path=str(db_path), max_records=1000)

        cur = mgr.conn.cursor()

        # جدول السجلات الأساسي موجود
        cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='memory_logs'"
        )
        assert cur.fetchone() is not None, "جدول memory_logs غير موجود"

        # جدول FTS5 موجود
        cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='memory_search'"
        )
        assert cur.fetchone() is not None, "جدول memory_search (FTS5) غير موجود"

        # الفهارس الأربعة موجودة
        cur.execute("SELECT name FROM sqlite_master WHERE type='index'")
        index_names = {row[0] for row in cur.fetchall()}
        for expected in ("idx_timestamp", "idx_role", "idx_project", "idx_tags"):
            assert expected in index_names, f"الفهرس {expected} مفقود"

        # الـtriggers الثلاثة موجودة (ai/ad/au)
        cur.execute("SELECT name FROM sqlite_master WHERE type='trigger'")
        trigger_names = {row[0] for row in cur.fetchall()}
        for expected in ("memory_logs_ai", "memory_logs_ad", "memory_logs_au"):
            assert expected in trigger_names, f"الـ trigger {expected} مفقود"

        mgr.close()

    def test_wal_and_pragmas_applied(self, tmp_path):
        db_path = tmp_path / "mem.db"
        mgr = MemoryManager(db_path=str(db_path), max_records=1000)
        cur = mgr.conn.cursor()
        cur.execute("PRAGMA journal_mode")
        mode = cur.fetchone()[0]
        assert mode.lower() == "wal", "journal_mode يفترض يكون WAL"
        mgr.close()


# ---------------------------------------------------------------------------
# 2. مسار استرداد التلف — الأولوية القصوى
# ---------------------------------------------------------------------------

class TestCorruptionRecovery:
    def test_recovers_from_corrupt_db_file(self, tmp_path):
        db_path = tmp_path / "mem.db"

        # نكتب بايتات عشوائية غير صالحة كقاعدة بيانات SQLite
        db_path.write_bytes(b"\x00\x01\x02not-a-real-sqlite-db\xff\xfe" * 50)

        # ننشئ ملفات wal/shm مرافقة عمدًا للتأكد من حذفها
        wal_path = tmp_path / "mem.db-wal"
        shm_path = tmp_path / "mem.db-shm"
        wal_path.write_bytes(b"fake-wal-data")
        shm_path.write_bytes(b"fake-shm-data")

        # لا يفترض أن يرمي استثناء غير معالج
        mgr = MemoryManager(db_path=str(db_path), max_records=1000)

        # الملف التالف يفترض أن يُعاد تسميته بلاحقة .db.corrupt
        corrupt_path = db_path.with_suffix(".db.corrupt")
        assert corrupt_path.exists(), "الملف التالف لم يُعاد تسميته إلى .db.corrupt"

        # قاعدة البيانات الجديدة يفترض أن تكون سليمة وقابلة للاستخدام
        row_id = mgr.add_memory(role="user", content="اختبار بعد الاسترداد")
        assert row_id is not None

        # ملفات wal/shm القديمة يفترض أن تُحذف
        assert not wal_path.exists() or wal_path.stat().st_size != len(b"fake-wal-data")
        assert not shm_path.exists() or shm_path.stat().st_size != len(b"fake-shm-data")

        mgr.close()

    def test_corrupt_db_emits_warning(self, tmp_path):
        db_path = tmp_path / "mem2.db"
        db_path.write_bytes(b"garbage" * 100)

        with pytest.warns(UserWarning, match="corruption"):
            mgr = MemoryManager(db_path=str(db_path), max_records=1000)
        mgr.close()


# ---------------------------------------------------------------------------
# 3. add_memory + _prune_if_needed (+ vacuum بعد 1000 حذف)
# ---------------------------------------------------------------------------

class TestPruning:
    def test_add_memory_returns_row_id(self, tmp_path):
        mgr = MemoryManager(db_path=str(tmp_path / "mem.db"), max_records=1000)
        row_id = mgr.add_memory(role="user", content="مرحبا", metadata={"k": "v"})
        assert isinstance(row_id, int)
        mgr.close()

    def test_prune_keeps_only_target_size_when_exceeding_max(self, tmp_path):
        max_records = 20
        mgr = MemoryManager(db_path=str(tmp_path / "mem.db"), max_records=max_records)

        for i in range(max_records + 10):
            mgr.add_memory(role="user", content=f"رسالة {i}")

        cur = mgr.conn.cursor()
        cur.execute("SELECT count(*) FROM memory_logs")
        count = cur.fetchone()[0]

        # المفروض العدد ما يتجاوز max_records، وأقرب لـ 90% منه بعد التقليم
        assert count <= max_records
        mgr.close()

    def test_oldest_records_are_pruned_first(self, tmp_path):
        max_records = 5
        mgr = MemoryManager(db_path=str(tmp_path / "mem.db"), max_records=max_records)

        contents = [f"msg-{i}" for i in range(max_records + 5)]
        for c in contents:
            mgr.add_memory(role="user", content=c)
            time.sleep(0.001)  # نضمن تسلسل زمني مختلف بين السجلات

        remaining = mgr.get_recent_history(limit=100)
        remaining_contents = {r["content"] for r in remaining}

        # أقدم رسالة (msg-0) يفترض تكون محذوفة
        assert "msg-0" not in remaining_contents
        # أحدث رسالة يفترض موجودة
        assert contents[-1] in remaining_contents
        mgr.close()

    def test_vacuum_called_after_thousand_deletions(self, tmp_path, monkeypatch):
        mgr = MemoryManager(db_path=str(tmp_path / "mem.db"), max_records=5)

        vacuum_calls = []
        monkeypatch.setattr(mgr, "vacuum", lambda: vacuum_calls.append(True))

        # إضافة كافية لتوليد أكثر من 1000 عملية حذف تراكمية
        for i in range(1010):
            mgr.add_memory(role="user", content=f"msg-{i}")

        assert len(vacuum_calls) >= 1, "vacuum() لم يُستدعَ بعد تجاوز 1000 حذف تراكمي"
        mgr.close()


# ---------------------------------------------------------------------------
# 4. hybrid_search
# ---------------------------------------------------------------------------

class TestHybridSearch:
    def test_fts_match_returns_relevant_results(self, tmp_path):
        mgr = MemoryManager(db_path=str(tmp_path / "mem.db"), max_records=1000)
        mgr.add_memory(role="user", content="نتحدث عن الذكاء الاصطناعي والوكلاء")
        mgr.add_memory(role="user", content="طبخة اليوم كانت لذيذة جدًا")

        results = mgr.hybrid_search("الذكاء الاصطناعي", limit=5)
        assert len(results) >= 1
        assert any("الذكاء" in r["content"] for r in results)
        mgr.close()

    def test_recent_history_boosts_ranking_even_without_keyword_match(self, tmp_path):
        mgr = MemoryManager(db_path=str(tmp_path / "mem.db"), max_records=1000)
        mgr.add_memory(role="user", content="رسالة قديمة غير ذات صلة")
        time.sleep(0.01)
        mgr.add_memory(role="user", content="رسالة حديثة أيضًا غير ذات صلة")

        results = mgr.hybrid_search("كلمة غير موجودة إطلاقًا", limit=5)
        # حتى بدون تطابق FTS، يفترض ترجع نتائج بناءً على الحداثة
        assert len(results) >= 1
        mgr.close()

    def test_current_file_match_boosts_score(self, tmp_path):
        mgr = MemoryManager(db_path=str(tmp_path / "mem.db"), max_records=1000)
        mgr.add_memory(
            role="assistant",
            content="تم تعديل core/verifier.py لإضافة تحقق جديد",
            metadata={"file": "core/verifier.py"},
        )
        mgr.add_memory(role="assistant", content="رسالة عشوائية أخرى")

        results = mgr.hybrid_search(
            "شيء غير مرتبط", limit=5, current_file="core/verifier.py"
        )
        assert any("verifier.py" in r["content"] for r in results)
        mgr.close()

    def test_sql_injection_safe_in_current_file_param(self, tmp_path):
        mgr = MemoryManager(db_path=str(tmp_path / "mem.db"), max_records=1000)
        mgr.add_memory(role="user", content="محتوى طبيعي")

        malicious_file = "core/%_\\evil'; DROP TABLE memory_logs; --"
        # لا يفترض يرمي استثناء ولا يكسر القاعدة
        results = mgr.hybrid_search("محتوى", limit=5, current_file=malicious_file)
        assert isinstance(results, list)

        cur = mgr.conn.cursor()
        cur.execute("SELECT count(*) FROM memory_logs")
        assert cur.fetchone()[0] >= 1, "جدول memory_logs تأثر أو انحذف — احتمال ثغرة"
        mgr.close()


# ---------------------------------------------------------------------------
# 5. دورة حياة الاتصال
# ---------------------------------------------------------------------------

class TestLifecycle:
    def test_close_sets_conn_to_none(self, tmp_path):
        mgr = MemoryManager(db_path=str(tmp_path / "mem.db"), max_records=1000)
        mgr.close()
        assert mgr.conn is None

    def test_double_close_does_not_raise(self, tmp_path):
        mgr = MemoryManager(db_path=str(tmp_path / "mem.db"), max_records=1000)
        mgr.close()
        mgr.close()  # يفترض ما يرمي استثناء لأن conn أصلاً None

    def test_context_manager_closes_on_exit(self, tmp_path):
        db_path = str(tmp_path / "mem.db")
        with MemoryManager(db_path=db_path, max_records=1000) as mgr:
            mgr.add_memory(role="user", content="داخل context manager")
            assert mgr.conn is not None
        assert mgr.conn is None

    def test_context_manager_closes_even_on_exception(self, tmp_path):
        db_path = str(tmp_path / "mem.db")
        with pytest.raises(ValueError):
            with MemoryManager(db_path=db_path, max_records=1000) as mgr:
                raise ValueError("خطأ متعمد لاختبار __exit__")
        assert mgr.conn is None

    def test_del_closes_connection_without_error(self, tmp_path):
        mgr = MemoryManager(db_path=str(tmp_path / "mem.db"), max_records=1000)
        mgr.__del__()  # استدعاء مباشر بدل انتظار garbage collector
        assert mgr.conn is None


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
