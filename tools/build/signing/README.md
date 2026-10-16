# 代码签名证书（本机私有，不入库）

构建流程在「复制 exe」之后、「压缩 zip」之前调用
[`tools/build/code_sign.py`](../code_sign.py) 给 `build_<版本>/FaustLauncher.exe`
打 Authenticode 签名，保证 zip 里装的是签好的 exe。

```
signing/
├── README.md             ← 本文件（入库）
├── signing.json          ← 配置 + 明文密码（.gitignore，不入库）
├── FaustLauncher.pfx     ← 私钥（.gitignore，不入库）
├── FaustLauncher.cer     ← 公钥证书，用于在别的机器上装信任（不入库）
└── signtool/             ← SDK 里那套 signtool.exe + 依赖 DLL（.gitignore，不入库）
```

> **私钥不进 git。** 上面标了「不入库」的条目都由根目录 `.gitignore` 挡住。
> 换机器 / 重新 clone 后这个目录里只剩 README，构建会自动跳过签名（见下文），
> 需要发签名版时把 pfx 拷回来即可。

## 配置项（signing.json）

| 键 | 默认 | 说明 |
| --- | --- | --- |
| `pfx` | `FaustLauncher.pfx` | 证书路径；相对路径按本目录算 |
| `password` | — | PFX 密码；也可用环境变量 `FAUST_PFX_PASSWORD` 覆盖 |
| `timestamp_url` | `http://timestamp.digicert.com` | 时间戳服务。**建议保留**：加上它，签名在证书过期后仍然有效 |
| `file_digest` / `timestamp_digest` | `sha256` | 对应 signtool 的 `/fd` 与 `/td` |
| `required` | `false`（本机已设为 `true`） | `true` = 签名失败就中止构建；`false` = 只警告、继续打包 |
| `verify` | `false` | `true` = 签完再跑 `signtool verify /pa` 并把结果写进日志 |
| `signtool` | 空 | 留空自动查找；本目录放 `signtool/signtool.exe` 即可 |

环境变量优先级高于 `signing.json`：`FAUST_SIGNTOOL`、`FAUST_PFX`、`FAUST_PFX_PASSWORD`。

## signtool 从哪来

`code_sign.py` 按顺序找：`signing.json` 的 `signtool` → `FAUST_SIGNTOOL` →
`PATH` → 本目录 `signtool/signtool.exe` → `Windows Kits\10\bin\*\x64\` →
NuGet 的 `Microsoft.Windows.SDK.BuildTools` → Visual Studio 自带的 VSI 副本。

本机没有装完整 SDK，用的是 `signing/signtool/` 这份从 SDK 摘出来的副本（3.4 MB）。
想要更正规的装法：

```powershell
winget install Microsoft.WindowsSDK.10.0.26100
# 或
winget install Microsoft.VisualStudio.2022.BuildTools
```

装完之后把 `signing.json` 的 `signtool` 清空、删掉 `signing/signtool/` 也能跑。

## 单独使用

```powershell
# 看当前解析到的证书 / signtool 路径
python tools\build\code_sign.py --show-config

# 手动签一个文件（构建之外的场景）
python tools\build\code_sign.py build_V0.9.2\FaustLauncher.exe

# 校验已有签名
python tools\build\code_sign.py --verify build_V0.9.2\FaustLauncher.exe
```

## 换一张证书（证书过期 / 换机器 / 换成 CA 签发的）

```powershell
# 1) 生成自签名代码签名证书（5 年有效）
$cert = New-SelfSignedCertificate -Type CodeSigningCert `
  -Subject "CN=FaustLauncher, O=FaustLauncher, C=CN" `
  -CertStoreLocation Cert:\CurrentUser\My `
  -KeyUsage DigitalSignature -KeyAlgorithm RSA -KeyLength 3072 `
  -NotAfter (Get-Date).AddYears(5) `
  -TextExtension @("2.5.29.37={text}1.3.6.1.5.5.7.3.3")

# 2) 导出私钥（.pfx）与公钥（.cer），文件名要和 signing.json 对齐
$pwd = ConvertTo-SecureString '换成新密码' -Force -AsPlainText
Export-PfxCertificate -Cert $cert -FilePath tools\build\signing\FaustLauncher.pfx -Password $pwd
Export-Certificate   -Cert $cert -FilePath tools\build\signing\FaustLauncher.cer -Type CERT

# 3) 同 步 signing.json 里的 password
# 4) 让本机信任它，否则 signtool verify /pa 会报
#    "terminated in a root certificate which is not trusted"
Import-Certificate -FilePath tools\build\signing\FaustLauncher.cer `
  -CertStoreLocation Cert:\CurrentUser\Root
```

**如果是 CA（DigiCert / SSL.com / Sectigo / GlobalSign）签发的证书**：直接把它导出的
`.pfx` 覆盖到 `signing/FaustLauncher.pfx` 并同步密码即可，流程完全一样。
EV 证书在硬件令牌里，用 `signtool sign /sha1 <指纹>` 配合 `/n` 选证书，不需要 pfx
（那种情况把 `pfx` 换成 `n` 参数不在本脚本范围内）。

## 关于自签名的效果

自签名证书只对**装了这张 `.cer` 到「受信任的根证书颁发机构」的机器**有效。
别人机器上默认不受信任，SmartScreen 弹出“未知发布者”的行为**不会改善** ——
要真正消掉警告只能买 CA 签发的 OV/EV 代码签名证书。
自签名的价值在于：内部使用、锁定文件来源、避免运行时的“文件已被修改”提示。
