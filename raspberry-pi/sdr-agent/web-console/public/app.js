const view = {
  state: null,
  active: null,
  provider: null,
  providerModels: [],
  results: [],
  recognitions: [],
  selectedRecognitionId: null,
  recognitionEpoch: 0,
  selectedResultId: null,
  selectedResult: null,
  corpusResults: [],
  selectedCorpusId: null,
  selectedCorpus: null,
  settingsDirty: false,
  settingsOpen: false,
  resultsOpen: false,
  corpusOpen: false,
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
  renderModelTrace();
  const enabled = Boolean(view.active);
  document.querySelectorAll('[data-command], #command-input, #command-form button, #auto-form input, #auto-form button').forEach((element) => { element.disabled = !enabled; });
}

async function loadProvider() {
  view.provider = await api('/api/provider');
  renderProvider();
}

function renderProvider() {
  if (!view.provider) return;
  const status = document.querySelector('#provider-status');
  if (view.provider.configured) {
    status.textContent = `${view.provider.provider} / ${view.provider.model} · ${formatTokens(view.provider.context_window)} · ${view.provider.compression_threshold_percent}% 压缩`;
    document.querySelector('#provider-api').value = view.provider.api;
    document.querySelector('#provider-base-url').value = view.provider.base_url;
    document.querySelector('#provider-id').value = view.provider.provider;
    document.querySelector('#provider-model').value = view.provider.model;
    document.querySelector('#provider-context-window').value = view.provider.context_window;
    document.querySelector('#provider-compression-threshold').value = view.provider.compression_threshold_percent;
  } else {
    status.textContent = '尚未配置第三方上游';
  }
  const survey = view.provider.initial_survey || defaultSurvey();
  const radio = document.querySelector(`input[name="survey-mode"][value="${survey.mode}"]`);
  if (radio) radio.checked = true;
  document.querySelector('#survey-start-mhz').value = hzToMhz(survey.start_hz);
  document.querySelector('#survey-stop-mhz').value = hzToMhz(survey.stop_hz);
  document.querySelector('#survey-step-mhz').value = hzToMhz(survey.step_hz);
  document.querySelector('#survey-dwell-ms').value = survey.dwell_ms;
  document.querySelector('#survey-gain-db').value = survey.gain_db ?? 20;
  document.querySelector('#save-iq').checked = Boolean(view.provider.result_storage?.save_iq);
  document.querySelector('#provider-api-key').value = '';
  updateSurveyControls();
  markSettingsDirty(false);
}

function defaultSurvey() {
  return { mode: 'full_band', start_hz: 70000000, stop_hz: 6000000000, step_hz: 8000000, dwell_ms: 5, gain_db: 20 };
}

function surveyMode() {
  return document.querySelector('input[name="survey-mode"]:checked')?.value || 'full_band';
}

function surveyPayload() {
  return {
    mode: surveyMode(),
    start_hz: Math.round(Number(document.querySelector('#survey-start-mhz').value) * 1000000),
    stop_hz: Math.round(Number(document.querySelector('#survey-stop-mhz').value) * 1000000),
    step_hz: Math.round(Number(document.querySelector('#survey-step-mhz').value) * 1000000),
    dwell_ms: Number(document.querySelector('#survey-dwell-ms').value),
    gain_db: Number(document.querySelector('#survey-gain-db').value),
  };
}

function updateSurveyControls() {
  const mode = surveyMode();
  if (mode === 'full_band') {
    const survey = defaultSurvey();
    document.querySelector('#survey-start-mhz').value = hzToMhz(survey.start_hz);
    document.querySelector('#survey-stop-mhz').value = hzToMhz(survey.stop_hz);
    document.querySelector('#survey-step-mhz').value = hzToMhz(survey.step_hz);
    document.querySelector('#survey-dwell-ms').value = survey.dwell_ms;
  }
  document.querySelectorAll('#survey-fields input').forEach((input) => {
    input.disabled = mode === 'disabled' || (mode === 'full_band' && input.id !== 'survey-gain-db');
  });
  document.querySelector('#survey-fields').classList.toggle('fields-disabled', mode === 'disabled');
  updateSurveyBudget();
}

function updateSurveyBudget() {
  const budget = document.querySelector('#survey-budget');
  const summary = document.querySelector('#survey-budget-summary');
  const detail = document.querySelector('#survey-budget-detail');
  if (surveyMode() === 'disabled') {
    budget.dataset.state = 'disabled';
    summary.textContent = '首次扫描已关闭';
    detail.textContent = '新对话会直接进入控制台，不建立初始频谱。';
    return;
  }
  const survey = surveyPayload();
  const span = survey.stop_hz - survey.start_hz;
  const points = survey.step_hz > 0 && span >= 0 ? Math.ceil(span / survey.step_hz) + 1 : 0;
  const durationMs = points * (survey.dwell_ms + 250);
  const bytes = points * 4096 * 4;
  const valid = survey.start_hz >= 70000000 && survey.stop_hz <= 6000000000
    && survey.start_hz <= survey.stop_hz && survey.step_hz > 0 && survey.step_hz <= 8000000
    && survey.dwell_ms >= 0 && survey.dwell_ms <= 1000 && survey.gain_db >= 0 && survey.gain_db <= 60
    && points <= 768 && durationMs <= 300000;
  budget.dataset.state = valid ? 'ready' : 'error';
  summary.textContent = valid
    ? `${points} 点 · 约 ${Math.round(durationMs / 1000)} 秒 · 约 ${formatBytes(bytes)}`
    : '扫描预算超出安全边界';
  detail.textContent = valid
    ? `仅 RX，固定 ${survey.gain_db} dB 增益，10 MHz 采样率，4096 samples/点；可随时停止并恢复射频状态。`
    : '请限制在 70–6000 MHz、步进不超过 8 MHz、增益 0–60 dB、最多 768 点 / 300 秒。';
}

