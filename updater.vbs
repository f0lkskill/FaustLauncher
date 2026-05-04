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

' ========== 正确启动EXE（修复工作目录！） ==========
If fso.FileExists(exePath) Then
    ' 关键：先切换工作目录，再运行！
    WshShell.CurrentDirectory = exeDir
    WshShell.Run """" & exePath & """", 1, False
End If

Set fso = Nothing
Set WshShell = Nothing