<#
.SYNOPSIS
  Install a Windows scheduled task that runs the vibecoder change-detector
  every 30 minutes for this repo.

.DESCRIPTION
  Idempotent: re-running registers the same task with overwrite. Uses
  `python -3` if available, else `python`. Uses the path of THIS script
  to locate detect.py, so the task is portable.

.NOTES
  Run from an elevated or non-elevated shell; SchTasks user-scope is fine.
#>

$ErrorActionPreference = "Stop"

$here  = Split-Path -Parent $MyInvocation.MyCommand.Path
$repo  = Split-Path -Parent $here
$detect = Join-Path $here "detect.py"
if (-not (Test-Path $detect)) { throw "detect.py not found at $detect" }

$repoSlug = (Split-Path -Leaf $repo) -replace "[^A-Za-z0-9_-]", "_"
$taskName = "Vibecoder_$repoSlug"

$pyCmd = (Get-Command py -ErrorAction SilentlyContinue) ? "py" : "python"
if (-not $pyCmd) { $pyCmd = "python" }

$action  = New-ScheduledTaskAction -Execute $pyCmd -Argument "`"$detect`""
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 30)
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopOnIdleEnd -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
Write-Host "[vibecoder] registered scheduled task '$taskName' running '$pyCmd $detect' every 30 min."
