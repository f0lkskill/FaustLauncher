"""
已弃用
纯ai瞎写的,别笑我

LLC BABEL Python 复刻 - 命令行版本
面向《边狱公司》的网络连接优选工具

功能：
1. Cloudflare CDN 优选（延迟+下载测速）
2. CloudFront API 优选（多源DNS解析+HTTPS探针）
3. Hosts 文件管理（安全写入、备份、还原）
"""

import argparse
import asyncio
import csv
import json
import os
import platform
import re
import shutil
import socket
import ssl
import subprocess
import sys
import tempfile
import time
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional, Set, Tuple
from urllib.parse import urlencode

import urllib.error


# ============== 配置 ==============
CONFIG_DIR = Path(__file__).parent.parent.parent / "config"
CFST_DIR = Path(__file__).parent / "cfst"

# Cloudflare 配置
CF_DOMAINS = [
    "download.limbuscompanycdn.org",
    "downloadcommon.limbuscompanycdn.org",
    "downloadfmod.limbuscompanycdn.org"
]
CF_IP_FILE = CFST_DIR / "ip.txt"
CF_RESULT_FILE = CFST_DIR / "result.csv"

# 多个测速 URL 备选
CF_TEST_URLS = [
    "https://cf.xiu2.xyz/url",
    "https://speed.cloudflare.com/__down?bytes=25000000",
    "https://speed.cloudflare.com/__down?bytes=10000000",
]

# CloudFront 配置
CFRONT_ENDPOINTS = {
    "www": {
        "domain": "www.limbuscompanyapi.com",
        "probe_url": "https://www.limbuscompanyapi.com/"
    },
    "notice": {
        "domain": "notice.limbuscompanyapi.com",
        "probe_url": "https://notice.limbuscompanyapi.com/"
    }
}

# 常用 CloudFront IP 段（当 DNS 失败时作为备选）
CFRONT_IP_RANGES = [
    "13.32.0.0/15",    # Amazon CloudFront
    "13.224.0.0/14",   # Amazon CloudFront
    "13.249.0.0/16",   # Amazon CloudFront
    "18.64.0.0/14",    # Amazon CloudFront
    "18.244.0.0/15",   # Amazon CloudFront
    "52.84.0.0/15",    # Amazon CloudFront
    "52.222.128.0/17", # Amazon CloudFront
    "54.182.0.0/16",   # Amazon CloudFront
    "54.192.0.0/16",   # Amazon CloudFront
    "54.230.0.0/16",   # Amazon CloudFront
    "54.233.0.0/16",   # Amazon CloudFront
    "54.239.128.0/18", # Amazon CloudFront
    "54.240.128.0/18", # Amazon CloudFront
    "64.252.64.0/18",  # Amazon CloudFront
    "99.84.0.0/16",    # Amazon CloudFront
    "99.86.0.0/16",    # Amazon CloudFront
    "130.176.0.0/16",  # Amazon CloudFront
    "143.204.0.0/16",  # Amazon CloudFront
    "204.246.164.0/22",# Amazon CloudFront
    "204.246.168.0/22",# Amazon CloudFront
    "204.246.172.0/24",# Amazon CloudFront
    "204.246.173.0/24",# Amazon CloudFront
    "204.246.174.0/23",# Amazon CloudFront
    "204.246.176.0/20",# Amazon CloudFront
    "205.251.200.0/21",# Amazon CloudFront
    "205.251.208.0/20",# Amazon CloudFront
    "205.251.249.0/24",# Amazon CloudFront
    "205.251.250.0/23",# Amazon CloudFront
    "205.251.252.0/23",# Amazon CloudFront
    "205.251.254.0/24",# Amazon CloudFront
    "216.137.32.0/19", # Amazon CloudFront
    "223.71.71.128/25",# Amazon CloudFront China
    "223.71.71.96/27", # Amazon CloudFront China
]

# DoH 配置
DOH_SERVERS = [
    {"name": "阿里 DoH", "url": "https://dns.alidns.com/resolve"},
    {"name": "DNSPod DoH", "url": "https://doh.pub/dns-query"},
    {"name": "360 DoH", "url": "https://doh.360.cn/dns-query"},
]

# Hosts 标记
HOSTS_MARKERS = {
    "cf": ("# START-OF-LLC-BABEL-CF", "# END-OF-LLC-BABEL-CF"),
    "amazon": ("# START-OF-LLC-BABEL-AMAZON", "# END-OF-LLC-BABEL-AMAZON")
}


