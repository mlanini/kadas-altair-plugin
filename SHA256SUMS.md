# SHA256 Checksums - KADAS Altair Plugin v0.4.1

## Package Integrity Verification

Verify the integrity of downloaded files using SHA256 checksums:

```powershell
# Windows PowerShell
Get-FileHash kadas_altair_plugin_full_v0.4.1.zip -Algorithm SHA256
```

```bash
# Linux/macOS
shasum -a 256 kadas_altair_plugin_full_v0.4.1.zip
```

---

## Checksums

### kadas_altair_plugin_full_v0.4.1.zip
- **Size**: 0.16 MB (165,420 bytes)
- **SHA256**: `A774306CED1D944AFF10C000D7E0F5914BFCE501C674298AC9443001BAACAA51`
- **Build**: 2026-03-31 12:09:58
- **Build mode**: `KADAS_SKIP_PIP=1` (no pip dependency install step)

---

## Verification Steps

### Windows PowerShell
```powershell
# Verify checksum
$expectedHash = "A774306CED1D944AFF10C000D7E0F5914BFCE501C674298AC9443001BAACAA51"
$actualHash = (Get-FileHash kadas_altair_plugin_full_v0.4.1.zip -Algorithm SHA256).Hash

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
echo "A774306CED1D944AFF10C000D7E0F5914BFCE501C674298AC9443001BAACAA51  kadas_altair_plugin_full_v0.4.1.zip" | shasum -a 256 --check
# Expected output: kadas_altair_plugin_full_v0.4.1.zip: OK
```

---

## Generated On
- **Date**: 2026-03-31
- **Plugin Version**: 0.4.1
- **Package**: kadas_altair_plugin_full_v0.4.1.zip
- **Packaging**: `python package_plugin_full.py` with `KADAS_SKIP_PIP=1`

---

**Repository**: https://github.com/mlanini/kadas-altair  
**Release**: https://github.com/mlanini/kadas-altair/releases/tag/v0.4.1
