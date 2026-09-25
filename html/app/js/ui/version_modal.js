/* ==============================================================================
 * js/ui/version_modal.js — 应用内版本更新二级模态窗口
 * ------------------------------------------------------------------------------
 * 职责:
 *   · 普通更新提示可关闭; 强制更新不可关闭并自动开始下载
 *   · 下载进度条/速度/阶段文案, 以及 window.__onVersionModal 推送入口
 * 本文件提供:
 *  函数: closeVersionModal / verVersionLine / verLinkHost / verRenderFoot / verProgressShow / verSetLabel / verSetProgress / verSetError / startVersionDownload / updateVersionModalProgress / openVersionModal
 *  状态/常量: verModalEl / verForced / verDownloading
 *  全局入口: window.__onVersionModal
 * 依赖: 依赖 bootstrap/state/utils
 * 加载顺序: 14/22    (拆分自原 app.js 行 3573-3771)
 * ============================================================================== */
'use strict';

// ---------------- 版本更新模态窗口 (应用内二级模态) ----------------
// 检测到新版本: 立即弹出并强制下载更新 (无关闭按钮, 点击遮罩/Esc 均无效);
// 已是最新版本: 同样展示版本信息, 右上角提供关闭按钮 (✕)。
// 视觉: 品牌图标 + 版本跨度 (等宽数字) + 细分隔线 + 无边框文档区, 样式完全跟随 App。
let verModalEl = null;        // 当前模态 DOM
let verForced = false;        // 强制更新模式 (窗口不可取消)
let verDownloading = false;   // 更新包下载中

function closeVersionModal() {
  if (!verModalEl || verForced) return;   // 强制更新: 窗口不允许关闭
  const el = verModalEl;
  verModalEl = null;
  closePanel(el);
}

// 版本跨度: 旧 → 新 (等宽数字, 信息本身就是设计)
function verVersionLine(d) {
  if (d.has_update && d.current && d.latest) {
    return '<span class="ver-from">' + esc(d.current) + '</span>' +
           '<span class="ver-to">' + esc(d.latest) + '</span>';
  }
  return '<span class="ver-to">' + esc(d.latest || d.current || '未知版本') + '</span>';
}

// 链接只展示域名, 完整地址放 title
function verLinkHost(url) {
  try { return new URL(url).host || String(url); } catch (e) { return String(url || ''); }
}

// 底部操作区: 强制更新不提供任何"取消"入口, 仅在失败时给"重新下载"
function verRenderFoot(opts) {
  opts = opts || {};
  const foot = document.getElementById('ver-foot');
  if (!foot) return;
  let html = '';
  if (opts.retry) html = '<button class="btn btn-primary" id="ver-retry">重新下载</button>';
  else if (opts.actions) {
    html = '<button class="btn btn-ghost" id="ver-later">稍后</button>' +
           '<button class="btn btn-primary" id="ver-now">立即下载更新</button>';
  }
  foot.innerHTML = html;
  foot.hidden = !html;
  const retry = document.getElementById('ver-retry');
  if (retry) retry.onclick = () => startVersionDownload();
  const later = document.getElementById('ver-later');
  if (later) later.onclick = closeVersionModal;
  const now = document.getElementById('ver-now');
  if (now) now.onclick = () => startVersionDownload();
}

function verProgressShow(show) {
  const el = document.getElementById('ver-progress');
  if (!el) return;
  if (!show) { el.hidden = true; return; }
  if (!el.hidden) return;          // 已显示: 不重复触导入场动画
  el.hidden = false;
  el.classList.remove('ver-in');
  void el.offsetWidth;             // 强制重排, 让入场动画可重复触发
  el.classList.add('ver-in');
}

function verSetLabel(text, state) {
  const el = document.getElementById('ver-progress-label');
  if (!el) return;
  el.textContent = text || '';
  el.className = 'ver-progress-label' + (state ? ' ' + state : '');
}

function verSetProgress(d) {
  d = d || {};
  const pct = Math.max(0, Math.min(100, Number(d.percent) || 0));
  const fill = document.getElementById('ver-fill');
  if (fill) fill.style.width = pct.toFixed(1) + '%';
  const pctEl = document.getElementById('ver-pct');
  if (pctEl) pctEl.textContent = pct.toFixed(1) + '%';
  const meta = document.getElementById('ver-meta');
  if (meta) {
    const total = Number(d.total) || 0;
    meta.textContent = total > 0
      ? fmtBytes(d.downloaded || 0) + ' / ' + fmtBytes(total) +
        (d.speed ? '   ·   ' + fmtSpeed(d.speed) : '')
      : '';
  }
}

function verSetError(text) {
  verDownloading = false;
  verProgressShow(true);
  const wrap = document.getElementById('ver-progress');
  if (wrap) wrap.classList.add('error');
  verSetLabel(text || '更新失败, 请重试', 'error');
  verRenderFoot({ retry: true });
}

