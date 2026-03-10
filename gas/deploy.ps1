<#
.SYNOPSIS
    Deploy GAS code to Google Apps Script project.
.DESCRIPTION
    Pushes AutoSetup.gs + Menu.gs to Google Sheets Apps Script.
    Requires: npm install -g @google/clasp
    First time: clasp login
.PARAMETER Action
    deploy (default) — push code to Apps Script
    status — show current deployment info
    setup — interactive setup for first-time users
.EXAMPLE
    .\deploy.ps1 deploy
    .\deploy.ps1 setup
#>

param(
    [ValidateSet("deploy", "status", "setup")]
    [string]$Action = "deploy"
)

$ErrorActionPreference = "Stop"
$ROOT = Split-Path -Parent $MyInvocation.MyCommand.Definition
$CLASP_JSON = Join-Path $ROOT ".clasp.json"

# ========== COLORS ==========
function Write-Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }
function Write-OK($msg) { Write-Host "  OK: $msg" -ForegroundColor Green }
function Write-Warn($msg) { Write-Host "  WARN: $msg" -ForegroundColor Yellow }
function Write-Err($msg) { Write-Host "  ERROR: $msg" -ForegroundColor Red }

# ========== SETUP ==========
if ($Action -eq "setup") {
    Write-Step "CIC Daily Report — GAS Deploy Setup"
    Write-Host @"

Huong dan cai dat clasp (chi can lam 1 lan):

1. Cai Node.js: https://nodejs.org/ (chon LTS)
2. Mo PowerShell, chay:
   npm install -g @google/clasp

3. Dang nhap Google:
   clasp login
   (Trinh duyet mo ra -> chon tai khoan Google -> Allow)

4. Lay Script ID:
   - Mo Google Sheets -> Extensions -> Apps Script
   - Nhin thanh dia chi, URL co dang:
     https://script.google.com/macros/s/AKfyc.../edit
   - Hoac vao Project Settings (banh rang) -> copy "Script ID"

5. Chay setup:
   .\deploy.ps1 setup
   (Paste Script ID khi duoc hoi)

"@

    # Check if clasp is installed
    try {
        $claspVersion = & clasp --version 2>&1
        Write-OK "clasp da cai: $claspVersion"
    } catch {
        Write-Err "clasp chua cai. Chay: npm install -g @google/clasp"
        exit 1
    }

    # Ask for Script ID
    $scriptId = Read-Host "`nNhap Script ID (tu Apps Script > Project Settings)"
    if (-not $scriptId -or $scriptId.Length -lt 20) {
        Write-Err "Script ID khong hop le. Phai la chuoi dai ~50 ky tu."
        exit 1
    }

    # Create .clasp.json
    $claspConfig = @{
        scriptId = $scriptId
        rootDir = "."
    } | ConvertTo-Json

    Set-Content -Path $CLASP_JSON -Value $claspConfig -Encoding UTF8
    Write-OK "Da tao $CLASP_JSON"

    # Create .claspignore
    $claspIgnore = Join-Path $ROOT ".claspignore"
    Set-Content -Path $claspIgnore -Value @"
README.md
deploy.ps1
.clasp.json
.claspignore
**/*.md
"@ -Encoding UTF8
    Write-OK "Da tao .claspignore"

    Write-Host "`nSetup hoan tat! Bay gio chay: .\deploy.ps1 deploy" -ForegroundColor Green
    exit 0
}

# ========== CHECK PREREQUISITES ==========
Write-Step "Kiem tra moi truong"

# Check clasp
try {
    $null = & clasp --version 2>&1
    Write-OK "clasp OK"
} catch {
    Write-Err "clasp chua cai. Chay: .\deploy.ps1 setup"
    exit 1
}

# Check .clasp.json
if (-not (Test-Path $CLASP_JSON)) {
    Write-Err ".clasp.json chua co. Chay: .\deploy.ps1 setup"
    exit 1
}
Write-OK ".clasp.json OK"

# Check GAS files exist
$gasFiles = @("AutoSetup.gs", "Menu.gs")
foreach ($f in $gasFiles) {
    $path = Join-Path $ROOT $f
    if (-not (Test-Path $path)) {
        Write-Err "Thieu file: $f"
        exit 1
    }
}
Write-OK "GAS files: $($gasFiles -join ', ')"

# ========== STATUS ==========
if ($Action -eq "status") {
    Write-Step "Trang thai deploy"
    Push-Location $ROOT
    try {
        & clasp status
        & clasp deployments
    } finally {
        Pop-Location
    }
    exit 0
}

# ========== DEPLOY ==========
Write-Step "Deploy GAS code"

Push-Location $ROOT
try {
    # Push code
    Write-Host "  Pushing code..." -ForegroundColor White
    $pushOutput = & clasp push --force 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Err "clasp push that bai:`n$pushOutput"
        exit 1
    }
    Write-OK "Code da push len Apps Script"

    # Show what was pushed
    Write-Host "`n  Files da deploy:" -ForegroundColor White
    foreach ($f in $gasFiles) {
        $size = (Get-Item (Join-Path $ROOT $f)).Length
        Write-Host "    - $f ($([math]::Round($size/1024, 1)) KB)" -ForegroundColor Gray
    }

    Write-Host "`nDeploy thanh cong!" -ForegroundColor Green
    Write-Host "Mo Google Sheets va reload (F5) de thay thay doi.`n" -ForegroundColor Yellow

} finally {
    Pop-Location
}
