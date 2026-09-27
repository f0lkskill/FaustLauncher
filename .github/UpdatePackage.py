import requests
import os
import json
from datetime import datetime, timedelta
from pathlib import Path
import sys

project_root = Path(os.path.dirname(__file__)).parent
print(project_root)
sys.path.append(project_root.as_posix())

from functions.webFunc import *
from LanzouUpload import LanzouUploader

# 笔记地址直接硬编码 (web_config.json 已 gitignore 不上传仓库, workflow 不依赖该文件;
# 环境变量 ADDRESS 可覆盖, 未设置时使用默认汉化源笔记地址)
DEFAULT_NOTE_ADDRESS = "FaustLauncher"
ADDRESS = (os.environ.get('ADDRESS', '') or '').strip() or DEFAULT_NOTE_ADDRESS


def get_llc():
    """
    从 LLC 获取汉化包信息
    """
    
    try:
        GithubDownloader = GitHubReleaseFetcher(
            False,
            ignore_ssl=True
        )
        last_ver = GithubDownloader.get_latest_release("LocalizeLimbusCompany", "LocalizeLimbusCompany")
        return last_ver.tag_name, last_ver # type: ignore

    except Exception as e:
        print(f"获取 LLC 版本失败: {e}")
        return None, None


def should_check_llc(last_update_time):
    """判断 LLC 是否需要检查更新 —— 总是检查。

    原规则是"本周已更新过则只在中午 12 点请求一次", 但 workflow 的 cron 用的是
    UTC (0 12 * * * = 北京时间 20:00), 定时触发时 now.hour 永远不等于 12:
    于是本周只要更新过一次, 之后所有运行都会跳过 LLC 检查, 新版本再也更新不到
    (表现为"汉化明明更新了, action 却直接跳过")。

    检查本身只是一次 GitHub API 调用; 真正要不要下载/上传由
    new_llc_version != current_llc_version 把关, 不需要再用时间窗省这一步。
    """
    return True

def should_check_mirror(last_update_time):
    """
    判断LLC镜像是否需要更新
    规则：如果距离上一次更新超过2.5天，则需要更新
    """
    now = datetime.now()
    if now - last_update_time >= timedelta(days=2, hours=12):
        return True
    return False

