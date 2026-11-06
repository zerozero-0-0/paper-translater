import asyncio
import logging

import httpx

from .config import Config
from .llm import LlamaServer, ServerError
from .store import Store

log = logging.getLogger(__name__)


class Worker:
    """論文を 1 本ずつ、段落単位で翻訳して保存する。"""

    def __init__(self, config: Config, store: Store, server: LlamaServer):
        self.config = config
        self.store = store
        self.server = server
        self.wake = asyncio.Event()
        self.subscribers: dict[str, set[asyncio.Queue]] = {}

    def subscribe(self, paper_id: str) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue()
        self.subscribers.setdefault(paper_id, set()).add(queue)
        return queue

    def unsubscribe(self, paper_id: str, queue: asyncio.Queue) -> None:
        self.subscribers.get(paper_id, set()).discard(queue)

    def publish(self, paper_id: str, event: dict) -> None:
        for queue in self.subscribers.get(paper_id, ()):
            queue.put_nowait(event)

    def publish_paper(self, paper_id: str) -> None:
        if paper := self.store.paper(paper_id):
            keys = ("status", "error", "done", "total", "failed", "model")
            self.publish(paper_id, {"type": "paper", **{key: paper[key] for key in keys}})

    async def run(self) -> None:
        while True:
            paper_id = self.store.next_queued()
            if paper_id:
                await self._translate(paper_id)
                continue
            self.wake.clear()
            timeout = self.config.idle_stop_seconds if self.server.running else None
            try:
                await asyncio.wait_for(self.wake.wait(), timeout)
            except TimeoutError:
                await self.server.stop()

    async def _translate(self, paper_id: str) -> None:
        try:
            self.store.set_status(paper_id, "translating")
            self.publish_paper(paper_id)
            await self.server.start(self.store.paper(paper_id)["model"])
            while True:
                paper = self.store.paper(paper_id)
                if paper is None or paper["status"] != "translating":
                    return
                segment = self.store.next_pending(paper_id)
                if segment is None:
                    break
                await self._translate_segment(paper_id, segment)
            self.store.set_status(paper_id, "done")
        except (ServerError, httpx.TransportError) as error:
            log.exception("translation stopped")
            self.store.set_status(paper_id, "error", str(error))
        self.publish_paper(paper_id)

    async def _translate_segment(self, paper_id: str, segment: dict) -> None:
        idx = segment["idx"]
        # 履歴の入力処理は数秒かかるので、文脈が効く本文にだけ渡す
        history = self.store.history(paper_id, idx, self.config.history) if segment["kind"] == "text" else []
        try:
            result = await self.server.translate(segment["source"], history)
            text, status = result.text, "done" if result.complete and result.text else "failed"
        except httpx.HTTPStatusError as error:
            log.warning("segment %s failed: %s", idx, error.response.text[:300])
            text, status = "", "failed"
        self.store.save_translation(paper_id, idx, text, status)
        self.publish(paper_id, {"type": "segment", "idx": idx, "translation": text, "status": status})
        self.publish_paper(paper_id)
