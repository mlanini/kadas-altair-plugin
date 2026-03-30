# SHA256 Checksums - KADAS Altair Plugin v0.3.1

## Package Integrity Verification

Verify the integrity of downloaded files using SHA256 checksums:

```powershell
# Windows PowerShell
Get-FileHash kadas_altair_plugin_full_v0.3.1.zip -Algorithm SHA256
```

```bash
# Linux/macOS
shasum -a 256 kadas_altair_plugin_full_v0.3.1.zip
```

---

## Checksums

### kadas_altair_plugin_full_v0.3.1.zip
- **Size**: 5.78 MB (6,056,309 bytes)
- **SHA256**: `[TO BE CALCULATED AFTER FINAL BUILD]`
- **Build**: [TO BE UPDATED]
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
Invoke-WebRequest -Uri "https://github.com/mlanini/kadas-altair/releases/download/v0.3.1/kadas_altair_plugin_full_v0.3.1.zip" -OutFile "kadas_altair_plugin_full_v0.3.1.zip"

# Verify checksum
$expectedHash = "[TO BE CALCULATED]"
$actualHash = (Get-FileHash kadas_altair_plugin_full_v0.3.1.zip -Algorithm SHA256).Hash

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
wget https://github.com/mlanini/kadas-altair/releases/download/v0.3.1/kadas_altair_plugin_full_v0.3.1.zip

# Verify checksum
echo "[TO BE CALCULATED]  kadas_altair_plugin_full_v0.3.1.zip" | shasum -a 256 --check

# Should output: kadas_altair_plugin_full_v0.3.1.zip: OK
```

---

## What This Means

- **Checksum Match (✅)**: File downloaded correctly, safe to install
- **Checksum Mismatch (❌)**: File corrupted or tampered with, **DO NOT INSTALL**

---

## Generated On
- **Date**: [TO BE UPDATED AFTER FINAL BUILD]
- **Plugin Version**: 0.3.1
- **Package**: kadas_altair_plugin_full_v0.3.1.zip

---

## Additional Security

For maximum security, verify the Git tag signature:

```bash
# Clone repository
git clone https://github.com/mlanini/kadas-altair.git
cd kadas-altair

# Verify tag signature (if GPG signed)
git tag -v v0.3.1

# Build from source
python package_plugin_full.py
```

---

**Repository**: https://github.com/mlanini/kadas-altair  
**Release**: https://github.com/mlanini/kadas-altair/releases/tag/v0.3.1
