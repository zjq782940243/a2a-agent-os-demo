"""Research Agent: searches local Markdown sources and returns an A2A Artifact."""

from __future__ import annotations

import json
import os
from pathlib import Path

from agent_server import BaseAgent, pause_for_demo
from common import extract_message_text, new_id
from runtime import configured_runtime
from tools import source_search


ROOT = Path(__file__).resolve().parent
SOURCE_DIR = ROOT / "data" / "sources"


class ResearchAgent(BaseAgent):
    slug = "research"

    def __init__(self, port: int = 8001):
        super().__init__(port, {
            "name": "Local Research Agent",
            "description": "Searches an approved local source set and produces cited research notes.",
            "url": f"http://127.0.0.1:{port}",
            "version": "0.1.0",
            "capabilities": {"streaming": False, "pushNotifications": False},
            "skills": [{"id": "local-source-search", "name": "Local source search", "description": "Find relevant Markdown sources and extract evidence."}],
            "defaultInputModes": ["text"],
            "defaultOutputModes": ["text"],
            "metadata": {
                "runtime": os.environ.get("A2A_RUNTIME", "mock"),
                "tools": ["source_search"],
                "memory": "context-read",
            },
        })

    def process(self, task_id: str, params: dict) -> None:
        try:
            self.store.update(task_id, "working", "正在检索本地资料")
            pause_for_demo()
            if self.store.is_canceled(task_id):
                return
            text = extract_message_text(params)
            try:
                request = json.loads(text)
            except json.JSONDecodeError:
                request = {"topic": text}
            topic = str(request.get("topic", "")).strip() or "Agent OS"
            tool_result = source_search(topic, SOURCE_DIR, limit=3)
            self.store.add_event(task_id, "toolEvents", tool_result)
            sources = tool_result["output"]["sources"]
            if not sources:
                artifact = {
                    "artifactId": new_id("artifact"),
                    "name": "research-notes.md",
                    "parts": [{"kind": "text", "text": "\n".join([
                        f"# 研究结果：{topic}",
                        "",
                        "## 证据状态",
                        "未在当前批准的本地资料范围内找到与该主题直接匹配的来源。",
                        "",
                        "## 检索范围",
                        "本次仅检索 `data/sources/*.md`；没有相关来源，因此不对该主题作事实性归纳。",
                        "",
                        "## 下一步",
                        "请补充相关资料，或接入 Web/MCP/企业知识库搜索工具后再继续研究。",
                    ])}],
                    "metadata": {
                        "sourceCount": 0,
                        "evidenceStatus": "insufficient",
                        "runtime": "host-guard",
                        "toolCalls": [{"toolCallId": tool_result["toolCallId"], "name": tool_result["name"], "durationMs": tool_result["durationMs"], "status": tool_result["status"]}],
                    },
                }
                self.store.add_artifact(task_id, artifact)
                self.store.update(task_id, "completed", "未找到相关来源，已停止无证据推理")
                return
            lines = [f"# 研究结果：{topic}", "", "> 资料范围：Demo 内置本地 Markdown；生产环境应替换为带权限和来源记录的搜索工具。", ""]
            for index, source in enumerate(sources, 1):
                lines.extend([f"## {index}. {Path(source['path']).stem}", f"来源：`{source['path']}`；匹配度：{source['score']}", "", source["content"], ""])
            memory_context = request.get("memory_context") or []
            if memory_context:
                lines.extend(["## 相关历史记忆", "", "以下内容来自 UniPi-style Memory Adapter，仅作为上下文，不替代本次资料检索：", ""])
                for memory in memory_context[:3]:
                    lines.extend([f"- `{memory.get('topic', 'unknown')}`：{memory.get('summary', '')[:600]}"])
            fallback = "\n".join(lines)
            runtime_result = configured_runtime().run(
                "你是研究 Agent。请仅依据下面提供的本地资料，围绕研究主题输出中文 Markdown 研究笔记。\n"
                "要求：保留每个资料的 source 路径；区分资料原文与归纳；不要补充资料中没有的事实；如果证据不足请明确写出。\n\n"
                + fallback,
                fallback,
                cancel_check=lambda: self.store.is_canceled(task_id),
            )
            artifact = {"artifactId": new_id("artifact"), "name": "research-notes.md", "parts": [{"kind": "text", "text": runtime_result.text}], "metadata": {"sourceCount": len(sources), "runtime": runtime_result.runtime, "pi": runtime_result.details, "toolCalls": [{"toolCallId": tool_result["toolCallId"], "name": tool_result["name"], "durationMs": tool_result["durationMs"], "status": tool_result["status"]}]}}
            self.store.add_artifact(task_id, artifact)
            self.store.update(task_id, "completed", f"已返回 {len(sources)} 个来源（runtime={runtime_result.runtime}）")
        except Exception as exc:
            self.store.update(task_id, "failed", str(exc))


if __name__ == "__main__":
    ResearchAgent().run()
