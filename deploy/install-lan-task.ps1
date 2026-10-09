$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $PSScriptRoot
$launcher = Join-Path $PSScriptRoot 'run-lan-http.ps1'
$taskName = 'MesaSoporteS6-LAN'

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = [Security.Principal.WindowsPrincipal]::new($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Abra PowerShell como administrador para registrar el inicio automático.'
}

if (-not (Test-Path -LiteralPath $launcher)) {
    throw "No se encuentra el lanzador: $launcher"
}
if (-not (Test-Path -LiteralPath (Join-Path $root '.venv\Scripts\python.exe'))) {
    throw 'No existe el entorno Python .venv del proyecto.'
}
if (Get-NetTCPConnection -State Listen -LocalPort 8080 -ErrorAction SilentlyContinue) {
    throw 'El puerto 8080 está ocupado. Detenga primero el servidor LAN manual con Ctrl+C en su terminal.'
}

$dataDir = Join-Path $root 'instance'
if (Test-Path -LiteralPath $dataDir) {
    & icacls.exe $dataDir /inheritance:r /grant:r '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw 'No fue posible restringir los permisos de la base SQLite existente.'
    }
}

$arguments = '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "{0}" -Persistent' -f $launcher
$action = New-ScheduledTaskAction -Execute (Join-Path $PSHOME 'powershell.exe') -Argument $arguments -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -AtStartup -RandomDelay (New-TimeSpan -Seconds 30)
$taskPrincipal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -RestartCount 5 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -MultipleInstances IgnoreNew

Register-ScheduledTask `
    -TaskName $taskName `
    -Description 'Mesa de Soporte S6 LAN HTTP limitado a 192.0.2.0/24. Tráfico sin cifrar; solo piloto LAN.' `
    -Action $action `
    -Trigger $trigger `
    -Principal $taskPrincipal `
    -Settings $settings `
    -Force | Out-Null

Write-Host "Tarea '$taskName' registrada para arrancar con Windows bajo SYSTEM." -ForegroundColor Green
Write-Host 'La tarea no necesita guardar contraseña de usuario.' -ForegroundColor Cyan
Write-Host 'Use Start-ScheduledTask -TaskName MesaSoporteS6-LAN para iniciarla ahora.' -ForegroundColor Yellow