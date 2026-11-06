import asyncio
import re
import time
from dataclasses import dataclass

import httpx

from .config import Config, Model, find_binary

HISTORY_CHAR_LIMIT = 6000
STARTUP_TIMEOUT_SECONDS = 120


class ServerError(RuntimeError):
    pass


@dataclass
class Translation:
    text: str
    complete: bool


class LlamaServer:
    """llama serve を必要なときだけ起動し、使い終わったら止める。"""

    def __init__(self, config: Config):
        self.config = config
        self.base_url = f"http://127.0.0.1:{config.port}"
        self.process: asyncio.subprocess.Process | None = None
        self.model: str | None = None
        self.log_path = config.data_dir / "llama.log"
        self.client = httpx.AsyncClient(timeout=httpx.Timeout(600, connect=5))

    @property
    def running(self) -> bool:
        return self.process is not None and self.process.returncode is None

    def command(self, model: Model) -> list[str]:
        config = self.config
        binary = find_binary(config.binary)
        if binary is None:
            raise ServerError("llama.cpp が見つかりません。`uv run paper-translator setup` で確認してください")
        if not model.path.exists():
            raise ServerError(f"{model.label} のモデルがありません。`uv run paper-translator setup` で取得してください")
        command = [str(binary)] + (["serve"] if binary.name == "llama" else [])
        command += ["-m", str(model.path), "--jinja", "--no-prefill-assistant", "--offline", "--no-webui"]
        command += ["--host", "127.0.0.1", "--port", str(config.port), "-c", str(config.ctx_size), "-np", "1"]
        draft = config.models.get(model.draft or "")
        if draft and draft.path.exists():
            command += ["-md", str(draft.path), "--spec-type", "draft-simple"]
            command += ["--spec-draft-n-max", str(model.draft_max)]
        return command

    async def start(self, model_key: str) -> None:
        if self.running and self.model == model_key:
            return
        await self.stop()
        command = self.command(self.config.models[model_key])
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("w") as log:
            self.process = await asyncio.create_subprocess_exec(
                *command,
                stdout=log,
                stderr=asyncio.subprocess.STDOUT,
            )
        self.model = model_key
        await self._wait_until_ready()

    async def _wait_until_ready(self) -> None:
        deadline = time.monotonic() + STARTUP_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            if not self.running:
                raise ServerError(f"llama serve が終了しました。{self.log_path} を確認してください")
            try:
                if (await self.client.get(f"{self.base_url}/health")).status_code == 200:
                    return
            except httpx.TransportError:
                pass
            await asyncio.sleep(0.5)
        await self.stop()
        raise ServerError("llama serve の起動がタイムアウトしました")

    async def stop(self) -> None:
        if not self.running:
            return
        self.process.terminate()
        try:
            await asyncio.wait_for(self.process.wait(), timeout=10)
        except TimeoutError:
            self.process.kill()
            await self.process.wait()

    async def translate(self, text: str, history: list[tuple[str, str]]) -> Translation:
        config = self.config
        messages = []
        if len(text) + sum(len(s) + len(t) for s, t in history) < HISTORY_CHAR_LIMIT:
            for source, translation in history:
                messages += [
                    {"role": "user", "content": clean(source)},
                    {"role": "assistant", "content": clean(translation)},
                ]
        messages.append({"role": "user", "content": clean(text)})

        kwargs = {"source_lang": config.source_lang, "target_lang": config.target_lang, "form": config.form}
        glossary = matching_terms(text, config.glossary)
        if glossary:
            kwargs["glossary"] = glossary

        response = await self.client.post(
            f"{self.base_url}/v1/chat/completions",
            json={
                "messages": messages,
                "temperature": 0,
                # 繰り返しに陥っても止まるように、原文の長さから上限を決める
                "max_tokens": min(3000, max(256, len(text))),
                "chat_template_kwargs": kwargs,
            },
        )
        response.raise_for_status()
        choice = response.json()["choices"][0]
        return Translation(choice["message"]["content"].strip(), choice["finish_reason"] == "stop")

    async def close(self) -> None:
        await self.stop()
        await self.client.aclose()


def matching_terms(text: str, glossary: tuple[dict[str, str], ...]) -> list[dict[str, str]]:
    return [term for term in glossary if re.search(rf"\b{re.escape(term['source'])}s?\b", text, re.IGNORECASE)]


def clean(text: str) -> str:
    """チャットテンプレートが拒否する予約トークンを取り除く。"""
    return text.replace("<|plamo:", "<| plamo:")
