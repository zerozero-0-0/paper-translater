from pathlib import Path

import pymupdf
import pytest

from paper_translator.config import Config, Model
from paper_translator.llm import Translation


class FakeServer:
    """llama serve の代わりに、決まった訳文を返す。"""

    def __init__(self):
        self.running = False
        self.calls: list[str] = []
        self.failures: dict[str, Exception | Translation] = {}

    async def start(self, model: str) -> None:
        self.running = True
        self.started_with = model

    async def stop(self) -> None:
        self.running = False

    async def close(self) -> None:
        self.running = False

    async def translate(self, text: str, history: list[tuple[str, str]]) -> Translation:
        self.calls.append(text)
        failure = self.failures.get(text)
        if isinstance(failure, Exception):
            raise failure
        return failure or Translation(f"訳: {text}", True)


@pytest.fixture
def config(tmp_path: Path) -> Config:
    return Config(
        binary="auto",
        models={
            "plamo-8b": Model("plamo-8b", "8B", "repo/8b", tmp_path / "8b.gguf", "small", 6),
            "small": Model("small", "0.8B", "repo/small", tmp_path / "small.gguf"),
        },
        default_model="plamo-8b",
        port=0,
        ctx_size=4096,
        idle_stop_seconds=1,
        source_lang="en",
        target_lang="ja",
        form="plain",
        history=0,
        glossary=(),
        data_dir=tmp_path / "data",
    )


@pytest.fixture
def server() -> FakeServer:
    return FakeServer()


@pytest.fixture
def pdf_bytes() -> bytes:
    document = pymupdf.open()
    page = document.new_page(width=612, height=792)
    page.insert_textbox((72, 70, 540, 110), "A Small Paper About Testing", fontsize=18)
    page.insert_textbox((72, 150, 540, 200), "This is the first paragraph of the body text in the paper.", fontsize=10)
    page.insert_textbox((72, 220, 540, 270), "This is the second paragraph of the body text in the paper.", fontsize=10)
    return document.tobytes()
