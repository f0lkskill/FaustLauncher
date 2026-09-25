/* ==============================================================================
 * js/ui/character.js — 角色小人(随机边缘探头摇摆)与问候语气泡
 * ------------------------------------------------------------------------------
 * 职责:
 *   · 初始化/排期/位姿动画/气泡弹出与坠落/碰撞检测/点击交互
 *   · 配置读取自后端 character_greetings 等数据
 * 本文件提供:
 *  函数: initCharacter / charFallbackItem / charRange / randInRange / scheduleCharacter / randomCharPos / applyCharPose / playCharAnim / startCharSpeech / showCharBubble / hideCharBubble / clearCharTimers / onCharClick / retractCharIfBottom / posCollides / characterCycle
 *  状态/常量: charImages / charGreetings / _charGreetingsReady / charEl / CHAR_EDGES / CHAR_COLLIDE_SEL
 * 依赖: 依赖 bootstrap(api), utils
 * 加载顺序: 12/22    (拆分自原 app.js 行 3328-3572)
 * ============================================================================== */
'use strict';

// ---------------- 角色小人 (随机边缘探头摇摆) ----------------
let charImages = [];
let charGreetings = {};
let _charGreetingsReady = false;
let charEl = null, charImgEl = null;
const CHAR_EDGES = ['right', 'bottom', 'top'];

// ---- 初始化: 读取后端配置(间隔 / 位置范围 / 问候语) ----
function initCharacter() {
  charEl = document.getElementById('character');
  if (!charEl) return;
  charImgEl = document.getElementById('character-img');
  charEl.addEventListener('click', onCharClick);
  // 图片与问候语都就绪后立即显示一次 (不等冷却)
  const tryStart = () => {
    if (charImages.length && _charGreetingsReady) characterCycle();
  };
  if (api) {
    withTimeout(api.get_characters(), 6000, []).then(list => {
      charImages = (list && list.length) ? list : [charFallbackItem()];
      tryStart();
    }).catch(() => { charImages = [charFallbackItem()]; tryStart(); });
    withTimeout(api.get_character_greetings(), 6000, {}).then(map => {
      charGreetings = map || {};
      _charGreetingsReady = true;
      tryStart();
    }).catch(() => { charGreetings = {}; _charGreetingsReady = true; tryStart(); });
  } else {
    charImages = [charFallbackItem()];
    charGreetings = {};
    _charGreetingsReady = true;
    characterCycle();
  }
}

function charFallbackItem() {
  // 不再用文件路径兜底: pywebview 用本地 http 服务加载页面 (root = html/app/),
  // '../../assets/...' 必然 404 -> 坏图。后端 get_characters 拿不到图时干脆不显示角色小人。
  return { name: '', uri: '' };
}

// 角色间隔范围设置 [min,max] (可在设置页调整)
function charRange(key, dmin, dmax) {
  const s = BOOT && BOOT.settings_schema ? BOOT.settings_schema[key] : null;
  let v = s ? s.value : null;
  if (!Array.isArray(v) || v.length < 2) v = (s && Array.isArray(s.default)) ? s.default : [dmin, dmax];
  const a = Number(v[0]) || dmin, b = Number(v[1]) || dmax;
  return [Math.min(a, b), Math.max(a, b)];
}
function randInRange(r) { return (r[0] || 0) + Math.random() * ((r[1] || r[0] || 0) - (r[0] || 0)); }

// ---- 排期与位姿: 随机边缘、随机位置、隐藏角落 ----
function scheduleCharacter() {
  const r = charRange('char_appear_interval', 10, 30);
  setTimeout(characterCycle, randInRange(r) * 1000);   // 缩回后在范围内随机再次出现
}

// 在边缘上随机像素位置 (比率 15%~85%), 并据此计算初始倾斜角度
function randomCharPos(edge) {
  const ratio = 15 + Math.random() * 70;           // 沿边缘的随机位置 (15%~85%)
  const base = ((ratio - 50) / 50) * 10;           // 位置越偏边, 倾角越大 (±10°)
  const jitter = Math.random() * 6 - 3;            // 额外 ±3° 抖动
  const pos = { ratio: ratio.toFixed(1), angle: (base + jitter).toFixed(1) };
  if (edge === 'right') {
    // 角色为半身像 (无腿): 底部藏在屏幕下缘之外, 仅露出上半身
    pos.bottom = '-' + (40 + Math.random() * 40).toFixed(0) + 'px';
  }
  return pos;
}

