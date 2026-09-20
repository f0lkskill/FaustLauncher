/* ==============================================================================
 * js/ui/background.js — 背景图层
 * ------------------------------------------------------------------------------
 * 职责:
 *   · applyBackgrounds / refreshBackgrounds: 应用后端下发的背景图列表与轮换
 * 本文件提供:
 *  函数: applyBackgrounds / refreshBackgrounds
 *  状态/常量: _bgInterval
 * 依赖: 依赖 bootstrap(api), state(BOOT)
 * 加载顺序: 11/22    (拆分自原 app.js 行 3288-3327)
 * ============================================================================== */
'use strict';

// ---------------- 背景 ----------------
let _bgInterval = null;

function applyBackgrounds(uris) {
  if (!uris || !uris.length) return;
  if (_bgInterval) { clearInterval(_bgInterval); _bgInterval = null; }
  const layer = $('#bg-layer');
  if (!layer) return;
  let idx = Math.floor(Math.random() * uris.length);
  let bgSlot = 'a';
  const show = (u) => {
    const im = new Image();
    im.onload = () => {
      const nextSlot = bgSlot === 'a' ? 'b' : 'a';
      layer.style.setProperty('--bg-image-' + nextSlot, 'url("' + u.replace(/"/g, '\\"') + '")');
      layer.classList.add('show-img');
      void layer.offsetWidth;
      layer.classList.add('bg-' + nextSlot);
      const oldSlot = bgSlot;
      setTimeout(() => layer.classList.remove('bg-' + oldSlot), 1150);
      bgSlot = nextSlot;
    };
    im.src = u;
  };
  show(uris[idx]);
  if (uris.length > 1) {
    _bgInterval = setInterval(() => {
      let n;
      do { n = Math.floor(Math.random() * uris.length); } while (n === idx);
      idx = n;
      show(uris[idx]);
    }, 25000);
  }
}

// 模糊度等背景相关设置变更后立即重新拉取背景
function refreshBackgrounds() {
  if (api) withTimeout(api.get_backgrounds(), 6000, []).then(applyBackgrounds).catch(() => {});
}
