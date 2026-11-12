# SHA256 Checksums - KADAS Altair Plugin

## Current verified package: v0.6.1

Verify the integrity of the packaged plugin with:

```powershell
Get-FileHash kadas_altair_plugin_full_v0.6.1.zip -Algorithm SHA256
```

```bash
shasum -a 256 kadas_altair_plugin_full_v0.6.1.zip
```

### Package

- **File**: `kadas_altair_plugin_full_v0.6.1.zip`
- **Size**: 2,638,093 bytes
- **SHA256**: `18A1F7C0233EAEB63692D2E7E066A598BFB7520CB1A4870990F83A84385A046E`
- **Version**: 0.6.1
- **Build date**: 2026-11-12
- **Build mode**: full package with dependencies installed and verified using QGIS Python 3.12.

The archive passed ZIP integrity validation and contains the v0.6.1 metadata, Custom STAC connector, and bundled dependencies.

## Previous verified package: v0.6.0

### Package Integrity Verification

```powershell
Get-FileHash kadas_altair_plugin_full_v0.6.0.zip -Algorithm SHA256
```

```bash
shasum -a 256 kadas_altair_plugin_full_v0.6.0.zip
```

### Package

- **File**: `kadas_altair_plugin_full_v0.6.0.zip`
- **Size**: 2,574,560 bytes
- **SHA256**: `0D893C1AA4256DB46022F4406F9D811889BA244CEA18ED25919A6ABCCFAB7DE8`
- **Version**: 0.6.0 (previous release)
- **Build date**: 2026-11-11
- **Build mode**: offline rebuild using the previously bundled dependencies and local PyEphem 4.2.1; PyPI access was unavailable.

The archive passed ZIP integrity validation and a bundled-SGP4 smoke test. See [RELEASE_NOTES.md](RELEASE_NOTES.md) for release highlights.

**Repository**: https://github.com/mlanini/kadas-altair-plugin
