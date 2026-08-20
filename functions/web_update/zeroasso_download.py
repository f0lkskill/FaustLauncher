import os
import json
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

        # 创建配置文件 (lang 目录名跟随当前汉化包平台方)
        from functions.web_update.translation_source import get_translation_dir_name
        config_content = f"""{{
    "lang": "{get_translation_dir_name()}",
    "titleFont": "",
    "contextFont": "",
    "samplingPointSize": 78,
    "padding": 5
}}"""
        
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

def _find_refer_root() -> str:
    """为神人版查找基板包 (参考包): 优先游戏目录已有汉化, 其次 lang/ 下已有汉化"""
    from functions.web_update.translation_source import (
        get_translation_dir_name, get_translation_dir,
    )
    from functions.base.settings_manager import get_settings_manager as _gsm

    game_path = _gsm().get_setting('game_path')
    if game_path:
        candidate = os.path.join(game_path, 'LimbusCompany_Data', 'Lang', get_translation_dir_name())
        if os.path.isdir(candidate):
            return candidate
        # 游戏目录兜底: 任意标准结构汉化 (用户手动装的零协常在 LLC_zh-CN)
        for d in ("LLC_zh-CN", "OurPlayHanHua"):
            p = os.path.join(game_path, 'LimbusCompany_Data', 'Lang', d)
            if os.path.isdir(p):
                return p
    candidate = os.path.abspath(get_translation_dir())
    if os.path.isdir(candidate):
        return candidate
    # 兜底: 任意标准结构汉化包 (零协包最通用), 与当前平台目录名无关
    for d in ("LLC_zh-CN", "OurPlayHanHua"):
        p = os.path.abspath(os.path.join("lang", d))
        if os.path.isdir(p):
            return p
    return ""


def _ensure_refer_root(gui) -> str:
    """确保存在参考包 (标准结构汉化包, 用于 transfile 哈希文件重命名)

    无参考包时自动下载零协会汉化包作为参考 (用户无感), 成功返回参考包目录,
    失败返回空串。
    """
    refer = _find_refer_root()
    if refer:
        return refer

    gui.current_file_var.set("未找到参考汉化包, 自动下载零协会汉化包作为文件映射参考...")
    print("[OurPlay] 未找到参考包, 自动下载零协会汉化包作为文件映射参考...")
    temp_file = ""
    try:
        download_url = ""
        download_way = settings_manager.get_setting('translate_download_way')
        try:
            if download_way == 2:
                download_url, _name = get_github_release_url()
            elif download_way == 1:
                result = get_download_path_ByGhProxy()
                if result:
                    download_url, _v = result
            elif download_way == 0:
                result = get_download_path_ByLanzouyun()
                if result:
                    download_url, _v = result
        except Exception as e:
            print(f"获取零协会下载地址失败: {e}")
        if not download_url:
            gui.current_file_var.set("❌ 自动获取参考包失败: 无法获取零协会下载地址")
            return ""

        temp_file = os.path.join('lang', 'LimbusLocalize_latest.7z')
        os.makedirs('lang', exist_ok=True)
        if not download_file_with_gui(download_url, temp_file, gui, '零协会汉化包(参考)'):
            return ""
        if not verify_download(temp_file):
            return ""
        if not extract_7z_file(temp_file, 'lang'):
            return ""

        # 解压产物: lang/LimbusCompany_Data/Lang/LLC_zh-CN -> lang/LLC_zh-CN
        src = os.path.join('lang', 'LimbusCompany_Data', 'Lang', 'LLC_zh-CN')
        target = os.path.abspath(os.path.join('lang', 'LLC_zh-CN'))
        if not os.path.isdir(src):
            gui.current_file_var.set("❌ 自动获取参考包失败: 解压产物结构异常")
            return ""
        from functions.base.game_launcher import safe_merge_dirs
        if os.path.isdir(target):
            import shutil as _sh
            _sh.rmtree(target, ignore_errors=True)
        safe_merge_dirs(src, target)
        # 清理解压中间产物
        leftover = os.path.join('lang', 'LimbusCompany_Data')
        if os.path.exists(leftover):
            import shutil as _sh2
            _sh2.rmtree(leftover, ignore_errors=True)
        print(f"[OurPlay] 参考包就绪: {target}")
        return target
    except Exception as e:
        print(f"自动获取参考包失败: {e}")
        return ""
    finally:
        if temp_file and os.path.exists(temp_file):
            cleanup_temp_files(temp_file)