function hzToMhz(value) {
  return Number((Number(value) / 1000000).toFixed(6));
}

function formatBytes(value) {
  return value < 1048576 ? `${Math.round(value / 1024)} KiB` : `${(value / 1048576).toFixed(1)} MiB`;
}

function markSettingsDirty(dirty = true) {
  view.settingsDirty = dirty;
  document.querySelector('#settings-dirty-dot').hidden = !dirty;
  document.querySelector('#settings-save-state').textContent = dirty ? '有未保存修改' : '已载入当前设置';
  document.querySelector('#settings-view').classList.toggle('dirty', dirty);
}

function showSettings() {
  view.settingsOpen = true;
  view.resultsOpen = false;
  view.corpusOpen = false;
  document.querySelector('#console-view').hidden = true;
  document.querySelector('#results-view').hidden = true;
  document.querySelector('#corpus-view').hidden = true;
  document.querySelector('#settings-view').hidden = false;
  document.querySelector('#corpus-entry').setAttribute('aria-expanded', 'false');
  document.querySelector('#corpus-entry').classList.remove('active');
  document.querySelector('#settings-entry').setAttribute('aria-expanded', 'true');
  document.querySelector('#settings-entry').classList.add('active');
  document.querySelector('#settings-title').focus?.();
}

function showConsole() {
  if (view.settingsDirty && !window.confirm('设置尚未保存，放弃修改并返回运行台？')) return;
  if (view.settingsDirty) renderProvider();
  view.settingsOpen = false;
  view.resultsOpen = false;
  view.corpusOpen = false;
  document.querySelector('#settings-view').hidden = true;
  document.querySelector('#results-view').hidden = true;
  document.querySelector('#corpus-view').hidden = true;
  document.querySelector('#console-view').hidden = false;
  document.querySelector('#settings-entry').setAttribute('aria-expanded', 'false');
  document.querySelector('#settings-entry').classList.remove('active');
  document.querySelector('#corpus-entry').setAttribute('aria-expanded', 'false');
  document.querySelector('#corpus-entry').classList.remove('active');
}

async function showResults() {
  view.settingsOpen = false;
  view.resultsOpen = true;
  view.corpusOpen = false;
  document.querySelector('#console-view').hidden = true;
  document.querySelector('#settings-view').hidden = true;
  document.querySelector('#corpus-view').hidden = true;
  document.querySelector('#results-view').hidden = false;
  document.querySelector('#settings-entry').setAttribute('aria-expanded', 'false');
  document.querySelector('#settings-entry').classList.remove('active');
  document.querySelector('#corpus-entry').setAttribute('aria-expanded', 'false');
  document.querySelector('#corpus-entry').classList.remove('active');
  try { await Promise.all([loadResults({ selectLatest: true }), loadRecognitions()]); } catch (error) { toast(error.message); }
}

async function showCorpus() {
  view.settingsOpen = false;
  view.resultsOpen = false;
  view.corpusOpen = true;
  document.querySelector('#console-view').hidden = true;
  document.querySelector('#settings-view').hidden = true;
  document.querySelector('#results-view').hidden = true;
  document.querySelector('#corpus-view').hidden = false;
  document.querySelector('#settings-entry').setAttribute('aria-expanded', 'false');
  document.querySelector('#settings-entry').classList.remove('active');
  document.querySelector('#corpus-entry').setAttribute('aria-expanded', 'true');
  document.querySelector('#corpus-entry').classList.add('active');
  try { await loadCorpus({ selectLatest: true }); } catch (error) { toast(error.message); }
}

function toggleSettings() {
  if (view.settingsOpen) showConsole(); else showSettings();
}

function discardSettings() {
  renderProvider();
  clearModelInventory();
  toast('未保存修改已放弃');
}

async function saveProvider(event) {
  event.preventDefault();
  const form = document.querySelector('#provider-form');
  if (!form.reportValidity()) return;
  const payload = {
    api: document.querySelector('#provider-api').value,
    base_url: document.querySelector('#provider-base-url').value.trim(),
    provider: document.querySelector('#provider-id').value.trim(),
    model: document.querySelector('#provider-model').value.trim(),
    api_key: document.querySelector('#provider-api-key').value,
    context_window: Number(document.querySelector('#provider-context-window').value),
    compression_threshold_percent: Number(document.querySelector('#provider-compression-threshold').value),
    initial_survey: surveyPayload(),
    result_storage: { save_iq: document.querySelector('#save-iq').checked },
  };
  try {
    view.provider = await api('/api/provider', { method: 'PUT', body: JSON.stringify(payload) });
    document.querySelector('#provider-api-key').value = '';
    renderProvider();
    toast('设置已保存，将用于下一个新对话');
  } catch (error) { toast(error.message); }
}

