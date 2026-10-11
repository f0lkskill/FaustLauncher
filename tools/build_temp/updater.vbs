Option Explicit
Dim fso, WshShell
Dim scriptName, currentDir, up1Dir, up2Dir, up3Dir
Dim exePath, exeDir
Dim file, fd, sk
Dim internalSrc, internalDst, internalNew, internalOld
Dim skinsNew, skinsOld
Dim errNo, missing

Set fso = CreateObject("Scripting.FileSystemObject")
Set WshShell = CreateObject("WScript.Shell")

' 脚本自身名字
scriptName = WScript.ScriptName

' 当前目录: 用**脚本自身所在目录**, 不要用 "当前工作目录"
' (正常更新时由 version_utils 以 cwd=更新包目录 启动 wscript, 两者一致;
'  但用户手动双击 updater.vbs、或被安全软件代为启动时, cwd 可能是 System32 之类的
'  无关目录 —— 按 cwd 推算会把文件复制到错误的位置)
currentDir = fso.GetParentFolderName(WScript.ScriptFullName)

' 计算 上上上级目录
up1Dir = fso.GetParentFolderName(currentDir)
up2Dir = fso.GetParentFolderName(up1Dir)
up3Dir = fso.GetParentFolderName(up2Dir)

' EXE 路径
exeDir = up3Dir
exePath = fso.BuildPath(exeDir, "FaustLauncher.exe")

' ========== 等待旧进程退出 (5 秒) ==========
' 旧启动器退出时会先隐藏窗口再后台慢慢关闭 (WebView2 销毁), 需等待其完全退出,
' 否则覆盖 exe 时文件被占用而失败
WScript.Sleep 5000

' ========== 1) 顶层文件: 覆盖复制 (排除 VBS 自己) ==========
For Each file In fso.GetFolder(currentDir).Files
    If LCase(file.Name) <> LCase(scriptName) Then
        On Error Resume Next
        Err.Clear
        fso.CopyFile file.Path, fso.BuildPath(up3Dir, file.Name), True
        If Err.Number = 0 Then
            fso.DeleteFile file.Path, True
        End If
        On Error GoTo 0
    End If
Next

' ========== 2) _internal: 整体替换 ==========
' 为什么不能像其它目录那样"合并覆盖":
'   _internal 里全是 PyInstaller 的运行时 (DLL / .pyd / PYZ)。CopyFolder 的覆盖语义是
'   **合并** —— 只会覆盖同名文件, 新版本删掉的文件会永远留在旧目录里。结果是新旧
'   DLL / 扩展模块混在一起被加载 (典型症状: 更新后启动崩溃、行为诡异), 而且目录只会
'   越滚越大 (当前约 65MB / 1900 个文件)。
'
' 替换过程分三步, 任何一步失败都不会破坏现有安装:
'   1) 新内容先复制成 _internal.new   —— 失败: 旧 _internal 原样未动, 启动器仍可用
'   2) 旧的改名为 _internal.old       —— 改名是瞬时的, 不额外占空间
'   3) _internal.new 改名为 _internal —— 失败: 把 .old 改回来, 恢复原状
' 三步都成功后才删除 .old。
internalSrc = fso.BuildPath(currentDir, "_internal")
internalDst = fso.BuildPath(up3Dir, "_internal")
internalNew = fso.BuildPath(up3Dir, "_internal.new")
internalOld = fso.BuildPath(up3Dir, "_internal.old")

