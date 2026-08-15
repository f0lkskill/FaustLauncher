#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
rebank — Fmod 模组差分打包与修补工具
======================================

基于 fmodbank.py（复用其 FMOD/FSBANK 拆包重打包核心）。

compare : 对比两个 bank，生成 .rebank 差分包
    原版 bank + 模组版 bank 拆包对比 → 找出模组改动过的 wav → 打包成 .rebank
    （zip 内含 rebank.json 配置 + 改动的 wav，不处理"删除"，只记 修改/新增）
    判定规则：按时长三位小数比较。模组整体重编码会让所有文件字节/采样率
    都变（纯误判），但真实改动的文件时长大都会变——没有作者精确到 1ms。

patch   : 应用 .rebank 模组到目标 bank
    前 N 个 .rebank + 最后 1 个目标 bank
    → 拆包目标 bank → 按文件名替换重名 wav（新增跳过，变长变短都替换）
    → 固定 vorbis/q92 重打包 → 输出修补后的 bank
    → 用完删除临时拆包目录（--work-dir 可换盘）

info    : 查看 .rebank 内容（配置 + 文件清单）

临时目录说明：拆包工作目录默认在系统临时盘，--work-dir 可指定其它盘/路径，
每次操作结束（含出错）都会自动删除。
"""

import argparse
import datetime
import json
import os
import shutil
import struct
import sys
import tempfile
import zipfile

import fmodbank

CONFIG_NAME = "rebank.json"          # 包内配置文件，识别名字/版本等，patch 解压时跳过
WAV_EXT = ".wav"


# ---------------------------------------------------------------------------
# 控制台 UTF-8（Windows GBK 终端显示中文不乱码）
# ---------------------------------------------------------------------------
def _utf8_console():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8") # type: ignore
        except Exception:
            pass


# ---------------------------------------------------------------------------
# 日志：控制台 + 可选文件
# ---------------------------------------------------------------------------
class Logger:
    def __init__(self):
        self._files = []

    def add_file(self, path):
        try:
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
            self._files.append(open(path, "w", encoding="utf-8"))
        except OSError as e:
            print("[日志] 无法写日志文件 %s: %s" % (path, e))

    def _emit(self, prefix, msg, err=False):
        line = ("%s %s" % (prefix, msg)).rstrip() if prefix else msg
        (sys.stderr if err else sys.stdout).write(line + "\n")
        for f in self._files:
            f.write(line + "\n")
            f.flush()

    def log(self, msg=""):
        self._emit("", msg)

    def step(self, msg):
        self._emit("[步骤]", msg)

    def warn(self, msg):
        self._emit("[警告]", msg)

    def error(self, msg):
        self._emit("[错误]", msg, err=True)

    def close(self):
        for f in self._files:
            f.close()
        self._files = []


# ---------------------------------------------------------------------------
# 临时工作目录
# ---------------------------------------------------------------------------
def make_work_dir(base):
    """在 base 下建一个唯一的临时目录（默认系统临时盘）。"""
    base = base or tempfile.gettempdir()
    root = os.path.join(os.path.abspath(base), "rebank_work")
    os.makedirs(root, exist_ok=True)
    return tempfile.mkdtemp(prefix="rebank_", dir=root)


def clean_work_dir(work):
    shutil.rmtree(work, ignore_errors=True)


# ---------------------------------------------------------------------------
# 拆包 bank → wav（复用 fmodbank 原语）
# ---------------------------------------------------------------------------
def extract_bank(dlls, bank_path, wav_dir, fsb_dir, password, log):
    """拆包一个 bank 到 wav_dir。返回 (bank_base, fsb_count)。"""
    bank_name = os.path.basename(bank_path)
    bank_base = bank_name[:-5] if bank_name.lower().endswith(".bank") else bank_name
    bank_dir = os.path.dirname(os.path.abspath(bank_path))

    info, check = fmodbank.extract_fsb(bank_path, fsb_dir)
    if check == 0:
        raise RuntimeError("无法解析 bank 文件: %s" % bank_name)
    if check == 2:
        raise RuntimeError("bank 里没有 FSB 音频: %s" % bank_name)
    if check == 5:  # 加密
        password = password or fmodbank._password_for(bank_dir, bank_base, None)
        if not password:
            raise RuntimeError("bank 已加密但找不到密码文件: %s" % bank_name)
        log.step("用密码解密: %s" % password)

    os.makedirs(wav_dir, exist_ok=True)
    for j in range(info["fsb_count"]): # type: ignore
        fsb_path = os.path.join(fsb_dir, "%s[%d].fsb" % (bank_base, j))
        if not os.path.isfile(fsb_path):
            log.warn("缺少 %s[%d].fsb，跳过" % (bank_base, j))
            continue
        sub = os.path.join(wav_dir, "%s[%d]" % (bank_base, j))
        try:
            n = fmodbank.extract_fsb_to_wav(dlls, fsb_path, sub, "%s[%d]" % (bank_base, j),
                                            log.log, True, password)
            log.step("拆包 %s[%d] → %d 个 wav" % (bank_base, j, n))
        except fmodbank.FmodBankError as e:
            log.warn("跳过损坏/打不开的 FSB %s[%d]: %s" % (bank_base, j, e))
    return bank_base, info["fsb_count"] # type: ignore


# ---------------------------------------------------------------------------
# 收集 wav：{ (fsb_index:int, 文件名): 绝对路径 }
# ---------------------------------------------------------------------------
def collect_wavs(wav_dir):
    out = {}
    for name in sorted(os.listdir(wav_dir)):
        sub = os.path.join(wav_dir, name)
        if not os.path.isdir(sub) or "[" not in name or not name.endswith("]"):
            continue
        try:
            idx = int(name[name.rindex("[") + 1:name.rindex("]")])
        except ValueError:
            continue
        for f in os.listdir(sub):
            if f.lower().endswith(WAV_EXT):
                out[(idx, f)] = os.path.join(sub, f)
    return out


def files_differ(a, b):
    """判断两个 wav 是否"真不同"：按时长三位小数比较。

    模组重编码会把整个 bank 的采样率/字节都改掉，字节对比全是误判。
    真实修改的文件时长大都会变化；没动的文件即使被重编码，时长也保持不变
    （没有模组作者会精确到 1ms 以下去微调时长）。
    返回 True 表示时长不同（视为被修改）。
    """
    da = wav_duration_file(a)
    db = wav_duration_file(b)
    if da is None or db is None:
        return True  # 无法解析的按修改处理，避免漏掉
    return da != db


def wav_duration_file(path):
    """读取 wav 文件，返回时长（秒，保留 3 位小数）；无法解析返回 None。"""
    try:
        with open(path, "rb") as fh:
            info = fh.read()
    except OSError:
        return None
    mi = read_wav_info(info)
    if mi is None:
        return None
    return round(wav_duration(*mi), 3)


# ---------------------------------------------------------------------------
# wav 头解析（按 chunk 走，兼容 fmt 长度差异）
# ---------------------------------------------------------------------------
def read_wav_info(data):
    """返回 (data_len, sample_rate, channels, bits_per_sample)，非法返回 None。"""
    if len(data) < 12 or data[0:4] != b"RIFF" or data[8:12] != b"WAVE":
        return None
    pos = 12
    rate = ch = bits = None
    while pos + 8 <= len(data):
        cid = data[pos:pos + 4]
        size = struct.unpack_from("<I", data, pos + 4)[0]
        pos += 8
        if cid == b"fmt ":
            fmt = data[pos:pos + min(size, 40)]
            if len(fmt) >= 16:
                ch = struct.unpack_from("<H", fmt, 2)[0]
                rate = struct.unpack_from("<I", fmt, 4)[0]
                bits = struct.unpack_from("<H", fmt, 14)[0]
        elif cid == b"data":
            return size, rate, ch, bits
        pos += size + (size & 1)
    return None


def wav_duration(data_len, rate, ch, bits):
    if not rate or not ch or not bits:
        return 0.0
    return data_len / (rate * ch * (bits // 8))


# ---------------------------------------------------------------------------
# .rebank 打包 / 读取
# ---------------------------------------------------------------------------
def make_rebank(stage_dir, out_path):
    if os.path.exists(out_path):
        os.remove(out_path)
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as z:
        for root, _, files in os.walk(stage_dir):
            for f in files:
                full = os.path.join(root, f)
                rel = os.path.relpath(full, stage_dir).replace("\\", "/")
                z.write(full, rel)


def read_rebank_info(path):
    """读取 .rebank：返回 (config dict 或 None, [包内非配置文件名])。"""
    cfg = None
    wavs = []
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        if CONFIG_NAME in names:
            try:
                cfg = json.loads(z.read(CONFIG_NAME).decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                cfg = None
        wavs = [n for n in names if not n.startswith(CONFIG_NAME) and not n.endswith("/")]
    return cfg, wavs


# ---------------------------------------------------------------------------
# compare：对比打包 .rebank
# ---------------------------------------------------------------------------
def cmd_compare(args, dlls, log):
    log.log("======== 对比打包 ========")
    log.log("原版   : %s" % os.path.abspath(args.original))
    log.log("模组版 : %s" % os.path.abspath(args.modded))

    out_path = args.output or (os.path.splitext(args.modded)[0] + ".rebank")
    if args.log:
        log.add_file(args.log)
    else:
        log.add_file(os.path.splitext(out_path)[0] + ".log")

    work = make_work_dir(args.work_dir)
    log.log("临时目录: %s" % work)
    try:
        a_wav = os.path.join(work, "a_wav"); a_fsb = os.path.join(work, "a_fsb")
        b_wav = os.path.join(work, "b_wav"); b_fsb = os.path.join(work, "b_fsb")
        log.step("1/4 拆包原版 bank ...")
        a_base, a_count = extract_bank(dlls, args.original, a_wav, a_fsb, None, log)
        log.step("2/4 拆包模组版 bank ...")
        b_base, b_count = extract_bank(dlls, args.modded, b_wav, b_fsb, None, log)

        A = collect_wavs(a_wav)
        B = collect_wavs(b_wav)
        modified = [k for k in B if k in A and files_differ(A[k], B[k])]
        added = [k for k in B if k not in A]
        log.step("3/4 对比完成: 修改=%d 新增=%d（删除忽略，按时长三位小数判定）"
                 % (len(modified), len(added)))

        if not modified and not added:
            log.warn("两个 bank 音频完全一致，没有差异，不生成 .rebank。")
            return

        for idx, name in modified:
            log.log("  [修改] fsb[%d] %s" % (idx, name))
        for idx, name in added:
            log.log("  [新增] fsb[%d] %s" % (idx, name))

        # 暂存要打包的 wav（取模组版的）
        stage = os.path.join(work, "stage")
        os.makedirs(stage, exist_ok=True)
        for idx, name in modified + added:
            dst = os.path.join(stage, str(idx))
            os.makedirs(dst, exist_ok=True)
            shutil.copy2(B[(idx, name)], os.path.join(dst, name))

        # 配置文件
        cfg = {
            "format": "rebank",
            "name": args.name or os.path.splitext(os.path.basename(args.modded))[0],
            "version": args.version or "1.0",
            "author": args.author or "",
            "description": args.desc or "",
            "base_bank": a_base,
            "created": datetime.datetime.now().isoformat(timespec="seconds"),
            "count": len(modified) + len(added),
            "files": [
                {"index": i, "name": n,
                 "status": "modified" if (i, n) in modified else "added"}
                for (i, n) in modified + added
            ],
        }
        with open(os.path.join(stage, CONFIG_NAME), "w", encoding="utf-8") as fh:
            json.dump(cfg, fh, ensure_ascii=False, indent=2)

        make_rebank(stage, out_path)
        log.step("4/4 已生成 %s  (%d 个文件, %.1f KB)"
                 % (os.path.abspath(out_path), cfg["count"], os.path.getsize(out_path) / 1024.0))
    finally:
        clean_work_dir(work)
        log.log("已清理临时目录: %s" % work)


# ---------------------------------------------------------------------------
# patch：应用 .rebank 到目标 bank
# ---------------------------------------------------------------------------
def cmd_patch(args, dlls, log):
    mods = list(args.mod)
    banks = []
    for p in args.inputs:
        if p.lower().endswith(".rebank"):
            mods.append(p)
        else:
            banks.append(p)

    if not mods:
        raise RuntimeError("没有 .rebank 模组，用 -m 指定（可重复多个），例如: patch -m mod1.rebank -m mod2.rebank 目标.bank")
    if len(banks) != 1:
        raise RuntimeError("应该只有 1 个目标 bank，实际 %d 个: %s" % (len(banks), ", ".join(banks)))

    target = banks[0]
    out_dir = os.path.abspath(args.out_dir)
    if args.log:
        log.add_file(args.log)
    else:
        log.add_file(os.path.join(out_dir, "rebank_patch.log"))

    log.log("======== 修补 bank ========")
    log.log("目标 bank : %s" % os.path.abspath(target))
    for m in mods:
        log.log("模组       : %s" % os.path.abspath(m))

    work = make_work_dir(args.work_dir)
    log.log("临时缓存目录: %s" % work)
    os.makedirs(out_dir, exist_ok=True)
    try:
        wav_dir = os.path.join(work, "wav"); fsb_dir = os.path.join(work, "fsb")
        log.step("1/4 拆包目标 bank ...")
        bank_base, fsb_count = extract_bank(dlls, target, wav_dir, fsb_dir, args.password, log)

        T = collect_wavs(wav_dir)

        replaced = skipped_new = skipped_bad = 0
        log.step("2/4 应用模组 ...")
        for m in mods:
            mname = os.path.basename(m)
            log.log("处理 %s" % mname)
            with zipfile.ZipFile(m) as z:
                for zi in z.infolist():
                    if zi.is_dir():
                        continue
                    rel = zi.filename.replace("\\", "/")
                    if rel.lower() == CONFIG_NAME:   # 不提取配置文件
                        continue
                    parts = rel.split("/")
                    try:
                        idx = int(parts[0]); fname = parts[-1]
                    except (ValueError, IndexError):
                        skipped_bad += 1
                        log.warn("[%s] 无法识别路径 %r，跳过" % (mname, rel))
                        continue
                    key = (idx, fname)
                    if key not in T:
                        skipped_new += 1
                        log.warn("[%s] %s 目标 bank 没有此文件，跳过（新增不受支持）" % (mname, rel))
                        continue
                    mod_data = z.read(zi)
                    if read_wav_info(mod_data) is None:
                        skipped_bad += 1
                        log.warn("[%s] %s 不是有效 wav，跳过" % (mname, fname))
                        continue
                    # 变长变短都是模组内容，一律替换
                    with open(T[key], "wb") as fh:
                        fh.write(mod_data)
                    replaced += 1
                    log.log("  [替换] %s" % rel)

        log.step("替换完成: 替换=%d 新增跳过=%d 无效跳过=%d"
                 % (replaced, skipped_new, skipped_bad))
        if replaced == 0:
            raise RuntimeError("没有成功替换任何文件，取消重打包。")

        log.step("3/4 重打包 bank（固定 vorbis / q%d / %d 线程）..." % (args.quality, args.threads))
        options = {
            "format": fmodbank.FSBANK_FORMAT_VORBIS,
            "format_name": "Vorbis",
            "quality": args.quality,
            "threads": args.threads,
            "build_flags": 0,
            "cache_dir": os.path.join(work, "fsbcache"),
            "password": args.password,
        }
        fmodbank.rebuild_bank_file(dlls, target, wav_dir, fsb_dir, out_dir, options, log.log, True)
        out_bank = os.path.join(out_dir, os.path.basename(target))
        log.step("4/4 修补完成: %s (%.1f MB)"
                 % (out_bank, os.path.getsize(out_bank) / 1048576.0))
    finally:
        clean_work_dir(work)
        log.log("已清理临时缓存目录: %s" % work)


# ---------------------------------------------------------------------------
# info：查看 .rebank 内容
# ---------------------------------------------------------------------------
def cmd_info(args, dlls, log):
    for p in args.files:
        log.log("== %s ==" % os.path.abspath(p))
        cfg, wavs = read_rebank_info(p)
        if cfg:
            log.log("  名字    : %s" % cfg.get("name", "?"))
            log.log("  版本    : %s" % cfg.get("version", "?"))
            log.log("  作者    : %s" % cfg.get("author", "?"))
            log.log("  描述    : %s" % cfg.get("description", "?"))
            log.log("  目标bank: %s" % cfg.get("base_bank", "?"))
            log.log("  生成时间: %s" % cfg.get("created", "?"))
            log.log("  文件数  : %d" % len(wavs))
        else:
            log.warn("  没有 %s 配置（可能不是 rebank 包）" % CONFIG_NAME)
        for n in wavs:
            log.log("    - %s" % n)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def build_parser():
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--work-dir", metavar="DIR",
                        help="临时拆包目录（默认系统临时盘；空间不足可换盘）")
    common.add_argument("--dll-dir", metavar="DIR",
                        help="fmod64.dll / fsbank64.dll 所在目录（默认自动查找）")
    common.add_argument("--log", metavar="FILE", help="日志文件路径（默认自动生成）")

    ap = argparse.ArgumentParser(
        prog="rebank", parents=[common],
        description="Fmod 模组差分打包(.rebank)与修补工具。依赖同目录 fmodbank.py + 原版 FMOD DLL。")
    sub = ap.add_subparsers(dest="command", required=True)

    cmp = sub.add_parser("compare", parents=[common], help="对比两个 bank，生成 .rebank 差分包")
    cmp.add_argument("original", help="原版 bank")
    cmp.add_argument("modded", help="模组版 bank")
    cmp.add_argument("-o", "--output", help="输出 .rebank 路径（默认 <模组版bank名>.rebank）")
    cmp.add_argument("--name", help="模组名")
    cmp.add_argument("--version", help="模组版本（默认 1.0）")
    cmp.add_argument("--author", help="作者")
    cmp.add_argument("--desc", help="描述")
    cmp.set_defaults(func=cmd_compare)

    pat = sub.add_parser("patch", parents=[common],
                         help="应用一个或多个 .rebank 模组修补目标 bank")
    pat.add_argument("inputs", nargs="*",
                     help="目标 bank（必填）+ 模组 .rebank（也可用 -m 指定），模组按扩展名自动识别")
    pat.add_argument("-m", "--mod", action="append", default=[], metavar="REBANK",
                     help="模组 .rebank 文件，可重复传多个（自定义模组数量）")
    pat.add_argument("-o", "--out-dir", default="./build", help="输出目录（默认 ./build）")
    pat.add_argument("-p", "--password", help="目标 bank 加密密码（如需要）")
    pat.add_argument("--quality", type=int, default=92, help="重打包 vorbis 质量（固定，默认 92）")
    pat.add_argument("-cpu", "--threads", type=int, default=fmodbank.default_cpu_threads(),
                     help="重打包编码线程数（默认自动用一半 CPU 核心，如 -cpu 4）")
    pat.set_defaults(func=cmd_patch)

    inf = sub.add_parser("info", parents=[common], help="查看 .rebank 内容")
    inf.add_argument("files", nargs="+", help="一个或多个 .rebank 文件")
    inf.set_defaults(func=cmd_info)

    return ap


def main(argv=None):
    _utf8_console()
    args = build_parser().parse_args(argv)
    log = Logger()
    try:
        dlls = fmodbank.FmodDlls(args.dll_dir)
        args.func(args, dlls, log)
    except (fmodbank.FmodBankError, RuntimeError, OSError) as e:
        log.error(str(e))
        sys.exit(1)
    finally:
        log.close()


if __name__ == "__main__":
    main()
