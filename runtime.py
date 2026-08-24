"""Optional internal Agent runtime adapters.

The demo stays dependency-free by default. When Pi is installed, setting
``A2A_RUNTIME=pi`` or ``A2A_RUNTIME=unipi`` enables the Pi JSONL CLI adapter.
UniPi is a Pi package, so the same process is the correct integration point.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional


@dataclass
class RuntimeResult:
    text: str
    runtime: str
    details: Dict[str, Any]


class RuntimeAdapter:
    name = "unknown"

    def run(self, prompt: str, fallback: str, cancel_check: Optional[Callable[[], bool]] = None) -> RuntimeResult:
        raise NotImplementedError


class MockRuntime(RuntimeAdapter):
    name = "mock"

    def run(self, prompt: str, fallback: str, cancel_check: Optional[Callable[[], bool]] = None) -> RuntimeResult:
        return RuntimeResult(text=fallback, runtime=self.name, details={"mode": "deterministic-mock"})


class RuntimeCanceled(RuntimeError):
    """Raised when a running runtime process is terminated by task cancellation."""


class PiCliRuntime(RuntimeAdapter):
    """Call Pi's documented non-interactive JSON event stream."""

    def __init__(self, label: str = "pi") -> None:
        self.name = label
        configured = os.environ.get("PI_BIN", "pi")
        self.binary = configured if os.path.isabs(configured) else shutil.which(configured)
        if not self.binary:
            raise RuntimeError(
                "Pi runtime requested but the 'pi' command was not found. "
                "Install Pi with Node.js >= 22.19, or unset A2A_RUNTIME."
            )
        self.timeout = int(os.environ.get("PI_TIMEOUT_SECONDS", "180"))

    def run(self, prompt: str, fallback: str, cancel_check: Optional[Callable[[], bool]] = None) -> RuntimeResult:
        # A2A hands Pi the research context as text. Disable Pi's coding tools
        # and discovered extensions here so the model cannot wander into local
        # file/memory operations or let an extension alter the response shape.
        command = [
            self.binary,
            "--mode", "json",
            "-p",
            "--no-session",
            "--no-approve",
            "--no-tools",
            "--no-extensions",
            "--no-skills",
            "--no-prompt-templates",
            "--no-context-files",
            "--thinking", "off",
        ]
        # The live demo is configured for the user's selected DeepSeek model;
        # PI_MODEL can override it without putting credentials in source.
        # Flash is the responsive default for a live demo; PI_MODEL can select
        # deepseek/deepseek-v4-pro when answer quality matters more than latency.
        model = os.environ.get("PI_MODEL", "deepseek/deepseek-v4-flash").strip()
        if model:
            command.extend(["--model", model])
        command.append(prompt)
        started = time.monotonic()
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        stdout = ""
        stderr = ""
        while True:
            if cancel_check and cancel_check():
                self._terminate(process)
                raise RuntimeCanceled("Pi canceled")
            if time.monotonic() - started >= self.timeout:
                self._terminate(process)
                raise RuntimeError(f"Pi timed out after {self.timeout}s")
            try:
                stdout, stderr = process.communicate(timeout=0.1)
                break
            except subprocess.TimeoutExpired:
                continue
        if process.returncode != 0:
            detail = (stderr or stdout or "Pi exited with an error").strip()
            raise RuntimeError(detail[-1200:])
        text = self._assistant_text(stdout)
        if not text:
            raise RuntimeError("Pi returned no assistant text")
        return RuntimeResult(text=text, runtime=self.name, details=self._telemetry(stdout, time.monotonic() - started))

    @staticmethod
    def _terminate(process: subprocess.Popen) -> None:
        process.terminate()
        try:
            process.communicate(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate()

    @staticmethod
    def _assistant_text(stdout: str) -> str:
        chunks = []
        for line in stdout.splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("type") != "message_end":
                continue
            message = event.get("message") or {}
            if message.get("role") != "assistant":
                continue
            for item in message.get("content") or []:
                if isinstance(item, dict) and item.get("type") == "text" and isinstance(item.get("text"), str):
                    chunks.append(item["text"])
        return "\n".join(chunks).strip()

    @staticmethod
    def _telemetry(stdout: str, elapsed: float) -> Dict[str, Any]:
        counts: Dict[str, int] = {}
        model = ""
        provider = ""
        usage: Dict[str, Any] = {}
        for line in stdout.splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            event_type = event.get("type")
            if isinstance(event_type, str):
                counts[event_type] = counts.get(event_type, 0) + 1
            message = event.get("message") or {}
            if isinstance(message, dict) and message.get("role") == "assistant":
                model = str(message.get("model") or model)
                provider = str(message.get("provider") or provider)
                if isinstance(message.get("usage"), dict):
                    usage = message["usage"]
        return {
            "model": model,
            "provider": provider,
            "durationMs": round(elapsed * 1000),
            "eventCounts": counts,
            "usage": usage,
            "tools": "disabled",
        }


def configured_runtime() -> RuntimeAdapter:
    mode = os.environ.get("A2A_RUNTIME", "mock").strip().lower()
    if mode in {"", "mock"}:
        return MockRuntime()
    if mode in {"pi", "unipi"}:
        return PiCliRuntime(mode)
    if mode == "auto":
        return PiCliRuntime("pi") if shutil.which(os.environ.get("PI_BIN", "pi")) else MockRuntime()
    raise RuntimeError(f"Unsupported A2A_RUNTIME={mode!r}; use mock, pi, unipi, or auto")
