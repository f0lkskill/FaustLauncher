"""零协会 (LocalizeLimbusCompany) 汉化包搬运脚本。

由 .github/workflows/check.yml 定时调用, 只做一件事:
  1. 读云端笔记里的当前版本状态;
  2. 比对零协会最新 release —— 有新版本, 或镜像该刷新了, 就下载它的 .zip / .7z;
  3. 传到两个镜像 (UpFileClient / 蓝奏云), 连同版本号写回笔记;
  4. 都没变化时直接返回, 不碰笔记也不上传。

笔记字段是启动器下载汉化的唯一来源 (读取方: functions/web_update/zeroasso_download.py):
  llc_version / llc_download_url / llc_download_mirror / lanzou_download_url
"""
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import requests

project_root = Path(os.path.dirname(__file__)).parent
sys.path.append(project_root.as_posix())

from functions.webFunc import *
from LanzouUpload import LanzouUploader

# 笔记地址直接硬编码 (web_config.json 已 gitignore 不上传仓库, workflow 不依赖该文件;
# 环境变量 ADDRESS 可覆盖, 未设置时使用默认汉化源笔记地址)
DEFAULT_NOTE_ADDRESS = "FaustLauncher"
ADDRESS = (os.environ.get('ADDRESS', '') or '').strip() or DEFAULT_NOTE_ADDRESS

GITHUB_OWNER = "LocalizeLimbusCompany"
GITHUB_REPO = "LocalizeLimbusCompany"
# 镜像链接会被上游清理, 超过这个天数就重传一次 (与版本是否变化无关)
MIRROR_REFRESH = timedelta(days=2, hours=12)


def _load_note_json(note_):
    """笔记内容 -> dict; 为空或损坏时按首次运行返回 {}"""
    raw = (note_.note_content or "").strip()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            return data
        print("笔记内容不是 JSON 对象，按首次运行处理")
    except json.JSONDecodeError as e:
        print(f"笔记内容无法解析为 JSON ({e})，按首次运行处理")
    return {}


def _parse_time(data, key):
    """读笔记里的时间戳; 缺失或非法时回退到 1970 (视为从未更新)"""
    try:
        return datetime.fromisoformat(data.get(key) or '1970-01-01T00:00:00')
    except (ValueError, TypeError):
        return datetime.fromisoformat('1970-01-01T00:00:00')


def get_llc():
    """零协会最新 release -> (tag, release 对象); 失败返回 (None, None)"""
    try:
        fetcher = GitHubReleaseFetcher(False, ignore_ssl=True)
        last_ver = fetcher.get_latest_release(GITHUB_OWNER, GITHUB_REPO)
        return last_ver.tag_name, last_ver  # type: ignore
    except Exception as e:
        print(f"获取零协会版本失败: {e}")
        return None, None


def download_assets(release):
    """下载 release 里的 .7z / .zip -> (zip 资源, 7z 资源, 笔记里的下载地址)"""
    seven_asset = release.get_assets_by_extension(".7z")[0]  # type: ignore
    zip_asset = release.get_assets_by_extension(".zip")[0]  # type: ignore
    for asset in (zip_asset, seven_asset):
        # 关闭 SSL 验证: 部分环境到 GitHub 的证书链不完整
        with open(asset.name, "wb") as f:
            f.write(requests.get(asset.download_url, verify=False).content)
    return zip_asset, seven_asset, {'zip': zip_asset.download_url,
                                    'seven': seven_asset.download_url}


def upload_mirror(zip_asset, seven_asset):
    """上传到 UpFileClient 镜像 -> 笔记里的 llc_download_mirror; 失败返回 None"""
    client = UpFileClient()
    zip_result = client.upload(zip_asset.name)
    seven_result = client.upload(seven_asset.name)
    if not zip_result.get('success') or not seven_result.get('success'):
        print("镜像上传失败，本次不更新笔记")
        return None
    return {
        'zip': {'direct': zip_result.get('direct_download_url'),
                'web': zip_result.get('download_url')},
        'seven': {'direct': seven_result.get('direct_download_url'),
                  'web': seven_result.get('download_url')},
    }


