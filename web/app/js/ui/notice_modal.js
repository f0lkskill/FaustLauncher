/* ==============================================================================
 * js/ui/notice_modal.js — 应用内公告阅读窗口
 * ------------------------------------------------------------------------------
 * 职责:
 *   · 加载云端公告与本地已读状态, 仅在启动检查结束后延迟展示
 *   · 以紧凑的左侧标题列表 + 右侧 Markdown 正文呈现公告
 *   · 公告实际展示后立即持久化已读 ID, 未读项显示红点
 * 本文件提供:
 *  函数: loadNotices / openNoticeModal / closeNoticeModal / closeNoticeModalForPriority /
 *        maybeShowNoticeModal
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
function noticeRenderList() {
  const list = document.getElementById('notice-list');
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

function noticeRenderSelection() {
  const item = noticeFindItem(noticeSelectedId);
  if (!item) return;

  const title = document.getElementById('notice-title');
  if (title) title.textContent = item.title;

  const timeline = document.getElementById('notice-timeline');
  if (timeline) {
    timeline.textContent = item.timeline;
    timeline.hidden = !item.timeline;
  }

  const content = document.getElementById('notice-content');
  if (content) {
    content.innerHTML = item.html ||
      (item.content
        ? '<p>' + esc(item.content) + '</p>'
        : '<p class="notice-empty">这条公告没有正文。</p>');
  }
}

function noticeSelect(noticeId) {
  const item = noticeFindItem(noticeId);
  if (!item) return;
  noticeSelectedId = item.id;
  noticeRenderList();
  noticeRenderSelection();

  if (!item.is_read) {
    // 已展示即视为读过; 先更新界面, 磁盘写入失败也不会打断当前阅读。
    item.is_read = true;
    noticeRenderList();
    if (api && typeof api.mark_notice_read === 'function') {
      api.mark_notice_read(item.id).catch(e => {
        console.warn('公告已读状态保存失败:', e);
      });
    }
  }
}

// ---------------- 公告加载 ----------------
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

// ---------------- 公告模态窗口 ----------------
function noticePriorityBlocked() {
  return !!noticeModalEl ||
    !!(typeof verModalEl !== 'undefined' && verModalEl) ||
    !!(typeof pcModalEl !== 'undefined' && pcModalEl) ||
    document.body.classList.contains('path-locked');
}

function maybeShowNoticeModal() {
  if (!noticeStartupDone || noticeDismissed || noticePriorityBlocked()) return false;
  if (!noticeLoaded) {
    loadNotices();
    return false;
  }
  if (!noticeUnreadItems().length) return false;
  return openNoticeModal();
}

function openNoticeModal() {
  if (noticeModalEl || noticePriorityBlocked()) return false;
  const item = noticeFindItem(noticeSelectedId) || noticeUnreadItems()[0];
  if (!item) return false;

  noticeSelectedId = item.id;
  const panel = document.createElement('div');
  panel.id = 'notice-modal';
  panel.className = 'notice-overlay';
  panel.innerHTML =
  '<section class="notice-card" role="dialog" aria-modal="true">' +
    '<div class="notice-body">' +
      '<aside class="notice-side">' +
        '<div class="notice-list" id="notice-list"></div>' +
      '</aside>' +
      '<main class="notice-main">' +
        '<div class="notice-meta">' +
          '<div class="notice-title-wrap">' +
            '<h2 class="notice-title" id="notice-title"></h2>' +
            '<time class="notice-timeline" id="notice-timeline" hidden></time>' +
          '</div>' +
          panelCloseBtn('notice-close', 'notice-x') +
        '</div>' +
        '<div class="md-content notice-md" id="notice-content"></div>' +
      '</main>' +
    '</div>' +
  '</section>';
  document.body.appendChild(panel);
  noticeModalEl = panel;
  document.body.classList.add('modal-open');

  const closeBtn = document.getElementById('notice-close');
  if (closeBtn) closeBtn.onclick = closeNoticeModal;
  panel.addEventListener('click', (e) => {
    if (e.target === panel) closeNoticeModal();
  });

  noticeRenderList();
  noticeSelect(item.id);
  return true;
}

function _noticeClose(suppressForSession) {
  if (suppressForSession) noticeDismissed = true;
  const panel = noticeModalEl;
  noticeModalEl = null;
  if (!panel) return;
  closePanel(panel);
}

function closeNoticeModal() {
  _noticeClose(true);
}

// 版本更新/游戏路径窗口优先级更高: 暂存公告, 它们关闭后仍可恢复展示。
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
