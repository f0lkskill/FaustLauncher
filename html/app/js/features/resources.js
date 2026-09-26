/* ==============================================================================
 * js/features/resources.js — 资源管理页(本地插件 / Mod)
 * ------------------------------------------------------------------------------
 * 职责:
 *   · 分区切换、搜索、分页, 列表与卡片渲染(hover 渐变描边 + 3D 跟随)
 *   · 重装、打开目录、独立管理器入口, 卡片上的启用/禁用设置项
 *   · 资源详情模态窗口(设置表单自动保存 + 卸载等操作)
 *   · 进入本页的加载态: 立刻清空旧列表 + 转圈, 直到本次刷新结束再渲染
 * 本文件提供:
 *  函数: syncResActions / bindResReinstallButtons / refreshMods / renderResFromCache / resNeedsFetch /
 *        setResLoading / enterResourcePage / confirmReinstall / renderResList / renderResPagination /
 *        authorLinksHtml / buildResCard / renderSettingsFields / collectSettingsFields / openResModal
 *  状态/常量: resKind / resPage / RES_PAGE_SIZE / resSearch / resAddons / resMods / resRefreshing / resRefreshedAt / RES_REFRESH_GAP / SETTING_LABELS
 * 依赖: bootstrap($/api) / state / utils; 卡片的 3D 跟随效果由 ui/tilt.js 的 addCardTilt 提供
 * 加载顺序: 16/22    (拆分自原 app.js 行 760-1104)
 * ============================================================================== */
'use strict';

// ---------------- 资源管理 (插件/Mod) ----------------
let resKind = 'addon';          // 当前分区: addon | mod
let resPage = 1;                // 当前页
const RES_PAGE_SIZE = 5;        // 每页最多 5 个
let resSearch = '';             // 资源管理搜索词
let resAddons = [];             // 插件列表
let resMods = [];               // Mod 列表

// 按当前分区同步按钮组显示
function syncResActions() {
  const a = $('#res-actions-addon'), m = $('#res-actions-mod');
  if (a) a.hidden = resKind !== 'addon';
  if (m) m.hidden = resKind !== 'mod';
}

function bindResReinstallButtons() {
  const addonBtn = $('#btn-reinstall-addon');
  const modBtn = $('#btn-reinstall-mod');
  if (addonBtn) addonBtn.onclick = () => {
    const dirs = resAddons.filter(x => x.reinstall_available).map(x => x.dir || x.name);
    if (dirs.length) confirmReinstall('addon', dirs, '插件');
    else toast('缓存中没有可精确匹配的插件', 'warn');
  };
  if (modBtn) modBtn.onclick = () => {
    const dirs = resMods.filter(x => x.reinstall_available).map(x => x.dir || x.name);
    if (dirs.length) confirmReinstall('mod', dirs, 'Mod');
    else toast('缓存中没有可精确匹配的 Mod', 'warn');
  };
}

// 刷新去重: 同一次操作 (如删除插件) 会同时触发前端直接刷新与后端 __onResChanged 钩子,
// 两次都真正执行时列表会连续渲染两次 (看起来"重复刷新了两遍")。
// 这里: 进行中的刷新直接复用同一 Promise; 刚刷完的重复请求直接忽略, 保证只刷一次。
let resRefreshing = null;
let resRefreshedAt = 0;
const RES_REFRESH_GAP = 400;   // ms, 同一次操作的重复刷新合并窗口

// ---- 数据: 拉取本地插件/Mod 列表 (带重复刷新合并窗口, 避免一次操作触发多次请求) ----
async function refreshMods(keepPage) {
  if (!api) { toast('浏览器预览模式', 'warn'); return; }
  if (resRefreshing) return resRefreshing;                     // 刷新中: 复用同一次请求
  if (Date.now() - resRefreshedAt < RES_REFRESH_GAP) return;    // 刚刷完: 忽略重复请求(调用方自行决定怎么显示)
  resRefreshing = (async () => {
    try {
      const d = await api.get_mods_data();
      resAddons = d.addons || [];
      resMods = d.dir_mods || [];
      if (!keepPage) resPage = 1;
      renderResFromCache();
    } catch (e) {
      const list = $('#res-list');
      if (list) list.innerHTML = '<div class="res-empty">读取失败: ' + esc(String(e)) + '</div>';
    } finally {
      resRefreshedAt = Date.now();
      resRefreshing = null;
    }
  })();
  return resRefreshing;
}

