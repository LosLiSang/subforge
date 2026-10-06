import pytest

from subforge.library import LibraryStore
from subforge.ui.import_tasks import INTERRUPTED_MESSAGE, ImportTaskRegistry, recover_interrupted


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        ({"status": "running", "message": "下载中"},
         {"status": "error", "stage": "failed", "message": INTERRUPTED_MESSAGE}),
        ({"status": "done", "message": "导入完成"}, {"status": "done", "message": "导入完成"}),
        ({"status": "cancelled"}, {"status": "cancelled"}),
        ({"status": "done", "auto_process_status": "pending"},
         {"status": "done", "auto_process_status": "skipped"}),
        ({"status": "done", "auto_process_status": "queued"},
         {"status": "done", "auto_process_status": "queued"}),
    ],
)
def test_recover_interrupted(data, expected):
    result = recover_interrupted(data)
    for key, value in expected.items():
        assert result[key] == value


def test_registry_persists_updates_and_recovers_after_restart(tmp_path):
    store = LibraryStore.initialize(tmp_path / "Library")
    registry = ImportTaskRegistry(lambda: store)
    registry["a"] = {"task_id": "a", "kind": "download", "status": "running", "source_url": "https://x/a"}
    registry["b"] = {"task_id": "b", "kind": "download", "status": "running", "source_url": "https://x/b"}
    registry["b"].update(status="done", message="导入完成", item_id="item-1")
    store.close()

    reopened = LibraryStore.open(tmp_path / "Library")
    restarted = ImportTaskRegistry(lambda: reopened)
    assert restarted.keys() == ["a", "b"]
    assert restarted["b"]["status"] == "done"
    assert restarted["b"]["item_id"] == "item-1"
    assert restarted["a"]["status"] == "error"
    assert restarted["a"]["message"] == INTERRUPTED_MESSAGE
    # 恢复后的状态也已写回数据库
    assert reopened.get_import_task("a")["status"] == "error"
    reopened.close()


def test_registry_without_library_keeps_tasks_in_memory():
    registry = ImportTaskRegistry(lambda: None)
    registry["m"] = {"task_id": "m", "status": "running"}
    registry["m"]["status"] = "done"
    assert registry.get("m")["status"] == "done"


def _backdate(store, task_id, created_at):
    with store._db_lock, store._db:
        store._db.execute("UPDATE import_tasks SET created_at=? WHERE task_id=?", (created_at, task_id))


def test_prune_import_tasks_by_age_and_count_keeps_running(tmp_path):
    from datetime import UTC, datetime

    store = LibraryStore.initialize(tmp_path / "Library")
    for i, status in enumerate(["done", "running", "done", "error", "done"]):
        store.save_import_task({"task_id": f"t{i}", "status": status})
        _backdate(store, f"t{i}", f"2026-01-0{i + 1}T00:00:00Z")
    _backdate(store, "t0", "2025-01-01T00:00:00Z")  # 超过保留天数
    _backdate(store, "t1", "2025-01-01T00:00:00Z")  # 也过期，但仍在运行

    removed = store.prune_import_tasks(
        max_count=2, max_age_days=30, now=datetime(2026, 1, 10, tzinfo=UTC),
    )

    remaining = {t["task_id"] for t in store.list_import_tasks()}
    assert removed == 2  # t0 过期；t2 超出数量上限
    assert remaining == {"t1", "t3", "t4"}
    store.close()


def test_registry_prunes_on_new_task(tmp_path):
    store = LibraryStore.initialize(tmp_path / "Library")
    registry = ImportTaskRegistry(lambda: store, max_count=2)
    for i in range(3):
        registry[f"t{i}"] = {"task_id": f"t{i}", "status": "done"}

    assert "t0" not in registry
    assert store.get_import_task("t0") is None
    assert registry.keys() == ["t1", "t2"]
    store.close()


def test_registry_reads_limits_from_resolver_and_prune_applies_immediately(tmp_path):
    store = LibraryStore.initialize(tmp_path / "Library")
    limit = {"count": 10}
    registry = ImportTaskRegistry(lambda: store, max_count=lambda: limit["count"])
    for i in range(3):
        registry[f"t{i}"] = {"task_id": f"t{i}", "status": "done"}

    limit["count"] = 1
    registry.prune()

    assert registry.keys() == ["t2"]
    store.close()
