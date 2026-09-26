/* ==============================================================================
 * js/ui/background.js — 背景图层
 * ------------------------------------------------------------------------------
 * 职责:
 *   · applyBackgrounds / refreshBackgrounds: 应用后端下发的背景图 (每次随机一张)
 *   · 双层元素交替淡入; 切换皮肤时可靠、即时地换图
 * 本文件提供:
 *  函数: applyBackgrounds / refreshBackgrounds
 *  状态/常量: _bgSlot / _bgSeq / _bgCleanTimer
 * 依赖: 依赖 bootstrap(api), state(BOOT); DOM: #bg-layer > #bg-img-a / #bg-img-b
 * 加载顺序: 11/22
 * ============================================================================== */
'use strict';

// ---------------- 背景 ----------------
// 每次启动/刷新只从后端拿一张**随机**背景图 (后端在背景目录的全部图片里随机抽)。
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
let _bgSeq = 0;              // 请求序号: 只接受最后一次请求的结果
let _bgCleanTimer = null;    // 待执行的"移除旧层"定时器

// 返回 Promise<boolean>: 调用方 (切换皮肤) 可以等背景真的换完再收尾
function applyBackgrounds(uris) {
  if (!uris || !uris.length) return Promise.resolve(false);
  const layer = $('#bg-layer');
  if (!layer) return Promise.resolve(false);
  // 兼容多张的情况: 也只随机取一张 (纯随机, 不排队轮换)
  const u = String(uris.length > 1 ? uris[Math.floor(Math.random() * uris.length)] : uris[0]);
  const seq = ++_bgSeq;
  return new Promise(resolve => {
    const im = new Image();
    im.onload = () => {
      if (seq !== _bgSeq) { resolve(false); return; }   // 已有更新的请求, 丢弃过期结果
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
      }, 1150);
      resolve(true);
    };
    im.onerror = () => resolve(false);
    im.src = u;
  });
}

// 模糊度等背景相关设置变更、或切换皮肤后立即重新拉取背景 (会重新随机抽一张)
// 超时给足: 皮肤的背景图可能是大图, 后端要解码+压缩+base64, 6 秒偏紧
// (超时会拿到空数组 -> 背景保持旧图, 表现为"切换皮肤后背景没变")
function refreshBackgrounds() {
  if (!api) return Promise.resolve(false);
  return withTimeout(api.get_backgrounds(), 15000, [])
    .then(applyBackgrounds)
    .catch(() => false);
}
