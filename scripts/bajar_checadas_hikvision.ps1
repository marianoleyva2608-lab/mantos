# Baja TODAS las checadas guardadas en un checador Hikvision (DS-K1T343) y las
# sube al sistema (adpacksystem.cloud) por el mismo endpoint que usa el aparato.
# Se puede correr las veces que sea: no duplica (misma llave empleado+fecha+serial).
#
# Uso (PowerShell, en una PC de la red de la planta):
#   powershell -ExecutionPolicy Bypass -File bajar_checadas_hikvision.ps1
#   powershell -ExecutionPolicy Bypass -File bajar_checadas_hikvision.ps1 -Ip 192.168.1.152 -Planta conversion
# Modo automatico (lo usa la tarea semanal de programar_semanal.ps1):
#   ... -Dias 8 -CredFile <archivo cifrado con la contrasena>

param(
    [string]$Ip = '192.168.1.152',
    [string]$Planta = 'conversion',
    [string]$Desde = '2020-01-01',
    [int]$Dias = 0,
    [string]$CredFile = '',
    [string]$Servidor = 'https://adpacksystem.cloud'
)

$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

if ($Dias -gt 0) { $Desde = (Get-Date).AddDays(-$Dias).ToString('yyyy-MM-dd') }
if ($CredFile -and (Test-Path $CredFile)) {
    # Credencial cifrada con DPAPI: solo la abre este usuario de Windows en esta PC
    $cred = Import-Clixml $CredFile
} else {
    $cred = Get-Credential -UserName 'admin' -Message "Usuario y contrasena del checador $Ip"
}
$utf8 = New-Object System.Text.UTF8Encoding($false)

function Post-Json($url, $obj, $credencial) {
    $bytes = $utf8.GetBytes(($obj | ConvertTo-Json -Depth 6 -Compress))
    $p = @{ Uri = $url; Method = 'Post'; Body = $bytes; UseBasicParsing = $true
            ContentType = 'application/json; charset=utf-8'; TimeoutSec = 30 }
    if ($credencial) { $p.Credential = $credencial }
    $r = Invoke-WebRequest @p
    $r.RawContentStream.Position = 0
    $txt = (New-Object IO.StreamReader($r.RawContentStream, $utf8)).ReadToEnd()
    if ($txt.TrimStart().StartsWith('{')) { return $txt | ConvertFrom-Json }
    return $txt
}

# 1) Bajar del aparato, de 30 en 30
$hasta = (Get-Date).AddDays(1).ToString('yyyy-MM-dd')
$eventos = New-Object System.Collections.ArrayList
$pos = 0
$searchId = [guid]::NewGuid().ToString()
Write-Host "Leyendo checadas de $Ip desde $Desde ..."
while ($true) {
    $cond = @{ AcsEventCond = @{
        searchID = $searchId; searchResultPosition = $pos; maxResults = 30
        major = 5; minor = 0
        startTime = "${Desde}T00:00:00-06:00"; endTime = "${hasta}T23:59:59-06:00" } }
    try {
        $resp = Post-Json "http://$Ip/ISAPI/AccessControl/AcsEvent?format=json" $cond $cred
    } catch {
        Write-Host "No se pudo leer el checador: $($_.Exception.Message)" -ForegroundColor Red
        Write-Host 'Revisa la IP, el usuario y la contrasena.'
        exit 1
    }
    $ae = $resp.AcsEvent
    $lote = @($ae.InfoList)
    foreach ($x in $lote) {
        if ($x -and ($x.employeeNoString -or $x.name)) { [void]$eventos.Add($x) }
    }
    $pos += [int]$ae.numOfMatches
    Write-Host ("  leidos {0} de {1}" -f $pos, $ae.totalMatches)
    if ($ae.responseStatusStrg -ne 'MORE' -or [int]$ae.numOfMatches -eq 0) { break }
}
Write-Host "Checadas con persona: $($eventos.Count)"
if ($eventos.Count -eq 0) { exit 0 }

# 2) Subir al sistema con el mismo formato que manda el aparato
$url = "$Servidor/checador/$Planta"
$ok = 0; $fallas = 0; $n = 0
foreach ($x in $eventos) {
    $n++
    $ev = @{ dateTime = $x.time; AccessControllerEvent = @{
        majorEventType = 5; subEventType = $x.minor
        employeeNoString = $x.employeeNoString; name = $x.name
        attendanceStatus = $x.attendanceStatus; serialNo = $x.serialNo
        time = $x.time; origen = 'descarga_historico' } }
    try { [void](Post-Json $url $ev $null); $ok++ }
    catch { $fallas++; Write-Host "  falla en $($x.time) $($x.name): $($_.Exception.Message)" -ForegroundColor Yellow }
    if ($n % 100 -eq 0) { Write-Host "  subidas $n de $($eventos.Count)" }
}
Write-Host ("Listo: {0} subidas, {1} con falla." -f $ok, $fallas) -ForegroundColor Green
Write-Host "Revisalas en $Servidor/asistencia (filtro Planta)."
