/* ==============================================================================
 * js/core/icons.js — 统一 SVG 图标仓库 (assets/icon/*.svg)
 * ------------------------------------------------------------------------------
 * 职责:
 *   · 提供 ICONS 名称表, 取代此前散落在 HTML/JS 里的 emoji 字符
 *   · iconSvg(name, opts) 生成内联 SVG 标记; 图标用 currentColor 描绘, 颜色跟随
 *     所在元素的 CSS color, 因此 hover/激活/禁用态无需再写一份图标
 *   · ICON_URL(name) 供需要 <img src> 的场景取路径
 * 说明:
 *   · SVG 素材来自用户提供的图标包, 已按英文名归档到 assets/icon/
 *   · 项目图标 (icon.png) 与插件/Mod 自带图标不使用本仓库, 保持原样
 * 本文件提供:
 *  状态/常量: ICONS / ICON_BASE
 *  函数: iconSvg / iconImg / ICON_URL
 * 依赖: 无 (只需最先加载的核心文件之后)
 * 加载顺序: 3/23 (紧随 state.js, 供后续所有界面文件使用)
 * ============================================================================== */
'use strict';

const ICON_BASE = 'assets/icon/';

// 图标名 -> 文件名 (全部为 assets/icon/<name>.svg)
const ICONS = {
  add: 'add.svg',
  addPicture: 'add-picture.svg',
  allApplication: 'all-application.svg',
  boltOne: 'bolt-one.svg',
  bookmark: 'bookmark.svg',
  bookmarkOne: 'bookmark-one.svg',
  bug: 'bug.svg',
  caution: 'caution.svg',
  close: 'close.svg',
  code: 'code.svg',
  downloadTwo: 'download-two.svg',
  fileAdditionOne: 'file-addition-one.svg',
  fileStaffOne: 'file-staff-one.svg',
  fileSuccess: 'file-success.svg',
  folderDownload: 'folder-download.svg',
  hamburger: 'hamburger-button.svg',
  harm: 'harm.svg',
  install: 'install.svg',
  key: 'key.svg',
  keyhole: 'keyhole.svg',
  like: 'like.svg',
  more: 'more.svg',
  moreApp: 'more-app.svg',
  moreOne: 'more-one.svg',
  moreTwo: 'more-two.svg',
  paperclip: 'paperclip.svg',
  pic: 'pic.svg',
  power: 'power.svg',
  previewClose: 'preview-close-one.svg',
  protect: 'protect.svg',
  reduceOne: 'reduce-one.svg',
  refresh: 'refresh.svg',
  save: 'save-one.svg',
  search: 'search.svg',
  settingConfig: 'setting-config.svg',
  settingTwo: 'setting-two.svg',
  share: 'share.svg',
  shareThree: 'share-three.svg',
  tool: 'tool.svg',
  translate: 'translate.svg',
  unlock: 'unlock.svg',
  uploadPicture: 'upload-picture.svg',
  write: 'write.svg',
  zoomIn: 'zoom-in.svg',
  zoomOut: 'zoom-out.svg',
};

function ICON_URL(name) {
  return ICON_BASE + (ICONS[name] || ICONS.tool);
}

// 内联 SVG: 允许 CSS 着色 (currentColor) 与尺寸控制, 优于 <img>
//   name: ICONS 的键或直接给 "xxx.svg"
//   opts.cls  附加 class; opts.size 字号(px, 同时决定宽高)
function iconSvg(name, opts) {
  opts = opts || {};
  const file = ICONS[name] || name;
  const url = ICON_BASE + file;
  const cls = 'ico' + (opts.cls ? ' ' + opts.cls : '');
  const size = opts.size ? ' style="width:' + opts.size + 'px;height:' + opts.size + 'px"' : '';
  // 用 <use> 引用 sprite 太绕; 直接用 SVG 的 <image> 会丢掉 currentColor,
  // 因此这里按需在运行时拉取并内联(见 hydrateSvgIcons), 该函数只输出占位节点。
  return '<svg class="' + cls + '" data-icon="' + esc(file) + '" viewBox="0 0 48 48"' +
    ' fill="none" aria-hidden="true"' + size + '>' + '</svg>';
}

