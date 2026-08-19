"""OurPlay 汉化包下载: 获取下载 URL / 版本, 以及神人版结构转换

两个版本 (均为 OurPlay Android 端 API, 以 is_unofficial 区分):
    普通版 (正经版): is_unofficial=2
    神人版:          is_unofficial=3
下载内容为 transfile (hash 命名文件), 需借助基板包 (参考包) 转换为标准结构。
"""
import base64
import json
import os
import shutil
import tempfile
import zipfile
from collections import defaultdict

import requests

# ── 设备信息 ────────────────────────────────────────────────────


def _make_device_android() -> str:
    """OurPlay Android 端设备信息 (base64)"""
    device = {
        "product": "V1824A",
        "mainver": 306800,
        "os": "Android",
        "productId": 6000,
        "hos_version": "",
        "release": "9",
        "abi": "arm64-v8a",
        "brand_name": "vivo",
        "pkg": "com.excean.gspace",
        "vc": 11020,
        "manufacturer": "vivo",
        "apiPublicFlag": 110,
        "vn": "8.5.9",
        "model": "V1824A",
        "packageName": "com.excean.gspace",
        "api": 28,
        "brand": "vivo",
        "aid": "f219cadbb65e69de",
        "isHOS": 0,
        "ab_info": ["PE-1", "OC-2", "PG-0", "PF-1"],
        "all_ab_info": ["PE-1", "OC-2", "PG-0", "PF-1"],
        "abTest": "62",
        "ssid": "1733610978679124900",
        "deviceId": "7645707876178117133",
        "userArea": 330000,
        "userId": "2026-4908897",
        "guestid": 61875446,
        "vip": 0,
        "cdpTags": "",
        "gmp_tags": [""],
        "customizationAd": 1,
        "customizationGame": 1,
        "customizationPush": 1,
        "uqid": "67511305",
        "cqid": "f219de4761vtz42mvosy",
        "first_channel": "610035",
        "first_sub_channel": "109",
        "last_channel": "610035",
        "last_sub_channel": "109",
        "now_channel": "610035",
        "now_sub_channel": "99",
        "uid_channel": "610035",
        "chid": "610035",
        "subchid": "109",
        "adchid": "",
        "nuser_id": "1060002610013974648",
        "nuserid_channel": 610035,
        "nuserid_sub_channel": 109,
        "nuserid_vercode": "11020",
        "nuserid_create_date": "2026-07-08 16:20:16",
        "language": "zh",
        "country": "cn",
        "uid": 24405328,
        "rid": 0,
        "compver": 127200,
        "oaid": "",
        "ipv4": "36.24.25.176",
        "operatorIp": "112.0.1.1",
    }
    device_str = json.dumps(device)
    return base64.b64encode(device_str.encode("utf-8")).decode("utf-8")


# ── 下载信息获取 ────────────────────────────────────────────────


def get_ourplay_download_info(official: bool = True):
    """获取 OurPlay 汉化包下载信息

    official=True  -> 普通版 (is_unofficial=2)
    official=False -> 神人版 (is_unofficial=3)

    Returns:
        (download_url, md5, size, version_code) 或 None
    """
    return _fetch_android_info(official=official)


def _fetch_android_info(official: bool):
    headers = {
        "device-user": _make_device_android(),
        "User-Agent": "okhttp/3.12.13",
    }
    url = "https://gapi.ourplay.com.cn/depends/zhapk"
    data = {"pkg": "com.ProjectMoon.LimbusCompany", "language_type": "chinese",
            "language_ver": 0, "split": 1, "is_unofficial": 2 if official else 3,
            "ver": "406"}
    r = requests.post(url, headers=headers, data=data, timeout=(10, 60))
    r.raise_for_status()
    response_data = r.json()
    if response_data.get("code") != 1:
        return None
    d = response_data["data"]
    return d["url"], d["md5"], d["size"], str(d["versionCode"])


# ── 解压与结构处理 ──────────────────────────────────────────────


def extract_translation_zip(zip_path: str, extract_dir: str) -> bool:
    """解压 OurPlay 汉化包 zip 到目录"""
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(extract_dir)
        return True
    except Exception as e:
        print(f"[OurPlay] 解压失败: {e}")
        return False


def find_ourplay_root(extract_dir: str) -> str | None:
    """在解压目录中定位标准 OurPlayHanHua 目录 (如 com.ProjectMoon.LimbusCompany/Lang/OurPlayHanHua)"""
    for dirpath, dirnames, filenames in os.walk(extract_dir):
        if os.path.basename(dirpath) == "OurPlayHanHua":
            if os.path.isfile(os.path.join(dirpath, "manifest.json")):
                return dirpath
    return None


# ── 神人版转换 (移植自 LCTA) ────────────────────────────────────

