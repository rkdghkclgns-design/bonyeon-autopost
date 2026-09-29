# Registers the daily Naver cross-post task (Windows Task Scheduler, current user).
#   powershell -ExecutionPolicy Bypass -File scripts\install_naver_task.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\install_naver_task.ps1 -Remove
# Runs scripts\naver_daily.py at 10:30 and 11:30 every day (after the 10:00 Google post; 11:30 covers the
# 10:40 backup run). If the PC is off, the day is skipped (Google only). If it was asleep, it wakes to run.
param([switch]$Remove)

$TaskName = "BonyeonNaverDaily"
$Root = Split-Path -Parent $PSScriptRoot

if ($Remove) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Output "removed: $TaskName"
    exit 0
}

$Python = Join-Path $Root ".venv\Scripts\pythonw.exe"   # pythonw: no console window
if (-not (Test-Path $Python)) { throw "python not found: $Python" }

$Action = New-ScheduledTaskAction -Execute $Python -Argument "scripts\naver_daily.py" -WorkingDirectory $Root
$Triggers = @(
    (New-ScheduledTaskTrigger -Daily -At "10:30"),
    (New-ScheduledTaskTrigger -Daily -At "11:30")
)
$Settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -WakeToRun -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 30) -MultipleInstances IgnoreNew
$Principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Triggers -Settings $Settings `
    -Principal $Principal -Description "Bonyeon: post today's Google blog post to Naver (same content)" -Force | Out-Null
$Task = Get-ScheduledTask -TaskName $TaskName
Write-Output ("registered: {0} ({1})" -f $Task.TaskName, $Task.State)
($Task.Triggers | ForEach-Object { $_.StartBoundary }) -join ", "
