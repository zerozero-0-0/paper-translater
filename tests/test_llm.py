from paper_translator.llm import clean, matching_terms

GLOSSARY = (
    {"source": "token", "target": "トークン"},
    {"source": "self-attention", "target": "セルフアテンション"},
)


def test_matching_terms_uses_word_boundaries_and_plurals():
    assert matching_terms("Input Tokens are embedded.", GLOSSARY) == [GLOSSARY[0]]
    assert matching_terms("A tokenizer splits text.", GLOSSARY) == []


def test_clean_removes_reserved_token_prefix():
    assert "<|plamo:" not in clean("before <|plamo:msg|> after")
