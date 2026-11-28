/* ==============================================================================
 * js/ui/notice_modal.js — 应用内公告阅读窗口与收件箱
 * ------------------------------------------------------------------------------
 * 职责:
 *   · 加载云端公告与本地已读状态, 仅在启动检查结束后延迟展示
 *   · 以同一套左侧标题列表 + 右侧 Markdown 正文渲染公告模态与收件箱页面
 *   · 公告实际展示后立即持久化已读 ID, 未读项显示红点
 * 本文件提供:
 *  函数: loadNotices / openNoticeModal / closeNoticeModal / closeNoticeModalForPriority /
 *        maybeShowNoticeModal / enterInboxPage
 *  全局入口: window.__onStartupChecksDone
 * 依赖: 依赖 bootstrap/state/utils/tools, 并让位于 version_modal/settings 的高优先级窗口
 * 加载顺序: 15/23 (紧跟 version_modal)
 * ============================================================================== */
'use strict';

// ---------------- 公告状态 ----------------
let noticeModalEl = null;
let noticeItems = [];
let noticeSelectedId = '';
let noticeLoadPromise = null;
let noticeLoaded = false;
let noticeStartupDone = false;
let noticeDismissed = false;

/**
 * 把后端的一条公告规整成前端统一结构，丢弃缺 id/title 或 id 过长的脏数据。
 * @param {object} raw 后端 get_notices 返回的原始条目
 * @returns {object|null} 归一化后的公告，不合格返回 null
 */
function noticeNormalizeItem(raw) {
  if (!raw || typeof raw !== 'object') return null;
  const id = String(raw.id || '').trim();
  const title = String(raw.title || '').trim();
  if (!id || !title || id.length > 256) return null;
  return {
    id,
    title,
    timeline: String(raw.timeline || '').trim(),
    html: typeof raw.html === 'string' ? raw.html : '',
    content: String(raw.content || ''),
    is_read: !!raw.is_read,
  };
}

function noticeFindItem(noticeId) {
  return noticeItems.find(item => item.id === noticeId) || null;
}

function noticeUnreadItems() {
  return noticeItems.filter(item => !item.is_read);
}

// ---------------- 公告列表与正文 ----------------
// 模态与收件箱共用同一视图结构; 根节点通过 data-notice-view 标识, 避免两处
// 同时存在时互相抢固定 ID。页面不传关闭按钮, 因而两种载体只保留必要的差异。
/**
 * 生成公告视图的 HTML：模态与收件箱共用同一结构，仅关闭按钮/ARIA 不同。
 * @param {boolean} isPage true 表示收件箱页面，false 表示弹窗
 * @returns {string} 卡片根节点 HTML
 */
function noticeViewHtml(isPage) {
  return '<section class="notice-card' + (isPage ? ' notice-card-page' : '') + '"' +
    ' data-notice-view role="' + (isPage ? 'region' : 'dialog') + '"' +
    (isPage ? ' aria-label="收件箱"' : ' aria-modal="true" aria-label="公告"') + '>' +
    '<div class="notice-body">' +
      '<aside class="notice-side">' +
        '<div class="notice-list" data-notice-list></div>' +
      '</aside>' +
      '<div class="notice-main">' +
        '<div class="notice-meta">' +
          '<div class="notice-title-wrap">' +
            '<h2 class="notice-title" data-notice-title></h2>' +
            '<time class="notice-timeline" data-notice-timeline hidden></time>' +
          '</div>' +
          (isPage ? '' : panelCloseBtn('notice-close', 'notice-x')) +
        '</div>' +
        '<div class="md-content notice-md" data-notice-content></div>' +
      '</div>' +
    '</div>' +
  '</section>';
}

function noticeRenderList(view) {
  const list = view && view.querySelector('[data-notice-list]');
  if (!list) return;
  list.innerHTML = '';
  noticeItems.forEach(item => {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'notice-item' + (item.id === noticeSelectedId ? ' active' : '');
    button.dataset.noticeId = item.id;

    const title = document.createElement('span');
    title.className = 'notice-item-title';
    title.textContent = item.title;
    button.appendChild(title);

    if (!item.is_read) {
      const dot = document.createElement('span');
      dot.className = 'notice-unread-dot';
      button.appendChild(dot);
    }

    button.addEventListener('click', () => noticeSelect(item.id));
    list.appendChild(button);
  });
}

