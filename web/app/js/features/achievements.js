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

let achTab = 'all';             // 当前分区: all | done | todo (默认全部)
let achPage = 1;                // 当前页
const ACH_PAGE_SIZE = 5;        // 每页条数 (与资源管理/下载中心一致)
let achSearch = '';             // 搜索词
let achRarity = '';             // 稀有度筛选: '' = 不筛
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
// 排列/筛选顺序: **稀有的靠前** (神话 → 普通), 同类保持后端给的顺序
const ACH_RARITY_ORDER = ['mythic', 'legendary', 'epic', 'rare', 'uncommon', 'common'];

function achRarityKey(item) {
  return String((item && item.rarity) || '').toLowerCase();
}

function achRarityRank(item) {
  const i = ACH_RARITY_ORDER.indexOf(achRarityKey(item));
  return i < 0 ? ACH_RARITY_ORDER.length : i;   // 没标稀有度的排最后
}

// ---------------- 分区 / 计数 ----------------

function achTabItems(tab) {
  if (tab === 'all' || !tab) return achItems.slice();
  return achItems.filter(it => (tab === 'done' ? !!it.completed : !it.completed));
}

function achCount(tab) {
  return achTabItems(tab).length;
}

// 计数直接写在分区按钮上, 不再单占一行
function renderAchCounts() {
  [['all', '#ach-count-all'], ['done', '#ach-count-done'], ['todo', '#ach-count-todo']]
    .forEach(([tab, sel]) => {
      const el = $(sel);
      if (el) el.textContent = String(achCount(tab));
    });
}

