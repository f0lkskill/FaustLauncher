/* ==============================================================================
 * js/ui/background.js — 背景图层
 * ------------------------------------------------------------------------------
 * 职责:
 *   · applyBackgrounds / refreshBackgrounds: 应用后端下发的背景图 (每次只随机一张, 不定时轮换)
 * 本文件提供:
 *  函数: applyBackgrounds / refreshBackgrounds
 *  状态/常量: _bgSlot
 * 依赖: 依赖 bootstrap(api), state(BOOT)
 * 加载顺序: 11/22    (拆分自原 app.js 行 3288-3327)
 * ============================================================================== */
'use strict';

// ---------------- 背景 ----------------
// 每次启动/刷新只从后端拿一张**随机**背景图 (后端在 background 目录的**全部**图片里随机抽),
// 不再定时轮换: 以前每 25 秒自动换 + 池子固定为 sorted() 前 4 张, 看着就是"轮询"。
let _bgSlot = 'a';

function applyBackgrounds(uris) {
  if (!uris || !uris.length) return;
  const layer = $('#bg-layer');
  if (!layer) return;
  // 兼容多张的情况: 也只随机取一张 (纯随机, 不排队轮换)
  const u = String(uris.length > 1 ? uris[Math.floor(Math.random() * uris.length)] : uris[0]);
  const im = new Image();
  im.onload = () => {
    const nextSlot = _bgSlot === 'a' ? 'b' : 'a';
    layer.style.setProperty('--bg-image-' + nextSlot, 'url("' + u.replace(/"/g, '\\"') + '")');
    layer.classList.add('show-img');
    void layer.offsetWidth;
    layer.classList.add('bg-' + nextSlot);
    const oldSlot = _bgSlot;
    setTimeout(() => layer.classList.remove('bg-' + oldSlot), 1150);
    _bgSlot = nextSlot;
  };
  im.src = u;
}

// 模糊度等背景相关设置变更后立即重新拉取背景 (会重新随机抽一张)
function refreshBackgrounds() {
  if (api) withTimeout(api.get_backgrounds(), 6000, []).then(applyBackgrounds).catch(() => {});
}
