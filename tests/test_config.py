from pathlib import Path

import pytest

from paper_translator.config import ROOT, load_config

MODELS = """
default = "big"

[models.big]
label = "big"
repo = "r"
file = "big.gguf"
draft = "{draft}"
draft_max = 6

[models.small]
label = "small"
repo = "r"
file = "small.gguf"

[server]
binary = "auto"
port = 1
ctx_size = 1
idle_stop_seconds = 1

[translation]
source_lang = "en"
target_lang = "ja"
form = "plain"
history = 0
"""


def write_config(root: Path, draft: str) -> None:
    (root / "models").mkdir()
    (root / "models/models.toml").write_text(MODELS.format(draft=draft))
    (root / "models/glossary.toml").write_text('[[term]]\nsource = "a"\ntarget = "b"\n')


def test_unknown_draft_model_is_an_error(tmp_path):
    write_config(tmp_path, "missing")

    with pytest.raises(ValueError, match="missing"):
        load_config(tmp_path)


def test_shipped_config_is_valid():
    config = load_config(ROOT)

    assert config.models[config.default_model].draft in config.models