# ============== 数据类 ==============
@dataclass
class CfstResult:
    """CloudflareSpeedTest 结果"""
    ip: str
    avg_latency_ms: float
    download_mbps: float
    loss_rate: float


@dataclass
class ProbeResult:
    """CloudFront 探针结果"""
    ip: str
    success: bool
    latency_ms: float
    status_code: Optional[int] = None
    error: Optional[str] = None


@dataclass
class CloudFrontSelection:
    """CloudFront 优选结果"""
    domain: str
    ip: str
    median_latency_ms: float
    worst_latency_ms: float
    success_count: int


@dataclass
class OptimizationResult:
    """整体优化结果"""
    cf_result: Optional[CfstResult] = None
    cfront_results: Dict[str, CloudFrontSelection] = field(default_factory=dict)
    logs: List[str] = field(default_factory=list)


# ============== 工具函数 ==============
def log_message(message: str, logs: List[str], callback: Optional[Callable[[str], None]] = None):
    """记录日志"""
    timestamp = datetime.now().strftime("%H:%M:%S")
    full_message = f"[{timestamp}] {message}"
    logs.append(full_message)
    print(full_message)
    if callback:
        callback(full_message)


def get_hosts_path() -> Path:
    """获取系统 hosts 文件路径"""
    if platform.system() == "Windows":
        return Path(os.environ.get("SystemRoot", "C:\\Windows")) / "System32" / "drivers" / "etc" / "hosts"
    else:
        return Path("/etc/hosts")


def get_backup_path(hosts_path: Path) -> Path:
    """获取备份文件路径"""
    return hosts_path.parent / "hosts.llcbabel.bak"