def upload_lanzou(zip_asset, seven_asset):
    """上传到蓝奏云 -> 笔记里的 lanzou_download_url; 失败返回 None (不阻断主流程)"""
    uploader = LanzouUploader()
    if not uploader.login():
        print("蓝奏云登录失败，跳过蓝奏云镜像")
        return None
    zip_result = uploader.upload(zip_asset.name)
    seven_result = uploader.upload(seven_asset.name)
    if not (zip_result.get('success') and seven_result.get('success')):
        print(f"蓝奏云上传失败: zip={zip_result.get('error')}, "
              f"seven={seven_result.get('error')}，跳过蓝奏云镜像")
        return None
    return {'zip': zip_result.get('parse_url'), 'seven': seven_result.get('parse_url')}


def main():
    print(f"检查零协会汉化更新 (笔记: {ADDRESS})")

    note_ = Note(id_name="FaustLauncher", address=ADDRESS, pwd="AutoTranslate")
    note_.fetch_note_info()

    # 笔记读不出内容时分两种情况:
    #   · 笔记存在但没内容 (被清空) —— 按首次运行自愈, 稍后会把状态写回去;
    #   · 线路/HTTP 故障 —— 直接失败退出让 Action 变红。若也按首次运行继续, 会把
    #     版本状态当成空的, 于是每轮都重复下载/上传。
    if not getattr(note_, "has_get", False):
        if getattr(note_, "empty_note", False):
            print("笔记内容为空，按首次运行处理")
        else:
            reason = getattr(note_, "last_fetch_error", "") or "未知原因"
            print(f"错误: 笔记读取失败 ({reason})")
            exit(1)

    current_data = _load_note_json(note_)
    # 早期版本往笔记里写过 OurPlay 字段, 该流程已移除, 顺手清掉
    for legacy_key in ('ourplay_version', 'ourplay_download_url', 'ourplay_last_update_time'):
        current_data.pop(legacy_key, None)

    # 逐字段安全读取: 缺键不能触发"首次运行"重置, 否则已知版本会被清空,
    # 造成每轮都重复下载/上传
    current_version = current_data.get('llc_version')
    mirror_due = datetime.now() - _parse_time(current_data, 'llc_mirror_update_time') >= MIRROR_REFRESH

    print("检查零协会最新版本...")
    new_version, release = get_llc()
    if new_version is None:
        # 接口不可用时沿用笔记里的版本, 这样"只该刷镜像"的那次仍然能刷
        print("获取零协会版本失败，沿用笔记里的版本")
        new_version = current_version
    if new_version is None:
        print("获取版本信息失败，退出")
        exit(1)

    need_update = new_version != current_version
    if not need_update and not mirror_due:
        print("版本无变化")
        return
    if release is None:
        print("release 资源列表获取失败，跳过本次更新")
        return
    if need_update:
        print(f"发现新版本: {current_version} -> {new_version}")

    zip_asset, seven_asset, download_urls = download_assets(release)
    mirror = upload_mirror(zip_asset, seven_asset)
    if mirror is None:
        return

    now = datetime.now().isoformat()
    current_data['llc_download_url'] = download_urls
    current_data['llc_download_mirror'] = mirror
    current_data['llc_version'] = new_version
    current_data['llc_mirror_update_time'] = now
    if need_update:
        current_data['llc_last_update_time'] = now

    lanzou = upload_lanzou(zip_asset, seven_asset)
    if lanzou:
        current_data['lanzou_download_url'] = lanzou
        print(f"蓝奏云上传成功: {lanzou}")

    note_.update_note_content(json.dumps(current_data, ensure_ascii=False, indent=4))
    print("更新完成")


if __name__ == "__main__":
    main()
