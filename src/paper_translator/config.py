import tomllib
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Config:
    binary: Path
    model: Path
    template: Path
    port: int
    ctx_size: int
    idle_stop_seconds: int
    source_lang: str
    target_lang: str
    form: str
    history: int
    glossary: tuple[dict[str, str], ...]
    data_dir: Path


def load_config(root: Path = ROOT) -> Config:
    models_dir = root / "models"
    raw = tomllib.loads((models_dir / "models.toml").read_text())
    model = raw["models"][raw["active"]]
    server, translation = raw["server"], raw["translation"]
    return Config(
        binary=Path(server["binary"]).expanduser(),
        model=models_dir / model["file"],
        template=models_dir / model["template"],
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