# ============== CloudflareSpeedTest 封装 ==============
class CfstRunner:
    """CloudflareSpeedTest 运行器"""

    def __init__(self, cfst_dir: Optional[Path] = None):
        self.cfst_dir = cfst_dir or CFST_DIR
        self.cfst_exe = self.cfst_dir / "cfst.exe"
        self.test_urls = CF_TEST_URLS
        self.current_url_index = 0

    @property
    def test_url(self) -> str:
        """获取当前测速 URL"""
        return self.test_urls[self.current_url_index]

    def next_test_url(self) -> bool:
        """切换到下一个测速 URL"""
        if self.current_url_index < len(self.test_urls) - 1:
            self.current_url_index += 1
            print(f"[信息] 切换到备选测速 URL: {self.test_url}")
            return True
        return False

    def ensure_cfst(self) -> bool:
        """确保 CFST 工具存在"""
        if not self.cfst_exe.exists():
            # 尝试下载或提示用户
            print(f"[警告] 未找到 cfst.exe: {self.cfst_exe}")
            print("[提示] 请从 https://github.com/XIU2/CloudflareSpeedTest 下载并放置到 CFST 目录")
            return False

        # 确保 IP 文件存在
        if not CF_IP_FILE.exists():
            # 创建默认 IP 列表
            self._create_default_ip_list()

        return True

    def _create_default_ip_list(self, ultra_fast: bool = False):
        """创建默认 Cloudflare IP 列表（精简版，加速扫描）

        Args:
            ultra_fast: 使用超小 IP 段列表（用于快速测试）
        """
        if ultra_fast:
            # 超小列表：只测试最常用的几个 IP 段
            default_ips = """104.16.0.0/13
104.24.0.0/14
172.64.0.0/13"""
        else:
            # 精选响应较快的 IP 段
            default_ips = """104.16.0.0/13
104.24.0.0/14
172.64.0.0/13
162.158.0.0/15
198.41.128.0/17
173.245.48.0/20
141.101.64.0/18
108.162.192.0/18
190.93.240.0/20
188.114.96.0/20"""

        self.cfst_dir.mkdir(parents=True, exist_ok=True)
        with open(CF_IP_FILE, "w", encoding="utf-8") as f:
            f.write(default_ips)
        print(f"[信息] 已创建默认 IP 列表 ({'超小' if ultra_fast else '精简'}): {CF_IP_FILE}")

    def build_arguments(self, out_file: Path, quick_mode: bool = False) -> List[str]:
        """构建 CFST 参数

        Args:
            quick_mode: 快速模式，减少测试节点和时间
        """
        if quick_mode:
            # 快速模式：只测延迟，不测下载
            return [
                "-f", str(CF_IP_FILE),
                "-t", "1",           # 延迟测速次数
                "-dn", "0",          # 不测试下载速度
                "-p", "1",           # 显示进度（让用户知道还在运行）
                "-o", str(out_file)
            ]
        else:
            return [
                "-f", str(CF_IP_FILE),
                "-url", self.test_url,
                "-t", "2",           # 延迟测速次数
                "-dn", "10",         # 下载测速节点数（减少以加快速度）
                "-dt", "3",          # 下载测速时间（缩短）
                "-p", "1",           # 显示进度
                "-o", str(out_file)
            ]

    def parse_result(self, result_file: Path) -> Optional[CfstResult]:
        """解析 CFST 结果文件"""
        if not result_file.exists():
            return None

        try:
            with open(result_file, "r", encoding="utf-8") as f:
                reader = csv.reader(f)
                header = next(reader, None)  # 跳过表头

                for row in reader:
                    if len(row) >= 6:
                        return CfstResult(
                            ip=row[0],
                            avg_latency_ms=float(row[1]),
                            download_mbps=float(row[2]),
                            loss_rate=float(row[5])
                        )
        except Exception as e:
            print(f"[错误] 解析结果文件失败: {e}")

        return None

    async def run_async(
        self,
        log_callback: Optional[Callable[[str], None]] = None,
        progress_callback: Optional[Callable[[int, int], None]] = None,
        quick_mode: bool = False,
        ultra_fast: bool = False,
        timeout: float = 120.0
    ) -> Optional[CfstResult]:
        """异步运行 CFST

        Args:
            quick_mode: 快速模式，只测延迟
            ultra_fast: 使用超小 IP 列表（更快完成）
            timeout: 超时时间（秒）
        """
        if not self.ensure_cfst():
            return None

        # 确保 IP 文件存在
        if not CF_IP_FILE.exists():
            self._create_default_ip_list(ultra_fast=ultra_fast)

        out_file = self.cfst_dir / "result_cf.csv"

        # 尝试多个测速 URL
        max_attempts = len(self.test_urls)
        for attempt in range(max_attempts):
            result = await self._run_single_with_timeout(
                out_file, log_callback, progress_callback, quick_mode, timeout
            )
            if result:
                # 快速模式只测延迟，不检查下载速度
                if quick_mode or result.download_mbps > 0.1:
                    return result

            # 尝试下一个 URL
            if attempt < max_attempts - 1:
                if not self.next_test_url():
                    break
                print(f"[警告] 测速结果异常，尝试下一个 URL...")

        return result if 'result' in locals() else None

    async def _run_single_with_timeout(
        self,
        out_file: Path,
        log_callback: Optional[Callable[[str], None]],
        progress_callback: Optional[Callable[[int, int]], None],
        quick_mode: bool,
        timeout: float
    ) -> Optional[CfstResult]:
        """带超时的单次运行"""
        try:
            return await asyncio.wait_for(
                self._run_single(out_file, log_callback, progress_callback, quick_mode),
                timeout=timeout
            )
        except asyncio.TimeoutError:
            print(f"[错误] CFST 运行超时（{timeout}秒）")
            return None

    async def _run_single(
        self,
        out_file: Path,
        log_callback: Optional[Callable[[str], None]],
        progress_callback: Optional[Callable[[int, int]], None], # type: ignore
        quick_mode: bool
    ) -> Optional[CfstResult]:
        """单次运行 CFST"""
        # 删除旧结果
        if out_file.exists():
            out_file.unlink()

        args = self.build_arguments(out_file, quick_mode)
        cmd = [str(self.cfst_exe)] + args

        print(f"[信息] 启动 CloudflareSpeedTest...")
        print(f"[URL] {self.test_url}")
        print(f"[命令] {' '.join(cmd)}")

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=str(self.cfst_dir),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            # 实时读取输出
            while True:
                line = await process.stdout.readline() # type: ignore
                if not line:
                    break

                decoded = line.decode("utf-8", errors="ignore").strip()
                if decoded:
                    if log_callback:
                        log_callback(decoded)

                    # 解析进度
                    match = re.search(r'(\d+)\s*/\s*(\d+)', decoded)
                    if match and progress_callback:
                        current, total = int(match.group(1)), int(match.group(2))
                        progress_callback(current, total)

            await process.wait()

            if process.returncode != 0:
                stderr = await process.stderr.read() # type: ignore
                print(f"[错误] CFST 进程失败: {stderr.decode('utf-8', errors='ignore')}")
                return None

            return self.parse_result(out_file)

        except Exception as e:
            print(f"[错误] 运行 CFST 失败: {e}")
            return None


