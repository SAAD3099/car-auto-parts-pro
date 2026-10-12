param([Parameter(Mandatory=$true)][string]$Manifest)
$ErrorActionPreference = 'Stop'
$info = Get-Content -LiteralPath $Manifest -Raw -Encoding UTF8 | ConvertFrom-Json
$desktopFolder = [Environment]::GetFolderPath('Desktop')
$wsh = New-Object -ComObject WScript.Shell
$link = $wsh.CreateShortcut((Join-Path $desktopFolder 'AutoParts Pro.lnk'))
$link.TargetPath = $info.pythonw
$link.Arguments = '"' + $info.bootstrap + '"'
$link.WorkingDirectory = $info.root
$link.IconLocation = $info.icon + ',0'
$link.Description = 'AutoParts Pro - Desktop Automotive Command Center'
$link.WindowStyle = 1
$link.Save()
