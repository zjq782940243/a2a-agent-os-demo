const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

// Vercel adapter for the browser demo. The local Python services remain the
// reference implementation; this function mirrors their public contract in a
// stateless-friendly way so the UI can be shared without running three daemons.
const state = globalThis.__a2aVercelState || (globalThis.__a2aVercelState = {
  tasks: new Map(),
  memories: new Map(),
});

const now = () => new Date().toISOString();
const id = (prefix) => `${prefix}_${crypto.randomBytes(6).toString('hex')}`;
const clone = (value) => JSON.parse(JSON.stringify(value));

function terms(text) {
  return String(text || '').toLowerCase().match(/[\w\u4e00-\u9fff]+/g) || [];
}

function approvedSources() {
  const sourceDir = path.join(process.cwd(), 'data', 'sources');
  let files = [];
  try { files = fs.readdirSync(sourceDir).filter((name) => name.endsWith('.md')).sort(); } catch (_) {}
  return files.map((name) => ({
    path: `data/sources/${name}`,
    content: fs.readFileSync(path.join(sourceDir, name), 'utf8').trim(),
  }));
}

function searchSources(topic) {
  const queryTerms = terms(topic).filter((term) => term.length > 1);
  const rows = approvedSources().map((source) => ({
    ...source,
    score: queryTerms.reduce((sum, term) => sum + source.content.toLowerCase().split(term).length - 1, 0),
  })).filter((source) => source.score > 0);
  rows.sort((a, b) => b.score - a.score || a.path.localeCompare(b.path));
  return rows.slice(0, 3);
}

function searchMemory(topic) {
  const queryTerms = terms(topic).filter((term) => term.length > 1);
  return [...state.memories.values()].map((memory) => ({
    ...memory,
    score: queryTerms.reduce((sum, term) => sum + `${memory.topic} ${memory.summary}`.toLowerCase().split(term).length - 1, 0),
  })).filter((memory) => memory.score > 0).sort((a, b) => b.score - a.score).slice(0, 3);
}

function createTask(topic, retryOf) {
  const memoryHits = searchMemory(topic);
  const task = {
    id: id('orchestrator'),
    status: { state: 'submitted', timestamp: now(), message: '任务已创建' },
    artifacts: [],
    history: [{ state: 'submitted', message: '任务已创建', timestamp: now() }],
    context: { topic, memoryHits, ...(retryOf ? { retryOf } : {}) },
    protocol: [],
    toolEvents: [],
    memoryEvents: [],
  };
  const entry = { task, events: [] };
  state.tasks.set(task.id, entry);
  emit(entry, 'task.created');
  return entry;
}

function emit(entry, type) {
  entry.events.push({ seq: entry.events.length + 1, type, timestamp: now(), task: clone(entry.task) });
}

function update(entry, stateName, message) {
  const event = { state: stateName, timestamp: now(), ...(message ? { message } : {}) };
  entry.task.status = { state: stateName, timestamp: event.timestamp, ...(message ? { message } : {}) };
  entry.task.history.push(event);
  emit(entry, `task.${stateName}`);
}

function addProtocol(entry, phase, direction, endpoint, payload) {
  entry.task.protocol.push({ timestamp: now(), phase, direction, endpoint, payload: clone(payload) });
  emit(entry, 'protocol.added');
}

function addArtifact(entry, artifact) {
  entry.task.artifacts.push(artifact);
  emit(entry, 'artifact.added');
}

function runtimeTelemetry() {
  return {
    runtime: 'vercel-serverless',
    pi: {
      model: process.env.PI_MODEL || 'deterministic-local-adapter',
      provider: process.env.DEEPSEEK_API_KEY ? 'deepseek-compatible-api (opt-in)' : 'local',
      durationMs: 8,
      eventCounts: { serverless_request: 1, artifact_generated: 1 },
      usage: { totalTokens: 0 },
      tools: 'host-controlled source_search',
      mode: 'Vercel adapter; real Pi is available through start_deepseek_demo.sh locally',
    },
  };
}

function researchMarkdown(topic, sources, memories) {
  if (!sources.length) {
    return [
      `# 研究报告：${topic}`,
      '',
      '> 证据状态：insufficient',
      '',
      `本次仅检索已批准的本地资料目录，未找到与“${topic}”直接匹配的来源。`,
      '',
      '不会用无关资料填充结论。请补充相关资料后再研究。',
    ].join('\\n');
  }
  const lines = [`# 研究笔记：${topic}`, '', '## 资料命中', ''];
  sources.forEach((source, index) => {
    lines.push(`### ${index + 1}. ${source.path}（匹配度 ${source.score}）`, '', source.content, '');
  });
  if (memories.length) {
    lines.push('## 历史记忆（仅作上下文）', '');
    memories.forEach((memory) => lines.push(`- ${memory.topic}（score ${memory.score}）`));
    lines.push('');
  }
  lines.push('## 证据边界', '', '以上内容仅来自本地 Markdown 资料；Vercel 适配版不会把未命中的内容当作事实。');
  return lines.join('\\n');
}