// 用内存里已有的数据重画列表(不发请求): 三个渲染步骤固定成一组, 避免各处漏同步按钮组
function renderResFromCache() {
  renderResList();
  syncResActions();              // 保持按钮组与当前分区一致
  bindResReinstallButtons();
}

// ---- 资源管理页的加载态 ----
// 进入本页时: 需要重新拉取就先清空旧列表并转圈, 数据到位后再整屏渲染一次。
// 旧实现会保留上一轮的列表, 拉取回来又整体重画 —— 观感上像"刷新了两遍"。
function resNeedsFetch() {
  return !!resRefreshing || (Date.now() - resRefreshedAt >= RES_REFRESH_GAP);
}

// 清空列表/分页 + 显示或隐藏卡片上的转圈遮罩
function setResLoading(on) {
  const card = $('#page-mod_addon .card');
  if (on) {
    const list = $('#res-list');
    const pg = $('#res-pagination');
    if (list) list.innerHTML = '';   // 立刻清空: 不让旧列表先闪一下再被替换
    if (pg) pg.innerHTML = '';
    showFrameLoading(card);
  } else {
    hideFrameLoading(card);
  }
}

// 页面入口(switchPage 调用): 该拉新数据就"清空 + 转圈 → 渲染", 去重窗口内则直接用现有数据重画
function enterResourcePage() {
  if (!resNeedsFetch()) { renderResFromCache(); return; }
  setResLoading(true);
  Promise.resolve(refreshMods()).catch(() => {}).finally(() => {
    // 兜底: 本次既没拉到数据也没渲染(被去重跳过 / 后端不可用)时, 用内存数据补一次, 避免空列表
    const list = $('#res-list');
    if (list && !list.children.length) renderResFromCache();
    setResLoading(false);
  });
}

function confirmReinstall(kind, dirs, label) {
  // 详情窗口只传入一个资源，不需要重复弹确认层；仍走同一套
  // prepare_reinstall -> startDownloadItem 流程，确保下载抽屉和进度一致。
  if (dirs.length === 1) {
    (async () => {
      const r = await api.prepare_reinstall(kind, dirs[0]).catch(e => ({ error: String(e) }));
      if (r && r.ok && r.item) {
        startDownloadItem(kind, r.item);
        toast('已开始重装' + label, 'info', 3000);
      } else if (r && r.error) {
        toast('准备重装失败: ' + r.error, 'error');
      }
    })();
    return;
  }
  const panel = document.createElement('div');
  panel.className = 'panel-overlay';
  panel.innerHTML = '<div class="panel-card"><div class="panel-head"><h3>重装所有' + label + '</h3><button class="panel-close" title="关闭"><svg class="ico" data-icon="close.svg" viewBox="0 0 48 48" fill="none" aria-hidden="true"></svg></button></div>' +
    '<div class="panel-body"><p>将删除本地资源，并使用启动时缓存的云端信息重新安装。是否继续？</p></div>' +
    '<div class="panel-foot"><button class="btn btn-ghost" data-no>取消</button><button class="btn btn-primary" data-yes>确认重装</button></div></div>';
  document.body.appendChild(panel);
  const close = () => closePanel(panel);
  panel.querySelector('.panel-close').onclick = close;
  panel.querySelector('[data-no]').onclick = close;
  panel.querySelector('[data-yes]').onclick = async () => {
    const btn = panel.querySelector('[data-yes]');
    btn.disabled = true;
    close();
    const prepared = [];
    for (const dir of dirs) {
      const r = await api.prepare_reinstall(kind, dir).catch(e => ({ error: String(e) }));
      if (r && r.ok && r.item) prepared.push(r.item);
      else if (r && r.error) toast('准备重装失败: ' + r.error, 'error');
    }
    prepared.forEach(item => startDownloadItem(kind, item));
    if (prepared.length) toast('已开始重装' + label, 'info', 3000);
  };
}