async function queryProviderModels() {
  const baseUrl = document.querySelector('#provider-base-url');
  const apiKey = document.querySelector('#provider-api-key');
  if (!baseUrl.reportValidity()) return;
  const button = document.querySelector('#query-provider-models');
  clearModelInventory();
  const modelList = document.querySelector('#provider-model-list');
  modelList.replaceChildren(new Option('正在查询…', ''));
  modelList.disabled = true;
  button.disabled = true;
  button.textContent = '正在查询…';
  setModelInventoryStatus('正在连接上游 /models…', 'loading');
  try {
    const result = await api('/api/provider/models', {
      method: 'POST',
      body: JSON.stringify({ base_url: baseUrl.value.trim(), api_key: apiKey.value }),
    });
    renderModelInventory(result.models);
    toast(`上游返回 ${result.models.length} 个模型`);
  } catch (error) {
    modelList.replaceChildren(new Option('查询失败，请检查上方状态', ''));
    setModelInventoryStatus(error.message, 'error');
    toast(error.message);
  } finally {
    button.disabled = false;
    button.textContent = '查询上游模型';
  }
}

function renderModelInventory(models) {
  view.providerModels = models;
  const datalist = document.querySelector('#provider-model-options');
  const select = document.querySelector('#provider-model-list');
  datalist.replaceChildren();
  select.replaceChildren(new Option('选择一个上游模型…', ''));
  for (const model of models) {
    datalist.append(new Option('', model.id));
    select.append(new Option(model.context_window ? `${model.id} · ${formatTokens(model.context_window)}` : `${model.id} · 上游未提供上下文`, model.id));
  }
  select.disabled = false;
  const withContext = models.filter((model) => model.context_window).length;
  setModelInventoryStatus(`已发现 ${models.length} 个模型，其中 ${withContext} 个带上下文窗口`, 'ready');
  applySelectedModel(document.querySelector('#provider-model').value);
}

function applySelectedModel(modelId) {
  const selected = view.providerModels.find((model) => model.id === modelId);
  if (selected?.context_window) {
    document.querySelector('#provider-context-window').value = selected.context_window;
    markSettingsDirty();
    toast(`已采用上游返回的上下文窗口：${formatTokens(selected.context_window)}`);
  }
}

function setModelInventoryStatus(message, state) {
  const inventory = document.querySelector('#model-inventory');
  inventory.hidden = false;
  inventory.dataset.state = state;
  document.querySelector('#model-inventory-status').textContent = message;
}

function clearModelInventory() {
  view.providerModels = [];
  document.querySelector('#provider-model-options').replaceChildren();
  const select = document.querySelector('#provider-model-list');
  select.replaceChildren();
  select.disabled = true;
  document.querySelector('#model-inventory').hidden = true;
}

async function clearProvider() {
  if (!window.confirm('清除私密上游配置？新对话将回退到部署环境配置。')) return;
  try {
    view.provider = await api('/api/provider', { method: 'DELETE' });
    document.querySelector('#provider-form').reset();
    clearModelInventory();
    renderProvider();
    toast('上游配置已清除');
  } catch (error) { toast(error.message); }
}

function presetOpenCode() {
  document.querySelector('#provider-api').value = 'openai-completions';
  document.querySelector('#provider-base-url').value = 'https://opencode.ai/zen/go/v1';
  document.querySelector('#provider-id').value = 'opencode-go';
  document.querySelector('#provider-model').value = 'deepseek-v4-flash';
  document.querySelector('#provider-context-window').value = '196608';
  document.querySelector('#provider-compression-threshold').value = '90';
  clearModelInventory();
  markSettingsDirty();
  document.querySelector('#provider-api-key').focus();
}

function clearProviderFields() {
  document.querySelector('#provider-form').reset();
  clearModelInventory();
  updateSurveyControls();
  markSettingsDirty();
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
  const compacted = view.active.compaction_count || 0;
  activeMeta.textContent = `${statusLabel(view.active.status)} · ${view.active.events.length} 条可见记录${compacted ? ` · 已压缩 ${compacted} 次` : ''}`;
  for (const event of view.active.events) {
    const row = document.createElement('div');
    row.className = `line ${safeKind(event.kind)}`;
    const time = document.createElement('time');
    time.textContent = new Date(event.timestamp_ms).toLocaleTimeString('zh-CN', { hour12: false });
    const kind = document.createElement('span');
    kind.className = 'kind';
    kind.textContent = kindLabel(event.kind);
    const text = document.createElement('span');
    text.className = 'text';
    text.textContent = event.text;
    row.append(time, kind, text);
    view.terminal.append(row);
  }
}

function renderModelTrace() {
  const trace = document.querySelector('#model-trace');
  const inputPanel = document.querySelector('#model-input-panel');
  const thinkingPanel = document.querySelector('#thinking-panel');
  const decisionPanel = document.querySelector('#decision-panel');
  const modelInput = view.active?.model_input;
  const thinking = view.active?.thinking;
  const decision = view.active?.decision_basis;
  const hasThinking = Boolean(thinking?.text);
  trace.hidden = !modelInput && !hasThinking && !decision;
  inputPanel.hidden = !modelInput;
  if (modelInput) document.querySelector('#model-input-content').textContent = JSON.stringify(modelInput, null, 2);
  thinkingPanel.hidden = !hasThinking;
  if (hasThinking) document.querySelector('#thinking-content').textContent = thinking.text;
  const live = document.querySelector('#thinking-live');
  live.hidden = !hasThinking || !thinking.active;
  decisionPanel.hidden = !decision;
  if (decision) document.querySelector('#decision-content').textContent = decision;
}