def ip_range_to_ips(ip_range: str, max_per_range: int = 5) -> List[str]:
    """将 IP 段转换为具体 IP 列表（随机采样）"""
    import random
    try:
        import ipaddress
        network = ipaddress.ip_network(ip_range, strict=False)
        hosts = list(network.hosts())
        if len(hosts) > max_per_range:
            # 随机采样
            sampled = random.sample(hosts, max_per_range)
        else:
            sampled = hosts
        return [str(ip) for ip in sampled]
    except Exception:
        return []


def generate_cfront_fallback_ips(max_total: int = 50) -> List[str]:
    """生成 CloudFront 备选 IP 列表"""
    import random
    all_ips = []
    for ip_range in CFRONT_IP_RANGES:
        ips = ip_range_to_ips(ip_range, max_per_range=3)
        all_ips.extend(ips)

    # 随机打乱并限制数量
    random.shuffle(all_ips)
    return all_ips[:max_total]


# ============== DNS 解析 ==============
class DnsResolver:
    """DNS 解析器"""

    @staticmethod
    async def resolve_system(domain: str, timeout: float = 3.0) -> List[str]:
        """使用系统 DNS 解析"""
        try:
            loop = asyncio.get_event_loop()
            result = await asyncio.wait_for(
                loop.run_in_executor(None, socket.getaddrinfo, domain, None, socket.AF_INET),
                timeout=timeout
            )
            ips = set()
            for item in result:
                ip = item[4][0]
                ips.add(ip)
            return list(ips)
        except Exception as e:
            print(f"[DNS] 系统 DNS 解析失败: {e}")
            return []

    @staticmethod
    async def resolve_doh(name: str, domain: str, url: str, timeout: float = 3.0) -> List[str]:
        """使用 DoH 解析"""
        try:
            query_url = f"{url}?name={domain}&type=A"

            ssl_context = ssl.create_default_context()
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE

            req = urllib.request.Request(
                query_url,
                headers={
                    "Accept": "application/dns-json",
                    "User-Agent": "LLC-BABEL-Python/1.0"
                }
            )

            loop = asyncio.get_event_loop()
            response = await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    lambda: urllib.request.urlopen(req, context=ssl_context, timeout=timeout)
                ),
                timeout=timeout
            )

            data = json.loads(response.read().decode("utf-8"))

            ips = []
            if "Answer" in data:
                for answer in data["Answer"]:
                    if answer.get("type") == 1:  # A record
                        ips.append(answer["data"])

            return ips

        except Exception as e:
            print(f"[DNS] {name} 解析失败: {e}")
            return []

    @staticmethod
    async def get_candidates(domain: str, max_candidates: int = 24, use_fallback: bool = True) -> List[str]:
        """从多个源获取候选 IP"""
        all_ips: Set[str] = set()

        # 系统 DNS
        ips = await DnsResolver.resolve_system(domain)
        print(f"[DNS] 系统 DNS 返回 {len(ips)} 个 IP")
        all_ips.update(ips)

        # DoH 服务器
        for server in DOH_SERVERS:
            ips = await DnsResolver.resolve_doh(server["name"], domain, server["url"])
            print(f"[DNS] {server['name']} 返回 {len(ips)} 个 IP")
            all_ips.update(ips)

        # 如果 DNS 都失败了，使用备选 IP
        if not all_ips and use_fallback:
            print("[警告] DNS 解析全部失败，使用内置 CloudFront IP 段作为备选...")
            fallback_ips = generate_cfront_fallback_ips(max_total=max_candidates)
            print(f"[备选] 从 {len(CFRONT_IP_RANGES)} 个 IP 段生成 {len(fallback_ips)} 个候选 IP")
            all_ips.update(fallback_ips)

        return list(all_ips)[:max_candidates]


