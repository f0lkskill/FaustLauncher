/* ==============================================================================
 * js/ui/carousel.js — 3D 卡片轮播(快捷方式页 / 实用工具页)与丝滑拖拽
 * ------------------------------------------------------------------------------
 * 职责:
 *   · 快捷方式: 卡片构建、尺寸自适应、环状布局
 *   · 实用工具: 卡片构建、点击进入工具窗口
 *   · rAF + spring 弹性吸附拖拽, 以及盒子布局(窄窗口)切换
 * 本文件提供:
 *  函数: computeFeatSize / applyFeatSize / isBoxLayout / renderFeatures / layoutCarousel / bindFeaturesCarousel / openToolAction / renderTools / layoutToolsCarousel / bindToolsCarousel
 *  状态/常量: featTotal / featStep / TOOL_PENDING / toolsTotal / toolsData
 * 依赖: 依赖 bootstrap/state/utils/theme(rafThrottle)
 * 加载顺序: 13/22    (拆分自原 app.js 行 2058-2604)
 * ============================================================================== */
'use strict';

// ---------------- 快捷方式页(主页推荐卡) 与 实用工具页 ----
let featTotal = 0, featAngle = 0;
let featStep = 340;   // 卡片间距, 随主区宽度自适应

// 计算卡片尺寸: 中间卡完整 + 两侧卡自然露出 (卡宽 ≈ 主区宽/2.2, 间距 = 卡宽, 不重叠),
// 受高度上限约束 (等比例拉伸)
function computeFeatSize() {
  const main = document.getElementById('main');
  const W = Math.max(320, (main ? main.clientWidth : 720) - 60);
  const H = Math.max(360, window.innerHeight - 150);  // 留出 #main padding + 指示点
  let c = W / 2.2;
  const cMaxH = H * 3 / 4 * 0.92;                      // 高度约束: 卡高不超高
  if (c > cMaxH) c = cMaxH;
  c = Math.max(220, Math.min(c, 520));
  // 间距比卡宽大 12%, 卡片之间留出空隙, 不贴太近
  return { w: Math.round(c), h: Math.round(c * 4 / 3), step: Math.round(c * 1.12) };
}

function applyFeatSize() {
  const stage = $('#features-stage');
  if (!stage) return;
  const s = computeFeatSize();
  // 快捷方式与工具页共用同一卡片尺寸
  ['#features-stage', '#tools-stage'].forEach(sel => {
    const st = $(sel);
    if (st) {
      st.style.width = s.w + 'px';
      st.style.height = s.h + 'px';
      st.style.fontSize = (s.w / 7.5).toFixed(1) + 'px';  // 内容字号随卡片等比例缩放
    }
  });
  featStep = s.step;
  layoutCarousel(false);
  layoutToolsCarousel(false);
}

function isBoxLayout() {
  const s = BOOT && BOOT.settings_schema ? BOOT.settings_schema.page_layout : null;
  if (!s) return false;
  const v = s.value !== undefined ? s.value : s.default;
  return Number(v) === 1;   // 1 = 箱式布局
}

