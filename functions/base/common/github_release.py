"""GitHub Releases 查询客户端与数据结构。

直接请求 GitHub API 在国内经常不通，这里用一组 gh-proxy 加速地址并发尝试，
取第一个成功响应的代理并记录为优先项；也可关掉代理直连。对外提供最新
release、预发布、按 tag 查询和分页列表，并把 API JSON 转成
:class:`ReleaseInfo` / :class:`ReleaseAsset` 供上层取下载地址。
"""

import requests
import warnings
from typing import Optional, List, Dict, Any
from dataclasses import dataclass
from copy import deepcopy
from contextlib import contextmanager, suppress
from concurrent.futures import ThreadPoolExecutor, as_completed

@dataclass
class ReleaseAsset:
    """发布资源：文件名、大小、下载地址与所属代理管理器。"""
    name: str
    size: int
    download_url: str
    content_type: str
    download_count: int
    proxys: 'ProxyManager'
    
    @property
    def formatted_size(self) -> str:
        """把字节数格式化成 ``B/KB/MB/GB/TB`` 的可读字符串。"""
        if self.size == 0:
            return "0 B"
        
        size_names = ["B", "KB", "MB", "GB", "TB"]
        size_bytes = self.size
        i = 0
        while size_bytes >= 1024 and i < len(size_names) - 1:
            size_bytes /= 1024
            i += 1
        return f"{size_bytes:.2f} {size_names[i]}"

@dataclass
class ReleaseInfo:
    """一次 release 的结构化信息及其资源列表。"""
    repo_owner: str
    repo_name: str
    tag_name: str
    name: str
    body: str
    published_at: str
    prerelease: bool
    draft: bool
    assets: List[ReleaseAsset]
    proxys: 'ProxyManager'
    
    def get_asset_by_name(self, name: str) -> Optional[ReleaseAsset]:
        """按文件名精确查找发布资源，找不到返回 None。"""
        for asset in self.assets:
            if asset.name == name:
                return asset
        return None
    
    def get_assets_by_extension(self, extension: str) -> List[ReleaseAsset]:
        """返回文件名以 extension 结尾的所有发布资源。"""
        return [asset for asset in self.assets if asset.name.endswith(extension)]
    
    @property
    def source_zip_url(self) -> str:
        """该 tag 的源码 ZIP 下载地址。"""
        return f"https://github.com/{self.repo_owner}/{self.repo_name}/archive/refs/tags/{self.tag_name}.zip"
    
    @property
    def source_tar_url(self) -> str:
        """该 tag 的源码 tar.gz 下载地址。"""
        return f"https://github.com/{self.repo_owner}/{self.repo_name}/archive/refs/tags/{self.tag_name}.tar.gz"

class ProxyManager:
    
    """GitHub 加速代理列表与当前优先代理。"""
    def __init__(self):
        """初始化代理列表；直接请求模式不创建代理管理器。"""
        self.proxies: List[str] = []
        self.current_index: int = 0
        self.last_successful_proxy: Optional[str] = None
        self._initialize_proxies()
    
    def _initialize_proxies(self):
        """先放默认 gh-proxy，再尝试从 API 拉取更多可用代理。"""
        self.proxies.append("https://gh-proxy.org/")
        
        try:
            self._fetch_proxies_from_api()
        except Exception as e:
            print(f"从API获取代理列表失败，使用默认代理: {e}")
    
    def _fetch_proxies_from_api(self):
        """从 api.akams.cn 拉取代理节点，过滤 HTTPS 并去重。"""
        api_url = "https://api.akams.cn/github"
        try:
            response = requests.get(api_url, timeout=5)
            response.raise_for_status()
            data = response.json()
            
            if data.get("code") == 200:
                nodes_data = data.get("data", [])
                new_proxies = []
                
                for node_data in nodes_data:
                    url = node_data.get("url", "").rstrip('/') + '/'
                    if url.startswith("https://") and "gh-proxy.org" not in url:
                        new_proxies.append(url)
                
                if new_proxies:
                    self.proxies.extend(new_proxies)
                    print(f"成功加载 {len(new_proxies)} 个代理")
                    
        except Exception as e:
            print(f"获取代理列表失败: {e}")
    
    def set_proxy_by_url(self, proxy_url: str):
        """把某个代理设为当前优先项；不在列表里返回 False。"""
        if proxy_url in self.proxies:
            self.current_index = self.proxies.index(proxy_url)
            self.last_successful_proxy = proxy_url
            return True
        return False
    
    def get_proxies(self) -> List[str]:
        """把代理列表按当前下标轮转，优先尝试最近成功的代理。"""
        result = self.proxies[self.current_index:] + self.proxies[:self.current_index]
        
        return result

