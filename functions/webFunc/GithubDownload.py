"""GitHub Release 获取器（薄封装）

统一实现见 functions/base/common/github_release.py。
原双份重复实现（本文件与 functions/web_update/github_utils.py）已合并到集合库。
"""

from functions.base.common.github_release import (
    ReleaseAsset,
    ReleaseInfo,
    ProxyManager,
    GitHubReleaseFetcher,
    RepoBoundGitHubReleaseFetcher,
    print_release_summary,
)


# 全局请求器实例
GithubRequester: GitHubReleaseFetcher = None  # type: ignore

def init_request():
    """初始化全局请求器"""
    global GithubRequester
    GithubRequester = GitHubReleaseFetcher(
        use_proxy=True,
        ignore_ssl=True
        )
    print("GitHub请求器已初始化")


# 使用示例
if __name__ == "__main__":
    init_request()
    
    fetcher = GithubRequester
    
    # 获取不同仓库的最新release信息
    print("=" * 60)
    print("示例1: 获取vscode的最新release")
    print("=" * 60)
    latest_release = fetcher.get_latest_release("microsoft", "vscode")
    if latest_release:
        print_release_summary(latest_release)
        
        # 查找特定文件
        print("\n查找Windows安装包:")
        windows_assets = latest_release.get_assets_by_extension(".exe")
        for asset in windows_assets:
            print(f"  - {asset.name}: {asset.download_url}")

    print("\n" + "=" * 60)
    print("示例2: 获取pytorch的最新预览版release")
    print("=" * 60)
    stable_release = fetcher.get_latest_pre_release("pytorch", "pytorch")
    if stable_release:
        print_release_summary(stable_release)
    
    print("\n" + "=" * 60)
    print("示例3: 使用全局请求器获取numpy的特定版本")
    print("=" * 60)
    if GithubRequester:
        numpy_release = GithubRequester.get_release_by_tag("numpy", "numpy", "v1.24.0")
        if numpy_release:
            print_release_summary(numpy_release)
