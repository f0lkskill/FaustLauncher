/* ==============================================================================
 * js/ui/theme.js — 主题与性能设置(外观侧)
 * ------------------------------------------------------------------------------
 * 职责:
 *   · 背景透明度(玻璃系数) / 硬件加速 / 帧率上限
 *   · 主题色推导: applyTheme + shadeColor + hexA
 *   · rAF 节流工具 rafThrottle / carouselRAF(供轮播与拖拽复用)
 * 本文件提供:
 *  函数: applyGlassFactor / applyHwAccel / applyFrameLimit / rafThrottle / applyTheme / shadeColor / hexA
 *  状态/常量: frameLimit / __lastRafT / carouselRAF
 * 依赖: 依赖 bootstrap; 由设置页的即时生效逻辑调用
 * 加载顺序: 6/22    (拆分自原 app.js 行 1989-2057)
 * ============================================================================== */
'use strict';

// ---- 外观与性能开关(改动后立即生效) ----
function applyGlassFactor() {
  let v = 1;
  try {
    const s = BOOT && BOOT.settings_schema ? BOOT.settings_schema.glass_factor : null;
    if (s) v = Number(s.value !== undefined ? s.value : s.default) || 1;
  } catch (e) { v = 1; }
  document.documentElement.style.setProperty('--glass-factor', String(v));
}

// 启用毛玻璃开关: 关闭时给 body 加 no-hw, 禁用 backdrop-filter 等毛玻璃高消耗效果
function applyHwAccel() {
  let v = true;
  try {
    const s = BOOT && BOOT.settings_schema ? BOOT.settings_schema.glass_enabled : null;
    if (s) v = Boolean(s.value !== undefined ? s.value : s.default);
  } catch (e) { v = true; }
  document.body.classList.toggle('no-hw', !v);
}

// 帧渲染上限: 限制 JS 动画 rAF 帧率, 减少毛玻璃卡片等每帧重绘的 GPU 开销
let frameLimit = 60;
let __lastRafT = 0;
function applyFrameLimit() {
  let idx = 2;
  try {
    const s = BOOT && BOOT.settings_schema ? BOOT.settings_schema.frame_limit : null;
    if (s) idx = Number(s.value !== undefined ? s.value : s.default) || 2;
  } catch (e) { idx = 2; }
  const fpsList = [30, 45, 60, 90, 120];
  frameLimit = fpsList[idx] || 60;
}
function rafThrottle(cb) {
  if (frameLimit >= 120) return requestAnimationFrame(cb);
  const interval = 1000 / frameLimit;
  const loop = (t) => {
    if (t - __lastRafT >= interval) { __lastRafT = t; cb(t); }
    else requestAnimationFrame(loop);
  };
  return requestAnimationFrame(loop);
}

// 轮播交互保持原生刷新频率，不受设置中的全局帧率上限影响。
const carouselRAF = (cb) => requestAnimationFrame(cb);

function applyTheme(color) {
  if (!color) return;
  color = String(color);
  if (/^#[0-9a-fA-F]{6}$/.test(color)) {
    // 主题色只调整窗口底色, 高亮色固定为 vscode 蓝 (避免黑底覆盖 accent)
    document.documentElement.style.setProperty('--bg', color);
    document.documentElement.style.setProperty('--bg-tint', color);
  }
}

function shadeColor(hex, pct) {
  const n = parseInt(hex.slice(1), 16);
  let r = (n >> 16) & 255, g = (n >> 8) & 255, bl = n & 255;
  r = Math.max(0, Math.min(255, Math.round(r + r * pct / 100)));
  g = Math.max(0, Math.min(255, Math.round(g + g * pct / 100)));
  bl = Math.max(0, Math.min(255, Math.round(bl + bl * pct / 100)));
  return '#' + ((r << 16) | (g << 8) | bl).toString(16).padStart(6, '0');
}

function hexA(hex, a) {
  const n = parseInt(hex.slice(1), 16);
  const r = (n >> 16) & 255, g = (n >> 8) & 255, bl = n & 255;
  return 'rgba(' + r + ',' + g + ',' + bl + ',' + a + ')';
}
