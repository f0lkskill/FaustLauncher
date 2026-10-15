/* ==============================================================================
 * js/ui/background.js — 背景图层
 * ------------------------------------------------------------------------------
 * 职责:
 *   · applyBackgrounds / refreshBackgrounds: 应用后端下发的背景图
 *   · loadBackgroundPool / startBackgroundRotation: 一次拉全整池, 之后本地随机轮换
 *   · 双层元素交替淡入; 切换皮肤时可靠、即时地换图
 * 本文件提供:
 *  函数: applyBackgrounds / refreshBackgrounds / loadBackgroundPool
 *        startBackgroundRotation / stopBackgroundRotation
 *  状态/常量: _bgSlot / _bgSeq / _bgCleanTimer / _bgPool / _bgRotateTimer / _BG_ROTATE_MS
 * 依赖: 依赖 bootstrap(api), state(BOOT); DOM: #bg-layer > #bg-img-a / #bg-img-b
 * 加载顺序: 11/22
 * ============================================================================== */
'use strict';

// ---------------- 背景 ----------------
// 两条链路分工:
//   ① 首屏: refreshBackgrounds() 向后端要**一张**随机图 -> 最快能显示 (只编码 1 张)
//   ② 轮换: loadBackgroundPool() 一次拉下**整池**背景, 之后每 _BG_ROTATE_MS 在本地
//      随机抽一张换上。换图不再走 js_api, 所以是瞬时的, 也没有"轮询"感。
//
// 2026-09-26 修正: 上一版把 25 秒轮换定时器整个删掉了 (只留"启动随机一张"),
//   结果是整场会话背景一成不变 —— 用户反馈"背景不会随机变换"。随机性本身没错,
//   错的是当时池子被后端 sorted() 锁成前 4 张, 前端在这 4 张里顺序转, 看着像轮询。
//   现在池子是全量 + 前端纯随机抽, 两个问题一起解决。
//
// 换图用两层交替淡入: #bg-img-a / #bg-img-b, 加 .on 的那层显影 (opacity .62)。
//
// 2026-09-26 两处修正:
//   ① 「切换皮肤后背景卡死」—— 旧实现加完新层后固定 1150ms 移除旧层,
//      但从不取消上一次的定时器。连续切换时时序会变成:
//        切换1: 加 b, 安排 1150ms 后移除 a
//        切换2: 加 a, 安排 1150ms 后移除 b
//        切换1 的定时器先到 -> 把切换2 刚加上的 a 摘掉
//      => 两层都没有 .on, 背景就再也不动了。
//      现在: 加新层前先取消上一个清理定时器, 定时器只移除"这一次的旧层"。
//   ② 「背景不即时更新」—— 旧实现把 100KB+ 的 data URI 通过
//      style.setProperty('--bg-image-x', 'url(...)') 交给伪元素读,
//      个别情况下这个超长自定义属性会被解析器丢弃, 而 class 已加上,
//      于是伪元素 background-image 仍是 none => 看起来"没更新"。
//      现在直接设元素自身的 style.backgroundImage, 不再经过自定义属性。
let _bgSlot = 'a';
let _bgSeq = 0;              // 单张链路的请求序号: 只接受最后一次请求的结果
let _bgCleanTimer = null;    // 待执行的"移除旧层"定时器

// ---------------- 本地背景池 ----------------
// 池子是自己轮换的, 只在"启动 / 切皮肤 / 改模糊度"时重新拉 —— 这三处都会让
// 后端 _background_files() 的结果整体换掉, 所以序号 _bgPoolSeq 一失效就丢弃旧结果。
let _bgPool = [];            // data URI 列表 (后端已应用模糊)
let _bgPoolSeq = 0;          // 池子的请求序号: 只接受最后一次请求的结果
let _bgRotateTimer = null;   // 轮换定时器
let _bgRotateIdx = -1;       // 当前显示的池内下标, 用于避免连续抽到同一张

const _BG_ROTATE_MS = 30000;    // 轮换间隔 (池内随机抽一张换上)
const _BG_CROSSFADE_MS = 1150;  // 摘掉旧层 .on 的延时。CSS 里 .bg-img 是 1.1s,
                                // 这里故意多留 50ms, 保证淡出播完再摘 —— 若小于 1.1s
                                // 旧层会在过渡中途被切掉, 画面会闪。
const _BG_POOL_TIMEOUT_MS = 60000;  // 整池要解码+缩放+编码十几张大图, 6~15s 都正常

