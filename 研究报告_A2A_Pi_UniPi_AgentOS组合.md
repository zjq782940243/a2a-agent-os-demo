# 研究结果：A2A、Pi、UniPi、Agent OS 如何组合

> 资料范围：Demo 内置本地 Markdown（`data/sources/` 与 `README.md`），另参考本项目 `runtime.py`、`*_agent.py` 等源码以印证说明文档。本报告不做任何超出资料的断言。

---

## 0. 元信息

本报告严格基于以下本地资料撰写。每个章节均区分**资料原文**（引述或忠实转述原始内容）与**归纳**（基于原文的分析推断）。凡是资料中未提及或证据不足的地方，会显式标注「资料未提及」或「归纳」。

引用源：

| 代号 | 路径 |
| --- | --- |
| S1 | `data/sources/a2a.md` |
| S2 | `data/sources/agent-os.md` |
| S3 | `data/sources/pi.md` |
| S4 | `data/sources/unipi.md` |
| S5 | `README.md`（a2a-demo 项目说明） |

> 说明：研究主题「A2A、Pi、UniPi、Agent OS」四者角色分散在上述资料中。`data/sources/` 目录下存在 `a2a.md`（S1）、`agent-os.md`（S2）、`pi.md`（S3）、`unipi.md`（S4）四份简短的定义性资料；`README.md`（S5）是 Demo 自身的说明文档，给出了三者如何在同一个最小闭环中组合的具体操作路径，对本题结论最为直接，故列为重点依据。

---

## 1. 各组件定位（基于资料原文）

### 1.1 A2A（Agent2Agent）
- **资料原文**（S1）：「A2A（Agent2Agent）定义 Agent 之间发现能力、发送消息、跟踪 Task 和交换 Artifact 的协议。Agent Card 描述服务能力；Task 可以经历 `submitted`、`working`、`completed` 或 `failed` 等状态；Artifact 承载文本、文件或结构化结果。」
- **归纳**：A2A 的核心被描述为「协议」，关注的是 Agent 之间的交互对象（Agent Card / Task / Artifact）与 Task 状态机，不涉及单个 Agent 内部如何运行。

### 1.2 Pi
- **资料原文**（S3）：「Pi 是一个偏底层、可编程的 Agent Harness/运行时。它负责模型对话、工具循环、上下文处理和扩展点；默认能力边界、沙箱和凭据隔离需要由宿主应用补齐。」
- **归纳**：Pi 被定性为「偏底层、可编程」的运行时/harness，承担的是**单个 Agent 内部**的模型对话与工具循环；文档明确指出它默认**不具备**能力边界、沙箱与凭据隔离，需由宿主应用补齐。

### 1.3 UniPi
- **资料原文**（S4）：「UniPi（公开资料中常见的 UniPi 项目）可作为 Pi 的工作站式扩展，强调记忆、工作流、压缩、子 Agent 等工程能力。它不是 A2A 协议实现；如果要让 UniPi 暴露为 A2A Agent，需要额外编写 Adapter，并明确工具权限和数据边界。」
- **归纳**：UniPi 被定位为「Pi 的工作站式扩展」，强调工程能力（记忆/工作流/压缩/子 Agent）；资料明确两点：它**不是** A2A 协议实现；若要作为 A2A Agent 暴露需额外写 Adapter，且要明确工具权限与数据边界。

### 1.4 Agent OS
- **资料原文**（S2）：「Agent OS 更适合被理解为一种组合式运行架构，而不是单一产品：它通常包含 Agent Runtime、工具与权限、记忆、任务调度、观测审计以及 Agent 间通信。A2A 解决跨 Agent 协作，MCP 或 Tool API 解决 Agent 调用外部工具。」
- **归纳**：Agent OS 被描述为「组合式运行架构」而非单一产品，其组成件包含运行时（Runtime）、工具权限、记忆、任务调度、观测审计与「Agent 间通信」。资料进一步给出分工：A2A 管跨 Agent 协作，MCP 或 Tool API 管 Agent 调用外部工具。

> **证据边界提醒**：四份源（S1–S4）均为简短的定义性描述，未提供架构图、参考实现或详细接口说明。除 S5 演示了 A2A + Pi + UniPi 的实际运行方式外，各层之间更细的耦合/数据流在当前资料中「未提及」。

---

