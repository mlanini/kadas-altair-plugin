# KADAS Altaír — Satellite Imagery Browser Plugin

**Multi-source satellite imagery browser for KADAS Albireo 2**

[![License](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Version](https://img.shields.io/badge/Version-0.4.3-success.svg)](https://github.com/mlanini/kadas-altair-plugin)
[![Status](https://img.shields.io/badge/Status-Production-success.svg)](https://github.com/mlanini/kadas-altair-plugin)
[![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/mlanini/kadas-altair-plugin)

## Screenshots

![Vantor EO Open Data Connector](screenshots/screenshot01_vantor.jpg)
![ICEYE SAR Open Data Connector](screenshots/screenshot02_iceye.jpg)
![Archive Search — Copernicus](screenshots/screenshot03_copernicus.jpg)
![Smart Tasking with orbit prediction](screenshots/screenshot04_smarttasking.jpg)

---

## Documentation

| Document | Contents |
|----------|----------|
| **[README.md](README.md)** | Overview, features, quick start (this file) |
| **[GUIDE.md](GUIDE.md)** | Installation, configuration, usage tutorial |
| **[ARCHITECTURE.md](ARCHITECTURE.md)** | System design, network stack, OpenSSL, proxy/VPN |
| **[CONTRIBUTING.md](CONTRIBUTING.md)** | Development setup, adding connectors, testing |
| **[CHANGELOG.md](CHANGELOG.md)** | Version-by-version change log |

---

## Quick Start

### Installation

Download `kadas_altair_plugin_full_vX.Y.Z.zip` and copy manually:

```powershell
# Windows
# Check you KADAS flavour first: Mil, Zivil or Light
Copy-Item -Recurse kadas_altair_plugin "$env:APPDATA\Kadas\KadasZivil\profiles\default\python\plugins\"

# Linux / macOS
cp -r kadas_altair_plugin ~/.local/share/Kadas/KadasZivil/profiles/default/python/plugins/
```

### First Use

1. Activate **KADAS Albireo** → `Settings` → `Plugins` → `KADAS Altair vx.x.x` 
2. Go to "EO" menu tab
3. Choose **Altair Open Data Panel** from Altair menu button
4. Select a connector (e.g. *Maxar Open Data*)
5. Click **Authenticate** (no credentials needed for open-data sources)
6. Pick a collection from the dropdown
7. Draw a search area or use the map extent
8. Click **Search** — results appear in the table
9. Select a scene → **Load Layer** → done

---

## Features

### Connectors

7 production-ready connectors, 1 experimental, 2 stubs:

| # | Connector | Type | Highlights | Status |
|---|-----------|------|------------|--------|
| 1 | **ICEYE SAR** | Radar | 3 collections · 196 items · 1–3 m | Production |
| 2 | **Umbra SAR** | Radar | Recursive STAC · 16–25 cm · GEC/SICD/SIDD/CPHD | Production |
| 3 | **Capella SAR** | Radar | ~1 000 images · X-band · ~1 m | Production |
| 4 | **Maxar Open Data** | Optical | 55+ disaster events · 0.3–0.5 m (Vantor STAC) | Production |
| 5 | **swisstopo RapidMapping** | Optical | Swiss emergency events · sub-meter | Production |
| 6 | **Copernicus Data Space** | Multi | Sentinel-1/2/3/5P · OAuth2 · 10 m–7 km | Production |
| 7 | **Jilin-1 Gaofen** | Optical | CGSTL constellation · 0.72 m · STAC API | Production |
| 8 | **NASA EarthData** | Multi | CMR granule search · STAC catalog | Experimental |
| 9 | **Planet** | Optical | PSScene, SkySatScene · 0.5–3 m | Stub |
| 10 | **OneAtlas** | Optical | Airbus imagery · 0.5 m | Stub |

### Search & Visualization

- **Unified search** — spatial (bbox / polygon), temporal, cloud-cover filters
- **"All Sources" mode** — query every connector in parallel (ThreadPoolExecutor, 5 workers)
- **Interactive footprints** — bidirectional map ↔ table selection with click-on-canvas
- **Quicklook preview** — georeferenced thumbnail overlay (WGS 84)
- **COG loading** — Cloud-Optimized GeoTIFF streaming via GDAL vsicurl (no download)
- **5-minute cache** — collection metadata cached for fast repeated queries

### Smart Tasking

- **Satellite catalogue** — 22 EO satellites with TLE, sensor model, off-nadir limits
- **Overpass prediction** — SGP4 bearing-convergence algorithm (sensor footprint × AOI)
- **3D orbit visualisation** — orbit track, ground track, swath corridor, satellite marker, nadir axis
- **Archive search** — per-satellite historical scene lookup across all STAC connectors
- **Send to Tasking** — one-click prefill of Tasking Order form (provider, sensor, GSD, AOI, dates, SAR mode, notes)

### Tasking Orders

- **Guided form** — provider, sensor, priority, AOI, resolution, cloud cover, SAR parameters
- **Mailto workflow** — generates pre-filled email to the selected provider
- **Smart prefill** — auto-populates from Smart Tasking archive or overpass results

### Network & Security

- **QgsNetworkAccessManager** — inherits KADAS proxy, SSL, and timeout settings automatically
- **OAuth2** — secure token-based authentication for Copernicus Data Space
- **No API keys** — most open-data sources work without credentials
- **OpenSSL 3.0** — legacy provider auto-configured by the plugin

### Logging

- Built-in log viewer (`Plugins` → `Altair` → `View Log`)
- Per-connector debug and error tracking

---

## Project Structure

```
kadas-altair-plugin/
├── README.md
├── GUIDE.md
├── ARCHITECTURE.md
├── CONTRIBUTING.md
├── CHANGELOG.md
├── RELEASE_NOTES.md
├── LICENSE
├── package_plugin_full.py          # Build (full, with deps)
├── package_plugin_lite.py          # Build (lite, no deps)
└── kadas_altair_plugin/
    ├── plugin.py                   # Entry point
    ├── logger.py                   # Logging subsystem
    ├── connectors/
    │   ├── base.py                 # Abstract connector interface
    │   ├── connector_manager.py    # Registry + parallel loader
    │   ├── iceye_stac.py
    │   ├── umbra_stac.py
    │   ├── capella_stac.py
    │   ├── vantor.py               # Maxar Open Data
    │   ├── swisstopo_stac.py
    │   ├── copernicus_stac.py      # OAuth2 STAC 1.1
    │   ├── nasa_earthdata.py
    │   ├── jilin_gaofen_stac.py    # Jilin-1 Gaofen (CGSTL)
    │   ├── planet.py               # Stub
    │   └── oneatlas.py             # Stub
    ├── gui/
    │   ├── dock.py                 # Main search panel
    │   ├── archive_dock.py         # Archive browser
    │   ├── smart_tasking_dock.py   # Overpass prediction + 3D viz
    │   ├── tasking_dock.py         # Tasking order form
    │   ├── settings_dock.py        # Settings panel
    │   ├── footprint_tool.py       # Map-click interaction
    │   └── log_viewer.py           # Log viewer dialog
    ├── utilities/
    │   └── proxy_handler.py
    └── secrets/
        └── secure_storage.py       # Keyring / encryption fallback
```

---

## Building

```powershell
# Full package (bundles pip dependencies)
python package_plugin_full.py
# → kadas_altair_plugin_full_vX.Y.Z.zip

# Skip pip install (CI / offline)
$env:KADAS_SKIP_PIP = "1"; python package_plugin_full.py

# Lite package (no bundled deps)
python package_plugin_lite.py
# → kadas_altair_plugin_lite.zip
```

---

## Requirements

- **KADAS Albireo 2.3+** (QGIS 3.x based)
- Internet connection
- No external Python dependencies required at runtime (only QGIS/Qt built-ins)

---

## Common Issues

| Issue | Solution |
|-------|----------|
| Plugin not appearing | Verify folder name is `kadas_altair_plugin`; restart KADAS |
| Collections not loading | Select connector, wait for auto-population |
| No search results | Expand date range / cloud cover; verify AOI on map |
| Proxy / VPN errors | Auto-configured from KADAS settings — see [ARCHITECTURE.md](ARCHITECTURE.md) |
| COG loading fails | Check internet; verify GDAL vsicurl support |
| OpenSSL 3.0 legacy error | Auto-configured by plugin — see [ARCHITECTURE.md](ARCHITECTURE.md) |

Full troubleshooting: [GUIDE.md](GUIDE.md)

---

## Contributing

Contributions welcome — see [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines and [ARCHITECTURE.md](ARCHITECTURE.md) for technical details.

**Before submitting issues:**
- Check logs: `Plugins` → `Altair` → `View Log`
- Include KADAS version, plugin version (`0.4.3`), and steps to reproduce

---

## License

**MIT License** — see [LICENSE](LICENSE).

---

## Credits

**Author:** Michael Lanini — mlanini@proton.me

**Built with:**
[KADAS Albireo 2](https://www.kadas.org/) · [STAC Specification](https://stacspec.org/) · [GDAL vsicurl](https://gdal.org/user/virtual_file_systems.html) · [SGP4](https://pypi.org/project/sgp4/)

**Inspired by:**
[eo-predictor](https://github.com/developmentseed/eo-predictor) · [sat-predict](https://sat-predict.davidhsu.cc/) · [kadas-vantor-plugin](https://github.com/mlanini/kadas-vantor-plugin) · [qgis-maxar-plugin](https://github.com/opengeos/qgis-maxar-plugin)

**Open-data providers:**
ICEYE · Umbra · Capella · Maxar · swisstopo · Copernicus · NASA · CGSTL (Jilin-1)

---

**[GUIDE.md](GUIDE.md)** · **[ARCHITECTURE.md](ARCHITECTURE.md)** · **[CONTRIBUTING.md](CONTRIBUTING.md)** · **[CHANGELOG.md](CHANGELOG.md)**
Issues: https://github.com/mlanini/kadas-altair-plugin/issues

© 2026 Michael Lanini — Open Source Software
