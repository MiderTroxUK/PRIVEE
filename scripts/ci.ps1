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

    # Lot 3.3 — contrôle des écritures directes : toute écriture métier passe par
    # MutationService. Les motifs .save_node( / .save_arc( sont interdits dans
    # supplyscore\web_ui\ et run_app.py (périmètre limité pour l'instant :
    # orchestrator.py garde le droit d'écrire tant que l'intégration E3.I n'a
    # pas rebranché ses appels).
    Write-Host ""
    Write-Host "=== contrôle des écritures directes (MutationService) ===" -ForegroundColor Cyan
    $ScanFiles = @()
    $WebUiDir = Join-Path $RepoRoot "supplyscore\web_ui"
    if (Test-Path $WebUiDir) {
        $ScanFiles += @(Get-ChildItem -Path $WebUiDir -Recurse -Filter "*.py" |
                Select-Object -ExpandProperty FullName)
    }
    $RunAppFile = Join-Path $RepoRoot "run_app.py"
    if (Test-Path $RunAppFile) {
        $ScanFiles += $RunAppFile
    }
    $DirectWrites = @()
    if ($ScanFiles.Count -gt 0) {
        $DirectWrites = @(Select-String -Path $ScanFiles -Pattern '\.save_node\(', '\.save_arc\(')
    }
    if ($DirectWrites.Count -gt 0) {
        Write-Host "Écritures directes interdites (passer par MutationService) :" -ForegroundColor Red
        foreach ($Hit in $DirectWrites) {
            $RelativePath = $Hit.Path.Substring($RepoRoot.Length + 1)
            Write-Host ("  {0}:{1} : {2}" -f $RelativePath, $Hit.LineNumber, $Hit.Line.Trim()) -ForegroundColor Red
        }
        Write-Host ""
        Write-Host "ÉCHEC : étape « contrôle des écritures directes » ($($DirectWrites.Count) occurrence(s)). Pipeline interrompu." -ForegroundColor Red
        exit 1
    }
    Write-Host "OK : contrôle des écritures directes" -ForegroundColor Green

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
