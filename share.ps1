$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$port = 8000
$py   = ".\.venv\Scripts\python.exe"
$set  = "--settings=config.settings.tunnel"

if (-not (Test-Path $py)) { throw "No .venv found in $PSScriptRoot" }
if (-not (Get-Command cloudflared -ErrorAction SilentlyContinue)) {
    throw "cloudflared missing. Run: winget install Cloudflare.cloudflared"
}

# Lock the owner dashboard for the public link
$env:DEMO_OPEN_LOGIN = $(if ($args -contains "-demo") { "1" } else { "0" })
$env:DJANGO_SETTINGS_MODULE = "config.settings.tunnel"

# Free the port if an old server is still running
Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
    ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }

Write-Host "`n[1/4] Checks" -ForegroundColor Cyan
& $py manage.py check $set
Write-Host "`n[2/4] Migrate + static" -ForegroundColor Cyan
& $py manage.py migrate --noinput $set
& $py manage.py collectstatic --noinput $set | Out-Null

Write-Host "`n[3/4] Local server http://127.0.0.1:$port" -ForegroundColor Cyan
$server = Start-Process $py -ArgumentList "manage.py","runserver","127.0.0.1:$port","--insecure","--noreload",$set -PassThru -NoNewWindow

try {
    $up = $false
    1..30 | ForEach-Object {
        if (-not $up) {
            try { Invoke-WebRequest "http://127.0.0.1:$port/" -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop | Out-Null; $up = $true }
            catch { if ($_.Exception.Response) { $up = $true } else { Start-Sleep -Seconds 1 } }
        }
    }
    if (-not $up) { throw "Local server did not respond in 30s." }
    Write-Host "Local server is up." -ForegroundColor Green
    Start-Process "http://127.0.0.1:$port"

    Write-Host "`n[4/4] Cloudflare tunnel: copy the https://xxxx.trycloudflare.com URL below" -ForegroundColor Cyan
    cloudflared tunnel --url "http://127.0.0.1:$port"
}
finally {
    if ($server -and -not $server.HasExited) { Stop-Process -Id $server.Id -Force }
    Write-Host "Server stopped." -ForegroundColor Yellow
}
