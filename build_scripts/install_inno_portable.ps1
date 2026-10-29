param([Parameter(Mandatory = $true)][string] $TargetDirectory)

$ErrorActionPreference = "Stop"
$targetPath = [IO.Path]::GetFullPath($TargetDirectory)
if (Test-Path -LiteralPath $targetPath) { throw "Compiler directory already exists: $targetPath" }
$downloadDirectory = Join-Path (Split-Path -Parent $targetPath) ("inno-download-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $downloadDirectory -Force | Out-Null
$installerPath = Join-Path $downloadDirectory "innosetup-6.7.4.exe"
$downloadUrl = "https://github.com/jrsoftware/issrc/releases/download/is-6_7_4/innosetup-6.7.4.exe"
$expectedHash = "A549929319F9120716677C685535CA4671E4B937B5FDC87E2585F32D8EB30E8C"
Invoke-WebRequest -Uri $downloadUrl -OutFile $installerPath -UseBasicParsing
if ((Get-FileHash -LiteralPath $installerPath -Algorithm SHA256).Hash -ne $expectedHash) {
    throw "Inno Setup compiler download does not match pinned SHA-256."
}
$signature = Get-AuthenticodeSignature -LiteralPath $installerPath
if ($signature.Status -ne "Valid" -or $signature.SignerCertificate.Subject -notmatch "Pyrsys B\.V\.") {
    throw "Inno Setup compiler signature is invalid."
}
# Official portable mode avoids installed-program registration and shortcuts:
# https://jrsoftware.org/ishelp/topic_technotes.htm
$arguments = @("/PORTABLE=1", "/CURRENTUSER", "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/NOICONS", ('/DIR="{0}"' -f $targetPath), ('/LOG="{0}"' -f (Join-Path $downloadDirectory "portable-install.log")))
$process = Start-Process -FilePath $installerPath -ArgumentList $arguments -WindowStyle Hidden -Wait -PassThru
$compilerPath = Join-Path $targetPath "ISCC.exe"
if ($process.ExitCode -ne 0 -or -not (Test-Path -LiteralPath $compilerPath)) {
    throw "Portable compiler installation failed. See $downloadDirectory"
}
Write-Output $compilerPath
