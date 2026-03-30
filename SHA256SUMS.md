# SHA256 Checksums - KADAS Altair Plugin v0.4.0

## Package Integrity Verification

Verify the integrity of downloaded files using SHA256 checksums:

```powershell
# Windows PowerShell
Get-FileHash kadas_altair_plugin_full_v0.4.0.zip -Algorithm SHA256
```

```bash
# Linux/macOS
shasum -a 256 kadas_altair_plugin_full_v0.4.0.zip
```

---

## Checksums

### kadas_altair_plugin_full_v0.4.0.zip
- **Size**: 0.15 MB (162,478 bytes)
- **SHA256**: `2B6259DB5CA64603EE3356C983828A3176C09C23A15932D91B337B3057611503`
- **Build**: 2026-03-30 21:47:24
- **Changes**:
  - 🗺️ Enhanced Copernicus STAC connector with OAuth2 authentication
  - 📦 Bundled pystac-client and owslib libraries
  - 🔧 Improved settings UI with connector-specific configurations
  - ✨ Updated search interface and results display
  - 📝 Updated metadata to reflect 11 data sources

---

## Verification Steps

### Windows PowerShell
```powershell
# Download plugin
Invoke-WebRequest -Uri "https://github.com/mlanini/kadas-altair/releases/download/v0.4.0/kadas_altair_plugin_full_v0.4.0.zip" -OutFile "kadas_altair_plugin_full_v0.4.0.zip"

# Verify checksum
$expectedHash = "2B6259DB5CA64603EE3356C983828A3176C09C23A15932D91B337B3057611503"
$actualHash = (Get-FileHash kadas_altair_plugin_full_v0.4.0.zip -Algorithm SHA256).Hash

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
wget https://github.com/mlanini/kadas-altair/releases/download/v0.4.0/kadas_altair_plugin_full_v0.4.0.zip

# Verify checksum
echo "2B6259DB5CA64603EE3356C983828A3176C09C23A15932D91B337B3057611503  kadas_altair_plugin_full_v0.4.0.zip" | shasum -a 256 --check

# Should output: kadas_altair_plugin_full_v0.4.0.zip: OK
```

---

## What This Means

- **Checksum Match (✅)**: File downloaded correctly, safe to install
- **Checksum Mismatch (❌)**: File corrupted or tampered with, **DO NOT INSTALL**

---

## Generated On
- **Date**: 2026-03-30
- **Plugin Version**: 0.4.0
- **Package**: kadas_altair_plugin_full_v0.4.0.zip

---

## Additional Security

For maximum security, verify the Git tag signature:

```bash
# Clone repository
git clone https://github.com/mlanini/kadas-altair.git
cd kadas-altair

# Verify tag signature (if GPG signed)
git tag -v v0.4.0

# Build from source
python package_plugin_full.py
```

---

**Repository**: https://github.com/mlanini/kadas-altair  
**Release**: https://github.com/mlanini/kadas-altair/releases/tag/v0.4.0
