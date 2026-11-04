# Runs the whole test suite against a local PostgreSQL (includes the stock-race test SQLite skips).
# Usage:  powershell -ExecutionPolicy Bypass -File .\scripts\run_tests_postgres.ps1
param(
    [string]$DbName = "royalcream",
    [string]$DbUser = "royal",
    [string]$DbHost = "localhost",
    [int]$DbPort = 5432
)
$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $PSScriptRoot
$py = Join-Path $root ".venv\Scripts\python.exe"
Set-Location $root

$secure = Read-Host "PostgreSQL password for user '$DbUser'" -AsSecureString
$bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
$plain = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
[Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)

$env:DB_ENGINE = "postgresql"
$env:DB_NAME = $DbName
$env:DB_USER = $DbUser
$env:DB_PASSWORD = $plain
$env:DB_HOST = $DbHost
$env:DB_PORT = [string]$DbPort
try {
    Write-Host "Running migrations check and tests on PostgreSQL ($DbHost`:$DbPort / $DbName) ..." -ForegroundColor Cyan
    $out = & $py manage.py test tests 2>&1 | ForEach-Object { "$_" }
    $exit = $LASTEXITCODE
    $out | Where-Object { $_ -match '^(Found |Ran |OK|FAILED|ERROR:|FAIL:)' }
    if ($exit -ne 0) {
        Write-Host "`n--- FAILURE DETAILS ---" -ForegroundColor Red
        $start = 0
        for ($i = 0; $i -lt $out.Count; $i++) { if ($out[$i] -match '^={20,}') { $start = $i; break } }
        $out[$start..($out.Count - 1)] | Where-Object { $_ -notmatch ' (INFO|WARNING|ERROR) (apps|django)' }
    } else {
        Write-Host "`nALL GREEN ON POSTGRESQL (the concurrency test ran, it is no longer skipped)" -ForegroundColor Green
    }
}
finally {
    Remove-Item Env:DB_PASSWORD -ErrorAction SilentlyContinue
}