function applyCharPose(edge, pos, hidden, noAnim) {
  const s = charEl.style;
  s.transition = noAnim ? 'none' : 'transform .75s cubic-bezier(.2,.8,.3,1)';
  s.left = 'auto'; s.right = 'auto'; s.top = 'auto'; s.bottom = 'auto';
  if (edge === 'right') {
    // 底部藏在屏幕外 (无腿), 仅水平镜像面向左, 探头露出约 75% 宽
    s.bottom = pos.bottom || '-50px';
    s.right = '0';
    s.transform = 'translate(' + (hidden ? '110%' : '25%') + ', 0) scaleX(-1)';
  } else if (edge === 'bottom') {
    s.left = pos.ratio + '%'; s.bottom = '0';
    s.transform = 'translate(-50%, ' + (hidden ? '110%' : '28%') + ') rotate(' + pos.angle + 'deg)';
  } else { // top
    // 顶部探头: 垂直翻转 (scaleY -1), 露出的是头部而非腿部
    s.left = pos.ratio + '%'; s.top = 'var(--titlebar-h)';
    s.transform = 'translate(-50%, ' + (hidden ? '-110%' : '-28%') + ') rotate(' + pos.angle + 'deg) scaleY(-1)';
  }
}

// 随机播放一次角色动效 (摇摆/弹跳/震动/缩放弹入/左右探头)
function playCharAnim() {
  const CHAR_ANIMS = ['char-wiggle', 'char-bounce', 'char-shake', 'char-pop', 'char-nod'];
  const animClass = CHAR_ANIMS[Math.floor(Math.random() * CHAR_ANIMS.length)];
  charImgEl.classList.remove('char-wiggle', 'char-bounce', 'char-shake', 'char-pop', 'char-nod');
  void charImgEl.offsetWidth;
  charImgEl.classList.add(animClass);
  if (charEl._animTimer) { clearTimeout(charEl._animTimer); charEl._animTimer = null; }
  charEl._animTimer = setTimeout(() => charImgEl.classList.remove(animClass), 1400);
}

// 探头期间循环展示问候语: 每隔几秒换一条新文本, 每次配合角色动效
function startCharSpeech(edge, pos, greetings) {
  if (!greetings || !greetings.length) return;
  let lastIdx = -1;
  const next = () => {
    let idx = Math.floor(Math.random() * greetings.length);
    if (greetings.length > 1 && idx === lastIdx) idx = (idx + 1) % greetings.length;
    lastIdx = idx;
    playCharAnim();
    showCharBubble(edge, pos, greetings[idx]);
    if (charEl._speechTimer) { clearTimeout(charEl._speechTimer); charEl._speechTimer = null; }
    const sr = charRange('char_speech_interval', 10, 15);
    charEl._speechTimer = setTimeout(next, randInRange(sr) * 1000);   // 范围内随机换一条
  };
  next();
}

// 角色问候语气泡: 弹入 -> 停留 -> 旋转坠落, 紧贴角色实际矩形, 箭头指向角色
function showCharBubble(edge, pos, text) {
  const b = document.getElementById('char-bubble');
  if (!b || !text) return;
  hideCharBubble();
  b.style.display = '';
  b.style.setProperty('--bx', '0');
  b.style.setProperty('--by', '0');
  b.textContent = text;
  b.style.left = 'auto'; b.style.right = 'auto'; b.style.top = 'auto'; b.style.bottom = 'auto';
  const centered = (edge === 'bottom' || edge === 'top');   // 顶/底边缘气泡水平居中
  b.classList.add(edge === 'right' ? 'b-right' : edge === 'bottom' ? 'b-bottom' : 'b-top');
  // 用角色实际变换后的矩形定位, 保证气泡紧贴角色
  const cr = charEl.getBoundingClientRect();
  const vw = window.innerWidth, vh = window.innerHeight;
  if (edge === 'right') {
    // 角色在右下角: 气泡紧贴角色左侧, 垂直与角色中部对齐
    b.style.right = (vw - cr.left + 14) + 'px';
    b.style.top = (cr.top + cr.height / 2) + 'px';
    b.style.setProperty('--by', '-50%');
  } else if (edge === 'bottom') {
    // 角色在底部: 气泡在角色正上方居中
    b.style.left = (cr.left + cr.width / 2) + 'px';
    b.style.bottom = (vh - cr.top + 14) + 'px';
  } else { // top
    // 角色在顶部: 气泡在角色正下方居中
    b.style.left = (cr.left + cr.width / 2) + 'px';
    b.style.top = Math.max(40, cr.bottom + 14) + 'px';
  }
  charEl._bubbleCentered = centered;
  b.classList.add(centered ? 'char-bubble-in-c' : 'char-bubble-in');
  charEl._bubbleFallTimer = setTimeout(() => {
    b.classList.remove('char-bubble-in', 'char-bubble-in-c');
    b.classList.add(centered ? 'char-bubble-fall-c' : 'char-bubble-fall');
    charEl._bubbleGoneTimer = setTimeout(hideCharBubble, 950);
  }, 3500);
}

function hideCharBubble() {
  const b = document.getElementById('char-bubble');
  if (!b) return;
  if (charEl._bubbleFallTimer) { clearTimeout(charEl._bubbleFallTimer); charEl._bubbleFallTimer = null; }
  if (charEl._bubbleGoneTimer) { clearTimeout(charEl._bubbleGoneTimer); charEl._bubbleGoneTimer = null; }
  b.className = '';
  b.style.display = 'none';
}

