import os
import time
import requests
import subprocess
from functions.pages.download.download_gui import DownloadGUI
from functions.web_update.github_utils import GitHubReleaseFetcher
from functions.web_update.download_utils import check_need_up_translate
from functions.base.settings_manager import get_settings_manager
from functions.base.web_config import get_webnote

# 7-Zip可执行文件路径
SEVEN_ZIP_PATH = r"resources\7-zip\7z.exe"
settings_manager = get_settings_manager()


def get_github_release_url() -> tuple[str, str] | None:
    """从GitHub Release获取7z文件下载链接"""
    try:
        fetcher = GitHubReleaseFetcher(
            repo_owner="LocalizeLimbusCompany",
            repo_name="LocalizeLimbusCompany",
            use_proxy=True,
            proxy_url="https://gh-proxy.org/"
        )
        
        latest_release = fetcher.get_latest_release()
        if not latest_release:
            return None, None # type: ignore
            
        # 查找7z文件
        windows_assets = latest_release.get_assets_by_extension(".7z")
        for asset in windows_assets:
            if "LimbusLocalize" in asset.name:
                return asset.download_url, latest_release.name
                
        return None, None # type: ignore
    except Exception as e:
        print(f"获取GitHub Release失败: {e}")
        return None, None # type: ignore


# 保留原有的函数（用于命令行模式）
def download_file(url, local_filename):
    """下载文件并显示进度"""
    try:
        # 发送请求
        response = requests.get(url, stream=True)
        response.raise_for_status()
        
        # 获取文件大小
        total_size = int(response.headers.get('content-length', 0))
        block_size = 8192
        
        # 创建目录
        os.makedirs(os.path.dirname(local_filename), exist_ok=True)
        
        # 下载文件
        with open(local_filename, 'wb') as f:
            downloaded_size = 0
            for chunk in response.iter_content(chunk_size=block_size):
                if chunk:
                    f.write(chunk)
                    downloaded_size += len(chunk)
                    
                    # 显示下载进度
                    if total_size > 0:
                        percent = (downloaded_size / total_size) * 100
                        print(f"\r下载进度: {percent:.1f}% ({downloaded_size}/{total_size} bytes)", end='')
        
        print("\n下载完成!")
        return True
        
    except requests.exceptions.RequestException as e:
        print(f"下载失败: {e}")
        return False
    except Exception as e:
        print(f"下载过程中出现错误: {e}")
        return False

def extract_with_7zip(archive_path, extract_path):
    """使用系统7zip解压（直接使用本地7z.exe）"""
    try:
        # 检查7z.exe是否存在
        if not os.path.exists(SEVEN_ZIP_PATH):
            print(f"错误: 7-Zip可执行文件不存在: {SEVEN_ZIP_PATH}")
            return False
        
        print(f"使用本地7-Zip解压: {SEVEN_ZIP_PATH}")
        
        # 确保目标目录存在
        os.makedirs(extract_path, exist_ok=True)
        
        # 检查文件大小，确保下载完整
        file_size = os.path.getsize(archive_path)
        if file_size < 1000:  # 如果文件太小，可能下载不完整
            print(f"警告: 压缩文件可能不完整，大小: {file_size} bytes")
            return False
        
        # 使用7z.exe解压
        # 注意: 7z 在中文系统上输出 GBK 文本, 不能用 utf-8 硬解码(会导致
        # UnicodeDecodeError); 使用系统默认编码 + errors='replace' 兜底。
        result = subprocess.run([
            SEVEN_ZIP_PATH, 
            'x',           # 解压命令
            archive_path,   # 压缩文件路径
            f'-o{extract_path}',  # 输出目录
            '-y',          # 确认所有操作
            '-r'           # 递归处理子目录
        ], capture_output=True, text=True, errors='replace', creationflags=subprocess.CREATE_NO_WINDOW)
        
        if result.returncode == 0:
            print("7-Zip解压成功!")
            return True
        else:
            print(f"7-Zip解压失败，返回码: {result.returncode}")
            print(f"错误输出: {result.stderr}")
            return False
            
    except Exception as e:
        print(f"7-Zip解压失败: {e}")
        return False

