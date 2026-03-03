# SHA256 Checksums - KADAS Altair Plugin v0.3.0

## Package Integrity Verification

Verify the integrity of downloaded files using SHA256 checksums:

```powershell
# Windows PowerShell
Get-FileHash kadas_altair_plugin_full_v0.3.0.zip -Algorithm SHA256
```

```bash
# Linux/macOS
shasum -a 256 kadas_altair_plugin_full_v0.3.0.zip
```

---

## Checksums

### kadas_altair_plugin_full_v0.3.0.zip
- **Size**: 1.60 MB (1,675,153 bytes)
- **SHA256**: `2BE0260A2CB1B9EAA504A89EC7C414A72D78F83C543B8B06CAC938CEBAC911E3`
- **Build**: 2026-02-28 10:03:43
- **Changes**:
  - � Added Bearer token authentication for Copernicus COG preview/download
  - ➕ Added username/password fields in Copernicus settings (secure storage)
  - 🐛 Fixed HTTP 403 error when loading Copernicus COGs via GDAL
  - � Fixed download timeout by sending OAuth2 token in requests
  - 📦 Package filename now includes version number

---

## Verification Steps

### Windows PowerShell
```powershell
# Download plugin
Invoke-WebRequest -Uri "https://github.com/mlanini/kadas-altair/releases/download/v0.3.0/kadas_altair_plugin_full_v0.3.0.zip" -OutFile "kadas_altair_plugin_full_v0.3.0.zip"

# Verify checksum
$expectedHash = "2BE0260A2CB1B9EAA504A89EC7C414A72D78F83C543B8B06CAC938CEBAC911E3"
$actualHash = (Get-FileHash kadas_altair_plugin_full_v0.3.0.zip -Algorithm SHA256).Hash

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
