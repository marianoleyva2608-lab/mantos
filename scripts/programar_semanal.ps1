# Deja programada la descarga semanal de checadas de los dos checadores.
# Correr UNA VEZ en esta PC (la que esta en la red de la planta):
#   powershell -ExecutionPolicy Bypass -File programar_semanal.ps1
#
# 1) Pide la contrasena de cada checador y la guarda cifrada (DPAPI) en
#    %LOCALAPPDATA%\adpack-checador. Solo este usuario de Windows en esta PC
#    puede abrirla.
# 2) Crea la tarea "ADPACK - checadas semanales": cada lunes a las 07:00 baja
#    los ultimos 8 dias de cada checador y los sube al sistema (no duplica).
#    Si la PC estaba apagada, corre en cuanto se prenda.

$ErrorActionPreference = 'Stop'
$checadores = @(
    @{ Planta = 'matriz';     Ip = '192.168.1.153' },
    @{ Planta = 'conversion'; Ip = '192.168.1.152' }
)
$carpeta = Join-Path $env:LOCALAPPDATA 'adpack-checador'
New-Item -ItemType Directory -Force $carpeta | Out-Null
$script = Join-Path $PSScriptRoot 'bajar_checadas_hikvision.ps1'

$lineas = @('$ErrorActionPreference = ''Continue''')
foreach ($c in $checadores) {
    $cf = Join-Path $carpeta "cred_$($c.Planta).xml"
    $cred = Get-Credential -UserName 'admin' -Message "Contrasena del checador $($c.Planta) ($($c.Ip))"
    $cred | Export-Clixml $cf
    $log = Join-Path $carpeta "log_$($c.Planta).txt"
    $lineas += "& '$script' -Ip $($c.Ip) -Planta $($c.Planta) -Dias 8 -CredFile '$cf' *> '$log'"
    Write-Host "Guardada la contrasena de $($c.Planta)."
}
$corredor = Join-Path $carpeta 'semanal.ps1'
Set-Content -Path $corredor -Value $lineas -Encoding UTF8

$accion = New-ScheduledTaskAction -Execute 'powershell.exe' `
    -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$corredor`""
$cuando = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday -At 7:00am
$ajustes = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 2)
Register-ScheduledTask -TaskName 'ADPACK - checadas semanales' -Action $accion -Trigger $cuando `
    -Settings $ajustes -Description 'Baja las checadas de los checadores Matriz y Conversion y las sube a adpacksystem.cloud' `
    -Force | Out-Null

Write-Host ''
Write-Host 'Listo: la tarea "ADPACK - checadas semanales" corre cada lunes a las 7:00.' -ForegroundColor Green
Write-Host "Resultados de cada corrida: $carpeta\log_*.txt"
Write-Host 'Para probarla ahora: Programador de tareas > ADPACK - checadas semanales > Ejecutar.'
