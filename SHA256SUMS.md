# SHA256 Checksums - KADAS Altair Plugin v0.5.0

## Package Integrity Verification

Verify the integrity of downloaded files using SHA256 checksums:

```powershell
# Windows PowerShell
Get-FileHash kadas_altair_plugin_full_v0.5.0.zip -Algorithm SHA256
```

```bash
# Linux/macOS
shasum -a 256 kadas_altair_plugin_full_v0.5.0.zip
```

---

## Checksums

### kadas_altair_plugin_full_v0.5.0.zip
- **Size**: 1.04 MB (1,089,588 bytes)
- **SHA256**: `AE381A7461F89C8C2A6F0E7AD20E6D4A62F22763EE43E6B368C92A0D125426CA`
- **Build**: 2026-08-08 14:56:05
- **Build mode**: `KADAS_SKIP_PIP=1` (no pip dependency install step)

---

## Verification Steps

### Windows PowerShell
```powershell
# Verify checksum
$expectedHash = "AE381A7461F89C8C2A6F0E7AD20E6D4A62F22763EE43E6B368C92A0D125426CA"
$actualHash = (Get-FileHash kadas_altair_plugin_full_v0.5.0.zip -Algorithm SHA256).Hash

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
echo "AE381A7461F89C8C2A6F0E7AD20E6D4A62F22763EE43E6B368C92A0D125426CA  kadas_altair_plugin_full_v0.5.0.zip" | shasum -a 256 --check
# Expected output: kadas_altair_plugin_full_v0.5.0.zip: OK
```

---

## Generated On
- **Date**: 2026-08-08
- **Plugin Version**: 0.5.0
- **Package**: kadas_altair_plugin_full_v0.5.0.zip
- **Packaging**: `python package_plugin_full.py` with `KADAS_SKIP_PIP=1`

---

**Repository**: https://github.com/mlanini/kadas-altair-plugin  
**Release**: https://github.com/mlanini/kadas-altair/releases/tag/v0.5.0
