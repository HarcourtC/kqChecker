<#
PowerShell helper to register/unregister a Scheduled Task that runs the project's wrapper.
Usage examples (PowerShell elevated needed to register as SYSTEM):

# Register task running as SYSTEM every 3 minutes:
.\scripts\register_task_scheduler.ps1 -TaskName "kqCheckerPolling" -PythonExe "C:\Python39\python.exe" -ScriptPath "E:\Program\kaoqing\run_once_locked.py" -IntervalMinutes 3 -RunAsSystem

# Unregister:
.\scripts\register_task_scheduler.ps1 -TaskName "kqCheckerPolling" -Remove

# Register as current user (no -RunAsSystem):
.\scripts\register_task_scheduler.ps1 -TaskName "kqCheckerPolling" -PythonExe "C:\Python39\python.exe" -ScriptPath "E:\Program\kaoqing\run_once_locked.py" -IntervalMinutes 3

# Notes:
# - Run PowerShell as Administrator if using -RunAsSystem. If you run as non-admin, omit -RunAsSystem.
# - The script uses a trigger that starts 1 minute from now and repeats indefinitely every N minutes.
# - The wrapper prevents overlapping runs using a local lock file.
#>

param(
  [string]$TaskName = "kqCheckerPolling",
  [string]$PythonExe = "C:\\Python39\\python.exe",
  [string]$ScriptPath = "E:\\Program\\kaoqing\\run_once_locked.py",
  [int]$IntervalMinutes = 3,
  [switch]$RunAsSystem,
  [switch]$Remove
)

function Register-MyTask {
    param($TaskName, $PythonExe, $ScriptPath, $IntervalMinutes, $RunAsSystem)

    if (-not (Test-Path $ScriptPath)) {
        Write-Error "ScriptPath not found: $ScriptPath"
        return 1
    }

    $action = New-ScheduledTaskAction -Execute $PythonExe -Argument "`"$ScriptPath`""

    # Trigger: start at system startup (only once). The scheduler (main.py) is long-running
    # so we only start it on boot rather than repeating every N minutes.
    $trigger = New-ScheduledTaskTrigger -AtStartup

    $desc = "kqChecker polling: every $IntervalMinutes minutes. Runs $ScriptPath"

    if ($RunAsSystem) {
        try {
            $principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -RunLevel Highest
            Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Principal $principal -Description $desc -Force
        } catch {
            Write-Error "Failed to register as SYSTEM: $_"
            return 2
        }
    } else {
        try {
            # Register as current user
            Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Description $desc -Force
        } catch {
            Write-Error "Failed to register task: $_"
            return 3
        }
    }

    Write-Host "Registered task '$TaskName' to run $ScriptPath every $IntervalMinutes minutes. Start time: $startTime"
    return 0
}

function Unregister-MyTask {
    param($TaskName)
    try {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction Stop
        Write-Host "Unregistered task '$TaskName'"
        return 0
    } catch {
        Write-Error "Failed to unregister task: $_"
        return 1
    }
}

if ($Remove) {
    exit (Unregister-MyTask -TaskName $TaskName)
} else {
    exit (Register-MyTask -TaskName $TaskName -PythonExe $PythonExe -ScriptPath $ScriptPath -IntervalMinutes $IntervalMinutes -RunAsSystem:$RunAsSystem)
}
