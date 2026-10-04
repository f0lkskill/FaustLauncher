/*
 * FaustLauncher 构建工具 —— 前端逻辑
 *
 * 与后端（build.py 的 BuildApi）约定：
 *   · 所有方法返回 Promise；长任务（构建/上传）在**后台线程**跑，
 *     通过 poll() 返回事件队列，前端每 150ms 轮询一次。
 *   · 事件格式：{type:'log', text, level} | {type:'step', index, state}
 *              | {type:'progress', value, cls} | {type:'status', text, level}
 *              | {type:'upload', percent, text} | {type:'done', ok}
 */
'use strict';

const $ = (sel) => document.querySelector(sel);

// ⚠ pywebview 的 api 是**注入的**，注入时机可能早于也可能晚于本脚本 ——
// 所以不能在这里抓成常量（那样永远是 null，界面就会报"pywebview 未就绪"）。
// 与 web/version_update、web/extension_tools 同一套写法：在事件里**重新取**，
// 并且立刻也试一次；再补一个短轮询兜底（个别环境不发 pywebviewready）。
let api = null;
let steps = [];
let pollTimer = null;

function esc(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function renderSteps() {
  $('#steps').innerHTML = steps.map((s, i) =>
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
      if (ev.text) $('#phase').textContent = ev.text;
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
}

async function poll() {
  if (!api) return;
  try {
    const res = await api.poll();
    if (res && res.steps && !steps.length) { steps = res.steps; renderSteps(); }
    (res && res.events || []).forEach(handleEvent);
  } catch (e) { /* 关闭窗口途中会抛错，忽略 */ }
}

async function boot() {
  const st = await api.get_state();
  steps = (st && st.steps) || [];
  renderSteps();
  $('#ver').textContent = (st && st.version) || '—';
  $('#phase').textContent = '构建中…';
  clearInterval(pollTimer);
  pollTimer = setInterval(poll, 150);
  await api.start_build();          // 与原 Tk 版一致：打开即自动开始构建
}

function tryInitApi() {
  if (api) return true;
  const wv = window.pywebview;
  if (wv && wv.api && typeof wv.api.get_state === 'function') {
    api = wv.api;
    boot().catch((e) => appendLog('初始化失败：' + e + '\n', 'bad'));
    return true;
  }
  return false;
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

window.addEventListener('pywebviewready', tryInitApi);
if (!tryInitApi()) {
  let tries = 0;                       // 兜底：个别环境不发 pywebviewready
  const timer = setInterval(() => {
    if (tryInitApi() || ++tries > 50) clearInterval(timer);
  }, 100);
}