function renderOverview() {
  setText('#controller-status', view.active ? `${statusLabel(view.active.status)} · ${view.active.title}` : '等待活动对话');
  const plot = view.active?.sweep_plot;
  setText('#sweep-status', plot
    ? `${plot.sweep_id} · ${plot.points.length} 点 · ${plot.candidates.length} 个候选`
    : latestText('sweep') || initialSurveyLabel(view.active?.initial_survey_status));
  setText('#qwen-status', latestText('qwen') || '尚无模型输出');
  setText('#cruise-status', latestText('cruise') || '逐步批准模式');
}

async function loadResults({ selectLatest = false } = {}) {
  view.results = await api('/api/results');
  document.querySelector('#results-count').textContent = `${view.results.length} 次已保存采集`;
  renderResultsList();
  if (!view.results.length) {
    view.selectedResultId = null;
    view.selectedResult = null;
    renderResultDetail();
    return;
  }
  const selectedStillExists = view.results.some((result) => result.id === view.selectedResultId);
  if (selectLatest || !selectedStillExists) view.selectedResultId = view.results[0].id;
  await selectResult(view.selectedResultId, { rerenderList: true });
}

function renderResultsList() {
  const list = document.querySelector('#results-list');
  list.replaceChildren();
  if (!view.results.length) {
    const empty = document.createElement('p');
    empty.className = 'result-list-empty';
    empty.textContent = '完成一次扫频后，结果会自动出现在这里。';
    list.append(empty);
    return;
  }
  for (const result of view.results) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = `result-list-item${result.id === view.selectedResultId ? ' active' : ''}`;
    const kind = document.createElement('small');
    kind.textContent = result.kind === 'initial' ? 'INITIAL SURVEY' : 'PLANNED SWEEP';
    const title = document.createElement('strong');
    title.textContent = result.sweep_id;
    const meta = document.createElement('span');
    meta.textContent = `${formatDate(result.created_at_ms)} · ${result.point_count} 点 · ${result.candidate_count} 候选`;
    button.append(kind, title, meta);
    button.addEventListener('click', () => selectResult(result.id));
    list.append(button);
  }
}

async function selectResult(id, { rerenderList = true } = {}) {
  view.selectedResultId = id;
  if (rerenderList) renderResultsList();
  const result = await api(`/api/results/${id}`);
  if (view.selectedResultId !== id) return;
  view.selectedResult = result;
  renderResultDetail();
}

function renderResultDetail() {
  const empty = document.querySelector('#results-empty');
  const content = document.querySelector('#result-content');
  if (!view.selectedResult) {
    empty.hidden = false;
    content.hidden = true;
    return;
  }
  empty.hidden = true;
  content.hidden = false;
  const { summary, sweep_plot: plot } = view.selectedResult;
  const firstHz = plot.points[0][0];
  const lastHz = plot.points[plot.points.length - 1][0];
  setText('#result-kind', plot.kind === 'initial' ? 'INITIAL SURVEY' : 'PLANNED SWEEP');
  setText('#result-title', plot.sweep_id);
  setText('#result-time', `${formatDate(summary.created_at_ms)} · AGX 处理后结果`);
  setText('#result-band', `${formatFrequency(firstHz)}–${formatFrequency(lastHz)}`);
  setText('#result-points', `${plot.points.length}`);
  setText('#result-gain', `${plot.gain_db} dB`);
  setText('#result-noise', `${plot.noise_floor_dbfs.toFixed(1)} dBFS`);
  setText('#result-candidates', `${plot.candidates.length}`);
  setText('#result-elapsed', formatDuration(plot.elapsed_ms));
  const dataset = plot.dataset;
  setText('#dataset-state', dataset
    ? `已保存 ${formatBytes(dataset.bytes)} 原始 IQ · ${dataset.datatype}`
    : '本次未保存原始 IQ');
  setText('#dataset-detail', dataset
    ? '一次扫描对应一组 SigMF data/meta 文件；删除这次采集会同时删除这组文件。'
    : '频率、功率、噪声基线和候选仍已保存在 AGX SQLite。');
  renderCandidateTable(plot.candidates);
  renderSpectrum(plot);
}

function renderCandidateTable(candidates) {
  setText('#candidate-count', `${candidates.length} 个`);
  const body = document.querySelector('#candidate-table');
  body.replaceChildren();
  if (!candidates.length) {
    const row = document.createElement('tr');
    row.className = 'candidate-empty';
    const cell = document.createElement('td');
    cell.colSpan = 6;
    cell.textContent = '本次扫频没有超过检测阈值的候选。';
    row.append(cell);
    body.append(row);
    return;
  }
  for (const candidate of candidates) {
    const row = document.createElement('tr');
    for (const value of [
      candidate.id,
      formatFrequency(candidate.center_hz),
      formatFrequencySpan(candidate.bandwidth_hz),
      `${candidate.peak_dbfs.toFixed(1)} dBFS`,
      `${candidate.snr_db.toFixed(1)} dB`,
      String(candidate.point_count),
    ]) {
      const cell = document.createElement('td');
      cell.textContent = value;
      row.append(cell);
    }
    body.append(row);
  }
}