# 参考包索引缓存: 参考包不变时跳过全量解析 (参考包通常 2000+ 文件)
_reference_index_cache = {
    "fingerprint": "",
    "ref_files": None,
    "id_to_paths": None,
}


def _dir_fingerprint(root) -> str:
    """目录快速指纹: 基于所有文件的相对路径 + 大小 + 修改时间"""
    import hashlib
    h = hashlib.md5()
    try:
        for dirpath, dirnames, filenames in os.walk(root):
            for fn in sorted(filenames):
                p = os.path.join(dirpath, fn)
                try:
                    st = os.stat(p)
                except OSError:
                    continue
                rel = os.path.relpath(p, root).replace("\\", "/")
                h.update(rel.encode("utf-8", "ignore"))
                h.update(str(st.st_size).encode("ascii"))
                h.update(str(int(st.st_mtime)).encode("ascii"))
    except Exception:
        return ""
    return h.hexdigest()


def _build_reference_index(refer_root):
    """基板包索引: {relative_path: set_of_ids} / {id: [paths]}

    参考包目录内容未变化时使用缓存, 避免每次转换都重新解析全部文件。
    """
    global _reference_index_cache
    fp = _dir_fingerprint(refer_root)
    if fp and fp == _reference_index_cache.get("fingerprint") \
            and _reference_index_cache.get("ref_files") is not None:
        print("[OurPlay] 参考包索引命中缓存, 跳过全量解析")
        return _reference_index_cache["ref_files"], _reference_index_cache["id_to_paths"]

    ref_files = {}
    id_to_paths = defaultdict(list)
    for dirpath, dirnames, filenames in os.walk(refer_root):
        for filename in filenames:
            filepath = os.path.join(dirpath, filename)
            rel_path = os.path.relpath(filepath, refer_root).replace("\\", "/")
            if not filename.endswith(".json"):
                continue
            if filename == "manifest.json":
                continue
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue
            if "dataList" not in data or not isinstance(data["dataList"], list):
                continue
            ids = set()
            for item in data["dataList"]:
                if isinstance(item, dict) and "id" in item:
                    id_val = str(item["id"])
                    if id_val:
                        ids.add(id_val)
                        id_to_paths[id_val].append(rel_path)
            if ids:
                ref_files[rel_path] = ids
    print(f"[OurPlay] 参考包索引: {len(ref_files)} 个文件, {len(id_to_paths)} 个唯一 ID")
    if fp:
        _reference_index_cache.update(
            fingerprint=fp, ref_files=ref_files, id_to_paths=id_to_paths)
    return ref_files, id_to_paths


def _build_transfile_index(hash_dir):
    """transfile 索引: {hash_filename: (data_list, set_of_ids)}

    2000+ 个 JSON 文件逐个解析较慢, 用线程池并行解析 (json.load 为 C 实现, 多线程可提速)。
    """
    from concurrent.futures import ThreadPoolExecutor

    hash_files = {}
    binary_count = 0
    if not os.path.isdir(hash_dir):
        return hash_files, binary_count
    filenames = []
    for filename in os.listdir(hash_dir):
        filepath = os.path.join(hash_dir, filename)
        if not os.path.isfile(filepath):
            continue
        if filename == "google_app_measurement_local.db":
            continue
        filenames.append(filename)

    def _parse_one(filename):
        filepath = os.path.join(hash_dir, filename)
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return filename, None, True
        if "dataList" not in data or not isinstance(data["dataList"], list):
            return filename, None, True
        ids = set()
        for item in data["dataList"]:
            if isinstance(item, dict) and "id" in item:
                id_val = str(item["id"])
                if id_val:
                    ids.add(id_val)
        return filename, (data["dataList"], ids), False

    workers = max(4, min(16, os.cpu_count() or 4))
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for filename, parsed, is_bin in ex.map(_parse_one, filenames):
            if is_bin:
                binary_count += 1
                continue
            hash_files[filename] = parsed
    print(f"[OurPlay] transfile 扫描: {len(hash_files)} 个 JSON, {binary_count} 个二进制/非JSON")
    return hash_files, binary_count


def _match_ref_to_transfile(ref_files, hash_files, id_to_paths):
    """为每个基板包文件找到最佳 transfile hash 文件 (多数投票)"""
    id_to_hash = defaultdict(set)
    for hash_name, (data_list, hash_ids) in hash_files.items():
        for hid in hash_ids:
            id_to_hash[hid].add(hash_name)

    # 预计算各 hash 文件的 id 数 (max 排序用, 避免重复 len)
    hash_id_size = {h: len(hash_files[h][1]) for h in hash_files}

    ref_to_hash = {}
    for ref_path, ref_ids in ref_files.items():
        hash_votes = defaultdict(int)
        for rid in ref_ids:
            for hname in id_to_hash.get(rid, ()):
                hash_votes[hname] += 1
        if hash_votes:
            best_hash = max(hash_votes.keys(),
                            key=lambda h: (hash_votes[h], -hash_id_size[h]))
            if hash_votes[best_hash] >= max(1, len(ref_ids) * 0.5):
                ref_to_hash[ref_path] = best_hash

    print(f"[OurPlay] 匹配完成: {len(ref_to_hash)}/{len(ref_files)} 个基板文件已匹配 transfile")
    return ref_to_hash


