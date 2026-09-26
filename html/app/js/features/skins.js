/* ==============================================================================
 * js/features/skins.js — 玻璃窗 (皮肤系统)
 * ------------------------------------------------------------------------------
 * 职责:
 *   · 左侧竖排列出全部启动器皮肤 (含内置"默认皮肤"), 点击即**立刻**切换生效
 *   · 右侧是该皮肤的背景图欣赏区, 支持上一张/下一张与自动轮播
 *   · 皮肤覆盖层样式的加载与卸载 (作为 <style> 追加在默认样式之后, 两者合并生效)
 * 本文件提供:
 *  函数: applyBootSkin / loadSkinCss / refreshSkinAssets / enterSkinsPage / loadSkins /
 *        renderSkinList / pickSkin / showSkinBackgrounds / renderSkinBg / skinBgStep /
 *        toggleSkinAuto / stopSkinAuto
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

// 皮肤可能替换了 html/app/assets (assets/web) 与启动器图标, 切换后重新取一次
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
    d = await withTimeout(api.get_skins(), 20000, { skins: [], active: '' }) || d;
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
      '<span class="skin-empty-hint">把皮肤目录放进 html/app_skins/ 即可</span></div>';
    return;
  }
  skinList.forEach(s => {
    const on = s.id === skinActiveId;
    const card = document.createElement('button');
    card.type = 'button';
    card.className = 'skin-card' + (on ? ' active' : '');
    card.dataset.skinId = s.id;
    card.innerHTML =
      // profile 图铺满整张卡片当背景, 上面盖一层文字蒙版
      '<img class="skin-card-bg" src="' + (s.profile_uri || PROJECT_ICON) + '" alt="" ' +
        'onerror="this.src=\'' + PROJECT_ICON + '\'">' +
      '<div class="skin-card-mask"></div>' +
      '<div class="skin-card-info">' +
        '<div class="skin-card-name">' + esc(s.name) +
          (on ? '<span class="skin-card-badge">使用中</span>' : '') + '</div>' +
        '<div class="skin-card-desc">' + esc(s.description || '') + '</div>' +
        '<div class="skin-card-meta">' +
          (s.background_count ? s.background_count + ' 张背景' : '无背景图') +
        '</div>' +
      '</div>';
    // 蒙版用该皮肤自己的 theme_color (config.json)
    const mask = card.querySelector('.skin-card-mask');
    const maskBg = skinMaskStyle(s.theme_color);
    if (mask && maskBg) mask.style.background = maskBg;
    card.onclick = () => pickSkin(s);   // 没阻止冒泡 -> 全局点击音效正常
    list.appendChild(card);
  });
}

// 点左侧卡片: 右侧先切到它的背景, 然后**立刻**应用皮肤 (重载样式 + 资源 + 主背景)
async function pickSkin(skin) {
  showSkinBackgrounds(skin);
  await applySkin(skin);
}

// ---------------- 应用皮肤 ----------------
// 连点不同皮肤时会有多个 applySkin 并发跑; 用序号保证只有**最后一次**点击
// 负责收尾 (改列表高亮/提示), 避免先点的后返回把界面盖回旧皮肤。
async function applySkin(skin) {
  if (!api) { toast('浏览器预览模式', 'warn'); return; }
  const seq = ++_skinApplySeq;
  const r = await api.set_active_skin(skin.id).catch(e => ({ error: String(e) }));
  if (r && r.error) { toast('切换皮肤失败: ' + r.error, 'error'); return; }
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
  if (box) box.innerHTML = '<div class="skin-empty">正在读取背景图…</div>';
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
  if (!skinBgList.length) {
    box.innerHTML = '<div class="skin-empty">该皮肤没有背景图</div>';
    if (info) info.textContent = '0 / 0';
    if (nameEl) nameEl.textContent = '';
    return;
  }
  const cur = skinBgList[skinBgIdx];
  // 淡入: 换图时重播一次过渡, 让"轮询欣赏"更顺眼
  box.innerHTML = '<img class="skin-bg-img" src="' + esc(cur.uri) + '" alt="">';
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
