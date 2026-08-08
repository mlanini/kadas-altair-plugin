"""Connectors for EO data providers.

This package intentionally avoids eager submodule imports so a failure in one
connector does not block the entire package namespace from loading.
"""

from importlib import import_module
from typing import Any, Dict, Tuple

_LAZY_IMPORTS: Dict[str, Tuple[str, str | None]] = {
    "ConnectorBase": (".base", "ConnectorBase"),
    "ConnectorManager": (".connector_manager", "ConnectorManager"),
    "ConnectorType": (".connector_manager", "ConnectorType"),
    "ConnectorCapability": (".connector_manager", "ConnectorCapability"),
    "OneAtlasConnector": (".oneatlas", "OneAtlasConnector"),
    "PlanetConnector": (".planet", "PlanetConnector"),
    "VantorConnector": (".vantor", "VantorConnector"),
    "IceyeStacConnector": (".iceye_stac", "IceyeStacConnector"),
    "IceyeConnector": (".iceye", "IceyeConnector"),
    "UmbraSTACConnector": (".umbra_stac", "UmbraSTACConnector"),
    "UmbraConnector": (".umbra", "UmbraConnector"),
    "CapellaSTACConnector": (".capella_stac", "CapellaSTACConnector"),
    "CapellaConnector": (".capella", "CapellaConnector"),
    "CdseSentinelConnector": (".cdse_sentinel", "CdseSentinelConnector"),
    "NasaEarthdataConnector": (
        ".nasa_earthdata",
        "NasaEarthdataConnector",
    ),
    "SwisstopoStacConnector": (".swisstopo_stac", "SwisstopoStacConnector"),
    "JilinGaofenStacConnector": (
        ".jilin_gaofen_stac",
        "JilinGaofenStacConnector",
    ),
    "JaxaEarthStacConnector": (
        ".jaxa_earth_stac",
        "JaxaEarthStacConnector",
    ),
    "Element84StacConnector": (
        ".element84_stac",
        "Element84StacConnector",
    ),
    "PlanetaryComputerStacConnector": (
        ".planetary_computer_stac",
        "PlanetaryComputerStacConnector",
    ),
}


def __getattr__(name: str) -> Any:
    try:
        module_path, attribute_name = _LAZY_IMPORTS[name]
    except KeyError as exc:
        raise AttributeError(
            f"module {__name__!r} has no attribute {name!r}"
        ) from exc

    module = import_module(module_path, __name__)
    value = (
        module if attribute_name is None else getattr(module, attribute_name)
    )
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(_LAZY_IMPORTS))
