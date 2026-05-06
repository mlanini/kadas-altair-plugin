# SHA256 Checksums - KADAS Altair Plugin v0.4.3

## Package Integrity Verification

Verify the integrity of downloaded files using SHA256 checksums:

```powershell
# Windows PowerShell
Get-FileHash kadas_altair_plugin_full_v0.4.3.zip -Algorithm SHA256
```

```bash
# Linux/macOS
shasum -a 256 kadas_altair_plugin_full_v0.4.3.zip
```

---

## Checksums

### kadas_altair_plugin_full_v0.4.3.zip
- **Size**: 0.19 MB (201,257 bytes)
- **SHA256**: `381393a04be79ceb8e2c9250f37cd300a83b3991a10d54577d93a17624716e97`
- **Build**: 2026-05-06 11:01:14
- **Build mode**: `KADAS_SKIP_PIP=1` (no pip dependency install step)

---

## Verification Steps

### Windows PowerShell
```powershell
# Verify checksum
$expectedHash = "381393a04be79ceb8e2c9250f37cd300a83b3991a10d54577d93a17624716e97"
$actualHash = (Get-FileHash kadas_altair_plugin_full_v0.4.3.zip -Algorithm SHA256).Hash

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
echo "381393a04be79ceb8e2c9250f37cd300a83b3991a10d54577d93a17624716e97  kadas_altair_plugin_full_v0.4.3.zip" | shasum -a 256 --check
# Expected output: kadas_altair_plugin_full_v0.4.3.zip: OK
```

---

## Generated On
- **Date**: 2026-05-06
- **Plugin Version**: 0.4.3
- **Package**: kadas_altair_plugin_full_v0.4.3.zip
- **Packaging**: `python package_plugin_full.py` with `KADAS_SKIP_PIP=1`

---

**Repository**: https://github.com/mlanini/kadas-altair  
**Release**: https://github.com/mlanini/kadas-altair/releases/tag/v0.4.2
