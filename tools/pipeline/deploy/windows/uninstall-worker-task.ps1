# Stops the Worker and removes the "Synora Worker" scheduled task. Leaves ~/.synora (keys, certificate, config, logs) alone.
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File uninstall-worker-task.ps1
#
# To only pause the Worker instead: Stop-ScheduledTask 'Synora Worker'  /  Disable-ScheduledTask 'Synora Worker'.
$ErrorActionPreference = 'Stop'
$task_name = 'Synora Worker'
if (-not (Get-ScheduledTask -TaskName $task_name -ErrorAction SilentlyContinue)) {
    Write-Output "No task named '$task_name'."
    exit 0
}
Stop-ScheduledTask -TaskName $task_name -ErrorAction SilentlyContinue
Unregister-ScheduledTask -TaskName $task_name -Confirm:$false
Write-Output "Removed '$task_name'."
