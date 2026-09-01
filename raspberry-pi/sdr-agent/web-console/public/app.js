const view = {
  state: null,
  active: null,
  provider: null,
  reloadTimer: null,
  terminal: document.querySelector('#terminal'),
  sessions: document.querySelector('#sessions'),
  input: document.querySelector('#command-input'),
};

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
  });
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
  return payload;
}

async function loadState({ keepScroll = true } = {}) {
  const nearBottom = view.terminal.scrollHeight - view.terminal.scrollTop - view.terminal.clientHeight < 70;
  view.state = await api('/api/state');
  view.active = view.state.sessions.find((item) => item.id === view.state.active_session_id) || null;
  render();
  if (!keepScroll || nearBottom) scrollBottom();
}

function render() {
  renderSessions();
  renderTerminal();
  renderOverview();
  renderProvider();
  const enabled = Boolean(view.active);
  document.querySelectorAll('[data-command], #command-input, #command-form button').forEach((element) => { element.disabled = !enabled; });
}

async function loadProvider() {
  view.provider = await api('/api/provider');
  renderProvider();
}

function renderProvider() {
  if (!view.provider) return;
  const status = document.querySelector('#provider-status');
  if (view.provider.configured) {
    status.textContent = `${view.provider.provider} / ${view.provider.model} · ${apiLabel(view.provider.api)}`;
    document.querySelector('#provider-api').value = view.provider.api;
    document.querySelector('#provider-base-url').value = view.provider.base_url;
    document.querySelector('#provider-id').value = view.provider.provider;
    document.querySelector('#provider-model').value = view.provider.model;
  } else {
    status.textContent = '尚未配置第三方上游';
  }
  document.querySelector('#provider-dock').classList.toggle('configured', view.provider.configured);
}

async function saveProvider(event) {
  event.preventDefault();
  const payload = {
    api: document.querySelector('#provider-api').value,
    base_url: document.querySelector('#provider-base-url').value.trim(),
    provider: document.querySelector('#provider-id').value.trim(),
    model: document.querySelector('#provider-model').value.trim(),
    api_key: document.querySelector('#provider-api-key').value,
  };
  try {
    view.provider = await api('/api/provider', { method: 'PUT', body: JSON.stringify(payload) });
    document.querySelector('#provider-api-key').value = '';
    document.querySelector('#provider-dock').open = false;
    renderProvider();
    toast('上游配置已保存，将用于下一个新对话');
  } catch (error) { toast(error.message); }
}

async function clearProvider() {
  if (!window.confirm('清除私密上游配置？新对话将回退到部署环境配置。')) return;
  try {
    view.provider = await api('/api/provider', { method: 'DELETE' });
    document.querySelector('#provider-form').reset();
    renderProvider();
    toast('上游配置已清除');
  } catch (error) { toast(error.message); }
}

function presetOpenCode() {
  document.querySelector('#provider-api').value = 'openai-responses';
  document.querySelector('#provider-base-url').value = 'https://opencode.ai/zen/v1';
  document.querySelector('#provider-id').value = 'opencode';
  document.querySelector('#provider-model').value = 'gpt-5.6-sol';
  document.querySelector('#provider-api-key').focus();
}

function clearProviderFields() {
  document.querySelector('#provider-form').reset();
  document.querySelector('#provider-base-url').focus();
}

function apiLabel(apiName) {
  return apiName === 'openai-responses' ? 'Responses' : 'Chat Completions';
}

function renderSessions() {
  view.sessions.replaceChildren();
  for (const session of [...view.state.sessions].sort((a, b) => b.last_used_at_ms - a.last_used_at_ms)) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = `session${session.id === view.state.active_session_id ? ' active' : ''}`;
    const title = document.createElement('strong');
    title.textContent = session.title;
    const meta = document.createElement('span');
    meta.textContent = sessionMeta(session);
    button.append(title, meta);
    button.addEventListener('click', () => activate(session.id));
    view.sessions.append(button);
  }
}

