"""Summary Agent: turns research notes into a concise, cited Markdown answer."""

from __future__ import annotations

import json
import os

from agent_server import BaseAgent, pause_for_demo
from common import extract_message_text, new_id
from runtime import configured_runtime


class SummaryAgent(BaseAgent):
    slug = "summary"

    def __init__(self, port: int = 8002):
        super().__init__(port, {
            "name": "Summary Agent",
            "description": "Synthesizes research notes into a concise Markdown answer.",
            "url": f"http://127.0.0.1:{port}",
            "version": "0.1.0",
            "capabilities": {"streaming": False, "pushNotifications": False},
            "skills": [{"id": "synthesize-notes", "name": "Synthesize notes", "description": "Produce a structured answer with explicit evidence boundaries."}],
            "defaultInputModes": ["text"],
            "defaultOutputModes": ["text"],
            "metadata": {
                "runtime": os.environ.get("A2A_RUNTIME", "mock"),
                "memory": "report-write-by-orchestrator",
            },
        })

    def process(self, task_id: str, params: dict) -> None:
        try:
            self.store.update(task_id, "working", "正在整理研究结果")
            pause_for_demo()
            if self.store.is_canceled(task_id):
                return
            text = extract_message_text(params)
            try:
                request = json.loads(text)
            except json.JSONDecodeError:
                request = {"topic": "研究主题", "research_markdown": text}
            topic = str(request.get("topic", "研究主题"))
            notes = str(request.get("research_markdown", "")).strip()
            evidence_status = str(request.get("evidence_status", "supported"))
            # This deterministic template keeps the demo usable without an API key.
            body = notes or "未收到研究资料。"
            fallback = "\n".join([
                f"# {topic}",
                "",
                "## 结论摘要",
                "本 Demo 已通过 A2A 将主题交给研究 Agent，再由总结 Agent 汇总。以下内容来自研究 Agent 返回的 Artifact。",
                "",
                "## 研究资料",
                body,
                "",
                "## 边界说明",
                "当前使用本地模拟资料，未连接互联网或真实大模型；接入 Pi/UniPi 时，应在此处保留工具调用、权限和来源审计信息。",
            ])
            if evidence_status == "insufficient":
                # Do not spend a model call or let a model elaborate unrelated material
                # when the research agent found no matching evidence.
                output_text = body
                runtime_name = "host-guard"
                runtime_details = {"mode": "no-evidence-guard"}
            else:
                runtime_result = configured_runtime().run(
                    "你是总结 Agent。请基于以下研究资料，用中文输出一份结构清晰、克制准确的 Markdown 报告。保留来源路径，不要虚构未提供的事实。\n\n" + body,
                    fallback,
                    cancel_check=lambda: self.store.is_canceled(task_id),
                )
                output_text = runtime_result.text
                runtime_name = runtime_result.runtime
                runtime_details = runtime_result.details
            artifact = {"artifactId": new_id("artifact"), "name": "final-report.md", "parts": [{"kind": "text", "text": output_text}], "metadata": {"runtime": runtime_name, "pi": runtime_details, "evidenceStatus": evidence_status}}
            self.store.add_artifact(task_id, artifact)
            self.store.update(task_id, "completed", f"已生成最终 Markdown 报告（runtime={runtime_name}）")
        except Exception as exc:
            self.store.update(task_id, "failed", str(exc))


if __name__ == "__main__":
    SummaryAgent().run()
