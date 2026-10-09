param(
    [switch]$Persistent
)

$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $PSScriptRoot
$dataDir = Join-Path $root 'instance'
$secureDir = 'C:\ProgramData\MesaSoporteS6'
$secretFile = Join-Path $secureDir 'lan-session-secret.txt'
$smtpConfigFile = Join-Path $secureDir 'smtp-config.json'
$smtpKeyFile = Join-Path $secureDir 'smtp-config.key'
$hostAddress = '192.0.2.10'
$port = 8080
$ruleName = 'MesaSoporteS6-LAN-HTTP'

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = [Security.Principal.WindowsPrincipal]::new($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Abra PowerShell como administrador para configurar el firewall y lanzar el portal LAN.'
}

$address = Get-NetIPAddress -AddressFamily IPv4 -IPAddress $hostAddress -ErrorAction SilentlyContinue
if (-not $address -or $address.AddressState -ne 'Preferred') {
    throw "La IP LAN $hostAddress no está asignada y activa en este equipo. No se modificó la red."
}

New-Item -ItemType Directory -Path $secureDir -Force | Out-Null
if (-not (Test-Path -LiteralPath $secretFile)) {
    $randomBytes = New-Object byte[] 48
    $random = [Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $random.GetBytes($randomBytes)
    } finally {
        $random.Dispose()
    }
    $secret = [Convert]::ToBase64String($randomBytes)
    [System.IO.File]::WriteAllText($secretFile, $secret, [System.Text.Encoding]::ASCII)
}

& icacls.exe $secureDir /inheritance:r /grant:r '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw 'No fue posible restringir a SYSTEM y Administradores los permisos del secreto de sesión.'
}
& icacls.exe $secretFile /inheritance:r /grant:r '*S-1-5-18:F' '*S-1-5-32-544:F' | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw 'No fue posible restringir los permisos del archivo de secreto.'
}

$secretKey = [System.IO.File]::ReadAllText($secretFile, [System.Text.Encoding]::ASCII).Trim()
if ($secretKey.Length -lt 32) {
    throw 'El secreto de sesión persistente es inválido; no se iniciará el servidor.'
}

$listeners = @(Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue)
if ($listeners.Count -gt 0) {
    throw "El puerto $port ya está ocupado. No se detuvo ni reemplazó el proceso existente."
}

$createdFirewallRule = $false
$firewallRule = Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue
if (-not $firewallRule) {
    New-NetFirewallRule `
        -DisplayName $ruleName `
        -Description 'Mesa Soporte S6 HTTP solo para piloto LAN; tráfico sin cifrar.' `
        -Direction Inbound `
        -Action Allow `
        -Protocol TCP `
        -LocalPort $port `
        -RemoteAddress '192.0.2.0/24' `
        -Profile Domain `
        -EdgeTraversalPolicy Block | Out-Null
    $createdFirewallRule = $true
} else {
    $addressFilter = $firewallRule | Get-NetFirewallAddressFilter
    $portFilter = $firewallRule | Get-NetFirewallPortFilter
    if (-not $firewallRule.Enabled -or $firewallRule.Direction -ne 'Inbound' -or $firewallRule.Action -ne 'Allow' -or
        $firewallRule.Profile -notmatch 'Domain' -or $portFilter.Protocol -ne 'TCP' -or $portFilter.LocalPort -ne [string]$port -or
        $addressFilter.RemoteAddress -notcontains '192.0.2.0/24' -and $addressFilter.RemoteAddress -notcontains '192.0.2.10/255.255.255.0') {
        throw "La regla '$ruleName' existe pero no coincide con el alcance LAN esperado; no se iniciará el listener."
    }
}

$env:HELPDESK_MODE = 'lan-http'
$env:HELPDESK_HOST = $hostAddress
$env:HELPDESK_PORT = [string]$port
$env:HELPDESK_DATA_DIR = $dataDir
$env:HELPDESK_SECRET_KEY = $secretKey
$env:HELPDESK_COOKIE_SECURE = '0'
$env:HELPDESK_LAN_HTTP_ACK = 'I_ACCEPT_UNENCRYPTED_LAN_HTTP'

if (Test-Path -LiteralPath $smtpConfigFile) {
    if (-not (Test-Path -LiteralPath $smtpKeyFile)) {
        throw "Existe configuración SMTP pero falta la clave protegida: $smtpKeyFile"
    }
    $smtpConfig = Get-Content -LiteralPath $smtpConfigFile -Raw | ConvertFrom-Json
    $smtpKey = [System.IO.File]::ReadAllBytes($smtpKeyFile)
    $smtpPassword = ConvertTo-SecureString $smtpConfig.password -SecureKey $smtpKey
    $smtpCredential = [System.Net.NetworkCredential]::new($smtpConfig.username, $smtpPassword)
    $env:HELPDESK_SMTP_HOST = $smtpConfig.host
    $env:HELPDESK_SMTP_PORT = [string]$smtpConfig.port
    $env:HELPDESK_SMTP_USERNAME = $smtpConfig.username
    $env:HELPDESK_SMTP_PASSWORD = $smtpCredential.Password
    $env:HELPDESK_SMTP_FROM = $smtpConfig.from
    $env:HELPDESK_SMTP_SSL = [string]$smtpConfig.ssl
}

Write-Host "Portal LAN: http://${hostAddress}:${port}/" -ForegroundColor Yellow
Write-Host 'El tráfico HTTP no está cifrado. Limite su uso a una LAN confiable; no use desde Internet ni redes Wi-Fi públicas.' -ForegroundColor Yellow
Write-Host 'La consola administrativa sigue requiriendo usuario y contraseña.' -ForegroundColor Cyan

Push-Location $root
try {
    & (Join-Path $root '.venv\Scripts\python.exe') 'server.py'
} finally {
    Pop-Location
    $persistentTask = Get-ScheduledTask -TaskName 'MesaSoporteS6-LAN' -ErrorAction SilentlyContinue
    if ($createdFirewallRule -and -not $Persistent -and -not $persistentTask) {
        Remove-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue
    }
}