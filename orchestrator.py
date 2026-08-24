"""Orchestrator: public API and A2A client for the local demo."""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from common import TaskStore, new_id, now_iso, read_json, write_json
from memory import MemoryStore


ROOT = Path(__file__).resolve().parent


class TaskCanceled(Exception):
    """Internal control flow used when a user cancels the orchestration task."""


def http_json(method: str, url: str, payload=None):
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


class Orchestrator:
    def __init__(self, port: int = 8000, research_url: str = "http://127.0.0.1:8001", summary_url: str = "http://127.0.0.1:8002"):
        self.port = port
        self.research_url = research_url
        self.summary_url = summary_url
        self.store = TaskStore()
        self.memory = MemoryStore()

    def cards(self):
        cards = []
        for url in (self.research_url, self.summary_url):
            try:
                cards.append(http_json("GET", f"{url}/.well-known/agent-card.json"))
            except Exception as exc:
                cards.append({"url": url, "error": str(exc)})
        return cards

    def submit(self, topic: str, retry_of: str = ""):
        task_id = new_id("orchestrator")
        memory_hits = self.memory.search(topic)
        context = {"topic": topic, "memoryHits": memory_hits}
        if retry_of:
            context["retryOf"] = retry_of
        self.store.create(task_id, context)
        self.store.add_event(task_id, "memoryEvents", {"operation": "search", "query": topic, "hitCount": len(memory_hits), "hits": [{"id": item["id"], "topic": item["topic"], "score": item["score"]} for item in memory_hits]})
        threading.Thread(target=self.run_task, args=(task_id, topic), daemon=True).start()
        return self.store.snapshot(task_id)

    def cancel(self, task_id: str):
        task = self.store.snapshot(task_id)
        self.store.cancel(task_id)
        context = task.get("context") or {}
        children = (("researchTaskId", self.research_url), ("summaryTaskId", self.summary_url))
        for key, base_url in children:
            child_id = context.get(key)
            if not child_id:
                continue
            try:
                http_json("POST", f"{base_url}/a2a/tasks/{child_id}/cancel", {})
            except Exception:
                # The parent cancellation remains authoritative if a child has already exited.
                pass
        self.store.add_event(task_id, "protocol", {
            "timestamp": now_iso(),
            "phase": "task/cancel",
            "direction": "outbound",
            "endpoint": "/api/tasks/{id}/cancel",
            "payload": {"taskId": task_id, "childTasks": {key: (context.get(key) or None) for key, _ in children}},
        })
        return self.store.snapshot(task_id)

    def retry(self, task_id: str):
        task = self.store.snapshot(task_id)
        state = task["status"]["state"]
        if state not in {"failed", "canceled"}:
            raise ValueError("只有 failed 或 canceled 任务可以重试")
        topic = str((task.get("context") or {}).get("topic", "")).strip()
        if not topic:
            raise ValueError("原任务缺少研究主题")
        return self.submit(topic, retry_of=task_id)

    @staticmethod
    def _protocol_payload(payload):
        """Keep raw protocol inspection useful without duplicating huge reports."""
        copied = json.loads(json.dumps(payload, ensure_ascii=False))
        parts = (((copied.get("params") or {}).get("message") or {}).get("parts") or []) if isinstance(copied, dict) else []
        for part in parts:
            if isinstance(part, dict) and isinstance(part.get("text"), str) and len(part["text"]) > 1400:
                part["text"] = part["text"][:1400] + "… [truncated for protocol view]"
        return copied

    def record_protocol(self, task_id: str, phase: str, direction: str, endpoint: str, payload) -> None:
        self.store.add_event(task_id, "protocol", {"timestamp": now_iso(), "phase": phase, "direction": direction, "endpoint": endpoint, "payload": self._protocol_payload(payload)})

    def run_task(self, task_id: str, topic: str):
        try:
            self.ensure_active(task_id)
            for role, url in (("research", self.research_url), ("summary", self.summary_url)):
                self.ensure_active(task_id)
                try:
                    card = http_json("GET", f"{url}/.well-known/agent-card.json")
                    self.record_protocol(task_id, "agent-card", "inbound", f"{url}/.well-known/agent-card.json", {"agent": role, "card": card})
                except Exception as exc:
                    self.record_protocol(task_id, "agent-card", "error", f"{url}/.well-known/agent-card.json", {"agent": role, "error": str(exc)})
            self.store.update(task_id, "working", "编排 Agent 正在调用研究 Agent")
            memory_hits = self.store.snapshot(task_id)["context"].get("memoryHits", [])
            request = {"jsonrpc": "2.0", "id": new_id("rpc"), "method": "message/send", "params": {"message": {"messageId": new_id("message"), "role": "user", "parts": [{"kind": "text", "text": json.dumps({"topic": topic, "memory_context": memory_hits}, ensure_ascii=False)}]}}}
            self.record_protocol(task_id, "research-message/send", "outbound", f"{self.research_url}/a2a", request)
            response = http_json("POST", f"{self.research_url}/a2a", request)
            self.record_protocol(task_id, "research-task-accepted", "inbound", f"{self.research_url}/a2a", response)
            research_id = response["result"]["task"]["id"]
            self.store.merge_context(task_id, {"researchTaskId": research_id})
            self.store.update(task_id, "working", f"研究 Agent 已接单：{research_id}")
            research = self.wait_for_agent(task_id, self.research_url, research_id)
            if research["status"]["state"] != "completed":
                if research["status"]["state"] == "canceled":
                    raise TaskCanceled()
                raise RuntimeError(research["status"].get("message", "研究 Agent 失败"))
            research_text = research["artifacts"][0]["parts"][0]["text"]
            research_artifact = research["artifacts"][0]
            research_metadata = research_artifact.get("metadata") or {}
            self.store.add_artifact(task_id, {**research_artifact, "metadata": {**(research_artifact.get("metadata") or {}), "fromTask": research_id}})
            for event in research.get("toolEvents", []):
                compact = {key: value for key, value in event.items() if key != "output"}
                output = event.get("output") or {}
                compact["output"] = {"sourceCount": output.get("sourceCount", 0), "paths": [source.get("path") for source in output.get("sources", [])], "reason": output.get("reason")}
                self.store.add_event(task_id, "toolEvents", compact)
            self.store.update(task_id, "working", "研究完成，正在调用总结 Agent")
            self.ensure_active(task_id)
            summary_request = {"jsonrpc": "2.0", "id": new_id("rpc"), "method": "message/send", "params": {"message": {"messageId": new_id("message"), "role": "user", "parts": [{"kind": "text", "text": json.dumps({"topic": topic, "research_markdown": research_text, "evidence_status": research_metadata.get("evidenceStatus", "supported")}, ensure_ascii=False)}]}}}
            self.record_protocol(task_id, "summary-message/send", "outbound", f"{self.summary_url}/a2a", summary_request)
            summary_response = http_json("POST", f"{self.summary_url}/a2a", summary_request)
            self.record_protocol(task_id, "summary-task-accepted", "inbound", f"{self.summary_url}/a2a", summary_response)
            summary_id = summary_response["result"]["task"]["id"]
            self.store.merge_context(task_id, {"summaryTaskId": summary_id})
            self.store.update(task_id, "working", f"总结 Agent 已接单：{summary_id}")
            summary = self.wait_for_agent(task_id, self.summary_url, summary_id)
            if summary["status"]["state"] != "completed":
                if summary["status"]["state"] == "canceled":
                    raise TaskCanceled()
                raise RuntimeError(summary["status"].get("message", "总结 Agent 失败"))
            self.ensure_active(task_id)
            final_artifact = summary["artifacts"][0]
            final_text = final_artifact["parts"][0]["text"]
            memory_record = self.memory.store(topic, final_text)
            self.store.add_event(task_id, "memoryEvents", {"operation": "store", "memory": {"id": memory_record["id"], "topic": memory_record["topic"], "updatedAt": memory_record["updatedAt"]}, "sourceTask": summary_id})
            self.store.add_artifact(task_id, {**final_artifact, "metadata": {**(final_artifact.get("metadata") or {}), "fromTask": summary_id, "memoryId": memory_record["id"]}})
            self.record_protocol(task_id, "artifact-delivery", "inbound", f"{self.summary_url}/a2a/tasks/{summary_id}", {"taskId": summary_id, "artifacts": [{"name": final_artifact.get("name"), "artifactId": final_artifact.get("artifactId"), "metadata": final_artifact.get("metadata", {})}]})
            self.store.update(task_id, "completed", "A2A 链路完成")
        except TaskCanceled:
            # cancel() already records the terminal state and downstream cancellation.
            return
        except Exception as exc:
            self.store.update(task_id, "failed", f"调用链失败：{exc}")

    def ensure_active(self, task_id: str):
        if self.store.is_canceled(task_id):
            raise TaskCanceled()

    def wait_for_agent(self, parent_task_id: str, base_url: str, task_id: str):
        # A real model-backed Agent can take longer than the local mock path.
        # Keep polling well inside Pi's 90s subprocess timeout.
        for _ in range(1200):
            if self.store.is_canceled(parent_task_id):
                try:
                    http_json("POST", f"{base_url}/a2a/tasks/{task_id}/cancel", {})
                except Exception:
                    pass
                raise TaskCanceled()
            task = http_json("GET", f"{base_url}/a2a/tasks/{task_id}")["task"]
            if task["status"]["state"] in {"completed", "failed", "canceled"}:
                return task
            time.sleep(0.1)
        raise TimeoutError(f"agent task timeout: {task_id}")

    def serve(self):
        owner = self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, fmt, *args):
                return

            def do_GET(self):
                parsed = urlparse(self.path)
                path = parsed.path
                if path == "/api/health":
                    return write_json(self, {"ok": True, "service": "orchestrator"})
                if path == "/api/agents":
                    return write_json(self, {"agents": owner.cards()})
                if path.startswith("/api/tasks/") and path.endswith("/events"):
                    task_id = path.split("/")[-2]
                    if not owner.store.has(task_id):
                        return write_json(self, {"error": "task_not_found"}, 404)
                    try:
                        query_cursor = int((parse_qs(parsed.query).get("after") or ["0"])[0])
                    except ValueError:
                        query_cursor = 0
                    try:
                        header_cursor = int(self.headers.get("Last-Event-ID", query_cursor))
                    except ValueError:
                        header_cursor = query_cursor
                    cursor = max(query_cursor, header_cursor)
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                    self.send_header("Cache-Control", "no-cache")
                    self.send_header("Connection", "keep-alive")
                    self.send_header("X-Accel-Buffering", "no")
                    self.end_headers()
                    try:
                        while True:
                            events = owner.store.wait_events(task_id, cursor, timeout=15.0)
                            if not events:
                                self.wfile.write(b": keepalive\n\n")
                                self.wfile.flush()
                                continue
                            for event in events:
                                payload = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
                                self.wfile.write(f"id: {event['seq']}\ndata: {payload}\n\n".encode("utf-8"))
                                self.wfile.flush()
                                cursor = event["seq"]
                            state = events[-1]["task"]["status"]["state"]
                            if state in {"completed", "failed", "canceled"}:
                                return
                    except (BrokenPipeError, ConnectionResetError):
                        return
                if path.startswith("/api/tasks/"):
                    task_id = path.rsplit("/", 1)[-1]
                    if not owner.store.has(task_id):
                        return write_json(self, {"error": "task_not_found"}, 404)
                    return write_json(self, {"task": owner.store.snapshot(task_id)})
                if path in {"/", "/index.html"}:
                    body = (ROOT / "frontend" / "index.html").read_bytes()
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                return write_json(self, {"error": "not_found"}, 404)

            def do_POST(self):
                path = urlparse(self.path).path
                if path.startswith("/api/tasks/"):
                    parts = path.strip("/").split("/")
                    if len(parts) == 4 and parts[0] == "api" and parts[1] == "tasks" and parts[3] == "cancel":
                        task_id = parts[2]
                        if not owner.store.has(task_id):
                            return write_json(self, {"error": "task_not_found"}, 404)
                        return write_json(self, {"task": owner.cancel(task_id)}, 200)
                    if len(parts) == 4 and parts[0] == "api" and parts[1] == "tasks" and parts[3] == "retry":
                        task_id = parts[2]
                        if not owner.store.has(task_id):
                            return write_json(self, {"error": "task_not_found"}, 404)
                        try:
                            return write_json(self, {"task": owner.retry(task_id)}, 202)
                        except ValueError as exc:
                            return write_json(self, {"error": "retry_not_allowed", "detail": str(exc)}, 409)
                if path != "/api/tasks":
                    return write_json(self, {"error": "not_found"}, 404)
                try:
                    payload = read_json(self)
                    topic = str(payload.get("topic", "")).strip()
                    if not topic:
                        return write_json(self, {"error": "topic_required"}, 422)
                    return write_json(self, {"task": owner.submit(topic)}, 202)
                except Exception as exc:
                    return write_json(self, {"error": "invalid_request", "detail": str(exc)}, 400)

        return ThreadingHTTPServer(("127.0.0.1", self.port), Handler)
