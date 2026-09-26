/* ==============================================================================
 * js/ui/terminal.js — 终端面板: ANSI 着色渲染 + 日志追加
 * ------------------------------------------------------------------------------
 * 职责:
 *   · ansiToHtml: 把后端日志里的 ANSI 颜色码转成 HTML, 并推断语义色(成功/警告/错误/进行中)
 *   · addLog: 带时间戳写入终端 DOM, 自动滚动与行数上限, 同时转发给流水线关键字解析
 * 本文件提供:
 *  函数: ansiToHtml / addLog
 *  状态/常量: ANSI_COLORS / termBody / termAutoScroll
 * 依赖: 依赖 bootstrap($) 与 utils(esc); handlePipelineLog 在 pipeline.js 中实现(运行时调用)
 * 加载顺序: 9/22    (拆分自原 app.js 行 398-452)
 * ============================================================================== */
'use strict';

// ---------------- ANSI 转 HTML ----------------
const ANSI_COLORS = {
  30: '#555a68', 31: '#ef4444', 32: '#10b981', 33: '#f59e0b',
  34: '#38bdf8', 35: '#c084fc', 36: '#22d3ee', 37: '#e8ecf4',
  90: '#6b7689', 91: '#f87171', 92: '#34d399', 93: '#fbbf24',
  94: '#60a5fa', 95: '#d8b4fe', 96: '#67e8f9', 97: '#ffffff',
};

function ansiToHtml(text) {
  const parts = String(text).split(/\x1b\[/);
  let out = parts[0];
  let cls = 'info';
  for (let i = 1; i < parts.length; i++) {
    const m = /^([0-9;]*)m/.exec(parts[i]);
    if (!m) { out += parts[i]; continue; }
    const codes = m[1] ? m[1].split(';') : [];
    let rest = parts[i].slice(m[0].length);
    if (codes.includes('0')) { cls = 'info'; out += '</span>'.repeat(0) + rest; continue; }
    let style = '';
    if (codes.includes('1')) style += 'font-weight:bold;';
    for (const c of codes) {
      if (ANSI_COLORS[c]) { style += 'color:' + ANSI_COLORS[c] + ';'; break; }
      if (c >= 40 && c <= 47) style += 'background:#2d3650;';
    }
    out += '<span style="' + style + '">' + esc(rest) + '</span>';
  }
  // 简易语义色
  if (/❌|错误|失败|出错/.test(out)) cls = 'error';
  else if (/✓|成功|完成|安装到/.test(out)) cls = 'success';
  else if (/警告/.test(out)) cls = 'warning';
  else if (/开始|正在|下载|检查/.test(out)) cls = 'wait';
  return { html: out, cls };
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
  const t = new Date();
  const ts = t.toTimeString().slice(0, 8);
  div.innerHTML = '<span class="t-time">[' + ts + ']</span>' + html;
  if (termBody) {
    termBody.appendChild(div);
    while (termBody.children.length > 1500) termBody.firstChild.remove();
    if (termAutoScroll) termBody.scrollTop = termBody.scrollHeight;
  }
  handlePipelineLog(line);
}
