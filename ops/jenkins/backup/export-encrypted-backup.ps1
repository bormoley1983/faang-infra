[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$OutputDirectory,
    [string]$Namespace = "jenkins",
    [string]$BackupClaim = "jenkins-home-backup",
    [securestring]$Passphrase,
    [ValidateRange(100000, 5000000)]
    [int]$KdfIterations = 600000
)

$ErrorActionPreference = "Stop"
$magic = [Text.Encoding]::ASCII.GetBytes("FAANGBK1")
$headerLength = 76
$tagLength = 32
$exporterPod = "jenkins-backup-export-$([Guid]::NewGuid().ToString('N').Substring(0, 10))"
$outputPath = $null

function Invoke-Kubectl {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)

    $result = & kubectl @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "kubectl failed: $($Arguments -join ' ')"
    }
    return $result
}

function Get-PlainText {
    param([securestring]$Value)

    $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($Value)
    try {
        return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
    } finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
    }
}

function Get-FileSha256 {
    param([string]$Path)

    $stream = [IO.File]::OpenRead($Path)
    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        return [Convert]::ToHexString($sha.ComputeHash($stream)).ToLowerInvariant()
    } finally {
        $sha.Dispose()
        $stream.Dispose()
    }
}

if (-not $Passphrase) {
    $Passphrase = Read-Host "Backup encryption passphrase" -AsSecureString
    $confirmation = Read-Host "Confirm backup encryption passphrase" -AsSecureString
    $first = Get-PlainText $Passphrase
    $second = Get-PlainText $confirmation
    try {
        if ($first -cne $second) {
            throw "Passphrases do not match."
        }
        if ($first.Length -lt 16) {
            throw "Use an encryption passphrase of at least 16 characters."
        }
    } finally {
        $first = $null
        $second = $null
    }
}

$outputDirectoryPath = [IO.Path]::GetFullPath($OutputDirectory)
[IO.Directory]::CreateDirectory($outputDirectoryPath) | Out-Null

$pod = @{
    apiVersion = "v1"
    kind = "Pod"
    metadata = @{
        name = $exporterPod
        namespace = $Namespace
        labels = @{ "app.kubernetes.io/name" = "jenkins-backup-export" }
    }
    spec = @{
        automountServiceAccountToken = $false
        restartPolicy = "Never"
        securityContext = @{ seccompProfile = @{ type = "RuntimeDefault" } }
        containers = @(@{
            name = "export"
            image = "moby/buildkit:v0.30.0-rootless@sha256:d76eb1caecac5733ef7553c1e90a1b21f1bb218cd1142d3553de0747b4a14ba9"
            imagePullPolicy = "IfNotPresent"
            command = @("sleep")
            args = @("1800")
            resources = @{
                requests = @{ cpu = "25m"; memory = "32Mi" }
                limits = @{ cpu = "250m"; memory = "128Mi" }
            }
            securityContext = @{
                allowPrivilegeEscalation = $false
                readOnlyRootFilesystem = $true
                runAsUser = 1000
                runAsGroup = 1000
                capabilities = @{ drop = @("ALL") }
            }
            volumeMounts = @(@{ name = "backup"; mountPath = "/backup"; readOnly = $true })
        })
        volumes = @(@{
            name = "backup"
            persistentVolumeClaim = @{ claimName = $BackupClaim; readOnly = $true }
        })
    }
}

