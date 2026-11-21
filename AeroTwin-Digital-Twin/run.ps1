<#
.SYNOPSIS
    Start the aero piston engine digital twin. DRDO / IDEX PS 26054.

.DESCRIPTION
    A thin wrapper around run.py, which does the real work. This exists only to
    find a usable Python, because on Windows "python" frequently is not one:

      * If Python has never been installed, PATH still contains a Microsoft
        Store alias at AppData\Local\Microsoft\WindowsApps\python.exe. Running
        it opens the Store and exits 0 having done nothing, so a plain
        `python run.py` silently does nothing at all.
      * The launcher itself needs to run BEFORE anything is installed, so it
        cannot rely on the project's own virtual environment existing yet.

    Preference order: the project venv, then the `py` launcher, then any
    python on PATH that is not the Store stub.

.EXAMPLE
    .\run.ps1
    .\run.ps1 --check
    .\run.ps1 --port 9000
#>

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Definition

function Test-RealPython {
    param([string]$Exe)
    if (-not $Exe) { return $false }
    # The Store alias is a zero-byte reparse point; a real interpreter answers.
    if ($Exe -like '*\WindowsApps\*') { return $false }
    try {
        $v = & $Exe -c "import sys; print(sys.version_info[0]*100+sys.version_info[1])" 2>$null
        return ($LASTEXITCODE -eq 0 -and [int]$v -ge 311)
    } catch { return $false }
}

$py = $null

$venvPy = Join-Path $root '.venv\Scripts\python.exe'
if (Test-Path $venvPy) { $py = $venvPy }

if (-not $py) {
    $launcher = Get-Command py -ErrorAction SilentlyContinue
    if ($launcher) {
        $cand = & py -3 -c "import sys; print(sys.executable)" 2>$null
        if ($LASTEXITCODE -eq 0 -and (Test-RealPython $cand)) { $py = $cand }
    }
}

if (-not $py) {
    foreach ($c in (Get-Command python, python3 -ErrorAction SilentlyContinue)) {
        if (Test-RealPython $c.Source) { $py = $c.Source; break }
    }
}

if (-not $py) {
    Write-Host ''
    Write-Host 'No usable Python 3.11+ was found.' -ForegroundColor Red
    Write-Host ''
    Write-Host 'If typing "python" opens the Microsoft Store, that is a stub,'
    Write-Host 'not an interpreter. Install Python from python.org (tick "Add'
    Write-Host 'python.exe to PATH"), open a new terminal, and run this again.'
    Write-Host ''
    exit 1
}

& $py (Join-Path $root 'run.py') @args
exit $LASTEXITCODE
