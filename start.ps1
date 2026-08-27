# SORA // NEXUS 起動スクリプト
#
#   .\start.ps1              SORA + トンネル + ブラウザ自動起動
#   .\start.ps1 -NoTunnel    外部公開なし（ローカルのみ）
#   .\start.ps1 -Kiosk       ブラウザを全画面で開く（展示用）
#   .\start.ps1 -NoBrowser   ブラウザを開かない
#
# ローカルからの直接アクセスは認証なし。
# トンネル経由のアクセスにだけ .env の ADMIN_USER / ADMIN_PASSWORD を要求する。

param(
    [switch]$NoTunnel,
    [switch]$NoBrowser,
    [switch]$Kiosk
)

$root        = $PSScriptRoot
$python      = Join-Path $root "venv\Scripts\python.exe"
$cloudflared = "C:\Program Files (x86)\cloudflared\cloudflared.exe"
$port        = 8000

function Get-EnvValue([string]$key) {
    $line = Select-String -Path (Join-Path $root ".env") -Pattern "^$key=" -ErrorAction SilentlyContinue |
            Select-Object -First 1
    if ($line) { return $line.Line.Split("=", 2)[1].Trim() }
    return $null
}

function Test-Port([int]$p) {
    try {
        $s = New-Object Net.Sockets.TcpClient
        $s.Connect("127.0.0.1", $p)
        $s.Close()
        return $true
    } catch { return $false }
}

function Find-Browser {
    $candidates = @(
        "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
        "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
        "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe",
        "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe",
        "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe"
    )
    return $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
}

# ── 既存プロセスの掃除 ─────────────────────────────────────────
if (Test-Port $port) {
    Write-Host "ポート $port を使用中のプロセスを停止します..." -ForegroundColor DarkGray
    Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty OwningProcess | Sort-Object -Unique |
        ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue }
    Get-Process cloudflared -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2
}

# ── トンネル ───────────────────────────────────────────────────
$tunnel = $null
$tunnelUrl = $null

if (-not $NoTunnel) {
    if (-not (Test-Path $cloudflared)) {
        Write-Host "cloudflared が見つかりません: winget install --id Cloudflare.cloudflared" -ForegroundColor Yellow
    }
    elseif (-not (Get-EnvValue "ADMIN_PASSWORD")) {
        Write-Host "ADMIN_PASSWORD が .env に未設定のためトンネルを起動しません。" -ForegroundColor Red
        Write-Host "認証なしで公開すると誰でもカメラ映像を見られます。" -ForegroundColor Red
    }
    else {
        $log = Join-Path $env:TEMP "sora_tunnel.log"
        Remove-Item $log, "$log.out" -Force -ErrorAction SilentlyContinue
        $tunnel = Start-Process -FilePath $cloudflared `
            -ArgumentList "tunnel", "--url", "http://localhost:$port" `
            -RedirectStandardError $log -RedirectStandardOutput "$log.out" `
            -WindowStyle Hidden -PassThru
    }
}

# ── SORA 本体 ──────────────────────────────────────────────────
Write-Host "SORA を起動しています" -NoNewline
$sora = Start-Process -FilePath $python -ArgumentList "app.py" `
    -WorkingDirectory $root -WindowStyle Hidden -PassThru

for ($i = 0; $i -lt 60; $i++) {
    if (Test-Port $port) { break }
    Start-Sleep -Seconds 1
    Write-Host "." -NoNewline
}
Write-Host ""

if (-not (Test-Port $port)) {
    Write-Host "SORA の起動に失敗しました。" -ForegroundColor Red
    if ($tunnel -and -not $tunnel.HasExited) { Stop-Process -Id $tunnel.Id -Force -ErrorAction SilentlyContinue }
    exit 1
}

# ── トンネル URL の取得 ────────────────────────────────────────
if ($tunnel) {
    $log = Join-Path $env:TEMP "sora_tunnel.log"
    for ($i = 0; $i -lt 20 -and -not $tunnelUrl; $i++) {
        if (Test-Path $log) {
            $tunnelUrl = (Select-String -Path $log -Pattern "https://[a-z0-9-]+\.trycloudflare\.com" -AllMatches |
                          ForEach-Object { $_.Matches.Value } | Select-Object -First 1)
        }
        if (-not $tunnelUrl) { Start-Sleep -Seconds 1 }
    }
}

# ── 案内 ───────────────────────────────────────────────────────
Write-Host ""
Write-Host "  SORA 起動完了" -ForegroundColor Green
Write-Host ""
Write-Host "  本体      http://localhost:$port/"
Write-Host "  管理画面  http://localhost:$port/admin"
if ($tunnelUrl) {
    Write-Host ""
    Write-Host "  外部から  $tunnelUrl/admin" -ForegroundColor Cyan
    Write-Host "            $(Get-EnvValue 'ADMIN_USER') / $(Get-EnvValue 'ADMIN_PASSWORD')"
    Write-Host "            ※URLは起動のたびに変わります" -ForegroundColor DarkGray
}
Write-Host ""

# ── ブラウザ ───────────────────────────────────────────────────
if (-not $NoBrowser) {
    $browser = Find-Browser
    $url = "http://localhost:$port/"
    if ($browser) {
        $browserArgs = if ($Kiosk) { @("--kiosk", $url) } else { @($url) }
        Start-Process -FilePath $browser -ArgumentList $browserArgs | Out-Null
    } else {
        Start-Process $url | Out-Null
    }
    Write-Host "  ブラウザを開きました。Space キーで起動してください。" -ForegroundColor Yellow
} else {
    Write-Host "  ブラウザで開き、Space キーを押してください。" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "  終了するには、このウィンドウで Ctrl+C を押してください。" -ForegroundColor DarkGray
Write-Host ""

# ── 終了待ち ───────────────────────────────────────────────────
try {
    Wait-Process -Id $sora.Id
}
finally {
    Write-Host ""
    Write-Host "終了処理中..." -ForegroundColor DarkGray
    if ($sora   -and -not $sora.HasExited)   { Stop-Process -Id $sora.Id   -Force -ErrorAction SilentlyContinue }
    if ($tunnel -and -not $tunnel.HasExited) { Stop-Process -Id $tunnel.Id -Force -ErrorAction SilentlyContinue }
    Write-Host "SORA とトンネルを停止しました。"
}
