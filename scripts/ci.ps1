<#
.SYNOPSIS
    Pipeline CI local SupplyScore : lint -> format -> typage -> tests.

.DESCRIPTION
    Exécute séquentiellement ruff check, ruff format --check, mypy puis pytest
    (avec couverture). S'arrête à la première étape en échec avec un code de
    retour non nul. Compatible Windows PowerShell 5.1 (aucun && / ||).

.PARAMETER SkipMypy
    Saute l'étape mypy.

.PARAMETER Benchmarks
    Réservé (benchmarks de performance) — no-op pour l'instant.

.PARAMETER Ui
    Réservé (tests UI navigateur) — no-op pour l'instant.

.EXAMPLE
    .\scripts\ci.ps1
    .\scripts\ci.ps1 -SkipMypy
#>
[CmdletBinding()]
param(
    [switch]$SkipMypy,
    [switch]$Benchmarks,
    [switch]$Ui
)

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$VenvScripts = Join-Path $RepoRoot ".venv\Scripts"
$Ruff = Join-Path $VenvScripts "ruff.exe"
$Mypy = Join-Path $VenvScripts "mypy.exe"
$Python = Join-Path $VenvScripts "python.exe"

foreach ($exe in @($Ruff, $Mypy, $Python)) {
    if (-not (Test-Path $exe)) {
        Write-Host "Introuvable : $exe — le venv .venv est-il créé et synchronisé ?" -ForegroundColor Red
        exit 1
    }
}

function Invoke-Step {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$Exe,
        [Parameter(Mandatory = $true)][string[]]$StepArgs
    )
    Write-Host ""
    Write-Host "=== $Name ===" -ForegroundColor Cyan
    & $Exe @StepArgs
    if ($LASTEXITCODE -ne 0) {
        Write-Host ""
        Write-Host "ÉCHEC : étape « $Name » (exit $LASTEXITCODE). Pipeline interrompu." -ForegroundColor Red
        exit $LASTEXITCODE
    }
    Write-Host "OK : $Name" -ForegroundColor Green
}

Push-Location $RepoRoot
try {
    Invoke-Step -Name "ruff check" -Exe $Ruff -StepArgs @(
        "check", "supplyscore", "run_app.py", "tests"
    )

    Invoke-Step -Name "ruff format --check" -Exe $Ruff -StepArgs @(
        "format", "--check", "supplyscore", "run_app.py", "tests"
    )

    if ($SkipMypy) {
        Write-Host ""
        Write-Host "mypy : étape sautée (-SkipMypy)." -ForegroundColor Yellow
    }
    else {
        Invoke-Step -Name "mypy" -Exe $Mypy -StepArgs @(
            "supplyscore", "run_app.py"
        )
    }

    Invoke-Step -Name "pytest (+ couverture)" -Exe $Python -StepArgs @(
        "-m", "pytest", "tests",
        "--cov=supplyscore", "--cov-report=term", "--cov-report=xml"
    )

    if ($Benchmarks) {
        Write-Host ""
        Write-Host "Benchmarks : réservé, pas encore implémenté (no-op)." -ForegroundColor Yellow
    }
    if ($Ui) {
        Write-Host ""
        Write-Host "Tests UI : réservé, pas encore implémenté (no-op)." -ForegroundColor Yellow
    }

    Write-Host ""
    Write-Host "CI locale : toutes les étapes sont vertes." -ForegroundColor Green
    exit 0
}
finally {
    Pop-Location
}
