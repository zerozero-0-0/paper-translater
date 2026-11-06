import asyncio

import httpx

from paper_translator.llm import ServerError, Translation
from paper_translator.pdf import Segment
from paper_translator.store import Store
from paper_translator.worker import Worker

FIRST = "First paragraph."
SECOND = "Second paragraph."


def make_worker(config, server):
    store = Store(config.data_dir / "app.db")
    store.add_paper("paper", "a.pdf", "A", [], [Segment("text", 0, FIRST), Segment("text", 0, SECOND)])
    return Worker(config, store, server), store


def test_translates_every_pending_segment(config, server):
    worker, store = make_worker(config, server)
    asyncio.run(worker._translate("paper"))

    assert store.paper("paper")["status"] == "done"
    assert [s["translation"] for s in store.segments("paper")] == [f"訳: {FIRST}", f"訳: {SECOND}"]


def test_resume_skips_saved_segments(config, server):
    worker, store = make_worker(config, server)
    store.save_translation("paper", 0, "保存済み", "done")
    asyncio.run(worker._translate("paper"))

    assert server.calls == [SECOND]
    assert store.segments("paper")[0]["translation"] == "保存済み"


def test_truncated_output_is_marked_failed_and_job_continues(config, server):
    worker, store = make_worker(config, server)
    server.failures[FIRST] = Translation("途中まで", False)
    asyncio.run(worker._translate("paper"))

    assert [s["status"] for s in store.segments("paper")] == ["failed", "done"]
    assert store.paper("paper")["failed"] == 1


def test_rejected_request_fails_only_that_segment(config, server):
    worker, store = make_worker(config, server)
    request = httpx.Request("POST", "http://test")
    response = httpx.Response(400, request=request, text="too long")
    server.failures[FIRST] = httpx.HTTPStatusError("bad", request=request, response=response)
    asyncio.run(worker._translate("paper"))

    assert [s["status"] for s in store.segments("paper")] == ["failed", "done"]


def test_server_failure_stops_job_and_keeps_progress(config, server):
    worker, store = make_worker(config, server)
    server.failures[SECOND] = ServerError("llama が停止しました")
    asyncio.run(worker._translate("paper"))

    paper = store.paper("paper")
    assert (paper["status"], paper["error"]) == ("error", "llama が停止しました")
    assert [s["status"] for s in store.segments("paper")] == ["done", "pending"]


def test_pause_stops_after_current_segment(config, server):
    worker, store = make_worker(config, server)
    original = server.translate

    async def pause_during_translation(text, history):
        store.set_status("paper", "paused")
        return await original(text, history)

    server.translate = pause_during_translation
    asyncio.run(worker._translate("paper"))

    assert store.paper("paper")["status"] == "paused"
    assert [s["status"] for s in store.segments("paper")] == ["done", "pending"]


def test_events_reach_subscribers(config, server):
    worker, _ = make_worker(config, server)
    queue = worker.subscribe("paper")
    asyncio.run(worker._translate("paper"))

    events = [queue.get_nowait() for _ in range(queue.qsize())]
    assert [e["idx"] for e in events if e["type"] == "segment"] == [0, 1]
    assert events[-1]["status"] == "done"
