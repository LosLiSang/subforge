"""下载/导入任务注册表：内存缓存 + SQLite（Library index.sqlite 的 import_tasks 表）持久化。

调用方仍按 dict 使用（``registry[task_id] = {...}``、``task.update(...)``、
``task["k"] = v``），每次修改都会写回当前活动 Library 的数据库，
因此服务重启后下载任务历史仍然保留。
"""
from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Iterator

from subforge.library import LibraryStore

logger = logging.getLogger(__name__)

INTERRUPTED_MESSAGE = "服务重启，任务已中断"
# 历史保留规则：最多保留最近 N 条，且不超过 N 天（运行中的任务不清理）
DEFAULT_MAX_COUNT = 200
DEFAULT_MAX_AGE_DAYS = 30


class ImportTask(dict):
    """修改即持久化的任务 dict。"""

    def __init__(self, data: dict, on_change: Callable[["ImportTask"], None] | None = None) -> None:
        super().__init__(data)
        self._on_change = on_change

    def _changed(self) -> None:
        if self._on_change is not None:
            self._on_change(self)

    def __setitem__(self, key, value) -> None:
        super().__setitem__(key, value)
        self._changed()

    def __delitem__(self, key) -> None:
        super().__delitem__(key)
        self._changed()

    def update(self, *args, **kwargs) -> None:  # type: ignore[override]
        super().update(*args, **kwargs)
        self._changed()

    def setdefault(self, key, default=None):
        if key in self:
            return self[key]
        self[key] = default
        return default

    def pop(self, key, *default):
        value = super().pop(key, *default)
        self._changed()
        return value


def recover_interrupted(data: dict) -> dict:
    """进程重启后，原先运行中的任务已无后台线程，转为可重试的 error。纯函数。"""
    data = dict(data)
    if data.get("status") == "running":
        data["status"] = "error"
        data["stage"] = "failed"
        data["message"] = INTERRUPTED_MESSAGE
    if data.get("auto_process_status") in {"pending", "scheduling"}:
        # 自动处理的待入队快照只存在于内存，重启后无法恢复
        data["auto_process_status"] = "skipped"
        data["auto_process_message"] = "服务重启，未自动加入字幕处理队列"
    return data


class ImportTaskRegistry:
    """按活动 Library 加载/保存下载导入任务。没有 Library 时仅保存在内存。"""

    def __init__(
        self,
        library_resolver: Callable[[], LibraryStore | None],
        *,
        max_count: int | Callable[[], int] = DEFAULT_MAX_COUNT,
        max_age_days: int | Callable[[], int] = DEFAULT_MAX_AGE_DAYS,
    ) -> None:
        """max_count / max_age_days 可传常量或解析函数（设置页修改后立即生效）。"""
        self._library_resolver = library_resolver
        self._max_count_resolver = max_count if callable(max_count) else (lambda: max_count)
        self._max_age_days_resolver = max_age_days if callable(max_age_days) else (lambda: max_age_days)
        self._lock = threading.RLock()
        self._tasks: dict[str, ImportTask] = {}
        self._loaded_root = None

    @property
    def _max_count(self) -> int:
        return max(1, int(self._max_count_resolver()))

    @property
    def _max_age_days(self) -> int:
        return max(1, int(self._max_age_days_resolver()))

    def _library(self) -> LibraryStore | None:
        try:
            return self._library_resolver()
        except Exception:
            return None

    def _persister(self, library: LibraryStore | None) -> Callable[[ImportTask], None]:
        """任务绑定创建/加载时的 Library，后台线程更新时不再重新解析。"""
        def persist(task: ImportTask) -> None:
            self._persist(library, task)
        return persist

    @staticmethod
    def _persist(library: LibraryStore | None, task: ImportTask) -> None:
        if library is None:
            return
        try:
            library.save_import_task(dict(task))
        except Exception as exc:  # 持久化失败不影响下载本身
            logger.warning("保存下载任务 %s 失败: %s", task.get("task_id"), exc)

    def prune(self) -> None:
        """按当前保留规则立即清理（保存设置后调用）。"""
        self._sync()
        self._prune(self._library())

    def _prune(self, library: LibraryStore | None) -> None:
        """按保留规则清理数据库，并同步移除内存中已被清理的任务。"""
        if library is None:
            return
        try:
            removed = library.prune_import_tasks(
                max_count=self._max_count, max_age_days=self._max_age_days,
            )
            if not removed:
                return
            keep = {str(t["task_id"]) for t in library.list_import_tasks(self._max_count)}
        except Exception as exc:
            logger.warning("清理下载任务历史失败: %s", exc)
            return
        with self._lock:
            for task_id, task in list(self._tasks.items()):
                if task_id not in keep and task.get("status") != "running":
                    del self._tasks[task_id]

    def _sync(self) -> None:
        """活动 Library 变化（含首次访问）时从数据库重新加载。"""
        library = self._library()
        root = library.root if library is not None else None
        with self._lock:
            if root == self._loaded_root:
                return
            # 切换 Library 即换一套任务历史
            self._tasks = {}
            self._loaded_root = root
            if library is None:
                return
            try:
                stored = library.list_import_tasks(self._max_count)
            except Exception as exc:
                logger.warning("加载下载任务历史失败: %s", exc)
                return
            for data in stored:
                recovered = recover_interrupted(data)
                task = ImportTask(recovered, self._persister(library))
                self._tasks[str(recovered["task_id"])] = task
                if recovered != data:
                    self._persist(library, task)
            self._prune(library)

    # ---- dict 风格接口 ----
    def __setitem__(self, task_id: str, data: dict) -> None:
        self._sync()
        library = self._library()
        task = ImportTask({**data, "task_id": data.get("task_id", task_id)}, self._persister(library))
        with self._lock:
            self._tasks[task_id] = task
        self._persist(library, task)
        self._prune(library)

    def __getitem__(self, task_id: str) -> ImportTask:
        self._sync()
        return self._tasks[task_id]

    def __contains__(self, task_id: object) -> bool:
        self._sync()
        return task_id in self._tasks

    def __len__(self) -> int:
        self._sync()
        return len(self._tasks)

    def __iter__(self) -> Iterator[str]:
        self._sync()
        return iter(list(self._tasks))

    def get(self, task_id: str, default=None) -> ImportTask | None:
        self._sync()
        return self._tasks.get(task_id, default)

    def items(self) -> list[tuple[str, ImportTask]]:
        self._sync()
        with self._lock:
            return list(self._tasks.items())

    def values(self) -> list[ImportTask]:
        self._sync()
        with self._lock:
            return list(self._tasks.values())

    def keys(self) -> list[str]:
        self._sync()
        with self._lock:
            return list(self._tasks)