## 2. 如何组合

### 2.1 各组件在分工中的位置（归纳）

把第 1 节的原文放在一起，可以得到一张相互不冲突的分工图：

- **对外协作（跨 Agent/层间）→ A2A**：承担 Agent 之间发现能力、发送消息、跟踪 Task、交换 Artifact（S1）。
- **Agent 单体内部运行时 → Pi**：承担模型对话、工具循环、上下文处理、扩展点（S3）。
- **在 Pi 之上叠加工程能力 → UniPi**：作为 Pi 的可选扩展，提供记忆、工作流等（S4）。
- **承载一切的「组合式运行架构」→ Agent OS**：可被理解为把上述运行时、工具权限、记忆、调度、观测审计与 Agent 间通信整合起来的环境（S2）。

> **归纳说明**：「外层是 Agent OS、中层是 A2A、内层是 Pi/UniPi 作为 Agent 内部运行时」这一分层顺序，是我综合四份资料的措辞推导出的结构，**并非任一资料显式写出**。资料只分别给出了各者职责和两两关系，未给出统一分层图，故以下路径均标注为归纳。

### 2.2 Demo 中给出的真实组合方式（S5，资料原文 + 归纳）

S5 描述了一个「默认不依赖第三方 Python 包、不需要 API Key」的最小闭环，数据流（S5 原文）：

```
用户 -> 编排 Agent -> 研究 Agent -> 总结 Agent -> Artifact
```

各服务接口分工（S5 原文）：
- Orchestrator `:8000`：对外页面和 API，串联两个 Agent。
- Research Agent `:8001` 与 Summary Agent `:8002`：均提供 `/.well-known/agent-card.json`、`POST /a2a`、`GET /a2a/tasks/{id}`。
- Agent 的 `POST /a2a` 使用 JSON-RPC 2.0 的 `message/send` 方法；返回的 Task 先为 `submitted`，后台处理后通过 Task 查询获得状态与 Artifact。

关于 Pi / UniPi 接入（S5 原文要点）：
- 默认 `A2A_RUNTIME=mock`；安装 Pi（要求 Node.js >= 22.19）后可切换总结 Agent 的内部运行时。
- 通过 `A2A_RUNTIME=pi`（或 `=unipi`）、`PI_BIN`、`PI_MODEL` 环境变量配置。
- UniPi 是 Pi 的 package/extension，使用相同的 CLI 适配方式（`pi install npm:@pi-unipi/unipi`）。
- 适配器位于 `runtime.py`，调用 Pi 的 `--mode json -p --no-session --no-approve --thinking off`，只解析 `message_end` 中的 assistant 文本。
- 「Pi 默认没有文件、网络、进程和凭据隔离；接入真实环境前请放进容器或其他策略沙箱。」
- 「研究 Agent 与总结 Agent 都会在各自的任务处理线程中启动一次 Pi JSONL 会话。」

**归纳**：这份文档展示的组合范式是**把 A2A 与 Pi/UniPi 解耦**——A2A 端点和 Artifact 契约保持固定（Agent Card + `POST /a2a` + Task 查询），Pi/UniPi 只作为某个 Agent（研究 Agent/总结 Agent）内部、用于生成结果的模型与工具循环运行时，通过 `runtime.py` 适配器以进程内子进程方式被调用。也就是说，「Pi 放在 Agent 内部，让 A2A 只承担跨 Agent 任务与结果传输」（S3）这一设计意图，在 S5 有具体落地示例。

> **源码印证（项目自身，非外部资料）**：`runtime.py` 中的 `PiCliRuntime` 在有 `PI_MODEL` 时将其加入命令行，无则回退默认模型（`deepseek/deepseek-v4-flash`），并仅从 `message_end` 事件里取 assistant 文本；`RuntimeAdapter` 接口在 mock/pi/unipi/auto 四种模式间切换。`research_agent.py`、`summary_agent.py` 均通过 `configured_runtime().run(prompt, fallback)` 使用该适配器。这些内容与 S5 描述一致。

### 2.3 若要把 UniPi 暴露为 A2A Agent（S4 + S5 归纳）

