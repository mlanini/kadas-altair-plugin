# Changelog

All notable changes to KADAS Altair Plugin will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0] - 2026-02-25

### Added
- **Performance Optimization**: Parallel collection loading with ThreadPoolExecutor (5 concurrent workers)
- **Caching System**: 5-minute TTL cache for collections with automatic invalidation on authentication
- **Enhanced ICEYE Logging**: Detailed bbox filtering diagnostics with INFO-level logging
- **Documentation Consolidation**: Streamlined to 4 essential documents (README, GUIDE, ARCHITECTURE, CONTRIBUTING)
- **KADAS Branding**: Consistent KADAS Albireo 2.3+ references throughout all documentation

### Changed
- Collection loading speed improved **5x** (30s → 6s) with parallel execution
- Cached collection loading improved **300x** (30s → 0.1s) with TTL cache
- Cache automatically invalidates after authentication flow
- ICEYE connector now logs "✅ INCLUDING" or "❌ EXCLUDING" with bbox coordinates
- Updated installation paths to KADAS-specific locations (Kadas/Kadas/profiles/default/)
- Documentation structure: Consolidated TECHNICAL.md and PERFORMANCE_IMPROVEMENTS.md into ARCHITECTURE.md

### Fixed
- ICEYE bbox filtering now properly validated and logged
- Collection cache properly cleared after connector authentication

### Documentation
- **ARCHITECTURE.md**: New comprehensive technical reference (consolidates previous technical docs)
- **README.md**: Updated with KADAS branding and 4-document structure
- **GUIDE.md**: Updated with KADAS-specific paths, settings, and requirements
- **CONTRIBUTING.md**: Enhanced with testing guidelines

### Technical Details
- Python 3.12+ support
- KADAS Albireo 2.3+ compatibility (based on QGIS 3.x platform)
- Connector Framework with 9 connectors (5 production-ready)
- Qt-based networking via QgsNetworkAccessManager
- Bundled pystac-client dependency (1.59 MB package)

## [0.1.0] - Initial Release

### Added
- Multi-source satellite imagery browser for KADAS Albireo 2
- 5 production-ready connectors:
  - **ICEYE SAR Open Data**: 3 collections, 196 SAR imagery items, global coverage
  - **Umbra SAR Open Data**: High-resolution SAR up to 16cm, recursive STAC catalog
  - **Capella SAR Open Data**: ~1000 SAR images, X-band radar, multiple product formats
  - **Maxar Open Data (Vantor STAC)**: 55+ disaster event collections, sub-meter optical
  - **Copernicus Dataspace**: Sentinel-1/2/3/5P via OAuth2 and STAC API
- 4 additional experimental connectors: Planet, Google Earth Engine, NASA EarthData, OneAtlas
- Interactive map-based footprint selection with bidirectional table sync
- Cloud-Optimized GeoTIFF (COG) loading via GDAL vsicurl
- Advanced search filters: bbox, date range, cloud cover
- OAuth2 client credentials flow support
- Comprehensive logging system with log viewer
- QgsNetworkAccessManager for SSL/proxy handling
- Native QGIS network integration
- 300+ collections across all connectors

### Features
- Unified connector interface via ConnectorManager middleware
- Advanced search with multiple filter types
- Footprint visualization on map canvas
- Load imagery directly from URL (COG support)
- Settings dialog for connector configuration
- Log viewer with filtering capabilities
- Secure credential storage
- Proxy and VPN support via Qt networking stack

---

## Version History Legend

- **Added**: New features
- **Changed**: Changes in existing functionality
- **Deprecated**: Soon-to-be removed features
- **Removed**: Removed features
- **Fixed**: Bug fixes
- **Security**: Vulnerability fixes
- **Documentation**: Documentation updates
- **Technical Details**: Internal/technical changes

---

## Links

- [GitHub Repository](https://github.com/mlanini/kadas-altair)
- [Issue Tracker](https://github.com/mlanini/kadas-altair/issues)
- [Installation Guide](GUIDE.md)
- [Architecture Documentation](ARCHITECTURE.md)
- [Contributing Guidelines](CONTRIBUTING.md)
