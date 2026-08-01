def load_bundle_versions(env):
    """从 UnityPy Environment 中读取 Unity 引擎版本与 SerializedFile header 版本。"""
    info = {"unity_version": "", "serialized_file_version": 0, "version_player": ""}
    try:
        info["unity_version"] = getattr(env.file, "version_engine", "") or ""
        info["version_player"] = getattr(env.file, "version_player", "") or ""
        for sub in getattr(env.file, "files", {}).values():
            header = getattr(sub, "header", None)
            if header is not None:
                info["serialized_file_version"] = getattr(header, "version", 0)
                info["unity_version"] = getattr(sub, "unity_version", info["unity_version"])
                break
    except Exception:
        pass
    return info
