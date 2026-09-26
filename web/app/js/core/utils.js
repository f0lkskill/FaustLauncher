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

// icon: 可选, icons.js 里的图标名 (为兼容原有调用, 放在末尾)
function toast(msg, type = 'info', ms = 3200, icon = '') {
  const box = $('#toasts');
  const el = document.createElement('div');
  el.className = 'toast ' + type;
  el.innerHTML = (icon ? iconSvg(icon) : '') + esc(msg);
  box.appendChild(el);
  setTimeout(() => { el.classList.add('out'); setTimeout(() => el.remove(), 320); }, ms);
}

function toastTop(msg, type = 'info', ms = 3200, icon = '') {
  let box = document.getElementById('toasts-top');
  if (!box) {
    box = document.createElement('div');
    box.id = 'toasts-top';
    document.body.appendChild(box);
  }
  const el = document.createElement('div');
  el.className = 'toast ' + type;
  el.innerHTML = (icon ? iconSvg(icon) : '') + esc(msg);
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

// 项目图标统一刷新: PROJECT_ICON 拿到 (或变化) 之后, 把页面上所有标了 data-project-icon 的
// 图标重挂一遍 —— 万一某窗口/面板在 bootstrap 之前就渲染了 (那时还是默认路径), 也不会停在坏图上。
function refreshProjectIcons() {
  try {
    document.querySelectorAll('img[data-project-icon]').forEach(img => {
      if (img.getAttribute('src') !== PROJECT_ICON) img.src = PROJECT_ICON;
    });
  } catch (e) {}
}

// ---------------- 远程图标水合 ----------------
// 启动时序保护 (2026-09-25 修「首次进入图标初始化错误」):
//   ① 闸门: 先等 app 就绪 (BOOT 拿到 = 后端 js_api 真的能用) 再等 HYDRATE_GATE_DELAY_MS。
//      启动瞬间后端还在忙 (加载插件/查更新), 这时候几十个图标一起砸过去 -> 蓝奏云限流或
//      超时 -> 失败结果被后端负缓存 60 秒 -> 首次进入图标全成兜底图, 要等一会儿或重进页面
//      才恢复。所以第一次水合整体延后, 并限制并发, 给后端留出喘息时间。
//   ② 限并发 + 错开: 同时最多 ICON_MAX_CONCURRENT 个 get_icon, 其余排队, 每次开始前错开
//      ICON_QUEUE_STAGGER_MS, 避免"46 个图标 ≈ 200+ 请求"的冷启动集中打击。
//   ③ 失败自愈: 单次失败**不卡住 spinner** (立刻回退兜底图), 之后按 ICON_RETRY_DELAYS
//      后台重试; 重试成功就把它写回当前 DOM 里所有同 url 的图标 (后端负缓存只有 60 秒,
//      最后一次重试能兜住), 不需要用户重进页面。
let APP_READY = false;                       // app.js 的 startupFinish 里置 true
const HYDRATE_GATE_DELAY_MS = 900;           // app 就绪后再等一会儿才开始拉图标
const ICON_GATE_MAX_WAIT_MS = 8000;          // 就绪信号一直没来也要放行 (避免图标永不加载)
const ICON_MAX_CONCURRENT = 4;               // 并发上限
const ICON_QUEUE_STAGGER_MS = 120;           // 排队任务开始前错开的时间
const ICON_TIMEOUT_MS = 12000;               // 单个图标请求超时
const ICON_RETRY_DELAYS = [5000, 20000, 65000];  // 失败后的后台重试退避
//   最后一次 65s 是刻意跨过后端的图标负缓存 (NEGATIVE_TTL=60s), 否则重试必然瞬时失败

let _iconGatePromise = null;
let _iconRunning = 0;
const _iconQueue = [];
const _iconUriCache = new Map();     // url -> data URI
const _iconPending = new Map();      // url -> Promise<data URI>

// 闸门: 等 app 就绪 + 再等一会儿; 超时兜底放行
function iconGate() {
  if (!_iconGatePromise) {
    _iconGatePromise = new Promise(res => {
      const t0 = Date.now();
      const wait = () => {
        if (APP_READY) { setTimeout(res, HYDRATE_GATE_DELAY_MS); return; }
        if (Date.now() - t0 >= ICON_GATE_MAX_WAIT_MS) { APP_READY = true; res(); return; }
        setTimeout(wait, 200);
      };
      wait();
    });
  }
  return _iconGatePromise;
}

// 队列: 限并发 + 错开开始时间
function _iconEnqueue(task) {
  return new Promise((resolve, reject) => {
    _iconQueue.push({ task, resolve, reject });
    _iconPump();
  });
}

function _iconPump() {
  if (_iconRunning >= ICON_MAX_CONCURRENT || !_iconQueue.length) return;
  const job = _iconQueue.shift();
  _iconRunning++;
  setTimeout(() => {
    Promise.resolve()
      .then(job.task)
      .then(v => { _iconRunning--; job.resolve(v); _iconPump(); },
            e => { _iconRunning--; job.reject(e); _iconPump(); });
  }, ICON_QUEUE_STAGGER_MS);
}

// 重试成功后写回 DOM: 页面上所有还挂着同一 url 的图标一起补上
function _applyIconToDom(url, uri) {
  if (!uri) return;
  try {
    document.querySelectorAll('img[data-icon-url]').forEach(img => {
      if (img.getAttribute('data-icon-url') === url) setIconReady(img, uri);
    });
  } catch (e) {}
}

// 单次请求 (+ 失败后按退避后台重试; 重试不占用 spinner/不阻塞调用方)
function _iconFetch(url, name, attempt) {
  return withTimeout(api.get_icon(url, name), ICON_TIMEOUT_MS, '')
    .catch(() => '')
    .then(uri => {
      if (uri) return uri;
      const delay = ICON_RETRY_DELAYS[attempt];
      if (delay != null) {
        setTimeout(() => {
          _iconEnqueue(() => _iconFetch(url, name, attempt + 1))
            .then(again => {
              if (again) { _iconUriCache.set(url, again); _applyIconToDom(url, again); }
            })
            .catch(() => {});
        }, delay);
      }
      return '';
    });
}

// 图标解析统一入口: 同一个 url 并发只请求一次, 成功结果缓存在内存
// (解析完成 = 第一次尝试结束; 失败的重试在后台跑, 不拖着调用方)
function resolveIconUri(url, name) {
  if (!url) return Promise.resolve('');
  if (_iconUriCache.has(url)) return Promise.resolve(_iconUriCache.get(url));
  if (_iconPending.has(url)) return _iconPending.get(url);
  const p = iconGate()
    .then(() => _iconEnqueue(() => _iconFetch(url, name, 0)))
    .then(uri => {
      _iconPending.delete(url);
      if (uri) _iconUriCache.set(url, uri);
      return uri || '';
    })
    .catch(() => { _iconPending.delete(url); return ''; });
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
