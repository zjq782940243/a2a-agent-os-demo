"""Small shared helpers for the zero-dependency A2A demo."""

from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False).encode("utf-8")


def read_json(handler) -> Dict[str, Any]:
    length = int(handler.headers.get("Content-Length", "0"))
    raw = handler.rfile.read(length) if length else b"{}"
    return json.loads(raw.decode("utf-8"))


def write_json(handler, value: Any, status: int = 200) -> None:
    body = json_bytes(value)
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def extract_message_text(params: Dict[str, Any]) -> str:
    """Extract concatenated text parts from an A2A Message object."""
    message = params.get("message") or {}
    parts = message.get("parts") or []
    texts = []
    for part in parts:
        if isinstance(part, dict) and isinstance(part.get("text"), str):
            texts.append(part["text"])
    return "\n".join(texts).strip()


class TaskStore:
    """Thread-safe in-memory Task store; enough for a local demo."""

    def __init__(self) -> None:
        self._tasks: Dict[str, Dict[str, Any]] = {}
        self._events: Dict[str, list] = {}
        self._lock = threading.RLock()
        self._events_ready = threading.Condition(self._lock)

    def create(self, task_id: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        task = {
            "id": task_id,
            "status": {"state": "submitted", "timestamp": now_iso()},
            "artifacts": [],
            "history": [{"state": "submitted", "message": "任务已创建", "timestamp": now_iso()}],
            "context": context or {},
            "protocol": [],
            "toolEvents": [],
            "memoryEvents": [],
        }
        with self._lock:
            self._tasks[task_id] = task
            self._events[task_id] = []
            self._emit_locked(task_id, "task.created")
        return self.snapshot(task_id)

    def update(self, task_id: str, state: str, message: str = "") -> Dict[str, Any]:
        with self._lock:
            if self._tasks[task_id]["status"]["state"] == "canceled" and state != "canceled":
                return self.snapshot(task_id)
            task = self._tasks[task_id]
            event = {"state": state, "message": message, "timestamp": now_iso()}
            task["status"] = {"state": state, "timestamp": event["timestamp"], "message": message}
            task["history"].append(event)
            self._emit_locked(task_id, f"task.{state}")
        return self.snapshot(task_id)

    def add_artifact(self, task_id: str, artifact: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            if self._tasks[task_id]["status"]["state"] == "canceled":
                return self.snapshot(task_id)
            self._tasks[task_id]["artifacts"].append(artifact)
            self._emit_locked(task_id, "artifact.added")
        return self.snapshot(task_id)

    def add_event(self, task_id: str, collection: str, event: Dict[str, Any]) -> Dict[str, Any]:
        if collection not in {"protocol", "toolEvents", "memoryEvents"}:
            raise ValueError(f"unsupported task event collection: {collection}")
        with self._lock:
            self._tasks[task_id][collection].append(event)
            self._emit_locked(task_id, f"{collection}.added")
        return self.snapshot(task_id)

    def cancel(self, task_id: str, message: str = "任务已取消") -> Dict[str, Any]:
        with self._lock:
            task = self._tasks[task_id]
            state = task["status"]["state"]
            if state in {"completed", "failed", "canceled"}:
                return self.snapshot(task_id)
            timestamp = now_iso()
            task["status"] = {"state": "canceled", "timestamp": timestamp, "message": message}
            task["history"].append({"state": "canceled", "message": message, "timestamp": timestamp})
            self._emit_locked(task_id, "task.canceled")
            return self.snapshot(task_id)

    def merge_context(self, task_id: str, values: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            self._tasks[task_id]["context"].update(values)
            self._emit_locked(task_id, "context.updated")
        return self.snapshot(task_id)

    def is_canceled(self, task_id: str) -> bool:
        with self._lock:
            return self._tasks[task_id]["status"]["state"] == "canceled"

    def events_since(self, task_id: str, cursor: int = 0) -> list:
        with self._lock:
            return json.loads(json.dumps([event for event in self._events[task_id] if event["seq"] > cursor], ensure_ascii=False))

    def wait_events(self, task_id: str, cursor: int = 0, timeout: float = 15.0) -> list:
        with self._events_ready:
            events = self.events_since(task_id, cursor)
            if events:
                return events
            self._events_ready.wait(timeout)
            return self.events_since(task_id, cursor)

    def _emit_locked(self, task_id: str, event_type: str) -> None:
        events = self._events[task_id]
        task = self._tasks[task_id]
        events.append({
            "seq": len(events) + 1,
            "type": event_type,
            "timestamp": now_iso(),
            "task": json.loads(json.dumps(task, ensure_ascii=False)),
        })
        self._events_ready.notify_all()

    def snapshot(self, task_id: str) -> Dict[str, Any]:
        with self._lock:
            return json.loads(json.dumps(self._tasks[task_id], ensure_ascii=False))

    def has(self, task_id: str) -> bool:
        with self._lock:
            return task_id in self._tasks
