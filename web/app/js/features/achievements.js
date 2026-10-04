/* ==============================================================================
 * js/features/achievements.js — 成就页
 * ------------------------------------------------------------------------------
 * 职责:
 *   · 列出全部成就与**本地**完成状态 (后端 get_achievements: 只读本地用户文件)
 *   · 分区: 已完成 / 未完成 (左) + 搜索 + 分页, 卡片排列沿用下载中心/资源管理的 res-* 样式
 *   · 刷新时机: 切入本页时 / 窗口重新聚焦且停在本页时 / 点右上角"云端同步刷新"。
 *     现阶段这几种刷新**都是本地刷新**; 云端同步那一步等接口就位后再挂上去。
 * 本文件提供:
 *  状态: achTab / achPage / achItems
 *  函数: enterAchievementPage / bindAchievementEvents / refreshAchievements /
 *        syncAchievementsOnFocus / renderAchList
 * 依赖: core/* (api / $ / esc / iconSvg / currentPage); 样式复用 resources 的 res-*
 * 加载顺序: 位于 user.js 之后、app.js 之前
 * ============================================================================== */
'use strict';

let achTab = 'done';            // 当前分区: done | todo
let achPage = 1;                // 当前页
const ACH_PAGE_SIZE = 5;        // 每页条数 (与资源管理/下载中心一致)
let achSearch = '';             // 搜索词
let achItems = [];              // 后端返回的完整列表 (未过滤)
let achLoaded = false;          // 是否已经拿到过一次数据
let achRefreshing = null;       // 正在进行的刷新 Promise (合并重复请求)
let achRefreshedAt = 0;         // 上次刷新完成时间
const ACH_REFRESH_GAP = 400;    // ms, 同一次操作的重复刷新合并窗口
const ACH_FOCUS_GAP = 800;      // ms, 聚焦刷新的合并窗口 (alt-tab 来回切时不刷接口)
let _lastAchFocusSync = 0;

// 稀有度中文名 (与成就系统 RARITY_NAMES_ZH 对应)
const ACH_RARITY_ZH = {
  common: '普通', uncommon: '优秀', rare: '稀有',
  epic: '史诗', legendary: '传说', mythic: '神话',
};

// ---------------- 分区 / 计数 ----------------

function achCount(tab) {
  return achItems.filter(it => (tab === 'done' ? !!it.completed : !it.completed)).length;
}

// 计数直接写在分区按钮上, 不再单占一行
function renderAchCounts() {
  const d = $('#ach-count-done');
  const t = $('#ach-count-todo');
  if (d) d.textContent = String(achCount('done'));
  if (t) t.textContent = String(achCount('todo'));
}

function syncAchTabs() {
  $$('#page-achievement .res-tab').forEach(b => {
    b.classList.toggle('active', (b.dataset.ach === 'todo' ? 'todo' : 'done') === achTab);
  });
}

// ---------------- 数据 ----------------

// 拉一次本地成就清单。并发调用共用同一个 Promise; 失败只提示、保留旧数据。
async function refreshAchievements() {
  if (achRefreshing) return achRefreshing;
  if (!api) {                       // 浏览器预览模式: 没有后端, 直接给空列表
    achItems = [];
    achLoaded = true;
    achRefreshedAt = Date.now();
    renderAchAll();
    return [];
  }
  achRefreshing = (async () => {
    try {
      const r = await api.get_achievements();
      if (r && r.ok === false) {
        toast(r.error || '读取成就失败', 'error');
      } else if (r && Array.isArray(r.items)) {
        achItems = r.items;
        achLoaded = true;
      }
    } catch (e) {
      toast('读取成就失败: ' + e, 'error');
    } finally {
      achRefreshing = null;
      achRefreshedAt = Date.now();
      renderAchAll();
    }
    return achItems;
  })();
  return achRefreshing;
}

function achNeedsFetch() {
  return !achLoaded || (Date.now() - achRefreshedAt >= ACH_REFRESH_GAP);
}

// ---------------- 渲染 ----------------

function renderAchAll() {
  renderAchCounts();
  syncAchTabs();
  renderAchList();
}

function renderAchList() {
  const list = $('#ach-list');
  if (!list) return;
  list.innerHTML = '';
  let items = achItems.filter(it => (achTab === 'done' ? !!it.completed : !it.completed));
  if (achSearch) {
    const kw = achSearch.toLowerCase();
    items = items.filter(it =>
      (it.name || '').toLowerCase().includes(kw) ||
      (it.description || '').toLowerCase().includes(kw) ||
      (it.id || '').toLowerCase().includes(kw));
  }
  const totalPages = Math.max(1, Math.ceil(items.length / ACH_PAGE_SIZE));
  if (achPage > totalPages) achPage = totalPages;
  const pageItems = items.slice((achPage - 1) * ACH_PAGE_SIZE, achPage * ACH_PAGE_SIZE);
  if (!pageItems.length) {
    let empty = achTab === 'done' ? '还没有已完成的成就' : '全部成就都已完成';
    if (achSearch) empty = '没有匹配的成就（' + (achTab === 'done' ? '已完成' : '未完成') + '）';
    list.innerHTML = '<div class="res-empty">' + esc(empty) + '</div>';
  } else {
    pageItems.forEach((item, i) => {
      const card = buildAchCard(item);
      card.style.animationDelay = (i * 0.05) + 's';
      list.appendChild(card);
    });
  }
  renderAchPagination($('#ach-pagination'), items.length, totalPages);
}

