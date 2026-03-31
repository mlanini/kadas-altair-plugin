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
- **Size**: 0.16 MB (166,125 bytes)
- **SHA256**: `A09F71A63FCAB19A67DFA3C04894F8E34E479D3C59BB7CE6A4A39EE28E40A228`
- **Build**: 2026-03-31 12:21:00
- **Build mode**: `KADAS_SKIP_PIP=1` (no pip dependency install step)

---

## Verification Steps

### Windows PowerShell
```powershell
# Verify checksum
$expectedHash = "A09F71A63FCAB19A67DFA3C04894F8E34E479D3C59BB7CE6A4A39EE28E40A228"
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
echo "A09F71A63FCAB19A67DFA3C04894F8E34E479D3C59BB7CE6A4A39EE28E40A228  kadas_altair_plugin_full_v0.4.1.zip" | shasum -a 256 --check
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
