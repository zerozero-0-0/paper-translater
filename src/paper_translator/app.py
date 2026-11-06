import asyncio
import hashlib
import json
import shutil
from contextlib import asynccontextmanager
from pathlib import Path

import pymupdf
from fastapi import FastAPI, Form, HTTPException, Response, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .config import Config, load_config
from .llm import LlamaServer
from .pdf import extract, reference_index
from .store import Store
from .worker import Worker

STATIC_DIR = Path(__file__).parent / "static"
PAGE_DPI = 150
EQUATION_DPI = 200


class RevalidatedStaticFiles(StaticFiles):
    """UI の更新がすぐ届くように、毎回 ETag で確認させる。"""

    async def get_response(self, path: str, scope) -> Response:
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache"
        return response


def parse_pdf(path: Path) -> tuple[list[dict], list]:
    with pymupdf.open(path) as document:
        pages = [{"width": page.rect.width, "height": page.rect.height} for page in document]
        return pages, extract(document)


def render_page(source: Path, target: Path, page: int) -> None:
    with pymupdf.open(source) as document:
        document[page].get_pixmap(dpi=PAGE_DPI).save(target)


def render_segment(source: Path, boxes: list[list[float]]) -> bytes:
    page = boxes[0][0]
    clip = pymupdf.Rect()
    for box in boxes:
        if box[0] == page:
            clip |= pymupdf.Rect(box[1:])
    with pymupdf.open(source) as document:
        return document[int(page)].get_pixmap(dpi=EQUATION_DPI, clip=clip + (-4, -4, 4, 4)).tobytes("png")


def to_markdown(segments: list[dict], model_label: str) -> str:
    lines = []
    for segment in segments:
        text = segment["translation"] or segment["source"]
        match segment["kind"]:
            case "title":
                lines.append(f"# {text}")
            case "heading":
                lines.append(f"## {text}")
            case "equation":
                lines.append(f"`{segment['source']}`")
            case "caption" | "footnote":
                lines.append(f"> {text}")
            case "text":
                lines.append(text)
    lines.append(f"---\n\nこの訳文は PLaMo 3 Translate {model_label} による機械翻訳の生成物です。Built with PLaMo")
    return "\n\n".join(lines) + "\n"


def create_app(config: Config, server: LlamaServer | None = None) -> FastAPI:
    papers_dir = config.data_dir / "papers"
    papers_dir.mkdir(parents=True, exist_ok=True)
    store = Store(config.data_dir / "app.db")
    server = server or LlamaServer(config)
    worker = Worker(config, store, server)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        store.pause_unfinished()
        task = asyncio.create_task(worker.run())
        yield
        task.cancel()
        await server.close()

    app = FastAPI(lifespan=lifespan)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost"])

    def get_paper(paper_id: str) -> dict:
        paper = store.paper(paper_id)
        if paper is None:
            raise HTTPException(404, "論文が見つかりません")
        return paper

    @app.get("/api/models")
    def list_models() -> dict:
        models = [
            {"key": model.key, "label": model.label, "available": model.path.exists()}
            for model in config.models.values()
        ]
        return {"default": config.default_model, "models": models}

    @app.get("/api/papers")
    def list_papers() -> list[dict]:
        return store.papers()

    @app.post("/api/papers", status_code=201)
    async def upload(file: UploadFile, model: str | None = Form(None)) -> dict:
        model = model or config.default_model
        if model not in config.models:
            raise HTTPException(400, "指定されたモデルがありません")
        data = await file.read()
        paper_id = hashlib.sha256(data).hexdigest()
        if existing := store.paper(paper_id):
            return existing

        directory = papers_dir / paper_id
        directory.mkdir(exist_ok=True)
        path = directory / "source.pdf"
        path.write_bytes(data)
        try:
            pages, segments = await run_in_threadpool(parse_pdf, path)
            if not any(segment.kind == "text" for segment in segments):
                raise HTTPException(422, "本文のテキストを取り出せませんでした。スキャン PDF には未対応です")
        except (pymupdf.FileDataError, ValueError, HTTPException) as error:
            shutil.rmtree(directory)
            if isinstance(error, HTTPException):
                raise
            raise HTTPException(400, "PDF を読み込めませんでした") from error

        title = next((s.source for s in segments if s.kind == "title"), file.filename or "無題")
        store.add_paper(paper_id, file.filename or "paper.pdf", title, pages, segments, model)
        worker.wake.set()
        return get_paper(paper_id)

    @app.get("/api/papers/{paper_id}")
    def read_paper(paper_id: str) -> dict:
        segments = store.segments(paper_id)
        return {**get_paper(paper_id), "segments": segments, "references": reference_index(segments)}

    @app.post("/api/papers/{paper_id}/pause")
    def pause(paper_id: str) -> dict:
        if get_paper(paper_id)["status"] in ("queued", "translating"):
            store.set_status(paper_id, "paused")
            worker.publish_paper(paper_id)
        return get_paper(paper_id)

    @app.post("/api/papers/{paper_id}/resume")
    async def resume(paper_id: str) -> dict:
        get_paper(paper_id)
        store.retry_failed(paper_id)
        store.set_status(paper_id, "queued")
        worker.wake.set()
        worker.publish_paper(paper_id)
        return get_paper(paper_id)

    @app.delete("/api/papers/{paper_id}", status_code=204)
    def delete(paper_id: str) -> Response:
        get_paper(paper_id)
        store.delete_paper(paper_id)
        shutil.rmtree(papers_dir / paper_id)
        return Response(status_code=204)

    @app.get("/api/papers/{paper_id}/pages/{page}.png")
    def page_image(paper_id: str, page: int) -> FileResponse:
        paper = get_paper(paper_id)
        if not 0 <= page < len(paper["pages"]):
            raise HTTPException(404, "ページが見つかりません")
        target = papers_dir / paper_id / f"page-{page}.png"
        if not target.exists():
            render_page(papers_dir / paper_id / "source.pdf", target, page)
        return FileResponse(target, media_type="image/png", headers={"Cache-Control": "max-age=86400"})

    @app.get("/api/papers/{paper_id}/segments/{idx}.png")
    def segment_image(paper_id: str, idx: int) -> Response:
        get_paper(paper_id)
        segment = store.segment(paper_id, idx)
        if segment is None:
            raise HTTPException(404, "段落が見つかりません")
        image = render_segment(papers_dir / paper_id / "source.pdf", segment["boxes"])
        return Response(image, media_type="image/png")

    @app.get("/api/papers/{paper_id}/export.md")
    def export(paper_id: str) -> PlainTextResponse:
        label = config.models[get_paper(paper_id)["model"]].label
        return PlainTextResponse(to_markdown(store.segments(paper_id), label), media_type="text/markdown")

    @app.get("/api/papers/{paper_id}/events")
    async def events(paper_id: str) -> StreamingResponse:
        get_paper(paper_id)

        async def stream():
            queue = worker.subscribe(paper_id)
            try:
                while True:
                    try:
                        event = await asyncio.wait_for(queue.get(), timeout=30)
                        yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                    except TimeoutError:
                        yield ": keep-alive\n\n"
            finally:
                worker.unsubscribe(paper_id, queue)

        return StreamingResponse(stream(), media_type="text/event-stream")

    app.mount("/", RevalidatedStaticFiles(directory=STATIC_DIR, html=True))
    return app


def default_app() -> FastAPI:
    return create_app(load_config())
