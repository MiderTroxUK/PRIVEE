<#
.SYNOPSIS
    Installateur local de SupplyScore (Lot 17.3) — idempotent.

.DESCRIPTION
    Installe (ou met à jour) l'environnement d'exécution de SupplyScore :

    1. vérifie que l'outil « uv » est disponible (sinon, affiche comment
       l'installer et s'arrête) ;
    2. synchronise l'environnement virtuel .venv via « uv sync » en mode
       copie (UV_LINK_MODE=copy — fiable sur tous les systèmes de fichiers
       Windows, dossiers synchronisés compris) ;
    3. vérifie que le paquet supplyscore s'importe correctement.

    Le script peut être relancé sans risque : « uv sync » est idempotent.
    Une fois l'installation terminée, lancez l'application avec
    scripts\SupplyScore.bat (double-clic) ou scripts\SupplyScore.ps1.

.EXAMPLE
    .\scripts\Installer.ps1
#>
$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot

Write-Host "=== Installation de SupplyScore ===" -ForegroundColor Cyan
Write-Host "Racine du dépôt : $RepoRoot"

# --- Étape 1/3 : vérifier uv -------------------------------------------------------
Write-Host ""
Write-Host "Étape 1/3 : vérification de l'outil « uv »..." -ForegroundColor Cyan
$Uv = Get-Command uv -ErrorAction SilentlyContinue
if ($null -eq $Uv) {
    Write-Host "L'outil « uv » est introuvable sur ce poste." -ForegroundColor Red
    Write-Host "Installez-le puis relancez ce script :" -ForegroundColor Yellow
    Write-Host "  winget install astral-sh.uv" -ForegroundColor Yellow
    Write-Host "  (ou : powershell -c `"irm https://astral.sh/uv/install.ps1 | iex`")" -ForegroundColor Yellow
    exit 1
}
Write-Host "OK : uv trouvé ($($Uv.Source))." -ForegroundColor Green

# --- Étape 2/3 : synchroniser l'environnement ---------------------------------------
Write-Host ""
Write-Host "Étape 2/3 : synchronisation de l'environnement (.venv) via « uv sync »..." -ForegroundColor Cyan
$env:UV_LINK_MODE = "copy"
Push-Location $RepoRoot
try {
    uv sync
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ÉCHEC : « uv sync » a retourné le code $LASTEXITCODE." -ForegroundColor Red
        exit $LASTEXITCODE
    }
}
finally {
    Pop-Location
}
Write-Host "OK : environnement synchronisé." -ForegroundColor Green

# --- Étape 3/3 : vérifier l'installation --------------------------------------------
Write-Host ""
Write-Host "Étape 3/3 : vérification de l'installation..." -ForegroundColor Cyan
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    Write-Host "ÉCHEC : Python du venv introuvable ($Python)." -ForegroundColor Red
    exit 1
}
$Version = & $Python -c "import supplyscore; print(supplyscore.__version__)"
if ($LASTEXITCODE -ne 0) {
    Write-Host "ÉCHEC : le paquet supplyscore ne s'importe pas." -ForegroundColor Red
    exit 1
}
Write-Host "OK : supplyscore v$Version importé correctement." -ForegroundColor Green

Write-Host ""
Write-Host "Installation terminée." -ForegroundColor Green
Write-Host "Lancez l'application avec : scripts\SupplyScore.bat (double-clic possible)" -ForegroundColor Cyan
exit 0