function renderFeatures(features) {
  const stage = $('#features-stage');
  if (!stage) return;
  const box = isBoxLayout();
  const carouselEl = $('#features-carousel');
  const gridEl = $('#features-grid');
  const dotsEl = $('#features-dots');
  if (carouselEl) carouselEl.hidden = box;
  if (dotsEl) dotsEl.hidden = box;
  const list = (features || []).filter(Boolean);
  featTotal = list.length;
  featAngle = 0;
  if (box) {
    // 箱式布局: 网格平铺, 点击打开
    if (gridEl) {
      gridEl.hidden = false;
      gridEl.innerHTML = '';
      list.forEach((f) => {
        const card = document.createElement('button');
        card.className = 'box-card';
        // 只认后端内嵌的 data URI: 相对路径在 pywebview 的 http 服务下必然 404 (坏图)
        const bg = f.image_uri || '';
        card.innerHTML =
          '<div class="box-card-bg">' + (bg ? '<img src="' + esc(bg) + '" alt="" draggable="false">' : '') + '</div>' +
          '<div class="box-card-body">' +
            '<div class="box-card-name">' + esc(f.name) + '</div>' +
            '<div class="box-card-desc">' + esc(f.desc || '') + '</div>' +
          '</div>';
        card.onclick = () => {
          if (api) api.open_feature(f.name).catch(e => toast(String(e), 'error'));
          else toast('浏览器预览模式', 'warn');
        };
        gridEl.appendChild(card);
      });
    }
    return;
  }
  stage.innerHTML = '';
  if (!featTotal) return;
  list.forEach((f, i) => {
    const wrap = document.createElement('div');
    wrap.className = 'carousel-item';
    const inner = document.createElement('div');
    inner.className = 'carousel-item-inner';
    const bg = f.image_uri || '';   // 同上: 不用相对路径, 拿不到就不放图
    const bgHtml = bg ? '<img class="carousel-item-bg" src="' + esc(bg) + '" alt="" draggable="false">' : '';
    inner.innerHTML = bgHtml +
      '<div class="carousel-item-content">' +
        '<div class="lc-ico">' + esc(f.name.split(' ')[0]) + '</div>' +
        '<div class="lc-name">' + esc(f.name.split(' ').slice(1).join(' ') || f.name) + '</div>' +
        '<div class="lc-desc">' + esc(f.desc || '') + '</div>' +
      '</div>';
    inner.dataset.featureName = f.name;   // 单击打开 (在轮播拖拽判定中触发)
    wrap.appendChild(inner);
    stage.appendChild(wrap);
  });
  // 底部指示点: 点击跳转到对应卡片
  const dotsWrap = document.getElementById('features-dots');
  if (dotsWrap) {
    dotsWrap.innerHTML = '';
    list.forEach((_, i) => {
      const dot = document.createElement('button');
      dot.className = 'cdot';
      dot.title = '跳到第 ' + (i + 1) + ' 个快捷方式';
      dot.addEventListener('click', () => {
        if (typeof window.__featGoTo === 'function') window.__featGoTo(i);
        else { featAngle = i; layoutCarousel(true); }
      });
      dotsWrap.appendChild(dot);
    });
  }
  applyFeatSize();
}

// CoverFlow 式循环轮播: 卡片沿弧线排列, 中间正面最大, 两侧倾斜有立体感但保持 1:1 不缩小,
// 无限循环; 支持 float offset 实现丝滑拖拽 (不再 Math.round 跳变)
function layoutCarousel(smooth) {
  const stage = $('#features-stage');
  if (!stage || !featTotal) return;
  const n = featTotal || 1;
  // 用浮点 offset, 拖拽时连续变化不跳变
  const offset = featAngle;
  const X = [0, featStep, featStep * 2]; // d=0,1,2 横向位置 (间距 = 卡宽, 三卡无缝填满)
  const S = [1, 1, 1];         // 缩放: 全部 1:1, 不缩小 (仅保留倾斜的立体感)
  const DEPTH = 80, ANGLE = 16; // 深度/角度: 保留 CoverFlow 立体层次与倾斜
  const OPACITY = [1, 0.9, 0.65]; // 远离中心的卡轻微渐隐, 层次过渡更柔和
  const cards = stage.querySelectorAll('.carousel-item');
  if (!cards.length) return;
  cards.forEach((card, i) => {
    let d = ((i - offset) % n + n) % n;
    if (d > n / 2) d = d - n;
    const prev = card._d;
    const jumped = prev !== undefined && Math.abs(d - prev) > n / 2;
    card._d = d;
    const ad = Math.abs(d);
    const idx = Math.min(Math.floor(ad), 2);   // 必须取整, 否则浮点索引取到 undefined
    const frac = ad - idx;
    const xBase = X[idx] ?? 0;
    const xNext = (X[idx + 1] ?? (xBase + featStep));
    const x = (d < 0 ? -1 : 1) * (xBase + (xNext - xBase) * frac);
    const scale = S[idx] ?? 1;
    const z = -ad * DEPTH;
    const rot = d * ANGLE;
    const opacity = OPACITY[idx] ?? 0.65;
    card.style.opacity = String(opacity);
    card.style.transition = (smooth && !jumped)
      ? 'transform .45s cubic-bezier(.22,.75,.28,1), opacity .45s ease'
      : 'none';
    card.style.transform = 'translate3d(' + (x || 0).toFixed(2) + 'px, 0, ' + (z || 0).toFixed(2) + 'px) rotateY(' + (rot || 0).toFixed(2) + 'deg) scale(' + scale.toFixed(4) + ')';
  });
  // 同步底部指示点: 当前居中的卡高亮
  const activeDot = ((Math.round(offset) % n) + n) % n;
  const dots = document.querySelectorAll('#features-dots .cdot');
  dots.forEach((d, i) => d.classList.toggle('active', i === activeDot));
}

