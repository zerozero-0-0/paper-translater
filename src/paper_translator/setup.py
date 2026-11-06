"""初回セットアップ。llama.cpp の確認とモデルの取得を行う。"""

from huggingface_hub import hf_hub_download

from .config import Config, find_binary, load_config

INSTALL_HINT = "llama.cpp が見つかりません。`brew install llama.cpp` などでインストールしてください"


def download_models(config: Config) -> None:
    for model in config.models.values():
        if model.path.exists():
            print(f"{model.label}: 取得済み")
            continue
        print(f"{model.label}: {model.repo} から取得します")
        hf_hub_download(model.repo, model.path.name, local_dir=model.path.parent)


def main() -> int:
    config = load_config()
    binary = find_binary(config.binary)
    print(f"llama.cpp: {binary}" if binary else INSTALL_HINT)
    download_models(config)
    if not binary:
        return 1
    print("準備できました。`uv run paper-translator` で起動します")
    return 0