class GitHubReleaseFetcher:
    
    """GitHub Releases API 客户端，支持多代理并发回退。"""
    def __init__(self, use_proxy: bool = True, ignore_ssl: bool = False):
        """初始化代理列表；直接请求模式不创建代理管理器。"""
        self.use_proxy = use_proxy
        self.ignore_ssl = ignore_ssl
        
        self.github_api_base = "https://api.github.com"
        
        self.proxy_manager = ProxyManager() if use_proxy else None
        
        self.session = requests.Session()
        self.session.headers.update({
            'Accept': 'application/vnd.github.v3+json',
            'User-Agent': 'GitHub-Release-Fetcher/1.0'
        })
        
        self.max_workers = 3
        self.request_timeout = 8
        
        if self.ignore_ssl:
            self.session.verify = False
            warnings.filterwarnings('ignore', message='Unverified HTTPS request')
    
    def update_config(self, use_proxy: bool = True, ignore_ssl: bool = False):
        """更新是否走代理与是否忽略 SSL 校验。"""
        self.use_proxy = use_proxy
        self.ignore_ssl = ignore_ssl
    
    def _build_api_url(self, repo_owner: str, repo_name: str, endpoint: str, proxy_url: str = "") -> str:
        """拼出 GitHub API 地址；proxy_url 非空时前缀到 URL 前。"""
        api_url = f"{self.github_api_base}/repos/{repo_owner}/{repo_name}/{endpoint}"
        
        if proxy_url:
            api_url = f"{proxy_url}{api_url}"
            
        return api_url
    
    def _request_with_proxy(self, repo_owner: str, repo_name: str, endpoint: str, 
                          proxy_url: str, timeout: float = None) -> Optional[Dict[str, Any]]: # type: ignore
        """经单个代理请求 API，返回 ``(数据, 代理地址)``；失败数据为 None。"""
        if timeout is None:
            timeout = self.request_timeout
            
        api_url = self._build_api_url(repo_owner, repo_name, endpoint, proxy_url)
        
        try:
            response = self.session.get(api_url, timeout=timeout)
            if response.status_code == 200:
                return response.json(), proxy_url # type: ignore
            else:
                print(f"代理 {proxy_url} 返回状态码: {response.status_code}")
                return None, proxy_url # type: ignore
                
        except Exception as e:
            print(f"代理 {proxy_url} 请求失败: {e}")
            return None, proxy_url # type: ignore
    
    def _make_request(self, repo_owner: str, repo_name: str, endpoint: str, **kwargs) -> Optional[Dict[str, Any]]:
        """并发尝试所有代理直到成功；返回 JSON 数据或 None。"""
        if not self.use_proxy or not self.proxy_manager:
            api_url = self._build_api_url(repo_owner, repo_name, endpoint)
            try:
                response = self.session.get(api_url, timeout=30, **kwargs)
                response.raise_for_status()
                return response.json()
            except Exception as e:
                print(f"直接请求失败: {e}")
                return None
        
        proxies = self.proxy_manager.get_proxies()
        
        if not proxies:
            print("没有可用的代理")
            return None
        
        print(f"使用线程池（最大 {self.max_workers} 个线程）尝试 {len(proxies)} 个代理...")
        
        executor = ThreadPoolExecutor(max_workers=self.max_workers)
        
        @contextmanager
        def auto_shutdown_pool():
            """上下文管理器：离开时取消未完成任务并关闭线程池。"""
            yield
            try:
                executor.shutdown(wait=False, cancel_futures=True)
            except:
                for _future in future: # type: ignore
                    with suppress(Exception):
                        if not _future.done():
                            _future.cancel()
                executor.shutdown(wait=False)
        
        with auto_shutdown_pool():
            future_to_proxy = {}
            for proxy_url in proxies:
                future = executor.submit(
                    self._request_with_proxy, 
                    repo_owner, repo_name, endpoint, proxy_url
                )
                future_to_proxy[future] = proxy_url
            
            try:
                for future in as_completed(future_to_proxy):
                    try:
                        data, used_proxy = future.result()
                        
                        if data is not None:
                            self.proxy_manager.set_proxy_by_url(used_proxy)
                            print(f"成功使用代理: {used_proxy}")
                            return data
                            
                    except Exception as e:
                        proxy_url = future_to_proxy[future]
                        print(f"代理 {proxy_url} 任务异常: {e}")
                        
            except TimeoutError:
                print(f"请求超时")
        
        print("所有代理尝试均失败")
        return None    
    def get_latest_release(self, repo_owner: str, repo_name: str) -> Optional[ReleaseInfo]:
        """取仓库最新 release；失败返回 None。"""
        try:
            print(f"正在获取最新release: {repo_owner}/{repo_name}")
            
            data = self._make_request(repo_owner, repo_name, "releases/latest")
            if data is None:
                print("获取release信息失败")
                return None
                
            return self._parse_release_data(repo_owner, repo_name, data)
            
        except Exception as e:
            print(f"获取release信息失败: {e}")
            return None
    
    def get_latest_pre_release(self, repo_owner: str, repo_name: str) -> Optional[ReleaseInfo]:
        """优先取第一页里的预发布版，没有则退回最新版。"""
        try:
            print(f"正在获取第 1 页release列表...")
            params = {"per_page": 30, "page": 1}
            
            data = self._make_request(repo_owner, repo_name, "releases", params=params)
            if data is None or not data:
                print(f"未找到任何release或请求失败")
                return None
            
            for release in data:
                if release.get('prerelease', False) and not release.get('draft', False): # type: ignore
                    print(f"在第 1 页找到预发布版本: {release.get('tag_name')}") # type: ignore
                    return self._parse_release_data(repo_owner, repo_name, release) # type: ignore
            
            print(f"第一页没有找到预发布版本，返回最新版本")
            return self._parse_release_data(repo_owner, repo_name, data[0]) # type: ignore
                
        except Exception as e:
            print(f"获取最新预发布版失败: {e}")
            return None
    
    def get_release_by_tag(self, repo_owner: str, repo_name: str, tag_name: str) -> Optional[ReleaseInfo]:
        """按 tag 取指定 release；失败返回 None。"""
        try:
            print(f"正在获取release: {repo_owner}/{repo_name}@{tag_name}")
            
            data = self._make_request(repo_owner, repo_name, f"releases/tags/{tag_name}")
            if data is None:
                print(f"获取标签 {tag_name} 失败")
                return None
            
            return self._parse_release_data(repo_owner, repo_name, data)
            
        except Exception as e:
            print(f"获取release信息失败: {e}")
            return None
    
    def list_all_releases(self, repo_owner: str, repo_name: str, per_page: int = 30) -> List[ReleaseInfo]:
        """分页列出全部 release；失败时返回已取到的部分。"""
        try:
            print(f"正在列出所有release: {repo_owner}/{repo_name}")
            
            releases = []
            page = 1
            
            while True:
                params = {"per_page": per_page, "page": page}
                
                data = self._make_request(repo_owner, repo_name, "releases", params=params)
                if data is None:
                    break
                    
                if not data:
                    break
                
                for release in data:
                    releases.append(self._parse_release_data(repo_owner, repo_name, release)) # type: ignore
                
                page += 1
                
                if len(data) < per_page:
                    break
            
            return releases
            
        except Exception as e:
            print(f"获取release列表失败: {e}")
            return []
    
    def _parse_release_data(self, repo_owner: str, repo_name: str, release_data: Dict[str, Any]) -> ReleaseInfo:
        """把 GitHub API 的 release JSON 转成 ReleaseInfo/ReleaseAsset。"""
        assets = []
        proxys = deepcopy(self.proxy_manager)
        for asset in release_data.get('assets', []):
            true_download_url = asset['browser_download_url']
            true_download_url = [true_download_url[i:] for i in range(len(true_download_url))
                                 if true_download_url[i:].startswith('https://github.com')]
            if not true_download_url:
                true_download_url = [asset['browser_download_url']]
            true_download_url = true_download_url[0]
            assets.append(ReleaseAsset(
                name=asset['name'],
                size=asset['size'],
                download_url=true_download_url,
                content_type=asset.get('content_type', 'application/octet-stream'),
                download_count=asset.get('download_count', 0),
                proxys=proxys # type: ignore
            ))
        
        return ReleaseInfo(
            repo_owner=repo_owner,
            repo_name=repo_name,
            tag_name=release_data['tag_name'],
            name=release_data.get('name', ''),
            body=release_data.get('body', ''),
            published_at=release_data.get('published_at', ''),
            prerelease=release_data.get('prerelease', False),
            draft=release_data.get('draft', False),
            assets=assets,
            proxys=proxys # type: ignore
        )

