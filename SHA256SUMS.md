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
- **Size**: 0.19 MB (197,238 bytes)
- **SHA256**: `95A09E01551FE3B19D7F20AAE6054715921F5A7B6DF192FA586D1CCA3746F9C1`
- **Build**: 2026-04-01 18:21:03
- **Build mode**: `KADAS_SKIP_PIP=1` (no pip dependency install step)

---

## Verification Steps

### Windows PowerShell
```powershell
# Verify checksum
$expectedHash = "95A09E01551FE3B19D7F20AAE6054715921F5A7B6DF192FA586D1CCA3746F9C1"
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
echo "95A09E01551FE3B19D7F20AAE6054715921F5A7B6DF192FA586D1CCA3746F9C1  kadas_altair_plugin_full_v0.4.2.zip" | shasum -a 256 --check
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