function summaryMarkdown(topic, research, evidenceStatus) {
  if (evidenceStatus === 'insufficient') return research;
  return [
    `# ${topic}`,
    '',
    '## 结论摘要',
    '',
    '本报告由 Vercel 适配层按 A2A 教学契约串联研究与总结两个 Agent。总结只整理研究 Agent 返回的资料，不扩写未提供的事实。',
    '',
    '## 研究结果',
    '',
    research,
    '',
    '## 运行边界',
    '',
    '线上版本运行在 Vercel Serverless；仓库中的本地启动脚本仍支持真实 Pi + DeepSeek。',
  ].join('\\n');
}

function runPipeline(topic, retryOf) {
  const entry = createTask(topic, retryOf);
  const { task } = entry;
  const memoryHits = task.context.memoryHits || [];
  task.memoryEvents.push({ operation: 'search', query: topic, hitCount: memoryHits.length, hits: memoryHits.map(({ id, topic: hitTopic, score }) => ({ id, topic: hitTopic, score })) });
  emit(entry, 'memoryEvents.added');

  const researchCard = {
    name: 'Research Agent (Vercel)',
    description: 'Searches approved local Markdown sources.',
    url: '/api/agents/research',
    version: 'vercel-adapter',
    capabilities: { streaming: false, pushNotifications: false },
    skills: [{ id: 'source-search', name: 'Source search', description: 'Search local evidence only.' }],
  };
  const summaryCard = {
    name: 'Summary Agent (Vercel)',
    description: 'Structures research artifacts with evidence boundaries.',
    url: '/api/agents/summary',
    version: 'vercel-adapter',
    capabilities: { streaming: false, pushNotifications: false },
    skills: [{ id: 'synthesize-notes', name: 'Synthesize notes', description: 'Produce a concise cited Markdown artifact.' }],
  };
  addProtocol(entry, 'agent-card', 'inbound', '/api/agents/research', { agent: 'research', card: researchCard });
  addProtocol(entry, 'agent-card', 'inbound', '/api/agents/summary', { agent: 'summary', card: summaryCard });
  update(entry, 'working', '编排 Agent 正在调用研究 Agent');

  const researchId = id('research');
  const researchRequest = { jsonrpc: '2.0', id: id('rpc'), method: 'message/send', params: { message: { messageId: id('message'), role: 'user', parts: [{ kind: 'text', text: JSON.stringify({ topic, memory_context: memoryHits }) }] } } };
  addProtocol(entry, 'research-message/send', 'outbound', '/api/agents/research', researchRequest);
  addProtocol(entry, 'research-task-accepted', 'inbound', '/api/agents/research', { jsonrpc: '2.0', id: researchRequest.id, result: { task: { id: researchId, status: { state: 'submitted' } } } });
  task.context.researchTaskId = researchId;
  update(entry, 'working', `研究 Agent 已接单：${researchId}`);

  const sources = searchSources(topic);
  const toolEvent = {
    toolCallId: id('toolcall'), name: 'source_search', input: { topic, scope: 'data/sources/*.md', limit: 3 },
    output: { sources: sources.map(({ path: sourcePath, score }) => ({ path: sourcePath, score })), sourceCount: sources.length, reason: sources.length ? 'matched_sources' : 'no_relevant_sources' },
    durationMs: 4, status: 'completed',
  };
  task.toolEvents.push(toolEvent);
  emit(entry, 'toolEvents.added');
  const evidenceStatus = sources.length ? 'supported' : 'insufficient';
  const researchText = researchMarkdown(topic, sources, memoryHits);
  addArtifact(entry, { artifactId: id('artifact'), name: 'research-notes.md', parts: [{ kind: 'text', text: researchText }], metadata: { sourceCount: sources.length, evidenceStatus, ...runtimeTelemetry() } });
  update(entry, 'working', `研究完成，正在调用总结 Agent`);

  const summaryId = id('summary');
  const summaryRequest = { jsonrpc: '2.0', id: id('rpc'), method: 'message/send', params: { message: { messageId: id('message'), role: 'user', parts: [{ kind: 'text', text: JSON.stringify({ topic, research_markdown: researchText, evidence_status: evidenceStatus }) }] } } };
  addProtocol(entry, 'summary-message/send', 'outbound', '/api/agents/summary', summaryRequest);
  addProtocol(entry, 'summary-task-accepted', 'inbound', '/api/agents/summary', { jsonrpc: '2.0', id: summaryRequest.id, result: { task: { id: summaryId, status: { state: 'submitted' } } } });
  task.context.summaryTaskId = summaryId;
  update(entry, 'working', `总结 Agent 已接单：${summaryId}`);

  const finalText = summaryMarkdown(topic, researchText, evidenceStatus);
  const record = { id: id('memory'), topic, summary: finalText.slice(0, 4000), updatedAt: now() };
  state.memories.set(topic, record);
  task.memoryEvents.push({ operation: 'store', memory: record, sourceTask: summaryId });
  emit(entry, 'memoryEvents.added');
  const summaryArtifact = { artifactId: id('artifact'), name: 'final-report.md', parts: [{ kind: 'text', text: finalText }], metadata: { evidenceStatus, ...runtimeTelemetry(), fromTask: summaryId, memoryId: record.id } };
  addArtifact(entry, summaryArtifact);
  addProtocol(entry, 'artifact-delivery', 'inbound', `/api/agents/summary/tasks/${summaryId}`, { taskId: summaryId, artifacts: [{ name: summaryArtifact.name, artifactId: summaryArtifact.artifactId, metadata: summaryArtifact.metadata }] });
  update(entry, 'completed', 'A2A 链路完成');
  return entry.task;
}