// ---- 列表渲染: 分区 / 搜索 / 分页 ----
function renderResList() {
  const list = $('#res-list');
  if (!list) return;
  list.innerHTML = '';
  let items = resKind === 'addon' ? resAddons : resMods;
  if (resSearch) {
    const kw = resSearch.toLowerCase();
    items = items.filter(it =>
      (it.name || '').toLowerCase().includes(kw) ||
      (it.description || '').toLowerCase().includes(kw));
  }
  // 显示顺序: 已启用的排前面, 已禁用的一律沉到后面 (组内保持后端给的顺序)。
  // 重排只发生在"整页刷新"时 (切换页面 / 换分区 / 搜索 / 翻页 / 后端通知刷新);
  // 卡片上的启用/禁用按钮走 applyCardEnabledState 就地更新, 不会当场把卡片挪走。
  items = items.slice().sort((a, b) => Number(!!b.enabled) - Number(!!a.enabled));
  const totalPages = Math.max(1, Math.ceil(items.length / RES_PAGE_SIZE));
  if (resPage > totalPages) resPage = totalPages;
  const pageItems = items.slice((resPage - 1) * RES_PAGE_SIZE, resPage * RES_PAGE_SIZE);
  if (!pageItems.length) {
    list.innerHTML = '<div class="res-empty">' + (resKind === 'addon' ? '暂无插件 (addons/ 目录)' : '暂无 Mod (mods/ 目录)') + '</div>';
  } else {
    pageItems.forEach((item, i) => { const c = buildResCard(item); if (c) { c.style.animationDelay = (i * 0.05) + 's'; list.appendChild(c); } });
  }
  renderResPagination($('#res-pagination'), items.length, totalPages);
}

function renderResPagination(pagination, totalItems, totalPages) {
  if (!pagination) return;
  pagination.innerHTML = '';
  const prev = document.createElement('button');
  prev.textContent = '←';
  prev.disabled = resPage <= 1;
  prev.onclick = () => { if (resPage > 1) { resPage--; renderResList(); } };
  pagination.appendChild(prev);
  for (let i = 1; i <= totalPages; i++) {
    const b = document.createElement('button');
    b.textContent = i;
    if (i === resPage) b.classList.add('active');
    b.onclick = () => { resPage = i; renderResList(); };
    pagination.appendChild(b);
  }
  const next = document.createElement('button');
  next.textContent = '→';
  next.disabled = resPage >= totalPages;
  next.onclick = () => { if (resPage < totalPages) { resPage++; renderResList(); } };
  pagination.appendChild(next);
}

// 作者链接渲染 (可点击超链接)
function authorLinksHtml(links) {
  if (!links || !links.length) return '';
  return links.map(l =>
    '<a class="res-author-link" href="' + esc(l.url || '#') + '" target="_blank" onclick="stopClick(event)">' + esc(l.name) + '</a>'
  ).join(' · ');
}

// 就地刷新一张卡片的启用/禁用外观 (不改列表顺序):
// 只改这一张卡的 class / 状态徽章 / 按钮态, 因此点击禁用后卡片停在原地。
function applyCardEnabledState(card, item) {
  if (!card || !item) return;
  const enabled = !!item.enabled;
  // live-toggle: 关掉入场动画, 让 opacity/filter 平滑过渡 (否则切 class 会重播 cardPopIn)
  card.classList.add('live-toggle');
  card.classList.toggle('disabled', !enabled);
  const badge = card.querySelector('.res-state-badge');
  if (badge) {
    badge.className = 'res-state-badge ' + (enabled ? 'on' : 'off');
    badge.textContent = enabled ? '已启用' : '已禁用';
  }
  const btn = card.querySelector('.res-toggle-btn');
  if (btn) {
    btn.classList.toggle('on', enabled);
    btn.title = enabled ? '点击禁用' : '点击启用';
    btn.setAttribute('aria-pressed', enabled ? 'true' : 'false');
  }
}

