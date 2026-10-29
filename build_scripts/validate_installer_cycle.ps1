param(
    [string] $InnoCompiler = "build_validation\tools\inno-6.7.4\ISCC.exe",
    [string] $Executable = "build_validation\run-20261029-001\dist\TTSLive.exe"
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$compilerPath = (Resolve-Path -LiteralPath $InnoCompiler).Path
$executablePath = (Resolve-Path -LiteralPath $Executable).Path
$validationRoot = [IO.Path]::GetFullPath((Join-Path $projectRoot "build_validation"))
$cycleDirectory = Join-Path $validationRoot ("install-cycle-" + [guid]::NewGuid().ToString("N"))
$installDirectory = Join-Path $cycleDirectory "installed"
$validationId = "{E8019612-CC81-4BF8-A17E-A5075CDE2411}_is1"

function Assert-IsolatedPath {
    param([string] $Path)
    $absolute = [IO.Path]::GetFullPath($Path)
    if (-not $absolute.StartsWith($validationRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Validation target escapes the project validation directory: $absolute"
    }
    $ancestor = $absolute
    while ($ancestor -and $ancestor.Length -ge $validationRoot.Length) {
        if ((Test-Path -LiteralPath $ancestor) -and ((Get-Item -LiteralPath $ancestor -Force).Attributes -band [IO.FileAttributes]::ReparsePoint)) {
            throw "Validation paths must not contain reparse points: $ancestor"
        }
        $ancestor = Split-Path -Parent $ancestor
    }
    return $absolute
}

function Invoke-IsolatedProcess {
    param([string] $Program, [string[]] $Arguments)
    $null = Assert-IsolatedPath $installDirectory
    $process = Start-Process -FilePath $Program -ArgumentList $Arguments -WindowStyle Hidden -PassThru
    if (-not $process.WaitForExit(120000)) {
        Stop-Process -Id $process.Id -Force
        throw "Validation process exceeded 120 seconds: $Program"
    }
    if ($process.ExitCode -ne 0) { throw "Validation process failed ($($process.ExitCode)): $Program" }
}

$registryPaths = @(
    "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\$validationId",
    "HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\$validationId",
    "HKCU:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\$validationId",
    "HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\$validationId"
)
function Assert-NoRegistration {
    foreach ($registryPath in $registryPaths) {
        if (Test-Path -LiteralPath $registryPath) { throw "Unexpected validation registration: $registryPath" }
    }
}

$null = Assert-IsolatedPath $installDirectory
if (Test-Path -LiteralPath $cycleDirectory) { throw "Cycle directory must be new." }
Assert-NoRegistration
New-Item -ItemType Directory -Path (Join-Path $cycleDirectory "installers") -Force | Out-Null
$originalHash = (Get-FileHash -LiteralPath $executablePath -Algorithm SHA256).Hash
$installers = @{}
foreach ($version in @("0.0.1", "0.0.2")) {
    $auditPath = Join-Path $cycleDirectory ("installer-" + $version + "-preprocessed.iss")
    $wrapperPath = Join-Path $cycleDirectory ("installer-" + $version + ".iss")
    $wrapper = @"
#define TTSLiveVersion "$version"
#define TTSLiveExePath "$executablePath"
#define TTSLiveValidationBuild 1
#define TTSLiveValidationDirectory "$installDirectory"
[Setup]
SourceDir=$projectRoot
#include "$projectRoot\installer.iss"
#expr SaveToFile("$auditPath")
"@
    Set-Content -LiteralPath $wrapperPath -Value $wrapper -Encoding UTF8
    & $compilerPath "/Q" ("/O" + (Join-Path $cycleDirectory "installers")) ("/FValidation-" + $version) $wrapperPath
    if ($LASTEXITCODE -ne 0) { throw "Validation installer compilation failed: $version" }
    $audit = Get-Content -LiteralPath $auditPath -Raw
    if ($audit -match '(?im)^\[(Icons|Run|Registry|UninstallRun)\]' -or
        $audit -notmatch '(?im)^CreateUninstallRegKey=no\s*$' -or
        $audit -notmatch 'E8019612-CC81-4BF8-A17E-A5075CDE2411' -or
        $audit -match '2E3AF7D8-A9F3-4D0C-B91F-5600A6F58C11') {
        throw "Preprocessed installer does not meet the isolation requirements."
    }
    $installers[$version] = Join-Path $cycleDirectory ("installers\Validation-" + $version + ".exe")
}

$installedExecutable = Join-Path $installDirectory "TTSLive.exe"
$processLog = Join-Path $cycleDirectory "install-0.0.1.log"
Invoke-IsolatedProcess -Program $installers["0.0.1"] -Arguments @("/SP-", "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/NOICONS", "/NOCLOSEAPPLICATIONS", "/NORESTARTAPPLICATIONS", ('/DIR="{0}"' -f $installDirectory), ('/LOG="{0}"' -f $processLog))
Assert-NoRegistration
if ((Get-FileHash -LiteralPath $installedExecutable -Algorithm SHA256).Hash -ne $originalHash) { throw "Installed executable differs from the validated executable." }
$smokeOutput = Join-Path $cycleDirectory "installed-smoke.json"
$previousDataDirectory = $env:TTSLIVE_DATA_DIR
try {
    $env:TTSLIVE_DATA_DIR = Join-Path $installDirectory "data"
    Invoke-IsolatedProcess -Program $installedExecutable -Arguments @("--smoke-test", "--smoke-output", ('"{0}"' -f $smokeOutput))
} finally {
    $env:TTSLIVE_DATA_DIR = $previousDataDirectory
}
if (-not (Get-Content -LiteralPath $smokeOutput -Raw | ConvertFrom-Json).ok) { throw "Installed executable smoke test failed." }
$environmentFixture = Join-Path $installDirectory ".env"
$personalFixture = Join-Path $installDirectory "data\personal.txt"
[IO.File]::WriteAllText($environmentFixture, "VALIDATION_CONTEXT=installer-cycle`r`n", [Text.UTF8Encoding]::new($false))
[IO.File]::WriteAllText($personalFixture, "Personal validation fixture, no secrets.`r`n", [Text.UTF8Encoding]::new($false))
$fixtureHashes = @{}
foreach ($fixture in @($environmentFixture, $personalFixture)) { $fixtureHashes[$fixture] = (Get-FileHash -LiteralPath $fixture -Algorithm SHA256).Hash }
$processLog = Join-Path $cycleDirectory "install-0.0.2.log"
Invoke-IsolatedProcess -Program $installers["0.0.2"] -Arguments @("/SP-", "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/NOICONS", "/NOCLOSEAPPLICATIONS", "/NORESTARTAPPLICATIONS", ('/DIR="{0}"' -f $installDirectory), ('/LOG="{0}"' -f $processLog))
Assert-NoRegistration
foreach ($fixture in $fixtureHashes.Keys) {
    if ((Get-FileHash -LiteralPath $fixture -Algorithm SHA256).Hash -ne $fixtureHashes[$fixture]) { throw "Upgrade changed a personal fixture." }
}
$uninstallerPath = (Resolve-Path -LiteralPath (Join-Path $installDirectory "unins000.exe")).Path
$null = Assert-IsolatedPath $uninstallerPath
Invoke-IsolatedProcess -Program $uninstallerPath -Arguments @("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", ('/LOG="{0}"' -f (Join-Path $cycleDirectory "uninstall.log")))
for ($attempt = 0; $attempt -lt 40 -and (Test-Path -LiteralPath $uninstallerPath); $attempt++) { Start-Sleep -Milliseconds 250 }
if (Test-Path -LiteralPath $installedExecutable) { throw "Uninstall did not remove the executable." }
foreach ($fixture in $fixtureHashes.Keys) {
    if ((Get-FileHash -LiteralPath $fixture -Algorithm SHA256).Hash -ne $fixtureHashes[$fixture]) { throw "Uninstall changed a personal fixture." }
}
Assert-NoRegistration
if ((Get-FileHash -LiteralPath $executablePath -Algorithm SHA256).Hash -ne $originalHash) { throw "Original executable was changed." }
$manifestPath = Join-Path $validationRoot "validation.json"
$manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
$evidence = [pscustomobject]@{
    success = $true; directory = $cycleDirectory; target = $installDirectory
    versions = @("0.0.1", "0.0.2"); production_installer_executed = $false
    installed_executable_smoke = (Get-Content -LiteralPath $smokeOutput -Raw | ConvertFrom-Json)
    upgrade_preserved_fixture_hashes = $true; uninstall_preserved_fixture_hashes = $true
    uninstall_removed_executable = $true; no_uninstall_registration = $true
    preprocessed_icons_run_registry_sections_absent = $true
    fixture_hashes = $fixtureHashes
}
$manifest | Add-Member -MemberType NoteProperty -Name isolated_installer_cycle -Value $evidence -Force
$manifest.limits | Add-Member -MemberType NoteProperty -Name validation_installer_executed -Value $true -Force
$manifest.limits | Add-Member -MemberType NoteProperty -Name installation_test_scope -Value "Validation build only: unique AppId, no registration, icons or launch; production installer was not executed." -Force
$manifest.limits.installation_upgrade_uninstall_tested = $true
$manifest | ConvertTo-Json -Depth 30 | Set-Content -LiteralPath $manifestPath -Encoding UTF8
$evidence | ConvertTo-Json -Depth 10
