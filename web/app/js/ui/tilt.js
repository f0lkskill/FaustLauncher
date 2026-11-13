/* ==============================================================================
 * js/ui/tilt.js — 3D 聚焦已舍弃, 保留同名空实现兼容旧调用
 * ------------------------------------------------------------------------------
 * 职责:
 *   · applyTiltBase / applyTiltFrame / applyTilt  —— 不再跟随鼠标倾斜
 *   · addCardTilt                                —— 空实现, 卡片不再 3D 跟随
 *   · resetTilt                                  —— 清掉历史内联倾斜
 *   · watchModalPanels                           —— 监听 .panel-overlay 维护 modal-open
 * ============================================================================== */
'use strict';

// 清掉历史内联倾斜: 旧版本可能在元素 style 上留下 perspective/rotate。
const TILT_ALL_SEL = '.card, .link-card, .dc-card, .hero, .chip, .dc-tab, .res-card';

function resetTilt() {
  document.querySelectorAll(TILT_ALL_SEL).forEach(el => {
    if (el.style.transform) el.style.transform = '';
  });
}
function applyTiltBase() { resetTilt(); }
function applyTiltFrame() {}
function applyTilt() {
  applyTiltBase();
  watchModalPanels();
}

// ---------------- 模态面板: 打开即压平倾斜 ----------------
// 面板都是各功能自己 document.createElement('div.panel-overlay') 后塞进 body 的,
// 没有统一的打开函数, 所以这里用 MutationObserver 统一兜底:
//   · 出现 .panel-overlay → body 加 modal-open (CSS 里 !important 压平) + 清内联倾斜;
//   · 最后一个面板移除 → 去掉 modal-open。
// 这样任何现在/以后新增的确认框、详情框都不会再带着卡片/面板的 3D 残余。
function watchModalPanels() {
  let queued = false;
  const sync = () => {
    queued = false;
    const open = !!document.querySelector('.panel-overlay:not(.closing)');
    document.body.classList.toggle('modal-open', open);
    if (open) resetTilt();
  };
  const isPanel = (n) => n && n.nodeType === 1 &&
    (n.classList.contains('panel-overlay') ||
     (n.querySelector && !!n.querySelector('.panel-overlay')));
  new MutationObserver((muts) => {
    let hit = false;
    for (const m of muts) {
      for (const n of m.addedNodes) { if (isPanel(n)) { hit = true; break; } }
      if (!hit) {
        for (const n of m.removedNodes) {
          if (n && n.nodeType === 1 && n.classList &&
              n.classList.contains('panel-overlay')) { hit = true; break; }
        }
      }
      if (hit) break;
    }
    if (!hit || queued) return;
    queued = true;
    requestAnimationFrame(sync);
  }).observe(document.body, { childList: true, subtree: true });
}

// 点击瞬间就压平: 卡片里的按钮被点时会立刻弹面板, 依赖 observer 需要等一帧,
// 先在这里同步清一次, 避免"点击的那一下卡片还歪着"。
document.addEventListener('click', (e) => {
  const t = e.target;
  if (!t || !t.closest) return;
  // 只处理卡片内部的操作控件(按钮/菜单), 不影响普通文字选择
  if (t.closest('.res-card .btn, .res-card .res-menu-btn, .dc-card .btn, .btn-danger')) {
    resetTilt();
  }
}, true);

// ---------------- 卡片级 3D 跟随(已舍弃) ----------------
function addCardTilt() {}
