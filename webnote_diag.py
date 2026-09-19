"""云端笔记 (webnote) 访问自检工具

用途: 当某位用户"启动器里云端数据全部获取失败, 但浏览器打开正常"时,
让他在**同一台机器**上运行本脚本, 一次性看出到底卡在哪一环:

    python webnote_diag.py

会依次检查并打印:
  1. 当前配置的笔记源 (config/web_config.json → webnote_bases)
  2. 系统 DNS 解析结果 (A/AAAA) —— 与 DoH 结果对比可发现 DNS 污染
  3. 逐个源: 建连 / TLS 握手 / HTTP 状态 / 响应大小 / 耗时
  4. DoH 解析 + 按原域名 SNI 直连 IP 的结果 (启动器的兜底路径)
  5. 本地缓存 (cache/webnote) 状态

依赖与启动器一致 (requests), 需要 Python 3.8+。
"""

import os
import socket
import ssl
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

try:
    import requests
except Exception as e:      # pragma: no cover
    print(f"缺少 requests 依赖: {e}")
    raise SystemExit(1)

import warnings
warnings.filterwarnings("ignore")

WIDTH = 74


def line(ch="─"):
    print(ch * WIDTH)


def head(title):
    line()
    print(title)
    line()


def check_dns(host):
    """系统 DNS (启动器实际使用的解析结果)"""
    out = {"A": [], "AAAA": [], "error": ""}
    try:
        for item in socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP):
            family, _, _, _, addr = item
            ip = addr[0]
            if family == socket.AF_INET and ip not in out["A"]:
                out["A"].append(ip)
            elif family == socket.AF_INET6 and ip not in out["AAAA"]:
                out["AAAA"].append(ip)
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {e}"
    return out


def check_source(url, key, timeout=(6, 15)):
    """常规请求一个笔记源, 返回 (ok, 摘要)"""
    # 1) DNS
    host = url.split("//", 1)[-1].split("/", 1)[0]
    dns = check_dns(host)
    a = ", ".join(dns["A"]) or "-"
    aaaa = ", ".join(dns["AAAA"]) or "-"
    print(f"  系统 DNS: A=[{a}] AAAA=[{aaaa}]" + (f" 错误={dns['error']}" if dns["error"] else ""))

    # 2) TCP 建连 (单独计时, 便于区分"连不上"和"连上但没响应")
    t0 = time.time()
    try:
        sock = socket.create_connection((host, 443), timeout=timeout[0])
        print(f"  TCP 建连: OK ({time.time() - t0:.2f}s)")
        try:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            t1 = time.time()
            ss = ctx.wrap_socket(sock, server_hostname=host)
            print(f"  TLS 握手: OK ({ss.version()}, {time.time() - t1:.2f}s)")
            ss.close()
        except Exception as e:
            print(f"  TLS 握手: 失败 {type(e).__name__}: {e}")
    except Exception as e:
        print(f"  TCP 建连: 失败 {type(e).__name__}: {e}")

    # 3) HTTP
    t0 = time.time()
    try:
        r = requests.get(url, verify=False, timeout=timeout)
        cost = time.time() - t0
        body = r.text or ""
        ok = r.status_code == 200 and bool(body.strip())
        print(f"  HTTP: {r.status_code}, {len(body)} 字节, {cost:.2f}s "
              f"{'✓ 正常' if ok else '✗ 内容为空或状态异常'}")
        return ok, f"HTTP {r.status_code} / {len(body)}B / {cost:.2f}s"
    except Exception as e:
        cost = time.time() - t0
        print(f"  HTTP: 失败 {type(e).__name__}: {str(e)[:160]} ({cost:.2f}s)")
        return False, f"{type(e).__name__} ({cost:.2f}s)"


def main():
    head("云端笔记 (webnote) 访问自检")

    from functions.webFunc.Webnote import (get_note_bases, get_update_url, resolve_via_doh,
                                           cache_read, _fmt_age)
    from functions.base.web_config import get_webnote

    key = get_webnote("mod_info")[0] or "FaustLauncher.mod.info.v2"
    print(f"待测笔记: {key}\n")

    bases = get_note_bases()
    print("配置的笔记源:")
    for b in bases:
        print(f"  - {b}")
    print(f"写回地址 (下载计数/排序): {get_update_url()}\n")

    results = []
    for template in bases:
        url = template.replace("{key}", key) if "{key}" in template else template.rstrip("/") + "/" + key
        head(f"常规请求: {template}")
        ok, summary = check_source(url, key)
        results.append((template, ok, summary))
        print()

    # DoH 兜底路径 (启动器在常规请求失败时使用)
    host = bases[0].split("//", 1)[-1].split("/", 1)[0]
    head("DoH 解析 (阿里/腾讯, 用于绕过 DNS 污染)")
    t0 = time.time()
    ips = resolve_via_doh(host)
    print(f"  {host} -> {ips or '解析失败'} ({time.time() - t0:.2f}s)")
    if ips:
        sys_ips = check_dns(host)["A"]
        if sys_ips and not (set(sys_ips) & set(ips)):
            print("  ⚠ 系统 DNS 与 DoH 结果不一致, 疑似 DNS 污染")
        from functions.webFunc.Webnote import _fetch_by_ip
        url0 = bases[0].replace("{key}", key) if "{key}" in bases[0] else bases[0].rstrip("/") + "/" + key
        t0 = time.time()
        text = _fetch_by_ip(url0, host, ips, (6, 15))
        print(f"  直连 IP (SNI={host}): {'✓ 成功, ' + str(len(text)) + ' 字节' if text else '✗ 失败'}"
              f" ({time.time() - t0:.2f}s)")
    print()

    head("本地缓存")
    cached, age = cache_read(key)
    if cached:
        print(f"  已缓存 {len(cached)} 字节, {_fmt_age(age)}前")
        print("  (云端失败时会自动回退到该缓存, 启动器仍可用)")
    else:
        print("  无缓存 (首次运行且云端失败时, 将没有可用数据)")
    print()

    head("结论")
    if any(ok for _, ok, _ in results):
        print("  ✓ 至少一个源可用 —— 启动器应能正常获取云端数据。")
        print("    若用户仍失败, 请让其在启动器内查看「终端」面板里的 [云端] 日志。")
    else:
        print("  ✗ 所有常规源都不可用。")
        if ips:
            print("  · DoH 解析成功, 说明大概率是系统 DNS 被污染或线路对域名不友好;")
            print("    启动器会自动走 DoH + 按域名直连 IP 兜底, 请确认启动器版本已包含该逻辑。")
        else:
            print("  · DoH 也解析失败: 该机器连 DoH 都不通, 建议更换 DNS 或网络。")
        print("  · 建议为主源的笔记准备第二个可达镜像 (见 README「云端数据」一节)。")

    print("\n各源结果:")
    for name, ok, summary in results:
        print(f"  {'✓' if ok else '✗'} {name}  {summary}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