function bindFeaturesCarousel() {
  const carousel = $('#features-carousel');
  if (!carousel) return;
  let featTarget = 0, animRAF = null;

  // 平滑滚动: 每次滚轮设目标=当前对齐位±1, rAF 缓动接近 (无惯性飞远/无卡顿)
  const animLoop = () => {
    const diff = featTarget - featAngle;
    featAngle += diff * 0.15;
    layoutCarousel(false);
    if (Math.abs(diff) < 0.01) {
      featAngle = featTarget;
      layoutCarousel(true);
      animRAF = null;
    } else {
      animRAF = carouselRAF(animLoop);
    }
  };
  const stopWheelAnim = () => {
    if (animRAF) { cancelAnimationFrame(animRAF); animRAF = null; }
  };

  // 指示点跳转: 停止滚轮动画后再设角度, 避免 animLoop 覆盖造成卡位
  window.__featGoTo = (i) => {
    stopAll();
    stopWheelAnim();
    featAngle = i;
    layoutCarousel(true);
  };

  carousel.addEventListener('wheel', (e) => {
    e.preventDefault();
    if (dragging) return;
    stopAll();
    featTarget = Math.round(featAngle) + (e.deltaY < 0 ? 1 : -1);
    if (!animRAF) animRAF = carouselRAF(animLoop);
  }, { passive: false });

  // ---- 丝滑拖拽: rAF 渲染 + spring 弹性吸附 ----
  let dragging = false, startX = 0, dragBase = 0;
  let moved = false, pressEl = null, pressName = null;
  let rafId = null, springId = null;

  const stopAll = () => {
    if (rafId) { cancelAnimationFrame(rafId); rafId = null; }
    if (springId) { cancelAnimationFrame(springId); springId = null; }
  };

  const clearPress = () => {
    if (pressEl) { pressEl.classList.remove('card-press'); pressEl = null; }
    pressName = null;
  };

  // 跟手阶段: rAF 持续渲染, featAngle 浮点跟随
  const startRenderLoop = () => {
    stopAll();
    const loop = () => {
      layoutCarousel(false);
      rafId = carouselRAF(loop);
    };
    rafId = carouselRAF(loop);
  };

  // 松手后: spring 弹性吸附到最近整数 (不抽动)
  const springToNearest = () => {
    stopAll();
    const target = Math.round(featAngle);
    const startVal = featAngle;
    const t0 = performance.now();
    const duration = 320; // ms
    const step = (now) => {
      const p = Math.min(1, (now - t0) / duration);
      // ease-out cubic: 平滑减速
      const ease = 1 - Math.pow(1 - p, 3);
      featAngle = startVal + (target - startVal) * ease;
      layoutCarousel(p < 0.98); // 接近结束时加回过渡
      if (p < 1) { springId = carouselRAF(step); }
      else { featAngle = target; layoutCarousel(true); }
    };
    springId = carouselRAF(step);
  };

  carousel.addEventListener('pointerdown', (e) => {
    dragging = true;
    moved = false;
    startX = e.clientX;
    dragBase = featAngle;
    stopWheelAnim();
    stopAll();
    startRenderLoop();
    // 按下反馈: 卡片缩小 + 高亮
    const hit = e.target.closest('.carousel-item-inner');
    if (hit) {
      pressEl = hit;
      pressName = hit.dataset.featureName || null;
      hit.classList.add('card-press');
    }
  });

  window.addEventListener('pointermove', (e) => {
    if (!dragging) return;
    const dx = e.clientX - startX;
    if (Math.abs(dx) > 6 && !moved) {
      moved = true;
      clearPress();   // 开始拖动, 取消按压缩放反馈
    }
    // 灵敏度: 拖 200px = 切 1 张; 方向取反 (向右拖 = 上一张, 向左拖 = 下一张)
    featAngle = dragBase - dx / 220;
  });
  window.addEventListener('pointerup', () => {
    if (!dragging) return;
    dragging = false;
    stopAll();
    // 未发生拖拽位移 -> 判定为单击, 打开对应快捷方式
    const clickName = pressName;   // 先保存, clearPress 会清空它
    if (!moved && clickName) {
      clearPress();
      if (api) api.open_feature(clickName).catch(e => toast(String(e), 'error'));
      else toast('浏览器预览模式', 'warn');
    } else {
      clearPress();
    }
    springToNearest();
  });
  window.addEventListener('pointercancel', () => {
    if (!dragging) return;
    dragging = false;
    clearPress();
    stopAll();
    springToNearest();
  });
}