try {
    $podJson = $pod | ConvertTo-Json -Depth 20 -Compress
    $podJson | & kubectl apply -f - | Out-Host
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to create the read-only backup exporter Pod."
    }
    Invoke-Kubectl -n $Namespace wait --for=condition=Ready "pod/$exporterPod" --timeout=180s | Out-Host

    $archives = @(& kubectl -n $Namespace exec $exporterPod -- find /backup -maxdepth 1 -type f -name "jenkins-home-*.tar.gz")
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to list archives on backup PVC $Namespace/$BackupClaim."
    }
    $archive = $archives | Sort-Object | Select-Object -Last 1
    if (-not $archive) {
        throw "No Jenkins backup archive exists on PVC $Namespace/$BackupClaim."
    }
    $archive = $archive.Trim()
    $sidecar = "$archive.sha256"
    $expectedHashLine = (& kubectl -n $Namespace exec $exporterPod -- cat $sidecar).Trim()
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to read the backup SHA-256 sidecar."
    }
    if ($expectedHashLine -notmatch '^([a-fA-F0-9]{64})\s+') {
        throw "The backup SHA-256 sidecar is invalid."
    }
    $expectedPlainHash = $Matches[1].ToLowerInvariant()
    $archiveName = [IO.Path]::GetFileName($archive)
    $outputPath = Join-Path $outputDirectoryPath "$archiveName.faangbak"
    if (Test-Path -LiteralPath $outputPath) {
        throw "Refusing to overwrite existing encrypted backup: $outputPath"
    }

    $salt = [byte[]]::new(16)
    $iv = [byte[]]::new(16)
    [Security.Cryptography.RandomNumberGenerator]::Fill($salt)
    [Security.Cryptography.RandomNumberGenerator]::Fill($iv)
    $plainPassphrase = Get-PlainText $Passphrase
    $passphraseBytes = [Text.Encoding]::UTF8.GetBytes($plainPassphrase)
    $plainPassphrase = $null
    $derive = [Security.Cryptography.Rfc2898DeriveBytes]::new(
        $passphraseBytes,
        $salt,
        $KdfIterations,
        [Security.Cryptography.HashAlgorithmName]::SHA256
    )
    $keyMaterial = $derive.GetBytes(64)
    $derive.Dispose()
    [Array]::Clear($passphraseBytes, 0, $passphraseBytes.Length)
    $encryptionKey = $keyMaterial[0..31]
    $authenticationKey = $keyMaterial[32..63]
    [Array]::Clear($keyMaterial, 0, $keyMaterial.Length)

    $startInfo = [Diagnostics.ProcessStartInfo]::new()
    $startInfo.FileName = (Get-Command kubectl).Source
    $startInfo.UseShellExecute = $false
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    foreach ($argument in @("-n", $Namespace, "exec", $exporterPod, "--", "cat", $archive)) {
        $startInfo.ArgumentList.Add($argument)
    }
    $process = [Diagnostics.Process]::new()
    $process.StartInfo = $startInfo
    $output = [IO.File]::Open($outputPath, [IO.FileMode]::CreateNew, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
    $aes = [Security.Cryptography.Aes]::Create()
    $plainSha = [Security.Cryptography.SHA256]::Create()
    try {
        $aes.KeySize = 256
        $aes.Mode = [Security.Cryptography.CipherMode]::CBC
        $aes.Padding = [Security.Cryptography.PaddingMode]::PKCS7
        $aes.Key = $encryptionKey
        $aes.IV = $iv

        $output.Write($magic, 0, $magic.Length)
        $iterationBytes = [BitConverter]::GetBytes($KdfIterations)
        $output.Write($iterationBytes, 0, $iterationBytes.Length)
        $output.Write($salt, 0, $salt.Length)
        $output.Write($iv, 0, $iv.Length)
        $output.Write([byte[]]::new(32), 0, 32)

        if (-not $process.Start()) {
            throw "Unable to start kubectl backup stream."
        }
        $stderrTask = $process.StandardError.ReadToEndAsync()
        $crypto = [Security.Cryptography.CryptoStream]::new(
            $output,
            $aes.CreateEncryptor(),
            [Security.Cryptography.CryptoStreamMode]::Write,
            $true
        )
        try {
            $buffer = [byte[]]::new(1MB)
            while (($count = $process.StandardOutput.BaseStream.Read($buffer, 0, $buffer.Length)) -gt 0) {
                [void]$plainSha.TransformBlock($buffer, 0, $count, $null, 0)
                $crypto.Write($buffer, 0, $count)
            }
            [void]$plainSha.TransformFinalBlock([byte[]]::new(0), 0, 0)
            $crypto.FlushFinalBlock()
        } finally {
            $crypto.Dispose()
            if ($buffer) {
                [Array]::Clear($buffer, 0, $buffer.Length)
            }
        }
        $process.WaitForExit()
        if ($process.ExitCode -ne 0) {
            throw "kubectl backup stream failed: $($stderrTask.GetAwaiter().GetResult().Trim())"
        }

        $actualPlainHash = [Convert]::ToHexString($plainSha.Hash).ToLowerInvariant()
        if ($actualPlainHash -cne $expectedPlainHash) {
            throw "Streamed archive SHA-256 does not match its cluster sidecar."
        }
        $output.Position = 44
        $output.Write($plainSha.Hash, 0, $plainSha.Hash.Length)
        $output.Flush($true)
    } catch {
        $output.Dispose()
        Remove-Item -LiteralPath $outputPath -Force -ErrorAction SilentlyContinue
        throw
    } finally {
        $plainSha.Dispose()
        $aes.Dispose()
        $process.Dispose()
        if ($output) {
            $output.Dispose()
        }
    }

    $hmac = [Security.Cryptography.HMACSHA256]::new($authenticationKey)
    $encryptedInput = [IO.File]::OpenRead($outputPath)
    try {
        $tag = $hmac.ComputeHash($encryptedInput)
    } finally {
        $encryptedInput.Dispose()
        $hmac.Dispose()
    }
    $append = [IO.File]::Open($outputPath, [IO.FileMode]::Append, [IO.FileAccess]::Write, [IO.FileShare]::None)
    try {
        $append.Write($tag, 0, $tag.Length)
        $append.Flush($true)
    } finally {
        $append.Dispose()
    }

    $encryptedHash = Get-FileSha256 $outputPath
    $metadata = [ordered]@{
        format = "FAANGBK1"
        createdUtc = [DateTime]::UtcNow.ToString("o")
        archiveName = $archiveName
        plaintextSha256 = $expectedPlainHash
        encryptedSha256 = $encryptedHash
        encryptedBytes = (Get-Item -LiteralPath $outputPath).Length
        encryption = "AES-256-CBC-HMAC-SHA256"
        kdf = "PBKDF2-HMAC-SHA256"
        kdfIterations = $KdfIterations
    }
    $metadataPath = "$outputPath.metadata.json"
    $metadata | ConvertTo-Json | Set-Content -LiteralPath $metadataPath -Encoding utf8NoBOM

    Write-Host "Encrypted Jenkins backup exported successfully."
    Write-Host "Backup: $outputPath"
    Write-Host "Metadata: $metadataPath"
    Write-Host "Plaintext SHA-256: $expectedPlainHash"
    Write-Host "Encrypted SHA-256: $encryptedHash"
} finally {
    & kubectl -n $Namespace delete pod $exporterPod --ignore-not-found=true --wait=false 2>$null | Out-Null
    if ($encryptionKey) {
        [Array]::Clear($encryptionKey, 0, $encryptionKey.Length)
    }
    if ($authenticationKey) {
        [Array]::Clear($authenticationKey, 0, $authenticationKey.Length)
    }
}