// 资源卡片: 下载中心样式, 图标用目录下图片, 名字旁启用/禁用标识, hover 渐变描边 + 3D 跟随
function buildResCard(item) {
  const name = item.name || '未知';
  const enabled = !!item.enabled;
  const desc = item.description || '（无描述）';
  const ver = item.version || '';
  const card = document.createElement('div');
  card.className = 'res-card' + (enabled ? '' : ' disabled');
  card.innerHTML =
    '<div class="res-card-main">' +
      '<img class="res-icon" src="' + (item.icon || PROJECT_ICON) + '" alt="" onerror="this.src=\'' + PROJECT_ICON + '\'">' +
      '<div class="res-info">' +
        '<div class="res-title-row">' +
          '<span class="res-title">' + esc(name) +
            '<span class="res-state-badge ' + (enabled ? 'on' : 'off') + '">' + (enabled ? '已启用' : '已禁用') + '</span>' +
          '</span>' +
          (ver ? '<span class="res-ver-inline">v' + esc(ver) + '</span>' : '') +
        '</div>' +
        '<div class="res-desc">' + esc(desc) + '</div>' +
        (authorLinksHtml(item.author_links) ? '<div class="res-desc">' + authorLinksHtml(item.author_links) + '</div>' : '') +
      '</div>' +
    '</div>' +
    '<div class="res-card-ops">' +
      '<button class="res-menu-btn" type="button" title="更多操作">' +
        '<svg class="ico" data-icon="more-one.svg" viewBox="0 0 48 48" fill="none" aria-hidden="true"></svg>' +
      '</button>' +
      '<button class="res-toggle-btn' + (enabled ? ' on' : '') + '" type="button"' +
        ' aria-pressed="' + (enabled ? 'true' : 'false') + '"' +
        ' title="' + (enabled ? '点击禁用' : '点击启用') + '">' +
        '<svg class="ico" data-icon="reduce-one.svg" viewBox="0 0 48 48" fill="none" aria-hidden="true"></svg>' +
      '</button>' +
    '</div>';
  card.querySelector('.res-toggle-btn').onclick = async (e) => {
    stopClick(e);   // 阻止冒泡(别触发卡片自身) 并补一次点击音效
    if (!api) { toast('浏览器预览模式', 'warn'); return; }
    const btn = e.currentTarget;
    if (btn.disabled) return;
    btn.disabled = true;
    const kind = resKind;
    const fn = kind === 'addon' ? api.set_addon_enabled : api.set_mod_enabled;
    const next = !item.enabled;
    try {
      const r = await fn(item.dir || item.name, next);
      if (r && r.error) { toast('操作失败: ' + r.error, 'error'); return; }
      item.enabled = next;
      // 同步内存 settings.enable, 保证详细界面(设置开关)一致
      if (item.settings) item.settings.enable = next;
      // 关键: 只就地更新这张卡片, **不** 调用 renderResList()。
      // renderResList 会把已禁用的条目排到列表末尾, 若在点击瞬间重排, 卡片会当场
      // 跳到后面去 —— 用户就觉得"点一下东西就飞走了"。
      // 这里让顺序保持不变, 等下一次整页刷新(切换页面 / 换分区 / 搜索 / 翻页)时
      // 再统一按启用优先重排。
      applyCardEnabledState(card, item);
    } catch (err) {
      toast('操作失败: ' + err, 'error');
    } finally {
      btn.disabled = false;
    }
  };
  card.querySelector('.res-menu-btn').onclick = () => openResModal(resKind, item);
  addCardTilt(card);
  return card;
}

// 设置项名称翻译 (目前仅 enable)
const SETTING_LABELS = { enable: '启用' };

// 模态内的启用状态标识 (电源图标 + 文案)
function resStateHtml(enabled) {
  return '<svg class="ico" data-icon="reduce-one.svg" viewBox="0 0 48 48" fill="none" aria-hidden="true"></svg> ' +
    (enabled ? '已启用' : '已禁用');
}

