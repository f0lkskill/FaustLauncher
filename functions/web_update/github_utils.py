"""GitHub Release 获取器（薄封装）

统一实现见 functions/base/common/github_release.py。
原双份重复实现（本文件与 functions/webFunc/GithubDownload.py）已合并到集合库。
"""

from functions.base.common.github_release import (
    ReleaseAsset,
    ReleaseInfo,
    ProxyManager,
    RepoBoundGitHubReleaseFetcher as GitHubReleaseFetcher,
    print_release_summary,
)


# 使用示例
if __name__ == "__main__":
    # 创建获取器实例
    fetcher = GitHubReleaseFetcher(
        repo_owner="LocalizeLimbusCompany",
        repo_name="LocalizeLimbusCompany",
        use_proxy=True,
        proxy_url="https://gh-proxy.org/"
    )
    
    # 获取最新release信息
    latest_release = fetcher.get_latest_release()
    
    if latest_release:
        print("=" * 60)
        print_release_summary(latest_release)
        print("=" * 60)
        
        # 获取简化信息（兼容旧API）
        simple_info:dict = fetcher.get_simple_release_info()  # type: ignore
        print("\n简化信息格式:")
        print(f"仓库: {simple_info['repo']}")
        print(f"版本: {simple_info['tag_name']}")
        print(f"资源文件数: {simple_info['total_assets']}")
        
        # 查找特定文件
        print("\n查找Windows安装包:")
        windows_assets = latest_release.get_assets_by_extension(".7z")
        for asset in windows_assets:
            print(f"  - {asset.name}: {asset.download_url}")
