import io
import json

from subforge.events import EventType, make_event
from subforge.worker import jsonl_sink


def test_jsonl_sink_serializes_safe_processing_event():
    stream = io.StringIO()
    sink = jsonl_sink(stream)

    sink(make_event(EventType.ASR_PROGRESS, "job-1", stage="asr", progress=0.5))

    data = json.loads(stream.getvalue())
    assert data["type"] == "asr_progress"
    assert data["job_id"] == "job-1"
    assert data["progress"] == 0.5
    assert "api_key" not in data
