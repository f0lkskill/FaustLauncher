/* ==============================================================================
 * js/features/skins.js — 玻璃窗 (皮肤系统)
 * ------------------------------------------------------------------------------
 * 职责:
 *   · 左侧竖排列出全部启动器皮肤 (含内置"默认皮肤"与云端尚未下载的皮肤),
 *     点击即**立刻**切换生效
 *   · 未下载 / 版本落后的皮肤在点选时自动从云端下载并解压, 卡片上显示进度
 *   · 右侧是该皮肤的背景图欣赏区, 支持上一张/下一张与自动轮播
 *   · 皮肤覆盖层样式的加载与卸载 (作为 <style> 追加在默认样式之后, 两者合并生效)
 * 本文件提供:
 *  函数: applyBootSkin / loadSkinCss / refreshSkinAssets / enterSkinsPage / loadSkins /
 *        renderSkinList / skinBadges / skinCardMeta / setSkinProgress / clearSkinProgress /
 *        syncSkinProgress / ensureSkinReady / pickSkin / showSkinBackgrounds / renderSkinBg /
 *        skinBgStep / toggleSkinAuto / stopSkinAuto / refreshCloudSkins
 *  状态/常量: skinList / skinActiveId / skinBgList / skinBgIdx / skinBgTimer / skinsInited
 * 依赖: 依赖 bootstrap($/api) / state / utils / ui.background(refreshBackgrounds)
 * ============================================================================== */
'use strict';

let skinList = [];          // 后端下发的皮肤列表
let skinActiveId = '';      // 当前生效的皮肤 id ('' = 默认皮肤)
let skinBgList = [];        // 当前展示皮肤的背景图 [{name, uri}]
let skinBgIdx = 0;          // 背景图欣赏区当前下标
let skinBgTimer = null;     // 自动轮播定时器
let skinsInited = false;    // 玻璃窗首次进入标记
let _skinBgSeq = 0;         // 背景列表请求序号 (防快速连点导致的并发乱序)
let _skinApplySeq = 0;      // 应用皮肤序号 (只让最后一次点击收尾)

// ---------------- 覆盖层样式 ----------------
// 皮肤 CSS 由后端读成文本下发 (皮肤目录不在 http 根目录下, 前端取不到路径),
// 这里作为 <style> 追加在默认 style.css **之后** —— 合并生效, 皮肤只需写差异部分。
// 把一段皮肤 CSS 挂上去 (空串 = 摘掉, 回到默认皮肤)
function applySkinCssText(css) {
  let el = document.getElementById('skin-css');
  if (!css) {
    if (el) el.remove();
    return;
  }
  if (!el) {
    el = document.createElement('style');
    el.id = 'skin-css';
    document.head.appendChild(el);
  }
  el.textContent = css;
}

async function loadSkinCss(skinId) {
  let css = '';
  if (skinId && api) {
    css = await withTimeout(api.get_skin_css(skinId), 8000, '').catch(() => '') || '';
  }
  applySkinCssText(css);
}

// 启动早期调用: Splash(转圈界面) 在 bootstrap/render 之前就显示了,
// 不在这里先注入的话, 启动画面会用默认皮肤, 之后再闪一下换成皮肤样式。
async function loadBootSkinEarly() {
  if (!api || typeof api.get_active_skin_css !== 'function') return;
  try {
    const css = await withTimeout(api.get_active_skin_css(), 6000, '') || '';
    if (css) applySkinCssText(css);
  } catch (e) { /* 拿不到就等 render 阶段正常注入 */ }
}

// 启动时按 settings.json 里的皮肤设置加载覆盖层 (切换皮肤时复用同一函数)
function applyBootSkin(skinId) {
  skinActiveId = skinId || '';
  return loadSkinCss(skinActiveId);
}

// 皮肤可能替换了 web/app/assets (assets/web) 与启动器图标, 切换后重新取一次
async function refreshSkinAssets() {
  if (!api) return;
  try {
    const b = await withTimeout(api.get_bootstrap(), 12000, null);
    if (!b) return;
    if (b.icon_uri) {
      PROJECT_ICON = b.icon_uri;
      document.querySelectorAll('.hero-aside .hero-bg-icon, .brand-icon, #titlebar .tb-icon')
        .forEach(img => { img.src = b.icon_uri; });
    }
    if (typeof refreshProjectIcons === 'function') refreshProjectIcons();
    // 快捷方式/工具卡片素材也可能被皮肤替换, 重渲染一次
    if (b.features && typeof renderFeatures === 'function') renderFeatures(b.features);
    if (b.tools && typeof renderTools === 'function') renderTools(b.tools);
  } catch (e) { /* 资源刷新失败不影响皮肤样式本身 */ }
}

