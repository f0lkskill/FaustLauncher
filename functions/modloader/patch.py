import glob
import json
import xxhash
import lzma
import os.path
import shutil
import logging
from pathlib import Path
from zipfile import ZipFile

from UnityPy.files import SerializedFile, BundleFile, ObjectReader
from UnityPy.streams import EndianBinaryReader

from compress import compress_lunartique_mod
from unity_utils import load_bundle_versions

import UnityPy


# ---------- 版本/尺寸兼容辅助 ----------


def load_carra_manifest(mod_asset_root: str, bundle_name: str) -> dict:
    """尝试从模组解压目录里读取 _manifest.json（兼容旧版 carra 无 manifest 的场景）。"""
    candidate = os.path.join(mod_asset_root, bundle_name, "_manifest.json")
    if os.path.isfile(candidate):
        try:
            with open(candidate, "rb") as mf:
                return json.load(mf)
        except Exception as e:
            logging.info("- Manifest parse failed, ignoring: %s", e)
    return {}


def safe_set_raw_data(obj: ObjectReader, data: bytes, manifest: dict, bundle_info: dict, asset_key: str):
    """对比 manifest 记录的 byte_size 与当前对象的 byte_size，安全地写入原始数据。

    策略：
      - 完全一致：直接 set_raw_data(data)；
      - 否则：按当前对象的 byte_size 截断或尾部零填充，
        避免 UnityPy 保存时大小不一致导致 bundle 校验失败或游戏崩溃。
    """
    current_size = getattr(obj, "byte_size", 0)
    asset_entry = manifest.get(asset_key, {}) if manifest else {}
    old_size = asset_entry.get("byte_size", 0)

    # 没有 manifest / 完全匹配 -> 直接写
    if not manifest or old_size == 0 or old_size == current_size:
        obj.set_raw_data(data)
        return

    # 尺寸变化，按当前对象要求的 byte_size 对齐
    data_len = len(data)
    if data_len == current_size:
        obj.set_raw_data(data)
        return

    if data_len > current_size:
        logging.warning(
            "- Asset size mismatch: modded=%d, current=%d; truncating to current size (path_id=%s)",
            data_len, current_size, asset_key,
        )
        obj.set_raw_data(data[:current_size])
    else:
        logging.warning(
            "- Asset size mismatch: modded=%d, current=%d; zero-padding (path_id=%s)",
            data_len, current_size, asset_key,
        )
        obj.set_raw_data(data + b"\x00" * (current_size - data_len))



def bundle_data_paths(appdata: str = os.getenv("APPDATA")):
    cache_path = os.path.join(appdata, "../LocalLow/Unity/ProjectMoon_LimbusCompany/*/*/")
    return map(os.path.normpath, glob.glob(cache_path))


def file_digest(file_path):
    with open(file_path, "rb") as ff:
        xxdigest = xxhash.xxh128()
        while chunk := ff.read(8192):
            xxdigest.update(chunk)

        return xxdigest.hexdigest()


def detect_lunartique_mods(mod_zips_root: str):
    for mod_zip in glob.glob(f"{mod_zips_root}/*.zip"):
        logging.info("Compressing lunartique format mod (might take a while!): %s", mod_zip)
        try:
            compress_lunartique_mod(mod_zip, mod_zip.replace(".zip", ".carra2"))
            os.remove(mod_zip)
            logging.info("* Done")
        except Exception as e:
            logging.info("* Error: %s", e)


def mod_file_size(file):
    try:
        return os.path.getsize(file)
    except:
        return 1 << 64


def extract_assets(mod_asset_root: str, mod_zips_root: str):
    for mod_zip in sorted(glob.glob(f"{mod_zips_root}/*.carra*"), key=mod_file_size, reverse=True):
        mod_zip = os.path.normpath(mod_zip)
        try:
            with ZipFile(mod_zip) as z:
                logging.info("Extracting %s", mod_zip)
                z.extractall(mod_asset_root)
        except Exception as e:
            logging.info("Error processing %s: %s", mod_zip, e)

    for mod_carra in glob.glob(f"{mod_asset_root}/*/*/*"):
        mod_carra_path = Path(mod_carra)
        new_mod_carra = os.path.join(mod_carra_path.parent.parent, mod_carra_path.name)
        os.replace(mod_carra, new_mod_carra)


