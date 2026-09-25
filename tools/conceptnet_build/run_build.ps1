# Launch (or resume) the ConceptNet 2.3b build as a DETACHED background process.
#
# Safe to run any number of times: the build takes a single-writer PID lock, so if one is already
# running a second launch just exits at once. If a previous build died (crash / logoff / reboot),
# this relaunch resumes from the durable verdict cache and reaches the byte-identical artifact -
# every proof already completed is reused, none is redone. That is the "cannot break" guarantee:
# the process may die, the work never does.
#
# Usage:  powershell -NoProfile -ExecutionPolicy Bypass -File run_build.ps1
# Monitor: the line count of .cache\verdicts.tsv climbs toward ~3,244; .cache\full_build.log is the log.

$ErrorActionPreference = 'Stop'
$here   = $PSScriptRoot
$engine = (Resolve-Path (Join-Path $here '..\..')).Path
$python = Join-Path $engine '.venv\Scripts\python.exe'
$outlog = Join-Path $here '.cache\build_stdout.log'
$errlog = Join-Path $here '.cache\full_build.log'

# Dump path is passed RELATIVE to the engine working directory on purpose: the absolute path
# contains a space ("symbolic invention engine"), and Start-Process -ArgumentList does not quote
# array elements, so a space would split the argument. The relative path has none. Every other
# path the build uses (edge cache, verdict log, lock, output) is derived from the module location,
# not the cwd, so it is unaffected.
$buildArgs = @(
    '-m', 'tools.conceptnet_build',
    '--dump', 'tools/conceptnet_build/.cache/conceptnet-assertions-5.7.0.csv.gz',
    '--z3-rlimit', '8000000'
)

$proc = Start-Process -FilePath $python -ArgumentList $buildArgs `
    -WorkingDirectory $engine -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput $outlog -RedirectStandardError $errlog

Write-Host "launched detached build: PID $($proc.Id)"
Write-Host "  log:      $errlog"
Write-Host "  progress: (Get-Content '$(Join-Path $here '.cache\verdicts.tsv')').Count  # climbs to ~3,244"
