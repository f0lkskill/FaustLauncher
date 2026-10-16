/* ==============================================================================
 * js/ui/terminal.js — 终端面板: 着色渲染 + 日志追加
 * ------------------------------------------------------------------------------
 * 职责:
 *   · ansiToHtml: 把一行日志转成 HTML(后端若带 ANSI 颜色码则解析上色)
 *   · addLog: 追加一行到终端 DOM, 自动滚动与行数上限, 同时转发给流水线关键字解析
 * 本文件提供:
 *  函数: ansiToHtml / addLog
 *  状态/常量: ANSI_COLORS / termBody / termAutoScroll
 * 依赖: 依赖 bootstrap($) 与 utils(esc); handlePipelineLog 在 pipeline.js 中实现(运行时调用)
 * 加载顺序: 9/22    (拆分自原 app.js 行 398-452)
 *
 * 统一约定: 时间戳、区域与级别都由后端写进这一行, 形如
 *   [2026-10-14 18:28:44.350] [用户API] [WARN ] [user_api.py:141]: 已载入本地登录态
 * 前端只负责上色和排版, 不再自己补时间戳、也不再按关键字猜级别——否则同一行
 * 在 cmd 窗口、日志文件与终端面板里就会长得不一样。
 * ============================================================================== */
'use strict';

// ---------------- ANSI 转 HTML ----------------
const ANSI_COLORS = {
  30: '#555a68', 31: '#ef4444', 32: '#10b981', 33: '#f59e0b',
  34: '#38bdf8', 35: '#c084fc', 36: '#22d3ee', 37: '#e8ecf4',
  90: '#6b7689', 91: '#f87171', 92: '#34d399', 93: '#fbbf24',
  94: '#60a5fa', 95: '#d8b4fe', 96: '#67e8f9', 97: '#ffffff',
};

// 级别直接读后端行里的 [INFO] / [WARN] / [ERROR] / [DEBUG] 标记(后端是唯一的判定点)
function levelClass(text) {
  if (/\[ERROR\]/.test(text)) return 'error';
  if (/\[WARN\s*\]/.test(text)) return 'warning';
  if (/\[DEBUG\]/.test(text)) return 'debug';
  return 'info';
}

function ansiToHtml(text) {
  const raw = String(text);
  if (raw.indexOf('\x1b[') < 0) {
    // 后端没给颜色时走这条快路; 顺带保证整行都被转义。
    return { html: esc(raw), cls: levelClass(raw) };
  }
  const parts = raw.split(/\x1b\[/);
  let out = esc(parts[0]);
  for (let i = 1; i < parts.length; i++) {
    const m = /^([0-9;]*)m/.exec(parts[i]);
    if (!m) { out += esc(parts[i]); continue; }
    const codes = m[1] ? m[1].split(';') : [];
    const rest = parts[i].slice(m[0].length);
    // 0 是复位: 必须真的闭合上一个 span, 否则后面的颜色会盖住前面那些列。
    if (codes.includes('0')) { out += '</span>' + esc(rest); continue; }
    let style = '';
    if (codes.includes('1')) style += 'font-weight:bold;';
    for (const c of codes) {
      if (ANSI_COLORS[c]) { style += 'color:' + ANSI_COLORS[c] + ';'; break; }
      if (c >= 40 && c <= 47) style += 'background:#2d3650;';
    }
    out += '<span style="' + style + '">' + esc(rest) + '</span>';
  }
  return { html: out, cls: levelClass(raw) };
}

// ---------------- 终端 ----------------
const termBody = $('#term-body');
let termAutoScroll = true;

function addLog(text) {
  const line = String(text == null ? '' : text).replace(/\r/g, '');
  if (!line.trim()) return;
  const { html, cls } = ansiToHtml(line);
  const div = document.createElement('div');
  div.className = 'term-line ' + cls;
  // 时间戳由后端随行给出, 这里不再插一个前端时间, 否则一行会出现两个时间。
  div.innerHTML = html;
  if (termBody) {
    termBody.appendChild(div);
    while (termBody.children.length > 1500) termBody.firstChild.remove();
    if (termAutoScroll) termBody.scrollTop = termBody.scrollHeight;
  }
  // 流水线关键字解析要的是纯文本: ANSI 转义序列夹在行里会让关键字匹配失灵。
  handlePipelineLog(line.replace(/\x1b\[[0-9;]*m/g, ''));
}
