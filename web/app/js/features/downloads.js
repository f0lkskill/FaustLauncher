/* ==============================================================================
 * js/features/downloads.js — 下载中心 + 下载任务抽屉
 * ------------------------------------------------------------------------------
 * 职责:
 *   · 已下载标记(downloadedSeen)与随机推荐的状态联动
 *   · 下载任务列表模型、进度/失败/移除、FAB 与抽屉开合
 *   · 云端插件/Mod 列表(资源管理式布局): 搜索、分页、安装、详情模态
 * 本文件提供:
 *  函数: applyDownloadedStyle / markItemDownloaded / addDownloadTask / updateDownloadTask / failDownloadTask / removeDownloadTask / updateFabVisibility / maybeCloseDrawer / toggleDrawer / renderDownloadDrawer / startDownloadItem / updateDownloadCountDisplay / initDownloadCenter / loadDCDisplay / renderDCList / renderDCPagination / markCardInstalled / markCardIsNew / buildDCCard / dcAuthorLinks / openDcModal
 *  状态/常量: downloadedSeen / _currentRec / downloadTasks / dcKind / dcPage / dcSearch / dcAddonItems / dcModItems
 * 依赖: 依赖 bootstrap/state/utils/ui.tilt
 * 加载顺序: 17/22    (拆分自原 app.js 行 1105-1518)
 * ============================================================================== */
'use strict';

// ---------------- 已下载标记(资源管理页 / 下载中心 / 随机推荐共享) ----------------
// 本次会话内已确认下载完成的项 (kind:name), 下载完成即时生效; 刷新列表仍会以后端检测为准
const downloadedSeen = new Set();
let _currentRec = null;   // 当前渲染的随机推荐 {kind, item}

function applyDownloadedStyle(btn) {
  btn.className = 'btn btn-downloaded';
  btn.innerHTML = icoText('fileSuccess', '已下载');
  btn.disabled = true;
  btn.onclick = null;
}

// 下载完成/检测到已安装时: 即时把对应按钮换成绿色"已下载"
function markItemDownloaded(kind, name) {
  downloadedSeen.add(kind + ':' + name);
  // 更新下载中心卡片: 标题旁显示"已安装" (按 data-name 精确匹配, 不受徽章文字干扰)
  document.querySelectorAll('#dc-list .res-card[data-name]').forEach(card => {
    if (card.dataset.name === name) markCardInstalled(card);
  });
  if (_currentRec && _currentRec.item && _currentRec.item.name === name &&
      (!kind || _currentRec.kind === kind)) {
    const dl = $('#rec-dl');
    if (dl) applyDownloadedStyle(dl);
  }
}

// ---------------- 下载任务抽屉 ----------------
let downloadTasks = [];

