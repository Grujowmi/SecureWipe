#Requires -Version 5.1
<#
.SYNOPSIS
    SecureWipe - install.ps1
    Installation des dependances Windows
.EXAMPLE
    powershell.exe -ExecutionPolicy Bypass -File install.ps1
#>

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$PythonMinVersion = [Version]"3.10.0"

function Write-Header($text) {
    Write-Host ""
    Write-Host "  $text" -ForegroundColor Cyan
    Write-Host ("  " + ("-" * $text.Length)) -ForegroundColor DarkBlue
}

function Write-Ok($text)   { Write-Host "  [OK] $text" -ForegroundColor Green  }
function Write-Warn($text) { Write-Host "  [!]  $text" -ForegroundColor Yellow }
function Write-Err($text)  { Write-Host "  [X]  $text" -ForegroundColor Red    }
function Write-Info($text) { Write-Host "  ->   $text" -ForegroundColor White  }

Write-Host ""
Write-Host "  +------------------------------------------+" -ForegroundColor Cyan
Write-Host "  |      SecureWipe -- Installation          |" -ForegroundColor Cyan
Write-Host "  +------------------------------------------+" -ForegroundColor Cyan
Write-Host ""

$IsAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator
)

if (-not $IsAdmin) {
    Write-Err "Ce script doit etre execute en tant qu'Administrateur."
    Write-Info "Clic droit sur install.ps1 -> Executer en tant qu'administrateur"
    Write-Host ""
    Read-Host "Appuyez sur Entree pour quitter"
    exit 1
}

Write-Ok "Droits administrateur confirmes"

Write-Header "[1/4] Verification de Python"

$PythonCmd = $null

foreach ($cmd in @("python3", "python", "py")) {
    try {
        $ver = & $cmd --version 2>&1
        if ($ver -match "Python (\d+\.\d+\.\d+)") {
            $foundVer = [Version]$matches[1]
            if ($foundVer -ge $PythonMinVersion) {
                $PythonCmd = $cmd
                Write-Ok "Python $foundVer trouve ($cmd)"
                break
            } else {
                Write-Warn "Python $foundVer trouve mais trop ancien (minimum 3.10)"
            }
        }
    } catch {}
}

if (-not $PythonCmd) {
    Write-Warn "Python 3.10+ non trouve. Tentative via winget..."
    try {
        winget install Python.Python.3.12 --silent --accept-package-agreements --accept-source-agreements
        $machinePath = [System.Environment]::GetEnvironmentVariable("PATH", "Machine")
        $userPath    = [System.Environment]::GetEnvironmentVariable("PATH", "User")
        $env:PATH    = $machinePath + ";" + $userPath
        $PythonCmd   = "python"
        Write-Ok "Python installe via winget"
    } catch {
        Write-Err "Impossible d'installer Python automatiquement."
        Write-Info "Telechargez Python 3.10+ sur https://www.python.org/downloads/"
        Write-Info "Cochez 'Add Python to PATH' lors de l'installation"
        Write-Host ""
        Read-Host "Appuyez sur Entree pour quitter"
        exit 1
    }
}

Write-Header "[2/4] Installation des dependances Python"

$RequirementsFile = Join-Path $ScriptDir "requirements.txt"

if (-not (Test-Path $RequirementsFile)) {
    Write-Err "requirements.txt non trouve dans $ScriptDir"
    exit 1
}

try {
    Write-Info "pip install -r requirements.txt..."
    & $PythonCmd -m pip install -r $RequirementsFile --quiet --upgrade
    Write-Ok "Dependances Python installees"
} catch {
    Write-Err "Erreur pip : $_"
    Write-Info "Commande manuelle : $PythonCmd -m pip install rich reportlab qrcode[pil] Pillow psutil"
    exit 1
}

Write-Header "[3/4] Verification des outils Windows"

$tools = @{
    "manage-bde" = "Gestion BitLocker (natif Windows)"
    "diskpart"   = "Gestion disques (natif Windows)"
    "cipher"     = "Chiffrement EFS (natif Windows)"
}

foreach ($tool in $tools.Keys) {
    $found = Get-Command $tool -ErrorAction SilentlyContinue
    if ($found) {
        Write-Ok "$tool -- $($tools[$tool])"
    } else {
        Write-Warn "$tool non trouve -- $($tools[$tool])"
    }
}

try {
    $null = Get-PhysicalDisk -ErrorAction Stop
    Write-Ok "Get-PhysicalDisk disponible"
} catch {
    Write-Warn "Get-PhysicalDisk non disponible -- fallback WMI sera utilise"
}

Write-Header "[4/4] Verification finale"

try {
    $check = & $PythonCmd -c "import rich, reportlab, qrcode, PIL; print('OK')" 2>&1
    if ($check -eq "OK") {
        Write-Ok "Toutes les dependances Python sont disponibles"
    } else {
        Write-Err "Dependances Python incompletes : $check"
        exit 1
    }
} catch {
    Write-Err "Erreur de verification : $_"
    exit 1
}

Write-Host ""
Write-Host "  +------------------------------------------+" -ForegroundColor Green
Write-Host "  |  Installation terminee avec succes !     |" -ForegroundColor Green
Write-Host "  +------------------------------------------+" -ForegroundColor Green
Write-Host ""
Write-Host "  Lancement normal (admin requis) :" -ForegroundColor White
Write-Host "  $PythonCmd securewipe.py" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Mode mock (test sans effacement reel) :" -ForegroundColor White
Write-Host "  Set SECUREWIPE_MOCK=1 puis : $PythonCmd securewipe.py" -ForegroundColor Cyan
Write-Host ""

Read-Host "Appuyez sur Entree pour quitter"