function renderAchPagination(pagination, totalItems, totalPages) {
  if (!pagination) return;
  pagination.innerHTML = '';
  const prev = document.createElement('button');
  prev.textContent = '←';
  prev.disabled = achPage <= 1;
  prev.onclick = () => { if (achPage > 1) { achPage--; renderAchList(); } };
  pagination.appendChild(prev);
  for (let i = 1; i <= totalPages; i++) {
    const b = document.createElement('button');
    b.textContent = i;
    if (i === achPage) b.classList.add('active');
    b.onclick = () => { achPage = i; renderAchList(); };
    pagination.appendChild(b);
  }
  const next = document.createElement('button');
  next.textContent = '→';
  next.disabled = achPage >= totalPages;
  next.onclick = () => { if (achPage < totalPages) { achPage++; renderAchList(); } };
  pagination.appendChild(next);
}

// 卡片: 与资源卡片同构 (左侧图标块 + 标题/状态徽章/稀有度 + 描述)
function buildAchCard(item) {
  const done = !!item.completed;
  const rarity = ACH_RARITY_ZH[item.rarity] || '';
  const card = document.createElement('div');
  card.className = 'res-card ach-card' + (done ? '' : ' disabled');
  card.innerHTML =
    '<div class="res-card-main">' +
      '<span class="ach-icon' + (done ? ' done' : '') + '">' +
        iconSvg(done ? 'checkOne' : 'unlock') +
      '</span>' +
      '<div class="res-info">' +
        '<div class="res-title-row">' +
          '<span class="res-title">' + esc(item.name || item.id) +
            '<span class="res-state-badge ' + (done ? 'on' : 'off') + '">' +
              (done ? '已完成' : '未完成') + '</span>' +
          '</span>' +
          (rarity ? '<span class="ach-rarity ach-rarity-' + esc(item.rarity || '') + '">' +
                    esc(rarity) + '</span>' : '') +
        '</div>' +
        '<div class="res-desc" title="' + esc(item.description || '') + '">' +
          esc(item.description || '（无描述）') + '</div>' +
      '</div>' +
    '</div>';
  addCardTilt(card);
  return card;
}

// 页面级加载态: 清空列表 + 转圈 (与资源管理页一致, 避免旧列表先闪一下)
function setAchLoading(on) {
  const card = $('#page-achievement .card');
  if (!card) return;
  if (on) {
    const list = $('#ach-list');
    const pg = $('#ach-pagination');
    if (list) list.innerHTML = '';
    if (pg) pg.innerHTML = '';
    showFrameLoading(card);
  } else {
    hideFrameLoading(card);
  }
}

// ---------------- 入口 / 刷新时机 ----------------

// 切入本页: 每次都重新读一遍本地记录 (完成状态可能刚在别处变化)
function enterAchievementPage() {
  syncAchTabs();
  if (!achNeedsFetch()) { renderAchAll(); return; }
  setAchLoading(true);
  Promise.resolve(refreshAchievements()).catch(() => {}).finally(() => {
    const list = $('#ach-list');
    if (list && !list.children.length) renderAchAll();   // 兜底: 没数据也画出空态
    setAchLoading(false);
  });
}

// 窗口重新聚焦: **只在本页时才刷新** (其它页面不该为它发请求)
function syncAchievementsOnFocus() {
  if (typeof currentPage === 'undefined' || currentPage !== 'achievement') return;
  const now = Date.now();
  if (now - _lastAchFocusSync < ACH_FOCUS_GAP) return;
  _lastAchFocusSync = now;
  Promise.resolve(refreshAchievements()).catch(() => {});
}

// 右上角唯一的按钮: 云端同步刷新 (云端还没接, 现在只做本地刷新)
async function cloudSyncAchievements() {
  const btn = $('#ach-cloud-sync');
  if (btn) btn.disabled = true;
  try {
    await refreshAchievements();
    toast('云端同步暂未接入，已刷新本地记录', 'info', 3000);
  } catch (e) {
    toast('刷新失败: ' + e, 'error');
  } finally {
    if (btn) btn.disabled = false;
  }
}

// ---------------- 事件绑定 ----------------

function bindAchievementEvents() {
  $$('#page-achievement .res-tab').forEach(btn => {
    btn.addEventListener('click', () => {
      const next = btn.dataset.ach === 'todo' ? 'todo' : 'done';
      if (next === achTab) return;
      achTab = next;
      achPage = 1;
      syncAchTabs();
      renderAchList();          // 数据已在内存里, 换分区不必再问后端
    });
  });

  const search = $('#ach-search');
  if (search) {
    search.addEventListener('input', () => {
      achSearch = search.value.trim();
      achPage = 1;
      renderAchList();
    });
  }

  const cloud = $('#ach-cloud-sync');
  if (cloud) cloud.addEventListener('click', cloudSyncAchievements);

  window.addEventListener('focus', syncAchievementsOnFocus);
  // 最小化/恢复时 focus 不一定来, 用 visibilitychange 补一次
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden) syncAchievementsOnFocus();
  });

  renderAchCounts();
}
