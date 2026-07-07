from __future__ import annotations

import json
import subprocess
import urllib.error
from io import BytesIO
from pathlib import Path

import pytest

from phanloaivanban import llm as llm_module

from phanloaivanban import pipeline
from phanloaivanban.llm import LocalLLM, _chat_prompt, _parse_server_response, _parse_server_text


class _FakeServerProcess:
    def __init__(self) -> None:
        self.terminated = False
        self.waited = False
        self.killed = False
        self.returncode = None

    def poll(self):
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = 0

    def wait(self, timeout: float | None = None) -> int:
        self.waited = True
        return 0

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9


def _runtime_with_llama(tmp_path: Path) -> Path:
    runtime_dir = tmp_path / "runtime"
    llama_bin = runtime_dir / "llama-bin"
    models = runtime_dir / "models"
    llama_bin.mkdir(parents=True)
    models.mkdir(parents=True)
    (llama_bin / "llama-cli.exe").write_bytes(b"cli")
    (llama_bin / "llama-server.exe").write_bytes(b"server")
    (models / "qwen.gguf").write_bytes(b"model")
    return runtime_dir


def test_extract_json_uses_persistent_llama_server_when_healthy(tmp_path: Path, monkeypatch) -> None:
    runtime_dir = _runtime_with_llama(tmp_path)
    process = _FakeServerProcess()
    popen_calls: list[list[str]] = []
    requested_urls: list[str] = []

    def fake_popen(args, **kwargs):
        popen_calls.append([str(arg) for arg in args])
        return process

    def fake_urlopen(request, timeout: float):
        requested_urls.append(request.full_url)
        if request.full_url.endswith("/health"):
            return BytesIO(b'{"status":"ok"}')
        body = json.loads(request.data.decode("utf-8"))
        assert body["messages"][0]["role"] == "user"
        payload = {
            "choices": [
                {"message": {"content": '{"so_van_ban":"42/QD","ten_van_ban":"Test"}'}}
            ]
        }
        return BytesIO(json.dumps(payload).encode("utf-8"))

    monkeypatch.setattr(llm_module.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(llm_module.urllib.request, "urlopen", fake_urlopen)

    client = LocalLLM(runtime_dir=runtime_dir)
    try:
        result = client.extract_json("sample text")
    finally:
        client.close()

    assert result == {"so_van_ban": "42/QD", "ten_van_ban": "Test"}
    assert popen_calls
    assert "llama-server.exe" in popen_calls[0][0]
    assert any(url.endswith("/v1/chat/completions") for url in requested_urls)
    assert process.terminated is True
    assert process.waited is True
    assert process.killed is False


def test_extract_json_falls_back_to_llama_cli_when_server_http_fails(tmp_path: Path, monkeypatch) -> None:
    runtime_dir = _runtime_with_llama(tmp_path)
    process = _FakeServerProcess()
    run_calls: list[list[str]] = []

    def fake_popen(args, **kwargs):
        return process

    def fake_urlopen(request, timeout: float):
        if request.full_url.endswith("/health"):
            return BytesIO(b'{"status":"ok"}')
        raise urllib.error.URLError("boom")

    def fake_run(args, **kwargs):
        run_calls.append([str(arg) for arg in args])
        return subprocess.CompletedProcess(args=args, returncode=0, stdout='{"so_van_ban":"CLI"}', stderr="")

    monkeypatch.setattr(llm_module.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(llm_module.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(llm_module.subprocess, "run", fake_run)

    client = LocalLLM(runtime_dir=runtime_dir)
    try:
        result = client.extract_json("sample text")
    finally:
        client.close()

    assert result == {"so_van_ban": "CLI"}
    assert run_calls
    assert "llama-cli.exe" in run_calls[0][0]
    assert process.terminated is True


def test_available_true_when_only_llama_cli_and_model_exist(tmp_path: Path) -> None:
    runtime_dir = tmp_path / "runtime"
    (runtime_dir / "llama-bin").mkdir(parents=True)
    (runtime_dir / "models").mkdir(parents=True)
    (runtime_dir / "llama-bin" / "llama-cli.exe").write_bytes(b"cli")
    (runtime_dir / "models" / "qwen.gguf").write_bytes(b"model")

    assert LocalLLM(runtime_dir=runtime_dir).available() is True


def test_available_true_when_only_llama_server_and_model_exist(tmp_path: Path) -> None:
    runtime_dir = tmp_path / "runtime"
    (runtime_dir / "llama-bin").mkdir(parents=True)
    (runtime_dir / "models").mkdir(parents=True)
    (runtime_dir / "llama-bin" / "llama-server.exe").write_bytes(b"server")
    (runtime_dir / "models" / "qwen.gguf").write_bytes(b"model")

    assert LocalLLM(runtime_dir=runtime_dir).available() is True


def test_parse_json_from_server_rejects_malformed_content() -> None:
    payload = {"choices": [{"message": {"content": "not json"}}]}

    result = _parse_server_response(json.dumps(payload).encode("utf-8"))

    assert result is None


def test_parse_server_text_returns_raw_chat_content() -> None:
    payload = {"choices": [{"message": {"content": "Cau tra loi"}}]}

    assert _parse_server_text(json.dumps(payload).encode("utf-8")) == "Cau tra loi"


def test_chat_prompt_requires_answer_from_wiki_context() -> None:
    prompt = _chat_prompt("Hoi gi?", "Nguon wiki")

    assert "NGUON WIKI" in prompt
    assert "Hoi gi?" in prompt
    assert "Nguon wiki" in prompt
    assert "Khong thay thong tin trong nguon" in prompt


def test_scan_folder_does_not_start_local_llm_for_metadata(tmp_path: Path, monkeypatch) -> None:
    started: list[bool] = []

    class FakeLocalLLM:
        def __init__(self) -> None:
            started.append(True)

    monkeypatch.setattr(pipeline, "LocalLLM", FakeLocalLLM)
    monkeypatch.setattr(pipeline, "iter_documents", lambda folder: [folder / "broken.pdf"])
    monkeypatch.setattr(pipeline, "extract_text", lambda path: (_ for _ in ()).throw(RuntimeError("boom")))

    with pytest.raises(RuntimeError, match="boom"):
        pipeline.scan_folder(tmp_path, tmp_path / "records.sqlite")

    assert started == []


# ── Prompt content tests ──


SAMPLE_WIKI = """---
type: legal_document_source
ten_van_ban: "Luật Bảo vệ môi trường"
---

# Luật Bảo vệ môi trường

## Metadata candidates
- ten_van_ban: Luật Bảo vệ môi trường

## Header text
QUỐC HỘI
Luật số: 72/2020/QH14

## Nội dung văn bản
Luật này quy định về hoạt động bảo vệ môi trường; quyền, nghĩa vụ và trách nhiệm của cơ quan,
tổ chức, hộ gia đình và cá nhân trong bảo vệ môi trường.
"""


def test_prompt_requires_3_to_5_vietnamese_sentences_for_trich_yeu() -> None:
    prompt = LocalLLM._prompt(SAMPLE_WIKI)
    assert "3-5" in prompt
    assert "tiếng Việt" in prompt
    assert "trich_yeu" in prompt


def test_prompt_describes_wiki_canonical_markdown_input() -> None:
    prompt = LocalLLM._prompt(SAMPLE_WIKI)
    assert "wiki" in prompt.lower()
    assert "markdown" in prompt.lower()
    assert "YAML frontmatter" in prompt


def test_prompt_enforces_json_only_output() -> None:
    prompt = LocalLLM._prompt(SAMPLE_WIKI)
    assert "JSON object" in prompt
    assert "json" in prompt.lower()


def test_prompt_forbids_markdown_output() -> None:
    prompt = LocalLLM._prompt(SAMPLE_WIKI)
    # Check that markdown is only prohibited in output context, not input
    assert "KHÔNG markdown" in prompt or "không markdown" in prompt.lower()
    assert "không giải thích" in prompt.lower()


def test_prompt_forbids_chain_of_thought_and_guessing() -> None:
    prompt = LocalLLM._prompt(SAMPLE_WIKI)
    assert "chain-of-thought" in prompt or "suy luận dây chuyền" in prompt
    assert "KHÔNG ĐOÁN" in prompt or "không đoán" in prompt.lower()


def test_prompt_instructs_metadata_cross_verification_against_content() -> None:
    prompt = LocalLLM._prompt(SAMPLE_WIKI)
    assert "đối chiếu" in prompt.lower() or "xác minh" in prompt.lower()
    assert "metadata" in prompt.lower()


def test_prompt_does_not_allow_hallucination() -> None:
    prompt = LocalLLM._prompt(SAMPLE_WIKI)
    assert "Không tự ý thêm" in prompt or "không tự ý thêm" in prompt.lower()
    assert "null" in prompt.lower()


def test_prompt_preserves_full_json_schema() -> None:
    prompt = LocalLLM._prompt(SAMPLE_WIKI)
    assert '"so_van_ban"' in prompt
    assert '"ten_van_ban"' in prompt
    assert '"co_quan_phat_hanh"' in prompt
    assert '"ngay_ban_hanh"' in prompt
    assert '"loai_van_ban"' in prompt
    assert '"trich_yeu"' in prompt


def test_prompt_input_contains_sample_wiki_text() -> None:
    prompt = LocalLLM._prompt(SAMPLE_WIKI)
    assert "Luật này quy định" in prompt