// 启用/禁用电源按钮 (模态设置区用, 带 data-set 以便随表单一起收集)
function resToggleBtnHtml(key, on) {
  return '<button type="button" class="res-toggle-btn' + (on ? ' on' : '') + '"' +
    ' data-set="' + esc(key) + '" data-value="' + (on ? '1' : '0') + '"' +
    ' aria-pressed="' + (on ? 'true' : 'false') + '"' +
    ' title="' + (on ? '点击禁用' : '点击启用') + '">' +
    '<svg class="ico" data-icon="reduce-one.svg" viewBox="0 0 48 48" fill="none" aria-hidden="true"></svg>' +
    '</button>';
}

// 设置字段渲染 (bool→开关, number→数字框, 其余→文本框); enable 标签译为"启用"
// 例外: enable 是"启用/禁用这个资源"本身, 统一用与卡片一致的电源按钮, 不再用滑动开关
function renderSettingsFields(settings) {
  const keys = settings ? Object.keys(settings) : [];
  if (!keys.length) return '<div class="res-empty">暂无配置项</div>';
  let html = '<div class="res-settings">';
  keys.forEach(k => {
    const v = settings[k];
    const label = SETTING_LABELS[k] || k;
    if (k === 'enable') {
      html += '<div class="res-set-row"><span class="res-set-name">' + esc(label) + '</span>' +
        resToggleBtnHtml(k, !!v) + '</div>';
    } else if (typeof v === 'boolean') {
      html += '<label class="res-set-row"><span class="res-set-name">' + esc(label) + '</span>' +
        '<span class="switch"><input type="checkbox" data-set="' + esc(k) + '"' + (v ? ' checked' : '') + '><span class="slider"></span></span></label>';
    } else if (typeof v === 'number') {
      html += '<label class="res-set-row"><span class="res-set-name">' + esc(label) + '</span>' +
        '<input type="number" step="any" data-set="' + esc(k) + '" value="' + esc(v) + '"></label>';
    } else {
      html += '<label class="res-set-row"><span class="res-set-name">' + esc(label) + '</span>' +
        '<input type="text" data-set="' + esc(k) + '" value="' + esc(v) + '"></label>';
    }
  });
  html += '</div>';
  return html;
}

function collectSettingsFields(panel) {
  const s = {};
  panel.querySelectorAll('[data-set]').forEach(el => {
    const k = el.dataset.set;
    if (el.classList.contains('res-toggle-btn')) s[k] = el.dataset.value === '1';
    else if (el.type === 'checkbox') s[k] = el.checked;
    else if (el.type === 'number') s[k] = Number(el.value);
    else s[k] = el.value;
  });
  return s;
}