function startVersionDownload() {
  if (!api || !verModalEl || verDownloading) return;
  verDownloading = true;
  const wrap = document.getElementById('ver-progress');
  if (wrap) wrap.classList.remove('error');
  verProgressShow(true);
  verSetProgress({ percent: 0 });
  verSetLabel('正在获取更新包…');
  verRenderFoot({});
  api.start_version_update().then(r => {
    if (r && r.error) verSetError(r.error);
  }).catch(e => verSetError(String(e)));
}

// 后端推送下载进度 (__onEvent('version_update'))
function updateVersionModalProgress(d) {
  if (!verModalEl) return;
  d = d || {};
  const stage = d.stage || 'progress';
  if (stage === 'error') { verSetError(d.text); return; }
  verProgressShow(true);
  const wrap = document.getElementById('ver-progress');
  if (wrap) wrap.classList.remove('error');
  if (d.text) verSetLabel(d.text, stage === 'ready' ? 'ok' : '');
  if (stage === 'progress') verSetProgress(d);
  else if (stage === 'ready') {
    verDownloading = false;
    verSetProgress({ percent: 100, downloaded: d.downloaded, total: d.total, speed: 0 });
    toastTop('更新包已就绪, 正在重启并安装新版本…', 'success', 6000);
  }
}

function openVersionModal(d) {
  d = d || {};
  const forced = !!(d.forced && d.has_update && d.can_update);
  if (verModalEl) {
    // 已在展示: 强制更新窗口优先 (替换信息窗口), 其余情况不重复弹出
    if (verForced || !forced) return;
    const old = verModalEl;
    verModalEl = null;
    closePanel(old);
  }
  verForced = forced;
  verDownloading = false;

  const panel = document.createElement('div');
  panel.id = 'ver-modal';
  panel.className = 'ver-overlay' + (forced ? ' forced' : '');
  panel.innerHTML =
    '<div class="ver-card">' +
      (forced ? '<span class="ver-accent" aria-hidden="true"></span>' : '') +
      '<header class="ver-head">' +
        '<img class="ver-mark" data-project-icon src="' + PROJECT_ICON + '" alt="" draggable="false">' +
        '<div class="ver-head-main">' +
          '<div class="ver-eyebrow">' + esc(d.title || (d.has_update ? '发现新版本' : '已是最新版本')) + '</div>' +
          '<div class="ver-vers">' + verVersionLine(d) + '</div>' +
        '</div>' +
        (forced ? '' : '<button class="ver-x" id="ver-close" title="关闭" aria-label="关闭">✕</button>') +
      '</header>' +
      '<div class="ver-rule"></div>' +
      '<div class="ver-submeta">' +
        '<span class="ver-submeta-title">更新说明</span>' +
        (d.date ? '<span class="ver-submeta-date">' + esc(d.date) + '</span>' : '') +
        (d.url
          ? '<a class="ver-submeta-link" href="' + esc(d.url) + '" target="_blank" rel="noreferrer" title="' +
            esc(d.url) + '">' + esc(verLinkHost(d.url)) + ' ↗</a>'
          : '') +
      '</div>' +
      '<div class="ver-doc"><div class="ver-doc-inner">' +
        (d.html || '<p class="ver-empty">这次更新没有留下说明。</p>') +
      '</div></div>' +
      '<div class="ver-progress" id="ver-progress" hidden>' +
        '<div class="ver-progress-head">' +
          '<span class="ver-progress-label" id="ver-progress-label">准备下载更新包</span>' +
          '<span class="ver-progress-pct" id="ver-pct">0.0%</span>' +
        '</div>' +
        '<div class="ver-bar"><span class="ver-bar-fill" id="ver-fill"></span></div>' +
        '<div class="ver-progress-meta" id="ver-meta"></div>' +
      '</div>' +
      '<footer class="ver-foot" id="ver-foot" hidden></footer>' +
    '</div>';
  document.body.appendChild(panel);
  verModalEl = panel;

  if (!forced) {
    const closeBtn = document.getElementById('ver-close');
    if (closeBtn) closeBtn.onclick = closeVersionModal;
    // 信息模式: 点击遮罩 / Esc / 按钮均可关闭
    panel.addEventListener('click', (e) => { if (e.target === panel) closeVersionModal(); });
    if (d.has_update && d.can_update) verRenderFoot({ actions: true });
  }
  // 强制更新: 打开后立即自动开始下载 (用户可同时阅读更新内容)
  if (d.auto_start) {
    setTimeout(() => { if (verModalEl === panel) startVersionDownload(); }, 900);
  }
}

// Esc 关闭 (仅非强制模式生效)
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape' && verModalEl && !verForced) closeVersionModal();
});

// 后端推送入口: window.__onVersionModal(payload)
window.__onVersionModal = function (payload) { openVersionModal(payload); };
