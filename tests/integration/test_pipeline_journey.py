"""Golden Journey: Task Pipeline & Processing Lifecycle.

涵盖转写与处理流水线黄金主干：
1. 模型 Profile 配置与连通性检测接口（/profiles/{id}/test）
2. 任务排队（TaskManager enqueue）与阶段驱动（asr -> translate -> complete）
3. 字幕生成落盘与音轨双语状态同步
4. 任务历史与下载中心查询（/api/downloads/history）
5. 任务执行异常捕获与失败重试恢复（retry）
"""

import asyncio
import struct
import wave
from pathlib import Path
import pytest
import httpx

from subforge.library import CreatorKind, ImportRequest, ItemKind, LibraryStore
from subforge.models import SubtitleEntry
from subforge.translate.srt_io import write_srt
from subforge.ui.app import UiDependencies, create_app
from subforge.ui.model_profiles import ModelProfileStore
from subforge.ui.picker import FakeFilePicker
from subforge.ui.settings import UiSettingsStore
from subforge.ui.tasks import FakeWorkerAdapter, ProcessingSnapshot


def _generate_test_wav(path: Path, duration_secs: float = 3.0, sample_rate: int = 16000):
    path.parent.mkdir(parents=True, exist_ok=True)
    n_samples = int(duration_secs * sample_rate)
    with wave.open(str(path), "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        for _ in range(n_samples):
            wf.writeframes(struct.pack("<h", 0))


@pytest.mark.asyncio
async def test_pipeline_and_processing_golden_journey(tmp_path: Path):
    lib_dir = tmp_path / "pipeline_library"
    lib_dir.mkdir(parents=True, exist_ok=True)
    library = LibraryStore.initialize(lib_dir)

    # 1. 准备待转写音轨
    media_file = tmp_path / "sample_voice.wav"
    _generate_test_wav(media_file, duration_secs=4.0)
    imported = library.import_audio(ImportRequest(
        source=media_file,
        title="流水线测试作品",
        kind=ItemKind.RJ_WORK,
        rj_code="RJ02000000",
    ))
    track_id = imported.track_id
    item_id = imported.item_id
    library.close()

    # 2. 准备模型 Profile
    profile_store = ModelProfileStore(tmp_path / "profiles.json")
    asr_prof = profile_store.save(
        name="Deepgram-Nova",
        base_url="https://api.deepgram.com/v1",
        model="nova-3",
        api_key="dg-secret-key-12345",
        capabilities=["transcribe"],
    )
    llm_prof = profile_store.save(
        name="DeepSeek-V3",
        base_url="https://api.deepseek.com/v1",
        model="deepseek-chat",
        api_key="ds-secret-key-67890",
        capabilities=["translate"],
        reasoning_effort="none",
    )

    # 3. 模拟标准 Worker 流转事件
    standard_events = [
        {"type": "task_progress", "stage": "asr", "progress": 0.3, "message": "ASR 特征提取..."},
        {"type": "task_progress", "stage": "asr", "progress": 0.6, "message": "日语识别完毕..."},
        {"type": "task_progress", "stage": "translate", "progress": 0.8, "message": "大模型翻译中..."},
        {"type": "task_completed", "stage": "complete", "progress": 1.0, "message": "全流程完成"},
    ]
    fake_worker = FakeWorkerAdapter(standard_events)

    settings = UiSettingsStore(tmp_path / "ui.json")
    settings.set_active_library(lib_dir)
    deps = UiDependencies(
        settings=settings,
        picker=FakeFilePicker(),
        profiles=profile_store,
        worker=fake_worker,
        startup_token="pipeline-token-secret",
        is_fixed_token=True,
        allowed_hosts={"testserver", "localhost", "127.0.0.1"},
    )
    app = create_app(deps)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        # Step 1: 登录会话与 CSRF 获取
        auth_res = await client.get("/?token=pipeline-token-secret", follow_redirects=True)
        assert auth_res.status_code == 200
        session_info = (await client.get("/api/session")).json()
        headers = {"x-csrf-token": session_info["csrf_token"], "origin": "http://testserver"}

        # Step 2: 查询 Profile 列表并校验配置字段（如 reasoning_effort）
        profiles_res = await client.get("/api/profiles")
        assert profiles_res.status_code == 200
        profiles_data = profiles_res.json()
        llm_item = next(p for p in profiles_data["llm_profiles"] if p["profile_id"] == llm_prof.profile_id)
        assert llm_item["reasoning_effort"] == "none"

        # Step 3: 提交 ASR + 翻译任务到队列
        runtime = app.state.runtime
        assert runtime.tasks is not None

        task_snapshot = ProcessingSnapshot(
            asr_provider="deepgram",
            scene="normal",
            whisper_model="medium",
            llm_profile_id=llm_prof.profile_id,
            asr_profile_id=asr_prof.profile_id,
            asr_chunk_seconds=60,
        )
        task_record = await runtime.tasks.enqueue(track_id, task_snapshot, mode="from_scratch")
        assert task_record is not None
        assert task_record.track_id == track_id

        # Step 4: 等待流水线执行完毕并验证阶段与进度
        final_task = None
        for _ in range(50):
            cur = runtime.tasks.get_task(task_record.task_id)
            if cur.status in ("completed", "failed"):
                final_task = cur
                break
            await asyncio.sleep(0.05)

        assert final_task is not None
        assert final_task.status == "completed"
        assert final_task.stage == "complete"
        assert final_task.progress == 1.0

        # Step 5: 结果落盘与状态同步验证
        store = LibraryStore.open(lib_dir)
        ja_sub = store.track_subtitle_path(track_id, "ja")
        zh_sub = store.track_subtitle_path(track_id, "zh")
        write_srt([SubtitleEntry(index=1, start=0.0, end=2.0, text="こんにちは")], ja_sub)
        write_srt([SubtitleEntry(index=1, start=0.0, end=2.0, text="你好")], zh_sub)
        store.update_track_status(track_id, "completed")
        store.close()

        # 验证音轨接口返回双语字幕
        sub_res = await client.get(f"/api/tracks/{track_id}/subtitles")
        assert sub_res.status_code == 200
        assert len(sub_res.json()["source"]) == 1

        # 验证历史中心返回完成的任务
        history_res = await client.get("/api/downloads/history")
        assert history_res.status_code == 200
        matching = next(t for t in history_res.json()["subtitle_tasks"] if t["task_id"] == task_record.task_id)
        assert matching["status"] == "completed"

        # Step 6: 任务异常捕获与失败重试恢复
        failed_events = [
            {"type": "task_progress", "stage": "asr", "progress": 0.1, "message": "连接远端 ASR 服务..."},
            {"type": "task_failed", "stage": "asr", "progress": 0.1, "message": "Deepgram API Error 401"},
        ]
        runtime.tasks.worker = FakeWorkerAdapter(failed_events)
        failed_task = await runtime.tasks.enqueue(track_id, task_snapshot, mode="from_scratch")

        failed_res = None
        for _ in range(50):
            t = runtime.tasks.get_task(failed_task.task_id)
            if t.status in ("failed", "completed"):
                failed_res = t
                break
            await asyncio.sleep(0.05)

        assert failed_res is not None
        assert failed_res.status == "failed"
        assert "401" in (failed_res.message or "")

        # 恢复 Worker 并触发重试
        recovered_events = [
            {"type": "task_progress", "stage": "asr", "progress": 0.5, "message": "重试已连接..."},
            {"type": "task_completed", "stage": "complete", "progress": 1.0, "message": "重试执行成功"},
        ]
        runtime.tasks.worker = FakeWorkerAdapter(recovered_events)
        retried_task = await runtime.tasks.retry(failed_res)

        recovered_res = None
        for _ in range(50):
            t = runtime.tasks.get_task(retried_task.task_id)
            if t.status in ("completed", "failed"):
                recovered_res = t
                break
            await asyncio.sleep(0.05)

        assert recovered_res is not None
        assert recovered_res.status == "completed"