def extract_with_zipfile_backup(archive_path, extract_path):
    """备用方案：使用Python内置zipfile"""
    import zipfile
    try:
        print("尝试使用zipfile作为备用方案...")
        
        # 检查是否为zip格式
        with zipfile.ZipFile(archive_path, 'r') as zip_ref:
            zip_ref.extractall(extract_path)
        print("zipfile解压成功!")
        return True
    except zipfile.BadZipFile:
        print("文件不是zip格式，无法使用zipfile解压")
        return False
    except Exception as e:
        print(f"zipfile解压失败: {e}")
        return False

def extract_7z_file(archive_path, extract_path):
    """解压7z文件（主函数）"""
    print(f"开始解压文件到: {extract_path}")
    
    # 检查文件是否存在
    if not os.path.exists(archive_path):
        print(f"错误: 压缩文件不存在: {archive_path}")
        return False
    
    # 优先使用本地7-Zip
    if extract_with_7zip(archive_path, extract_path):
        return True
    
    # 如果7-Zip失败，尝试使用zipfile作为备用方案
    print("7-Zip解压失败，尝试使用zipfile备用方案...")
    return extract_with_zipfile_backup(archive_path, extract_path)

def create_config_file(game_path):
    """创建配置文件"""
    try:
        config_path = os.path.join(game_path, 'LimbusCompany_Data', 'Lang', 'config.json')
        config_dir = os.path.dirname(config_path)
        
        # 确保目录存在
        os.makedirs(config_dir, exist_ok=True)
        
        # 创建配置文件
        config_content = """{
    "lang": "LLC_zh-CN",
    "titleFont": "",
    "contextFont": "",
    "samplingPointSize": 78,
    "padding": 5
}"""
        
        with open(config_path, 'w', encoding='utf-8') as f:
            f.write(config_content)
        
        print(f"配置文件已创建: {config_path}")
        return True
        
    except Exception as e:
        print(f"创建配置文件失败: {e}")
        return False

def cleanup_temp_files(temp_path):
    """清理临时文件"""
    try:
        if os.path.exists(temp_path):
            os.remove(temp_path)
            print("临时文件已清理")
    except Exception as e:
        print(f"清理临时文件失败: {e}")

def verify_download(file_path):
    """验证下载的文件是否完整"""
    try:
        file_size = os.path.getsize(file_path)
        if file_size < 1000:
            print(f"错误: 下载的文件太小，可能不完整: {file_size} bytes")
            return False
        
        # 检查文件是否可以正常打开（基本验证）
        with open(file_path, 'rb') as f:
            header = f.read(10)
            if len(header) < 10:
                print("错误: 文件头读取失败，文件可能损坏")
                return False
        
        print(f"文件验证通过，大小: {file_size} bytes")
        return True
    except Exception as e:
        print(f"文件验证失败: {e}")
        return False
    
