from paper_translator.pdf import Segment
from paper_translator.store import Store


def test_paper_counts_failed_segments(tmp_path):
    store = Store(tmp_path / "app.db")
    segments = [Segment("text", 0, "one"), Segment("text", 0, "two"), Segment("reference", 0, "ref")]
    store.add_paper("id", "a.pdf", "A", [], segments)
    store.save_translation("id", 0, "一", "done")
    store.save_translation("id", 1, "", "failed")

    paper = store.paper("id")
    assert (paper["done"], paper["total"], paper["failed"]) == (2, 2, 1)

    store.retry_failed("id")
    assert store.paper("id")["failed"] == 0
