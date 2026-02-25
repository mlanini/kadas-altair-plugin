# SHA256 Checksums - KADAS Altair Plugin v0.2.0

## Package Integrity Verification

Verify the integrity of downloaded files using SHA256 checksums:

```powershell
# Windows PowerShell
Get-FileHash kadas_altair_plugin_full.zip -Algorithm SHA256
```

```bash
# Linux/macOS
shasum -a 256 kadas_altair_plugin_full.zip
```

---

## Checksums

### kadas_altair_plugin_full.zip
- **Size**: 1.59 MB (1,668,436 bytes)
- **SHA256**: `D7C449A13E887991EB8F10E8755BABCF2C2066E86C6A9893701783A148D5AB6D`

---

## Verification Steps

### Windows PowerShell
```powershell
# Download plugin
Invoke-WebRequest -Uri "https://github.com/mlanini/kadas-altair/releases/download/v0.2.0/kadas_altair_plugin_full.zip" -OutFile "kadas_altair_plugin_full.zip"

# Verify checksum
$expectedHash = "D7C449A13E887991EB8F10E8755BABCF2C2066E86C6A9893701783A148D5AB6D"
$actualHash = (Get-FileHash kadas_altair_plugin_full.zip -Algorithm SHA256).Hash

if ($actualHash -eq $expectedHash) {
    Write-Host "✅ Checksum verified! File is authentic." -ForegroundColor Green
} else {
    Write-Host "❌ Checksum mismatch! File may be corrupted." -ForegroundColor Red
    Write-Host "Expected: $expectedHash" -ForegroundColor Yellow
    Write-Host "Actual:   $actualHash" -ForegroundColor Yellow
}
```

### Linux/macOS
```bash
# Download plugin
wget https://github.com/mlanini/kadas-altair/releases/download/v0.2.0/kadas_altair_plugin_full.zip

# Verify checksum
echo "D7C449A13E887991EB8F10E8755BABCF2C2066E86C6A9893701783A148D5AB6D  kadas_altair_plugin_full.zip" | shasum -a 256 --check

# Should output: kadas_altair_plugin_full.zip: OK
```

---

## What This Means

- **Checksum Match (✅)**: File downloaded correctly, safe to install
- **Checksum Mismatch (❌)**: File corrupted or tampered with, **DO NOT INSTALL**

---

## Generated On
- **Date**: 2024-12-XX
- **Plugin Version**: 0.2.0
- **Package**: kadas_altair_plugin_full.zip

---

## Additional Security

For maximum security, verify the Git tag signature:

```bash
# Clone repository
git clone https://github.com/mlanini/kadas-altair.git
cd kadas-altair

# Verify tag signature (if GPG signed)
git tag -v v0.2.0

# Build from source
python package_plugin_full.py
```

---

**Repository**: https://github.com/mlanini/kadas-altair  
**Release**: https://github.com/mlanini/kadas-altair/releases/tag/v0.2.0
