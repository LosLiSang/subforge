from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

from subforge.config import load_config, setup_logging
from subforge.events import ProcessingEvent
from subforge.models import Job
from subforge.orchestrator import process_one
from subforge.resume import ResumeStore


def jsonl_sink(stream):
    """Create an EventSink that writes one JSON object per line."""
    def emit(event: ProcessingEvent) -> None:
        stream.write(json.dumps(event.to_dict(), ensure_ascii=False) + "\n")
        stream.flush()
    return emit


async def run_request(request_path: Path) -> int:
    request = json.loads(request_path.read_text(encoding="utf-8"))
    overrides = request.get("config_overrides") or {}
    jobs_dir = overrides.pop("jobs_dir", None)
    models_dir = overrides.pop("models_dir", None)
    if overrides.get("output_dir"):
        overrides["output_dir"] = Path(overrides["output_dir"])
    config = load_config(
        config_path=Path(request["config_path"]) if request.get("config_path") else None,
        cli_overrides=overrides,
    )
    if jobs_dir:
        config.jobs_dir = Path(jobs_dir)
    if models_dir:
        config.models_dir = Path(models_dir)
    if request.get("model_path"):
        config.direct_model_path = Path(request["model_path"])
    if os.environ.get("SUBFORGE_WORKER_LLM_API_KEY"):
        config.llm_api_key = os.environ["SUBFORGE_WORKER_LLM_API_KEY"]
    if os.environ.get("SUBFORGE_WORKER_DEEPGRAM_API_KEY"):
        config.deepgram_api_key = os.environ["SUBFORGE_WORKER_DEEPGRAM_API_KEY"]
    setup_logging(config)
    job = Job(
        file_path=Path(request["media_path"]),
        source_lang=request.get("source_lang", config.source_lang),
        target_lang=request.get("target_lang", config.target_lang),
        model_size=request.get("model", config.model),
        id=request["job_id"],
    )
    resume_store = ResumeStore(
        config.jobs_dir,
        identity=request.get("track_id"),
        relative_to=Path(request["library_root"]) if request.get("library_root") else None,
    )
    await process_one(
        job, config, pbar_slot=0,
        event_sink=jsonl_sink(sys.stdout),
        resume_store=resume_store,
    )
    return 0 if job.error is None else 1


def main() -> None:
    parser = argparse.ArgumentParser(description="SubForge processing worker")
    parser.add_argument("--request", required=True, type=Path)
    args = parser.parse_args()
    raise SystemExit(asyncio.run(run_request(args.request)))


if __name__ == "__main__":
    main()
