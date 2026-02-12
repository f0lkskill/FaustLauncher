import pystray

def check_and_run_aalc():
    import os
    import subprocess

    print("正在启动 AALC...")
    try:
        # 批处理文件中指定的工作目录
        work_dir = r"addons\AALC-auto\AALC"
        
        # 检查工作目录是否存在
        if not os.path.exists(work_dir):
            print(f"错误：工作目录不存在 - {work_dir}")
            return
        
        # 尝试不同的文件名形式
        possible_exe_names = ["run.bat"]
        
        for exe_name in possible_exe_names:
            exe_path = os.path.join(work_dir, exe_name)
            
            if os.path.exists(exe_path):
                # 尝试运行
                try:
                    result = subprocess.run(
                        [exe_path],  # 使用绝对路径
                        capture_output=True,
                        text=True,
                        timeout=60
                    )
                except Exception as e:
                    print(f"AALC运行失败：{e}")
                    continue
            else:
                print(f"AALC不存在：{exe_path}")
            
    except Exception as e:
        print(f"AALC发生错误：{e}")

self = ADDON_ARG['AddonManager']
func_menu = pystray.Menu(pystray.MenuItem('测试', check_and_run_aalc))

self.menu_items.append(pystray.MenuItem(ADDON_ARG['AddonName'], action=func_menu))

self.gamestart_funcs.append(check_and_run_aalc)