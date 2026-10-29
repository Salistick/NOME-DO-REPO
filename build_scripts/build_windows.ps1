param(
    [string] $PythonPath = ".venv\Scripts\python.exe",
    [string] $Version = "dev",
    [string] $ArtifactRoot = "",
    [string] $InnoCompiler = "",
    [switch] $SkipDependencyInstall,
    [switch] $SkipTests
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$pythonExecutable = (Resolve-Path -LiteralPath $PythonPath).Path
if ([string]::IsNullOrWhiteSpace($ArtifactRoot)) {
    $buildName = "build-" + (Get-Date -Format "yyyyMMdd-HHmmss") + "-" + [guid]::NewGuid().ToString("N").Substring(0, 8)
    $ArtifactRoot = Join-Path $projectRoot ("dist\" + $buildName)
}
$artifactDirectory = [IO.Path]::GetFullPath($ArtifactRoot)
if (Test-Path -LiteralPath $artifactDirectory) {
    throw "Artifact directory already exists: $artifactDirectory. Choose a new directory."
}
New-Item -ItemType Directory -Path $artifactDirectory | Out-Null

function Invoke-Checked {
    param([string] $Program, [string[]] $Arguments)
    & $Program @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Program failed with exit code $LASTEXITCODE" }
}

if (-not $SkipDependencyInstall) {
    Invoke-Checked -Program $pythonExecutable -Arguments @("-m", "pip", "install", "--require-hashes", "--only-binary=:all:", "-r", "requirements-dev.txt")
}
Invoke-Checked -Program $pythonExecutable -Arguments @("-m", "pip", "check")
if (-not $SkipTests) {
    Invoke-Checked -Program $pythonExecutable -Arguments @("-m", "ruff", "check", ".")
    Invoke-Checked -Program $pythonExecutable -Arguments @("-m", "unittest", "discover", "-s", "tests", "-v")
}
$env:TTSLIVE_VERSION = $Version
$env:PYINSTALLER_CONFIG_DIR = Join-Path $artifactDirectory "pyinstaller-cache"
Invoke-Checked -Program $pythonExecutable -Arguments @("build_scripts\prepare_windows_build_assets.py")
Invoke-Checked -Program $pythonExecutable -Arguments @("-m", "PyInstaller", "--noconfirm", "--clean", "--workpath", (Join-Path $artifactDirectory "work"), "--distpath", (Join-Path $artifactDirectory "dist"), "bot_live.spec")
$executablePath = Join-Path $artifactDirectory "dist\TTSLive.exe"
$smokeOutput = Join-Path $artifactDirectory "smoke.json"
$env:TTSLIVE_DATA_DIR = Join-Path $artifactDirectory "smoke-data"
$smokeProcess = Start-Process -FilePath $executablePath -ArgumentList @("--smoke-test", "--smoke-output", ('"{0}"' -f $smokeOutput)) -WindowStyle Hidden -PassThru
if (-not $smokeProcess.WaitForExit(120000)) {
    Stop-Process -Id $smokeProcess.Id -Force
    throw "Packaged smoke test exceeded 120 seconds."
}
if ($smokeProcess.ExitCode -ne 0 -or -not (Test-Path -LiteralPath $smokeOutput)) {
    throw "Packaged smoke test failed. See $smokeOutput"
}
$smokeResult = Get-Content -LiteralPath $smokeOutput -Raw | ConvertFrom-Json
if (-not $smokeResult.ok) { throw "Packaged smoke test reported a failure. See $smokeOutput" }
if (-not [string]::IsNullOrWhiteSpace($InnoCompiler)) {
    Invoke-Checked -Program $InnoCompiler -Arguments @(("/O" + (Join-Path $artifactDirectory "dist")), ("/DTTSLiveVersion=" + $Version), ("/DTTSLiveExePath=" + $executablePath), "installer.iss")
}
Write-Host "Build validated: $artifactDirectory"