// 图标素材缓存: 名称 -> 已剔除 XML 头/宽高属性的 <svg> 内部内容
const _svgCache = new Map();
const _svgPending = new Map();

// 拉取一份 SVG, 返回可直接塞进占位 <svg> 的内部标记 + viewBox
function _loadSvg(file) {
  if (_svgCache.has(file)) return Promise.resolve(_svgCache.get(file));
  if (_svgPending.has(file)) return _svgPending.get(file);
  const p = fetch(ICON_BASE + file)
    .then(r => (r.ok ? r.text() : Promise.reject(new Error('HTTP ' + r.status))))
    .then(text => {
      const m = /<svg([^>]*)>([\s\S]*)<\/svg>/i.exec(text);
      if (!m) throw new Error('bad svg: ' + file);
      const attrs = m[1];
      const vb = /viewBox="([^"]+)"/i.exec(attrs);
      const inner = m[2].replace(/<\?xml[\s\S]*?\?>/g, '').trim();
      const out = { inner: inner, viewBox: vb ? vb[1] : '0 0 48 48' };
      _svgCache.set(file, out);
      _svgPending.delete(file);
      return out;
    })
    .catch(e => { _svgPending.delete(file); throw e; });
  _svgPending.set(file, p);
  return p;
}

// 把 root 内所有 data-icon 占位替换成真实的 SVG 内容 (幂等: 已填充的会打标记跳过)
function hydrateSvgIcons(root) {
  const nodes = (root || document).querySelectorAll('svg[data-icon]:not([data-icon-ready])');
  nodes.forEach(node => {
    const file = node.dataset.icon;
    node.setAttribute('data-icon-ready', '1');   // 先占位, 避免重复排队
    _loadSvg(file).then(svg => {
      node.setAttribute('viewBox', svg.viewBox);
      node.innerHTML = svg.inner;
    }).catch(() => {
      // 拉取失败(磁盘/服务瞬时不可用): 摘掉标记, 稍后自动重试 ——
      // 不能一直留空, 否则整页图标静默消失。
      node.removeAttribute('data-icon-ready');
      const tries = Number(node.dataset.iconRetry || 0);
      if (tries < 3) {
        node.dataset.iconRetry = String(tries + 1);
        setTimeout(() => { hydrateSvgIcons(node.parentNode || document); },
                   800 * (tries + 1));
      }
    });
  });
}

// 自动水合: 任何地方 (innerHTML / createElement) 插入的 data-icon 占位都会被补全。
// 有了它, 各渲染函数不必记得手动调用 hydrateSvgIcons, 从根上避免"漏调用 -> 空图标"。
(function _autoHydrateSvgIcons() {
  let scheduled = false;
  const run = () => { scheduled = false; hydrateSvgIcons(document); };
  const schedule = () => { if (!scheduled) { scheduled = true; setTimeout(run, 0); } };
  const start = () => {
    hydrateSvgIcons(document);
    try {
      new MutationObserver(schedule).observe(document.documentElement, {
        childList: true, subtree: true,
      });
    } catch (e) { /* 极老内核不支持时退化为仅在插桩点手动调用 */ }
  };
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start);
  } else {
    start();
  }
})();

// 生成一个 <img> 图标 (用于必须用图片的场合, 颜色不可变)
function iconImg(name, opts) {
  opts = opts || {};
  const cls = opts.cls || 'ico-img';
  const size = opts.size ? ' width="' + opts.size + '" height="' + opts.size + '"' : '';
  const alt = opts.alt ? esc(opts.alt) : '';
  return '<img class="' + cls + '" src="' + ICON_URL(name) + '" alt="' + alt + '"' + size + '>';
}

// 图标 + 文案 的组合标记。调用方传纯文本, 这里负责转义 ——
// 专供原先用 textContent 拼 "✓ 已完成" 这类位置改用 innerHTML。
// 图标与文字之间固定留一个空格 (下载小图标和次数之间需要看得清的间隔)。
function icoText(name, text) {
  return iconSvg(name) + ' ' + esc(text == null ? '' : text);
}