const TOOL_PENDING = [];

// 工具点击分发 (供轮播单击判定调用)
function openToolAction(t) {
  const pending = TOOL_PENDING.includes(t.id);
  if (pending) { toast('该工具将在后续版本接入 Web UI', 'warn'); return; }
  if (t.page) { switchPage(t.page); return; }
  if (t.id === 'auto_translate') { openAutoTranslate(); return; }
  if (t.id === 'font') { openFontSelector(); return; }
  if (t.id === 'gradient') { openGradientTool(); return; }
  if (t.id === 'extension_tools') { openExtensionTools(); return; }
  if (api) api.open_tool(t.id).catch(e => toast(String(e), 'error'));
  else toast('浏览器预览模式', 'warn');
}

// 工具页: 与快捷方式完全一致的 3D 轮播展示
let toolsTotal = 0, toolsAngle = 0;
let toolsData = [];

function renderTools(tools) {
  const stage = $('#tools-stage');
  if (!stage) return;
  const box = isBoxLayout();
  const carouselEl = $('#tools-carousel');
  const gridEl = $('#tools-grid');
  const dotsEl = $('#tools-dots');
  if (carouselEl) carouselEl.hidden = box;
  if (dotsEl) dotsEl.hidden = box;
  const list = (tools || []).filter(Boolean);
  toolsTotal = list.length;
  toolsAngle = 0;
  toolsData = list;
  if (box) {
    // 箱式布局: 网格平铺, 点击打开工具
    if (gridEl) {
      gridEl.hidden = false;
      gridEl.innerHTML = '';
      list.forEach((t) => {
        const card = document.createElement('button');
        card.className = 'box-card';
        const bg = t.image_uri || '';   // 相对路径在 http 服务下 404, 只认内嵌 data URI
        card.innerHTML =
          '<div class="box-card-bg">' + (bg ? '<img src="' + esc(bg) + '" alt="" draggable="false">' : '') + '</div>' +
          '<div class="box-card-body">' +
            '<div class="box-card-name">' + esc(t.name) + '</div>' +
            '<div class="box-card-desc">' + esc(t.desc || '') + '</div>' +
          '</div>';
        card.onclick = () => openToolAction(t);
        gridEl.appendChild(card);
      });
    }
    return;
  }
  stage.innerHTML = '';
  if (!toolsTotal) return;
  list.forEach((t, i) => {
    const wrap = document.createElement('div');
    wrap.className = 'carousel-item';
    const inner = document.createElement('div');
    inner.className = 'carousel-item-inner';
    // 图片处理逻辑与快捷方式一致: 无图片则留空
    const bg = t.image_uri || '';   // 同上
    const bgHtml = bg ? '<img class="carousel-item-bg" src="' + esc(bg) + '" alt="" draggable="false">' : '';
    inner.innerHTML = bgHtml +
      '<div class="carousel-item-content">' +
        '<div class="lc-ico">' + esc(t.name.split(' ')[0]) + '</div>' +
        '<div class="lc-name">' + esc(t.name.split(' ').slice(1).join(' ') || t.name) + '</div>' +
        '<div class="lc-desc">' + esc(t.desc || '') + '</div>' +
      '</div>';
    inner.dataset.toolId = t.id;   // 单击打开 (在轮播拖拽判定中触发)
    wrap.appendChild(inner);
    stage.appendChild(wrap);
  });
  // 底部指示点: 点击跳转到对应卡片
  const dotsWrap = document.getElementById('tools-dots');
  if (dotsWrap) {
    dotsWrap.innerHTML = '';
    list.forEach((_, i) => {
      const dot = document.createElement('button');
      dot.className = 'cdot';
      dot.title = '跳到第 ' + (i + 1) + ' 个工具';
      dot.addEventListener('click', () => {
        if (typeof window.__toolsGoTo === 'function') window.__toolsGoTo(i);
        else { toolsAngle = i; layoutToolsCarousel(true); }
      });
      dotsWrap.appendChild(dot);
    });
  }
  applyFeatSize();
}

