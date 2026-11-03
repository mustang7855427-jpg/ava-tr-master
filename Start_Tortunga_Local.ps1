param(
    [switch]$Stop,
    [string]$TlsCertificatePath,
    [string]$TlsPrivateKeyPath
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $projectRoot '.venv-app\Scripts\python.exe'
$webScript = Join-Path $projectRoot 'web.py'
$gameScript = Join-Path $projectRoot 'server.py'
$logDirectory = Join-Path $projectRoot 'logs'
$pidFile = Join-Path $logDirectory 'local-server-pids.json'
$webPort = 8080
$gamePort = 8123

function Test-RedisReady {
    $client = [System.Net.Sockets.TcpClient]::new()
    try {
        $client.Connect('127.0.0.1', 6379)
        $stream = $client.GetStream()
        $request = [System.Text.Encoding]::ASCII.GetBytes("*1`r`n`$4`r`nPING`r`n")
        $stream.Write($request, 0, $request.Length)
        $stream.Flush()
        $reader = [System.IO.StreamReader]::new($stream)
        return $reader.ReadLine() -eq '+PONG'
    }
    catch {
        return $false
    }
    finally {
        $client.Dispose()
    }
}

function Assert-LocalPortAvailable {
    param([int]$Port)

    $listener = [System.Net.Sockets.TcpListener]::new(
        [System.Net.IPAddress]::Loopback, $Port)
    try {
        $listener.Start()
    }
    catch {
        throw "Port 127.0.0.1:$Port is busy. Stop the previous server or check its logs."
    }
    finally {
        $listener.Stop()
    }
}

function Wait-ForTcpPort {
    param(
        [System.Diagnostics.Process]$Process,
        [int]$Port
    )

    $deadline = [DateTime]::UtcNow.AddSeconds(20)
    while ([DateTime]::UtcNow -lt $deadline) {
        $Process.Refresh()
        if ($Process.HasExited) {
            throw ('Server process exited during startup (code {0}). Check logs in {1}.' -f $Process.ExitCode, $logDirectory)
        }
        $client = [System.Net.Sockets.TcpClient]::new()
        try {
            $connect = $client.BeginConnect('127.0.0.1', $Port, $null, $null)
            if ($connect.AsyncWaitHandle.WaitOne(300)) {
                $client.EndConnect($connect)
                return
            }
        }
        catch {
        }
        finally {
            $client.Dispose()
        }
        Start-Sleep -Milliseconds 250
    }
    throw "Server did not open port 127.0.0.1:$Port within 20 seconds. Check logs in $logDirectory."
}

function Test-LocalHttpEndpoint {
    param(
        [string]$Uri,
        [int[]]$ExpectedStatus,
        [string]$PinnedCertificateThumbprint
    )

    $handler = [System.Net.Http.HttpClientHandler]::new()
    if (-not [string]::IsNullOrWhiteSpace($PinnedCertificateThumbprint)) {
        $handler.ServerCertificateCustomValidationCallback = {
            param($message, $certificate, $chain, $errors)
            return (
                $message.RequestUri.Host -eq 'localhost' -and
                $certificate.Thumbprint -eq $PinnedCertificateThumbprint
            )
        }.GetNewClosure()
    }
    $client = [System.Net.Http.HttpClient]::new($handler)
    try {
        $response = $client.GetAsync($Uri).GetAwaiter().GetResult()
        $status = [int]$response.StatusCode
        if ($status -notin $ExpectedStatus) {
            throw "Check of $Uri returned HTTP $status."
        }
        return $status
    }
    finally {
        $client.Dispose()
        $handler.Dispose()
    }
}

if ($Stop) {
    if (-not (Test-Path -LiteralPath $pidFile)) {
        Write-Output 'No PID file for servers started by this script.'
        exit 0
    }
    $started = Get-Content -LiteralPath $pidFile -Raw | ConvertFrom-Json
    foreach ($entry in @($started)) {
        $process = Get-CimInstance Win32_Process -Filter "ProcessId = $($entry.pid)" |
            Where-Object { $_.CommandLine -like "*$projectRoot*" -and $_.CommandLine -like "*$($entry.script)*" }
        if ($process) {
            Stop-Process -Id $process.ProcessId -ErrorAction Stop
        }
    }
    Remove-Item -LiteralPath $pidFile -Force
    Write-Output 'Stopped server processes started by this script.'
    exit 0
}

if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Nie znaleziono interpretera aplikacji: $python"
}
if (-not (Test-Path -LiteralPath $webScript -PathType Leaf) -or
    -not (Test-Path -LiteralPath $gameScript -PathType Leaf)) {
    throw 'Brakuje web.py lub server.py w folderze projektu.'
}
if (-not (Test-RedisReady)) {
    throw 'Redis is not responding on 127.0.0.1:6379. Start the local Redis service.'
}
if ([string]::IsNullOrWhiteSpace($TlsCertificatePath) -ne
    [string]::IsNullOrWhiteSpace($TlsPrivateKeyPath)) {
    throw 'For local HTTPS, provide both -TlsCertificatePath and -TlsPrivateKeyPath.'
}

