/*
 * FaustLauncher 构建工具 —— 前端逻辑
 *
 * 与后端（build.py 的 BuildApi）约定：
 *   · 所有方法返回 Promise；长任务（构建/上传）在**后台线程**跑，
 *     通过 get_state() / poll() 返回事件队列，前端每 150ms 轮询一次。
 *   · 事件格式：{type:'log', text, level} | {type:'step', index, state}
 *              | {type:'progress', value} | {type:'status', text, level}
 *              | {type:'upload', percent, text} | {type:'done', ok}
 */
'use strict';

const $ = (sel) => document.querySelector(sel);
const api = (window.pywebview && window.pywebview.api) || null;

let steps = [];
let pollTimer = null;

function esc(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function renderSteps() {
  const box = $('#steps');
  box.innerHTML = steps.map((s, i) =>
    '<li id="step-' + i + '" class="pending"><i>○</i><span>' + esc(s.name) + '</span></li>'
  ).join('');
}

function setStep(index, state) {
  const li = $('#step-' + index);
  if (!li) return;
  const icon = { pending: '○', running: '◉', done: '●', failed: '✕' }[state] || '○';
  li.className = state;
  li.querySelector('i').textContent = icon;
}

function setProgress(value, cls) {
  const v = Math.max(0, Math.min(100, Number(value) || 0));
  const bar = $('#bar');
  bar.style.width = v + '%';
  bar.className = cls || '';
  $('#pct').textContent = Math.round(v) + '%';
}

function appendLog(text, level) {
  const box = $('#log');
  const cls = level === 'ok' ? 'ok' : level === 'bad' ? 'bad' : level === 'warn' ? 'warn' : '';
  const span = document.createElement('span');
  if (cls) span.className = cls;
  span.textContent = text;
  box.appendChild(span);
  box.scrollTop = box.scrollHeight;
}

function handleEvent(ev) {
  if (!ev || !ev.type) return;
  switch (ev.type) {
    case 'log': appendLog(ev.text || '', ev.level); break;
    case 'step': setStep(ev.index, ev.state); break;
    case 'progress': setProgress(ev.value, ev.cls); break;
    case 'status':
      $('#status').textContent = ev.text || '';
      $('#phase').textContent = ev.text || $('#phase').textContent;
      break;
    case 'upload': {
      $('#upload').hidden = false;
      const v = Math.max(0, Math.min(100, Number(ev.percent) || 0));
      $('#up-bar').style.width = v + '%';
      $('#up-pct').textContent = Math.round(v) + '%';
      if (ev.text) $('#up-status').textContent = ev.text;
      break;
    }
    case 'done': onDone(!!ev.ok); break;
    default: break;
  }
}

function onDone(ok) {
  $('#phase').textContent = ok ? '构建完成' : '构建失败';
  $('#phase').className = 'chip ' + (ok ? 'ok' : 'bad');
  setProgress(ok ? 100 : 0, ok ? 'ok' : 'bad');
  $('#btn-open').disabled = !ok;
  $('#btn-publish').disabled = !ok;
  $('#btn-close').textContent = ok ? '关闭' : '关闭';
}

async function poll() {
  if (!api) return;
  try {
    const res = await api.poll();
    // 首次拿到步骤表
    if (res && res.steps && !steps.length) { steps = res.steps; renderSteps(); }
    (res && res.events || []).forEach(handleEvent);
  } catch (e) { /* 窗口关闭途中会抛错，忽略 */ }
}

function startPolling() {
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = setInterval(poll, 150);
}

async function boot() {
  if (!api) {
    appendLog('pywebview 未就绪：请用 build.py 启动本工具。\n', 'bad');
    return;
  }
  const st = await api.get_state();
  steps = (st && st.steps) || [];
  renderSteps();
  $('#ver').textContent = (st && st.version) || '—';
  $('#phase').textContent = '构建中…';
  startPolling();
  await api.start_build();          // 与原 Tk 版一致：打开即自动开始构建
}

$('#btn-publish').addEventListener('click', async () => {
  if (!api) return;
  $('#btn-publish').disabled = true;
  $('#upload').hidden = false;
  $('#up-status').textContent = '开始上传…';
  await api.publish();
});
$('#btn-open').addEventListener('click', () => api && api.open_build_dir());
$('#btn-close').addEventListener('click', () => api && api.close());
$('#btn-clear').addEventListener('click', () => { $('#log').textContent = ''; });

if (window.pywebview && window.pywebview.api) boot();
else window.addEventListener('pywebviewready', boot);
