/* ==============================================================================
 * js/ui/frame_loading.js — 卡片加载转圈动画(frame-spinner)控制
 * ------------------------------------------------------------------------------
 * 职责:
 *   · 内联样式控制 spinner 显隐(不依赖 CSS 规则), 隐藏时先淡出再 display:none
 * 本文件提供:
 *  函数: setFrameLoading / showFrameLoading / hideFrameLoading
 * 依赖: 无
 * 加载顺序: 8/22    (拆分自原 app.js 行 377-397)
 * ============================================================================== */
'use strict';

// ---------------- Frame 加载转圈动画 ----------------
// 用内联样式直接控制 spinner 显示/隐藏, 不依赖 CSS 规则 (.card.loading .frame-spinner)
// 隐藏时先淡出 (opacity 过渡), 再 display:none, 让蒙版平滑消失
function setFrameLoading(frame, on) {
  if (!frame) return;
  frame.classList.toggle('loading', on);
  const sp = frame.querySelector('.frame-spinner');
  if (!sp) return;
  if (sp._fadeTimer) { clearTimeout(sp._fadeTimer); sp._fadeTimer = null; }
  if (on) {
    sp.style.display = 'flex';
    void sp.offsetWidth;   // 强制 reflow, 确保 opacity 过渡生效
    sp.style.opacity = '1';
  } else {
    sp.style.opacity = '0';
    sp._fadeTimer = setTimeout(() => { sp.style.display = 'none'; sp._fadeTimer = null; }, 420);
  }
}
function showFrameLoading(frame) { setFrameLoading(frame, true); }
function hideFrameLoading(frame) { setFrameLoading(frame, false); }
