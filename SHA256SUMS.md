# SHA256 Checksums - KADAS Altair Plugin v0.4.2

## Package Integrity Verification

Verify the integrity of downloaded files using SHA256 checksums:

```powershell
# Windows PowerShell
Get-FileHash kadas_altair_plugin_full_v0.4.2.zip -Algorithm SHA256
```

```bash
# Linux/macOS
shasum -a 256 kadas_altair_plugin_full_v0.4.2.zip
```

---

## Checksums

### kadas_altair_plugin_full_v0.4.2.zip
- **Size**: 0.18 MB (193,592 bytes)
- **SHA256**: `0AEDC6FEE4BD6A61EFFBA41FB983D2C59ECE1192358A3E2C682593D1D7472F98`
- **Build**: 2026-04-01 10:48:59
- **Build mode**: `KADAS_SKIP_PIP=1` (no pip dependency install step)

---

## Verification Steps

### Windows PowerShell
```powershell
# Verify checksum
$expectedHash = "0AEDC6FEE4BD6A61EFFBA41FB983D2C59ECE1192358A3E2C682593D1D7472F98"
$actualHash = (Get-FileHash kadas_altair_plugin_full_v0.4.2.zip -Algorithm SHA256).Hash

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
echo "0AEDC6FEE4BD6A61EFFBA41FB983D2C59ECE1192358A3E2C682593D1D7472F98  kadas_altair_plugin_full_v0.4.2.zip" | shasum -a 256 --check
# Expected output: kadas_altair_plugin_full_v0.4.2.zip: OK
```

---

## Generated On
- **Date**: 2026-04-01
- **Plugin Version**: 0.4.2
- **Package**: kadas_altair_plugin_full_v0.4.2.zip
- **Packaging**: `python package_plugin_full.py` with `KADAS_SKIP_PIP=1`

---

**Repository**: https://github.com/mlanini/kadas-altair  
**Release**: https://github.com/mlanini/kadas-altair/releases/tag/v0.4.2