# ============== CloudFront 探针 ==============
class CloudFrontProbe:
    """CloudFront HTTPS 探针"""

    def __init__(self, timeout: float = 4.0):
        self.timeout = timeout

    async def probe(self, domain: str, ip: str, probe_url: str) -> ProbeResult:
        """探测单个 IP"""
        start_time = time.time()

        try:
            # 创建 SSL 上下文，保持 SNI 正确
            ssl_context = ssl.create_default_context()
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE

            # 构建请求，使用 IP 连接但保持 Host 头
            parsed = urllib.parse.urlparse(probe_url) # type: ignore
            port = parsed.port or 443

            # 创建连接
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(ip, port, ssl=ssl_context),
                timeout=self.timeout
            )

            # 发送 HTTP 请求
            request = (
                f"GET {parsed.path or '/'} HTTP/1.1\r\n"
                f"Host: {domain}\r\n"
                f"User-Agent: LLC-BABEL-Python/1.0\r\n"
                f"Accept: */*\r\n"
                f"Connection: close\r\n\r\n"
            )

            writer.write(request.encode())
            await writer.drain()

            # 读取响应
            response_data = b""
            while True:
                try:
                    chunk = await asyncio.wait_for(reader.read(4096), timeout=2.0)
                    if not chunk:
                        break
                    response_data += chunk
                except asyncio.TimeoutError:
                    break

            writer.close()
            await writer.wait_closed()

            elapsed_ms = (time.time() - start_time) * 1000

            # 解析响应
            response_text = response_data.decode("utf-8", errors="ignore")
            status_match = re.search(r'HTTP/\d\.\d\s+(\d+)', response_text)
            status_code = int(status_match.group(1)) if status_match else 0

            # 检查是否成功
            success = 200 <= status_code < 400

            return ProbeResult(
                ip=ip,
                success=success,
                latency_ms=elapsed_ms,
                status_code=status_code,
                error=None if success else f"HTTP {status_code}"
            )

        except asyncio.TimeoutError:
            return ProbeResult(
                ip=ip,
                success=False,
                latency_ms=(time.time() - start_time) * 1000,
                error="Timeout"
            )
        except Exception as e:
            return ProbeResult(
                ip=ip,
                success=False,
                latency_ms=(time.time() - start_time) * 1000,
                error=str(e)
            )


