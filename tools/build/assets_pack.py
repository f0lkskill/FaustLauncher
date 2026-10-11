"""资源包（assets pack）制作 / 校验 / 拉取 / 上传。

**为什么要有这个东西**：``assets/images``、``assets/voices`` 与皮肤里的图片合计约 38 MB，
放在 git 里会把仓库撑得很大，而它们改动频繁、和代码无关。现在这些文件**不再入库**，
改成一个独立的资源包，由开发者自己拉取合并（发布包仍然把资源打进 zip 发给最终用户）。

**包格式：解压到仓库根即完成合并。** 包里就是 ``assets/images/...``、
``web/app_skins/<皮肤>/assets/...`` 这些**和仓库完全一致的相对路径** —— 所以不需要任何
"往哪儿放"的映射逻辑；代码里那些 ``assets/images/icon/icon.ico`` 之类的相对路径原样可用。
包内另带一份 ``.assets-pack/manifest.json``（逐文件 sha256 + 版本 + 生成时间），
拉取时先校验它、再落盘；``status`` 也靠它判断本地缺了什么。

用法（也可用 ``tools/run/assets.bat``）::

    python tools/build/assets_pack.py pack                 # 生成 ./faust-assets.zip
    python tools/build/assets_pack.py status               # 本地 vs 资源包清单，缺什么/被改过
    python tools/build/assets_pack.py fetch                # 从固定地址下载并合并
    python tools/build/assets_pack.py fetch --from X.zip   # 从本地 zip / 任意 URL 合并（离线）
    python tools/build/assets_pack.py upload               # 用 gh 传成 Release 资产（需 gh 登录）

 ``upload`` 只在显式调用时执行；``pack`` / ``fetch`` 都不联网（除非 fetch 需要下载）。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile

# 仓库根 = 本文件（tools/build/assets_pack.py）往上两级
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

# 资源包里放什么（相对仓库根的 glob；**只收文件**）
#   · assets/Font/ 不收：那是从汉化包里复制出来的运行期产物，本来就不入库
#   · resources/   不收：那是启动器运行期自己下载的资源目录，也不入库
PACK_GLOBS = (
    "assets/images/**/*",
    "assets/voices/**/*",
    "web/app_skins/*/assets/**/*",
    "web/app_skins/*/source/**/*",
    "web/app_skins/*/profile.*",
)

MANIFEST_IN_PACK = ".assets-pack/manifest.json"
DEFAULT_ZIP_NAME = "faust-assets.zip"
# 固定分发地址：主仓库上 tag=assets 的 Release 资产。换仓库/tag 只改这两行（或命令行覆盖）
DEFAULT_REPO = "f0lkskill/FaustLauncher"
DEFAULT_TAG = "assets"
ASSET_NAME = DEFAULT_ZIP_NAME


# --------------------------------------------------------------------------- 收集 / 清单


def collect_files() -> list[str]:
    """按 PACK_GLOBS 收集要打进资源包的文件（相对路径，正斜杠，已排序）。"""
    import glob as _glob

    found: set[str] = set()
    for pattern in PACK_GLOBS:
        for path in _glob.glob(os.path.join(ROOT, pattern), recursive=True):
            if not os.path.isfile(path):
                continue
            rel = os.path.relpath(path, ROOT).replace("\\", "/")
            if os.path.basename(rel).startswith("."):
                continue
            found.add(rel)
    return sorted(found)


def sha256_of(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_manifest(files: list[str], version: str) -> dict:
    entries = {}
    for rel in files:
        full = os.path.join(ROOT, rel)
        entries[rel] = {"sha256": sha256_of(full), "size": os.path.getsize(full)}
    head = ""
    try:
        head = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                              capture_output=True, text=True, timeout=10
                              ).stdout.strip()
    except Exception:  # noqa: BLE001
        pass
    return {"schema": 1, "version": version, "built_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "git_head": head, "file_count": len(entries), "files": entries}


def read_manifest_from_zip(zip_path: str) -> dict | None:
    try:
        with zipfile.ZipFile(zip_path) as zf:
            with zf.open(MANIFEST_IN_PACK) as fh:
                return json.loads(fh.read().decode("utf-8"))
    except Exception:  # noqa: BLE001
        return None


def read_local_manifest() -> dict | None:
    path = os.path.join(ROOT, MANIFEST_IN_PACK)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:  # noqa: BLE001
        return None


def pack_url(repo: str, tag: str) -> str:
    return f"https://github.com/{repo}/releases/download/{tag}/{ASSET_NAME}"


# --------------------------------------------------------------------------- 子命令


def cmd_pack(args) -> int:
    files = collect_files()
    if not files:
        print("没有收集到任何资源文件 —— 检查 PACK_GLOBS 或确认本地资源还在")
        return 1
    version = args.version or time.strftime("%Y-%m-%d")
    manifest = build_manifest(files, version)
    out = os.path.abspath(args.out or os.path.join(ROOT, DEFAULT_ZIP_NAME))
    total = sum(item["size"] for item in manifest["files"].values())
    print(f"资源包版本 {version}（git {manifest['git_head'] or '?'}）")
    print(f"待打包 {len(files)} 个文件，原始 {total / 1048576:.1f} MB")
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for rel in files:
            zf.write(os.path.join(ROOT, rel), rel)
        zf.writestr(MANIFEST_IN_PACK, json.dumps(manifest, ensure_ascii=False, indent=1))
    size = os.path.getsize(out)
    print(f"已生成 {out}（{size / 1048576:.1f} MB，压缩率 {size / max(total, 1):.0%}）")
    print(f"固定分发地址：{pack_url(args.repo, args.tag)}")
    print("上传：python tools/build/assets_pack.py upload"
          + (f" --repo {args.repo} --tag {args.tag}" if args.repo != DEFAULT_REPO
             or args.tag != DEFAULT_TAG else ""))
    return 0


def cmd_status(args) -> int:
    manifest = read_local_manifest()
    if manifest is None:
        print(f"本地没有 {MANIFEST_IN_PACK} —— 还没拉过资源包。")
        print(f"拉取：python tools/build/assets_pack.py fetch")
        # 仍然报一下"文件在不在"，方便判断是不是压根不需要拉
        files = collect_files()
        print(f"（当前工作区里能收集到 {len(files)} 个资源文件，共 "
              f"{sum(os.path.getsize(os.path.join(ROOT, f)) for f in files) / 1048576:.1f} MB）")
        return 1
    missing, changed, ok = [], [], 0
    for rel, item in manifest["files"].items():
        full = os.path.join(ROOT, rel)
        if not os.path.isfile(full):
            missing.append(rel)
        elif sha256_of(full) != item["sha256"]:
            changed.append(rel)
        else:
            ok += 1
    extra = [f for f in collect_files() if f not in manifest["files"]]
    print(f"资源包版本 {manifest.get('version')}（{manifest.get('built_at')}，"
          f"{manifest.get('file_count')} 个文件）")
    print(f"一致 {ok} / 缺失 {len(missing)} / 内容不同 {len(changed)} / 清单外 {len(extra)}")
    for label, rows in (("缺失", missing), ("内容不同", changed), ("清单外(本地多出来)", extra)):
        if rows:
            print(f"  {label}: {', '.join(rows[:6])}" + (" …" if len(rows) > 6 else ""))
    if missing or changed:
        print("需要重新拉取：python tools/build/assets_pack.py fetch")
        return 1
    print("本地与资源包一致。")
    return 0


def _download(url: str, dest: str) -> int:
    import urllib.request

    print(f"下载 {url}")
    with urllib.request.urlopen(url, timeout=60) as resp:  # noqa: S310
        total = int(resp.headers.get("Content-Length") or 0)
        done = 0
        with open(dest, "wb") as fh:
            while True:
                chunk = resp.read(1 << 20)
                if not chunk:
                    break
                fh.write(chunk)
                done += len(chunk)
                if total:
                    print(f"\r  {done / 1048576:.1f}/{total / 1048576:.1f} MB", end="")
    print()
    return os.path.getsize(dest)


def cmd_fetch(args) -> int:
    src = args.source or pack_url(args.repo, args.tag)
    tmp_dir = tempfile.mkdtemp(prefix="faust-assets-")
    try:
        if os.path.isfile(src):
            zip_path = src
            print(f"用本地资源包：{zip_path}")
        else:
            zip_path = os.path.join(tmp_dir, ASSET_NAME)
            try:
                _download(src, zip_path)
            except Exception as exc:  # noqa: BLE001
                print(f"下载失败：{type(exc).__name__}: {exc}")
                print(f"若资源包还没发布，可先拿到 zip 再离线合并："
                      f"python tools/build/assets_pack.py fetch --from <zip>")
                return 1

        manifest = read_manifest_from_zip(zip_path)
        if manifest is None:
            print(f"这个 zip 里没有 {MANIFEST_IN_PACK} —— 不是本工具生成的资源包，拒绝合并")
            return 1
        files = manifest.get("files") or {}
        print(f"资源包版本 {manifest.get('version')}（{manifest.get('built_at')}，"
              f"git {manifest.get('git_head') or '?'}），{len(files)} 个文件")

        # 先整体校验，再落盘：坏包不会把工作区改成半截状态
        bad = []
        with zipfile.ZipFile(zip_path) as zf:
            names = set(zf.namelist())
            for rel, item in files.items():
                if rel not in names:
                    bad.append(f"{rel}（包内缺条目）")
                    continue
                digest = hashlib.sha256(zf.read(rel)).hexdigest()
                if digest != item["sha256"]:
                    bad.append(f"{rel}（哈希不符）")
        if bad:
            print(f"校验失败 {len(bad)} 个：{', '.join(bad[:5])}" + (" …" if len(bad) > 5 else ""))
            return 1
        print("校验通过（逐文件 sha256）")

        if args.dry_run:
            print("--dry-run：只校验，不写盘")
            return 0

        written = 0
        with zipfile.ZipFile(zip_path) as zf:
            for rel in files:
                full = os.path.join(ROOT, rel.replace("/", os.sep))
                os.makedirs(os.path.dirname(full), exist_ok=True)
                with zf.open(rel) as src_fh, open(full, "wb") as dst_fh:
                    shutil.copyfileobj(src_fh, dst_fh)
                written += 1
            os.makedirs(os.path.join(ROOT, ".assets-pack"), exist_ok=True)
            with zf.open(MANIFEST_IN_PACK) as src_fh, \
                    open(os.path.join(ROOT, MANIFEST_IN_PACK), "wb") as dst_fh:
                shutil.copyfileobj(src_fh, dst_fh)
        print(f"已合并 {written} 个文件到仓库根（{ROOT}）")
        return 0
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def cmd_upload(args) -> int:
    zip_path = os.path.abspath(args.out or os.path.join(ROOT, DEFAULT_ZIP_NAME))
    if not os.path.isfile(zip_path):
        print(f"没有 {zip_path} —— 先跑 pack")
        return 1
    gh = shutil.which("gh")
    if not gh:
        print("找不到 gh（GitHub CLI）。装好并 gh auth login 后再试，"
              "或手动把 zip 传到 Release 资产里。")
        return 1
    url = pack_url(args.repo, args.tag)
    print(f"目标：{args.repo} 的 tag={args.tag}，资产名 {ASSET_NAME}")
    check = subprocess.run([gh, "release", "view", args.tag, "--repo", args.repo],
                           capture_output=True, text=True)
    if check.returncode != 0:
        print(f"tag {args.tag} 还没有 Release，创建它…")
        made = subprocess.run(
            [gh, "release", "create", args.tag, "--repo", args.repo,
             "--title", "资源包（assets pack）",
             "--notes", "开发者用的资源包。下载后解压到仓库根即完成合并，"
                        "或直接跑 tools/run/assets.bat fetch。"],
            capture_output=True, text=True)
        if made.returncode != 0:
            print(f"创建 Release 失败：{made.stderr.strip()}")
            return 1
    up = subprocess.run([gh, "release", "upload", args.tag, zip_path,
                         "--repo", args.repo, "--clobber"],
                        capture_output=True, text=True)
    if up.returncode != 0:
        print(f"上传失败：{up.stderr.strip()}")
        return 1
    print(f"上传完成：{url}")
    print("（tag 固定不变 → 拉取地址永远是这个，开发者不需要关心版本）")
    return 0


# --------------------------------------------------------------------------- CLI


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python tools/build/assets_pack.py",
        description="FaustLauncher 资源包：制作 / 校验 / 拉取 / 上传")
    parser.add_argument("--repo", default=DEFAULT_REPO, help=f"GitHub 仓库（默认 {DEFAULT_REPO}）")
    parser.add_argument("--tag", default=DEFAULT_TAG, help=f"Release tag（默认 {DEFAULT_TAG}）")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("pack", help="生成资源包 zip")
    p.add_argument("--out", default="", help=f"输出路径（默认仓库根 {DEFAULT_ZIP_NAME}）")
    p.add_argument("--version", default="", help="包版本（默认今天日期）")
    p.set_defaults(func=cmd_pack)

    p = sub.add_parser("status", help="本地资源 vs 资源包清单")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("fetch", help="下载资源包并合并到仓库根")
    p.add_argument("--from", dest="source", default="",
                   help="改用本地 zip 或其它 URL（离线/内网分发）")
    p.add_argument("--dry-run", action="store_true", help="只下载校验，不写盘")
    p.set_defaults(func=cmd_fetch)

    p = sub.add_parser("upload", help="用 gh 把 zip 传成 Release 资产")
    p.add_argument("--out", default="", help=f"要上传的 zip（默认 {DEFAULT_ZIP_NAME}）")
    p.set_defaults(func=cmd_upload)
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    os.chdir(ROOT)
    return int(args.func(args) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