// ---------------- 玻璃窗页面 ----------------
function enterSkinsPage() {
  if (!api) return;
  if (!skinsInited) {
    skinsInited = true;
    loadSkins();
  }
}

async function loadSkins() {
  const list = $('#skin-list');
  if (!list) return;
  list.innerHTML = '<div class="skin-empty">正在读取皮肤…</div>';
  let d = { skins: [], active: '' };
  try {
    // 不能套 withTimeout: 超时后 pywebview 仍会回调那个已被删掉的 id,
    // 前端直接抛 "…is not a function"。后端有预取缓存, 正常一笔就返回。
    d = await api.get_skins() || d;
  } catch (e) {
    toast('读取皮肤失败: ' + e, 'error');
  }
  skinList = d.skins || [];
  skinActiveId = d.active || '';
  renderSkinList();
  // 右侧默认展示"当前正在用的"皮肤的背景 (只预览, 不写设置)
  const cur = skinList.find(s => s.id === skinActiveId) || skinList[0];
  if (cur) showSkinBackgrounds(cur);
}


// 皮肤卡片蒙版: 用皮肤 config.json 里的 theme_color 生成。
// 直接拿主题色当蒙版会太亮 (文字看不清), 所以取它的**暗调** ——
// 既体现皮肤自己的色调, 又保证白色文字始终可读。
function skinMaskStyle(themeColor) {
  const hex = String(themeColor || '').trim();
  if (!/^#[0-9a-fA-F]{6}$/.test(hex)) return '';      // 没配主题色 -> 用默认黑色蒙版
  const n = parseInt(hex.slice(1), 16);
  const f = 0.28;                                      // 压暗系数
  const r = Math.round(((n >> 16) & 255) * f);
  const g = Math.round(((n >> 8) & 255) * f);
  const b = Math.round((n & 255) * f);
  const c = r + ',' + g + ',' + b;
  return 'linear-gradient(180deg,' +
    'rgba(' + c + ',.06) 0%,' +
    'rgba(' + c + ',.46) 45%,' +
    'rgba(' + c + ',.90) 100%)';
}

function renderSkinList() {
  const list = $('#skin-list');
  if (!list) return;
  list.innerHTML = '';
  const cnt = $('#skin-side-count');
  if (cnt) cnt.textContent = skinList.length ? skinList.length + ' 个' : '';
  if (!skinList.length) {
    list.innerHTML = '<div class="skin-empty">没有找到皮肤<br>' +
      '<span class="skin-empty-hint">联网后会自动获取云端皮肤</span></div>';
    return;
  }
  skinList.forEach(s => {
    const on = s.id === skinActiveId;
    const card = document.createElement('button');
    const badges = skinBadges(s, on);
    card.type = 'button';
    card.className = 'skin-card' +
      (on ? ' active' : '') +
      (s.unlocked === false ? ' locked' : '') +
      (s.installed === false ? ' remote' : '') +
      (s.installed === false && s.publishable === false ? ' offline' : '');
    card.dataset.skinId = s.id;
    card.innerHTML =
      // profile 图铺满整张卡片当背景, 上面盖一层文字蒙版
      '<img class="skin-card-bg" src="' + (s.profile_uri || PROJECT_ICON) + '" alt="" ' +
        'onerror="this.src=\'' + PROJECT_ICON + '\'">' +
      '<div class="skin-card-mask"></div>' +
      '<div class="skin-card-info">' +
        '<div class="skin-card-name">' + esc(s.name) + badges + '</div>' +
        '<div class="skin-card-desc">' + esc(s.description || '') + '</div>' +
        '<div class="skin-card-meta">' + skinCardMeta(s) + '</div>' +
      '</div>' +
      '<div class="skin-card-progress"><i></i></div>';
    // 蒙版用该皮肤自己的 theme_color (config.json)
    const mask = card.querySelector('.skin-card-mask');
    const maskBg = skinMaskStyle(s.theme_color);
    if (mask && maskBg) mask.style.background = maskBg;
    card.onclick = () => pickSkin(s);   // 没阻止冒泡 -> 全局点击音效正常
    list.appendChild(card);
  });
  syncSkinProgress();
}

// 卡片右上角的状态徽章: 使用中 / 待解锁 / 未下载 / 未发布 / 可更新
function skinBadges(s, on) {
  if (on) return '<span class="skin-card-badge">使用中</span>';
  if (s.unlocked === false) return '<span class="skin-card-badge locked-badge">待解锁</span>';
  if (s.installed === false && s.publishable === false) {
    return '<span class="skin-card-badge offline-badge">未发布</span>';
  }
  if (s.installed === false) return '<span class="skin-card-badge remote-badge">未下载</span>';
  if (s.needs_update) return '<span class="skin-card-badge update-badge">可更新</span>';
  return '';
}

// 卡片底部的信息行: 已下载的显示背景数量, 未下载的显示云端版本
function skinCardMeta(s) {
  if (s.installed === false) {
    if (s.publishable === false) return '皮肤包尚未发布';
    const ver = String(s.cloud_version || '').trim();
    return ver ? '云端 ' + esc(ver) : '点击下载';
  }
  const parts = [s.background_count ? s.background_count + ' 张背景' : '无背景图'];
  if (s.cloud_version) {
    const ver = String(s.cloud_version).trim();
    if (s.needs_update) parts.push('云端 ' + esc(ver));
    else if (ver) parts.push(esc(ver));
  }
  return parts.join(' · ');
}

// ---------------- 云端皮肤下载 ----------------
// 未安装或版本落后的皮肤, 点一下要先把包下下来; 进度通过 skin_progress
// 事件从后端推过来, 这里只负责把百分比画到卡片上。
let _skinProgress = {};     // {皮肤 id: {percent, message}}

function setSkinProgress(id, percent, message) {
  _skinProgress[id] = { percent: percent, message: message || '' };
  syncSkinProgress(id);
}

function clearSkinProgress(id) {
  delete _skinProgress[id];
  syncSkinProgress(id);
}

function syncSkinProgress(id) {
  const list = $('#skin-list');
  if (!list) return;
  skinList.forEach(s => {
    const card = list.querySelector('.skin-card[data-skin-id="' + CSS.escape(s.id) + '"]');
    if (!card) return;
    const p = _skinProgress[s.id];
    const bar = card.querySelector('.skin-card-progress');
    if (!p) {
      card.classList.remove('downloading');
      if (bar) bar.style.display = 'none';
      return;
    }
    card.classList.add('downloading');
    if (bar) {
      bar.style.display = 'block';
      const i = bar.querySelector('i');
      if (i) i.style.width = Math.max(4, Math.min(100, p.percent || 0)) + '%';
    }
  });
}

// 等后端把皮肤包准备好 (下载 + 解压); 进度条跟着走
async function ensureSkinReady(skin) {
  if (!api) return false;
  if (skin.installed !== false && !skin.needs_update) return true;
  if (skin.installed === false && skin.publishable === false) {
    toast('这款皮肤的皮肤包还没有发布, 请稍后再试', 'warn');
    return false;
  }
  const label = skin.installed === false ? '正在下载皮肤…' : '正在更新皮肤…';
  toast(label, 'info');
  setSkinProgress(skin.id, 0, label);
  // 先在原生下载抽屉里登记一行 (图标用云端缓存封面), 后端进度按皮肤名回填
  if (typeof startSkinDownload === 'function') startSkinDownload(skin);
  let r;
  try {
    r = await api.prepare_skin(skin.id);
  } catch (e) {
    r = { ok: false, error: String(e) };
  }
  clearSkinProgress(skin.id);
  if (typeof endSkinDownload === 'function') {
    endSkinDownload(skin, !!(r && r.ok), (r && r.error) || '');
  }
  if (!r || !r.ok) {
    toast('皮肤下载失败: ' + ((r && r.error) || '未知错误'), 'error');
    return false;
  }
  // 装完之后本地信息变了, 重新拉一次列表 (保留当前高亮)
  const keep = skinActiveId;
  await loadSkins();
  skinActiveId = keep;
  renderSkinList();
  return true;
}

// 点左侧卡片: 右侧先切到它的背景, 然后**立刻**应用皮肤 (重载样式 + 资源 + 主背景)
// 未下载/有更新的皮肤先走一次云端下载, 装好后再应用。
async function pickSkin(skin) {
  if (skin.unlocked === false) {
    if (typeof openSkinUnlockModal === 'function') openSkinUnlockModal(skin);
    return;
  }
  const ready = await ensureSkinReady(skin);
  if (!ready) return;
  // 皮肤可能是刚下载的, 用列表里的新对象继续 (带上了 background_count 等信息)
  const fresh = skinList.find(s => s.id === skin.id) || skin;
  showSkinBackgrounds(fresh);
  await applySkin(fresh);
}

// ---------------- 应用皮肤 ----------------
// 连点不同皮肤时会有多个 applySkin 并发跑; 用序号保证只有**最后一次**点击
// 负责收尾 (改列表高亮/提示), 避免先点的后返回把界面盖回旧皮肤。
async function applySkin(skin) {
  if (!api) { toast('浏览器预览模式', 'warn'); return; }
  const seq = ++_skinApplySeq;
  let r;
  try {
    r = await api.set_active_skin(skin.id);
  } catch (e) {
    r = { error: String(e) };
  }
  // 后端在应用前还会再核对一次皮肤包, 还是会自动下载并弹抽屉, 这里只接管失败
  if (r && r.error) {
    toast('切换皮肤失败: ' + r.error, 'error');
    if (typeof endSkinDownload === 'function') endSkinDownload(skin, false, r.error);
    return;
  }
  if (typeof endSkinDownload === 'function') endSkinDownload(skin, true);
  if (seq !== _skinApplySeq) return;             // 期间又点了别的皮肤
  skinActiveId = skin.id;
  renderSkinList();
  await loadSkinCss(skin.id);      // 覆盖层样式立即生效
  await refreshBackgrounds();      // 主背景换成该皮肤的图 (等它真的换完再收尾)
  await refreshSkinAssets();       // 图标/卡片素材跟随皮肤
  if (seq !== _skinApplySeq) return;
  toast('已应用皮肤: ' + skin.name, 'success');
}

// ---------------- 右侧: 背景图欣赏 ----------------
async function showSkinBackgrounds(skin) {
  const seq = ++_skinBgSeq;
  const box = $('#skin-preview');
  if (box) {
    // 先清掉上一款皮肤的图, 再交给统一的转圈遮罩 (不显示文字)
    box.innerHTML = '<div class="frame-spinner"><span></span></div>';
    showFrameLoading(box);
  }
  const info = $('#skin-bg-info');
  if (info) info.textContent = '…';
  const nameEl = $('#skin-bg-name');
  if (nameEl) nameEl.textContent = '';

  let d = { backgrounds: [] };
  try {
    d = await withTimeout(api.get_skin_backgrounds(skin.id), 30000, { backgrounds: [] }) || d;
  } catch (e) { /* 下面按空列表处理 */ }
  if (seq !== _skinBgSeq) return;   // 已经切到别的皮肤, 丢弃这次结果
  skinBgList = d.backgrounds || [];
  skinBgIdx = 0;
  renderSkinBg();
}

function renderSkinBg() {
  const box = $('#skin-preview');
  const info = $('#skin-bg-info');
  const nameEl = $('#skin-bg-name');
  if (!box) return;
  // 遮罩始终留在容器里 (上一帧刚换完 innerHTML, 这里重新取一次), 收起后只露出图或空态
  const spinner = '<div class="frame-spinner"><span></span></div>';
  if (!skinBgList.length) {
    box.innerHTML = '<div class="skin-empty">该皮肤没有背景图</div>' + spinner;
    hideFrameLoading(box);
    if (info) info.textContent = '0 / 0';
    if (nameEl) nameEl.textContent = '';
    return;
  }
  const cur = skinBgList[skinBgIdx];
  // 淡入: 换图时重播一次过渡, 让"轮询欣赏"更顺眼
  box.innerHTML = '<img class="skin-bg-img" src="' + esc(cur.uri) + '" alt="">' + spinner;
  hideFrameLoading(box);
  const img = box.querySelector('.skin-bg-img');
  if (img) { void img.offsetWidth; img.classList.add('in'); }
  if (info) info.textContent = (skinBgIdx + 1) + ' / ' + skinBgList.length;
  if (nameEl) nameEl.textContent = cur.name || '';
}

function skinBgStep(delta) {
  if (!skinBgList.length) return;
  skinBgIdx = (skinBgIdx + delta + skinBgList.length) % skinBgList.length;
  renderSkinBg();
}

function stopSkinAuto() {
  if (skinBgTimer) { clearInterval(skinBgTimer); skinBgTimer = null; }
  const btn = $('#skin-bg-auto');
  if (btn) { btn.textContent = '▶'; btn.classList.remove('on'); }
}

function toggleSkinAuto() {
  if (skinBgTimer) { stopSkinAuto(); return; }
  skinBgTimer = setInterval(() => skinBgStep(1), 4000);
  const btn = $('#skin-bg-auto');
  if (btn) { btn.textContent = '❚❚'; btn.classList.add('on'); }
}

function bindSkinEvents() {
  on('#skin-bg-prev', 'click', () => skinBgStep(-1));
  on('#skin-bg-next', 'click', () => skinBgStep(1));
  on('#skin-bg-auto', 'click', toggleSkinAuto);
}

// 云端皮肤清单在后台刷新完成 (后端推到 skin_themes_changed):
// 只有已进过玻璃窗才重绘, 免得用户在别的页面时白白重排一遍列表。
function refreshCloudSkins() {
  if (!skinsInited) return;
  loadSkins();
}