def download_file_with_gui(url, local_filename, gui, file_name):
    """带GUI进度显示的下载文件函数"""
    try:
        # 更新GUI状态
        gui.current_file_var.set(f"{file_name}")
        
        # 发送请求
        response = requests.get(url, stream=True, verify=False)
        response.raise_for_status()
        
        # 获取文件大小
        total_size = int(response.headers.get('content-length', 0))
        if total_size == 0:
            # 如果无法获取文件大小，使用默认值
            total_size = 10 * 1024 * 1024  # 10MB作为默认值
        
        block_size = 8192
        
        # 创建目录
        os.makedirs(os.path.dirname(local_filename), exist_ok=True)
        
        # 开始时间
        start_time = time.time()
        downloaded_size = 0
        last_update_time = start_time
        last_downloaded_size = 0
        
        # 平滑进度条相关变量
        current_animated_percent = 0.0  # 当前动画显示的百分比
        target_percent = 0.0  # 目标百分比
        animation_speed = 0.15  # 动画速度系数，值越小越平滑
        last_animation_time = start_time
        
        # 下载文件
        with open(local_filename, 'wb') as f:
            for chunk in response.iter_content(chunk_size=block_size):
                if not gui.is_downloading:
                    return False
                    
                if chunk:
                    speed = 0
                    f.write(chunk)
                    downloaded_size += len(chunk)
                    
                    # 计算实时下载速度（每秒更新）
                    current_time = time.time()

                    elapsed_time = current_time - last_update_time
                    downloaded_since_last = downloaded_size - last_downloaded_size
                    
                    speed = downloaded_since_last / elapsed_time / 1024  # KB/s
                    
                    # 计算目标百分比
                    target_percent = (downloaded_size / total_size) * 100
                        
                    # 平滑渐变效果：持续向目标百分比移动
                    animation_elapsed = current_time - last_animation_time
                    if animation_elapsed > 0.1:  # 每0.1秒更新一次动画
                        if current_animated_percent < target_percent:
                            # 使用缓动函数实现平滑过渡
                            progress_diff = target_percent - current_animated_percent
                            current_animated_percent += progress_diff * animation_speed
                            
                            # 确保不超过目标值
                            if current_animated_percent > target_percent:
                                current_animated_percent = target_percent
                        
                        # 显示下载进度（使用平滑后的百分比）
                        gui.update_progress(current_animated_percent, downloaded_size, total_size, speed)
                        last_animation_time = current_time
                    
                    last_update_time = current_time
                    last_downloaded_size = downloaded_size
        
        # 下载完成后，平滑过渡到100%并停止震动
        final_animation_start = time.time()
        while current_animated_percent < 99.9:
            current_time = time.time()
            animation_elapsed = current_time - final_animation_start
            
            # 平滑过渡到100%
            if current_animated_percent < target_percent:
                progress_diff = target_percent - current_animated_percent
                current_animated_percent += progress_diff * animation_speed * 2  # 加速完成
            else:
                # 如果已经达到目标值，继续平滑到100%
                progress_diff = 100 - current_animated_percent
                current_animated_percent += progress_diff * animation_speed * 1.5
            
            if current_animated_percent > 99.9:
                current_animated_percent = 100
            
            gui.update_progress(current_animated_percent, downloaded_size, total_size, 0)
            time.sleep(0.01)  # 短暂延迟让动画更平滑
            
            # 防止无限循环
            if animation_elapsed > 2.0:  # 最多2秒完成动画
                current_animated_percent = 100
                break
        
        return True
        
    except requests.exceptions.RequestException as e:
        gui.current_file_var.set(f"❌ 下载失败: {e}")
        # print(e)
        return False
    except Exception as e:
        gui.current_file_var.set(f"❌ 下载过程中出现错误: {e}")
        # print(e)

def _fetch_download_path(note_name: str, pwd: str, get_path) -> tuple[str, str] | None:
    """从云端笔记获取汉化包下载地址"""
    from webFunc import Note
    from json import loads
    note = Note(note_name, pwd)
    note.fetch_note_info()

    # print("获取到笔记内容:", note.note_content)
    note = loads(note.note_content)
    path = get_path(note)
    version = note['llc_version']

    if path:
        print(f"成功获取到下载地址: {path}")
        return (path, version)
    print("未获取到下载地址,失败...")
    return None

def get_download_path_ByNote() -> tuple[str, str] | None:
    address, pwd = get_webnote('translation')
    return _fetch_download_path(address, pwd,
                                lambda n: n['llc_download_mirror']['seven']['direct'])

def get_download_path_ByGhProxy() -> tuple[str, str] | None:
    address, _ = get_webnote('translation')
    return _fetch_download_path(address, "",
                                lambda n: 'https://gh-proxy.org/' + n['llc_download_url']['seven'])

def get_download_path_ByLanzouyun() -> tuple[str, str] | None:
    address, _ = get_webnote('translation')
    return _fetch_download_path(address, "",
                                lambda n: n['lanzou_download_url']['seven'])