def main():
    if not ADDRESS:
        print("错误: 未设置 ADDRESS 环境变量")
        exit(1)
    
    print(f"开始检查，ADDRESS: {ADDRESS}")
    
    note_ = Note(id_name="FaustLauncher", address=ADDRESS, pwd="AutoTranslate")
    note_.fetch_note_info()

    # 云端笔记读不出内容时分两种情况, 必须区别对待:
    #   · 笔记存在但没有内容 (HTTP 200 但内容为空) —— 笔记被清空就是这种:
    #     旧代码把它当成"获取失败"直接 return, 于是 Action 一直是绿的,
    #     汉化源笔记也一直是空的, 新版本永远更新不到;
    #   · 线路/HTTP 故障 —— 这时若也按"首次运行"继续, 会把全部版本状态重置,
    #     导致每轮都误判"有新版本"并重复下载/上传, 所以直接报错退出让 Action 变红。
    if not getattr(note_, "has_get", False):
        if getattr(note_, "empty_note", False):
            print("云端笔记内容为空 (笔记存在但没有内容) —— 按首次运行初始化, 稍后会写回版本状态")
        else:
            reason = getattr(note_, "last_fetch_error", "") or "未知原因"
            print(f"错误: 云端笔记获取失败 ({reason})，本次检查中止")
            print("提示: 属于线路/HTTP 故障, 不能按首次运行继续 (否则每轮都会重复下载上传)")
            exit(1)

    raw_content = (note_.note_content or "").strip()
    if raw_content:
        try:
            current_data = json.loads(raw_content)
            if not isinstance(current_data, dict):
                raise ValueError("笔记内容不是 JSON 对象")
        except (json.JSONDecodeError, ValueError) as e:
            print(f"笔记内容无法解析为 JSON ({e})，按首次运行初始化")
            current_data = {}
    else:
        print("笔记内容为空，按首次运行初始化")
        current_data = {}

    # 清理历史遗留的 OurPlay 字段 (OurPlay 更新流程已移除, 笔记里还留着旧键)
    for _legacy_key in ('ourplay_version', 'ourplay_download_url', 'ourplay_last_update_time'):
        current_data.pop(_legacy_key, None)

    # 逐字段安全读取 (缺失单个键不能触发"首次运行"重置):
    # 旧写法 current_data['llc_version'] 会抛 KeyError 被当成首次运行,
    # 从而把已知的 LLC 版本一并清空, 造成每轮都重复下载/上传/更新笔记。
    current_llc_version = current_data.get('llc_version')

    def _parse_time(key):
        """安全解析笔记中的时间戳, 缺失或非法时回退到 1970 (视为从未更新)"""
        try:
            return datetime.fromisoformat(current_data.get(key) or '1970-01-01T00:00:00')
        except (ValueError, TypeError):
            return datetime.fromisoformat('1970-01-01T00:00:00')

    llc_last_update = _parse_time('llc_last_update_time')
    llc_mirror_update = _parse_time('llc_mirror_update_time')
    
    # 判断是否需要检查LLC
    should_check_llc_flag = should_check_llc(llc_last_update)
    # 判断是否需要检查LLC镜像
    should_check_llc_mirror_flag = should_check_mirror(llc_mirror_update)
    
    if not should_check_llc_flag and not should_check_llc_mirror_flag:
        print("LLC 与镜像本轮都无需检查，跳过")
        return
    
    # 获取最新版本
    new_llc_version = None
    last_ver = None
    
    if should_check_llc_flag or should_check_llc_mirror_flag:
        print("检查LLC更新...")
        new_llc_version, last_ver = get_llc() # type: ignore
        if new_llc_version is None:
            print("获取LLC版本失败，使用当前版本")
            new_llc_version = current_llc_version
    else:
        print("跳过LLC检查")
        new_llc_version = current_llc_version
    
    if new_llc_version is None:
        print("获取版本信息失败，退出")
        exit(1)
    
    # 检查是否需要更新
    need_update_llc = (should_check_llc_flag and new_llc_version != current_llc_version)
    
    if not need_update_llc and not should_check_llc_mirror_flag:
        print("版本无变化")
        return
    
    if need_update_llc or should_check_llc_mirror_flag:
        # 需要 LLC 更新或刷新镜像时, 必须先拿到 release 资源列表; 获取失败则跳过 (避免 None 崩溃)
        if last_ver is None:
            print("LLC release 信息获取失败，跳过 LLC/镜像更新")
            return
        if need_update_llc:print(f"LLC版本更新: {current_llc_version} -> {new_llc_version}")

        seven_zip_asset = last_ver.get_assets_by_extension(".7z")[0] # type: ignore
        zip_asset = last_ver.get_assets_by_extension(".zip")[0] # type: ignore
        new_llc_download_url = {'zip':zip_asset.download_url, 
                                'seven':seven_zip_asset.download_url}
        
        with open(zip_asset.name, "wb") as f:
            r = requests.get(zip_asset.download_url, verify=False) # 关闭SSL验证
            f.write(r.content)
            
        with open(seven_zip_asset.name, "wb") as f:
            r = requests.get(seven_zip_asset.download_url, verify=False) # 关闭SSL验证
            f.write(r.content)
        
        file_transfer = UpFileClient()
        llc_upload_result = file_transfer.upload(zip_asset.name)
        llc_seven_upload_result = file_transfer.upload(seven_zip_asset.name)
        
        if not llc_upload_result.get('success') or not llc_seven_upload_result.get('success'):
            print("LLC文件上传失败，取消更新")
            return
        
        new_llc_mirror = {
            'zip': {'direct': llc_upload_result.get('direct_download_url'),
                    'web': llc_upload_result.get('download_url')},
            'seven': {'direct': llc_seven_upload_result.get('direct_download_url'),
                      'web': llc_seven_upload_result.get('download_url')}
        }
        current_data['llc_download_url'] = new_llc_download_url
        current_data['llc_download_mirror'] = new_llc_mirror
        current_data['llc_version'] = new_llc_version
        if need_update_llc:current_data['llc_last_update_time'] = datetime.now().isoformat()
        current_data['llc_mirror_update_time'] = datetime.now().isoformat()

        # 上传到蓝奏云 LLC_lang 文件夹，并记录 lz.qaiu.top 解析链接（失败不阻断主流程）
        lanzou_uploader = LanzouUploader()
        if lanzou_uploader.login():
            llc_lz_result = lanzou_uploader.upload(zip_asset.name)
            llc_seven_lz_result = lanzou_uploader.upload(seven_zip_asset.name)
            if llc_lz_result.get('success') and llc_seven_lz_result.get('success'):
                current_data['lanzou_download_url'] = {
                    'zip': llc_lz_result.get('parse_url'),
                    'seven': llc_seven_lz_result.get('parse_url')
                }
                print(f"蓝奏云上传成功: {current_data['lanzou_download_url']}")
            else:
                print(f"蓝奏云上传失败: zip={llc_lz_result.get('error')}, "
                      f"seven={llc_seven_lz_result.get('error')}，跳过蓝奏云镜像")
        else:
            print("蓝奏云登录失败，跳过蓝奏云镜像")
        
    # 提交更新
    note_.update_note_content(json.dumps(current_data, ensure_ascii=False, indent=4))

    print("更新完成")


if __name__ == "__main__":
    main()