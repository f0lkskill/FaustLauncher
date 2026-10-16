# FaustLauncher 被杀软误删 / 误报的排查与处置

面向用户与维护者。你遇到的“启动器 exe 莫名消失”，绝大多数不是启动器自己删的，
而是安全软件把它**静默隔离**了（Windows Defender 历史里通常能查到记录）。

---

## 一、先确认：是不是被杀软拿走了

按顺序做，全程一分钟内：

1. **看 Defender 的隔离历史**（最直接的证据）
   打开「Windows 安全中心」→「病毒和威胁防护」→「保护历史记录」，
   找 `FaustLauncher.exe` 或威胁名（如 `Trojan:Win32/Wacatac.B!ml`）。
   命令行等价做法（管理员 PowerShell）：

   ```powershell
   Get-MpThreatDetection | Select-Object -Last 10 InitialDetectionTime, Resources, ThreatID
   ```

   在结果里搜 `FaustLauncher`；命中即说明是被 Defender 隔离了，
   到「保护历史」里点「还原」并选择「允许在设备上」，exe 就会回到原位。

2. **看安装目录还剩什么**
   如果 `FaustLauncher.exe` 没了、`_internal\` 还在，几乎可以断定是**只删了 exe**
   （杀软按“可执行文件”处理，不会连带删数据目录）。若整个目录都没了就考虑清理软件。

3. **确认不是“在压缩包里运行”**
   直接双击压缩包里的 exe 会先在 `%TEMP%` 下解压再运行，程序目录随临时文件被清理，
   表现为“用了一会儿就没了”。**必须解压到一个固定目录再运行**。

---

## 二、永久放行（推荐给所有用户做一次）

选一种即可，**只放行启动器目录，别放行整个磁盘**。

### 方法 A：Windows 安全中心界面

「病毒和威胁防护」→「管理设置」→「排除项」→「添加或删除排除项」→「添加排除项」→
「文件夹」，选中启动器所在目录（例如 `D:\FaustLauncher`）。

### 方法 B：命令行（管理员 PowerShell，把路径换成你的安装目录）

```powershell
Add-MpPreference -ExclusionPath "D:\FaustLauncher"
```

撤销：

```powershell
Remove-MpPreference -ExclusionPath "D:\FaustLauncher"
```

### 方法 C：第三方杀软（360 / 火绒 / 腾讯电脑管家 等）

把安装目录加入「信任区 / 白名单 / 排除目录」，并关闭对它的「文件监控自动处理」。
360 与腾管还常把 PyInstaller 启动器报成 `HEUR/QVM` 系列启发式误报，加白即可。

---

## 三、维护者侧：把误报概率降下来

三件事按收益排序：

1. **提交误报申诉**（本仓库提供现成材料）
   跑 `python tools/build/report_hash.py` 生成 `defender-appeal.txt`，
   里面已排好应用名、版本、下载链接、SHA256 与用途说明；
   打开 <https://www.microsoft.com/en-us/wdsi/filesubmission> 选
   “Software developer” 提交，通常几天内该哈希会被拉白。
   第三方杀软（360 / 火绒 等）各自也有误报申诉通道，材料可复用同一份。

2. **让 exe 有完整版本资源**（本仓库已做）
   `tools/build/version_info_gen.py` 在打包时自动注入
   `CompanyName / FileDescription / FileVersion / ProductName / OriginalFilename`。
   无版本资源的 exe 在启发式评分里明显更可疑。

3. **代码签名**（成本最高，收益最稳）
   OV 证书可消除“未知发布者”并大幅降低误报；EV 证书可立即获得 SmartScreen 信任。
   在 `tools/build/FaustLauncher.spec` 的 `EXE(...)` 里把 `codesign_identity` 换成证书标识，
   并在打包后对 `FaustLauncher.exe` 执行 `signtool sign /fd sha256 /tr <时间戳服务器> /td sha256`。

---

## 四、附：为什么这个打包产物容易被误报

- PyInstaller 引导器（bootloader）是被大量恶意样本复用的公共外壳，厂商模型对它天然敏感。
- 没有代码签名、没有版本信息（历史上如此）会进一步拉高可疑评分。
- UPX 加壳同样是经典误报诱因（本仓库 spec 里 `upx=True`）。

这些都不是“做错了什么”，而是打包方式的固有代价；上面第三节的三件事就是对应解法。