function getPath(req) {
  const raw = String(req.url || '/').split('?')[0];
  return raw.replace(/^\/api(?=\/|$)/, '') || '/';
}

function getTask(idValue) {
  return state.tasks.get(idValue);
}

function publicTask(entry) {
  const task = clone(entry.task);
  // Serverless instances are not a durable task store. Include a compact event
  // snapshot in the create response so the browser can render the run even if
  // the next request lands on another instance.
  task.liveEvents = entry.events.map((event) => ({
    seq: event.seq,
    type: event.type,
    timestamp: event.timestamp,
    task: { status: event.task.status },
  }));
  return task;
}

async function bodyJson(req) {
  if (req.body && typeof req.body === 'object') return req.body;
  let body = '';
  for await (const chunk of req) body += chunk;
  try { return body ? JSON.parse(body) : {}; } catch (_) { return {}; }
}

function sendJson(res, value, status = 200) {
  res.statusCode = status;
  res.setHeader('Content-Type', 'application/json; charset=utf-8');
  res.end(JSON.stringify(value));
}

module.exports = async function handler(req, res) {
  const route = getPath(req);
  if (req.method === 'GET' && route === '/health') return sendJson(res, { ok: true, service: 'vercel-adapter' });
  if (req.method === 'GET' && route === '/agents') return sendJson(res, { agents: [
    { name: 'Research Agent (Vercel)', runtime: 'vercel-serverless', protocol: 'A2A message/send' },
    { name: 'Summary Agent (Vercel)', runtime: 'vercel-serverless', protocol: 'A2A message/send' },
  ] });
  if (req.method === 'POST' && route === '/tasks') {
    const payload = await bodyJson(req);
    const topic = String(payload.topic || '').trim();
    if (!topic) return sendJson(res, { error: 'topic_required' }, 422);
    const task = runPipeline(topic);
    return sendJson(res, { task: publicTask(state.tasks.get(task.id)) }, 202);
  }
  const match = route.match(/^\/tasks\/([^/]+)(?:\/(events|cancel|retry))?$/);
  if (!match) return sendJson(res, { error: 'not_found' }, 404);
  const taskId = match[1];
  const action = match[2];
  const entry = getTask(taskId);
  if (!entry) return sendJson(res, { error: 'task_not_found' }, 404);
  if (req.method === 'GET' && action === 'events') {
    res.statusCode = 200;
    res.setHeader('Content-Type', 'text/event-stream; charset=utf-8');
    res.setHeader('Cache-Control', 'no-cache, no-transform');
    res.setHeader('Connection', 'keep-alive');
    res.setHeader('X-Accel-Buffering', 'no');
    const after = Number(req.headers['last-event-id'] || 0);
    entry.events.filter((event) => event.seq > after).forEach((event) => {
      res.write(`id: ${event.seq}\ndata: ${JSON.stringify(event)}\n\n`);
    });
    return res.end();
  }
  if (req.method === 'GET' && !action) return sendJson(res, { task: entry.task });
  if (req.method === 'POST' && action === 'cancel') {
    if (!['completed', 'failed', 'canceled'].includes(entry.task.status.state)) update(entry, 'canceled', '任务已取消');
    return sendJson(res, { task: entry.task });
  }
  if (req.method === 'POST' && action === 'retry') {
    if (!['failed', 'canceled'].includes(entry.task.status.state)) return sendJson(res, { error: 'retry_not_allowed' }, 409);
    const task = runPipeline(entry.task.context.topic, taskId);
    return sendJson(res, { task: publicTask(state.tasks.get(task.id)) }, 202);
  }
  return sendJson(res, { error: 'method_not_allowed' }, 405);
};
