# 构建FaustLauncher
import subprocess
from functions.base.settings_manager import get_settings_manager
from rich import print

settings_manager = get_settings_manager()
version_info = settings_manager.get_setting("version_info")

print("开始构建FaustLauncher...")

subprocess.call(["pyinstaller", "--noconfirm", "--onedir", "--windowed", "--name", "FaustLauncher", "--icon","E:\\projects\\python\\FaustLauncher\\assets\\images\\icon\\icon.ico", "E:\\projects\\python\\FaustLauncher\\main.py"])

print(f"准备将构建好的FaustLauncher复制到版本文件夹...")

import shutil
import os

try:
    print(f"尝试删除原有的版本文件夹：{f'build_{version_info}'}")
    os.rmdir(f'build_{version_info}')
    print(f"已删除原有的版本文件夹：{f'build_{version_info}'}")
except:
    pass

# 创建新的版本文件夹
print("创建版本文件夹...")
os.makedirs(f'build_{version_info}', exist_ok=True)

# 创建新的版本文件夹
print("准备前置环境...")
shutil.copytree('build_temp', f'build_{version_info}', dirs_exist_ok=True)

print("复制资产文件...")
shutil.copytree('assets', f'build_{version_info}\\assets', dirs_exist_ok=True)
print("重置字体文件...")
shutil.rmtree(f'build_{version_info}\\assets\\Font')
os.makedirs(f'build_{version_info}\\assets\\Font', exist_ok=True)

print('重置配置文件...')
settings_manager.reset_all_settings()
print("复制配置文件...")
shutil.copytree('config', f'build_{version_info}\\config', dirs_exist_ok=True)

print("复制资源文件...")
os.makedirs(f'build_{version_info}\\resources', exist_ok=True)
os.makedirs(f'build_{version_info}\\resources\\7-zip', exist_ok=True)
shutil.copytree('resources\\7-zip', f'build_{version_info}\\resources\\7-zip', dirs_exist_ok=True)

# 复制许可证和md文件
print("复制许可证和md文件...")
shutil.copy('LICENSE', f'build_{version_info}\\LICENSE')
shutil.copy('README.md', f'build_{version_info}\\README.md')

# 复制可执行文件到新文件夹
shutil.copy("dist\\FaustLauncher\\FaustLauncher.exe", f'build_{version_info}\\FaustLauncher.exe')

print(f"FaustLauncher已构建完成，版本信息：{version_info}")

# 打开文件夹
print("打开版本文件夹...")
os.system(f"start {f'build_{version_info}'}")
os.system('pause')