If fso.FolderExists(internalSrc) Then

    ' ---- 2.1 新内容先落到 _internal.new ----
    On Error Resume Next
    Err.Clear
    If fso.FolderExists(internalNew) Then fso.DeleteFolder internalNew, True
    Err.Clear
    fso.CopyFolder internalSrc, internalNew, True
    errNo = Err.Number
    On Error GoTo 0
    If errNo <> 0 Then
        On Error Resume Next
        fso.DeleteFolder internalNew, True
        On Error GoTo 0
        MsgBox "FaustLauncher 更新失败：无法准备新版本的 _internal。" & vbCrLf & vbCrLf & _
               "常见原因：安装盘剩余空间不足（替换过程需要约 65MB 暂存空间），" & _
               "或安装目录里的文件仍被占用。" & vbCrLf & vbCrLf & _
               "当前版本未受影响，仍可正常使用。请关闭 FaustLauncher 后重试。", _
               48, "FaustLauncher 更新失败"
        Set fso = Nothing
        Set WshShell = Nothing
        WScript.Quit 1
    End If

    ' ---- 2.2 旧目录挪开 (瞬时改名) ----
    On Error Resume Next
    Err.Clear
    If fso.FolderExists(internalOld) Then fso.DeleteFolder internalOld, True
    Err.Clear
    fso.MoveFolder internalDst, internalOld
    errNo = Err.Number
    On Error GoTo 0
    If errNo <> 0 Then
        On Error Resume Next
        fso.DeleteFolder internalNew, True
        On Error GoTo 0
        MsgBox "FaustLauncher 更新失败：旧的 _internal 无法替换（文件被占用）。" & vbCrLf & vbCrLf & _
               "请关闭 FaustLauncher、资源管理器里的安装目录窗口后重试。" & vbCrLf & vbCrLf & _
               "当前版本未受影响，仍可正常使用。", _
               48, "FaustLauncher 更新失败"
        Set fso = Nothing
        Set WshShell = Nothing
        WScript.Quit 1
    End If

    ' ---- 2.3 新目录就位 ----
    On Error Resume Next
    Err.Clear
    fso.MoveFolder internalNew, internalDst
    errNo = Err.Number
    On Error GoTo 0
    If errNo <> 0 Then
        On Error Resume Next
        fso.MoveFolder internalOld, internalDst      ' 回滚, 保证启动器还能用
        On Error GoTo 0
        MsgBox "FaustLauncher 更新失败：_internal 替换未完成，已恢复为原版本。" & vbCrLf & vbCrLf & _
               "当前版本未受影响，仍可正常使用。请关闭 FaustLauncher 后重试。", _
               48, "FaustLauncher 更新失败"
        Set fso = Nothing
        Set WshShell = Nothing
        WScript.Quit 1
    End If

    ' ---- 2.4 补回用户自己放的皮肤 ----
    ' _internal\web\app_skins 是皮肤目录: 用户可能把自己做的/下载的皮肤放了进去,
    ' 整体替换会连带删掉, 所以把"新包里面没有的"皮肤目录复制回来。
    skinsNew = fso.BuildPath(internalDst, "web\app_skins")
    skinsOld = fso.BuildPath(internalOld, "web\app_skins")
    If fso.FolderExists(skinsNew) And fso.FolderExists(skinsOld) Then
        On Error Resume Next
        For Each sk In fso.GetFolder(skinsOld).SubFolders
            If Not fso.FolderExists(fso.BuildPath(skinsNew, sk.Name)) Then
                Err.Clear
                fso.CopyFolder sk.Path, fso.BuildPath(skinsNew, sk.Name), True
            End If
        Next
        On Error GoTo 0
    End If

    ' ---- 2.5 清理: 旧目录 + 源目录 ----
    ' 删除失败(仍被占用)不影响使用, 下次更新会再清一次
    On Error Resume Next
    fso.DeleteFolder internalOld, True
    fso.DeleteFolder internalSrc, True
    On Error GoTo 0
End If

' ========== 3) 其余子文件夹: 合并覆盖 (保留用户数据) ==========
' config / lang / mods / addons 等目录里可能装着用户自己的东西 (设置、汉化、Mod),
' 这些只做合并覆盖, 绝不整体删除。
For Each fd In fso.GetFolder(currentDir).SubFolders
    If LCase(fd.Name) <> "_internal" Then
        On Error Resume Next
        Err.Clear
        fso.CopyFolder fd.Path, fso.BuildPath(up3Dir, fd.Name), True
        If Err.Number = 0 Then
            fso.DeleteFolder fd.Path, True
        End If
        On Error GoTo 0
    End If
Next

' 删除空目录
On Error Resume Next
fso.DeleteFolder currentDir, True
On Error GoTo 0

' ========== 复制结果自检 ==========
' 上面的复制用了 On Error Resume Next: 某一项失败时只是保留源目录, 既不报错也不提示,
' 用户看到的仍然是"更新完成"。而本版本的启动器界面收在 _internal\web\ 下, 它一旦没被
' 复制过来, 下次启动只会弹一句"找不到页面文件", 用户根本不知道是这次更新没复制全。
' 所以在启动之前先把最关键的前端页面确认一遍 (兼容顶层 web\ 的旧结构)。
missing = ""
If Not fso.FileExists(fso.BuildPath(up3Dir, "_internal\web\app\index.html")) Then
    If Not fso.FileExists(fso.BuildPath(up3Dir, "web\app\index.html")) Then
        missing = missing & "  _internal\web\app\index.html" & vbCrLf
    End If
End If
If Not fso.FileExists(exePath) Then
    missing = missing & "  FaustLauncher.exe" & vbCrLf
End If

If missing <> "" Then
    MsgBox "FaustLauncher 更新未完成：" & vbCrLf & vbCrLf & _
           "以下关键文件没有复制到安装目录：" & vbCrLf & missing & vbCrLf & _
           "常见原因：安装目录里的文件正被占用（启动器/游戏/资源管理器没关干净）、" & _
           "磁盘空间不足，或更新包本身不完整。" & vbCrLf & vbCrLf & _
           "请关闭 FaustLauncher 后重试；若仍失败，请到发布页重新下载完整安装包，" & _
           "解压到一个新目录后直接运行。" & vbCrLf & vbCrLf & _
           "（为避免启动后只看到错误提示，本次不再自动启动）", _
           48, "FaustLauncher 更新未完成"
    Set fso = Nothing
    Set WshShell = Nothing
    WScript.Quit 1
End If

' ========== 正确启动EXE（修复工作目录！） ==========
If fso.FileExists(exePath) Then
    ' 关键：先切换工作目录，再运行！
    WshShell.CurrentDirectory = exeDir
    WshShell.Run """" & exePath & """", 1, False
End If

Set fso = Nothing
Set WshShell = Nothing
