# paper-translator

英語論文の PDF を、ローカルの PLaMo 翻訳モデル（llama.cpp）で和訳する Web UI です。
起動後はネットワークを使わず、原文ページと訳文を左右に並べて読めます。

## 起動

```sh
uv run paper-translator
```

ブラウザで http://127.0.0.1:8787 を開き、PDF をアップロードします。
`llama serve` は翻訳のときだけ自動で起動し、終わると `idle_stop_seconds` 後に停止します。

## モデルと設定

`models/` に GGUF、チャットテンプレート、`models.toml`、`glossary.toml` を置きます。
GGUF はリポジトリに含まないので、[pfnet/plamo-3-translate-8b-GGUF](https://huggingface.co/pfnet/plamo-3-translate-8b-GGUF) の `plamo-3-translate-8b-Q4_K_M.gguf` を `models/` に置いてください。
モデルの切り替え、ポート、文体は `models.toml` で設定します。
訳語は `glossary.toml` で固定します。原文に語が含まれる段落にだけ渡されます。

## 開発

```sh
uv run pytest
node --test tests/math.test.js
```

## データ

アップロードした PDF、ページ画像、翻訳結果は `data/` に保存されます。
段落ごとに保存するため、中断しても再開でき、同じ PDF は再翻訳しません。

## 制限

- テキスト PDF のみ対応しています（スキャン PDF は OCR が必要なため未対応）
- 文中の添字と分数は翻訳時に `d_k`、`1/√d_k` の形で残し、表示時に KaTeX で組版します（Markdown にはこの形のまま出力します）
- 添字が次の行と同じブロックに入る配置では、その 1 文が分断されることがあります

## 表示

図と表は、キャプションを起点に PDF から切り出して訳文側に表示します。
画面幅が 800px 以下のときは、ヘッダーの「日 / 英」で訳文と原文を切り替えます。