// 工具轮播布局: 与快捷方式完全一致 (间距/倾斜/渐隐)
function layoutToolsCarousel(smooth) {
  const stage = $('#tools-stage');
  if (!stage || !toolsTotal) return;
  const n = toolsTotal || 1;
  const offset = toolsAngle;
  const X = [0, featStep, featStep * 2];
  const S = [1, 1, 1];
  const DEPTH = 80, ANGLE = 16;
  const OPACITY = [1, 0.9, 0.65];
  const cards = stage.querySelectorAll('.carousel-item');
  if (!cards.length) return;
  cards.forEach((card, i) => {
    let d = ((i - offset) % n + n) % n;
    if (d > n / 2) d = d - n;
    const prev = card._d;
    const jumped = prev !== undefined && Math.abs(d - prev) > n / 2;
    card._d = d;
    const ad = Math.abs(d);
    const idx = Math.min(Math.floor(ad), 2);
    const frac = ad - idx;
    const xBase = X[idx] ?? 0;
    const xNext = (X[idx + 1] ?? (xBase + featStep));
    const x = (d < 0 ? -1 : 1) * (xBase + (xNext - xBase) * frac);
    const scale = S[idx] ?? 1;
    const z = -ad * DEPTH;
    const rot = d * ANGLE;
    const opacity = OPACITY[idx] ?? 0.65;
    card.style.opacity = String(opacity);
    card.style.transition = (smooth && !jumped)
      ? 'transform .45s cubic-bezier(.22,.75,.28,1), opacity .45s ease'
      : 'none';
    card.style.transform = 'translate3d(' + (x || 0).toFixed(2) + 'px, 0, ' + (z || 0).toFixed(2) + 'px) rotateY(' + (rot || 0).toFixed(2) + 'deg) scale(' + scale.toFixed(4) + ')';
  });
  const activeDot = ((Math.round(offset) % n) + n) % n;
  const dots = document.querySelectorAll('#tools-dots .cdot');
  dots.forEach((d, i) => d.classList.toggle('active', i === activeDot));
}

