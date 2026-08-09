# SHA256 Checksums - KADAS Altair Plugin v0.5.1

## Package Integrity Verification

Verify the integrity of downloaded files using SHA256 checksums:

```powershell
# Windows PowerShell
Get-FileHash kadas_altair_plugin_full_v0.5.1.zip -Algorithm SHA256
```

```bash
# Linux/macOS
shasum -a 256 kadas_altair_plugin_full_v0.5.1.zip
```

---

## Checksums

### kadas_altair_plugin_full_v0.5.1.zip
- **Size**: 1.04 MB (1,090,324 bytes)
- **SHA256**: `318089AF2FF513E028C7D2267BE5B95585081A11BF07510484741117FE4A68F9`
- **Build**: 2026-08-09 06:06:51
- **Build mode**: `KADAS_SKIP_PIP=1` (no pip dependency install step)

---

## Verification Steps

### Windows PowerShell
```powershell
# Verify checksum
$expectedHash = "318089AF2FF513E028C7D2267BE5B95585081A11BF07510484741117FE4A68F9"
$actualHash = (Get-FileHash kadas_altair_plugin_full_v0.5.1.zip -Algorithm SHA256).Hash

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
echo "318089AF2FF513E028C7D2267BE5B95585081A11BF07510484741117FE4A68F9  kadas_altair_plugin_full_v0.5.1.zip" | shasum -a 256 --check
# Expected output: kadas_altair_plugin_full_v0.5.1.zip: OK
```

---

## Generated On
- **Date**: 2026-08-08
- **Plugin Version**: 0.5.1
- **Package**: kadas_altair_plugin_full_v0.5.1.zip
- **Packaging**: `python package_plugin_full.py` with `KADAS_SKIP_PIP=1`

---

**Repository**: https://github.com/mlanini/kadas-altair-plugin  
**Release**: https://github.com/mlanini/kadas-altair-plugin/releases/tag/v0.5.1