def _install_ourplay(gui, temp_file, game_path, version, is_god):
    """下载并安装 OurPlay 汉化包 (结构处理 + 落到 lang/<平台目录名>), 成功返回 True"""
    import json
    from functions.web_update.ourplay_download import prepare_ourplay_dir
    from functions.web_update.translation_source import get_translation_dir
    from functions.base.game_launcher import safe_merge_dirs
    import shutil as _shutil

    gui.current_file_var.set("正在处理汉化包结构...")
    ourplay_root = ""
    temp_extract = ""
    try:
        # OurPlay 两版本 (普通/神人) 均为 transfile 结构, 都需要参考包转换;
        # 参考包缺失时自动下载零协会汉化包作为参考
        refer_root = _ensure_refer_root(gui)
        if not refer_root:
            gui.current_file_var.set("❌ 汉化包处理失败: 参考包获取失败, 无法重命名哈希文件")
            print("❌ _install_ourplay: 参考包获取失败")
            return False
        ourplay_root, temp_extract = prepare_ourplay_dir(
            temp_file, refer_root=refer_root)
    except Exception as e:
        gui.current_file_var.set(f"❌ 汉化包处理失败: {e}")
        print(f"❌ _install_ourplay: 汉化包处理失败: {e}")
        return False

    try:
        target = get_translation_dir()
        if os.path.exists(target):
            _shutil.rmtree(target, ignore_errors=True)
        os.makedirs(target, exist_ok=True)
        safe_merge_dirs(ourplay_root, target)
        # 防御: 清理 Font 目录下的字体文件 (OurPlay 包不带字体, 不应混入其他汉化组字体)
        removed_fonts = 0
        for font_dir in ("Font", "Font/Context", "Font/Title"):
            font_path = os.path.join(target, font_dir)
            if os.path.isdir(font_path):
                for fname in os.listdir(font_path):
                    if fname.lower().endswith((".ttf", ".otf", ".ttc")):
                        try:
                            os.remove(os.path.join(font_path, fname))
                            removed_fonts += 1
                        except OSError:
                            pass
        if removed_fonts:
            print(f"[OurPlay] 已移除汉化包中混入的字体文件: {removed_fonts} 个")
        try:
            info_dir = os.path.join(target, 'info')
            os.makedirs(info_dir, exist_ok=True)
            with open(os.path.join(info_dir, 'version.json'), 'w', encoding='utf-8') as f:
                json.dump({"version": str(version),
                           "platform": "ourplay_god" if is_god else "ourplay_normal"},
                          f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"写入版本信息失败: {e}")
            gui.current_file_var.set("❌ 汉化包已安装但版本信息写入失败, 下次将重新下载")
            return False
        return True
    finally:
        if temp_extract:
            _shutil.rmtree(temp_extract, ignore_errors=True)


def download_and_extract_gui(gui:DownloadGUI, config_path: str = "", download_files = None, auto_close:bool = True) -> bool:
    """带GUI的下载和解压主函数 (按汉化包平台方分支)"""
    from functions.web_update.translation_source import (
        get_translate_source, is_ourplay_source, is_god_source,
        check_need_up_translate as need_up,
    )
    # 加载配置
    game_path = config_path
    
    if not game_path:
        gui.current_file_var.set("❌ 错误: 未配置游戏路径")
        return False
    
    # 检查路径是否存在
    if not os.path.exists(game_path):
        gui.current_file_var.set(f"❌ 错误: 路径不存在: {game_path}")
        return False

    source = get_translate_source()
    is_ourplay = is_ourplay_source()
    is_god = is_god_source()

    # 获取下载链接
    gui.current_file_var.set("正在链接浮务器...")
    download_url = ""
    timeout_counter = 0
    need_update_translate = True
    is_custom = False

    # 定义要下载的文件列表
    if download_files:
        is_custom = True
    elif is_ourplay:
        download_files = [
            {
                'name': 'OurPlay 汉化包',
                'url': '',  # URL将在后续代码中动态设置
                'temp_filename': 'ourplay_translation.zip'
            }
        ]
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

        # 检查字体文件是否已存在 (OurPlay 包自带字体, 无需额外下载)
        if not is_ourplay and os.path.exists("assets/Font/Context/ChineseFont.ttf") and \
           file_info['name'] == 'TTF 字体文件':
            print("字体文件已存在, 无需下载.")
            success_count += 1
            continue

        if is_ourplay:
            # ── OurPlay 平台 ──────────────────────────────
            if file_info['name'] == 'OurPlay 汉化包':
                try:
                    from functions.web_update.ourplay_download import get_ourplay_download_info
                    gui.current_file_var.set("正在获取 OurPlay 汉化包下载信息...")
                    info = get_ourplay_download_info(official=not is_god)
                    if not info:
                        gui.current_file_var.set("❌ 获取 OurPlay 下载信息失败")
                        return False
                    download_url, md5, size, version = info
                    file_info['url'] = download_url
                    print(f"获取到 OurPlay 下载链接, 版本号: {version}")
                    if not need_up(version):
                        print("当前已是最新汉化版本，无需更新。")
                        need_update_translate = False
                    else:
                        print("检测到新版本，准备更新...")
                except Exception as e:
                    print(f"获取 OurPlay 下载信息失败: {e}")
                    gui.current_file_var.set(f"❌ 获取 OurPlay 下载信息失败: {e}")
                    return False

            if not need_update_translate and file_info['name'] == 'OurPlay 汉化包':
                success_count += 1
                continue

            temp_file = os.path.join(temp_dir, file_info['temp_filename'])
            try:
                if not download_file_with_gui(file_info['url'], temp_file, gui, file_info['name']):
                    continue
                if not verify_download(temp_file):
                    continue
                if file_info['name'] == 'OurPlay 汉化包':
                    if _install_ourplay(gui, temp_file, game_path, version, is_god):
                        success_count += 1
                else:
                    # 自定义资源 (资源更新流 mod_loader/siner_skill_info 等), 直接解压
                    if not extract_7z_file(temp_file, game_path):
                        continue
                    success_count += 1
            except Exception as e:
                print(e)
            finally:
                cleanup_temp_files(temp_file)
        else:
            # ── 零协会平台 (原有逻辑) ─────────────────────
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
                            version = name
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

                # 写入本地版本信息 (修复: 零协会分支缺失, 导致 check_need_up_translate 永远判定旧版)
                try:
                    import json as _json
                    from functions.web_update.translation_source import get_translation_dir as _gtd
                    _vdir = os.path.join(_gtd(), 'info')
                    os.makedirs(_vdir, exist_ok=True)
                    with open(os.path.join(_vdir, 'version.json'), 'w', encoding='utf-8') as f:
                        _json.dump({"version": str(version), "platform": "zeroasso"},
                                   f, ensure_ascii=False, indent=2)
                    print(f"[零协会] 已写入本地版本信息: {version}")
                except Exception as e:
                    print(f"写入版本信息失败: {e}")
                
                
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

