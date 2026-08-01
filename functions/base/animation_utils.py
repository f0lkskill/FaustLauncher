import tkinter as tk


def smooth_scroll(self, canvas, delta, anim_state):
    """在指定 canvas 上触发一次平滑滚动"""
    # Windows 下 delta = ±120 的倍数
    unit = int(delta / 120) if abs(delta) >= 120 else (1 if delta > 0 else -1)

    state = anim_state
    if state is None:
        # 退化到瞬时滚动
        canvas.yview_scroll(-unit * 5, "units")
        return

    # 取消正在运行的动画
    if state['anim_id'] is not None:
        try:
            canvas.after_cancel(state['anim_id'])
        except Exception:
            pass
        state['anim_id'] = None

    # 当前起点（以 yview 分数为准）
    try:
        current_frac = float(canvas.yview()[0])
    except (tk.TclError, Exception):
        current_frac = 0.0
    state['current'] = current_frac
    state['start'] = current_frac

    # 计算目标：每次滚动大约窗口高度的 18%（明显更灵敏）
    try:
        region = canvas.cget('scrollregion')
        if region:
            parts = list(map(int, region.split()))
            region_h = parts[3] - parts[1]
        else:
            region_h = 0
    except (tk.TclError, ValueError):
        region_h = 0
        
    win_h = max(canvas.winfo_height(), 1)
    # 每格滚动窗口高度的 ~18%
    px_per_unit = max(win_h * 0.18, 36)
    delta_px = (-unit) * px_per_unit * max(abs(delta) / 120, 1)

    if region_h > win_h:
        delta_frac = delta_px / (region_h - win_h)
    else:
        delta_frac = 0.0

    state['target'] = max(0.0, min(1.0, current_frac + delta_frac))
    state['step'] = 0
    # 动画总时长 ~ 120ms，足够顺滑但不拖沓
    state['steps'] = 10

    self._animate_scroll_step(canvas)