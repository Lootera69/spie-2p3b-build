param(
    [ValidateRange(1, 65535)][int]$Port = 8766,
    [string]$Bank,
    [string]$PlatformVerifier,
    [string]$WordNet,
    [string]$OpenEnglishWordNet,
    [switch]$NoBrowser
)

$ErrorActionPreference = 'Stop'
$brainbloomPython = Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $brainbloomPython)) {
    throw 'Create the engine environment first: py -3.12 -m venv .venv; ./.venv/Scripts/python.exe -m pip install -e .'
}

# Discover only the known sibling projects. Both are optional, read-only inputs.
if (-not $Bank) {
    $defaultBank = Join-Path $PSScriptRoot '../puzzle-batch/output/validated'
    if (Test-Path -LiteralPath $defaultBank) { $Bank = $defaultBank }
}
if (-not $PlatformVerifier) {
    $defaultVerifier = Join-Path $PSScriptRoot '../../BrainBloom/lib/forge/verify.ts'
    if ((Test-Path -LiteralPath $defaultVerifier) -and (Get-Command node -ErrorAction SilentlyContinue)) {
        $PlatformVerifier = $defaultVerifier
    }
}
$brainbloomArgs = @('-m', 'spie.questions.brainbloom', 'serve', '--port', $Port)
if ($Bank) { $brainbloomArgs += @('--bank', (Resolve-Path -LiteralPath $Bank).Path) }
if ($PlatformVerifier) { $brainbloomArgs += @('--platform-verifier', (Resolve-Path -LiteralPath $PlatformVerifier).Path) }
if ($WordNet) { $brainbloomArgs += @('--wordnet', (Resolve-Path -LiteralPath $WordNet).Path) }
if ($OpenEnglishWordNet) { $brainbloomArgs += @('--oewn', (Resolve-Path -LiteralPath $OpenEnglishWordNet).Path) }
if (-not $NoBrowser) { $brainbloomArgs += '--open' }
Write-Host 'BrainBloom local workshop. Keep this terminal open; Ctrl+C stops the server.'
Push-Location -LiteralPath $PSScriptRoot
try {
    & $brainbloomPython @brainbloomArgs
    exit $LASTEXITCODE
} finally {
    Pop-Location
}