def download_and_extract_mod(gui, target_dir, download_files):
    """简化的下载+解压函数 (供下载中心 Mod/插件使用)

    解压到临时目录后识别压缩包内的插件/Mod 目录,
    移动到 target_dir/<下载名>/ 下 (对齐 scan_addons/scan_mods 的子目录约定)
    """
    import shutil
    import traceback as _tb
    temp_root = os.path.join(target_dir, '_temp_download')
    os.makedirs(temp_root, exist_ok=True)
    try:
        for file_info in download_files:
            if not gui.is_downloading:
                break
            url = file_info.get('url', '')
            name = file_info.get('name', 'unknown')
            temp_filename = file_info.get('temp_filename', f"{name}.7z")
            if not url:
                continue
            temp_file = os.path.join(temp_root, temp_filename)
            gui.current_file_var.set(f"正在下载 {name}...")
            print(f"[下载中心] 开始下载: {url}")
            ok = download_file_with_gui(url, temp_file, gui, name)
            print(f"[下载中心] 下载结果: ok={ok}, exists={os.path.exists(temp_file)}")
            if ok is False:
                return False
            gui.current_file_var.set(f"正在解压 {name}...")
            if os.path.exists(temp_file):
                extract_dir = os.path.join(temp_root, temp_filename + '_extract')
                os.makedirs(extract_dir, exist_ok=True)
                ex = extract_7z_file(temp_file, extract_dir)
                print(f"[下载中心] 解压结果: {ex}")
                if not os.path.isdir(extract_dir):
                    return False
                entries = [e for e in os.listdir(extract_dir)
                           if e not in ('__MACOSX', '.DS_Store')]
                junk = {'.gitkeep', 'readme.txt', 'README.md', '说明.txt', '下载说明.txt', '来源.txt'}
                real = [e for e in entries if e not in junk]
                dest_dir = os.path.join(target_dir, name)
                if os.path.exists(dest_dir):
                    shutil.rmtree(dest_dir, ignore_errors=True)
                if len(real) == 1 and os.path.isdir(os.path.join(extract_dir, real[0])):
                    # 压缩包根是一个目录: 视为插件/Mod 本体
                    shutil.copytree(os.path.join(extract_dir, real[0]), dest_dir)
                elif len(real) >= 1:
                    # 散落文件: 建目标名目录放入
                    os.makedirs(dest_dir, exist_ok=True)
                    for e in real:
                        src = os.path.join(extract_dir, e)
                        dst = os.path.join(dest_dir, e)
                        if os.path.isdir(src):
                            shutil.copytree(src, dst)
                        else:
                            shutil.move(src, dst)
                else:
                    return False
        return True
    except Exception as e:
        print(f"[下载中心] 下载/解压失败: {e}")
        _tb.print_exc()
        return False
    finally:
        try:
            shutil.rmtree(temp_root, ignore_errors=True)
        except Exception:
            pass