// ---- 任务图标: 远程 URL 不能直接当 <img src> ----
// 云端给的是蓝奏云分享/解析链接, 浏览器直接加载必然失败(要么不是图片, 要么解析服务没开)。
// 统一交给后端 get_icon (带磁盘缓存) 换成 data URI, 并把结果缓存在任务对象上。
function isRemoteIcon(u) { return /^https?:\/\//i.test(String(u || '')); }

// ---- 任务模型: 新增 / 更新进度 / 失败 / 移除 ----
function addDownloadTask(t) {
  const idx = downloadTasks.findIndex(x => x.name === t.name);
  const nextIcon = t.icon || PROJECT_ICON;
  if (idx >= 0) {
    downloadTasks[idx].status = 'waiting';
    if (nextIcon !== downloadTasks[idx].icon) downloadTasks[idx].iconUri = null;
    downloadTasks[idx].icon = nextIcon;
    downloadTasks[idx].percent = 0;
  } else {
    downloadTasks.push({ name: t.name, kind: t.kind, icon: nextIcon, iconUri: null, status: 'waiting', percent: 0, downloaded: 0, total: 0, speed: 0 });
  }
  renderDownloadDrawer();
  updateFabVisibility();
}

function updateDownloadTask(name, data) {
  const t = downloadTasks.find(x => x.name === name);
  if (!t) return;
  if (data.percent !== undefined) {
    t.percent = Math.max(0, Math.min(100, Number(data.percent) || 0));
    if (data.downloaded !== undefined) t.downloaded = data.downloaded;
    if (data.total !== undefined) t.total = data.total;
    if (data.speed !== undefined) t.speed = data.speed;
    const wasDone = t.status === 'done';
    t.status = t.percent >= 100 ? 'done' : 'downloading';
    if (t.status === 'done' && !wasDone) {
      toastTop(name + ' 下载完成', 'success');
      // 即时更新下载中心/推荐卡的按钮为"已下载" (无需重启)
      if (t.kind) markItemDownloaded(t.kind, name);
      // 资源管理刷新由后端"解压完成"钩子 (__onResChanged) 触发, 保证落盘后再刷
      setTimeout(() => removeDownloadTask(name, true), 300);
    }
  }
  // 原位更新进度, 不重建 DOM (保证进度条过渡平滑)
  const row = document.querySelector('.dl-task[data-name="' + CSS.escape(name) + '"]');
  if (row && !row.classList.contains('leaving')) {
    const pct = Math.round(t.percent || 0);
    row.classList.remove('waiting', 'downloading', 'done', 'error');
    row.classList.add(t.status);
    row.querySelector('.dl-fill').style.width = pct + '%';
    const meta = row.querySelector('.dl-meta');
    if (t.status === 'done') meta.innerHTML = icoText('fileSuccess', '已完成');
    else if (t.status === 'error') meta.innerHTML = icoText('caution', t.error || '下载失败');
    else if (t.status === 'waiting') meta.textContent = '等待中…';
    else meta.textContent = fmtBytes(t.downloaded) + ' / ' + fmtBytes(t.total) +
      (t.speed ? ' · ' + fmtSpeed(t.speed) : '');
  } else {
    renderDownloadDrawer();
  }
  updateFabVisibility();
}

function failDownloadTask(name, text) {
  const t = downloadTasks.find(x => x.name === name);
  if (!t) return;
  t.status = 'error';
  t.error = text;
  setTimeout(() => removeDownloadTask(name, true), 8000);
  renderDownloadDrawer();
  updateFabVisibility();
}

function removeDownloadTask(name, animate) {
  const row = document.querySelector('.dl-task[data-name="' + CSS.escape(name) + '"]');
  if (animate && row) {
    row.classList.add('leaving');
    setTimeout(() => removeDownloadTask(name, false), 300);
    return;
  }
  const idx = downloadTasks.findIndex(x => x.name === name);
  if (idx >= 0) downloadTasks.splice(idx, 1);
  renderDownloadDrawer();
  updateFabVisibility();
  maybeCloseDrawer();
}

// ---- 抽屉(FAB)开合与可见性 ----
function updateFabVisibility() {
  const fab = $('#dl-fab');
  const active = downloadTasks.filter(t => t.status === 'downloading' || t.status === 'waiting');
  // 图标是静态 SVG (save-one), 这里只切换显隐, 不再替换字符图标
  fab.classList.toggle('visible', active.length > 0);
}

// 所有下载任务结束后自动关闭抽屉
function maybeCloseDrawer() {
  const active = downloadTasks.some(t => t.status === 'downloading' || t.status === 'waiting');
  if (!active && $('#dl-drawer').classList.contains('open')) {
    setTimeout(() => toggleDrawer(false), 200);
  }
}

function toggleDrawer(open) {
  $('#dl-drawer').classList.toggle('open', open);
  $('#dl-overlay').classList.toggle('show', open);
}

function renderDownloadDrawer() {
  const list = $('#dl-list');
  if (!list) return;
  const prevPos = new Map();
  [...list.children].forEach(c => prevPos.set(c.dataset.name, c.getBoundingClientRect().top));
  if (!downloadTasks.length) {
    list.innerHTML = '<div class="dl-empty">暂无下载任务</div>';
    return;
  }
  list.innerHTML = '';
  downloadTasks.forEach(t => {
    const row = document.createElement('div');
    row.className = 'dl-task ' + t.status;
    row.dataset.name = t.name;
    const pct = Math.round(t.percent || 0);
    const info = t.status === 'done' ? icoText('fileSuccess', '已完成')
      : t.status === 'error' ? icoText('caution', t.error || '下载失败')
      : t.status === 'waiting' ? '等待中…'
      : fmtBytes(t.downloaded) + ' / ' + fmtBytes(t.total) +
        (t.speed ? ' · ' + fmtSpeed(t.speed) : '');
    // 图标: 优先用已解析好的 data URI; 远程链接先占位, 渲染后交给后端解析
    const needResolve = !t.iconUri && isRemoteIcon(t.icon);
    const iconSrc = t.iconUri || (needResolve ? PROJECT_ICON : (t.icon || PROJECT_ICON));
    const iconAttrs = needResolve
      ? ' data-icon-url="' + esc(t.icon) + '" data-icon-name="' + esc(t.name) + '" data-icon-task="' + esc(t.name) + '"'
      : '';
    row.innerHTML =
      '<img class="dl-icon" src="' + esc(iconSrc) + '"' + iconAttrs +
        ' onerror="this.src=\'' + PROJECT_ICON + '\'">' +
      '<div class="dl-info">' +
        '<div class="dl-name">' + esc(t.name) +
          '<span class="dl-kind">' + (t.kind === 'addon' ? '插件' : 'Mod') + '</span></div>' +
        '<div class="dl-track"><div class="dl-fill" style="width:' + pct + '%"></div></div>' +
        '<div class="dl-meta">' + info + '</div>' +
      '</div>';
    list.appendChild(row);
  });
  hydrateIcons(list);   // 统一入口: 加载中转圈 + 完成后淡入
  // FLIP: 保留下来的任务从旧位置平滑滑上去
  requestAnimationFrame(() => {
    [...list.children].forEach(c => {
      const old = prevPos.get(c.dataset.name);
      if (old == null) return;
      const dy = old - c.getBoundingClientRect().top;
      if (dy) {
        c.animate([
          { transform: 'translateY(' + dy + 'px)' },
          { transform: 'translateY(0)' },
        ], { duration: 300, easing: 'ease' });
      }
    });
  });
}

function startDownloadItem(kind, item) {
  const url = item.dowload_url || item.download_url || item.url;
  if (!url) { toast('下载链接无效', 'error'); return; }
  const name = item.name || 'unknown';
  // 静默处理重复下载: 已有活跃的同名任务则忽略, 不重复添加 (避免进度条抽搐)
  if (downloadTasks.some(t => t.name === name && (t.status === 'downloading' || t.status === 'waiting'))) {
    return;
  }
  item.download_count = (Number(item.download_count) || 0) + 1;
  updateDownloadCountDisplay(name, item.download_count);
  addDownloadTask({ name, kind, icon: item.icon_url || PROJECT_ICON });
  toggleDrawer(true);
  if (api && kind === 'addon') {
    api.increase_download_count(kind, name).catch(() => {});
    api.download_addon(name, url).catch(e => { toast('下载失败: ' + e, 'error'); failDownloadTask(name, String(e)); });
  } else if (api) {
    api.increase_download_count(kind, name).catch(() => {});
    api.download_mod(name, url).catch(e => { toast('下载失败: ' + e, 'error'); failDownloadTask(name, String(e)); });
  } else {
    toast('浏览器预览模式', 'warn');
  }
}

function updateDownloadCountDisplay(name, count) {
  // 用 data-name 精确定位卡片: 标题里还挂着"已安装/新发布"徽章, 靠 textContent 比对会误判
  document.querySelectorAll('#dc-list .res-card[data-name]').forEach(card => {
    if (card.dataset.name !== name) return;
    const el = card.querySelector('.dc-count');
    if (el) el.innerHTML = icoText('downloadTwo', String(count));
  });
}

// ---------------- 下载中心 (资源管理式) ----------------
let dcKind = 'addon';
let dcPage = 1;
let dcSearch = '';             // 下载中心搜索词
let dcAddonItems = [];
let dcModItems = [];

// ---- 云端列表: 状态与初始化(首次进入才拉取) ----
function initDownloadCenter() {
  if (!api) return;
  $$('.res-tab[data-dc]').forEach(t => t.addEventListener('click', () => {
    $$('.res-tab[data-dc]').forEach(x => x.classList.remove('active'));
    t.classList.add('active');
    dcKind = t.dataset.dc;
    dcPage = 1;
    renderDCList();
  }));
  loadDCDisplay();
}

function loadDCDisplay() {
  const cardEl = $('#page-download_center .card');
  const list = $('#dc-list');
  if (list) list.innerHTML = '';
  showFrameLoading(cardEl);   // 圆圈加载动画, 不显示文字
  Promise.all([
    api.get_addon_list().catch(d => ({ pages: [], error: String(d) })),
    api.get_mod_list().catch(d => ({ pages: [], error: String(d) })),
  ]).then(([addonRes, modRes]) => {
    hideFrameLoading(cardEl);
    dcAddonItems = (addonRes.pages || []).flat().filter(Boolean);
    dcModItems = (modRes.pages || []).flat().filter(Boolean);
    dcPage = 1;
    renderDCList();
  }).catch(e => {
    hideFrameLoading(cardEl);
    if (list) list.innerHTML = '<div class="res-empty">' + icoText('caution', String(e)) + '</div>';
  });
}

// ---- 云端列表渲染: 分区 / 搜索 / 分页 ----
function renderDCList() {
  const list = $('#dc-list');
  if (!list) return;
  list.innerHTML = '';
  let items = dcKind === 'addon' ? dcAddonItems : dcModItems;
  if (dcSearch) {
    const kw = dcSearch.toLowerCase();
    items = items.filter(it =>
      (it.name || '').toLowerCase().includes(kw) ||
      (it.desc || '').toLowerCase().includes(kw));
  }
  const totalPages = Math.max(1, Math.ceil(items.length / RES_PAGE_SIZE));
  if (dcPage > totalPages) dcPage = totalPages;
  const pageItems = items.slice((dcPage - 1) * RES_PAGE_SIZE, dcPage * RES_PAGE_SIZE);
  if (!pageItems.length) {
    list.innerHTML = '';
  } else {
    pageItems.forEach((item, i) => { const c = buildDCCard(item, dcKind); if (c) { c.style.animationDelay = (i * 0.05) + 's'; list.appendChild(c); } });
    hydrateIcons(list);
  }
  renderDCPagination($('#dc-pagination'), items.length, totalPages);
}

function renderDCPagination(pagination, totalItems, totalPages) {
  if (!pagination) return;
  pagination.innerHTML = '';
  const prev = document.createElement('button');
  prev.textContent = '←';
  prev.disabled = dcPage <= 1;
  prev.onclick = () => { if (dcPage > 1) { dcPage--; renderDCList(); } };
  pagination.appendChild(prev);
  for (let i = 1; i <= totalPages; i++) {
    const b = document.createElement('button');
    b.textContent = i;
    if (i === dcPage) b.classList.add('active');
    b.onclick = () => { dcPage = i; renderDCList(); };
    pagination.appendChild(b);
  }
  const next = document.createElement('button');
  next.textContent = '→';
  next.disabled = dcPage >= totalPages;
  next.onclick = () => { if (dcPage < totalPages) { dcPage++; renderDCList(); } };
  pagination.appendChild(next);
}

// 卡片标记"已安装"
function markCardInstalled(card) {
  const title = card.querySelector('.res-title');
  if (title && !title.querySelector('.res-state-badge.installed')) {
    title.insertAdjacentHTML('beforeend', '<span class="res-state-badge installed">已安装</span>');
  }
  // 快捷下载按钮同步进入"已安装"态: 换成对勾图标 + 压暗, 一眼看出不能再下
  const btn = card.querySelector('.dc-dl-btn');
  if (btn) {
    btn.classList.add('installed');
    btn.disabled = true;
    btn.innerHTML = iconSvg('fileSuccess');
  }
}

function markCardIsNew(card) {
  const title = card.querySelector('.res-title');
  if (title && !title.querySelector('.res-state-badge.is-new')) {
    title.insertAdjacentHTML('beforeend', '<span class="res-state-badge is-new">新发布</span>');
  }
}

// 下载中心卡片: 资源管理卡片样式, 右侧快捷下载按钮 + 省略号模态, 已安装检测
function buildDCCard(item, kind) {
  const disabled = item.disabled;
  const card = document.createElement('div');
  card.className = 'res-card' + (disabled ? ' disabled' : '');
  card.dataset.name = item.name || '';   // 供"下载数 +1 / 已安装"精确回写
  card.innerHTML =
    '<div class="res-card-main">' +
      '<img class="res-icon" src="' + PROJECT_ICON + '" alt="" ' +
        'data-icon-url="' + esc(item.icon_url || '') + '" data-icon-name="' + esc(item.name || '') + '" ' +
        'onerror="this.src=\'' + PROJECT_ICON + '\'">' +
      '<div class="res-info">' +
        '<div class="res-title-row">' +
          '<span class="res-title">' + esc(item.name || '未知') + (disabled ? ' (暂不可用)' : '') + '</span>' +
          (item.version ? '<span class="res-ver-inline">v' + esc(item.version) + '</span>' : '') +
        '</div>' +
        '<div class="res-desc">' + esc(item.desc || '无描述') + '</div>' +
        '<div class="res-desc res-authors"><span class="dc-count">' + icoText('downloadTwo', String(item.download_count || 0)) + '</span>' +
          (authorLinksHtml(dcAuthorLinks(item.authors)) ? ' · ' + authorLinksHtml(dcAuthorLinks(item.authors)) : '') + '</div>' +
      '</div>' +
    '</div>' +
    '<div class="res-card-ops">' +
      '<button class="res-menu-btn" type="button">' +
        '<svg class="ico" data-icon="more-one.svg" viewBox="0 0 48 48" fill="none" aria-hidden="true"></svg>' +
      '</button>' +
      '<button class="dc-dl-btn" type="button"' + (disabled ? ' disabled' : '') + '>' +
        '<svg class="ico" data-icon="download-two.svg" viewBox="0 0 48 48" fill="none" aria-hidden="true"></svg>' +
      '</button>' +
    '</div>';
  card.querySelector('.res-menu-btn').onclick = () => openDcModal(kind, item);
  // 快捷下载: 不必进详情模态, 一键直接开始下载 (与资源管理的禁用按钮同一布局)
  const dlBtn = card.querySelector('.dc-dl-btn');
  dlBtn.onclick = (e) => {
    stopClick(e);   // 阻止冒泡(别打开详情模态) 并补一次点击音效
    if (disabled) return;
    if (!api) { toast('浏览器预览模式', 'warn'); return; }
    startDownloadItem(kind, item);
  };
  addCardTilt(card);
  // 已安装检测: 实时钩子 (下载完成即时更新) + 每次渲染检测
  if (api && !disabled) {
    const key = kind + ':' + item.name;
    if (downloadedSeen.has(key)) {
      markCardInstalled(card);
    } else {
      withTimeout(api.check_item_downloaded(kind, item.name), 5000, { downloaded: false })
        .then(r => { if (r && r.downloaded) { markCardInstalled(card); downloadedSeen.add(key); } })
        .catch(() => {});
    }
  }
  if (item.is_new) {
    markCardIsNew(card);
  }
  return card;
}

function dcAuthorLinks(authors) {
  if (authors && typeof authors === 'object' && !Array.isArray(authors)) {
    return Object.entries(authors).map(([n, u]) => ({ name: n, url: u }));
  }
  return [];
}

// 下载中心模态: 详情 + 下载按钮
function openDcModal(kind, item) {
  const existing = document.getElementById('dc-modal');
  if (existing) { closePanel(existing); return; }
  document.body.classList.add('modal-open');
  const disabled = item.disabled;
  const panel = document.createElement('div');
  panel.id = 'dc-modal';
  panel.className = 'panel-overlay';
  panel.innerHTML =
    '<div class="panel-card">' +
      '<div class="res-detail-head">' +
        '<img class="res-detail-icon" src="' + PROJECT_ICON + '" alt="" ' +
          'data-icon-url="' + esc(item.icon_url || '') + '" data-icon-name="' + esc(item.name || '') + '" ' +
          'onerror="this.src=\'' + PROJECT_ICON + '\'">' +
        '<div class="res-detail-main">' +
          '<div class="res-detail-title-row">' +
            '<span class="res-detail-name">' + esc(item.name || '未知') + '</span>' +
            '<button class="panel-close" id="dc-modal-close"><svg class="ico" data-icon="close.svg" viewBox="0 0 48 48" fill="none" aria-hidden="true"></svg></button>' +
          '</div>' +
          '<div class="res-detail-sub">' +
            (item.version ? '<span class="res-ver-inline">v' + esc(item.version) + '</span>' : '') +
            (authorLinksHtml(dcAuthorLinks(item.authors)) || '') +
          '</div>' +
          '<div class="res-detail-state off">' + icoText('downloadTwo', String(item.download_count || 0) + ' 次下载') + '</div>' +
        '</div>' +
      '</div>' +
      '<div class="res-detail-desc">' + esc(item.desc || '无描述') + '</div>' +
      '<div class="res-detail-ops">' +
        '<button class="btn btn-primary" id="dc-modal-dl" ' + (disabled ? 'disabled' : '') + '>' +
          '<svg class="ico" data-icon="download-two.svg" viewBox="0 0 48 48" fill="none" aria-hidden="true"></svg> 下载' +
        '</button>' +
      '</div>' +
    '</div>';
  document.body.appendChild(panel);
  hydrateIcons(panel);
  panel.addEventListener('click', (e) => { if (e.target === panel) closePanel(panel); });
  $('#dc-modal-close').onclick = () => closePanel(panel);
  if (!disabled) {
    const dlBtn = $('#dc-modal-dl');
    dlBtn.onclick = () => {
      startDownloadItem(kind, item);
      closePanel(panel);
    };
    // 已安装检测: 已安装则禁止再次下载
    const key = kind + ':' + item.name;
    const markDlInstalled = () => {
      dlBtn.disabled = true;
      dlBtn.innerHTML = icoText('fileSuccess', '已安装');
    };
    if (downloadedSeen.has(key)) {
      markDlInstalled();
    } else {
      withTimeout(api.check_item_downloaded(kind, item.name), 5000, { downloaded: false })
        .then(r => { if (r && r.downloaded) markDlInstalled(); })
        .catch(() => {});
    }
  }
}
