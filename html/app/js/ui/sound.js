/* ==============================================================================
 * js/ui/sound.js — 音效(浏览器内核播放, 不走后端)
 * ------------------------------------------------------------------------------
 * 职责:
 *   · 欢迎音效 / 点击音效的预加载与播放(含 autoplay 被拒后的首次交互补播)
 *   · 全局点击音效绑定(节流, 排除终端/气泡/提示条/遮罩)
 * 本文件提供:
 *  函数: preloadSounds / tryWelcome / playUISound / playWelcomeSound / bindClickSound
 *  状态/常量: _soundUris / _welcomePending / _uiTransitionDone / _welcomePlayed
 * 依赖: 依赖 bootstrap(api), state(设置项 click_sound)
 * 加载顺序: 7/22    (拆分自原 app.js 行 314-376)
 * ============================================================================== */
'use strict';

// ---------------- 音效 (浏览器内核播放) ----------------
const _soundUris = { welcome: '', click: '' };
let _welcomePending = false;
let _uiTransitionDone = false;
let _welcomePlayed = false;

function preloadSounds() {
  if (!api) return;
  withTimeout(api.get_sound('welcome'), 6000, '').then(u => {
    _soundUris.welcome = u;
    if (u && _uiTransitionDone) playWelcomeSound();
  }).catch(() => {});
  withTimeout(api.get_sound('click'), 6000, '').then(u => { _soundUris.click = u; }).catch(() => {});
}

function tryWelcome() {
  if (!_soundUris.welcome || !_welcomePending || _welcomePlayed) return;
  try {
    const a = new Audio(_soundUris.welcome);
    a.volume = 0.8;
    const p = a.play();
    if (p && p.then) p.then(() => { _welcomePending = false; _welcomePlayed = true; }).catch(() => {});
    else { _welcomePending = false; _welcomePlayed = true; }
  } catch (e) {}
}

function playUISound(kind) {
  if (kind === 'click' && BOOT && BOOT.settings_schema && !getSettingValue('click_sound')) return;
  const uri = _soundUris[kind];
  if (!uri) return;
  try {
    const a = new Audio(uri);
    a.volume = 0.8;
    a.play().catch(() => {});
  } catch (e) {}
}

function playWelcomeSound() {
  if (_welcomePlayed) return;
  _uiTransitionDone = true;
  _welcomePending = true;
  if (!_soundUris.welcome) return;
  tryWelcome();
}

// 全局点击音效 (覆盖几乎所有交互控件; 节流; 排除打字/滚动/气泡/通知/遮罩)
function bindClickSound() {
  let last = 0;
  document.addEventListener('click', (e) => {
    const t = e.target;
    if (!t || !t.closest) return;
    if (t === document.body || t === document.documentElement) return;
    // autoplay 被拒时: 用户首次交互后补播欢迎音效
    if (_welcomePending) { tryWelcome(); return; }
    const now = Date.now();
    if (now - last < 40) return;
    if (t.classList && t.classList.contains('panel-overlay')) return;   // 遮罩本身
    if (t.closest('#term-body, #char-bubble, .toast')) return;
    last = now;
    playUISound('click');
  });
}