function renderTerminal() {
  const activeTitle = document.querySelector('#active-title');
  const activeMeta = document.querySelector('#active-meta');
  view.terminal.replaceChildren();
  if (!view.active) {
    activeTitle.textContent = '未选择对话';
    activeMeta.textContent = '新建对话后将连接 sdr-agent';
    const empty = document.createElement('div');
    empty.className = 'terminal-empty';
    empty.textContent = '尚无终端输出';
    view.terminal.append(empty);
    return;
  }
  activeTitle.textContent = view.active.title;
  const compacted = Math.max(0, view.active.generation - 1);
  activeMeta.textContent = `${statusLabel(view.active.status)} · ${view.active.events.length} 条可见记录${compacted ? ` · 已压缩 ${compacted} 次` : ''}`;
  for (const event of view.active.events) {
    const row = document.createElement('div');
    row.className = `line ${safeKind(event.kind)}`;
    const time = document.createElement('time');
    time.textContent = new Date(event.timestamp_ms).toLocaleTimeString('zh-CN', { hour12: false });
    const kind = document.createElement('span');
    kind.className = 'kind';
    kind.textContent = event.kind;
    const text = document.createElement('span');
    text.className = 'text';
    text.textContent = event.text;
    row.append(time, kind, text);
    view.terminal.append(row);
  }
}

function renderOverview() {
  setText('#controller-status', view.active ? `${statusLabel(view.active.status)} · ${view.active.title}` : '等待活动对话');
  setText('#sweep-status', latestText('sweep') || '尚无扫频输出');
  setText('#qwen-status', latestText('qwen') || '尚无模型输出');
}

function latestText(kind) {
  if (!view.active) return '';
  return [...view.active.events].reverse().find((event) => event.kind === kind)?.text || '';
}

async function createSession() {
  try {
    await api('/api/sessions', { method: 'POST', body: JSON.stringify({}) });
    await loadState({ keepScroll: false });
  } catch (error) { toast(error.message); }
}

async function activate(id) {
  if (id === view.state.active_session_id) return;
  try {
    await api(`/api/sessions/${encodeURIComponent(id)}/activate`, { method: 'POST', body: '{}' });
    await loadState({ keepScroll: false });
  } catch (error) { toast(error.message); }
}

async function send(command) {
  if (!view.active || !command.trim()) return;
  try {
    await api(`/api/sessions/${encodeURIComponent(view.active.id)}/command`, {
      method: 'POST', body: JSON.stringify({ command }),
    });
    view.input.value = '';
    await loadState({ keepScroll: false });
  } catch (error) { toast(error.message); }
}

function connectEvents() {
  const source = new EventSource('/api/events');
  source.onopen = () => {
    setConnection(true, '局域网实时连接');
    loadState().catch((error) => toast(error.message));
  };
  source.onerror = () => setConnection(false, '正在重新连接');
  source.onmessage = () => {
    clearTimeout(view.reloadTimer);
    view.reloadTimer = setTimeout(() => loadState().catch((error) => toast(error.message)), 80);
  };
}

function setConnection(online, text) {
  const node = document.querySelector('.connection');
  node.classList.toggle('online', online);
  setText('#connection-text', text);
}

function toast(message) {
  const node = document.querySelector('#toast');
  node.textContent = message;
  node.classList.add('show');
  setTimeout(() => node.classList.remove('show'), 3000);
}

function scrollBottom() { view.terminal.scrollTop = view.terminal.scrollHeight; }
function setText(selector, text) { document.querySelector(selector).textContent = text; }
function safeKind(value) { return /^[a-z]+$/.test(value) ? value : 'system'; }
function sessionMeta(session) {
  const compacted = Math.max(0, session.generation - 1);
  return `${statusLabel(session.status)}${compacted ? ` · 已压缩 ${compacted} 次` : ''}`;
}
function statusLabel(status) {
  return ({ connected: '已连接', stored: '已保存', starting: '启动中', exited: '已退出', error: '错误' })[status] || status;
}

document.querySelector('#new-session').addEventListener('click', createSession);
document.querySelector('#provider-form').addEventListener('submit', saveProvider);
document.querySelector('#clear-provider').addEventListener('click', clearProvider);
document.querySelector('#preset-opencode').addEventListener('click', presetOpenCode);
document.querySelector('#preset-custom').addEventListener('click', clearProviderFields);
document.querySelector('#scroll-bottom').addEventListener('click', scrollBottom);
document.querySelectorAll('[data-command]').forEach((button) => button.addEventListener('click', () => send(button.dataset.command)));
document.querySelector('#command-form').addEventListener('submit', (event) => { event.preventDefault(); send(view.input.value); });
view.input.addEventListener('keydown', (event) => {
  if (event.key === 'Enter' && event.ctrlKey) { event.preventDefault(); send(view.input.value); }
});

Promise.all([loadState({ keepScroll: false }), loadProvider()])
  .then(connectEvents)
  .catch((error) => toast(error.message));
