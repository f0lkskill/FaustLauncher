/* ==============================================================================
 * js/core/utils.js — 通用工具函数
 * ------------------------------------------------------------------------------
 * 职责:
 *   · 转义/提示条(esc / toast / toastTop)、异步兜底超时 withTimeout
 *   · 远程图标统一走后端 get_icon(带磁盘缓存)批量补水 hydrateIcons
 *   · 字节/速率格式化, 以及路径显示缩写 shortPath
 * 本文件提供:
 *  函数: esc / toast / toastTop / withTimeout / hydrateIcons / fmtBytes / fmtSpeed / shortPath
 * 依赖: 依赖 bootstrap.js(api)
 * 加载顺序: 3/22    (拆分自原 app.js 行 242-313 + 1972-1988)
 * ============================================================================== */
'use strict';

// ---------------- 工具函数 ----------------
function esc(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function toast(msg, type = 'info', ms = 3200) {
  const box = $('#toasts');
  const el = document.createElement('div');
  el.className = 'toast ' + type;
  el.innerHTML = esc(msg);
  box.appendChild(el);
  setTimeout(() => { el.classList.add('out'); setTimeout(() => el.remove(), 320); }, ms);
}

function toastTop(msg, type = 'info', ms = 3200) {
  let box = document.getElementById('toasts-top');
  if (!box) {
    box = document.createElement('div');
    box.id = 'toasts-top';
    document.body.appendChild(box);
  }
  const el = document.createElement('div');
  el.className = 'toast ' + type;
  el.innerHTML = esc(msg);
  box.appendChild(el);
  setTimeout(() => { el.classList.add('out'); setTimeout(() => el.remove(), 320); }, ms);
}

function withTimeout(p, ms, fallback) {
  // 网络请求兜底超时: 防止云端慢/断网导致页面卡死
  return Promise.race([
    Promise.resolve(p),
    new Promise(res => setTimeout(() => res(fallback), ms)),
  ]);
}

// 1x1 透明图: 图标加载期间拿它占位, 配合 .icon-loading 显示转圈动画
const ICON_BLANK = 'data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7';

// 图标进入"加载中": 转圈动画 (避免先显示占位图再跳变)
function setIconLoading(img) {
  if (!img) return;
  img.classList.remove('icon-fade');
  img.classList.add('icon-loading');
  img.src = ICON_BLANK;
}

// 图标到手: 落图 + 淡入; uri 为空则回退项目图标
function setIconReady(img, uri) {
  if (!img) return;
  img.classList.remove('icon-loading');
  img.src = uri || PROJECT_ICON;
  img.classList.remove('icon-fade');
  void img.offsetWidth;              // 强制重排, 让淡入动画能重播
  img.classList.add('icon-fade');
}

// 图标解析统一入口: 同一个 url 并发只请求一次, 结果缓存在内存
const _iconUriCache = new Map();     // url -> data URI
const _iconPending = new Map();      // url -> Promise<data URI>

function resolveIconUri(url, name) {
  if (!url) return Promise.resolve('');
  if (_iconUriCache.has(url)) return Promise.resolve(_iconUriCache.get(url));
  if (_iconPending.has(url)) return _iconPending.get(url);
  const done = (uri) => {
    _iconPending.delete(url);
    if (uri) _iconUriCache.set(url, uri);
    return uri || '';
  };
  const p = withTimeout(api.get_icon(url, name), 9000, '')
    .then(uri => done(uri))
    .catch(() => done(''));
  _iconPending.set(url, p);
  return p;
}

// 图标走后端 get_icon (带磁盘缓存), 避免每次渲染都重新下载远程图标
// 加载期间先播转圈动画; 返回 Promise 数组, 便于调用方在图标全部加载完成后才结束 loading
function hydrateIcons(root) {
  const promises = [];
  if (!api) return promises;
  const imgs = (root || document).querySelectorAll('img[data-icon-url]');
  imgs.forEach(img => {
    const url = img.getAttribute('data-icon-url');
    const name = img.getAttribute('data-icon-name') || '';
    if (!url) return;
    setIconLoading(img);
    promises.push(resolveIconUri(url, name).then(uri => {
      setIconReady(img, uri);
      // 下载任务抽屉: 顺带把结果记到任务上, 下次渲染直接用
      const taskName = img.getAttribute('data-icon-task');
      if (taskName && typeof downloadTasks !== 'undefined') {
        const task = downloadTasks.find(x => x.name === taskName);
        if (task) task.iconUri = uri || '';
      }
    }));
  });
  return promises;
}

function fmtBytes(n) {
  if (n == null) return '-';
  n = Number(n);
  if (n >= 1024 * 1024 * 1024) return (n / 1024 / 1024 / 1024).toFixed(2) + ' GB';
  if (n >= 1024 * 1024) return (n / 1024 / 1024).toFixed(1) + ' MB';
  if (n >= 1024) return (n / 1024).toFixed(1) + ' KB';
  return n + ' B';
}

// 后端 speed 单位是 KB/s (非字节)
function fmtSpeed(kbps) {
  kbps = Number(kbps) || 0;
  if (kbps >= 1024) return (kbps / 1024).toFixed(2) + ' MB/s';
  if (kbps >= 1) return kbps.toFixed(1) + ' KB/s';
  return Math.round(kbps * 1024) + ' B/s';
}

// ---- 路径显示缩写(过长路径中间省略) ----
function shortPath(p) {
    p = String(p || '');
    const parts = p.split(/[\\/]/);
    const fileName = parts.slice(-1)[0]; // 获取最后一级
    
    // 如果整个路径长度小于等于10，直接返回
    if (p.length <= 10) return p;
    
    // 获取路径部分（不含文件名）
    const pathPart = parts.slice(0, -1).join('/');
    // 路径部分取前10个字符，加上文件名
    if (pathPart.length > 10) {
        return pathPart.substring(0, 10) + '.../' + fileName.substring(0, 5) + '...';
    }
    return p;
}