def convert_god_package(extract_dir: str, refer_root: str) -> str:
    """将神人版 transfile 目录转换为标准 OurPlayHanHua 结构, 返回输出目录

    extract_dir: 神人版包解压目录 (含 com.ProjectMoon.LimbusCompany/)
    refer_root:  基板包目录 (已安装的零协汉化目录, 标准结构)
    """
    hash_dir = os.path.join(extract_dir, "com.ProjectMoon.LimbusCompany")
    ref_files, id_to_paths = _build_reference_index(refer_root)
    if not ref_files:
        raise RuntimeError("基板包中未找到任何有效的 JSON 文件")
    hash_files, binary_count = _build_transfile_index(hash_dir)
    ref_to_hash = _match_ref_to_transfile(ref_files, hash_files, id_to_paths)

    output_root = os.path.join(extract_dir, "output")
    ourplay_root = os.path.join(output_root, "OurPlayHanHua")
    os.makedirs(ourplay_root, exist_ok=True)
    for sub in ("Font", "Context"), ("Font", "Title"):
        os.makedirs(os.path.join(ourplay_root, *sub), exist_ok=True)

    from_transfile = 0
    from_reference = 0

    for ref_path in ref_files:
        dest = os.path.join(ourplay_root, ref_path.replace("/", os.sep))
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        if ref_path in ref_to_hash:
            shutil.copy2(os.path.join(hash_dir, ref_to_hash[ref_path]), dest)
            from_transfile += 1
        else:
            src = os.path.join(refer_root, ref_path.replace("/", os.sep))
            if os.path.exists(src):
                shutil.copy2(src, dest)
            from_reference += 1

    # 复制非 dataList 文件 (Info、无 dataList 的 JSON 等), 但跳过 Font 字体
    # (OurPlay 包不带字体, 参考包字体为其他汉化组所有, 不应混入; 空目录已满足游戏验证)
    for dirpath, dirnames, filenames in os.walk(refer_root):
        for filename in filenames:
            filepath = os.path.join(dirpath, filename)
            rel_path = os.path.relpath(filepath, refer_root).replace("\\", "/")
            if rel_path in ref_files:
                continue
            if rel_path.startswith("Font/"):
                continue
            if filename == "manifest.json":
                continue
            dest = os.path.join(ourplay_root, rel_path.replace("/", os.sep))
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            shutil.copy2(filepath, dest)

    total = from_transfile + from_reference
    rate = 100 * from_transfile / total if total > 0 else 0
    print(f"[OurPlay] 转换完成: 总计 {total} 个文件, 来自 transfile: {from_transfile} ({rate:.1f}%), "
          f"来自基板回退: {from_reference}, 跳过二进制: {binary_count}")
    return ourplay_root


def prepare_ourplay_dir(zip_path: str, refer_root: str = "") -> tuple[str, str]:
    """处理 OurPlay 汉化包 zip -> 标准 OurPlayHanHua 目录

    Args:
        zip_path: 下载的汉化包 zip 路径
        refer_root: 转换所需的基板包目录 (标准结构汉化包, 如零协会)

    Returns:
        (ourplay_dir, temp_dir_to_cleanup) 或抛异常
    """
    temp_dir = tempfile.mkdtemp(prefix="ourplay_")
    try:
        if not extract_translation_zip(zip_path, temp_dir):
            raise RuntimeError("OurPlay 汉化包解压失败")
        # 1) 直接定位标准结构 (manifest 内置的完整包)
        root = find_ourplay_root(temp_dir)
        if root:
            return root, temp_dir
        # 2) transfile 结构: 需参考包转换
        if not refer_root or not os.path.isdir(refer_root):
            raise RuntimeError(
                "OurPlay 汉化包为 transfile 结构, 需要基板包(参考包)转换, 但未找到参考包。\n"
                "请先安装任一标准结构的汉化包 (如零协会) 作为参考包。"
            )
        ourplay_root = convert_god_package(temp_dir, refer_root)
        return ourplay_root, temp_dir
    except Exception:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise


if __name__ == "__main__":
    info = get_ourplay_download_info(official=True)
    print("普通版:", info)
    info2 = get_ourplay_download_info(official=False)
    print("神人版:", info2)
