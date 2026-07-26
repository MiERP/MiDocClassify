from __future__ import annotations

import importlib.util
import inspect

import pytest

from phanloaivanban.__main__ import main
from phanloaivanban import desktop


def test_cli_exposes_only_document_recognition_commands(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["--help"])

    assert exc_info.value.code == 0
    help_text = capsys.readouterr().out
    assert "scan" in help_text
    assert "desktop" in help_text
    assert "sync-check" in help_text
    assert "sync-repair" in help_text
    assert "chat" not in help_text
    assert "embedding" not in help_text
    assert "rerank" not in help_text
    assert "semantic" not in help_text


@pytest.mark.parametrize(
    "module_name",
    [
        "chat",
        "embeddings",
        "legal_chat",
        "llm",
        "llama_client",
        "llama_service",
        "query_expansion",
        "reranker",
        "retrieval",
    ],
)
def test_llm_chat_modules_are_not_packaged(module_name: str) -> None:
    assert importlib.util.find_spec(f"phanloaivanban.{module_name}") is None


def test_desktop_contains_only_document_recognition_ui() -> None:
    source = inspect.getsource(desktop).lower()
    assert "chat" not in source
    assert "llama" not in source
    assert "embedding" not in source


def test_desktop_moves_copyright_notice_to_window_title() -> None:
    assert desktop.WINDOW_TITLE == (
        "MiDoc - Classify \u2014 Ph\u1ea7n m\u1ec1m qu\u1ea3n l\u00fd th\u1ed1ng k\u00ea t\u00e0i li\u1ec7u, "
        "b\u1ea3n quy\u1ec1n ph\u1ea7n m\u1ec1m thu\u1ed9c v\u1ec1 Long-HAVS. Chi ti\u1ebft li\u00ean h\u1ec7 0982.958.730."
    )
    assert "author_label" not in inspect.getsource(desktop)