function renderSpectrum(plot) {
  const svg = document.querySelector('#spectrum-plot');
  svg.replaceChildren();
  const title = svgNode('title');
  title.textContent = `${plot.sweep_id} 扫频功率图`;
  const desc = svgNode('desc');
  desc.textContent = `${plot.points.length} 个真实频点，噪声基线 ${plot.noise_floor_dbfs.toFixed(1)} dBFS，${plot.candidates.length} 个候选。`;
  svg.append(title, desc);
  const defs = svgNode('defs');
  const gradient = svgNode('linearGradient', { id: 'trace-gradient', x1: '0', y1: '0', x2: '0', y2: '1' });
  gradient.append(
    svgNode('stop', { offset: '0%', 'stop-color': '#51d5e6', 'stop-opacity': '.25' }),
    svgNode('stop', { offset: '100%', 'stop-color': '#51d5e6', 'stop-opacity': '0' }),
  );
  defs.append(gradient);
  svg.append(defs);
  const left = 72, right = 970, top = 22, bottom = 310;
  const frequencies = plot.points.map((point) => point[0]);
  const powers = plot.points.map((point) => point[1]);
  const minHz = frequencies[0], maxHz = frequencies[frequencies.length - 1];
  let minPower = Math.floor(Math.min(plot.noise_floor_dbfs, ...powers) / 10) * 10 - 5;
  let maxPower = Math.ceil(Math.max(plot.noise_floor_dbfs, ...powers) / 10) * 10 + 5;
  if (maxPower - minPower < 20) { minPower -= 10; maxPower += 10; }
  const x = (hz) => left + ((hz - minHz) / Math.max(1, maxHz - minHz)) * (right - left);
  const y = (dbfs) => bottom - ((dbfs - minPower) / (maxPower - minPower)) * (bottom - top);
  for (let index = 0; index <= 5; index += 1) {
    const ratio = index / 5;
    const py = top + ratio * (bottom - top);
    svg.append(svgNode('line', { x1: left, y1: py, x2: right, y2: py, class: 'grid' }));
    const label = svgNode('text', { x: left - 10, y: py + 3, class: 'axis-label', 'text-anchor': 'end' });
    label.textContent = `${(maxPower - ratio * (maxPower - minPower)).toFixed(0)}`;
    svg.append(label);
  }
  for (let index = 0; index <= 6; index += 1) {
    const ratio = index / 6;
    const px = left + ratio * (right - left);
    svg.append(svgNode('line', { x1: px, y1: top, x2: px, y2: bottom, class: 'grid' }));
    const label = svgNode('text', { x: px, y: bottom + 24, class: 'axis-label', 'text-anchor': index === 0 ? 'start' : index === 6 ? 'end' : 'middle' });
    label.textContent = formatAxisFrequency(minHz + ratio * (maxHz - minHz));
    svg.append(label);
  }
  const points = plot.points.map(([hz, power]) => `${x(hz).toFixed(2)},${y(power).toFixed(2)}`);
  const area = `M ${left},${bottom} L ${points.join(' L ')} L ${right},${bottom} Z`;
  const line = `M ${points.join(' L ')}`;
  svg.append(svgNode('path', { d: area, class: 'trace-fill' }));
  svg.append(svgNode('line', { x1: left, y1: y(plot.noise_floor_dbfs), x2: right, y2: y(plot.noise_floor_dbfs), class: 'noise-line' }));
  svg.append(svgNode('path', { d: line, class: 'trace-line' }));
  for (const candidate of plot.candidates) {
    const cx = x(candidate.center_hz);
    const cy = y(candidate.peak_dbfs);
    svg.append(svgNode('circle', { cx, cy, r: 4.5, class: 'candidate-dot' }));
    const label = svgNode('text', { x: cx, y: Math.max(top + 10, cy - 9), class: 'candidate-label', 'text-anchor': 'middle' });
    label.textContent = candidate.id;
    svg.append(label);
  }
}

function svgNode(name, attributes = {}) {
  const node = document.createElementNS('http://www.w3.org/2000/svg', name);
  for (const [key, value] of Object.entries(attributes)) node.setAttribute(key, String(value));
  return node;
}

async function deleteSelectedResult() {
  if (!view.selectedResult) return;
  const { id, sweep_id: sweepId, iq_bytes: iqBytes } = view.selectedResult.summary;
  const suffix = iqBytes ? `，并删除 ${formatBytes(iqBytes)} 原始 IQ` : '';
  if (!window.confirm(`删除扫频结果 ${sweepId}${suffix}？此操作无法撤销。`)) return;
  try {
    await api(`/api/results/${id}`, { method: 'DELETE' });
    view.selectedResult = null;
    view.selectedResultId = null;
    await loadResults({ selectLatest: true });
    toast('采集结果已删除');
  } catch (error) { toast(error.message); }
}

async function refreshCorpusCount() {
  view.corpusResults = await api('/api/corpus');
  const count = view.corpusResults.length;
  document.querySelector('#corpus-entry-label').textContent = count ? `接收语料 · ${count}` : '接收语料';
  return view.corpusResults;
}

async function loadCorpus({ selectLatest = false } = {}) {
  await refreshCorpusCount();
  document.querySelector('#corpus-count').textContent = `${view.corpusResults.length} 条 RX-only 记录`;
  renderCorpusList();
  if (!view.corpusResults.length) {
    view.selectedCorpusId = null;
    view.selectedCorpus = null;
    renderCorpusDetail();
    return;
  }
  const selectedStillExists = view.corpusResults.some((result) => result.result_id === view.selectedCorpusId);
  if (selectLatest || !selectedStillExists) view.selectedCorpusId = view.corpusResults[0].result_id;
  await selectCorpus(view.selectedCorpusId, { rerenderList: true });
}