def cleanup_assets(bundle_data=bundle_data_paths):
    logging.info("Restoring data")
    for bundle_root in bundle_data():
        bundle_path = os.path.join(bundle_root, "__data")
        new_path = os.path.join(bundle_root, "__original")
        if not os.path.isfile(new_path):
            continue

        try:
            env = UnityPy.load(bundle_path)
            if env.file.version_player != "limbus_modded":
                os.remove(new_path)
                continue
        except Exception as e:
            logging.info("Corrupted file detected %s: %s", bundle_path, e)

        logging.info("Restoring %s", bundle_path)
        os.replace(new_path, bundle_path)


def patch_bundle_asset(env: UnityPy.Environment, mod_path: str):
    bundle_name = os.path.basename(os.path.normpath(mod_path))
    bundle_info = load_bundle_versions(env)
    # manifest 解压在 mod_asset_root/{bundle_name_parent}/下一级
    mod_root = os.path.dirname(mod_path)
    manifest = load_carra_manifest(mod_root, bundle_name)
    bundle_manifest = manifest.get("bundles", {}).get(bundle_name, {}) if manifest else {}
    asset_manifest = bundle_manifest.get("assets", {}) if bundle_manifest else {}

    # 若 manifest 与当前 Unity 版本差异则打印一次警告
    if manifest:
        old_uv = bundle_manifest.get("unity_version", "")
        cur_uv = bundle_info.get("unity_version", "")
        if old_uv and cur_uv and old_uv != cur_uv:
            logging.warning(
                "- Unity engine version mismatch: modded=%s current=%s; applying size-safe injection",
                old_uv, cur_uv,
            )

    for f in env.file.files.values():
        if not isinstance(f, SerializedFile):
            logging.info("Expected serialized file but got a %s instead?? Skipped", type(f))
            return

        objects = f.objects
        for modded_asset in os.listdir(mod_path):
            try:
                name = modded_asset.split(".")
                path_id = int(name[0])
                type_id = -1
                if len(name) > 1:
                    type_id = int(name[1])
            except ValueError:
                continue

            mod_part_path = os.path.join(mod_path, modded_asset)
            if not os.path.isfile(mod_part_path):
                continue
            if obj := objects.get(path_id):
                if not isinstance(obj, ObjectReader):
                    logging.error("- Object is not ObjectReader, wtf?")
                    continue
                logging.info("- Loading %s", mod_part_path)
                if type_id > 0 and type_id != obj.type_id:
                    logging.info("- Mismatching asset type, vanilla: %d, modded: %d, skipped", obj.type_id, type_id)
                    continue
                with open(mod_part_path, "rb") as mf:
                    safe_set_raw_data(
                        obj,
                        lzma.decompress(mf.read(), format=lzma.FORMAT_XZ),
                        asset_manifest,
                        bundle_info,
                        f"{bundle_name}/{path_id}.{type_id}",
                    )
            elif type_id > 0:
                logging.info("- Adding unused mod asset of type %d: %s", type_id, mod_part_path)
                reader = EndianBinaryReader(bytes(bytearray(1024)))
                obj = ObjectReader(assets_file=f, reader=reader)
                obj.path_id = path_id
                obj.type_id = type_id
                with open(mod_part_path, "rb") as mf:
                    obj.set_raw_data(lzma.decompress(mf.read(), format=lzma.FORMAT_XZ))
                objects[path_id] = obj


def patch_assets(mod_asset_root: str, bundle_data=bundle_data_paths):
    for bundle_root in bundle_data():
        # Move the original data to a new location temporarily
        bundle_root_path = Path(bundle_root)
        mod_path = os.path.join(mod_asset_root, bundle_root_path.parent.name)
        if not os.path.isdir(mod_path):
            continue

        bundle_path = os.path.join(bundle_root, "__data")
        new_path = os.path.join(bundle_root, "__original")
        os.chmod(bundle_path, 0o777)
        logging.info("Backing up %s", bundle_path)
        os.replace(bundle_path, new_path)

        logging.info("Patching %s", bundle_path)
        env = UnityPy.load(new_path)
        patch_bundle_asset(env, mod_path)

        env.file.version_player = "limbus_modded"
        with open(bundle_path, "wb") as f:
            f.write(env.file.save(packer="none"))
        logging.info("* Patching complete %s (%d) -> %s (%d)", file_digest(new_path), os.path.getsize(new_path),
                     file_digest(bundle_path), os.path.getsize(bundle_path))