# ============== CloudFront 优选器 ==============
class CloudFrontOptimizer:
    """CloudFront 端点优选器"""

    def __init__(
        self,
        max_concurrency: int = 6,
        finalist_count: int = 5,
        final_attempts: int = 3
    ):
        self.probe = CloudFrontProbe()
        self.max_concurrency = max_concurrency
        self.finalist_count = finalist_count
        self.final_attempts = final_attempts
        self._semaphore: Optional[asyncio.Semaphore] = None

    def _get_semaphore(self) -> asyncio.Semaphore:
        """获取或创建信号量（延迟初始化以避免事件循环绑定问题）"""
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(self.max_concurrency)
        return self._semaphore

    async def _probe_with_limit(self, domain: str, ip: str, probe_url: str) -> ProbeResult:
        """带并发限制的探针"""
        async with self._get_semaphore():
            return await self.probe.probe(domain, ip, probe_url)

    async def optimize_endpoint(
        self,
        name: str,
        domain: str,
        probe_url: str,
        progress_callback: Optional[Callable[[str, int, int], None]] = None
    ) -> Optional[CloudFrontSelection]:
        """优化单个端点"""
        print(f"\n[CloudFront] 开始优化 {domain}...")

        # 获取候选 IP
        candidates = await DnsResolver.get_candidates(domain)
        if not candidates:
            print(f"[错误] 无法获取 {domain} 的候选 IP")
            return None

        print(f"[信息] 共 {len(candidates)} 个候选 IP")

        # 阶段 1: 资格赛 - 单次探针
        print(f"[阶段 1] 资格赛 - 测试所有候选 IP...")
        qualification_tasks = [
            self._probe_with_limit(domain, ip, probe_url)
            for ip in candidates
        ]

        qualification_results = []
        for i, task in enumerate(asyncio.as_completed(qualification_tasks)):
            result = await task
            if result.success:
                qualification_results.append(result)

            if progress_callback:
                progress_callback(domain, i + 1, len(candidates))

        if not qualification_results:
            print(f"[错误] 没有 IP 通过资格赛")
            print(f"[提示] 可能的原因：")
            print(f"  1. 网络连接不稳定或防火墙阻止了连接")
            print(f"  2. CloudFront IP 段已被封锁或无法访问")
            print(f"  3. 该域名在当前网络环境下无法访问")
            print(f"[建议] 可以尝试使用 VPN 或代理，或稍后再试")
            return None

        # 按延迟排序，选择前 N 个进入决赛
        qualification_results.sort(key=lambda x: x.latency_ms)
        finalists = qualification_results[:self.finalist_count]

        print(f"[信息] {len(finalists)} 个 IP 进入决赛")
        for r in finalists:
            print(f"  - {r.ip}: {r.latency_ms:.1f}ms")

        # 阶段 2: 决赛 - 多次探针
        print(f"[阶段 2] 决赛 - 对入围 IP 进行 {self.final_attempts} 次测试...")

        final_results = []
        for candidate in finalists:
            latencies = []
            success_count = 0

            for attempt in range(self.final_attempts):
                result = await self.probe.probe(domain, candidate.ip, probe_url)
                if result.success:
                    latencies.append(result.latency_ms)
                    success_count += 1

            if success_count >= 2 and latencies:
                latencies.sort()
                median = latencies[len(latencies) // 2]
                worst = max(latencies)

                final_results.append(CloudFrontSelection(
                    domain=domain,
                    ip=candidate.ip,
                    median_latency_ms=median,
                    worst_latency_ms=worst,
                    success_count=success_count
                ))

        if not final_results:
            print(f"[错误] 没有 IP 通过决赛")
            return None

        # 选择最优
        final_results.sort(key=lambda x: x.median_latency_ms)
        best = final_results[0]

        print(f"[结果] 最优 IP: {best.ip}")
        print(f"       中位延迟: {best.median_latency_ms:.1f}ms")
        print(f"       最差延迟: {best.worst_latency_ms:.1f}ms")
        print(f"       成功次数: {best.success_count}/{self.final_attempts}")

        return best

    async def optimize_all(
        self,
        progress_callback: Optional[Callable[[str, int, int], None]] = None
    ) -> Dict[str, CloudFrontSelection]:
        """优化所有端点"""
        results = {}

        for name, config in CFRONT_ENDPOINTS.items():
            result = await self.optimize_endpoint(
                name,
                config["domain"],
                config["probe_url"],
                progress_callback
            )
            if result:
                results[name] = result

        return results


# ============== Hosts 文件管理 ==============
class HostsManager:
    """Hosts 文件管理器"""

    def __init__(self, hosts_path: Optional[Path] = None):
        self.hosts_path = hosts_path or get_hosts_path()
        self.backup_path = get_backup_path(self.hosts_path)

    def read_hosts(self) -> List[str]:
        """读取 hosts 文件"""
        if not self.hosts_path.exists():
            return []

        try:
            with open(self.hosts_path, "r", encoding="utf-8") as f:
                return f.read().splitlines()
        except Exception as e:
            print(f"[错误] 读取 hosts 失败: {e}")
            return []

    def extract_managed_block(self, lines: List[str], marker_start: str, marker_end: str) -> Tuple[int, int]:
        """提取受管块的位置"""
        start_idx = -1
        end_idx = -1

        for i, line in enumerate(lines):
            if marker_start in line:
                start_idx = i
            elif marker_end in line:
                end_idx = i
                break

        return start_idx, end_idx

    def update_managed_block(
        self,
        lines: List[str],
        marker_start: str,
        marker_end: str,
        entries: List[str]
    ) -> List[str]:
        """更新受管块"""
        start_idx, end_idx = self.extract_managed_block(lines, marker_start, marker_end)

        new_block = [marker_start]
        if entries:
            new_block.extend(entries)
        new_block.append(marker_end)

        if start_idx >= 0 and end_idx >= 0:
            # 替换现有块
            return lines[:start_idx] + new_block + lines[end_idx + 1:]
        else:
            # 添加新块
            return lines + [""] + new_block

    def create_backup(self) -> bool:
        """创建备份"""
        try:
            if self.hosts_path.exists():
                shutil.copy2(self.hosts_path, self.backup_path)
                print(f"[信息] 已创建备份: {self.backup_path}")
                return True
        except Exception as e:
            print(f"[错误] 创建备份失败: {e}")
        return False

    def write_hosts(
        self,
        cf_ip: Optional[str] = None,
        cfront_results: Optional[Dict[str, CloudFrontSelection]] = None
    ) -> bool:
        """写入 hosts 文件"""
        # 创建备份
        if not self.create_backup():
            print("[警告] 无法创建备份，继续写入...")

        # 读取现有内容
        lines = self.read_hosts()

        # 准备 Cloudflare 条目
        cf_entries = []
        if cf_ip:
            for domain in CF_DOMAINS:
                cf_entries.append(f"{cf_ip} {domain}")

        # 准备 CloudFront 条目
        cfront_entries = []
        if cfront_results:
            for name, result in cfront_results.items():
                cfront_entries.append(f"{result.ip} {result.domain}")

        # 更新块
        lines = self.update_managed_block(
            lines,
            HOSTS_MARKERS["cf"][0],
            HOSTS_MARKERS["cf"][1],
            cf_entries
        )

        lines = self.update_managed_block(
            lines,
            HOSTS_MARKERS["amazon"][0],
            HOSTS_MARKERS["amazon"][1],
            cfront_entries
        )

        # 写入文件
        try:
            with open(self.hosts_path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")
            print(f"[成功] 已更新 hosts 文件: {self.hosts_path}")
            return True
        except PermissionError:
            print(f"[错误] 权限不足，无法写入 hosts 文件")
            print(f"[提示] 请以管理员身份运行此程序")
            return False
        except Exception as e:
            print(f"[错误] 写入 hosts 失败: {e}")
            return False

    def restore_backup(self) -> bool:
        """从备份还原"""
        try:
            if not self.backup_path.exists():
                print(f"[错误] 备份文件不存在: {self.backup_path}")
                return False

            shutil.copy2(self.backup_path, self.hosts_path)
            print(f"[成功] 已从备份还原 hosts 文件")
            return True
        except Exception as e:
            print(f"[错误] 还原备份失败: {e}")
            return False

    def show_current(self):
        """显示当前受管条目"""
        lines = self.read_hosts()

        print("\n" + "=" * 50)
        print("当前 Hosts 受管条目:")
        print("=" * 50)

        in_cf_block = False
        in_amazon_block = False

        for line in lines:
            if HOSTS_MARKERS["cf"][0] in line:
                in_cf_block = True
                print("\n[Cloudflare CDN]")
                continue
            elif HOSTS_MARKERS["cf"][1] in line:
                in_cf_block = False
                continue
            elif HOSTS_MARKERS["amazon"][0] in line:
                in_amazon_block = True
                print("\n[CloudFront API]")
                continue
            elif HOSTS_MARKERS["amazon"][1] in line:
                in_amazon_block = False
                continue

            if (in_cf_block or in_amazon_block) and line.strip():
                print(f"  {line}")

        print("=" * 50)


# ============== 主程序 ==============
class BabelOptimizer:
    """LLC BABEL 优化器主类"""

    def __init__(self):
        self.cf_runner = CfstRunner()
        self.cfront_optimizer = CloudFrontOptimizer()
        self.hosts_manager = HostsManager()
        self.result = OptimizationResult()

    async def run_full_optimization(self, quick_mode: bool = False) -> OptimizationResult:
        """运行完整优化

        Args:
            quick_mode: 快速模式，只测延迟不测下载速度
        """
        print("=" * 60)
        print("LLC BABEL Python 复刻 - 网络连接优选工具")
        if quick_mode:
            print("[快速模式] 仅测试延迟，不测试下载速度")
        print("=" * 60)

        # 1. Cloudflare 测速
        print("\n" + "-" * 60)
        print("[阶段 1/2] Cloudflare CDN 优选")
        if quick_mode:
            print("[快速模式] 仅测试延迟...")
        print("-" * 60)

        cf_result = await self.cf_runner.run_async(quick_mode=quick_mode)
        if cf_result:
            self.result.cf_result = cf_result
            print(f"\n[Cloudflare 结果]")
            print(f"  最优 IP: {cf_result.ip}")
            print(f"  平均延迟: {cf_result.avg_latency_ms:.2f} ms")
            if quick_mode:
                print(f"  [快速模式] 下载速度未测试")
            else:
                print(f"  下载速度: {cf_result.download_mbps:.2f} Mbps")
            print(f"  丢包率: {cf_result.loss_rate * 100:.2f}%")
        else:
            print("[警告] Cloudflare 测速失败")

        # 2. CloudFront 优选
        print("\n" + "-" * 60)
        print("[阶段 2/2] CloudFront API 优选")
        print("-" * 60)

        cfront_results = await self.cfront_optimizer.optimize_all()
        self.result.cfront_results = cfront_results

        # 显示结果
        print("\n" + "=" * 60)
        print("优化结果汇总")
        print("=" * 60)

        if self.result.cf_result:
            print(f"\n[Cloudflare CDN]")
            print(f"  IP: {self.result.cf_result.ip}")
            print(f"  速度: {self.result.cf_result.download_mbps:.2f} Mbps")

        if self.result.cfront_results:
            print(f"\n[CloudFront API]")
            for name, result in self.result.cfront_results.items():
                print(f"  {result.domain}")
                print(f"    IP: {result.ip}")
                print(f"    延迟: {result.median_latency_ms:.1f}ms (worst: {result.worst_latency_ms:.1f}ms)")

        return self.result


def interactive_menu():
    """交互式菜单"""
    optimizer = BabelOptimizer()

    while True:
        print("\n" + "=" * 50)
        print("LLC BABEL Python 复刻")
        print("=" * 50)
        print("1. 开始完整优化")
        print("2. 快速优化 (仅延迟测试)")
        print("3. 仅优化 Cloudflare CDN")
        print("4. 仅优化 CloudFront API")
        print("5. 查看当前 hosts 配置")
        print("6. 应用优化结果到 hosts")
        print("7. 还原 hosts 备份")
        print("0. 退出")
        print("-" * 50)

        choice = input("请选择操作: ").strip()

        if choice == "1":
            asyncio.run(optimizer.run_full_optimization(quick_mode=False))

        elif choice == "2":
            print("\n[快速优化模式]")
            asyncio.run(optimizer.run_full_optimization(quick_mode=True))

        elif choice == "3":
            print("\n[Cloudflare CDN 优选]")
            print("1. 完整测速（较慢）")
            print("2. 快速模式（仅延迟）")
            print("3. 极速模式（超小IP列表）")
            cf_choice = input("请选择: ").strip()

            if cf_choice == "1":
                result = asyncio.run(optimizer.cf_runner.run_async(quick_mode=False))
            elif cf_choice == "2":
                result = asyncio.run(optimizer.cf_runner.run_async(quick_mode=True))
            elif cf_choice == "3":
                result = asyncio.run(optimizer.cf_runner.run_async(quick_mode=True, ultra_fast=True, timeout=60))
            else:
                print("无效选择")
                continue

            if result:
                optimizer.result.cf_result = result
                print(f"\n最优 IP: {result.ip}")
                print(f"平均延迟: {result.avg_latency_ms:.2f} ms")
                if not (cf_choice == "2" or cf_choice == "3"):
                    print(f"下载速度: {result.download_mbps:.2f} Mbps")

        elif choice == "4":
            print("\n[CloudFront API 优选]")
            results = asyncio.run(optimizer.cfront_optimizer.optimize_all())
            optimizer.result.cfront_results = results

        elif choice == "5":
            optimizer.hosts_manager.show_current()

        elif choice == "6":
            if not optimizer.result.cf_result and not optimizer.result.cfront_results:
                print("[错误] 没有可用的优化结果，请先运行优化")
                continue

            confirm = input("确认写入 hosts 文件? (y/N): ").strip().lower()
            if confirm == "y":
                optimizer.hosts_manager.write_hosts(
                    optimizer.result.cf_result.ip if optimizer.result.cf_result else None,
                    optimizer.result.cfront_results if optimizer.result.cfront_results else None
                )

        elif choice == "7":
            confirm = input("确认还原 hosts 备份? (y/N): ").strip().lower()
            if confirm == "y":
                optimizer.hosts_manager.restore_backup()

        elif choice == "0":
            print("再见!")
            break

        else:
            print("无效选择，请重试")


def main():
    """主入口"""
    parser = argparse.ArgumentParser(
        description="LLC BABEL Python 复刻 - 边狱公司网络连接优选工具"
    )
    parser.add_argument(
        "--optimize", "-o",
        action="store_true",
        help="运行完整优化"
    )
    parser.add_argument(
        "--quick", "-q",
        action="store_true",
        help="快速模式：仅测试延迟，不测试下载速度"
    )
    parser.add_argument(
        "--cf-only",
        action="store_true",
        help="仅优化 Cloudflare"
    )
    parser.add_argument(
        "--cfront-only",
        action="store_true",
        help="仅优化 CloudFront"
    )
    parser.add_argument(
        "--apply", "-a",
        action="store_true",
        help="自动应用结果到 hosts"
    )
    parser.add_argument(
        "--restore", "-r",
        action="store_true",
        help="还原 hosts 备份"
    )
    parser.add_argument(
        "--show",
        action="store_true",
        help="显示当前 hosts 配置"
    )
    parser.add_argument(
        "--interactive", "-i",
        action="store_true",
        help="交互式模式（默认）"
    )

    args = parser.parse_args()

    # 默认进入交互模式
    if len(sys.argv) == 1 or args.interactive:
        interactive_menu()
        return

    optimizer = BabelOptimizer()

    if args.restore:
        optimizer.hosts_manager.restore_backup()
        return

    if args.show:
        optimizer.hosts_manager.show_current()
        return

    if args.optimize:
        result = asyncio.run(optimizer.run_full_optimization(quick_mode=args.quick))

        if args.apply:
            optimizer.hosts_manager.write_hosts(
                result.cf_result.ip if result.cf_result else None,
                result.cfront_results if result.cfront_results else None
            )

    elif args.cf_only:
        result = asyncio.run(optimizer.cf_runner.run_async(quick_mode=args.quick))
        if result and args.apply:
            optimizer.hosts_manager.write_hosts(cf_ip=result.ip)

    elif args.cfront_only:
        results = asyncio.run(optimizer.cfront_optimizer.optimize_all())
        if results and args.apply:
            optimizer.hosts_manager.write_hosts(cfront_results=results)


if __name__ == "__main__":
    main()