import json
import logging
import lzma
import time
from zipfile import ZipFile

import UnityPy
from xxhash import xxh128


def scan_lunartique_mod_root(zip_file: ZipFile) -> str:
    names = set()
    for name in zip_file.namelist():
        name_parts = name.split("/")
        while name_parts:
            name_part = "/".join(name_parts)
            names.add(name_part)
            name_parts.pop()

    for root in names:
        if f"{root}/Uninstallation" in names and f"{root}/Installation" in names:
            return root

    raise Exception("Root folder for installation folder and uninstallation folder not found")


def scan_lunartique_data(zip_path: ZipFile, data_folder: str) -> set[str]:
    root = scan_lunartique_mod_root(zip_path)
    names = set()
    for name in zip_path.namelist():
        if name.startswith(f"{root}/{data_folder}/") and name.endswith("/__data"):
            names.add(name)
    return names


def compress_lunartique_mod(zip_path: str, output: str):
    with ZipFile(zip_path, "r") as root:
        vanilla_dict = {}
        vanilla_paths = scan_lunartique_data(root, "Uninstallation")
        if len(vanilla_paths) == 0:
            raise Exception("No asset files found")

        manifest = {
            "carra_format_version": 3,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "bundles": {},
        }

        for vanilla_path in vanilla_paths:
            parts = vanilla_path.split("/")[-3:]
            with root.open(vanilla_path, "r") as f:
                env = UnityPy.load(f)
                _record_bundle_version(manifest, parts[1], env)

                for obj in env.objects:
                    data = obj.get_raw_data()
                    parts[2] = str(obj.path_id)
                    vanilla_dict["/".join(parts)] = xxh128(data).digest()

        with ZipFile(output, "w") as z:
            for modded_path in map(lambda s: s.replace("Uninstallation", "Installation"), vanilla_paths):
                parts = modded_path.split("/")[-3:]
                with root.open(modded_path, "r") as f:
                    env = UnityPy.load(f)
                    _record_bundle_version(manifest, parts[1], env)

                    for obj in env.objects:
                        data = obj.get_raw_data()
                        parts[2] = str(obj.path_id)
                        key = "/".join(parts)
                        if vanilla_dict.get(key) == xxh128(data).digest():
                            continue
                        if key not in vanilla_dict:
                            logging.info("* New object found: %s","/".join(parts))
                        # manifest entry: bundle_subfolder/path_id.type_id -> byte_size/class_id
                        asset_key = f"{parts[1]}/{obj.path_id}.{obj.type_id}"
                        manifest["bundles"].setdefault(parts[1], {}).setdefault("assets", {})[asset_key] = {
                            "byte_size": len(data),
                            "class_id": obj.type_id,
                        }
                        key += f".{obj.type_id}"
                        with z.open(key, "w") as z_f:
                            logging.info("* Writing %s", key)
                            z_f.write(lzma.compress(data, preset=9, format=lzma.FORMAT_XZ))

            # 最后写入 manifest，便于 patch 时读取版本信息
            z.writestr("_manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))


def _record_bundle_version(manifest: dict, bundle_subfolder: str, env):
    """从 UnityPy Environment 中提取 Unity 引擎版本与 SerializedFile header 版本。"""
    bundle = manifest["bundles"].setdefault(bundle_subfolder, {})
    if "unity_version" in bundle:
        return
    try:
        bundle["unity_version"] = getattr(env.file, "version_engine", "") or ""
        bundle["version_player"] = getattr(env.file, "version_player", "") or ""
        # 找到第一个 SerializedFile 的 header version
        for sub in getattr(env.file, "files", {}).values():
            header = getattr(sub, "header", None)
            if header is not None:
                bundle["serialized_file_version"] = getattr(header, "version", 0)
                bundle["unity_version"] = getattr(sub, "unity_version", bundle.get("unity_version", ""))
                break
    except Exception as e:
        logging.debug("Cannot record bundle version for %s: %s", bundle_subfolder, e)