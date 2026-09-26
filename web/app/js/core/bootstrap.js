/* ==============================================================================
 * js/core/bootstrap.js — 启动基座: 环境探测 / 全局错误兜底 / 选择器与诊断工具
 * ------------------------------------------------------------------------------
 * 职责:
 *   · 前端全局错误浮层(捕获 error + unhandledrejection, 无需 DevTools 即可看到报错)
 *   · 主页两张卡片的 loading 圆圈兜底定时器(内容感知 800ms + 硬超时 30s)
 *   · pywebview 桥接对象探测(api / IS_BROWSER), 浏览器直开时 api 为 null
 *   · 窗口内诊断工具 window.__diag / __hideCircles 与 $ / $$ 选择器别名
 * 本文件提供:
 *  状态/常量: api / IS_BROWSER / $ / $$
 *  全局入口: window.__diag / window.__hideCircles
 * 依赖: 必须最先加载(其它所有文件都依赖 $ / $$ / api / IS_BROWSER)
 * 加载顺序: 1/22    (拆分自原 app.js 行 9-104)
 * ============================================================================== */
'use strict';

(function _errOverlay() {
  function show(tag, msg) {
    try {
      let box = document.getElementById('js-err');
      if (!box) {
        box = document.createElement('div');
        box.id = 'js-err';
        box.style.cssText = 'position:fixed;bottom:6px;left:6px;right:6px;z-index:99999;' +
          'background:rgba(140,20,20,.96);color:#ffd;font:12px/1.45 monospace;' +
          'padding:6px 10px;border-radius:6px;white-space:pre-wrap;max-height:38vh;overflow:auto;';
        document.body.appendChild(box);
      }
      box.textContent = (box.textContent ? box.textContent + '\n---\n' : '') +
        '[' + tag + '] ' + msg;
    } catch (_) {}
  }
  window.addEventListener('error', function (e) {
    show('JS', (e.message || '') + (e.filename ? '\n@ ' + e.filename + ':' + (e.lineno || '') : ''));
  });
  window.addEventListener('unhandledrejection', function (e) {
    const r = e && e.reason;
    const msg = (r && r.message) || String(r);
    const st = (r && r.stack) ? '\n' + r.stack.split('\n').slice(0, 6).join('\n') : '';
    show('ASYNC', msg + st);
  });
})();

// 兜底: 仅当极端卡死时才强制结束主页 loading (30 秒), 避免破坏慢速加载的圆圈
setTimeout(function () {
  ['stat-version-card', 'rec-card'].forEach(function (id) {
    var f = document.getElementById(id);
    if (f) f.classList.remove('loading');
  });
}, 30000);

// 兜底: 按内容是否已渲染来决定是否结束 loading (移除圆圈)。
// 一旦 changelog-body / rec-body 不再是 "加载中" 占位文本, 即强制移除对应卡片的 loading 类。
// 用 trim() 排除换行/空格等空白节点, 避免空卡片被误判为"已加载"
setInterval(function () {
  var ch = document.getElementById('changelog-body');
  if (ch && ch.textContent.trim() && ch.textContent.indexOf('加载中') === -1) {
    var f1 = document.getElementById('stat-version-card');
    if (f1) f1.classList.remove('loading');
  }
  var rb = document.getElementById('rec-body');
  if (rb && rb.textContent.trim() && rb.textContent.indexOf('加载中') === -1) {
    var f2 = document.getElementById('rec-card');
    if (f2) f2.classList.remove('loading');
  }
}, 800);

let api = (window.pywebview && window.pywebview.api) ? window.pywebview.api : null;

// 诊断: 在 DevTools Console 敲 window.__diag() 查看圆圈元素详情
window.__diag = function () {
  var out = [];
  ['stat-version-card', 'rec-card'].forEach(function (id) {
    var f = document.getElementById(id);
    if (!f) { out.push(id + ': 不存在'); return; }
    var sp = f.querySelector('.frame-spinner');
    var cs = sp ? getComputedStyle(sp) : null;
    out.push(id + ': class=[' + f.className + ']' +
      (sp ? (' spinner=[display:' + cs.display + ';position:' + cs.position + '] html=' + sp.outerHTML.slice(0, 60)) : ' spinner=无'));
  });
  var spins = document.querySelectorAll('.frame-spinner');
  out.push('页面 .frame-spinner 总数=' + spins.length);
  spins.forEach(function (s) {
    var cs = getComputedStyle(s);
    out.push('  el: display=' + cs.display + ' parent=' + (s.parentElement ? s.parentElement.id || s.parentElement.className : '?'));
  });
  var rot = document.querySelectorAll('.frame-spinner span, .pipe-step.active .st-ico, [class*=spin]');
  out.push('旋转元素数=' + rot.length);
  var cb = document.getElementById('changelog-body');
  var rb = document.getElementById('rec-body');
  out.push('changelog-body text=[' + (cb ? cb.textContent.trim().slice(0, 60) : '?') + ']');
  out.push('rec-body text=[' + (rb ? rb.textContent.trim().slice(0, 60) : '?') + ']');
  return out.join('\n');
};

// 诊断: 强制隐藏所有圆圈 (测试用)
window.__hideCircles = function () {
  var n = 0;
  document.querySelectorAll('.frame-spinner').forEach(function (s) {
    s.style.display = 'none'; n++;
  });
  ['stat-version-card', 'rec-card'].forEach(function (id) {
    var f = document.getElementById(id);
    if (f) f.classList.remove('loading');
  });
  return '已隐藏 ' + n + ' 个圆圈';
};
let IS_BROWSER = !api;

const $ = (s, r) => (r || document).querySelector(s);
const $$ = (s, r) => [...(r || document).querySelectorAll(s)];
