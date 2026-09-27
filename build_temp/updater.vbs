Option Explicit
Dim fso, WshShell
Dim scriptName, currentDir, up1Dir, up2Dir, up3Dir
Dim exePath, exeDir

Set fso = CreateObject("Scripting.FileSystemObject")
Set WshShell = CreateObject("WScript.Shell")

' 脚本自身名字
scriptName = WScript.ScriptName

' 当前目录
currentDir = fso.GetAbsolutePathName(".")

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

' ========== 复制所有文件（排除VBS自己），支持覆盖 ==========
Dim file
For Each file In fso.GetFolder(currentDir).Files
    If LCase(file.Name) <> LCase(scriptName) Then
        On Error Resume Next
        fso.CopyFile file.Path, fso.BuildPath(up3Dir, file.Name), True
        If Err.Number = 0 Then
            fso.DeleteFile file.Path, True
        End If
        On Error GoTo 0
    End If
Next

' ========== 复制所有子文件夹，支持覆盖 ==========
Dim fd
For Each fd In fso.GetFolder(currentDir).SubFolders
    On Error Resume Next
    fso.CopyFolder fd.Path, fso.BuildPath(up3Dir, fd.Name), True
    If Err.Number = 0 Then
        fso.DeleteFolder fd.Path, True
    End If
    On Error GoTo 0
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
Dim webOk, missing
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