// 核心换图: 把某个 data URI 交叉淡入到背景层。
// seq 有值 => 单张链路, 过期结果直接丢弃; seq 为 undefined => 本地轮换 (无并发竞争)。
function _bgShowUri(u, seq) {
  const layer = $('#bg-layer');
  if (!layer || !u) return Promise.resolve(false);
  return new Promise(resolve => {
    const im = new Image();
    im.onload = () => {
      if (seq !== undefined && seq !== _bgSeq) { resolve(false); return; }
      // 关键: 取消上一个尚未执行的"移除旧层"定时器, 否则它会在下一次切换
      // 之后触发, 把刚加上的层摘掉, 导致背景卡死。
      if (_bgCleanTimer) { clearTimeout(_bgCleanTimer); _bgCleanTimer = null; }
      const nextSlot = _bgSlot === 'a' ? 'b' : 'a';
      const oldSlot = _bgSlot;
      const el = document.getElementById('bg-img-' + nextSlot);
      const oldEl = document.getElementById('bg-img-' + oldSlot);
      if (!el) { resolve(false); return; }
      // 直接写元素样式: data URI 再长也不经过 CSS 自定义属性
      el.style.backgroundImage = 'url("' + u + '")';
      layer.classList.add('show-img');
      void el.offsetWidth;                 // 强制 reflow, 保证淡入过渡生效
      el.classList.add('on');
      _bgSlot = nextSlot;
      _bgCleanTimer = setTimeout(() => {
        _bgCleanTimer = null;
        if (oldEl) oldEl.classList.remove('on');
      }, _BG_CROSSFADE_MS);
      resolve(true);
    };
    im.onerror = () => resolve(false);
    im.src = u;
  });
}

// 从一份 URI 列表里随机取一张换上去 (首屏与"改模糊度"走这条)
function applyBackgrounds(uris) {
  if (!uris || !uris.length) return Promise.resolve(false);
  const u = String(uris.length > 1 ? uris[Math.floor(Math.random() * uris.length)] : uris[0]);
  return _bgShowUri(u, ++_bgSeq);
}

// 池内随机抽一张 (避开刚显示过的那张, 池子 > 1 时不会连着两次同图)
function _bgRotateStep() {
  if (_bgPool.length < 2) return;
  let n = _bgRotateIdx;
  let guard = 0;
  do {
    n = Math.floor(Math.random() * _bgPool.length);
  } while (n === _bgRotateIdx && ++guard < 20);
  _bgRotateIdx = n;
  _bgShowUri(_bgPool[n]);
}

function startBackgroundRotation() {
  stopBackgroundRotation();
  if (_bgPool.length < 2) return;   // 池里只有一张就没必要轮换
  _bgRotateTimer = setInterval(_bgRotateStep, _BG_ROTATE_MS);
}

function stopBackgroundRotation() {
  if (_bgRotateTimer) { clearInterval(_bgRotateTimer); _bgRotateTimer = null; }
}

// 一次拉下整个背景池, 到了才开始本地随机轮换。
// 与首屏那张**并行**跑: 谁先到都不会互相覆盖 (池子不主动换图, 只备料)。
function loadBackgroundPool() {
  if (!api || typeof api.get_background_pool !== 'function') return Promise.resolve(false);
  const seq = ++_bgPoolSeq;
  stopBackgroundRotation();
  _bgPool = [];
  _bgRotateIdx = -1;
  // 超时给足: 整池十几张大图要解码+缩放+base64, 慢一点也不能让轮换无声失效
  // (超时会拿到 null -> 池子保持空 -> 退回"启动随机一张"的老行为, 只是不轮换)
  return withTimeout(api.get_background_pool(), _BG_POOL_TIMEOUT_MS, null)
    .then(r => {
      if (seq !== _bgPoolSeq) return false;   // 期间又切了皮肤/改了模糊度, 丢弃这次结果
      const list = (r && r.backgrounds) ? r.backgrounds : [];
      _bgPool = list.filter(u => typeof u === 'string' && u);
      _bgRotateIdx = -1;                      // 首屏那张不在池内下标语义里, 不参与去重
      // 进入程序立刻换一次随机背景, 不等第一个 30s 轮换间隔:
      // 首屏那张是后端只编码 1 张的"单张", 这里从**整池**随机抽一张换上;
      // 池子已到齐, 所以这次换图之后看到的必然是整池里的随机一张。
      if (_bgPool.length >= 2) _bgRotateStep();
      startBackgroundRotation();
      return _bgPool.length > 0;
    })
    .catch(() => false);
}

// 模糊度等背景相关设置变更、或切换皮肤后立即重新拉取背景 (会重新随机抽一张),
// 并顺手重拉背景池 (这两件事都会让后端看到的背景目录/模糊参数整体变化)。
//
// 返回的是"首屏那张"的 Promise —— 调用方 (切皮肤) 只需等首图换完即可收尾,
// 整池在后台继续拉, 不阻塞界面。
function refreshBackgrounds() {
  if (!api) return Promise.resolve(false);
  const single = withTimeout(api.get_backgrounds(), 15000, [])
    .then(applyBackgrounds)
    .catch(() => false);
  loadBackgroundPool();     // 不 await: 池子慢，界面先出图
  return single;
}
