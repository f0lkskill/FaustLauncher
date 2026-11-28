"""web_tool 子模块：<launch_babel>（具体职责见函数文档）。"""


import subprocess

def launch_babel():
    """启动babel。"""
    try:
        subprocess.Popen(['start','resources/llc_babel/LLC_BABEL.exe'], shell=True)
        print("BABEL 工具已启动")
    except Exception as e:
        print(f"启动 BABEL 工具失败: {e}")
        
if __name__ == "__main__":
    launch_babel()
