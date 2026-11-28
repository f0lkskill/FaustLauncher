/* ==============================================================================
 * js/ui/mod_issue_modal.js — Mod 脚本素材校验失败汇总弹窗
 * ------------------------------------------------------------------------------
 * 职责:
 *   · 接收后端 window.__onModBatIssues 推送的跳过原因，按 Mod 汇总
 *   · 提示这些 Mod 可能已经失效，建议删除，并解释可能是游戏资源结构变化导致
 * 本文件提供:
 *  函数: showModIssueModal
 *  全局入口: window.__onModBatIssues（在 core/bridge.js 中挂上）
 * 依赖: bootstrap($/api) / utils(esc/icoText/closePanel)
 * 加载顺序: 14/23 (紧跟 notice_modal)
 * ============================================================================== */
'use strict';

/**
 * 显示“可能失效的 Mod”汇总模态，同一 Mod 的多次跳过会合并。
 * @param {Array<object>} issues 后端推送的 [{mod, bat, reason}, ...]
 */
function showModIssueModal(issues) {
  if (!Array.isArray(issues) || issues.length === 0) return;
  const existing = document.getElementById('mod-issue-modal');
  if (existing) { closePanel(existing); }

  const grouped = new Map();
  issues.forEach(function (item) {
    if (!item || !item.mod) return;
    const key = String(item.mod);
    if (!grouped.has(key)) grouped.set(key, []);
    grouped.get(key).push(String(item.reason || item.bat || '未知原因'));
  });
  if (!grouped.size) return;

  const names = Array.from(grouped.keys());
  const rows = names.map(function (name) {
    const reasons = grouped.get(name);
    return '<li class="mod-issue-item">' +
      '<span class="mod-issue-name">' + esc(name) + '</span>' +
      '<span class="mod-issue-reason">' + esc(reasons.slice(0, 2).join('；')) + '</span>' +
      '</li>';
  }).join('');

  document.body.classList.add('modal-open');
  const panel = document.createElement('div');
  panel.id = 'mod-issue-modal';
  panel.className = 'panel-overlay';
  panel.innerHTML =
    '<div class="panel-card">' +
      '<div class="panel-head">' +
        '<h3>' + icoText('caution', '部分 Mod 可能已失效') + '</h3>' +
        '<button class="panel-close" id="mod-issue-close" aria-label="关闭">' +
          '<svg class="ico" data-icon="close.svg" viewBox="0 0 48 48" fill="none" aria-hidden="true"></svg>' +
        '</button>' +
      '</div>' +
      '<div class="mod-issue-body">' +
        '<p class="mod-issue-lead">以下 ' + names.length + ' 个 Mod 的安装/卸载脚本因素材大小与游戏当前资源不符而被跳过，为避免覆盖错版素材，本次没有执行：</p>' +
        '<ul class="mod-issue-list">' + rows + '</ul>' +
        '<p class="mod-issue-note">建议删除这些 Mod 后重新启动游戏校验资源。游戏资源结构发生改变也会让 Mod 自然失效——这不代表启动器故障，旧版 Mod 需要等待作者适配新版本。</p>' +
      '</div>' +
      '<div class="res-detail-ops">' +
        '<button class="btn btn-primary" id="mod-issue-ok">知道了</button>' +
      '</div>' +
    '</div>';
  document.body.appendChild(panel);
  panel.addEventListener('click', function (e) { if (e.target === panel) closePanel(panel); });
  document.getElementById('mod-issue-close').onclick = function () { closePanel(panel); };
  document.getElementById('mod-issue-ok').onclick = function () { closePanel(panel); };
}
