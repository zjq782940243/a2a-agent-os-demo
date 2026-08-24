# A2A 多 Agent 研究 Demo

这是一个默认不依赖第三方 Python 包、不需要 API Key 的最小闭环，用来演示：

`用户 -> 编排 Agent -> A2A -> 研究 Agent -> source_search -> Pi -> A2A -> 总结 Agent -> Pi -> Artifact`

## 运行

```bash
cd a2a-demo
python3 start_demo.py
```

打开 <http://127.0.0.1:8000>，提交一个研究主题。页面通过 SSE 订阅编排 Task 的实时事件，展示 `submitted -> working -> completed/failed/canceled`、事件序号和最终 Markdown。演示时可以设置 `A2A_DEMO_PAUSE_SECONDS=1.5` 放慢本地阶段，方便点击 Cancel 观察取消链路。

## Vercel 在线版

仓库包含 `api/[...path].js` Vercel 适配层。它复用页面使用的 `/api/tasks`、Task、Artifact 和 Memory 契约，把三个本地 Python 服务压缩为一个可分享的 Serverless 函数。由于 Vercel 函数实例不保证跨请求共享内存，线上创建任务响应会附带 `liveEvents` 事件快照，页面据此展示完整调用链；本地 Python 版才提供可断线重连的真实 SSE TaskStore。线上默认使用确定性本地资料适配器，不需要 API Key；这不是把 Pi 进程运行在 Vercel 上。需要真实 Pi + DeepSeek 时，请使用下面的本地启动脚本或部署到支持长期进程的 Railway、Render、Fly.io 等平台。

部署步骤：

```bash
git clone <your-repository-url>
cd a2a-demo
npx vercel --prod
```

Vercel 环境变量不要写入仓库；真实密钥只应配置在 Vercel Project Settings 的 Environment Variables 中，并且仅在线上适配层确实需要时启用。

## 可选接入 Pi / UniPi

当前环境默认是 `A2A_RUNTIME=mock`。如果安装了 Pi（官方仓库要求 Node.js >= 22.19），可以切换总结 Agent 的内部运行时：

```bash
export A2A_RUNTIME=pi
# 可选：指定 Pi 可执行文件和模型
export PI_BIN=/path/to/pi
export PI_MODEL=deepseek/deepseek-v4-flash
# 只在当前进程注入，不要写入项目文件或提交到 Git
export DEEPSEEK_API_KEY='your-deepseek-api-key'
python3 start_demo.py
```

UniPi 是 Pi package/extension，使用相同的 CLI 适配方式：

```bash
pi install npm:@pi-unipi/unipi
export A2A_RUNTIME=unipi
export PI_BIN=/path/to/pi
export DEEPSEEK_API_KEY='your-deepseek-api-key'
python3 start_demo.py
```

本次已验证的真实 DeepSeek + UniPi 启动方式（密钥只从当前 shell 环境读取）：

```bash
export DEEPSEEK_API_KEY='your-deepseek-api-key'
./start_deepseek_demo.sh
```

脚本默认使用 `A2A_RUNTIME=pi`、`deepseek/deepseek-v4-flash` 和 `thinking=off`，也可以通过 `A2A_RUNTIME=unipi`、`PI_MODEL=...` 或 `PI_TIMEOUT_SECONDS=...` 覆盖。研究 Agent 与总结 Agent 都会在各自的任务处理线程中启动一次 Pi JSONL 会话。需要更强推理时可切换到 `deepseek/deepseek-v4-pro`，但响应时间会更长。

适配器位于 `runtime.py`，调用 Pi 的 `--mode json -p --no-session --no-approve --no-tools --no-extensions --no-skills --no-prompt-templates --no-context-files --thinking off`，只解析 `message_end` 中的 assistant 文本。这里仍然是 Pi 调用，但刻意关闭 UniPi 扩展和本地工具，避免研究任务触发文件扫描；UniPi 已安装，可在独立的工作流型 Agent 中再启用。没有 Pi、模型或凭据时不要设置该变量，Mock 模式仍可完整运行。Pi 默认没有文件、网络、进程和凭据隔离；接入真实环境前请放进容器或其他策略沙箱。

## 服务与接口

| 服务 | 端口 | 作用 |
| --- | ---: | --- |
| Orchestrator | 8000 | 对外页面和 API，串联两个 Agent |
| Research Agent | 8001 | `/.well-known/agent-card.json`、`POST /a2a`、`GET /a2a/tasks/{id}` |
| Summary Agent | 8002 | `/.well-known/agent-card.json`、`POST /a2a`、`GET /a2a/tasks/{id}` |

Agent 的 `POST /a2a` 使用 JSON-RPC 2.0 的 `message/send` 方法。返回的 Task 先是 `submitted`，后台处理后通过 Task 查询得到状态和 Artifact。这是 HTTP+JSON 的教学化子集，重点保留 A2A 的核心对象和生命周期。编排 Task 还会保留 Agent Card、`message/send`、Task 接受和 Artifact 传递的协议快照，页面可展开查看。

编排服务额外提供 `GET /api/tasks/{id}/events` 的 SSE 事件流；每条事件带 `id`、`type`、时间戳和最新 Task 快照，浏览器断线重连时可以使用 `Last-Event-ID` 继续。`POST /api/tasks/{id}/cancel` 会取消编排任务并尽力取消已经创建的下游 Task；`POST /api/tasks/{id}/retry` 只允许对 `failed` 或 `canceled` 任务重新创建一次编排 Task，并在新 Task context 中记录 `retryOf`。

研究 Agent 会调用受控的 `source_search` 工具，只读取 `data/sources/*.md`，并记录工具输入、来源路径、匹配度和耗时。没有匹配来源时不会回退返回无关文档，而是生成 `evidenceStatus=insufficient` 的证据边界 Artifact；Summary Agent 会进入 `host-guard`，不调用模型、不扩写无关内容。研究 Agent Card 会声明该工具以及“读取上下文记忆”的边界。编排 Agent 使用 SQLite 记忆适配器读取历史主题，并在任务完成后保存最终报告摘要；重复提交同一主题时，页面的 Memory search 事件会显示命中历史报告（例如 `hitCount=1`）。这是 UniPi 风格的可持久化 Memory Adapter，用来演示记忆边界，不声称当前 Pi 文本会话加载了 UniPi 扩展。当前 Task 状态仍保存在进程内存中，重启服务后任务列表会清空，但 SQLite 记忆会保留。

## 如何接入 Pi / UniPi

先保持 A2A 端点和 Artifact 契约不变，把 `tools.py` 的 `source_search()` 替换为真实 MCP/Web 搜索工具；当前 `research_agent.py` 和 `summary_agent.py` 都已提供可选 Pi 运行时。若要加载完整 UniPi 工作流，应增加独立的 UniPi Agent/Adapter，将其内部记忆、工作流和子 Agent 状态映射为 A2A Task，并把文件/文本映射为 Artifact。

当前取消是协作式的：Pi 子进程会收到终止信号，已完成的工具调用不会回滚；Task 状态和事件仍保存在进程内存中。生产化前至少补齐：认证与 Agent Card 信任、任务持久化、幂等键、工具沙箱、敏感信息脱敏、来源审计、断点续传和真正的 A2A 流式协议。
