# KADAS Altair User Guide

This guide explains how to install, configure, and use the KADAS Altair plugin to search, preview, and prepare satellite imagery acquisition orders inside KADAS Albireo 2.

Current documented release: v0.5.2.

## What the plugin offers

KADAS Altair brings together multiple EO/SAR data sources in a single operational workflow:
- archive search and preview of satellite scenes
- direct COG loading through GDAL and virtual file access
- multi-provider search through STAC connectors and provider-specific services
- Search and Predict with overpass prediction and 3D orbit visualization
- tasking-order preparation with prefill from search results

## Requirements

- KADAS Albireo 2.3+ or newer
- stable internet connectivity
- access to the required provider services (mandatory in some cases)

The plugin includes or naturally relies on the dependencies needed for basic operation. In offline environments or restricted networks, compatibility depends on KADAS support and the availability of remote services.

## Installation

### Method 1: manual installation

1. Download the plugin package from the repository or release page.
2. Extract the contents and verify that the folder is named `kadas_altair_plugin`.
3. Copy it into the KADAS plugins directory.

Windows example:

```powershell
Copy-Item -Recurse kadas_altair_plugin "$env:APPDATA\Kadas\KadasZivil\profiles\default\python\plugins"
```

Linux/macOS example:

```bash
cp -r kadas_altair_plugin ~/.local/share/Kadas/KadasZivil/profiles/default/python/plugins/
```

4. Restart KADAS.
5. Open the plugin manager and enable KADAS Altair.

### Method 2: full package build

To build a full package, run:

```powershell
python package_plugin_full.py
```

If you are working in CI or in an environment without dependency installation, you can use:

```powershell
$env:KADAS_SKIP_PIP = "1"
python package_plugin_full.py
```

## First launch

After activating the plugin, open the panels available from the Altair menu or the KADAS EO menu.

The main operational areas are:
- the Open Data / Archive Search panel for imagery search
- the Search and Predict panel for overpass prediction and historical search
- the Tasking panel for order preparation
- the Settings panel for authentication and configuration

## Basic workflow

### 1. Choose a connector

The plugin supports multiple providers. For immediate use:
- swisstopo STAC: public Swiss data and specific collections
- JAXA Earth STAC: public catalog with no credentials required
- Earth Search (Element84): public Sentinel and Landsat STAC access
- Microsoft Planetary Computer: public curated STAC access for optical and fire collections
- NASA EarthData: token or username/password workflows
- ICEYE, Umbra, Capella, Vantor Open Data: public or commercial providers

In many cases the connector is selected directly from the search interface. When a provider requires authentication, the plugin displays the required fields in the Settings section.

### 2. Define the area of interest

The area of interest can be defined in the following ways:
- by drawing a rectangle on the map
- by using the current view extent
- by entering coordinates manually

The area of interest is the starting point for each search. An overly large or poorly defined bounding box can reduce result quality or increase response time.

### 3. Set temporal and search filters

For each search, it is useful to set:
- a date range
- cloud cover, when supported by the provider
- a collection or dataset, when available
- free-text search, when supported by the connector

### 4. Run the search

After clicking Search, the plugin retrieves results and displays them in a table. If the provider supports footprints or previews, those are shown on the map.

In the **Search and Predict** panel, a dedicated hourglass indicator appears while archive search and/or overpass prediction are running in background.

### 5. Preview or load the results

From a selected result, you can:
- view a quick preview
- load the dataset as a COG or supported layer
- use the result as input for Search and Predict or Tasking

## Available connectors

### swisstopo STAC

- supports public STAC collections
- exposes swisstopo collections in a selectable form
- generally works without credentials for public sources

### JAXA Earth STAC

- public catalog based on STAC/COG
- does not require credentials for basic use
- useful for quickly checking availability, previews, and access to public data

### Earth Search (Element84)

- public STAC access for Sentinel and Landsat collections
- no credentials required for standard catalog use
- useful for broad archive discovery over public optical collections

### Microsoft Planetary Computer

- public STAC catalog with curated optical and fire-oriented collections
- no credentials required for standard catalog use
- useful when you need fast previewable public archive access