// 模态窗口 (插件/Mod 统一): 无标题栏, X 与名字同排; 设置表单自动保存; 操作按钮
function openResModal(kind, item) {
  const existing = document.getElementById('res-modal');
  if (existing) { closePanel(existing); return; }
  document.body.classList.add('modal-open');
  const isAddon = kind === 'addon';
  const dir = item.dir || item.name;   // 文件夹名 (后端操作用)
  const name = item.name || '';
  const enabled = !!item.enabled;
  const author = item.author || '';
  const ver = item.version || '';
  const panel = document.createElement('div');
  panel.id = 'res-modal';
  panel.className = 'panel-overlay';
  panel.innerHTML =
    '<div class="panel-card">' +
      '<div class="res-detail-head">' +
        '<img class="res-detail-icon" src="' + (item.icon || PROJECT_ICON) + '" onerror="this.src=\'' + PROJECT_ICON + '\'">' +
        '<div class="res-detail-main">' +
          '<div class="res-detail-title-row">' +
            '<span class="res-detail-name">' + esc(name) + '</span>' +
            '<button class="panel-close" id="res-modal-close" title="关闭"><svg class="ico" data-icon="close.svg" viewBox="0 0 48 48" fill="none" aria-hidden="true"></svg></button>' +
          '</div>' +
          '<div class="res-detail-sub">' +
            (ver ? '<span class="res-ver-inline">v' + esc(ver) + '</span>' : '') +
            (authorLinksHtml(item.author_links) || '') +
          '</div>' +
          '<div class="res-detail-state ' + (enabled ? 'on' : 'off') + '">' + resStateHtml(enabled) + '</div>' +
        '</div>' +
      '</div>' +
      '<div class="res-detail-desc">' + esc(item.description || '（无描述）') + '</div>' +
      renderSettingsFields(item.settings) +
      '<div class="res-detail-ops">' +
         '<button class="btn btn-ghost" id="res-open-dir">打开目录</button>' +
         (item.reinstall_available ? '<button class="btn btn-primary" id="res-reinstall">重装</button>' : '') +
         '<button class="btn btn-danger" id="res-delete">删除</button>' +
      '</div>' +
    '</div>';
  document.body.appendChild(panel);
  panel.addEventListener('click', (e) => { if (e.target === panel) closePanel(panel); });
  $('#res-modal-close').onclick = () => closePanel(panel);

  $('#res-open-dir').onclick = async () => {
    const r = await api.open_mod_item_dir(kind, dir).catch(e => ({ error: String(e) }));
    if (r && r.error) toast(r.error, 'error');
  };
  if (item.reinstall_available) {
    $('#res-reinstall').onclick = () => {
      closePanel(panel);
      confirmReinstall(kind, [dir], isAddon ? '插件' : 'Mod');
    };
  }
  $('#res-delete').onclick = async () => {
    try {
      if (isAddon) {
        const r = await api.delete_addon(dir);
        if (r && r.error) { toast('删除失败: ' + r.error, 'error'); return; }
        toast('已删除 ' + name, 'success');
        closePanel(panel);
        refreshMods(true);
      } else {
        // Mod 删除在后台线程执行 (可能清理游戏目录副本), 立即反馈, 结果由钩子通知
        await api.delete_mod(dir).catch(() => {});
        toast('正在卸载 ' + name + '...', 'info', 2500);
        closePanel(panel);
      }
    } catch (err) { toast('卸载失败: ' + err, 'error'); }
  };
  // 自动保存: 任一设置变化 → 防抖写回, 并即时更新模态内状态标识
  let saveTimer = null;
  const saveNow = () => {
    const settings = collectSettingsFields(panel);
    const fn = isAddon ? api.set_addon_settings : api.set_mod_settings;
    fn(dir, settings).then(r => {
      if (r && r.error) { toast('保存失败: ' + r.error, 'error'); return; }
      // 更新模态内启用/禁用状态
      const st = panel.querySelector('.res-detail-state');
      if (st) {
        const en = settings.enable !== undefined ? !!settings.enable : enabled;
        st.className = 'res-detail-state ' + (en ? 'on' : 'off');
        st.innerHTML = resStateHtml(en);
      }
      refreshMods(true);   // 保持当前页, 刷新列表状态标识
    }).catch(err => { toast('保存失败: ' + err, 'error'); });
  };
  // 启用/禁用电源按钮: 点击即切换并立即保存 (按钮是明确动作, 不等防抖)
  panel.querySelectorAll('.res-toggle-btn[data-set]').forEach(btn => {
    btn.addEventListener('click', () => {
      const on = btn.dataset.value !== '1';
      btn.dataset.value = on ? '1' : '0';
      btn.classList.toggle('on', on);
      btn.title = on ? '点击禁用' : '点击启用';
      btn.setAttribute('aria-pressed', on ? 'true' : 'false');
      clearTimeout(saveTimer);
      saveTimer = setTimeout(saveNow, 120);
    });
  });
  panel.querySelectorAll('[data-set]').forEach(el => {
    if (el.classList.contains('res-toggle-btn')) return;   // 电源按钮由上面单独处理
    const ev = el.type === 'text' || el.type === 'number' ? 'input' : 'change';
    el.addEventListener(ev, () => {
      clearTimeout(saveTimer);
      saveTimer = setTimeout(saveNow, 500);
    });
  });
}
