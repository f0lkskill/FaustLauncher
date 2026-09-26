/* ==============================================================================
 * js/ui/tilt.js — 3D 鼠标聚焦倾斜(主页全局跟随, 其它页面仅悬浮)
 * ------------------------------------------------------------------------------
 * 职责:
 *   · applyTiltBase / applyTiltFrame / applyTilt  —— 全局跟随(主页常驻倾角, 其它页面仅悬浮)
 *   · addCardTilt                                —— 卡片级跟随(资源卡片/下载中心卡片共用)
 * 本文件提供:
 *  函数: applyTiltBase / applyTiltFrame / applyTilt / addCardTilt
 *  状态/常量: TILT_SEL / tiltRAF / tiltMX / tiltMY
 * 依赖: 无
 * 加载顺序: 10/22    (拆分自原 app.js 行 3242-3287 + 913-928)
 * ============================================================================== */
'use strict';

// ---------------- 3D 鼠标聚焦倾斜 (主页全局跟随, 其他页面仅悬浮) ----------------
const TILT_SEL = '.card, .link-card, .dc-card, .hero, .chip, .dc-tab';
let tiltRAF = null;
let tiltMX = 0;
let tiltMY = 0;
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
    const inHome = !!el.closest('#page-home');
    const hovered = el.matches(':hover');
    if (!inHome && !hovered) {
      if (el.style.transform) el.style.transform = '';
      return;
    }
    const x = Math.max(-1, Math.min(1, (mx - (r.left + r.width / 2)) / (r.width / 2)));
    const y = Math.max(-1, Math.min(1, (my - (r.top + r.height / 2)) / (r.height / 2)));
    const s = hovered ? ' scale(1.02)' : '';
    el.style.transform = 'perspective(900px) rotateY(' + (x * 3.5).toFixed(2) + 'deg) rotateX(' +
      (-y * 3.5 + (inHome ? 2 : 0)).toFixed(2) + 'deg)' + s;
  });
}
function applyTilt() {
  applyTiltBase();
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

// ---------------- 卡片级 3D 跟随(资源卡片 / 下载中心卡片共用) ----------------
// 卡片 3D 跟随鼠标: 容器级事件委托 (避免卡片边缘因 transform 导致的抽搐闪烁)
function addCardTilt(card) {
  card.addEventListener('mousemove', (e) => {
    const r = card.getBoundingClientRect();
    const px = Math.max(-0.5, Math.min(0.5, (e.clientX - r.left) / r.width - 0.5));
    const py = Math.max(-0.5, Math.min(0.5, (e.clientY - r.top) / r.height - 0.5));
    // 角度减半 + 死区收缩, 边缘不会把指针"甩出"卡片造成闪烁
    card.style.transform = 'perspective(600px) rotateY(' + (px * 7).toFixed(2) +
      'deg) rotateX(' + (-py * 6).toFixed(2) + 'deg)';
  });
  card.addEventListener('mouseleave', () => {
    card.style.transform = '';   // 瞬间复位, 避免平滑过渡造成"3d聚焦后恢复"的视觉
  });
  card.addEventListener('mouseenter', () => { card.style.transition = 'none'; });
}