function renderCorpusList() {
  const list = document.querySelector('#corpus-list');
  list.replaceChildren();
  if (!view.corpusResults.length) {
    const empty = document.createElement('p');
    empty.className = 'result-list-empty';
    empty.textContent = '尚无通过合同校验的 P201 RX1 语料。';
    list.append(empty);
    return;
  }
  for (const result of view.corpusResults) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = `result-list-item${result.result_id === view.selectedCorpusId ? ' active' : ''}`;
    const kind = document.createElement('small');
    kind.textContent = `P201 RX1 · ${result.label_provenance} / ${result.label_reason}`;
    const title = document.createElement('strong');
    title.textContent = formatFrequency(result.center_hz);
    const meta = document.createElement('span');
    meta.textContent = `${formatDate(result.created_at_ms)} · ${formatBytes(result.iq_bytes)} · seq ${result.sequence}`;
    button.append(kind, title, meta);
    button.addEventListener('click', () => selectCorpus(result.result_id));
    list.append(button);
  }
}

async function selectCorpus(resultId, { rerenderList = true } = {}) {
  view.selectedCorpusId = resultId;
  if (rerenderList) renderCorpusList();
  const result = await api(`/api/corpus/${encodeURIComponent(resultId)}`);
  if (view.selectedCorpusId !== resultId) return;
  view.selectedCorpus = result;
  renderCorpusDetail();
}

function renderCorpusDetail() {
  const empty = document.querySelector('#corpus-empty');
  const content = document.querySelector('#corpus-content');
  if (!view.selectedCorpus) {
    empty.hidden = false;
    content.hidden = true;
    return;
  }
  empty.hidden = true;
  content.hidden = false;
  const { summary, manifest, record } = view.selectedCorpus;
  setText('#corpus-provenance', `P201 RECEIVE / ${summary.label_provenance}`);
  setText('#corpus-result-title', summary.result_id);
  setText('#corpus-result-time', `${summary.captured_at_utc} · ${summary.capture_day} · application result`);
  setText('#corpus-center', formatFrequency(summary.center_hz));
  setText('#corpus-rate', formatFrequencySpan(summary.sample_rate_hz));
  setText('#corpus-bandwidth', formatFrequencySpan(summary.rf_bandwidth_hz));
  setText('#corpus-gain', `${summary.rx_gain_db} dB`);
  setText('#corpus-rms', `${summary.raw_rms_dbfs.toFixed(1)} dBFS`);
  setText('#corpus-snr', `${summary.measured_snr_db.toFixed(1)} dB`);
  setText('#corpus-iq-state', `${formatBytes(summary.iq_bytes)} ci16_le · ${summary.samples} complex samples`);
  setText('#corpus-iq-detail', `SHA-256 ${summary.iq_sha256}；大 IQ 位于 AGX 应用目录且不进入 Git。删除按钮会删除此记录和语料包；共享 IQ 仅在最后一条引用删除后释放。`);
  setText('#corpus-label', `${summary.label_provenance} / ${summary.label_reason}${record.label.numeric_id == null ? '' : ` · 数字 ID ${record.label.numeric_id} · 名称 provisional`} · ${record.split}`);
  setText('#corpus-profile', `${summary.profile_id} · ${shortHash(summary.profile_sha256)}`);
  setText('#corpus-preprocess', `${summary.preprocess_id} · ${shortHash(summary.preprocess_sha256)}`);
  setText('#corpus-session', `${summary.capture_session_id} · ${summary.plan_id}`);
  setText('#corpus-health', `seq ${summary.sequence} · ${summary.healthy ? 'healthy' : 'unhealthy'} · flags ${summary.health_flags} · drop ${summary.dropped_samples}`);
  document.querySelector('#corpus-manifest').textContent = JSON.stringify(manifest, null, 2);
  document.querySelector('#corpus-record').textContent = JSON.stringify(record, null, 2);
}

async function deleteSelectedCorpus() {
  if (!view.selectedCorpus) return;
  const { result_id: resultId, iq_bytes: iqBytes } = view.selectedCorpus.summary;
  if (!window.confirm(`删除接收语料 ${resultId}，并移除此记录的 ${formatBytes(iqBytes)} IQ 引用？其他语料的共享 IQ 和分组约束会保留。此操作无法撤销。`)) return;
  try {
    await api(`/api/corpus/${encodeURIComponent(resultId)}`, { method: 'DELETE' });
    view.selectedCorpus = null;
    view.selectedCorpusId = null;
    await loadCorpus({ selectLatest: true });
    toast('接收语料及其 IQ 引用已删除');
  } catch (error) { toast(error.message); }
}

function shortHash(value) {
  return `${value.slice(0, 12)}…`;
}

function formatDate(value) {
  return new Date(value).toLocaleString('zh-CN', { hour12: false });
}

function formatDuration(value) {
  if (value < 1000) return `${value} ms`;
  return `${(value / 1000).toFixed(value < 10000 ? 1 : 0)} s`;
}

function formatFrequency(value) {
  if (value >= 1000000000) return `${(value / 1000000000).toFixed(3)} GHz`;
  if (value >= 1000000) return `${(value / 1000000).toFixed(3)} MHz`;
  return `${Math.round(value / 1000)} kHz`;
}

function formatFrequencySpan(value) {
  if (value >= 1000000) return `${(value / 1000000).toFixed(2)} MHz`;
  return `${(value / 1000).toFixed(1)} kHz`;
}

