from pathlib import Path


def test_no_queue_words():
    text = Path("README.md").read_text(encoding="utf-8").lower()
    assert "worker queue" in text
