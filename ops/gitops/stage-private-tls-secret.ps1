[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$PfxPath,
    [Parameter(Mandatory)][string]$PrivateEnvironmentRoot,
    [Parameter(Mandatory)][string]$OutputRelativePath,
    [Parameter(Mandatory)][string]$Namespace,
    [Parameter(Mandatory)][string]$SecretName,
    [SecureString]$PfxPassword,
    [switch]$ReplaceExisting
)

# Converts one PFX into one SOPS-encrypted kubernetes.io/tls Secret.
# Plaintext PEM is held only in process memory and is never printed or written.
$ErrorActionPreference = 'Stop'
if (-not $PfxPassword) { $PfxPassword = Read-Host 'PFX password' -AsSecureString }
if (-not (Test-Path -LiteralPath $PfxPath -PathType Leaf)) { throw 'PFX package was not found.' }
if (-not (Test-Path -LiteralPath $PrivateEnvironmentRoot -PathType Container)) { throw 'Private environment root was not found.' }

$privateRoot = (Resolve-Path -LiteralPath $PrivateEnvironmentRoot).Path
$sopsConfig = Join-Path $privateRoot '.sops.yaml'
if (-not (Test-Path -LiteralPath $sopsConfig -PathType Leaf)) { throw 'Private environment SOPS configuration was not found.' }
if ($OutputRelativePath -match '(^|[\\/])\.\.([\\/]|$)' -or [IO.Path]::IsPathRooted($OutputRelativePath)) { throw 'Output path must be relative to the private environment root.' }
$outputPath = Join-Path $privateRoot $OutputRelativePath
$outputParent = Split-Path -Parent $outputPath
if (-not (Test-Path -LiteralPath $outputParent -PathType Container)) { throw 'Output parent directory was not found.' }
if ((Test-Path -LiteralPath $outputPath) -and -not $ReplaceExisting) { throw 'Refusing to overwrite an existing encrypted Secret without -ReplaceExisting.' }
if ($Namespace -notmatch '^[a-z0-9]([-a-z0-9]*[a-z0-9])?$' -or $SecretName -notmatch '^[a-z0-9]([-a-z0-9]*[a-z0-9])?$') { throw 'Namespace or Secret name is invalid.' }

$ptr = [IntPtr]::Zero
$password = $null
$certificate = $null
$privateKey = $null
$plainTempPath = $null
$encryptedTempPath = $null
$encryptionSucceeded = $false
try {
    $ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($PfxPassword)
    $password = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr)
    $certificate = [Security.Cryptography.X509Certificates.X509Certificate2]::new(
        $PfxPath, $password, (
            [Security.Cryptography.X509Certificates.X509KeyStorageFlags]::EphemeralKeySet -bor
            [Security.Cryptography.X509Certificates.X509KeyStorageFlags]::Exportable
        )
    )
    if (-not $certificate.HasPrivateKey) { throw 'PFX does not contain a private key.' }

    $privateKey = [Security.Cryptography.X509Certificates.RSACertificateExtensions]::GetRSAPrivateKey($certificate)
    if ($null -eq $privateKey) {
        $privateKey = [Security.Cryptography.X509Certificates.ECDsaCertificateExtensions]::GetECDsaPrivateKey($certificate)
    }
    if ($null -eq $privateKey) { throw 'PFX key algorithm is unsupported.' }

    $certPem = $certificate.ExportCertificatePem().TrimEnd()
    $keyPem = $privateKey.ExportPkcs8PrivateKeyPem().TrimEnd()
    $indent = { param([string]$text) (($text -split "`r?`n" | ForEach-Object { '    ' + $_ }) -join "`n") }
    $plainYaml = @"
apiVersion: v1
kind: Secret
metadata:
  name: $SecretName
  namespace: $Namespace
type: kubernetes.io/tls
stringData:
  tls.crt: |
$(& $indent $certPem)
  tls.key: |
$(& $indent $keyPem)
"@

    # Windows SOPS treats /dev/stdin and - as literal paths. Create a short-lived
    # plaintext file beside the destination, with the encrypted-file suffix so
    # the private repository's path-based SOPS creation rule applies; remove it
    # in finally. SOPS writes an encrypted sibling temporary file first, so an
    # existing Secret is retained until encryption has succeeded.
    $plainTempPath = Join-Path $outputParent ('.faang-tls-' + [guid]::NewGuid().ToString('N') + '.sops.yaml')
    $encryptedTempPath = Join-Path $outputParent ('.faang-tls-' + [guid]::NewGuid().ToString('N') + '.encrypted.sops.yaml')
    [IO.File]::WriteAllText($plainTempPath, $plainYaml, [Text.UTF8Encoding]::new($false))
    $startInfo = [Diagnostics.ProcessStartInfo]::new()
    $startInfo.FileName = 'sops'
    $startInfo.ArgumentList.Add('--encrypt')
    $startInfo.ArgumentList.Add('--config')
    $startInfo.ArgumentList.Add($sopsConfig)
    $startInfo.ArgumentList.Add('--input-type')
    $startInfo.ArgumentList.Add('yaml')
    $startInfo.ArgumentList.Add('--output-type')
    $startInfo.ArgumentList.Add('yaml')
    $startInfo.ArgumentList.Add('--output')
    $startInfo.ArgumentList.Add($encryptedTempPath)
    $startInfo.ArgumentList.Add($plainTempPath)
    $startInfo.UseShellExecute = $false
    $startInfo.RedirectStandardError = $true
    $process = [Diagnostics.Process]::new()
    $process.StartInfo = $startInfo
    if (-not $process.Start()) { throw 'Unable to start SOPS.' }
    $errorOutput = $process.StandardError.ReadToEnd()
    $process.WaitForExit()
    if ($process.ExitCode -ne 0 -or -not (Test-Path -LiteralPath $encryptedTempPath -PathType Leaf)) { throw ('SOPS encryption failed: ' + ($errorOutput.Trim() | Select-Object -First 1)) }
    Move-Item -LiteralPath $encryptedTempPath -Destination $outputPath -Force
    $encryptionSucceeded = $true
    Write-Output "encrypted_tls_secret_staged=$OutputRelativePath"
}
finally {
    if ($privateKey) { $privateKey.Dispose() }
    if ($certificate) { $certificate.Dispose() }
    if ($ptr -ne [IntPtr]::Zero) { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr) }
    if ($plainTempPath) { Remove-Item -LiteralPath $plainTempPath -Force -ErrorAction SilentlyContinue }
    if ($encryptedTempPath) { Remove-Item -LiteralPath $encryptedTempPath -Force -ErrorAction SilentlyContinue }
    Remove-Variable password,plainYaml,certPem,keyPem -ErrorAction SilentlyContinue
}
