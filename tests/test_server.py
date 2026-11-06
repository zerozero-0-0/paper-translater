import pytest

from paper_translator.llm import LlamaServer, ServerError


def binary_in(tmp_path, monkeypatch, name):
    path = tmp_path / name
    path.touch()
    monkeypatch.setattr("paper_translator.llm.find_binary", lambda _: path)


def test_command_uses_serve_subcommand_and_draft_model(config, tmp_path, monkeypatch):
    binary_in(tmp_path, monkeypatch, "llama")
    (tmp_path / "8b.gguf").touch()
    (tmp_path / "small.gguf").touch()

    command = LlamaServer(config).command(config.models["plamo-8b"])

    assert command[1] == "serve"
    assert command[command.index("-md") + 1].endswith("small.gguf")
    assert command[command.index("--spec-draft-n-max") + 1] == "6"
    assert "--chat-template-file" not in command


def test_command_for_llama_server_has_no_subcommand(config, tmp_path, monkeypatch):
    binary_in(tmp_path, monkeypatch, "llama-server")
    (tmp_path / "small.gguf").touch()

    command = LlamaServer(config).command(config.models["small"])

    assert command[1] == "-m"
    assert "-md" not in command


def test_draft_model_is_optional(config, tmp_path, monkeypatch):
    binary_in(tmp_path, monkeypatch, "llama")
    (tmp_path / "8b.gguf").touch()

    assert "-md" not in LlamaServer(config).command(config.models["plamo-8b"])


def test_missing_model_explains_how_to_get_it(config, tmp_path, monkeypatch):
    binary_in(tmp_path, monkeypatch, "llama")

    with pytest.raises(ServerError, match="setup"):
        LlamaServer(config).command(config.models["plamo-8b"])


def test_missing_binary_explains_what_to_do(config, monkeypatch):
    monkeypatch.setattr("paper_translator.llm.find_binary", lambda _: None)

    with pytest.raises(ServerError, match="llama.cpp"):
        LlamaServer(config).command(config.models["plamo-8b"])
