param(
    [Parameter(Mandatory = $true)]
    [string[]] $Files
)

$ErrorActionPreference = "Stop"

$certBase64 = $env:WINDOWS_CODESIGN_CERT_BASE64
$certPassword = $env:WINDOWS_CODESIGN_CERT_PASSWORD
$timestampUrl = $env:WINDOWS_CODESIGN_TIMESTAMP_URL

if ([string]::IsNullOrWhiteSpace($timestampUrl)) {
    $timestampUrl = "http://timestamp.digicert.com"
}

if ([string]::IsNullOrWhiteSpace($certBase64) -or [string]::IsNullOrWhiteSpace($certPassword)) {
    Write-Host "Code signing skipped: WINDOWS_CODESIGN_CERT_BASE64/WINDOWS_CODESIGN_CERT_PASSWORD not configured."
    exit 0
}

function Get-SignToolPath {
    $command = Get-Command signtool.exe -ErrorAction SilentlyContinue
    if ($command) {
        return $command.Source
    }

    $kitsRoot = Join-Path ${env:ProgramFiles(x86)} "Windows Kits\10\bin"
    if (Test-Path $kitsRoot) {
        $candidate = Get-ChildItem -Path $kitsRoot -Recurse -Filter signtool.exe |
            Where-Object { $_.FullName -match "\\x64\\signtool\.exe$" } |
            Sort-Object FullName -Descending |
            Select-Object -First 1
        if ($candidate) {
            return $candidate.FullName
        }
    }

    throw "signtool.exe not found. Install Windows SDK or run on a GitHub Windows runner."
}

$pfxPath = Join-Path $env:TEMP ("ttslive-codesign-" + [guid]::NewGuid().ToString("N") + ".pfx")
$cert = $null

try {
    [IO.File]::WriteAllBytes($pfxPath, [Convert]::FromBase64String($certBase64))
    $securePassword = ConvertTo-SecureString $certPassword -AsPlainText -Force
    $cert = Import-PfxCertificate -FilePath $pfxPath -CertStoreLocation Cert:\CurrentUser\My -Password $securePassword
    if (-not $cert) {
        throw "Unable to import code signing certificate."
    }

    $signTool = Get-SignToolPath
    foreach ($file in $Files) {
        if (-not (Test-Path $file)) {
            throw "File not found for signing: $file"
        }

        Write-Host "Signing $file"
        & $signTool sign /fd SHA256 /td SHA256 /tr $timestampUrl /sha1 $cert.Thumbprint $file
        if ($LASTEXITCODE -ne 0) {
            throw "signtool failed for $file"
        }

        & $signTool verify /pa /v $file
        if ($LASTEXITCODE -ne 0) {
            throw "signature verification failed for $file"
        }
    }
}
finally {
    if (Test-Path $pfxPath) {
        Remove-Item -LiteralPath $pfxPath -Force
    }
    if ($cert) {
        Remove-Item -LiteralPath "Cert:\CurrentUser\My\$($cert.Thumbprint)" -ErrorAction SilentlyContinue
    }
}
