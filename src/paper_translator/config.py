import shutil
import tomllib
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BINARY_CANDIDATES = ("llama", "llama-server")
BINARY_FALLBACKS = (Path.home() / ".local/bin/llama",)


@dataclass(frozen=True)
class Model:
    key: str
    label: str
    repo: str
    path: Path
    draft: str | None = None
    draft_max: int = 0


@dataclass(frozen=True)
class Config:
    binary: str
    models: dict[str, Model]
    default_model: str
    port: int
    ctx_size: int
    idle_stop_seconds: int
    source_lang: str
    target_lang: str
    form: str
    history: int
    glossary: tuple[dict[str, str], ...]
    data_dir: Path


def find_binary(configured: str) -> Path | None:
    if configured != "auto":
        path = Path(configured).expanduser()
        return path if path.exists() else None
    for name in BINARY_CANDIDATES:
        if found := shutil.which(name):
            return Path(found)
    return next((path for path in BINARY_FALLBACKS if path.exists()), None)


def load_config(root: Path = ROOT) -> Config:
    models_dir = root / "models"
    raw = tomllib.loads((models_dir / "models.toml").read_text())
    server, translation = raw["server"], raw["translation"]
    models = {
        key: Model(
            key=key,
            label=model["label"],
            repo=model["repo"],
            path=models_dir / model["file"],
            draft=model.get("draft"),
            draft_max=model.get("draft_max", 0),
        )
        for key, model in raw["models"].items()
    }
    return Config(
        binary=server["binary"],
        models=models,
        default_model=raw["default"],
        port=server["port"],
        ctx_size=server["ctx_size"],
        idle_stop_seconds=server["idle_stop_seconds"],
        source_lang=translation["source_lang"],
        target_lang=translation["target_lang"],
        form=translation["form"],
        history=translation["history"],
        glossary=tuple(tomllib.loads((models_dir / "glossary.toml").read_text())["term"]),
        data_dir=root / "data",
    )