function bindToolsCarousel() {
  const carousel = $('#tools-carousel');
  if (!carousel) return;
  let toolsTarget = 0, animRAF = null;

  // 平滑滚动: 每次滚轮设目标=当前对齐位±1, rAF 缓动接近 (无惯性飞远/无卡顿)
  const animLoop = () => {
    const diff = toolsTarget - toolsAngle;
    toolsAngle += diff * 0.15;
    layoutToolsCarousel(false);
    if (Math.abs(diff) < 0.01) {
      toolsAngle = toolsTarget;
      layoutToolsCarousel(true);
      animRAF = null;
    } else {
      animRAF = carouselRAF(animLoop);
    }
  };
  const stopWheelAnim = () => {
    if (animRAF) { cancelAnimationFrame(animRAF); animRAF = null; }
  };

  // 指示点跳转: 停止滚轮动画后再设角度, 避免 animLoop 覆盖造成卡位
  window.__toolsGoTo = (i) => {
    stopAll();
    stopWheelAnim();
    toolsAngle = i;
    layoutToolsCarousel(true);
  };

  carousel.addEventListener('wheel', (e) => {
    e.preventDefault();
    if (dragging) return;
    stopAll();
    toolsTarget = Math.round(toolsAngle) + (e.deltaY < 0 ? 1 : -1);
    if (!animRAF) animRAF = carouselRAF(animLoop);
  }, { passive: false });

  let dragging = false, startX = 0, dragBase = 0;
  let moved = false, pressEl = null, pressId = null;
  let rafId = null, springId = null;

  const stopAll = () => {
    if (rafId) { cancelAnimationFrame(rafId); rafId = null; }
    if (springId) { cancelAnimationFrame(springId); springId = null; }
  };

  const clearPress = () => {
    if (pressEl) { pressEl.classList.remove('card-press'); pressEl = null; }
    pressId = null;
  };

  const startRenderLoop = () => {
    stopAll();
    const loop = () => {
      layoutToolsCarousel(false);
      rafId = carouselRAF(loop);
    };
    rafId = carouselRAF(loop);
  };

  const springToNearest = () => {
    stopAll();
    const target = Math.round(toolsAngle);
    const startVal = toolsAngle;
    const t0 = performance.now();
    const duration = 320;
    const step = (now) => {
      const p = Math.min(1, (now - t0) / duration);
      const ease = 1 - Math.pow(1 - p, 3);
      toolsAngle = startVal + (target - startVal) * ease;
      layoutToolsCarousel(p < 0.98);
      if (p < 1) { springId = carouselRAF(step); }
      else { toolsAngle = target; layoutToolsCarousel(true); }
    };
    springId = carouselRAF(step);
  };

  carousel.addEventListener('pointerdown', (e) => {
    dragging = true;
    moved = false;
    startX = e.clientX;
    dragBase = toolsAngle;
    stopWheelAnim();
    stopAll();
    startRenderLoop();
    const hit = e.target.closest('.carousel-item-inner');
    if (hit) {
      pressEl = hit;
      pressId = hit.dataset.toolId || null;
      hit.classList.add('card-press');
    }
  });

  window.addEventListener('pointermove', (e) => {
    if (!dragging) return;
    const dx = e.clientX - startX;
    if (Math.abs(dx) > 6 && !moved) {
      moved = true;
      clearPress();
    }
    toolsAngle = dragBase - dx / 220;
  });
  window.addEventListener('pointerup', () => {
    if (!dragging) return;
    dragging = false;
    stopAll();
    const clickId = pressId;   // 先保存, clearPress 会清空它
    if (!moved && clickId) {
      clearPress();
      const t = toolsData.find(x => x.id === clickId);
      if (t) openToolAction(t);
    } else {
      clearPress();
    }
    springToNearest();
  });
  window.addEventListener('pointercancel', () => {
    if (!dragging) return;
    dragging = false;
    clearPress();
    stopAll();
    springToNearest();
  });
}
