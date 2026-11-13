/* ==============================================================================
 * js/ui/tilt.js — 主页 3D 鼠标聚焦倾斜(其它页面不再跟随)
 * ------------------------------------------------------------------------------
 * 职责:
 *   · applyTiltBase / applyTiltFrame / applyTilt  —— 仅主页常驻倾角并跟随鼠标
 *   · addCardTilt                                —— 空实现(资源卡片不再 3D 跟随)
 *   · resetTilt                                  —— 清掉所有内联倾斜(打开模态/切页时用)
 *   · watchModalPanels                           —— 监听 .panel-overlay, 打开时压平倾斜
 * 本文件提供:
 *  函数: applyTiltBase / applyTiltFrame / applyTilt / addCardTilt / resetTilt / watchModalPanels
 *  状态/常量: TILT_SEL / TILT_ALL_SEL / tiltRAF / tiltMX / tiltMY
 * 依赖: 无
 * 加载顺序: 10/22    (拆分自原 app.js 行 3242-3287 + 913-928)
 * ============================================================================== */
'use strict';

// ---------------- 3D 鼠标聚焦倾斜 (只在主页启用) ----------------
const TILT_SEL = '.card, .link-card, .dc-card, .hero, .chip, .dc-tab';
// resetTilt 还要清掉旧版可能留在资源卡片上的内联 transform
const TILT_ALL_SEL = TILT_SEL + ', .res-card';
let tiltRAF = null;
let tiltMX = 0;
let tiltMY = 0;

// 一键清掉所有内联倾斜: 打开模态面板 / 切换页面时调用。
// 这些 transform 是 JS 写进 style 的内联样式, 不主动清就会一直留在元素上,
// 面板盖上去后指针不再悬停卡片, 倾斜却还挂着, 看起来就是"东西歪了"。
function resetTilt() {
  document.querySelectorAll(TILT_ALL_SEL).forEach(el => {
    if (el.style.transform) el.style.transform = '';
  });
}
function applyTiltBase() {
  document.querySelectorAll(TILT_SEL).forEach(el => {
    // 主页控件保留基准倾角; 其他页面控件还原无变形
    el.style.transform = el.closest('#page-home')
      ? 'perspective(900px) rotateX(2deg) rotateY(-1deg)'
      : '';
  });
}
function applyTiltFrame() {
  tiltRAF = null;
  const mx = tiltMX;
  const my = tiltMY;
  document.querySelectorAll(TILT_SEL).forEach(el => {
    const r = el.getBoundingClientRect();
    if (!r.width) return;
    if (!el.closest('#page-home')) {
      if (el.style.transform) el.style.transform = '';
      return;
    }
    const hovered = el.matches(':hover');
    const x = Math.max(-1, Math.min(1, (mx - (r.left + r.width / 2)) / (r.width / 2)));
    const y = Math.max(-1, Math.min(1, (my - (r.top + r.height / 2)) / (r.height / 2)));
    const s = hovered ? ' scale(1.02)' : '';
    el.style.transform = 'perspective(900px) rotateY(' + (x * 3.5).toFixed(2) + 'deg) rotateX(' +
      (-y * 3.5 + 2).toFixed(2) + 'deg)' + s;
  });
}
function applyTilt() {
  applyTiltBase();
  watchModalPanels();
  document.addEventListener('mousemove', (e) => {
    tiltMX = e.clientX;
    tiltMY = e.clientY;
    // tilt 是轻量 transform (卡片无 blur), 保持满帧跟随
    if (!tiltRAF) tiltRAF = requestAnimationFrame(applyTiltFrame);
  });
  document.addEventListener('mouseleave', () => {
    applyTiltBase();
  });
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