function formatAxisFrequency(value) {
  return value >= 1000000000 ? `${(value / 1000000000).toFixed(2)}G` : `${(value / 1000000).toFixed(0)}M`;
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

async function startAuto(event) {
  event.preventDefault();
  const form = document.querySelector('#auto-form');
  const mission = document.querySelector('#auto-mission');
  if (!form.reportValidity()) return;
  const steps = Number(document.querySelector('#auto-steps').value);
  const seconds = Number(document.querySelector('#auto-seconds').value);
  await send(`/auto start --steps ${steps} --seconds ${seconds} ${mission.value.trim()}`);
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
    view.reloadTimer = setTimeout(async () => {
      try {
        await loadState();
        if (view.resultsOpen) await loadResults();
      } catch (error) { toast(error.message); }
    }, 80);
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
function kindLabel(kind) {
  return ({ system: '系统', prompt: '提示', operator: '操作员', qwen: '上游模型', plan: '已验证计划', decision: '校验依据', search: '网络搜索', execution: '执行', sweep: '扫频', cruise: '巡航', error: '错误' })[kind] || '系统';
}
function formatTokens(value) {
  return `${new Intl.NumberFormat('zh-CN').format(value)} tokens`;
}
function sessionMeta(session) {
  const compacted = session.compaction_count || 0;
  const survey = initialSurveyLabel(session.initial_survey_status, true);
  return `${statusLabel(session.status)}${survey ? ` · ${survey}` : ''}${compacted ? ` · 已压缩 ${compacted} 次` : ''}`;
}
function initialSurveyLabel(status, compact = false) {
  const labels = compact
    ? { pending: '待初扫', running: '初扫中', complete: '初扫完成', failed: '初扫失败', skipped: '' }
    : { pending: '首次扫频等待启动', running: '首次全频扫描中', complete: '首次频谱已建立', failed: '首次扫频失败', skipped: '首次扫描已关闭' };
  return labels[status] ?? (compact ? '' : '尚无扫频输出');
}
function statusLabel(status) {
  return ({ connected: '已连接', stored: '已保存', starting: '启动中', exited: '已退出', error: '错误' })[status] || status;
}

document.querySelector('#new-session').addEventListener('click', createSession);
document.querySelector('#provider-form').addEventListener('submit', saveProvider);
document.querySelector('#query-provider-models').addEventListener('click', queryProviderModels);
document.querySelector('#provider-model-list').addEventListener('change', (event) => {
  if (event.target.value) {
    document.querySelector('#provider-model').value = event.target.value;
    applySelectedModel(event.target.value);
  }
});
document.querySelector('#provider-base-url').addEventListener('input', () => {
  if (view.providerModels.length) clearModelInventory();
});
document.querySelector('#provider-api-key').addEventListener('input', () => {
  if (view.providerModels.length) clearModelInventory();
});
document.querySelector('#preset-opencode').addEventListener('click', presetOpenCode);
document.querySelector('#preset-custom').addEventListener('click', clearProviderFields);
document.querySelector('#settings-entry').addEventListener('click', toggleSettings);
document.querySelector('#settings-back').addEventListener('click', showConsole);
document.querySelector('#corpus-entry').addEventListener('click', showCorpus);
document.querySelector('#corpus-back').addEventListener('click', showConsole);
document.querySelector('#delete-corpus').addEventListener('click', deleteSelectedCorpus);
document.querySelector('#sweep-results-entry').addEventListener('click', showResults);
document.querySelector('#results-back').addEventListener('click', showConsole);
document.querySelector('#delete-result').addEventListener('click', deleteSelectedResult);
document.querySelector('#discard-settings').addEventListener('click', discardSettings);
document.querySelector('#provider-form').addEventListener('input', (event) => {
  if (event.target.closest('#survey-fields') || event.target.name === 'survey-mode') updateSurveyBudget();
  markSettingsDirty();
});
document.querySelectorAll('input[name="survey-mode"]').forEach((radio) => radio.addEventListener('change', () => {
  updateSurveyControls();
  markSettingsDirty();
}));
document.querySelector('#scroll-bottom').addEventListener('click', scrollBottom);
document.querySelector('#auto-form').addEventListener('submit', startAuto);
document.querySelectorAll('[data-command]').forEach((button) => button.addEventListener('click', () => send(button.dataset.command)));
document.querySelector('#command-form').addEventListener('submit', (event) => { event.preventDefault(); send(view.input.value); });
view.input.addEventListener('keydown', (event) => {
  if (event.key === 'Enter' && event.ctrlKey) { event.preventDefault(); send(view.input.value); }
});
window.addEventListener('beforeunload', (event) => {
  if (!view.settingsDirty) return;
  event.preventDefault();
  event.returnValue = '';
});

Promise.all([loadState({ keepScroll: false }), loadProvider(), refreshCorpusCount()])
  .then(connectEvents)
  .catch((error) => toast(error.message));


const recognitionStatuses = { classified: '已分类', rejected: '已拒识', unavailable: '不可用', error: '错误' };
const recognitionOrigins = { engineering_rx: '实收实验 · 未生产准入', experimental_replay: '实验回放 · 未生产准入', synthetic_fixture: '合成演示 · 非实测结果' };
async function loadRecognitions(before = '') {
  const epoch = ++view.recognitionEpoch;
  const records = await api(`/api/recognition-results${before ? `?before=${before}` : ''}`);
  if (epoch !== view.recognitionEpoch) return;
  view.recognitions = records;
  view.selectedRecognitionId = null;
  setText('#recognition-count', `${records.length} 条记录 · 每页最多 50 条`);
  document.querySelector('#recognition-older').hidden = records.length < 50;
  renderRecognitionList();
  document.querySelector('#recognition-empty').hidden = records.length > 0;
  document.querySelector('#recognition-content').hidden = true;
  if (records.length) await selectRecognition(records[0].id);
}
function renderRecognitionList() {
  const list = document.querySelector('#recognition-list');
  list.replaceChildren();
  for (const record of view.recognitions) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = `result-list-item${record.id === view.selectedRecognitionId ? ' active' : ''}`;
    const origin = document.createElement('small');
    origin.textContent = recognitionOrigins[record.origin] || '未知来源';
    const title = document.createElement('strong');
    title.textContent = record.observation.candidate_id;
    const meta = document.createElement('span');
    meta.textContent = `${recognitionStatuses[record.observation.status]} · ${formatDate(record.created_at_ms)}`;
    button.append(origin, title, meta);
    button.addEventListener('click', () => selectRecognition(record.id).catch(error => toast(error.message)));
    list.append(button);
  }
}
async function selectRecognition(id) {
  view.selectedRecognitionId = id;
  renderRecognitionList();
  document.querySelector('#recognition-content').hidden = true;
  const record = await api(`/api/recognition-results/${id}`);
  if (view.selectedRecognitionId !== id) return;
  const o = record.observation;
  document.querySelector('#recognition-empty').hidden = true;
  document.querySelector('#recognition-content').hidden = false;
  setText('#recognition-origin', recognitionOrigins[record.origin]);
  setText('#recognition-candidate', o.candidate_id);
  setText('#recognition-status', `${recognitionStatuses[o.status]} · ${o.status}`);
  setText('#recognition-meaning', record.origin === 'synthetic_fixture'
    ? '以下是合成演示字段，类别、置信度与拒识依据均不代表实际接收或生产准入。'
    : record.origin === 'engineering_rx' ? '这是未准入的实收实验。模型预测不是独立标签，也不是已确认的接收结论。'
    : '这是未准入的实验回放。模型预测不是独立标签，也不是已确认的接收结论。');
  const fields = document.querySelector('#recognition-fields');
  fields.replaceChildren();
  const evidence = document.querySelector('#recognition-evidence');
  evidence.replaceChildren();
  const add = (label, value, target = fields) => {
    const term = document.createElement('dt'); term.textContent = label;
    const description = document.createElement('dd'); description.textContent = value ?? '—';
    target.append(term, description);
  };
  add('应用会话', record.session_id);
  add('请求 / 会话代次', `${o.request_id} / ${o.session_generation}`);
  add('结果时间', formatDate(o.observed_at_unix_ms));
  add('原因', o.reason);
  const predicted = o.class || record.experimental_prediction;
  add(o.class ? '演示类别 ID' : '实验预测 ID', predicted?.numeric_id);
  add('文本名称可信状态', predicted ? `${predicted.name || '尚无可信名称'} · ${predicted.name_status}` : '无分类名称');
  add(record.origin === 'synthetic_fixture' ? '演示校准置信度' : '校准置信度', o.calibrated_confidence == null ? '无' : `${(o.calibrated_confidence * 100).toFixed(2)}%`);
  add('校准状态', o.calibration_status);
  if (record.uncalibrated_probability != null) add('未校准实验概率', `${(record.uncalibrated_probability * 100).toFixed(2)}% · 不能作为准确率或准入依据`);
  if (o.identity) for (const [key,value] of Object.entries(o.identity)) add(`身份 · ${key}`, value, evidence);
  if (o.source) for (const [key,value] of Object.entries(o.source)) add(`来源 · ${key}`, value, evidence);
  if (o.quality) {
    add('窗口一致率', `${o.quality.window_count} 窗 · ${(o.quality.window_agreement * 100).toFixed(0)}%`);
    add('接收质量', `健康 ${o.quality.healthy ? '是' : '否'} · 溢出 ${o.quality.overflow ? '是' : '否'} · 削顶 ${o.quality.clipped_samples} · 丢样 ${o.quality.dropped_samples}`);
  }
  if (o.timing) add('耗时', `采集 ${o.timing.capture_us} µs · 推理 ${o.timing.inference_us} µs · Worker 总计 ${o.timing.worker_total_us} µs`);
  if (o.decision_references) for (const [key,value] of Object.entries(o.decision_references)) add(`演示引用 · ${key}`, `${value.id} · ${value.sha256}`, evidence);
  add('IQ 保留', '未保留');
}
document.querySelector('#recognition-refresh').addEventListener('click', () => loadRecognitions().catch(error => toast(error.message)));
document.querySelector('#recognition-older').addEventListener('click', () => loadRecognitions(view.recognitions.at(-1)?.id).catch(error => toast(error.message)));
document.querySelector('#recognition-delete').addEventListener('click', async () => {
  const id = view.selectedRecognitionId;
  if (!id || !window.confirm('删除这条识别记录？此操作不会删除原始采集或接收语料。')) return;
  try {
    await api(`/api/recognition-results/${id}`, { method: 'DELETE' });
    if (view.selectedRecognitionId === id) view.selectedRecognitionId = null;
    await loadRecognitions();
    toast('识别记录已删除');
  } catch (error) { toast(error.message); }
});

for (const kind of ['sweeps', 'recognitions']) {
  document.querySelector(`#archive-${kind}`).addEventListener('click', () => {
    document.querySelector('#capture-archive').hidden = kind !== 'sweeps';
    document.querySelector('#recognition-archive').hidden = kind !== 'recognitions';
    for (const item of ['sweeps', 'recognitions']) document.querySelector(`#archive-${item}`).setAttribute('aria-pressed', String(item === kind));
  });
}