function syncAchTabs() {
  $$('#page-achievement .res-tab').forEach(b => {
    const t = b.dataset.ach || 'all';
    b.classList.toggle('active', t === achTab);
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

// 当前分区 → 稀有度筛选 → 搜索 → 按稀有度排列
function achVisibleItems() {
  let items = achTabItems(achTab);
  if (achRarity) items = items.filter(it => achRarityKey(it) === achRarity);
  if (achSearch) {
    const kw = achSearch.toLowerCase();
    items = items.filter(it =>
      (it.name || '').toLowerCase().includes(kw) ||
      (it.description || '').toLowerCase().includes(kw) ||
      (it.id || '').toLowerCase().includes(kw));
  }
  // 稀有度排列 (神话 → 普通); 同稀有度保持后端给的顺序 → 带下标做稳定排序
  return items.map((it, i) => ({ it, i }))
    .sort((a, b) => (achRarityRank(a.it) - achRarityRank(b.it)) || (a.i - b.i))
    .map(p => p.it);
}

function renderAchList() {
  const list = $('#ach-list');
  if (!list) return;
  list.innerHTML = '';
  const items = achVisibleItems();
  const totalPages = Math.max(1, Math.ceil(items.length / ACH_PAGE_SIZE));
  if (achPage > totalPages) achPage = totalPages;
  const pageItems = items.slice((achPage - 1) * ACH_PAGE_SIZE, achPage * ACH_PAGE_SIZE);
  if (!pageItems.length) {
    let empty;
    if (achSearch || achRarity) empty = '没有匹配的成就';
    else if (achTab === 'done') empty = '还没有已完成的成就';
    else if (achTab === 'todo') empty = '全部成就都已完成';
    else empty = '还没有成就数据';
    list.innerHTML = '<div class="res-empty">' + esc(empty) + '</div>';
  } else {
    pageItems.forEach((item, i) => {
      const card = buildAchCard(item);
      card.style.animationDelay = (i * 0.05) + 's';
      list.appendChild(card);
    });
  }
  renderAchPagination($('#ach-pagination'), items.length, totalPages);
  syncAchFilterButton();
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
// 图标块: 有徽标图 (`item.icon`, 见 assets/achievement/) 就用它, 否则退回内联占位图标
function buildAchCard(item) {
  const done = !!item.completed;
  const rarity = ACH_RARITY_ZH[item.rarity] || '';
  const card = document.createElement('div');
  card.className = 'res-card ach-card' + (done ? '' : ' disabled');
  card.innerHTML =
    '<div class="res-card-main">' +
      // 稀有度只给一个 class, 边框颜色由 CSS 决定（素材里不含边框）
      '<span class="ach-icon r-' + esc(achRarityKey(item) || 'common') +
        (item.icon ? ' has-art' : '') + '">' +
        (item.icon
          ? '<img class="ach-art" src="' + esc(item.icon) + '" alt="">'
          : iconSvg(done ? 'checkOne' : 'unlock')) +
      '</span>' +
      '<div class="res-info">' +
        '<div class="res-title-row">' +
          '<span class="res-title">' + esc(item.name || item.id) +
            '<span class="res-state-badge ' + (done ? 'on' : 'off') + '">' +
              (done ? '已完成' : '未完成') + '</span>' +
          '</span>' +
          (item.plugin
            ? '<span class="ach-plugin-badge" title="来自插件' +
                (item.addon ? '：' + esc(item.addon) : '') +
                '；完成记录只存在本地，不参与云端同步">插件</span>'
            : '') +
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

// ---------------- 稀有度筛选 ----------------

// 菜单里只列当前分区里真的有的稀有度, 数量按**当前分区**统计 (与搜索无关)
function renderAchFilterMenu() {
  const menu = $('#ach-filter-menu');
  if (!menu) return;
  const tabItems = achTabItems(achTab);
  const row = (value, label, count) =>
    '<button class="ach-filter-item' + (achRarity === value ? ' active' : '') +
    '" type="button" data-rarity="' + esc(value) + '">' +
      '<span class="ach-filter-name">' + esc(label) + '</span>' +
      '<span class="ach-filter-n">' + count + '</span>' +
    '</button>';
  let html = row('', '全部稀有度', tabItems.length);
  ACH_RARITY_ORDER.forEach(r => {
    const n = tabItems.filter(it => achRarityKey(it) === r).length;
    if (n) html += row(r, ACH_RARITY_ZH[r] || r, n);
  });
  menu.innerHTML = html;
  menu.querySelectorAll('.ach-filter-item').forEach(btn => {
    btn.addEventListener('click', () => {
      achRarity = btn.dataset.rarity || '';
      achPage = 1;
      closeAchFilterMenu();
      renderAchAll();
    });
  });
}

function syncAchFilterButton() {
  const btn = $('#ach-filter');
  if (!btn) return;
  btn.classList.toggle('active', !!achRarity);
  btn.title = achRarity
    ? ('稀有度筛选：' + (ACH_RARITY_ZH[achRarity] || achRarity) + '（点击更换）')
    : '按稀有度筛选';
}

function openAchFilterMenu() {
  const menu = $('#ach-filter-menu');
  if (!menu) return;
  renderAchFilterMenu();
  menu.hidden = false;
}

function closeAchFilterMenu() {
  const menu = $('#ach-filter-menu');
  if (menu) menu.hidden = true;
}

function toggleAchFilterMenu() {
  const menu = $('#ach-filter-menu');
  if (!menu) return;
  if (menu.hidden) openAchFilterMenu();
  else closeAchFilterMenu();
}

// ---------------- 事件绑定 ----------------

function bindAchievementEvents() {
  $$('#page-achievement .res-tab').forEach(btn => {
    btn.addEventListener('click', () => {
      const next = btn.dataset.ach || 'all';
      closeAchFilterMenu();
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

  // 稀有度筛选: 点按钮开合菜单, 点别处/Esc 关掉
  const filterBtn = $('#ach-filter');
  if (filterBtn) {
    filterBtn.addEventListener('click', (e) => {
      if (e && e.stopPropagation) e.stopPropagation();
      toggleAchFilterMenu();
    });
  }
  document.addEventListener('click', (e) => {
    const wrap = $('#ach-filter-wrap');
    if (wrap && e.target && !wrap.contains(e.target)) closeAchFilterMenu();
  });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') closeAchFilterMenu();
  });

  const cloud = $('#ach-cloud-sync');
  if (cloud) cloud.addEventListener('click', cloudSyncAchievements);

  window.addEventListener('focus', syncAchievementsOnFocus);
  // 最小化/恢复时 focus 不一定来, 用 visibilitychange 补一次
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden) syncAchievementsOnFocus();
  });

  renderAchCounts();
  syncAchFilterButton();
}