// ---- 旧 emoji 兼容映射 ----
// 后端 (如 game_launcher.py 的启动流水线) 历史上把 emoji 字符当作 icon 推给前端。
// 旧版 Tk UI 仍在使用这些字符, 所以不改后端, 只在前端做一次"emoji -> 图标名"映射,
// 保证新旧两条渲染路径都能拿到图形图标。
const LEGACY_ICON_MAP = {
  '🚀': 'power', '🔍': 'search', '📥': 'downloadTwo', '🗂️': 'folderDownload',
  '💬': 'paperclip', '📦': 'code', '🧩': 'moreApp', '✅': 'fileSuccess',
  '❌': 'harm', '🎮': 'allApplication', '⚠': 'caution', '⬇': 'downloadTwo',
  '✓': 'fileSuccess', '✗': 'caution', '📁': 'allApplication', '🔄': 'refresh',
  '📝': 'write', '📖': 'bookmarkOne', '📒': 'paperclip', '🔧': 'settingConfig',
  '💻': 'code', '📂': 'folderDownload', '🎯': 'translate', '📌': 'bookmarkOne',
  '🕐': 'write', '🎲': 'like', '🔌': 'boltOne', '➕': 'fileAdditionOne',
  '↻': 'refresh', '⟳': 'refresh', '✕': 'reduceOne', '●': 'power', '○': 'power',
  '🔊': 'like', '🖼️': 'pic', '📄': 'fileStaffOne', '❓': 'caution', '🎵': 'like',
  '📚': 'bookmark', '🧷': 'paperclip', '⚙️': 'settingTwo', '🎨': 'pic',
};

// 面板右上角关闭按钮 (统一图标), 供各工具面板/模态复用。
// 这里用 close.svg (标准的 X), 不用 reduce-one:
//   · preview-close-one 是"被划掉的眼睛", 语义是隐藏, 不能当关闭;
//   · reduce-one 是圆圈减号, 语义是"减少/禁用", 归给启用禁用按钮。
// cls 默认 panel-close; 需要不同外观时传自己的 class (如版本弹窗的 ver-x)。
function panelCloseBtn(id, cls, extra) {
  return '<button class="' + (cls || 'panel-close') + '"' + (id ? ' id="' + id + '"' : '') +
    (extra ? ' ' + extra : '') + '>' + iconSvg('close') + '</button>';
}

// emoji -> 图标名。带不带变体选择符 (U+FE0E/U+FE0F) 都要能命中:
// 同一个符号在源码里可能写成 "X️" 也可能写成 "X", 二者码点不同但显示一致,
// 所以三个候选都试一遍 (原样 / 去变体符 / 去变体符再加 FE0F)。
function legacyIconName(value) {
  if (!value) return '';
  const v = String(value);
  const bare = v.replace(/[\uFE0E\uFE0F]/g, '');
  return LEGACY_ICON_MAP[v]
    || LEGACY_ICON_MAP[bare]
    || LEGACY_ICON_MAP[bare + '\uFE0F']
    || '';
}

// 依次尝试: 图标名 -> 旧 emoji
function iconSvgAuto(value) {
  if (!value) return '';
  const v = String(value);
  if (ICONS[v]) return iconSvg(v);
  const mapped = legacyIconName(v);
  return mapped ? iconSvg(mapped) : '';
}

// 把 "📁 游戏目录" 这样的标题拆成 { icon, text }。
// 快捷方式/工具卡片的 name 由后端提供且带 emoji 前缀 —— open_feature 是按**完整
// 字符串**(含 emoji)匹配的, 旧版 Tk UI 也依赖它, 因此数据层不能改;
// 这里只在渲染时把前缀 emoji 摘出来换成 SVG 图标, 文字部分原样使用。
function splitLegacyIcon(name) {
  const raw = String(name == null ? '' : name);
  const sp = raw.indexOf(' ');
  if (sp > 0) {
    const head = raw.slice(0, sp);
    if (legacyIconName(head)) {
      return { icon: head, text: raw.slice(sp + 1) };
    }
  }
  return { icon: '', text: raw };
}