### NASA EarthData

- supports Earthdata workflows through token or username/password credentials
- recommended for users who already work with NASA Earthdata accounts

### ICEYE, Umbra, Capella, Vantor Open Data

- connectors for providers with public or commercial availability
- may require authentication or specific accounts
- behavior depends on provider capabilities and configured credentials

### Planet and OneAtlas

- represent future integrations or partial/stub implementations depending on the plugin version
- should not be considered fully operational providers without validating the deployment context

## Search and Predict

The Search and Predict panel helps answer questions such as:
- when will a satellite pass over the area of interest?
- which scene might be acquired within a given time window?
- which archive result is most suitable for tasking?

### How to use it

1. Open the Search and Predict panel.
2. Select the satellite or constellation of interest.
3. Define the AOI and time window.
4. Start overpass prediction or archive search.
5. Review the results and use prefill in the Tasking panel.

### Main features

- overpass prediction using orbital models and convergence logic
- 3D visualization of the orbit, ground track, and swath corridor
- historical search across supported catalogs and providers
- busy hourglass feedback during long-running archive and overpass operations
- rapid transfer of results into the tasking workflow

### Busy indicator behavior

- Archive mode: the indicator is shown while archive connectors are being queried.
- Tasking mode: the indicator is shown while overpass prediction is being computed.
- Mixed mode: the indicator remains visible until both archive and overpass tasks complete.

## Tasking Order

The Tasking Order panel is intended to turn a selected result into a prepared request.

Typical workflow:
1. select a scene or result from search
2. transfer the relevant values into the tasking form
3. fill in provider, sensor, area, resolution, and timing constraints
4. submit the request through the plugin’s prefilled workflow

In recent versions, the flow is mainly oriented toward preparing the message or order rather than directly handling an external broker.

## Settings and authentication

Open the Settings panel to configure providers, endpoints, and credentials.

### Common fields

For many providers, it is useful to configure:
- endpoint or base URL
- token or API key
- username/password when required
- timeout and network settings

### Best practices

- use the plugin’s secure storage when supported by the provider
- verify credentials with the available test buttons
- keep the default endpoints unless a specific need requires otherwise
- check the KADAS network section if proxy or SSL errors appear

### Typical providers

- Earth Search / Planetary Computer: no credentials for normal public catalog access
- NASA EarthData: token or username/password
- Jilin-1 Gaofen: bearer token or tenant credentials
- commercial providers: account and token according to contract

## Troubleshooting

### The plugin does not appear or does not open

Check:
- that the plugin folder is named `kadas_altair_plugin`
- that the plugin is enabled in the plugin manager
- that KADAS was restarted after installation

### No search results

Check:
- that the AOI is valid and not too large
- that the time range is correct
- that the correct provider is selected
- that credentials are present if required
- that the provider supports the selected collection or dataset

### Authentication errors

Check:
- leading or trailing spaces in input fields
- expired or incorrect tokens or passwords
- the correctness of KADAS proxy, network, and SSL settings

### COG or preview layers do not load

Check:
- network availability
- GDAL / virtual file access support in the KADAS runtime
- correctness of the asset URL or provider response

### Diagnostic logs

Open the plugin log panel to review details about:
- authentication
- HTTP requests and provider responses
- network, proxy, or SSL errors

## Data attribution and licensing

The plugin code is distributed under the MIT license. Imagery data and metadata remain subject to the terms of the individual providers.

Before publishing maps, reports, or exports:
1. verify the provider’s terms or contract
2. include attribution for the dataset/collection and the scene or order ID
3. preserve any copyright or usage notes required by the provider

Minimum recommended attribution example:
- Provider: provider name
- Dataset/Collection: dataset or collection identifier
- Scene/Order ID: scene or order ID
- Acquisition Date (UTC): acquisition date and time

## Risorse utili

- README: `README.md`
- Changelog: `CHANGELOG.md`
- Release notes: `RELEASE_NOTES.md`
- Issues: https://github.com/mlanini/kadas-altair-plugin/issues

