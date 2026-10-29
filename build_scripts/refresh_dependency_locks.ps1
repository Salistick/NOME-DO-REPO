$ErrorActionPreference = "Stop"
Set-Location -LiteralPath (Split-Path -Parent $PSScriptRoot)
$pythonExecutable = Join-Path (Get-Location) ".venv\Scripts\python.exe"
foreach ($name in @("requirements", "requirements-build", "requirements-dev")) {
    & $pythonExecutable -m piptools compile --generate-hashes --allow-unsafe --no-emit-index-url --no-emit-trusted-host ("--output-file=" + $name + ".txt") ($name + ".in")
    if ($LASTEXITCODE -ne 0) { throw "Lock generation failed: $name" }
}
& $pythonExecutable -m pip install --require-hashes --only-binary=:all: -r requirements-dev.txt
if ($LASTEXITCODE -ne 0) { throw "Locked dependency install failed" }
& $pythonExecutable -m pip check
if ($LASTEXITCODE -ne 0) { throw "Dependency validation failed" }
& $pythonExecutable -m unittest discover -s tests -v
if ($LASTEXITCODE -ne 0) { throw "Regression tests failed" }