class RepoBoundGitHubReleaseFetcher(GitHubReleaseFetcher):

    """绑定固定仓库的便捷封装，调用时不必每次传 owner/name。"""
    def __init__(self, repo_owner: str, repo_name: str,
                 use_proxy: bool = True,
                 proxy_url: str = "https://gh-proxy.org/",
                 ignore_ssl: bool = False):
        """初始化代理列表；直接请求模式不创建代理管理器。"""
        super().__init__(use_proxy=use_proxy, ignore_ssl=ignore_ssl)
        self.repo_owner = repo_owner
        self.repo_name = repo_name
        self.proxy_url = proxy_url.rstrip('/')

    def get_latest_release(self) -> Optional[ReleaseInfo]:
        """取仓库最新 release；失败返回 None。"""
        return super().get_latest_release(self.repo_owner, self.repo_name)

    def get_latest_stable_release(self) -> Optional[ReleaseInfo]:
        """取发布时间最新的非预发布、非草稿版本。"""
        try:
            all_releases = self.list_all_releases()

            if not all_releases:
                print(f"未找到任何release: {self.repo_owner}/{self.repo_name}")
                return None

            stable_releases = [
                release for release in all_releases
                if not release.prerelease and not release.draft
            ]

            if not stable_releases:
                print(f"未找到稳定版release: {self.repo_owner}/{self.repo_name}")
                return None

            stable_releases.sort(
                key=lambda x: x.published_at,
                reverse=True
            )

            latest_stable = stable_releases[0]
            print(f"找到最新稳定版: {latest_stable.tag_name} (发布于: {latest_stable.published_at})")

            return latest_stable

        except Exception as e:
            print(f"获取最新稳定版失败: {e}")
            return None

    def get_release_by_tag(self, tag_name: str) -> Optional[ReleaseInfo]:
        """按 tag 取指定 release；失败返回 None。"""
        return super().get_release_by_tag(self.repo_owner, self.repo_name, tag_name)

    def list_all_releases(self, per_page: int = 30) -> List[ReleaseInfo]:
        """分页列出全部 release；失败时返回已取到的部分。"""
        return super().list_all_releases(self.repo_owner, self.repo_name, per_page)

    def get_simple_release_info(self) -> Optional[Dict[str, Any]]:
        """把 release 压成前端易用的纯字典（含资源与源码地址）。"""
        release_info = self.get_latest_release()
        if not release_info:
            return None

        assets_info = []
        for asset in release_info.assets:
            assets_info.append({
                'name': asset.name,
                'size': asset.size,
                'formatted_size': asset.formatted_size,
                'download_url': asset.download_url,
                'content_type': asset.content_type
            })

        source_urls = {
            "zip": release_info.source_zip_url,
            "tar.gz": release_info.source_tar_url,
        }

        return {
            'repo': f"{self.repo_owner}/{self.repo_name}",
            'tag_name': release_info.tag_name,
            'name': release_info.name,
            'body': release_info.body[:500] + "..." if len(release_info.body) > 500 else release_info.body,
            'published_at': release_info.published_at,
            'prerelease': release_info.prerelease,
            'draft': release_info.draft,
            'assets': assets_info,
            'source_code_urls': source_urls,
            'total_assets': len(release_info.assets)
        }

def print_release_summary(release_info: ReleaseInfo) -> None:
    """把 release 概要打印到终端。"""
    print(f"仓库: {release_info.repo_owner}/{release_info.repo_name}")
    print(f"版本: {release_info.tag_name}")
    print(f"名称: {release_info.name}")
    print(f"发布日期: {release_info.published_at}")
    print(f"预发布: {'是' if release_info.prerelease else '否'}")
    print(f"草稿: {'是' if release_info.draft else '否'}")
    
    if release_info.assets:
        print(f"\n资源文件 ({len(release_info.assets)} 个):")
        for i, asset in enumerate(release_info.assets, 1):
            print(f"  {i:2d}. {asset.name:<40} {asset.formatted_size:>10} (下载: {asset.download_count})")
    else:
        print("\n该release没有额外的资源文件")
    
    print(f"\n源码压缩包:")
    print(f"  ZIP: {release_info.source_zip_url}")
    print(f"  TAR.GZ: {release_info.source_tar_url}")