/**
 * 渲染选中公告的标题、时间和 Markdown 正文；后端没给 html 时用纯文本兜底。
 * @param {Element} view 公告视图根节点
 */
function noticeRenderSelection(view) {
  if (!view) return;
  const item = noticeFindItem(noticeSelectedId);
  if (!item) return;

  const title = view.querySelector('[data-notice-title]');
  if (title) title.textContent = item.title;

  const timeline = view.querySelector('[data-notice-timeline]');
  if (timeline) {
    timeline.textContent = item.timeline;
    timeline.hidden = !item.timeline;
  }

  const content = view.querySelector('[data-notice-content]');
  if (content) {
    content.innerHTML = item.html ||
      (item.content
        ? '<p>' + esc(item.content) + '</p>'
        : '<p class="notice-empty">这条公告没有正文。</p>');
  }
}

function noticeRenderView(view) {
  noticeRenderList(view);
  noticeRenderSelection(view);
}

function noticeRenderAllViews() {
  document.querySelectorAll('[data-notice-view]').forEach(noticeRenderView);
}

/**
 * 切换选中公告：同步刷新所有视图，并把首次展示的公告标记为已读。
 * @param {string} noticeId 公告 ID
 */
function noticeSelect(noticeId) {
  const item = noticeFindItem(noticeId);
  if (!item) return;
  noticeSelectedId = item.id;
  noticeRenderAllViews();

  if (!item.is_read) {
    // 已展示即视为读过; 先更新界面, 磁盘写入失败也不会打断当前阅读。
    item.is_read = true;
    document.querySelectorAll('[data-notice-view]').forEach(noticeRenderList);
    if (api && typeof api.mark_notice_read === 'function') {
      api.mark_notice_read(item.id).catch(e => {
        console.warn('公告已读状态保存失败:', e);
      });
    }
  }
}

// ---------------- 公告加载 ----------------
/**
 * 加载公告（带并发合并与成功缓存）：失败返回空列表，不影响启动流程。
 * @returns {Promise<Array<object>>} 归一化后的公告列表
 */
function loadNotices() {
  if (noticeLoadPromise) return noticeLoadPromise;
  if (noticeLoaded) return Promise.resolve(noticeItems);

  noticeLoadPromise = Promise.resolve()
    .then(() => {
      if (!api || typeof api.get_notices !== 'function') return null;
      return withTimeout(api.get_notices(), 12000, null);
    })
    .then(result => {
      const rawItems = result && Array.isArray(result.notices)
        ? result.notices
        : [];
      const seen = new Set();
      noticeItems = [];
      rawItems.forEach(raw => {
        const item = noticeNormalizeItem(raw);
        if (!item || seen.has(item.id)) return;
        seen.add(item.id);
        noticeItems.push(item);
      });
      if (!noticeSelectedId && noticeItems.length) {
        noticeSelectedId = noticeItems[0].id;
      }
      if (result && result.error) {
        console.warn('公告加载提示:', result.error);
      }
      return noticeItems;
    })
    .catch(e => {
      noticeItems = [];
      console.warn('公告加载失败:', e);
      return noticeItems;
    })
    .finally(() => {
      noticeLoaded = true;
      noticeLoadPromise = null;
      if (noticeStartupDone) maybeShowNoticeModal();
    });
  return noticeLoadPromise;
}

// ---------------- 收件箱页面 ----------------
function noticeRenderInboxState(root, message) {
  if (!root) return;
  root.innerHTML =
    '<section class="notice-card notice-card-page notice-card-state" role="region" aria-label="收件箱">' +
      '<div class="notice-page-state">' + esc(message) + '</div>' +
    '</section>';
}