function clearCharTimers() {
  if (charEl._wiggleTimer) { clearTimeout(charEl._wiggleTimer); charEl._wiggleTimer = null; }
  if (charEl._stayTimer) { clearTimeout(charEl._stayTimer); charEl._stayTimer = null; }
  if (charEl._speechTimer) { clearTimeout(charEl._speechTimer); charEl._speechTimer = null; }
  if (charEl._animTimer) { clearTimeout(charEl._animTimer); charEl._animTimer = null; }
  if (charImgEl) charImgEl.classList.remove('char-wiggle', 'char-bounce', 'char-shake', 'char-pop', 'char-nod');
  hideCharBubble();
}

// 点击立即缩回, 再次出现间隔同 scheduleCharacter (40s~120s)
function onCharClick() {
  if (!charEl || charEl._edge == null) return;
  clearCharTimers();
  applyCharPose(charEl._edge, charEl._pos, true);
  setTimeout(scheduleCharacter, 800);   // 等收回动画完成
}

// 终端拉起时强制底部角色缩回 (底部会被终端遮挡)
function retractCharIfBottom() {
  if (!charEl || charEl._edge !== 'bottom') return;
  clearCharTimers();
  const pos = charEl._pos;
  applyCharPose('bottom', pos, true);
  charEl._edge = null;
  setTimeout(scheduleCharacter, 800);
}

// 角色需要避让的关键交互元素 (尽量覆盖全部可点击控件)
const CHAR_COLLIDE_SEL = 'button, a, input, select, textarea, [role="button"], .btn, .nav-item, .link-card, .dc-card, .mod-card, .set-row, .cdot, .chip, .term-head, .term-toggle, .dl-fab, .status-chips, .hero-actions, .dc-tab, .stat-label, .set-control';

// 探测: 该边缘+位置是否与关键交互元素重叠 (临时放到可见位测 rect, 带膨胀边距)
function posCollides(edge, pos) {
  if (!charEl) return false;
  applyCharPose(edge, pos, false, true);
  const r = charEl.getBoundingClientRect();
  const PAD = 8;   // 与关键元素保持间距, 视觉上不贴住
  const rr = { left: r.left - PAD, right: r.right + PAD, top: r.top - PAD, bottom: r.bottom + PAD };
  const els = document.querySelectorAll(CHAR_COLLIDE_SEL);
  for (let i = 0; i < els.length; i++) {
    const t = els[i];
    if (!t || t === charEl || t.contains(charEl) || charEl.contains(t)) continue;
    const tr = t.getBoundingClientRect();
    if (tr.width === 0 || tr.height === 0) continue;
    if (rr.right > tr.left && rr.left < tr.right && rr.bottom > tr.top && rr.top < tr.bottom) {
      return true;
    }
  }
  return false;
}

function characterCycle() {
  const usable = (charImages || []).filter(x => x && x.uri);   // 没图的条目直接跳过
  if (!charEl || !usable.length) { scheduleCharacter(); return; }
  // 终端展开时避开底部边缘 (底部被终端占用)
  const termEl = document.getElementById('terminal');
  const termOpen = termEl ? termEl.classList.contains('open') : false;
  const availEdges = termOpen ? CHAR_EDGES.filter(e => e !== 'bottom') : CHAR_EDGES;
  // 多次尝试找一个不遮挡关键交互元素的位置 (最多 12 次)
  let edge, pos;
  for (let attempt = 0; attempt < 12; attempt++) {
    edge = availEdges[Math.floor(Math.random() * availEdges.length)];
    pos = randomCharPos(edge);
    if (!posCollides(edge, pos)) break;
  }
  charEl._edge = edge;
  charEl._pos = pos;
  // 随机选图片, 并按图片名取问候语表 (循环展示)
  const item = usable[Math.floor(Math.random() * usable.length)];
  charImgEl.src = item.uri;
  const greetings = charGreetings[item.name] || [];
  clearCharTimers();
  // 先无动画重置到新边缘的隐藏位, 下一帧再探头滑入
  applyCharPose(edge, pos, true, true);
  requestAnimationFrame(() => requestAnimationFrame(() => applyCharPose(edge, pos, false)));
  // 滑入完成后启动循环问候语 (每几秒换一条, 每次配合角色动效)
  charEl._wiggleTimer = setTimeout(() => {
    startCharSpeech(edge, pos, greetings);
  }, 800);
  // 停留设定时间 (范围内随机) 后收回, 然后进入下一轮
  charEl._stayTimer = setTimeout(() => {
    clearCharTimers();   // 停止文本循环与动效, 避免缩回后仍在展示
    applyCharPose(edge, pos, true);
    scheduleCharacter();
  }, randInRange(charRange('char_stay_interval', 40, 60)) * 1000);
}