def download_and_extract_gui(gui:DownloadGUI, config_path: str = "", download_files = None, auto_close:bool = True) -> bool:
    """带GUI的下载和解压主函数"""
    # 加载配置
    game_path = config_path
    
    if not game_path:
        gui.current_file_var.set("❌ 错误: 未配置游戏路径")
        return False
    
    # 检查路径是否存在
    if not os.path.exists(game_path):
        gui.current_file_var.set(f"❌ 错误: 路径不存在: {game_path}")
        return False

    # 获取下载链接
    gui.current_file_var.set("正在链接浮务器...")
    download_url = ""
    timeout_counter = 0
    need_update_translate = True
    is_custom = False

    
    # 定义要下载的文件列表
    if download_files:
        is_custom = True
    else:
        download_files = [
            {
                'name': '零协会汉化包',
                'url': '',  # URL将在后续代码中动态设置
                'temp_filename': 'LimbusLocalize_latest.7z'
            },
            {
                'name': 'TTF 字体文件',
                'url': 'https://lz.qaiu.top/parser?url=https://folkskill.lanzoum.com/irAGt3iha71c&pwd=3z4n',
                'temp_filename': 'LLCCN-Font.7z'
            }
        ]
    
    # 临时文件路径
    temp_dir = 'lang/'
    os.makedirs(temp_dir, exist_ok=True)
    
    success_count = 0
    download_way = settings_manager.get_setting('translate_download_way')
    
    for file_info in download_files:
        if not gui.is_downloading:
            break

        # 检查字体文件是否已存在
        if os.path.exists("assets/Font/Context/ChineseFont.ttf") and \
           file_info['name'] == 'TTF 字体文件':
            print("字体文件已存在, 无需下载.")
            success_count += 1
            continue

        if file_info['name'] == '零协会汉化包':

            if download_way == 2:
                print("使用 GitHub Release 方式下载汉化文件...")

                while not download_url:
                    if timeout_counter >= 10:
                        gui.current_file_var.set("❌ 获取GitHub Release信息失败，已达最大重试次数")
                        return False
                    
                    download_url, name = get_github_release_url() # type: ignore

                    if not download_url:
                        timeout_counter += 1
                        gui.current_file_var.set(f"❌ 获取GitHub Release信息失败，准备重试...\n(剩余次数 {10 - timeout_counter})")
                        time.sleep(1)
                    else:
                        print (f"获取到下载链接: {download_url}\n 零协汉化版本号: {name}")
                        file_info['url'] = download_url
                        if not check_need_up_translate(name):
                            print("当前已是最新汉化版本，无需更新。")
                            need_update_translate = False
                        else:
                            print("检测到新版本，准备更新...")

            else:
                if download_way == 2:
                    print("使用 upfile 转存源下载")
                    result = get_download_path_ByNote()  
                elif download_way == 1:
                    print('使用 gh-proxy 代理加速下载')
                    result = get_download_path_ByGhProxy()
                elif download_way == 0:
                    print('使用 lanzouyun 转存源下载')
                    result = get_download_path_ByLanzouyun()

                if result: # type: ignore
                    download_url, version = result
                    print (f"获取到下载链接: {download_url}\n 零协汉化版本号: {version}")
                    file_info['url'] = download_url
                else:
                    gui.current_file_var.set("❌ 获取下载地址失败")
                    return False

                if not check_need_up_translate(version):
                    print("当前已是最新汉化版本，无需更新。")
                    need_update_translate = False
                else:
                    print("检测到新版本，准备更新...")

        if not need_update_translate and \
            file_info['name'] == '零协会汉化包':
            success_count += 1
            continue

        temp_file = os.path.join(temp_dir, file_info['temp_filename'])
        
        try:
            # 下载文件
            if not download_file_with_gui(file_info['url'], temp_file, gui, file_info['name']):
                continue
            
            # 验证下载的文件
            if not verify_download(temp_file):
                continue
            
            # 解压文件
            if not extract_7z_file(temp_file, game_path):
                continue
            
            success_count += 1
            
            
        except Exception as e:
            print(e)
        finally:
            cleanup_temp_files(temp_file)
            # print('cleanup temp files')
    
    if auto_close:
        gui.is_downloading = False
        gui.root.after(1000, gui.root.destroy)
    
    # 创建配置文件（只在至少一个文件处理成功时创建）
    if success_count > 0 and not is_custom:
        create_config_file(game_path)
        return True
    else:
        if success_count > 0:
            return True
        return False

def main_gui(parent, config_path: str = ""):
    """GUI入口点"""
    gui = DownloadGUI(parent, config_path, download_func=download_and_extract_gui)
    
    return gui