/* ==============================================================================
 * js/ui/background.js — 背景图层
 * ------------------------------------------------------------------------------
 * 职责:
 *   · applyBackgrounds / refreshBackgrounds: 应用后端下发的背景图
 *   · startBackgroundRotation / stopBackgroundRotation: 定时轮换
 *   · 双层元素交替淡入; 切换皮肤时可靠、即时地换图
 * 本文件提供:
 *  函数: applyBackgrounds / refreshBackgrounds
 *        startBackgroundRotation / stopBackgroundRotation
 *  状态/常量: _bgSlot / _bgSeq / _bgCleanTimer / _bgRotateTimer / _bgGen / _BG_ROTATE_MS
 * 依赖: 依赖 bootstrap(api), state(BOOT); DOM: #bg-layer > #bg-img-a / #bg-img-b
 * 加载顺序: 11/22
 * ============================================================================== */
'use strict';

// ---------------- 背景 ----------------
// 首屏与轮换共用同一条轻量链路: 每次向后端要**一张随机图** (后端会避开上一张)。
//
// 2026-09-26 修正: 上一版把 25 秒轮换定时器整个删掉了 (只留"启动随机一张"),
//   结果是整场会话背景一成不变 —— 用户反馈"背景不会随机变换"。
//
// 2026-11-28 修正: 之前改成"启动时一次拉下整池 (12 张 data URI, 数 MB) 再轮换",
//   大 payload 经 pywebview 桥接很慢、甚至可能失败, 于是轮换定时器迟迟不启动,
//   表现就是"启动后一直只有一张图, 很久都不换"。现在:
//     · 每到一个间隔只请求一张, 请求体积和首屏一样小;
//     · 定时器在启动时立即跑起来, 不再等整池;
//     · 新图解码完成前旧图保持显示, 所以看不到空窗/闪烁;
//     · _bgGen 记录"背景代", 切皮肤/改模糊度时自增, 过期的异步结果直接丢弃,
//       避免切完皮肤又被上一套皮肤的图覆盖。
//
// 换图用两层交替淡入: #bg-img-a / #bg-img-b, 加 .on 的那层显影 (opacity .62)。
//
// 2026-09-26 两处修正:
//   ① 「切换皮肤后背景卡死」—— 旧实现加完新层后固定 1150ms 移除旧层,
//      但从不取消上一次的定时器。现在加新层前先取消上一个清理定时器。
//   ② 「背景不即时更新」—— 不再通过超长 CSS 自定义属性传图,
//      直接设元素自身的 style.backgroundImage。
let _bgSlot = 'a';
let _bgSeq = 0;              // 单张链路的请求序号: 只接受最后一次请求的结果
let _bgCleanTimer = null;    // 待执行的"移除旧层"定时器

// ---------------- 定时轮换 ----------------
let _bgRotateTimer = null;   // 轮换定时器
let _bgGen = 0;              // 背景代: 切皮肤/改设置后 +1, 用来丢弃过期请求

const _BG_ROTATE_MS = 20000;    // 轮换间隔 (后端每次随机一张, 并避开上一张)
const _BG_CROSSFADE_MS = 1150;  // 摘掉旧层 .on 的延时。CSS 里 .bg-img 是 1.1s,
                                // 这里故意多留 50ms, 保证淡出播完再摘 —— 若小于 1.1s
                                // 旧层会在过渡中途被切掉, 画面会闪。
const _BG_FETCH_TIMEOUT_MS = 8000;  // 单张背景请求超时 (编码一张图通常 <1s)

// 核心换图: 把某个 data URI 交叉淡入到背景层。
// seq 有值 => 单张链路, 过期结果直接丢弃; seq 为 undefined => 轮换 (无并发竞争)。
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

// 从一份 URI 列表里随机取一张换上去 (首屏与轮换共用)
function applyBackgrounds(uris) {
  if (!uris || !uris.length) return Promise.resolve(false);
  const u = String(uris.length > 1 ? uris[Math.floor(Math.random() * uris.length)] : uris[0]);
  return _bgShowUri(u, ++_bgSeq);
}

// 向后端要一张随机背景并换上; gen 过期 (期间切了皮肤/改了设置) 则丢弃结果。
function _bgFetchAndShow(gen) {
  if (!api || typeof api.get_backgrounds !== 'function') return Promise.resolve(false);
  return withTimeout(api.get_backgrounds(), _BG_FETCH_TIMEOUT_MS, [])
    .then(list => {
      if (gen !== _bgGen) return false;
      return applyBackgrounds(list);
    })
    .catch(() => false);
}

function _bgRotateStep() {
  _bgFetchAndShow(_bgGen);
}

function startBackgroundRotation() {
  stopBackgroundRotation();
  _bgRotateTimer = setInterval(_bgRotateStep, _BG_ROTATE_MS);
}

function stopBackgroundRotation() {
  if (_bgRotateTimer) { clearInterval(_bgRotateTimer); _bgRotateTimer = null; }
}

// 立即换一张随机背景, 并启动/重置轮换定时器。
// 模糊度等背景相关设置变更、或切换皮肤后都会调用这里, 让新设置立刻生效。
function refreshBackgrounds() {
  if (!api) return Promise.resolve(false);
  _bgGen += 1;
  const gen = _bgGen;
  const single = _bgFetchAndShow(gen);
  startBackgroundRotation();
  return single;
}