- S4 原文：UniPi「不是 A2A 协议实现；如果要让 UniPi 暴露为 A2A Agent，需要额外编写 Adapter，并明确工具权限和数据边界」。
- S5 原文（接入说明）：「先保持 A2A 端点和 Artifact 契约不变，把 `research_agent.py` 的 `process()` 替换为 Pi 的模型与工具循环；当前 `summary_agent.py` 已提供可选 Pi/UniPi 运行时。UniPi 需要更深的 Adapter 时，应将其内部 Task 状态映射为 A2A Task，并把文件/文本映射为 Artifact。」
- **归纳**：S4 与 S5 相互印证——要让 UniPi（或 Pi）作为 A2A Agent 对外暴露，需要一层 Adapter 做映射：内部任务状态 → A2A Task，文件/文本 → Artifact，同时保持 A2A 端点与 Artifact 契约不变。资料同时强调接入前需「明确工具权限和数据边界」（S4），并「放进容器或其他策略沙箱」（S5，针对 Pi）。

---

## 3. 四者关系总结表（归纳）

> 下表是将四份资料的定义性描述整合后的**归纳**，非某一资料原文；依据列标出来源。

| 组件 | 在组合中的角色（归纳） | 依据来源 |
| --- | --- | --- |
| Agent OS | 组合式运行架构，承载运行时/工具权限/记忆/调度/观测审计/Agent 间通信（最外层环境概念） | S2 |
| A2A | 跨 Agent 协作协议：发现能力、发消息、跟踪 Task、交换 Artifact | S1, S2 |
| MCP / Tool API | Agent 调用外部工具的方式（与 A2A 分工不同） | S2 |
| Pi | Agent 单体内部的底层模型对话/工具循环运行时（可编程、默认无沙箱与凭据隔离） | S3, S5 |
| UniPi | Pi 的工作站式扩展，提供记忆/工作流/压缩/子 Agent 等工程能力；非 A2A 实现 | S4, S5 |

---

## 4. 证据不足点

以下内容在现有本地资料中没有对应依据，本报告不作断言，仅列出待补充问题：

1. **Agent OS 的具体产品形态**：S2 仅称其为「组合式运行架构」，未给出具体产品、参考实现、目录/进程结构或与 A2A、Pi 的直接接线方式。
2. **A2A 完整协议细节**：S1 仅给出 Agent Card / Task 状态 / Artifact 三个概念；协议版本、传输细节、鉴权模型资料未载明。
3. **Pi 与 UniPi 在单进程内如何并行/嵌套**：多 Agent 各自一个 Pi 会话时，除「各自任务处理线程中启动一次 Pi JSONL 会话」（S5）外，无更细的并发/资源说明。
4. **生产化的认证与信任**：S5 仅在「生产化前至少补齐」清单中列出（认证与 Agent Card 信任、任务持久化、重试/超时、幂等键、工具沙箱、敏感信息脱敏、来源审计、流式更新），但未给出实现方案。
5. **四者「统一架构图」**：现有资料未提供任何跨组件架构示意图或统一层叠模型，第 2.1 / 3 节的分层结构完全为归纳，请勿当作事实引用。

---

## 5. 结论（归纳，受第 4 节证据范围约束）

在既有资料证据范围内，四者最合理的组合方式是**职责分离、层层解耦**：

- **A2A** 只管 **Agent 与 Agent 之间**的任务传递与结果（Artifact）交换，不关心 Agent 内部实现（S1）。
- **Pi** 作为 **Agent 内部**的底层模型/工具循环运行时，负责单个 Agent 产出内容（S3）；Demo 中也是在研究 Agent、总结 Agent 各自的线程里调用 Pi 会话，A2A 契约保持不变（S5）。
- **UniPi** 作为 Pi 之上，为单个 Agent 提供记忆/工作流/压缩/子 Agent 等能力；本身不是 A2A 实现，若要对外暴露为 A2A Agent，需额外写 Adapter 做「内部任务状态→A2A Task、文件/文本→Artifact」的映射，并明确工具权限与数据边界（S4, S5）。
- **Agent OS** 可作为容纳上述所有部件的组合式运行架构（运行时、工具权限、记忆、任务调度、观测审计、Agent 间通信），其中「跨 Agent 协作走 A2A」「Agent 调外部工具走 MCP/Tool API」（S2）。

最终能否在生产落地，取决于按 S5 清单补齐认证、持久化、沙箱、脱敏与来源审计等工程边界；而上述清单与实现细节在当前资料中「未提供」。
