[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$EncryptedBackup,
    [Parameter(Mandatory = $true)]
    [string]$OutputArchive,
    [securestring]$Passphrase
)

$ErrorActionPreference = "Stop"
$magic = [Text.Encoding]::ASCII.GetBytes("FAANGBK1")
$headerLength = 76
$tagLength = 32

function Get-PlainText {
    param([securestring]$Value)

    $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($Value)
    try {
        return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
    } finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
    }
}

if (-not $Passphrase) {
    $Passphrase = Read-Host "Backup encryption passphrase" -AsSecureString
}

$encryptedPath = [IO.Path]::GetFullPath($EncryptedBackup)
$outputPath = [IO.Path]::GetFullPath($OutputArchive)
if (Test-Path -LiteralPath $outputPath) {
    throw "Refusing to overwrite existing restore output: $outputPath"
}
$fileLength = (Get-Item -LiteralPath $encryptedPath).Length
if ($fileLength -le ($headerLength + $tagLength + 16)) {
    throw "Encrypted backup is too short to be valid."
}

$input = [IO.File]::OpenRead($encryptedPath)
$reader = [IO.BinaryReader]::new($input, [Text.Encoding]::UTF8, $true)
try {
    $actualMagic = $reader.ReadBytes(8)
    if (-not [Security.Cryptography.CryptographicOperations]::FixedTimeEquals($magic, $actualMagic)) {
        throw "Unsupported encrypted backup format."
    }
    $iterations = $reader.ReadInt32()
    if ($iterations -lt 100000 -or $iterations -gt 5000000) {
        throw "Invalid PBKDF2 iteration count in backup header."
    }
    $salt = $reader.ReadBytes(16)
    $iv = $reader.ReadBytes(16)
    $expectedPlainHash = $reader.ReadBytes(32)
} finally {
    $reader.Dispose()
    $input.Dispose()
}

$plainPassphrase = Get-PlainText $Passphrase
$passphraseBytes = [Text.Encoding]::UTF8.GetBytes($plainPassphrase)
$plainPassphrase = $null
$derive = [Security.Cryptography.Rfc2898DeriveBytes]::new(
    $passphraseBytes,
    $salt,
    $iterations,
    [Security.Cryptography.HashAlgorithmName]::SHA256
)
$keyMaterial = $derive.GetBytes(64)
$derive.Dispose()
[Array]::Clear($passphraseBytes, 0, $passphraseBytes.Length)
$encryptionKey = $keyMaterial[0..31]
$authenticationKey = $keyMaterial[32..63]
[Array]::Clear($keyMaterial, 0, $keyMaterial.Length)

try {
    $tagInput = [IO.File]::OpenRead($encryptedPath)
    try {
        $tagInput.Position = $fileLength - $tagLength
        $storedTag = [byte[]]::new($tagLength)
        if ($tagInput.Read($storedTag, 0, $storedTag.Length) -ne $storedTag.Length) {
            throw "Unable to read encrypted backup authentication tag."
        }
        $tagInput.Position = 0
        $hmac = [Security.Cryptography.HMACSHA256]::new($authenticationKey)
        try {
            $remaining = $fileLength - $tagLength
            $buffer = [byte[]]::new(1MB)
            while ($remaining -gt 0) {
                $requested = [int][Math]::Min($buffer.Length, $remaining)
                $count = $tagInput.Read($buffer, 0, $requested)
                if ($count -le 0) {
                    throw "Unexpected end of encrypted backup while authenticating."
                }
                [void]$hmac.TransformBlock($buffer, 0, $count, $null, 0)
                $remaining -= $count
            }
            [void]$hmac.TransformFinalBlock([byte[]]::new(0), 0, 0)
            if (-not [Security.Cryptography.CryptographicOperations]::FixedTimeEquals($storedTag, $hmac.Hash)) {
                throw "Backup authentication failed: wrong passphrase or corrupted file."
            }
        } finally {
            $hmac.Dispose()
            if ($buffer) {
                [Array]::Clear($buffer, 0, $buffer.Length)
            }
        }
    } finally {
        $tagInput.Dispose()
    }

    $outputParent = [IO.Path]::GetDirectoryName($outputPath)
    if ($outputParent) {
        [IO.Directory]::CreateDirectory($outputParent) | Out-Null
    }
    $cipherInput = [IO.File]::OpenRead($encryptedPath)
    $plainOutput = [IO.File]::Open($outputPath, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
    $aes = [Security.Cryptography.Aes]::Create()
    try {
        $aes.KeySize = 256
        $aes.Mode = [Security.Cryptography.CipherMode]::CBC
        $aes.Padding = [Security.Cryptography.PaddingMode]::PKCS7
        $aes.Key = $encryptionKey
        $aes.IV = $iv
        $cipherInput.Position = $headerLength
        $remaining = $fileLength - $headerLength - $tagLength
        $decrypt = [Security.Cryptography.CryptoStream]::new(
            $plainOutput,
            $aes.CreateDecryptor(),
            [Security.Cryptography.CryptoStreamMode]::Write,
            $true
        )
        try {
            $buffer = [byte[]]::new(1MB)
            while ($remaining -gt 0) {
                $requested = [int][Math]::Min($buffer.Length, $remaining)
                $count = $cipherInput.Read($buffer, 0, $requested)
                if ($count -le 0) {
                    throw "Unexpected end of encrypted backup while decrypting."
                }
                $decrypt.Write($buffer, 0, $count)
                $remaining -= $count
            }
            $decrypt.FlushFinalBlock()
        } finally {
            $decrypt.Dispose()
            if ($buffer) {
                [Array]::Clear($buffer, 0, $buffer.Length)
            }
        }
        $plainOutput.Flush($true)
    } catch {
        $plainOutput.Dispose()
        Remove-Item -LiteralPath $outputPath -Force -ErrorAction SilentlyContinue
        throw
    } finally {
        $aes.Dispose()
        $plainOutput.Dispose()
        $cipherInput.Dispose()
    }

    $restoredStream = [IO.File]::OpenRead($outputPath)
    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        $actualPlainHash = $sha.ComputeHash($restoredStream)
    } finally {
        $sha.Dispose()
        $restoredStream.Dispose()
    }
    if (-not [Security.Cryptography.CryptographicOperations]::FixedTimeEquals($expectedPlainHash, $actualPlainHash)) {
        Remove-Item -LiteralPath $outputPath -Force -ErrorAction SilentlyContinue
        throw "Restored archive SHA-256 does not match the authenticated backup header."
    }

    Write-Host "Encrypted backup authenticated and restored successfully."
    Write-Host "Archive: $outputPath"
    Write-Host "SHA-256: $([Convert]::ToHexString($actualPlainHash).ToLowerInvariant())"
} finally {
    [Array]::Clear($encryptionKey, 0, $encryptionKey.Length)
    [Array]::Clear($authenticationKey, 0, $authenticationKey.Length)
}
