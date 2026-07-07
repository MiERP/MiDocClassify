from __future__ import annotations

import atexit
import json
import os
import re
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Final

SERVER_STARTUP_SECONDS: Final = 8.0
SERVER_POLL_SECONDS: Final = 0.2
HTTP_TIMEOUT_SECONDS: Final = 5.0


class LocalLLM:
    def __init__(self, runtime_dir: Path = Path("runtime"), temperature: float = 0.0, max_tokens: int | None = None) -> None:
        self.runtime_dir = runtime_dir
        self.temperature = temperature
        self.max_tokens = max_tokens
        self._server_process: subprocess.Popen[str] | None = None
        self._server_url: str | None = None

    def available(self) -> bool:
        model_exists = self._gguf_model() is not None
        return self._ollama_exe().exists() or model_exists and (
            self._llama_server_exe().exists() or self._llama_cli_exe().exists()
        )

    def close(self) -> None:
        process = self._server_process
        self._server_process = None
        self._server_url = None
        if process is None or process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)

    def extract_json(self, text: str) -> dict[str, object] | None:
        if not self.available():
            return None
        answer = self._complete(self._prompt(text[:7000]), max_tokens=512)
        return _parse_json(answer) if answer else None

    def ask(self, question: str, context: str) -> str | None:
        if not self.available():
            return None
        return self._complete(_chat_prompt(question, context[:9000]), max_tokens=768)


    def _complete(self, prompt: str, max_tokens: int) -> str | None:
        actual_max_tokens = self.max_tokens if self.max_tokens is not None else max_tokens
        if self._llama_server_exe().exists() and self._gguf_model() is not None:
            server_result = self._run_llama_server_text(prompt, actual_max_tokens)
            if server_result is not None:
                return server_result
        if self._llama_cli_exe().exists() and self._gguf_model() is not None:
            return self._run_llama_cli_text(prompt, actual_max_tokens)
        if self._ollama_exe().exists():
            return self._run_ollama_text(prompt)
        return None

    def _ollama_exe(self) -> Path:
        return self.runtime_dir / "ollama" / "ollama.exe"

    def _llama_cli_exe(self) -> Path:
        return self.runtime_dir / "llama-bin" / "llama-cli.exe"

    def _llama_server_exe(self) -> Path:
        return self.runtime_dir / "llama-bin" / "llama-server.exe"

    def _gguf_model(self) -> Path | None:
        models_dir = self.runtime_dir / "models"
        candidates = sorted(models_dir.glob("*.gguf"))
        return candidates[0] if candidates else None

    def _run_llama_server_text(self, prompt: str, max_tokens: int) -> str | None:
        if not self._ensure_server():
            return None
        server_url = self._server_url
        if server_url is None:
            return None
        payload = json.dumps(
            {
                "model": "local",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": self.temperature,
                "max_tokens": max_tokens,
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            f"{server_url}/v1/chat/completions",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            response = urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS)
            return _parse_server_text(response.read())
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            return None

    def _ensure_server(self) -> bool:
        if self._server_process is not None and self._server_process.poll() is None and self._server_url is not None:
            return True
        model = self._gguf_model()
        if model is None:
            return False
        port = _free_port()
        self._server_url = f"http://127.0.0.1:{port}"
        try:
            self._server_process = subprocess.Popen(
                [
                    str(self._llama_server_exe()),
                    "-m",
                    str(model),
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(port),
                    "--ctx-size",
                    "4096",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                text=True,
            )
        except OSError:
            self._server_process = None
            self._server_url = None
            return False
        atexit.register(self.close)
        return self._wait_for_health()

    def _wait_for_health(self) -> bool:
        deadline = time.monotonic() + SERVER_STARTUP_SECONDS
        while time.monotonic() < deadline:
            process = self._server_process
            if process is None or process.poll() is not None or self._server_url is None:
                return False
            try:
                request = urllib.request.Request(f"{self._server_url}/health", method="GET")
                urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS).read()
                return True
            except (urllib.error.URLError, TimeoutError):
                time.sleep(SERVER_POLL_SECONDS)
        return False

    def _run_llama_cli_text(self, prompt: str, max_tokens: int) -> str | None:
        model = self._gguf_model()
        if model is None:
            return None
        with tempfile.NamedTemporaryFile("w", suffix=".txt", encoding="utf-8", delete=False) as handle:
            handle.write(prompt)
            prompt_path = Path(handle.name)
        try:
            result = subprocess.run(
                [
                    str(self._llama_cli_exe()),
                    "-m",
                    str(model),
                    "--no-display-prompt",
                    "--single-turn",
                    "--temp",
                    str(self.temperature),
                    "-n",
                    str(max_tokens),
                    "-c",
                    "4096",
                    "-f",
                    str(prompt_path),
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=240,
                check=False,
            )
        finally:
            prompt_path.unlink(missing_ok=True)
        if result.returncode != 0:
            return None
        return _strip_ansi(result.stdout).strip()

    def _run_ollama_text(self, prompt: str) -> str | None:
        env = os.environ.copy()
        env["OLLAMA_MODELS"] = str(self.runtime_dir / "models" / "ollama")
        result = subprocess.run(
            [str(self._ollama_exe()), "run", "qwen2.5:1.5b-instruct", prompt],
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
            env=env,
        )
        if result.returncode != 0:
            return None
        return _strip_ansi(result.stdout).strip()

    @staticmethod
    def _prompt(text: str) -> str:
        # Character ceiling: 7000 chars balances local-LLM context window
        # constraints (4k ctx default) against sufficient body text for
        # 3-5 sentence trich_yeu generation.  Tested with Qwen2.5-1.5B
        # on 30+ Vietnamese legal texts; beyond ~7500 chars the model
        # begins dropping JSON structure on the 1.5B variant.
        return f"""
Bạn là công cụ trích xuất metadata văn bản pháp luật Việt Nam.
Đầu vào là một trang wiki markdown CHUẨN (có YAML frontmatter và các phần nội dung).

Chỉ trả về MỘT JSON object hợp lệ. TUYỆT ĐỐI KHÔNG markdown, không giải thích,
không suy luận dây chuyền (chain-of-thought). Không tự ý thêm dữ kiện ngoài văn bản.

Quy tắc:
- `so_van_ban`: số/ký hiệu văn bản, ví dụ "24/2018/QH14".
- `ten_van_ban`: tên chính thức của văn bản, ví dụ "Luật An ninh mạng".
- `co_quan_phat_hanh`: cơ quan ban hành văn bản (Quốc hội, Chính phủ, Bộ, UBND...).
   Không lấy định nghĩa trong điều khoản. Không lấy tên cơ quan từ chú thích, footer.
- `ngay_ban_hanh`: định dạng YYYY-MM-DD.
- `trich_yeu`: tóm tắt 3-5 câu tiếng Việt, súc tích, mô tả PHẠM VI VÀ NỘI DUNG CỐT LÕI của toàn văn bản.
   Không sao chép nguyên văn tiêu đề. Phải dựa trên toàn bộ nội dung văn bản, không chỉ phần mở đầu.

QUAN TRỌNG - Xác minh metadata:
- Đầu vào CÓ THỂ chứa metadata ứng viên (trong YAML frontmatter hoặc phần Metadata candidates).
  Bạn PHẢI đối chiếu metadata đó với nội dung thực tế của văn bản.
  Metadata ứng viên có thể sai hoặc lỗi thời — chỉ sao chép nếu được xác nhận trong nội dung.
- Nếu không tìm thấy bằng chứng xác nhận trong văn bản, để null cho trường đó.
- TUYỆT ĐỐI KHÔNG ĐOÁN. Nếu không tự tin về một trường, để null.

JSON schema (chỉ trả về schema này, không gì khác):
{{
  "so_van_ban": string|null,
  "ten_van_ban": string|null,
  "co_quan_phat_hanh": string|null,
  "ngay_ban_hanh": string|null,
  "loai_van_ban": string|null,
  "trich_yeu": string|null
}}

TEXT:
{text}
""".strip()


def _strip_ansi(output: str) -> str:
    return re.sub(r"\x1b\[[0-9;]*m", "", output)


def _parse_json(output: str) -> dict[str, object] | None:
    cleaned = _strip_ansi(output)
    matches = re.findall(r"\{[\s\S]*?\}", cleaned)
    for candidate in reversed(matches):
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def _parse_server_text(raw: bytes) -> str | None:
    payload = json.loads(raw.decode("utf-8"))
    try:
        content = payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        return None
    return content.strip() if isinstance(content, str) else None


def _parse_server_response(raw: bytes) -> dict[str, object] | None:
    content = _parse_server_text(raw)
    return _parse_json(content) if content else None


def _chat_prompt(question: str, context: str) -> str:
    return f"""
Ban la tro ly hoi dap van ban phap luat Viet Nam.
Chi tra loi dua tren NGUON WIKI duoc cung cap. Neu khong thay thong tin trong nguon, noi ro: "Khong thay thong tin trong nguon.".
Tra loi ngan gon, bang tieng Viet, khong bia them.

CAU HOI:
{question}

NGUON WIKI:
{context}
""".strip()


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])
