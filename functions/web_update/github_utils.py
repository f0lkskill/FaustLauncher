
from functions.base.common.github_release import (
    ReleaseAsset,
    ReleaseInfo,
    ProxyManager,
    RepoBoundGitHubReleaseFetcher as GitHubReleaseFetcher,
    print_release_summary,
)

if __name__ == "__main__":
    fetcher = GitHubReleaseFetcher(
        repo_owner="LocalizeLimbusCompany",
        repo_name="LocalizeLimbusCompany",
        use_proxy=True,
        proxy_url="https://gh-proxy.org/"
    )
    
    latest_release = fetcher.get_latest_release()
    
    if latest_release:
        print("=" * 60)
        print_release_summary(latest_release)
        print("=" * 60)
        
        simple_info:dict = fetcher.get_simple_release_info()  # type: ignore
        print("\n简化信息格式:")
        print(f"仓库: {simple_info['repo']}")
        print(f"版本: {simple_info['tag_name']}")
        print(f"资源文件数: {simple_info['total_assets']}")
        
        print("\n查找Windows安装包:")
        windows_assets = latest_release.get_assets_by_extension(".7z")
        for asset in windows_assets:
            print(f"  - {asset.name}: {asset.download_url}")