New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
Assert-LocalPortAvailable $webPort
Assert-LocalPortAvailable $gamePort

$env:REDIS_URL = 'redis://127.0.0.1:6379/0'
$env:WEB_BIND_HOST = '127.0.0.1'
$env:GAME_BIND_HOST = '127.0.0.1'
$env:GAME_SERVER_HOST = '127.0.0.1'
$env:RENDER_DEPLOYMENT = $null
$env:RENDER_EXTERNAL_URL = $null
$env:PUBLIC_BASE_URL = $null
$env:PORT = $null
$scheme = 'http'
$pinnedCertificateThumbprint = $null
$env:WEB_TLS_CERT = $null
$env:WEB_TLS_KEY = $null
if (-not [string]::IsNullOrWhiteSpace($TlsCertificatePath)) {
    $TlsCertificatePath = (Resolve-Path -LiteralPath $TlsCertificatePath).Path
    $TlsPrivateKeyPath = (Resolve-Path -LiteralPath $TlsPrivateKeyPath).Path
    if (-not (Test-Path -LiteralPath $TlsCertificatePath -PathType Leaf) -or
        -not (Test-Path -LiteralPath $TlsPrivateKeyPath -PathType Leaf)) {
        throw 'Nie znaleziono pliku certyfikatu lub klucza TLS.'
    }
    $certificate = [System.Security.Cryptography.X509Certificates.X509Certificate2]::new(
        $TlsCertificatePath)
    if ([DateTime]::UtcNow -lt $certificate.NotBefore.ToUniversalTime() -or
        [DateTime]::UtcNow -gt $certificate.NotAfter.ToUniversalTime() -or
        $certificate.GetNameInfo(
            [System.Security.Cryptography.X509Certificates.X509NameType]::DnsName,
            $false) -ne 'localhost') {
        throw 'The certificate must be valid and issued for localhost.'
    }
    $pinnedCertificateThumbprint = $certificate.Thumbprint
    $certificate.Dispose()
    $env:WEB_TLS_CERT = $TlsCertificatePath
    $env:WEB_TLS_KEY = $TlsPrivateKeyPath
    $scheme = 'https'
}
$baseUrl = if ($scheme -eq 'https') {
    "https://localhost:$webPort"
}
else {
    "http://127.0.0.1:$webPort"
}
$env:PUBLIC_BASE_URL = $baseUrl

$startedProcesses = [System.Collections.Generic.List[object]]::new()
try {
    $webProcess = Start-Process -FilePath $python `
        -ArgumentList @('-u', $webScript) `
        -WorkingDirectory $projectRoot `
        -WindowStyle Hidden `
        -PassThru `
        -RedirectStandardOutput (Join-Path $logDirectory 'web-startup.out.log') `
        -RedirectStandardError (Join-Path $logDirectory 'web-startup.err.log')
    $startedProcesses.Add(@{ pid = $webProcess.Id; script = 'web.py' })
    Wait-ForTcpPort $webProcess $webPort

    $healthStatus = Test-LocalHttpEndpoint `
        "$baseUrl/healthz" @(200) $pinnedCertificateThumbprint
    $webhookStatus = Test-LocalHttpEndpoint `
        "$baseUrl/webhooks/payments" @(405) $pinnedCertificateThumbprint
    if ($webhookStatus -ne 405) {
        throw "Nieoczekiwany status sprawdzenia endpointu webhooka: HTTP $webhookStatus."
    }

    $gameProcess = Start-Process -FilePath $python `
        -ArgumentList @('-u', $gameScript) `
        -WorkingDirectory $projectRoot `
        -WindowStyle Hidden `
        -PassThru `
        -RedirectStandardOutput (Join-Path $logDirectory 'game-startup.out.log') `
        -RedirectStandardError (Join-Path $logDirectory 'game-startup.err.log')
    $startedProcesses.Add(@{ pid = $gameProcess.Id; script = 'server.py' })
    Wait-ForTcpPort $gameProcess $gamePort

    $startedProcesses | ConvertTo-Json |
        Set-Content -LiteralPath $pidFile -Encoding UTF8
    Write-Output "Website is available locally: $baseUrl/ (HTTP $healthStatus)"
    Write-Output "Payment endpoint responds locally: /webhooks/payments (HTTP $webhookStatus for control GET)"
    Write-Output "Game server is listening locally on 127.0.0.1:$gamePort."
    Write-Output "Transaction log: $(Join-Path $logDirectory 'payments.log')"
    if ($scheme -eq 'https') {
        Write-Output 'HTTPS is local only. The certificate must be trusted by the system/browser; this does not create public ingress.'
    }
    Write-Output 'To stop these processes, run: .\Start_Tortunga_Local.ps1 -Stop'
}
catch {
    foreach ($entry in $startedProcesses) {
        Stop-Process -Id $entry.pid -ErrorAction SilentlyContinue
    }
    throw
}
