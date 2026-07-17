"""
_summary_:
    启动 BABEL 工具
    Babel 是一个用于优化边狱巴士网络连接的工具
    Babel 通过选择最佳的 CloudFront IP 段来提高连接速度和稳定性
    此工具为零协会开发的开源项目，旨在为边狱公司玩家提供更好的网络体验
    遵循 MIT 协议引用本工具。
"""

import subprocess

def launch_babel():
    """
    启动 BABEL 工具
    """
    try:
        # 调用 babel.exe 并传递参数
        subprocess.Popen(['start','resources/llc_babel/LLC_BABEL.exe'], shell=True)
        print("BABEL 工具已启动")
    except Exception as e:
        print(f"启动 BABEL 工具失败: {e}")
        
if __name__ == "__main__":
    launch_babel()