# Registers the "Synora Worker" scheduled task for the current user.
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File install-worker-task.ps1 [-Start]
#
# The task runs the Worker daemon directly (python -m tools.pipeline.worker_daemon --env-file ...), so stopping the
# task stops the daemon and nothing is left behind. It runs in this user's session (so Claude Code keeps its normal
# login) with no stored password, and the daemon keeps its own timestamped, size-rotated log.
#
# Restart: the task starts at logon and again every minute; a start is ignored while an instance is running
# (MultipleInstances IgnoreNew), so a daemon that died is back within a minute. Task Scheduler's own "restart on
# failure" was tested and does not fire when the process is killed, so it is not relied on.
# Because of that, Stop-ScheduledTask alone is not a stop: use Disable-ScheduledTask first (see the README).
# Settings come from %USERPROFILE%\.synora\worker.env (copy worker.env.example there first).
param([switch]$Start)
$ErrorActionPreference = 'Stop'
$task_name = 'Synora Worker'
$home_dir = Join-Path $env:USERPROFILE '.synora'
$config_file = Join-Path $home_dir 'worker.env'

if (-not (Test-Path $config_file)) {
    throw "Create $config_file first (copy worker.env.example and edit it)."
}
$settings_map = @{}
foreach ($line in Get-Content $config_file) {
    $entry = $line.Trim()
    if ($entry -eq '' -or $entry.StartsWith('#') -or -not $entry.Contains('=')) { continue }
    $name, $value = $entry -split '=', 2
    $settings_map[$name.Trim()] = $value.Trim()
}
foreach ($required in 'SYNORA_PYTHON', 'SYNORA_BRIDGE_REPO', 'SYNORA_GATEWAY_URL', 'SYNORA_WORKER_ID', 'SYNORA_WORKER_KEY_FILE', 'SYNORA_WORKER_LOG_FILE') {
    if (-not $settings_map[$required]) { throw "worker.env is missing $required" }
}
foreach ($path in $settings_map['SYNORA_PYTHON'], $settings_map['SYNORA_BRIDGE_REPO'], $settings_map['SYNORA_WORKER_KEY_FILE']) {
    if (-not (Test-Path $path)) { throw "Configured path does not exist: $path" }
}
if ($settings_map['SYNORA_GATEWAY_URL'] -notmatch '^wss://') { throw 'SYNORA_GATEWAY_URL must start with wss://' }

$action = New-ScheduledTaskAction -Execute $settings_map['SYNORA_PYTHON'] `
    -Argument "-B -u -m tools.pipeline.worker_daemon --env-file `"$config_file`"" `
    -WorkingDirectory $settings_map['SYNORA_BRIDGE_REPO']
$logon = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
$watchdog = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 1) -RepetitionDuration (New-TimeSpan -Days 3650)
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew

Register-ScheduledTask -TaskName $task_name -Action $action -Trigger @($logon, $watchdog) -Principal $principal -Settings $settings `
    -Description 'Synora Agent Bridge Worker: outbound-only connection to the Gateway.' -Force | Out-Null
Write-Output "Registered '$task_name' (starts at logon and is checked every minute). Log: $($settings_map['SYNORA_WORKER_LOG_FILE'])"
if ($Start) {
    Start-ScheduledTask -TaskName $task_name
    Write-Output 'Started.'
}
