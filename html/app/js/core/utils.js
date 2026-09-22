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

// 图标走后端 get_icon (带磁盘缓存), 避免每次渲染都重新下载远程图标
// 返回 Promise 数组, 便于调用方在图标全部加载完成后才结束 loading (圆圈)
function hydrateIcons(root) {
  const promises = [];
  if (!api) return promises;
  const imgs = (root || document).querySelectorAll('img[data-icon-url]');
  imgs.forEach(img => {
    const url = img.getAttribute('data-icon-url');
    const name = img.getAttribute('data-icon-name') || '';
    if (!url) return;
    promises.push(withTimeout(api.get_icon(url, name), 6000, '').then(uri => {
      if (uri) img.src = uri;
    }).catch(() => {}));
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
