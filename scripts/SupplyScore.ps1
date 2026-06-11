<#
.SYNOPSIS
    Lanceur 1-clic de SupplyScore (Lot 17.3).

.DESCRIPTION
    Résout le Python du venv (.venv\Scripts\python.exe) relativement à la
    racine du dépôt, puis lance le serveur web local via supplyscore.cli avec
    --open-browser : le navigateur par défaut s'ouvre sur l'application une
    fois le serveur démarré. Tous les arguments passés au script sont
    transmis tels quels à la CLI (--demo, --port, --db-dir, ...).

.EXAMPLE
    .\scripts\SupplyScore.ps1
    .\scripts\SupplyScore.ps1 --demo --port 8099
#>
$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $Python)) {
    Write-Host "Python introuvable : $Python" -ForegroundColor Red
    Write-Host "L'environnement n'est pas installé : lancez d'abord scripts\Installer.ps1." -ForegroundColor Yellow
    exit 1
}

Write-Host "Démarrage de SupplyScore... (Ctrl+C pour arrêter le serveur)" -ForegroundColor Cyan
Write-Host "Le navigateur s'ouvrira automatiquement sur l'application." -ForegroundColor Cyan

& $Python -m supplyscore.cli --open-browser @args
$Code = $LASTEXITCODE

if ($Code -eq 2) {
    Write-Host ""
    Write-Host "ARRÊT : base corrompue détectée — SupplyScore n'a pas été lancé." -ForegroundColor Red
    Write-Host "Restaurez une sauvegarde saine (python -m supplyscore.tools.restore) puis relancez." -ForegroundColor Yellow
}
exit $Code