function noticeRenderInbox(markRead) {
  const root = document.getElementById('inbox-notice-root');
  if (!root) return false;

  if (!noticeLoaded) {
    noticeRenderInboxState(root, '正在加载收件箱...');
    return false;
  }
  if (!noticeItems.length) {
    noticeSelectedId = '';
    noticeRenderInboxState(root, '收件箱目前没有信息。');
    return true;
  }

  if (!noticeFindItem(noticeSelectedId)) noticeSelectedId = noticeItems[0].id;
  root.innerHTML = noticeViewHtml(true);
  const view = root.querySelector('[data-notice-view]');
  noticeRenderView(view);
  if (markRead) noticeSelect(noticeSelectedId);
  return true;
}

/**
 * 进入收件箱页：能立刻渲染就渲染，否则等公告加载完成后再补。
 */
function enterInboxPage() {
  if (noticeRenderInbox(true)) return;
  loadNotices().then(() => {
    if (currentPage === 'inbox') noticeRenderInbox(true);
  });
}

// ---------------- 公告模态窗口 ----------------
/**
 * 更高优先级的窗口（版本更新/路径确认/已有公告窗）是否正在占用界面。
 * @returns {boolean} true 时本次不弹公告
 */
function noticePriorityBlocked() {
  return !!noticeModalEl ||
    !!(typeof verModalEl !== 'undefined' && verModalEl) ||
    !!(typeof pcModalEl !== 'undefined' && pcModalEl) ||
    document.body.classList.contains('path-locked');
}

/**
 * 启动检查结束后尝试弹公告：只有存在未读公告且没有高优先级窗口时才展示。
 * @returns {boolean} 是否真的打开了弹窗
 */
function maybeShowNoticeModal() {
  if (!noticeStartupDone || noticeDismissed || noticePriorityBlocked()) return false;
  if (!noticeLoaded) {
    loadNotices();
    return false;
  }
  if (!noticeUnreadItems().length) return false;
  return openNoticeModal();
}

/**
 * 创建并显示公告弹窗；默认选中第一条未读公告并立即标记已读。
 * @returns {boolean} 是否成功创建弹窗
 */
function openNoticeModal() {
  if (noticeModalEl || noticePriorityBlocked()) return false;
  const item = noticeFindItem(noticeSelectedId) || noticeUnreadItems()[0];
  if (!item) return false;

  noticeSelectedId = item.id;
  const panel = document.createElement('div');
  panel.id = 'notice-modal';
  panel.className = 'notice-overlay';
  panel.innerHTML = noticeViewHtml(false);
  document.body.appendChild(panel);
  noticeModalEl = panel;
  document.body.classList.add('modal-open');

  const closeBtn = panel.querySelector('#notice-close');
  if (closeBtn) closeBtn.onclick = closeNoticeModal;
  panel.addEventListener('click', (e) => {
    if (e.target === panel) closeNoticeModal();
  });

  noticeRenderView(panel);
  noticeSelect(item.id);
  return true;
}

/**
 * 内部关闭函数。
 * @param {boolean} suppressForSession true 表示本次启动不再自动弹公告；
 *   高优先级窗口借用公告窗时传 false，之后还能恢复展示。
 */
function _noticeClose(suppressForSession) {
  if (suppressForSession) noticeDismissed = true;
  const panel = noticeModalEl;
  noticeModalEl = null;
  if (!panel) return;
  closePanel(panel);
}

/** 用户主动关闭：本次启动不再自动弹公告。 */
function closeNoticeModal() {
  _noticeClose(true);
}

// 版本更新/游戏路径窗口优先级更高: 暂存公告, 它们关闭后仍可恢复展示。
/** 高优先级窗口借道关闭：不抑制本次启动后续的公告展示。 */
function closeNoticeModalForPriority() {
  _noticeClose(false);
}

document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape' && noticeModalEl) closeNoticeModal();
});

// 后端完成启动检查后才会放行公告; 此入口也避免公告与版本/路径窗口竞争。
window.__onStartupChecksDone = function () {
  noticeStartupDone = true;
  maybeShowNoticeModal();
};
