"""
Altair Smart Tasking Dock Widget

A delightfully simple panel that helps you figure out which satellite
operator to throw money at (or beg data from).  Flip a few switches,
pick your favourite space robot, and let the plugin do the rest.

**Archive mode** — searches real catalogues via the connector framework
and lists results in the same tabular format as the Archive dock.

**Tasking mode** — predicts future satellite overpasses above your AOI
using SGP4 orbital propagation (when available) or a fast analytical
sun-synchronous model.  Think *eo-predictor* but inside QGIS.

No PhDs required.  No animals were harmed.  Probably.
"""

from __future__ import annotations

import math
import urllib.request
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from qgis.PyQt.QtCore import QDate, Qt, QSettings, QUrl, QVariant
from qgis.PyQt.QtGui import QColor, QFont
from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDateEdit,
    QDockWidget,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

try:
    from qgis.core import (
        QgsApplication,
        QgsCoordinateReferenceSystem,
        QgsCoordinateTransform,
        QgsFeature,
        QgsField,
        QgsFields,
        QgsFillSymbol,
        QgsGeometry,
        QgsLineSymbol,
        QgsMarkerSymbol,
        QgsPointXY,
        QgsProject,
        QgsRectangle,
        QgsTask,
        QgsVectorLayer,
    )
    from qgis.gui import QgsExtentWidget

    QGIS_AVAILABLE = True
except ImportError:
    QgsExtentWidget = None
    QgsTask = object  # type: ignore
    QGIS_AVAILABLE = False

from ..logger import get_logger

logger = get_logger('gui.smart_tasking')

# ---------------------------------------------------------------------------
# Optional SGP4 for accurate orbital propagation
# ---------------------------------------------------------------------------
try:
    from sgp4.api import Satrec, jday as _sgp4_jday

    _SGP4_OK = True
except ImportError:
    _SGP4_OK = False

# ---------------------------------------------------------------------------
# Optional QGIS native 3D rendering
# ---------------------------------------------------------------------------
try:
    from qgis._3d import (
        QgsLine3DSymbol,
        QgsPhongMaterialSettings,
        QgsPoint3DSymbol,
        QgsPolygon3DSymbol,
        QgsVectorLayer3DRenderer,
    )

    _3D_AVAILABLE = True
except ImportError:
    _3D_AVAILABLE = False

# ---------------------------------------------------------------------------
# Satellite catalogue — the big phone book of space robots 🛰️
# ---------------------------------------------------------------------------
# Extended fields (vs. v1):
#   norad_id          → NORAD catalogue number (for TLE fetch)
#   connector_ids     → list of archive connector IDs
#   orbit_alt_km      → nominal orbital altitude (km)
#   orbit_inc_deg     → orbital inclination (°)
#   orbit_period_min  → orbital period (minutes)
#   swath_km          → ground swath width (km)
#   revisit_days      → typical revisit period (days)
#   ltan_hour         → local time of descending node (hours, decimal)
#   sensor_model      → 'pushbroom' (wide swath) or 'off_nadir' (agile pointing)
#   max_off_nadir_deg → maximum off-nadir pointing angle (° — off_nadir model only)

SATELLITE_CATALOGUE: List[Dict] = [
    # --- Optical / Paid ------------------------------------------------
    {
        'id': 'maxar_wv3', 'operator': 'Maxar',
        'constellation': 'WorldView-3', 'sensor': 'Optical',
        'gsd_m': 0.31, 'access': 'Paid', 'daylight': 'Day',
        'fun_fact': 'Can see your BBQ from space. Literally.',
        'norad_id': 40115, 'connector_ids': ['vantor'],
        'orbit_alt_km': 617, 'orbit_inc_deg': 97.7,
        'orbit_period_min': 97.0, 'swath_km': 13.1,
        'revisit_days': 1.0, 'ltan_hour': 10.5,
        'sensor_model': 'off_nadir', 'max_off_nadir_deg': 45.0,
    },
    {
        'id': 'maxar_wv2', 'operator': 'Maxar',
        'constellation': 'WorldView-2', 'sensor': 'Optical',
        'gsd_m': 0.46, 'access': 'Paid', 'daylight': 'Day',
        'fun_fact': 'Old but gold — still rocking 8 bands since 2009.',
        'norad_id': 35946, 'connector_ids': ['vantor'],
        'orbit_alt_km': 770, 'orbit_inc_deg': 97.7,
        'orbit_period_min': 100.2, 'swath_km': 16.4,
        'revisit_days': 1.1, 'ltan_hour': 10.5,
        'sensor_model': 'off_nadir', 'max_off_nadir_deg': 45.0,
    },
    {
        'id': 'maxar_legion', 'operator': 'Maxar',
        'constellation': 'WorldView Legion', 'sensor': 'Optical',
        'gsd_m': 0.30, 'access': 'Paid', 'daylight': 'Day',
        'fun_fact': 'The new kids on the block. Fast revisit, sharp eyes.',
        'norad_id': 56789, 'connector_ids': ['vantor'],
        'orbit_alt_km': 500, 'orbit_inc_deg': 97.5,
        'orbit_period_min': 94.5, 'swath_km': 14.0,
        'revisit_days': 0.5, 'ltan_hour': 10.5,
        'sensor_model': 'off_nadir', 'max_off_nadir_deg': 45.0,
    },
    {
        'id': 'airbus_pleiades_neo', 'operator': 'Airbus',
        'constellation': 'Pléiades Neo', 'sensor': 'Optical',
        'gsd_m': 0.30, 'access': 'Paid', 'daylight': 'Day',
        'fun_fact': 'French precision. Croissant not included.',
        'norad_id': 49258, 'connector_ids': ['oneatlas'],
        'orbit_alt_km': 620, 'orbit_inc_deg': 97.9,
        'orbit_period_min': 97.2, 'swath_km': 14.0,
        'revisit_days': 0.5, 'ltan_hour': 10.5,
        'sensor_model': 'off_nadir', 'max_off_nadir_deg': 50.0,
    },
    {
        'id': 'airbus_spot7', 'operator': 'Airbus',
        'constellation': 'SPOT 6/7', 'sensor': 'Optical',
        'gsd_m': 1.5, 'access': 'Paid', 'daylight': 'Day',
        'fun_fact': '1.5 m is still enough to count cars in a parking lot.',
        'norad_id': 40053, 'connector_ids': ['oneatlas'],
        'orbit_alt_km': 694, 'orbit_inc_deg': 98.2,
        'orbit_period_min': 98.8, 'swath_km': 60.0,
        'revisit_days': 1.0, 'ltan_hour': 10.0,
        'sensor_model': 'off_nadir', 'max_off_nadir_deg': 30.0,
    },
    {
        'id': 'planet_skysat', 'operator': 'Planet Labs',
        'constellation': 'SkySat', 'sensor': 'Optical',
        'gsd_m': 0.50, 'access': 'Paid', 'daylight': 'Day',
        'fun_fact': 'Tiny satellites, big ambitions. Also does video!',
        'norad_id': 42987, 'connector_ids': ['planet'],
        'orbit_alt_km': 450, 'orbit_inc_deg': 97.0,
        'orbit_period_min': 93.5, 'swath_km': 6.6,
        'revisit_days': 1.0, 'ltan_hour': 10.5,
        'sensor_model': 'off_nadir', 'max_off_nadir_deg': 25.0,
    },
    {
        'id': 'planet_dove', 'operator': 'Planet Labs',
        'constellation': 'PlanetScope (Dove)', 'sensor': 'Optical',
        'gsd_m': 3.0, 'access': 'Paid', 'daylight': 'Day',
        'fun_fact': 'Over 100 cubesats. They photograph the ENTIRE Earth every day.',
        'norad_id': 44000, 'connector_ids': ['planet'],
        'orbit_alt_km': 475, 'orbit_inc_deg': 97.4,
        'orbit_period_min': 93.8, 'swath_km': 32.5,
        'revisit_days': 1.0, 'ltan_hour': 9.5,
        'sensor_model': 'pushbroom', 'max_off_nadir_deg': 0.0,
    },
    {
        'id': 'blacksky', 'operator': 'BlackSky',
        'constellation': 'BlackSky Gen-3', 'sensor': 'Optical',
        'gsd_m': 0.50, 'access': 'Paid', 'daylight': 'Day',
        'fun_fact': 'Revisit so fast they probably know your lunch schedule.',
        'norad_id': 52950, 'connector_ids': [],
        'orbit_alt_km': 430, 'orbit_inc_deg': 51.6,
        'orbit_period_min': 93.0, 'swath_km': 4.4,
        'revisit_days': 3.0, 'ltan_hour': None,  # not sun-synchronous
        'sensor_model': 'off_nadir', 'max_off_nadir_deg': 40.0,
    },
    {
        'id': 'esi_wv', 'operator': 'European Space Imaging',
        'constellation': 'WorldView (reseller)', 'sensor': 'Optical',
        'gsd_m': 0.31, 'access': 'Paid', 'daylight': 'Day',
        'fun_fact': 'Maxar images, but with a European accent.',
        'norad_id': 40115, 'connector_ids': ['vantor'],
        'orbit_alt_km': 617, 'orbit_inc_deg': 97.7,
        'orbit_period_min': 97.0, 'swath_km': 13.1,
        'revisit_days': 1.0, 'ltan_hour': 10.5,
        'sensor_model': 'off_nadir', 'max_off_nadir_deg': 45.0,
    },
    # --- Optical / Free ------------------------------------------------
    {
        'id': 'esa_s2', 'operator': 'ESA / Copernicus',
        'constellation': 'Sentinel-2', 'sensor': 'Optical',
        'gsd_m': 10.0, 'access': 'Free', 'daylight': 'Day',
        'fun_fact': 'Free, 10 m, global. The people\'s satellite.',
        'norad_id': 40697, 'connector_ids': ['copernicus_stac'],
        'orbit_alt_km': 786, 'orbit_inc_deg': 98.6,
        'orbit_period_min': 100.6, 'swath_km': 290.0,
        'revisit_days': 5.0, 'ltan_hour': 10.5,
        'sensor_model': 'pushbroom', 'max_off_nadir_deg': 0.0,
    },
    {
        'id': 'usgs_landsat9', 'operator': 'USGS / NASA',
        'constellation': 'Landsat 9', 'sensor': 'Optical',
        'gsd_m': 15.0, 'access': 'Free', 'daylight': 'Day',
        'fun_fact': 'Since 1972. The granddaddy of Earth observation.',
        'norad_id': 49260, 'connector_ids': ['nasa_earthdata'],
        'orbit_alt_km': 705, 'orbit_inc_deg': 98.2,
        'orbit_period_min': 98.9, 'swath_km': 185.0,
        'revisit_days': 16.0, 'ltan_hour': 10.0,
        'sensor_model': 'pushbroom', 'max_off_nadir_deg': 0.0,
    },
    {
        'id': 'swisstopo_s2sr', 'operator': 'swisstopo',
        'constellation': 'SWISSEO S2-SR', 'sensor': 'Optical',
        'gsd_m': 10.0, 'access': 'Free', 'daylight': 'Day',
        'fun_fact': 'Swiss-made, cheese-free. Surface reflectance for the Alps.',
        'norad_id': 40697, 'connector_ids': ['swisstopo_stac'],
        'orbit_alt_km': 786, 'orbit_inc_deg': 98.6,
        'orbit_period_min': 100.6, 'swath_km': 290.0,
        'revisit_days': 5.0, 'ltan_hour': 10.5,
        'sensor_model': 'pushbroom', 'max_off_nadir_deg': 0.0,
    },
    {
        'id': 'maxar_opendata', 'operator': 'Maxar Open Data',
        'constellation': 'WorldView (open events)', 'sensor': 'Optical',
        'gsd_m': 0.50, 'access': 'Free', 'daylight': 'Day',
        'fun_fact': 'After disasters Maxar opens the vault. Heroes in orbit.',
        'norad_id': 40115, 'connector_ids': ['vantor'],
        'orbit_alt_km': 617, 'orbit_inc_deg': 97.7,
        'orbit_period_min': 97.0, 'swath_km': 13.1,
        'revisit_days': 1.0, 'ltan_hour': 10.5,
        'sensor_model': 'off_nadir', 'max_off_nadir_deg': 45.0,
    },
    {
        'id': 'nasa_modis', 'operator': 'NASA',
        'constellation': 'MODIS (Terra/Aqua)', 'sensor': 'Optical',
        'gsd_m': 250.0, 'access': 'Free', 'daylight': 'Day',
        'fun_fact': '250 m? Yes, but you can see the whole planet twice a day.',
        'norad_id': 25994, 'connector_ids': ['nasa_earthdata'],
        'orbit_alt_km': 705, 'orbit_inc_deg': 98.2,
        'orbit_period_min': 98.9, 'swath_km': 2330.0,
        'revisit_days': 1.0, 'ltan_hour': 10.5,
        'sensor_model': 'pushbroom', 'max_off_nadir_deg': 0.0,
    },
    # --- SAR / Paid ----------------------------------------------------
    {
        'id': 'iceye_x', 'operator': 'ICEYE',
        'constellation': 'ICEYE X-band', 'sensor': 'SAR',
        'gsd_m': 0.25, 'access': 'Paid', 'daylight': 'Both',
        'fun_fact': 'Finnish micro-SAR. Sees through clouds AND your excuses.',
        'norad_id': 43114, 'connector_ids': ['iceye_stac'],
        'orbit_alt_km': 570, 'orbit_inc_deg': 97.7,
        'orbit_period_min': 96.0, 'swath_km': 30.0,
        'revisit_days': 1.0, 'ltan_hour': 22.0,
        'sensor_model': 'off_nadir', 'max_off_nadir_deg': 40.0,
    },
    {
        'id': 'capella', 'operator': 'Capella Space',
        'constellation': 'Capella SAR', 'sensor': 'SAR',
        'gsd_m': 0.30, 'access': 'Paid', 'daylight': 'Both',
        'fun_fact': '0.3 m SAR spotlight. Rain? Fog? Night? No problem.',
        'norad_id': 47474, 'connector_ids': ['capella_stac'],
        'orbit_alt_km': 525, 'orbit_inc_deg': 97.5,
        'orbit_period_min': 95.0, 'swath_km': 10.0,
        'revisit_days': 3.0, 'ltan_hour': 6.0,
        'sensor_model': 'off_nadir', 'max_off_nadir_deg': 40.0,
    },
    {
        'id': 'umbra', 'operator': 'Umbra',
        'constellation': 'Umbra SAR', 'sensor': 'SAR',
        'gsd_m': 0.16, 'access': 'Paid', 'daylight': 'Both',
        'fun_fact': '16 cm resolution. That\'s basically counting rivets.',
        'norad_id': 48900, 'connector_ids': ['umbra_stac'],
        'orbit_alt_km': 515, 'orbit_inc_deg': 97.5,
        'orbit_period_min': 94.5, 'swath_km': 10.0,
        'revisit_days': 3.0, 'ltan_hour': 6.0,
        'sensor_model': 'off_nadir', 'max_off_nadir_deg': 40.0,
    },
    {
        'id': 'airbus_tsx', 'operator': 'Airbus',
        'constellation': 'TerraSAR-X / PAZ', 'sensor': 'SAR',
        'gsd_m': 0.25, 'access': 'Paid', 'daylight': 'Both',
        'fun_fact': 'German engineering meets Spanish partnership. X-band twins.',
        'norad_id': 31698, 'connector_ids': [],
        'orbit_alt_km': 514, 'orbit_inc_deg': 97.4,
        'orbit_period_min': 94.8, 'swath_km': 100.0,
        'revisit_days': 11.0, 'ltan_hour': 18.0,
        'sensor_model': 'off_nadir', 'max_off_nadir_deg': 40.0,
    },
    # --- SAR / Free ----------------------------------------------------
    {
        'id': 'esa_s1', 'operator': 'ESA / Copernicus',
        'constellation': 'Sentinel-1', 'sensor': 'SAR',
        'gsd_m': 5.0, 'access': 'Free', 'daylight': 'Both',
        'fun_fact': 'Free C-band SAR. Interferometry for the masses.',
        'norad_id': 39634, 'connector_ids': ['copernicus_stac'],
        'orbit_alt_km': 693, 'orbit_inc_deg': 98.2,
        'orbit_period_min': 98.6, 'swath_km': 250.0,
        'revisit_days': 6.0, 'ltan_hour': 18.0,
        'sensor_model': 'pushbroom', 'max_off_nadir_deg': 0.0,
    },
    {
        'id': 'nasa_nisar', 'operator': 'NASA / ISRO',
        'constellation': 'NISAR', 'sensor': 'SAR',
        'gsd_m': 3.0, 'access': 'Free', 'daylight': 'Both',
        'fun_fact': 'L-band + S-band. A joint US-India radar lovechild.',
        'norad_id': 58230, 'connector_ids': ['nasa_earthdata'],
        'orbit_alt_km': 747, 'orbit_inc_deg': 98.4,
        'orbit_period_min': 99.7, 'swath_km': 242.0,
        'revisit_days': 12.0, 'ltan_hour': 6.0,
        'sensor_model': 'pushbroom', 'max_off_nadir_deg': 0.0,
    },
]


# GSD thresholds for resolution categories (metres)
_GSD_HIGH = 1.0        # ≤ 1 m
_GSD_MEDIUM = 15.0     # ≤ 15 m

_R_EARTH_KM = 6371.0


def _resolution_label(gsd: float) -> str:
    if gsd <= _GSD_HIGH:
        return 'High'
    if gsd <= _GSD_MEDIUM:
        return 'Medium'
    return 'Low'


# ---------------------------------------------------------------------------
# Sortable numeric table item
# ---------------------------------------------------------------------------
class _NumItem(QTableWidgetItem):
    """QTableWidgetItem that sorts numerically."""

    def __lt__(self, other: QTableWidgetItem) -> bool:
        try:
            return float(self.text()) < float(other.text())
        except ValueError:
            return super().__lt__(other)



# ===========================================================================
# Overpass prediction engine — bearing-convergence + sensor filtering
# ===========================================================================

def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in km between two WGS-84 points."""
    la1, lo1, la2, lo2 = map(math.radians, (lat1, lon1, lat2, lon2))
    dlat = la2 - la1
    dlon = lo2 - lo1
    a = math.sin(dlat / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin(dlon / 2) ** 2
    return 2.0 * _R_EARTH_KM * math.asin(min(1.0, math.sqrt(a)))


def _bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Initial bearing (degrees, 0-360) from point 1 to point 2."""
    la1, lo1, la2, lo2 = map(math.radians, (lat1, lon1, lat2, lon2))
    dlon = lo2 - lo1
    x = math.sin(dlon) * math.cos(la2)
    y = math.cos(la1) * math.sin(la2) - math.sin(la1) * math.cos(la2) * math.cos(dlon)
    return math.degrees(math.atan2(x, y)) % 360.0


def _destination_point(lat: float, lon: float, bearing_deg: float,
                       dist_km: float) -> Tuple[float, float]:
    """Point at *dist_km* along *bearing_deg* from (lat, lon)."""
    la = math.radians(lat)
    lo = math.radians(lon)
    br = math.radians(bearing_deg)
    d = dist_km / _R_EARTH_KM
    lat2 = math.asin(
        math.sin(la) * math.cos(d) + math.cos(la) * math.sin(d) * math.cos(br)
    )
    lon2 = lo + math.atan2(
        math.sin(br) * math.sin(d) * math.cos(la),
        math.cos(d) - math.sin(la) * math.sin(lat2),
    )
    return math.degrees(lat2), ((math.degrees(lon2) + 540.0) % 360.0) - 180.0


class _OverpassEngine:
    """Predict sensor-footprint crossings via bearing-convergence.

    Unlike conventional elevation-based predictors, this engine answers:
    *"when does the satellite's sensor footprint cross my target?"*

    **Algorithm (bearing-convergence)**

    1.  Propagate the satellite forward in time (SGP4 / analytical).
    2.  Compute the angle between the satellite velocity vector and the
        direction from satellite to ground target.  When this angle is
        exactly 90 deg, the satellite is at closest approach.
    3.  Detect zero-crossing of ``bearing_diff = angle - 90 deg``.
    4.  Bisect: reverse time-step, shrink by 20x, repeat until the
        bearing converges below 0.0001 deg.
    5.  Apply sensor-model constraints (pushbroom / off-nadir) to decide
        if the target is actually observable.

    **Sensor models**

    * *pushbroom* -- target is observable if within half the swath width.
    * *off_nadir* -- additionally, the off-nadir scan angle must be <=
      ``max_off_nadir_deg``.

    Each accepted pass also produces a full-orbit track (``orbit_track``,
    ``ground_track``) and a swath ribbon (``swath_ribbon``) for 3-D
    visualisation.
    """

    _TLE_URL = 'https://celestrak.org/NORAD/elements/gp.php?CATNR={norad}&FORMAT=tle'
    _TLE_TIMEOUT = 8  # seconds

    # Bearing-convergence tuning
    _INITIAL_STEP_S = 60.0      # coarse scan step (seconds)
    _SHRINK_FACTOR = 20.0       # bisection shrink
    _CONVERGENCE_DEG = 0.0001   # bearing precision threshold
    _MAX_BISECTIONS = 12        # safety limit per zero-crossing

    def __init__(self):
        self._tle_cache: Dict[int, Tuple[str, str]] = {}

    # ----- public API --------------------------------------------------

    def predict(
        self,
        sat: Dict,
        aoi_lat: float,
        aoi_lon: float,
        start_dt: datetime,
        end_dt: datetime,
    ) -> List[Dict]:
        """Return predicted sensor-footprint crossings for *sat*.

        Each returned dict contains:
            satellite, operator, datetime_utc, direction, max_elevation,
            duration_min, off_nadir_deg, ground_dist_km, confidence,
            sub_sat_lat, sub_sat_lon, orbit_alt_km, swath_km,
            orbit_track, ground_track, swath_ribbon
        """
        inc = sat.get('orbit_inc_deg', 98.0)
        if abs(aoi_lat) > inc:
            return []

        if _SGP4_OK:
            norad = sat.get('norad_id')
            if norad:
                tle = self._fetch_tle(norad)
                if tle:
                    try:
                        return self._sgp4_predict(sat, tle, aoi_lat, aoi_lon,
                                                  start_dt, end_dt)
                    except Exception as exc:
                        logger.warning(
                            f'SGP4 prediction failed for {sat["constellation"]}: '
                            f'{exc}; falling back to analytical model'
                        )

        return self._analytical_predict(sat, aoi_lat, aoi_lon, start_dt, end_dt)

    # ----- TLE fetching -----------------------------------------------

    def _fetch_tle(self, norad_id: int) -> Optional[Tuple[str, str]]:
        if norad_id in self._tle_cache:
            return self._tle_cache[norad_id]
        url = self._TLE_URL.format(norad=norad_id)
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'AltairPlugin/0.4'})
            with urllib.request.urlopen(req, timeout=self._TLE_TIMEOUT) as resp:
                text = resp.read().decode('utf-8', errors='replace').strip()
            lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
            if len(lines) >= 3:
                tle = (lines[1], lines[2])
            elif len(lines) == 2 and lines[0].startswith('1 ') and lines[1].startswith('2 '):
                tle = (lines[0], lines[1])
            else:
                return None
            self._tle_cache[norad_id] = tle
            return tle
        except Exception as exc:
            logger.debug(f'TLE fetch failed for NORAD {norad_id}: {exc}')
        return None

    # ----- SGP4 helpers ------------------------------------------------

    @staticmethod
    def _gmst_rad(jd: float, fr: float) -> float:
        T = ((jd - 2451545.0) + fr) / 36525.0
        sec = (67310.54841
               + (876600.0 * 3600.0 + 8640184.812866) * T
               + 0.093104 * T * T
               - 6.2e-6 * T * T * T)
        return math.radians((sec / 240.0) % 360.0)

    def _sat_ecef(self, satrec, dt: datetime) -> Optional[Tuple[float, float, float]]:
        """ECEF position (km)."""
        jd, fr = _sgp4_jday(dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second)
        e, r, _v = satrec.sgp4(jd, fr)
        if e != 0:
            return None
        g = self._gmst_rad(jd, fr)
        cg, sg = math.cos(g), math.sin(g)
        return (r[0] * cg + r[1] * sg,
                -r[0] * sg + r[1] * cg,
                r[2])

    def _sub_sat_lonlat(self, satrec, dt: datetime) -> Optional[Tuple[float, float]]:
        """(lat, lon) in degrees of the sub-satellite point."""
        pos = self._sat_ecef(satrec, dt)
        if pos is None:
            return None
        xe, ye, ze = pos
        lat = math.degrees(math.atan2(ze, math.sqrt(xe * xe + ye * ye)))
        lon = math.degrees(math.atan2(ye, xe))
        return lat, lon

    def _velocity_bearing(self, satrec, dt: datetime) -> Optional[float]:
        """Ground-track velocity bearing (deg) at *dt*.

        Computed from a small forward difference of sub-satellite points.
        """
        dt2 = dt + timedelta(seconds=2)
        p1 = self._sub_sat_lonlat(satrec, dt)
        p2 = self._sub_sat_lonlat(satrec, dt2)
        if p1 is None or p2 is None:
            return None
        return _bearing_deg(p1[0], p1[1], p2[0], p2[1])

    def _sat_altitude_km(self, satrec, dt: datetime) -> float:
        pos = self._sat_ecef(satrec, dt)
        if pos is None:
            return 600.0
        return math.sqrt(pos[0] ** 2 + pos[1] ** 2 + pos[2] ** 2) - _R_EARTH_KM

    # ----- Bearing-convergence SGP4 prediction ------------------------

    def _sgp4_predict(
        self, sat: Dict, tle: Tuple[str, str],
        tgt_lat: float, tgt_lon: float,
        start_dt: datetime, end_dt: datetime,
    ) -> List[Dict]:
        satrec = Satrec.twoline2rv(tle[0], tle[1])
        swath_km = sat.get('swath_km', 20.0)
        max_ona = sat.get('max_off_nadir_deg', 30.0)
        model = sat.get('sensor_model', 'pushbroom')
        alt_km = sat.get('orbit_alt_km', 600.0)
        period_s = sat.get('orbit_period_min', 97.0) * 60.0

        # Maximum sensor reach on ground (for pre-filtering)
        if model == 'off_nadir' and max_ona > 0:
            max_reach_km = alt_km * math.tan(math.radians(max_ona))
        else:
            max_reach_km = swath_km / 2.0

        overpasses: List[Dict] = []
        step = timedelta(seconds=self._INITIAL_STEP_S)
        dt = start_dt
        prev_bdiff: Optional[float] = None

        while dt <= end_dt:
            ss = self._sub_sat_lonlat(satrec, dt)
            if ss is None:
                dt += step
                prev_bdiff = None
                continue

            # Quick distance filter (skip if way too far)
            dist_km = _haversine_km(ss[0], ss[1], tgt_lat, tgt_lon)
            if dist_km > max_reach_km * 3.0:
                dt += step
                prev_bdiff = None
                continue

            # Bearing difference: angle between velocity and target direction
            vb = self._velocity_bearing(satrec, dt)
            if vb is None:
                dt += step
                prev_bdiff = None
                continue
            tb = _bearing_deg(ss[0], ss[1], tgt_lat, tgt_lon)
            perp = ((tb - vb + 180.0) % 360.0) - 180.0
            bdiff = abs(perp) - 90.0  # negative = inside approach, positive = outside

            if prev_bdiff is not None and prev_bdiff * bdiff < 0:
                # Zero-crossing detected -> bisect to converge
                t_lo = dt - step
                t_hi = dt
                converged_dt = dt
                bd_lo = prev_bdiff
                for _ in range(self._MAX_BISECTIONS):
                    t_mid = t_lo + (t_hi - t_lo) / 2
                    ss_m = self._sub_sat_lonlat(satrec, t_mid)
                    if ss_m is None:
                        break
                    vb_m = self._velocity_bearing(satrec, t_mid)
                    if vb_m is None:
                        break
                    tb_m = _bearing_deg(ss_m[0], ss_m[1], tgt_lat, tgt_lon)
                    perp_m = ((tb_m - vb_m + 180.0) % 360.0) - 180.0
                    bdiff_m = abs(perp_m) - 90.0

                    if abs(bdiff_m) < self._CONVERGENCE_DEG:
                        converged_dt = t_mid
                        break
                    if bd_lo * bdiff_m < 0:
                        t_hi = t_mid
                    else:
                        t_lo = t_mid
                        bd_lo = bdiff_m
                    converged_dt = t_mid

                # Evaluate sensor constraints at converged time
                pass_result = self._evaluate_pass(
                    satrec, sat, converged_dt, tgt_lat, tgt_lon,
                    swath_km, max_ona, model, alt_km, period_s,
                )
                if pass_result:
                    overpasses.append(pass_result)
                    # Skip past this pass to avoid duplicate detections
                    dt = converged_dt + timedelta(seconds=period_s * 0.8)
                    prev_bdiff = None
                    continue

            prev_bdiff = bdiff
            dt += step

        return overpasses

    def _evaluate_pass(
        self, satrec, sat: Dict, dt: datetime,
        tgt_lat: float, tgt_lon: float,
        swath_km: float, max_ona: float, model: str,
        alt_km: float, period_s: float,
    ) -> Optional[Dict]:
        """Check sensor constraints and build a full overpass dict."""
        ss = self._sub_sat_lonlat(satrec, dt)
        if ss is None:
            return None

        dist_km = _haversine_km(ss[0], ss[1], tgt_lat, tgt_lon)
        actual_alt = self._sat_altitude_km(satrec, dt)
        ona_deg = math.degrees(math.atan2(dist_km, actual_alt)) if actual_alt > 0 else 90.0

        # Sensor filtering
        if model == 'off_nadir':
            if ona_deg > max_ona:
                return None
        else:  # pushbroom
            if dist_km > swath_km / 2.0:
                return None

        # Elevation from observer
        elev = 90.0 - ona_deg

        # Direction
        ss_before = self._sub_sat_lonlat(satrec, dt - timedelta(seconds=30))
        direction = 'Ascending'
        if ss_before and ss_before[0] > ss[0]:
            direction = 'Descending'

        # Duration estimate (time target is within sensor footprint)
        half_reach = (swath_km / 2.0) if model == 'pushbroom' else (
            actual_alt * math.tan(math.radians(max_ona))
        )
        ground_speed_kms = (2.0 * math.pi * _R_EARTH_KM) / period_s
        duration_s = (2.0 * half_reach) / ground_speed_kms if ground_speed_kms > 0 else 0
        duration_min = duration_s / 60.0

        # Build orbit track, ground track, swath ribbon (~ 1 full period)
        orbit_track, ground_track, swath_ribbon = self._build_tracks(
            satrec, dt, period_s, swath_km, actual_alt,
        )

        return {
            'satellite': sat['constellation'],
            'operator': sat['operator'],
            'datetime_utc': dt.strftime('%Y-%m-%d %H:%M UTC'),
            'direction': direction,
            'max_elevation': round(elev, 1),
            'duration_min': round(duration_min, 1),
            'off_nadir_deg': round(ona_deg, 1),
            'ground_dist_km': round(dist_km, 1),
            'confidence': 'SGP4',
            'sub_sat_lat': ss[0],
            'sub_sat_lon': ss[1],
            'orbit_alt_km': round(actual_alt, 1),
            'swath_km': swath_km,
            'sensor_model': model,
            'orbit_track': orbit_track,
            'ground_track': ground_track,
            'swath_ribbon': swath_ribbon,
        }

    # ----- Orbit track / ground track / swath ribbon ------------------

    def _build_tracks(
        self, satrec, center_dt: datetime, period_s: float,
        swath_km: float, alt_km: float,
        n_points: int = 180,
    ) -> Tuple[List[Tuple], List[Tuple], List[Tuple]]:
        """Produce one full orbit of tracks centred on *center_dt*.

        Returns:
            orbit_track  -- list of (lon, lat, alt_m) for the 3-D orbit line
            ground_track -- list of (lon, lat) for the 2-D ground trace
            swath_ribbon -- list of (lon, lat) polygon vertices for the swath
        """
        half = period_s / 2.0
        dt_start = center_dt - timedelta(seconds=half)
        step_s = period_s / n_points

        orbit_pts: List[Tuple] = []
        ground_pts: List[Tuple] = []
        left_edge: List[Tuple] = []
        right_edge: List[Tuple] = []
        half_swath = swath_km / 2.0

        for i in range(n_points + 1):
            t = dt_start + timedelta(seconds=i * step_s)
            pos = self._sat_ecef(satrec, t)
            ss = self._sub_sat_lonlat(satrec, t)
            if pos is None or ss is None:
                continue

            slat, slon = ss
            alt_m = (math.sqrt(pos[0] ** 2 + pos[1] ** 2 + pos[2] ** 2)
                     - _R_EARTH_KM) * 1000.0

            orbit_pts.append((slon, slat, alt_m))
            ground_pts.append((slon, slat))

            # Velocity bearing for swath perpendicular
            vb = self._velocity_bearing(satrec, t)
            if vb is not None:
                left_brg = (vb - 90.0) % 360.0
                right_brg = (vb + 90.0) % 360.0
                lp = _destination_point(slat, slon, left_brg, half_swath)
                rp = _destination_point(slat, slon, right_brg, half_swath)
                left_edge.append((lp[1], lp[0]))   # (lon, lat)
                right_edge.append((rp[1], rp[0]))

        # Swath ribbon = left edge forward + right edge reversed -> closed
        swath_ribbon = left_edge + list(reversed(right_edge))
        if swath_ribbon:
            swath_ribbon.append(swath_ribbon[0])

        return orbit_pts, ground_pts, swath_ribbon

    # ----- Analytical (sun-synchronous) fallback ----------------------

    def _analytical_predict(
        self, sat: Dict,
        lat: float, lon: float,
        start_dt: datetime, end_dt: datetime,
    ) -> List[Dict]:
        """Estimate sensor crossings using a deterministic sun-synchronous model."""
        inc_r = math.radians(sat.get('orbit_inc_deg', 98.0))
        period = sat.get('orbit_period_min', 97.0)
        swath_km = sat.get('swath_km', 20.0)
        revisit_days = max(0.5, sat.get('revisit_days', 1.0))
        alt_km = sat.get('orbit_alt_km', 600.0)
        ltan = sat.get('ltan_hour', 10.5)
        model = sat.get('sensor_model', 'pushbroom')
        max_ona = sat.get('max_off_nadir_deg', 30.0)

        lat_r = math.radians(lat)
        if ltan is None:
            ltan = 10.5

        orbits_per_day = 1440.0 / period
        delta_lon = 360.0 / orbits_per_day
        circ_at_lat = 2.0 * math.pi * _R_EARTH_KM * math.cos(lat_r)
        spacing_km = (delta_lon / 360.0) * circ_at_lat if circ_at_lat > 0 else 9999.0

        if swath_km < spacing_km:
            effective_revisit = max(revisit_days, spacing_km / swath_km)
        else:
            effective_revisit = revisit_days

        sin_ratio = math.sin(lat_r) / math.sin(inc_r)
        if abs(sin_ratio) > 1:
            return []
        u_desc = math.pi - math.asin(sin_ratio)
        frac_desc = u_desc / (2.0 * math.pi)
        desc_utc_hour = (ltan - lon / 15.0) % 24.0
        time_offset_min = (frac_desc - 0.5) * period
        asc_utc_hour = (desc_utc_hour + period * orbits_per_day / 2.0 / 60.0) % 24.0

        period_s = period * 60.0
        ground_speed_kms = (2.0 * math.pi * _R_EARTH_KM) / period_s

        overpasses: List[Dict] = []
        current_day = start_dt.replace(hour=0, minute=0, second=0, microsecond=0)
        orbit_index = 0

        while current_day <= end_dt:
            for direction, utc_hour, t_offset in (
                ('Descending', desc_utc_hour, time_offset_min),
                ('Ascending', asc_utc_hour, -time_offset_min),
            ):
                if direction == 'Ascending':
                    if sat.get('daylight') not in ('Both', 'Night') \
                       and sat.get('sensor') != 'SAR':
                        continue

                pass_dt = current_day + timedelta(hours=utc_hour, minutes=t_offset)
                if not (start_dt <= pass_dt <= end_dt):
                    continue

                idx = orbit_index if direction == 'Descending' else orbit_index + 1
                phase = (idx * 0.618033988749895) % 1.0
                offset_km = phase * spacing_km * 0.5

                ona_deg = (math.degrees(math.atan2(offset_km, alt_km))
                           if alt_km > 0 else 90.0)
                if model == 'off_nadir':
                    if ona_deg > max_ona:
                        continue
                else:
                    if offset_km > swath_km / 2.0:
                        continue

                elev = 90.0 - ona_deg
                if elev < 5.0:
                    continue

                half_reach = (swath_km / 2.0 if model == 'pushbroom'
                              else (alt_km * math.tan(math.radians(max_ona))
                                    if max_ona > 0 else swath_km / 2.0))
                dur_min = ((2.0 * half_reach / ground_speed_kms / 60.0)
                           if ground_speed_kms > 0 else 0)

                orbit_track, ground_track, swath_ribbon = _analytical_tracks(
                    lat, lon, sat.get('orbit_inc_deg', 98.0), alt_km,
                    swath_km, period, direction,
                )

                overpasses.append({
                    'satellite': sat['constellation'],
                    'operator': sat['operator'],
                    'datetime_utc': pass_dt.strftime('%Y-%m-%d %H:%M UTC'),
                    'direction': direction,
                    'max_elevation': round(elev, 1),
                    'duration_min': round(dur_min, 1),
                    'off_nadir_deg': round(ona_deg, 1),
                    'ground_dist_km': round(offset_km, 1),
                    'confidence': 'Approximate',
                    'sub_sat_lat': lat,
                    'sub_sat_lon': lon,
                    'orbit_alt_km': alt_km,
                    'swath_km': swath_km,
                    'sensor_model': model,
                    'orbit_track': orbit_track,
                    'ground_track': ground_track,
                    'swath_ribbon': swath_ribbon,
                })

            current_day += timedelta(days=max(1, int(effective_revisit)))
            orbit_index += 1

        return overpasses


# ---------------------------------------------------------------------------
# Analytical orbit-track synthesis (no TLE)
# ---------------------------------------------------------------------------

def _analytical_tracks(
    tgt_lat: float, tgt_lon: float, inc_deg: float, alt_km: float,
    swath_km: float, period_min: float, direction: str,
    n_points: int = 120,
) -> Tuple[List[Tuple], List[Tuple], List[Tuple]]:
    """Create synthetic orbit/ground/swath tracks for the analytical model."""
    half_period_s = period_min * 30.0
    ground_speed_kms = (2.0 * math.pi * _R_EARTH_KM) / (period_min * 60.0)
    half_len_km = ground_speed_kms * half_period_s

    if direction == 'Descending':
        track_bearing = 180.0 + (90.0 - inc_deg)
    else:
        track_bearing = 0.0 - (90.0 - inc_deg)
    track_bearing %= 360.0

    orbit_pts: List[Tuple] = []
    ground_pts: List[Tuple] = []
    left_edge: List[Tuple] = []
    right_edge: List[Tuple] = []
    alt_m = alt_km * 1000.0
    half_swath = swath_km / 2.0
    step_km = (2.0 * half_len_km) / n_points

    for i in range(n_points + 1):
        d = -half_len_km + i * step_km
        pt = _destination_point(tgt_lat, tgt_lon, track_bearing, d)
        orbit_pts.append((pt[1], pt[0], alt_m))
        ground_pts.append((pt[1], pt[0]))

        lp = _destination_point(pt[0], pt[1], (track_bearing - 90) % 360, half_swath)
        rp = _destination_point(pt[0], pt[1], (track_bearing + 90) % 360, half_swath)
        left_edge.append((lp[1], lp[0]))
        right_edge.append((rp[1], rp[0]))

    swath_ribbon = left_edge + list(reversed(right_edge))
    if swath_ribbon:
        swath_ribbon.append(swath_ribbon[0])

    return orbit_pts, ground_pts, swath_ribbon


# ===========================================================================
# Background search task (mirrors ArchiveSearchTask)
# ===========================================================================
class _SmartSearchTask(QgsTask if QGIS_AVAILABLE else object):  # type: ignore
    """Run a multi-connector archive search in a background thread."""

    def __init__(self, connector_manager, search_params: Dict[str, Any]):
        if QGIS_AVAILABLE:
            super().__init__('Smart Tasking — Archive Search', QgsTask.CanCancel)
        self.connector_manager = connector_manager
        self.search_params = search_params
        self.results: List[Dict] = []
        self.error_message: Optional[str] = None

    def run(self) -> bool:
        try:
            bbox = self.search_params.get('bbox')
            start_date = self.search_params.get('start_date')
            end_date = self.search_params.get('end_date')
            max_cloud_cover = self.search_params.get('max_cloud_cover')
            limit = int(self.search_params.get('limit', 50))
            connector_ids = list(self.search_params.get('connector_ids', []))

            for cid in connector_ids:
                if self.isCanceled():
                    return False
                items, _token = self.connector_manager.search(
                    bbox=bbox,
                    start_date=start_date,
                    end_date=end_date,
                    max_cloud_cover=max_cloud_cover,
                    limit=limit,
                    connector_id=cid,
                )
                display = cid
                ci = getattr(self.connector_manager, '_connectors', {}).get(cid, {})
                if ci:
                    display = ci.get('display_name', cid)
                for item in (items or []):
                    item['_provider'] = display
                    item['_source'] = cid
                    self.results.append(item)

            logger.info(f'SmartSearchTask: {len(self.results)} scene(s) found')
            return True
        except Exception as exc:
            logger.error(f'SmartSearchTask failed: {exc}', exc_info=True)
            self.error_message = str(exc)
            return False

    def finished(self, result: bool) -> None:
        if not result:
            logger.error(f'SmartSearchTask error: {self.error_message}')


# ===========================================================================
# Background overpass prediction task
# ===========================================================================
class _OverpassTask(QgsTask if QGIS_AVAILABLE else object):  # type: ignore

    def __init__(self, satellites: List[Dict], lat: float, lon: float,
                 start_dt: datetime, end_dt: datetime):
        if QGIS_AVAILABLE:
            super().__init__('Smart Tasking — Overpass Prediction', QgsTask.CanCancel)
        self.satellites = satellites
        self.lat = lat
        self.lon = lon
        self.start_dt = start_dt
        self.end_dt = end_dt
        self.results: List[Dict] = []
        self.error_message: Optional[str] = None

    def run(self) -> bool:
        try:
            engine = _OverpassEngine()
            for sat in self.satellites:
                if self.isCanceled():
                    return False
                passes = engine.predict(sat, self.lat, self.lon, self.start_dt, self.end_dt)
                self.results.extend(passes)
            # Sort by time
            self.results.sort(key=lambda p: p.get('datetime_utc', ''))
            logger.info(f'OverpassTask: {len(self.results)} pass(es) predicted')
            return True
        except Exception as exc:
            logger.error(f'OverpassTask failed: {exc}', exc_info=True)
            self.error_message = str(exc)
            return False

    def finished(self, result: bool) -> None:
        if not result:
            logger.error(f'OverpassTask error: {self.error_message}')


# ===========================================================================
# Main dock widget
# ===========================================================================
class SmartTaskingDockWidget(QDockWidget):
    """Smart Tasking dock — flip switches, pick a satellite, search or predict."""

    _LABEL_COLOR = '#303030'

    # Archive-results table column indices
    _COL_PROVIDER  = 0
    _COL_DATE      = 1
    _COL_SATELLITE = 2
    _COL_CLOUD     = 3
    _COL_GSD       = 4
    _COL_ID        = 5

    # Overpass table column indices
    _OV_SAT       = 0
    _OV_OPERATOR  = 1
    _OV_TIME      = 2
    _OV_DIR       = 3
    _OV_ELEV      = 4
    _OV_ONA       = 5
    _OV_DIST      = 6
    _OV_DUR       = 7
    _OV_CONF      = 8

    def __init__(self, iface, parent=None):
        super().__init__('Smart Tasking 🛰️', parent)
        logger.info('Initializing Smart Tasking dock widget')

        self.iface = iface
        self.settings = QSettings()
        self.setObjectName('AltairSmartTaskingDock')
        self.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)

        self._filtered_catalogue: List[Dict] = list(SATELLITE_CATALOGUE)
        self._search_results: List[Dict] = []
        self._overpass_results: List[Dict] = []
        self._connector_manager = None
        self._active_search_task = None
        self._active_overpass_task = None
        self._footprints_layer = None
        self._3d_orbit_layer = None
        self._3d_ground_layer = None
        self._3d_swath_layer = None
        self._3d_sat_layer = None
        self._3d_nadir_layer = None

        self._setup_ui()
        self._apply_filters()
        self._init_connector_manager()

    # ------------------------------------------------------------------
    # Connector manager
    # ------------------------------------------------------------------

    def _init_connector_manager(self):
        """Lazy-init ConnectorManager with archive connectors."""
        try:
            from ..connectors.connector_manager import ConnectorManager, ConnectorCapability

            self._connector_manager = ConnectorManager()

            _REGISTRATIONS = [
                ('planet',          '..connectors.planet',          'PlanetConnector',          'Planet Labs',
                 [ConnectorCapability.BBOX_SEARCH, ConnectorCapability.DATE_RANGE,
                  ConnectorCapability.CLOUD_COVER, ConnectorCapability.AUTHENTICATION,
                  ConnectorCapability.COMMERCIAL]),
                ('oneatlas',        '..connectors.oneatlas',        'OneAtlasConnector',        'OneAtlas',
                 [ConnectorCapability.BBOX_SEARCH, ConnectorCapability.DATE_RANGE,
                  ConnectorCapability.CLOUD_COVER, ConnectorCapability.AUTHENTICATION,
                  ConnectorCapability.COMMERCIAL]),
                ('iceye_stac',      '..connectors.iceye_stac',      'IceyeStacConnector',       'ICEYE',
                 [ConnectorCapability.BBOX_SEARCH, ConnectorCapability.DATE_RANGE,
                  ConnectorCapability.AUTHENTICATION, ConnectorCapability.COMMERCIAL]),
                ('umbra_stac',      '..connectors.umbra_stac',      'UmbraSTACConnector',       'Umbra',
                 [ConnectorCapability.BBOX_SEARCH, ConnectorCapability.DATE_RANGE,
                  ConnectorCapability.AUTHENTICATION, ConnectorCapability.COMMERCIAL]),
                ('capella_stac',    '..connectors.capella_stac',    'CapellaSTACConnector',     'Capella',
                 [ConnectorCapability.BBOX_SEARCH, ConnectorCapability.DATE_RANGE,
                  ConnectorCapability.COG_SUPPORT]),
                ('vantor',          '..connectors.vantor',          'VantorConnector',          'Maxar (Vantor)',
                 [ConnectorCapability.BBOX_SEARCH, ConnectorCapability.DATE_RANGE,
                  ConnectorCapability.CLOUD_COVER]),
                ('copernicus_stac', '..connectors.copernicus_stac', 'CopernicusStacConnector',  'Copernicus',
                 [ConnectorCapability.BBOX_SEARCH, ConnectorCapability.DATE_RANGE,
                  ConnectorCapability.CLOUD_COVER, ConnectorCapability.AUTHENTICATION]),
                ('nasa_earthdata',  '..connectors.nasa_earthdata',  'NasaEarthdataConnector',   'NASA EarthData',
                 [ConnectorCapability.BBOX_SEARCH, ConnectorCapability.DATE_RANGE,
                  ConnectorCapability.AUTHENTICATION, ConnectorCapability.COG_SUPPORT]),
                ('swisstopo_stac',  '..connectors.swisstopo_stac',  'SwisstopoStacConnector',   'swisstopo',
                 [ConnectorCapability.BBOX_SEARCH, ConnectorCapability.DATE_RANGE,
                  ConnectorCapability.CLOUD_COVER, ConnectorCapability.COG_SUPPORT]),
            ]

            import importlib
            for cid, modpath, clsname, display, caps in _REGISTRATIONS:
                try:
                    mod = importlib.import_module(modpath, package=__package__)
                    cls = getattr(mod, clsname)
                    self._connector_manager.register_connector(cid, cls(), display, capabilities=caps)
                    logger.debug(f'SmartTasking: registered connector {cid}')
                except Exception as exc:
                    logger.debug(f'SmartTasking: connector {cid} unavailable: {exc}')

            logger.info('SmartTasking: connector manager ready')
        except Exception as exc:
            logger.error(f'SmartTasking: connector manager init failed: {exc}', exc_info=True)
            self._connector_manager = None

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _setup_ui(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.setWidget(scroll)

        root = QWidget()
        scroll.setWidget(root)

        root.setStyleSheet(
            f'QLabel {{ color: {self._LABEL_COLOR}; }}'
            f'QGroupBox {{ color: {self._LABEL_COLOR}; font-weight: bold; }}'
            f'QComboBox {{ color: {self._LABEL_COLOR}; }}'
        )

        layout = QVBoxLayout(root)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)
        layout.setAlignment(Qt.AlignTop)

        # --- Header ---
        header = QLabel('Smart Tasking 🛰️')
        hf = QFont()
        hf.setPointSize(12)
        hf.setBold(True)
        header.setFont(hf)
        header.setAlignment(Qt.AlignCenter)
        header.setStyleSheet('color: #1f1f1f;')
        layout.addWidget(header)

        subtitle = QLabel(
            'Flip a few switches, pick your favourite space robot, '
            'and let the plugin figure out who to bother. '
            'No rocket science degree needed. Probably.'
        )
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet(f'color: {self._LABEL_COLOR}; font-size: 10px;')
        layout.addWidget(subtitle)

        # --- Quick filters ---
        filter_group = QGroupBox('What Do You Need? (a.k.a. The Switches)')
        filter_form = QFormLayout(filter_group)
        filter_form.setRowWrapPolicy(QFormLayout.WrapAllRows)

        # Time range — determines archive vs new tasking
        date_row = QHBoxLayout()
        self.date_start = QDateEdit()
        self.date_start.setCalendarPopup(True)
        self.date_start.setDate(QDate.currentDate().addMonths(-1))
        self.date_start.setDisplayFormat('yyyy-MM-dd')
        date_row.addWidget(QLabel('From:'))
        date_row.addWidget(self.date_start)
        self.date_end = QDateEdit()
        self.date_end.setCalendarPopup(True)
        self.date_end.setDate(QDate.currentDate().addDays(14))
        self.date_end.setDisplayFormat('yyyy-MM-dd')
        date_row.addWidget(QLabel('To:'))
        date_row.addWidget(self.date_end)
        filter_form.addRow('Time Range:', date_row)

        self.mode_label = QLabel('')
        self.mode_label.setStyleSheet('font-weight: bold; font-size: 10px;')
        filter_form.addRow('', self.mode_label)

        self.date_start.dateChanged.connect(self._update_mode_label)
        self.date_end.dateChanged.connect(self._update_mode_label)

        # Sensor type
        self.sensor_combo = QComboBox()
        self.sensor_combo.addItems(['All', 'Optical', 'SAR'])
        self.sensor_combo.currentIndexChanged.connect(self._apply_filters)
        filter_form.addRow('Sensor Type:', self.sensor_combo)

        # Spatial resolution
        self.resolution_combo = QComboBox()
        self.resolution_combo.addItems(['All', 'High (≤1 m)', 'Medium (≤15 m)', 'Low (>15 m)'])
        self.resolution_combo.currentIndexChanged.connect(self._apply_filters)
        filter_form.addRow('Resolution:', self.resolution_combo)

        # Data access
        self.access_combo = QComboBox()
        self.access_combo.addItems(['All', 'Paid', 'Free / Open'])
        self.access_combo.currentIndexChanged.connect(self._apply_filters)
        filter_form.addRow('Data Access:', self.access_combo)

        # Daylight
        self.daylight_combo = QComboBox()
        self.daylight_combo.addItems(['All', 'Day', 'Night'])
        self.daylight_combo.currentIndexChanged.connect(self._apply_filters)
        filter_form.addRow('Daylight:', self.daylight_combo)

        layout.addWidget(filter_group)

        # --- Operator / constellation selectors ---
        select_group = QGroupBox('Pick Your Space Robot')
        select_form = QFormLayout(select_group)

        self.operator_combo = QComboBox()
        self.operator_combo.currentIndexChanged.connect(self._on_operator_changed)
        select_form.addRow('Operator:', self.operator_combo)

        self.constellation_combo = QComboBox()
        self.constellation_combo.currentIndexChanged.connect(self._on_constellation_changed)
        select_form.addRow('Constellation:', self.constellation_combo)

        layout.addWidget(select_group)

        # --- Fun fact box ---
        self.fun_fact_label = QLabel('')
        self.fun_fact_label.setWordWrap(True)
        self.fun_fact_label.setStyleSheet(
            'background-color: #fffde7; color: #5d4037; font-size: 10px; '
            'padding: 6px; border-radius: 4px; border: 1px solid #ffe082;'
        )
        layout.addWidget(self.fun_fact_label)

        # --- AOI ---
        aoi_group = QGroupBox('Where on Earth?')
        aoi_form = QFormLayout(aoi_group)

        self.extent_widget = None
        if QgsExtentWidget and self.iface:
            self.extent_widget = QgsExtentWidget(parent=aoi_group)
            self.extent_widget.setMapCanvas(self.iface.mapCanvas())
            canvas = self.iface.mapCanvas()
            canvas_extent = canvas.extent()
            canvas_crs = canvas.mapSettings().destinationCrs()
            self.extent_widget.setCurrentExtent(canvas_extent, canvas_crs)
            self.extent_widget.setOriginalExtent(canvas_extent, canvas_crs)
            self.extent_widget.setOutputCrs(canvas_crs)
            aoi_form.addRow('AOI:', self.extent_widget)
        else:
            fallback = QLabel('QgsExtentWidget unavailable. Draw an AOI in your dreams instead.')
            fallback.setWordWrap(True)
            fallback.setStyleSheet(f'color: {self._LABEL_COLOR}; font-size: 10px;')
            aoi_form.addRow('', fallback)

        layout.addWidget(aoi_group)

        # --- Action buttons ---
        buttons = QHBoxLayout()

        self.go_btn = QPushButton('🚀 Search / Predict')
        self.go_btn.setToolTip('Archive → search catalogues  |  Tasking → predict overpasses')
        self.go_btn.clicked.connect(self._on_go_clicked)
        buttons.addWidget(self.go_btn)

        self.reset_btn = QPushButton('🔄 Reset')
        self.reset_btn.clicked.connect(self._reset_all)
        buttons.addWidget(self.reset_btn)

        layout.addLayout(buttons)

        # --- Results tabs ---
        self.results_tabs = QTabWidget()

        # Tab 0: Archive Results
        archive_tab = QWidget()
        archive_layout = QVBoxLayout(archive_tab)
        archive_layout.setContentsMargins(0, 0, 0, 0)

        self.archive_table = QTableWidget()
        self.archive_table.setColumnCount(6)
        self.archive_table.setHorizontalHeaderLabels(
            ['Provider', 'Date', 'Satellite', 'Cloud %', 'GSD (m)', 'Scene ID']
        )
        ahh = self.archive_table.horizontalHeader()
        ahh.setSectionResizeMode(QHeaderView.ResizeToContents)
        ahh.setStretchLastSection(True)
        self.archive_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.archive_table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.archive_table.setAlternatingRowColors(True)
        self.archive_table.setSortingEnabled(True)
        self.archive_table.itemSelectionChanged.connect(self._on_archive_row_selected)
        archive_layout.addWidget(self.archive_table)

        self.archive_count_label = QLabel('No search performed')
        self.archive_count_label.setStyleSheet(f'color: {self._LABEL_COLOR}; font-size: 10px;')
        archive_layout.addWidget(self.archive_count_label)

        self.results_tabs.addTab(archive_tab, '📦 Archive Results')

        # Tab 1: Overpass Predictions
        overpass_tab = QWidget()
        overpass_layout = QVBoxLayout(overpass_tab)
        overpass_layout.setContentsMargins(0, 0, 0, 0)

        self.overpass_table = QTableWidget()
        self.overpass_table.setColumnCount(9)
        self.overpass_table.setHorizontalHeaderLabels(
            ['Satellite', 'Operator', 'Date/Time (UTC)', 'Direction',
             'Max Elev (°)', 'Off-Nadir (°)', 'Dist (km)',
             'Duration (min)', 'Confidence']
        )
        ohh = self.overpass_table.horizontalHeader()
        ohh.setSectionResizeMode(QHeaderView.ResizeToContents)
        ohh.setStretchLastSection(True)
        self.overpass_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.overpass_table.setAlternatingRowColors(True)
        self.overpass_table.setSortingEnabled(True)
        self.overpass_table.itemSelectionChanged.connect(self._on_overpass_row_selected)
        overpass_layout.addWidget(self.overpass_table)

        self.overpass_count_label = QLabel('No prediction performed')
        self.overpass_count_label.setStyleSheet(f'color: {self._LABEL_COLOR}; font-size: 10px;')
        overpass_layout.addWidget(self.overpass_count_label)

        self.results_tabs.addTab(overpass_tab, '🛰️ Predicted Overpasses')

        # Tab 2: Mission Summary
        summary_tab = QWidget()
        summary_layout = QVBoxLayout(summary_tab)
        summary_layout.setContentsMargins(0, 0, 0, 0)

        self.summary_text = QTextEdit()
        self.summary_text.setReadOnly(True)
        self.summary_text.setStyleSheet(
            f'color: {self._LABEL_COLOR}; font-size: 10px; font-family: monospace;'
        )
        summary_layout.addWidget(self.summary_text)
        self.results_tabs.addTab(summary_tab, '📋 Summary')

        layout.addWidget(self.results_tabs)

        # --- Status ---
        self.status_label = QLabel('Ready — flip switches and pick a satellite.')
        self.status_label.setStyleSheet(f'color: {self._LABEL_COLOR}; font-size: 10px;')
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        # Initial mode label update
        self._update_mode_label()

    # ------------------------------------------------------------------
    # Filtering logic
    # ------------------------------------------------------------------

    def _apply_filters(self):
        """Re-filter the catalogue based on current switch positions."""
        sensor = self.sensor_combo.currentText()
        res_text = self.resolution_combo.currentText()
        access_text = self.access_combo.currentText()
        daylight_text = self.daylight_combo.currentText()

        filtered: List[Dict] = []
        for sat in SATELLITE_CATALOGUE:
            if sensor != 'All' and sat['sensor'] != sensor:
                continue
            if res_text.startswith('High') and sat['gsd_m'] > _GSD_HIGH:
                continue
            if res_text.startswith('Medium') and (sat['gsd_m'] > _GSD_MEDIUM or sat['gsd_m'] <= _GSD_HIGH):
                continue
            if res_text.startswith('Low') and sat['gsd_m'] <= _GSD_MEDIUM:
                continue
            if access_text == 'Paid' and sat['access'] != 'Paid':
                continue
            if access_text.startswith('Free') and sat['access'] != 'Free':
                continue
            if daylight_text == 'Day' and sat['daylight'] not in ('Day', 'Both'):
                continue
            if daylight_text == 'Night' and sat['daylight'] not in ('Night', 'Both'):
                continue
            filtered.append(sat)

        self._filtered_catalogue = filtered
        self._rebuild_operator_combo()

    def _rebuild_operator_combo(self):
        self.operator_combo.blockSignals(True)
        self.operator_combo.clear()
        operators = sorted({s['operator'] for s in self._filtered_catalogue})
        if not operators:
            self.operator_combo.addItem('(no matches — loosen the switches!)')
        else:
            self.operator_combo.addItem('All operators')
            for op in operators:
                self.operator_combo.addItem(op)
        self.operator_combo.blockSignals(False)
        self._on_operator_changed()

    def _on_operator_changed(self):
        self.constellation_combo.blockSignals(True)
        self.constellation_combo.clear()
        op_text = self.operator_combo.currentText()
        if op_text == 'All operators' or op_text.startswith('(no'):
            candidates = self._filtered_catalogue
        else:
            candidates = [s for s in self._filtered_catalogue if s['operator'] == op_text]
        constellations = sorted({s['constellation'] for s in candidates})
        if not constellations:
            self.constellation_combo.addItem('(none available)')
        else:
            if len(constellations) > 1:
                self.constellation_combo.addItem('All constellations')
            for c in constellations:
                self.constellation_combo.addItem(c)
        self.constellation_combo.blockSignals(False)
        self._on_constellation_changed()

    def _on_constellation_changed(self):
        cname = self.constellation_combo.currentText()
        sat = next((s for s in self._filtered_catalogue if s['constellation'] == cname), None)
        if sat:
            self.fun_fact_label.setText(
                f'💡 <b>{sat["constellation"]}</b> ({sat["operator"]}): {sat["fun_fact"]}'
            )
            self.fun_fact_label.show()
        elif cname in ('All constellations', '(none available)'):
            count = len(self._filtered_catalogue)
            if count:
                self.fun_fact_label.setText(
                    f'🎯 <b>{count}</b> satellite(s) match your filters. '
                    f'Narrow it down or just go with "All" — we won\'t judge.'
                )
            else:
                self.fun_fact_label.setText(
                    '🤷 Zero matches. Try loosening the switches above, '
                    'or accept that no satellite can solve everything. Yet.'
                )
            self.fun_fact_label.show()
        else:
            self.fun_fact_label.hide()

        n = len(self._filtered_catalogue)
        self.status_label.setText(f'{n} satellite(s) match your criteria. Pick one and hit 🚀.')
        self.status_label.setStyleSheet(f'color: {self._LABEL_COLOR}; font-size: 10px;')

    # ------------------------------------------------------------------
    # Mode (archive vs new tasking)
    # ------------------------------------------------------------------

    def _update_mode_label(self):
        today = date.today()
        end_py = self.date_end.date().toPyDate()
        start_py = self.date_start.date().toPyDate()

        if end_py <= today:
            self.mode_label.setText('📦 MODE: Archive Search (all dates in the past)')
            self.mode_label.setStyleSheet('color: #1565c0; font-weight: bold; font-size: 10px;')
            self.go_btn.setText('🔍 Search Archive')
        elif start_py > today:
            self.mode_label.setText('🛰️ MODE: New Tasking — Overpass Prediction')
            self.mode_label.setStyleSheet('color: #2e7d32; font-weight: bold; font-size: 10px;')
            self.go_btn.setText('🛰️ Predict Overpasses')
        else:
            self.mode_label.setText('🔀 MODE: Mixed (archive search + overpass prediction)')
            self.mode_label.setStyleSheet('color: #e65100; font-weight: bold; font-size: 10px;')
            self.go_btn.setText('🔍🛰️ Search + Predict')

    # ------------------------------------------------------------------
    # AOI helpers
    # ------------------------------------------------------------------

    def _get_aoi_bbox_wgs84(self) -> Optional[Tuple[float, float, float, float]]:
        if not self.extent_widget:
            return None
        try:
            extent = self.extent_widget.outputExtent()
            crs = self.extent_widget.outputCrs()
            if not extent or extent.isEmpty() or not crs or not crs.isValid():
                return None
            if crs.authid() != 'EPSG:4326':
                tr = QgsCoordinateTransform(
                    crs, QgsCoordinateReferenceSystem('EPSG:4326'),
                    QgsProject.instance(),
                )
                extent = tr.transformBoundingBox(extent)
            return (extent.xMinimum(), extent.yMinimum(), extent.xMaximum(), extent.yMaximum())
        except Exception as exc:
            logger.warning(f'Smart Tasking: AOI read failed: {exc}')
            return None

    def _get_aoi_center(self) -> Optional[Tuple[float, float]]:
        """Return (lat, lon) centre of the AOI in WGS 84."""
        bbox = self._get_aoi_bbox_wgs84()
        if not bbox:
            return None
        lat = (bbox[1] + bbox[3]) / 2.0
        lon = (bbox[0] + bbox[2]) / 2.0
        return lat, lon

    # ------------------------------------------------------------------
    # Dispatch (Search / Predict / both)
    # ------------------------------------------------------------------

    def _on_go_clicked(self):
        """Central dispatch — detect mode and launch appropriate task(s)."""
        today = date.today()
        start_py = self.date_start.date().toPyDate()
        end_py = self.date_end.date().toPyDate()

        selected = self._selected_satellites()
        if not selected:
            QMessageBox.warning(self, 'No Match', 'No satellites match your filters.')
            return

        bbox = self._get_aoi_bbox_wgs84()
        if not bbox:
            QMessageBox.warning(self, 'Missing AOI', 'Please define an Area of Interest.')
            return

        do_archive = end_py <= today or start_py <= today
        do_tasking = end_py > today

        if do_archive:
            self._launch_archive_search(selected, bbox, start_py, min(end_py, today))

        if do_tasking:
            tasking_start = max(start_py, today + timedelta(days=1))
            self._launch_overpass_prediction(selected, bbox, tasking_start, end_py)

        # Always generate text summary
        self._generate_summary(selected, bbox)

    # ------------------------------------------------------------------
    # Archive search
    # ------------------------------------------------------------------

    def _launch_archive_search(self, satellites: List[Dict], bbox, start_d, end_d):
        """Launch a background archive search using the connector framework."""
        connector_ids = set()
        for sat in satellites:
            for cid in sat.get('connector_ids', []):
                connector_ids.add(cid)

        if not connector_ids:
            self.archive_count_label.setText('No archive connectors for selected satellites.')
            return

        if not self._connector_manager:
            self.archive_count_label.setText('Connector manager unavailable.')
            return

        # Auto-authenticate where possible
        ready_ids = []
        for cid in connector_ids:
            if self._try_authenticate(cid):
                ready_ids.append(cid)

        if not ready_ids:
            self.archive_count_label.setText(
                'No connectors authenticated. Configure credentials in Settings.'
            )
            return

        params = {
            'bbox': list(bbox),
            'start_date': str(start_d),
            'end_date': str(end_d),
            'max_cloud_cover': 1.0,
            'limit': 50,
            'connector_ids': ready_ids,
        }

        self.go_btn.setEnabled(False)
        self.status_label.setText('Searching archives …')
        self.status_label.setStyleSheet('color: #88ccff; font-size: 10px;')

        if QGIS_AVAILABLE and hasattr(QgsApplication, 'taskManager'):
            task = _SmartSearchTask(self._connector_manager, params)
            self._active_search_task = task
            task.taskCompleted.connect(lambda: self._on_search_done(task))
            task.taskTerminated.connect(lambda: self._on_search_error(task))
            QgsApplication.taskManager().addTask(task)
        else:
            # Synchronous fallback
            task = _SmartSearchTask(self._connector_manager, params)
            task.run()
            self._on_search_done(task)

    def _on_search_done(self, task: _SmartSearchTask):
        self.go_btn.setEnabled(True)
        self._search_results = task.results or []
        self._populate_archive_table()
        self.results_tabs.setCurrentIndex(0)
        n = len(self._search_results)
        self.status_label.setText(f'Archive search complete — {n} scene(s)')
        self.status_label.setStyleSheet('color: #00ffbf; font-size: 10px;')

    def _on_search_error(self, task: _SmartSearchTask):
        self.go_btn.setEnabled(True)
        msg = task.error_message or 'Unknown error'
        self.status_label.setText(f'Archive search failed: {msg}')
        self.status_label.setStyleSheet('color: #ff6b6b; font-size: 10px;')

    def _populate_archive_table(self):
        self.archive_table.setSortingEnabled(False)
        self.archive_table.setRowCount(0)

        for row_idx, item in enumerate(self._search_results):
            props = item.get('properties', item)
            provider  = str(item.get('_provider', props.get('provider', '')))
            date_str  = str(props.get('datetime', props.get('date', '')))[:10]
            satellite = str(props.get('platform', props.get('satellite_id',
                            props.get('constellation', ''))))
            cloud_raw = props.get('eo:cloud_cover', props.get('cloud_cover', ''))
            cloud_str = f'{float(cloud_raw):.1f}' if cloud_raw not in ('', None) else 'N/A'
            gsd_raw   = props.get('gsd', props.get('eo:gsd', ''))
            gsd_str   = f'{float(gsd_raw):.1f}' if gsd_raw not in ('', None) else 'N/A'
            scene_id  = str(item.get('id', props.get('id', '')))

            self.archive_table.insertRow(row_idx)
            pi = QTableWidgetItem(provider)
            pi.setData(Qt.UserRole, row_idx)
            self.archive_table.setItem(row_idx, self._COL_PROVIDER,  pi)
            self.archive_table.setItem(row_idx, self._COL_DATE,      QTableWidgetItem(date_str))
            self.archive_table.setItem(row_idx, self._COL_SATELLITE, QTableWidgetItem(satellite))
            ci = _NumItem(cloud_str); ci.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.archive_table.setItem(row_idx, self._COL_CLOUD, ci)
            gi = _NumItem(gsd_str);   gi.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.archive_table.setItem(row_idx, self._COL_GSD, gi)
            self.archive_table.setItem(row_idx, self._COL_ID, QTableWidgetItem(scene_id))

        self.archive_table.setSortingEnabled(True)
        count = len(self._search_results)
        self.archive_count_label.setText(f'{count} result(s) found')

        if count > 0:
            self._refresh_footprints_layer()

    def _on_archive_row_selected(self):
        """Highlight selected footprints on map."""
        rows = {idx.row() for idx in self.archive_table.selectionModel().selectedRows()}
        if not self._footprints_layer or not QGIS_AVAILABLE:
            return
        try:
            layer = QgsProject.instance().mapLayersByName('SmartTasking Footprints')
            if not layer:
                return
            layer = layer[0]
            fids = []
            for feat in layer.getFeatures():
                if feat.attribute('index') in rows:
                    fids.append(feat.id())
            layer.selectByIds(fids)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # 3D overpass visualisation (QGIS native 3D view)
    # ------------------------------------------------------------------

    def _on_overpass_row_selected(self):
        """Visualise the selected overpass in the QGIS 3D view."""
        rows = sorted(
            {idx.row() for idx in self.overpass_table.selectionModel().selectedRows()}
        )
        if not rows:
            self._remove_3d_layers()
            return
        vis_row = rows[0]  # one pass at a time
        item = self.overpass_table.item(vis_row, self._OV_SAT)
        if not item:
            return
        orig_idx = item.data(Qt.UserRole)
        if orig_idx is None or orig_idx >= len(self._overpass_results):
            return
        self._visualize_overpass_3d(self._overpass_results[orig_idx])

    def _visualize_overpass_3d(self, op: Dict):
        """Create five memory layers for a single satellite overpass.

        • **SmartTasking Orbit Track** — LineStringZ full orbit at altitude (white)
        • **SmartTasking Ground Track** — LineString on the surface (cyan)
        • **SmartTasking Swath**        — Polygon swath corridor (cyan, semi-transparent)
        • **SmartTasking Satellite**    — PointZ at orbital altitude (red)
        • **SmartTasking Nadir Axis**   — LineStringZ surface → satellite (red)

        Layers get proper 2D symbology (always works) **plus** QGIS-native 3D
        renderers when the ``qgis._3d`` module is available.
        """
        if not QGIS_AVAILABLE:
            return

        lat = op.get('sub_sat_lat')
        lon = op.get('sub_sat_lon')
        alt_km = op.get('orbit_alt_km', 600.0)
        swath_km = op.get('swath_km', 20.0)

        if lat is None or lon is None:
            logger.debug('Overpass has no sub-satellite coords — skipping 3D')
            return

        alt_m = alt_km * 1000.0
        orbit_track = op.get('orbit_track', [])
        ground_track = op.get('ground_track', [])
        swath_ribbon = op.get('swath_ribbon', [])

        # Remove previous visualisation
        self._remove_3d_layers()

        proj = QgsProject.instance()
        fld = QgsFields()
        fld.append(QgsField('name', QVariant.String))

        # ---- 1. Orbit track (LineStringZ at orbital altitude) --------
        orbit_layer = None
        if len(orbit_track) >= 2:
            orbit_layer = QgsVectorLayer(
                'LineStringZ?crs=EPSG:4326', 'SmartTasking Orbit Track', 'memory',
            )
            op_ = orbit_layer.dataProvider()
            op_.addAttributes(fld)
            orbit_layer.updateFields()

            # Split into segments to avoid antimeridian wrap artefacts
            segments: List[List[Tuple]] = []
            seg: List[Tuple] = [orbit_track[0]]
            for i in range(1, len(orbit_track)):
                if abs(orbit_track[i][0] - orbit_track[i - 1][0]) > 180:
                    if len(seg) >= 2:
                        segments.append(seg)
                    seg = []
                seg.append(orbit_track[i])
            if len(seg) >= 2:
                segments.append(seg)

            for seg in segments:
                coords = ', '.join(f'{p[0]} {p[1]} {p[2]}' for p in seg)
                feat = QgsFeature(orbit_layer.fields())
                feat.setGeometry(QgsGeometry.fromWkt(f'LINESTRINGZ({coords})'))
                feat.setAttribute('name', 'Orbit')
                op_.addFeatures([feat])

            orbit_layer.updateExtents()
            orbit_layer.renderer().setSymbol(QgsLineSymbol.createSimple({
                'color': '#ffffff', 'width': '0.6',
            }))

        # ---- 2. Ground track (LineString on surface) -----------------
        ground_layer = None
        if len(ground_track) >= 2:
            ground_layer = QgsVectorLayer(
                'LineString?crs=EPSG:4326', 'SmartTasking Ground Track', 'memory',
            )
            gp = ground_layer.dataProvider()
            gp.addAttributes(fld)
            ground_layer.updateFields()

            segments = []
            seg = [ground_track[0]]
            for i in range(1, len(ground_track)):
                if abs(ground_track[i][0] - ground_track[i - 1][0]) > 180:
                    if len(seg) >= 2:
                        segments.append(seg)
                    seg = []
                seg.append(ground_track[i])
            if len(seg) >= 2:
                segments.append(seg)

            for seg in segments:
                coords = ', '.join(f'{p[0]} {p[1]}' for p in seg)
                feat = QgsFeature(ground_layer.fields())
                feat.setGeometry(QgsGeometry.fromWkt(f'LINESTRING({coords})'))
                feat.setAttribute('name', 'Ground')
                gp.addFeatures([feat])

            ground_layer.updateExtents()
            ground_layer.renderer().setSymbol(QgsLineSymbol.createSimple({
                'color': '#00cccc', 'width': '1.0',
            }))

        # ---- 3. Swath corridor (Polygon on surface) ------------------
        swath_layer = None
        if len(swath_ribbon) >= 4:
            swath_layer = QgsVectorLayer(
                'Polygon?crs=EPSG:4326', 'SmartTasking Swath', 'memory',
            )
            swp = swath_layer.dataProvider()
            swp.addAttributes(fld)
            swath_layer.updateFields()

            # Clamp coordinates to valid geographic range
            clamped = []
            for pt in swath_ribbon:
                clon = max(-180.0, min(180.0, pt[0]))
                clat = max(-90.0, min(90.0, pt[1]))
                clamped.append((clon, clat))

            coords = ', '.join(f'{p[0]} {p[1]}' for p in clamped)
            feat = QgsFeature(swath_layer.fields())
            feat.setGeometry(QgsGeometry.fromWkt(f'POLYGON(({coords}))'))
            feat.setAttribute('name', 'Swath')
            swp.addFeatures([feat])
            swath_layer.updateExtents()

            swath_layer.renderer().setSymbol(QgsFillSymbol.createSimple({
                'color': '0,204,204,60',
                'outline_color': '#00cccc',
                'outline_width': '0.3',
            }))

        # ---- 4. Satellite position (PointZ) --------------------------
        sat_layer = QgsVectorLayer(
            'PointZ?crs=EPSG:4326', 'SmartTasking Satellite', 'memory',
        )
        sp = sat_layer.dataProvider()
        sp.addAttributes(fld)
        sat_layer.updateFields()

        sat_feat = QgsFeature(sat_layer.fields())
        sat_feat.setGeometry(
            QgsGeometry.fromWkt(f'POINTZ({lon} {lat} {alt_m})'),
        )
        sat_feat.setAttribute('name', op.get('satellite', ''))
        sp.addFeatures([sat_feat])
        sat_layer.updateExtents()

        sat_layer.renderer().setSymbol(QgsMarkerSymbol.createSimple({
            'name': 'circle', 'color': '#ff0000', 'size': '5',
            'outline_color': '#cc0000', 'outline_width': '0.4',
        }))

        # ---- 5. Nadir axis (LineStringZ) -----------------------------
        nadir_layer = QgsVectorLayer(
            'LineStringZ?crs=EPSG:4326', 'SmartTasking Nadir Axis', 'memory',
        )
        np_ = nadir_layer.dataProvider()
        np_.addAttributes(fld)
        nadir_layer.updateFields()

        nadir_feat = QgsFeature(nadir_layer.fields())
        nadir_feat.setGeometry(QgsGeometry.fromWkt(
            f'LINESTRINGZ({lon} {lat} 0, {lon} {lat} {alt_m})',
        ))
        nadir_feat.setAttribute('name', 'Nadir')
        np_.addFeatures([nadir_feat])
        nadir_layer.updateExtents()

        nadir_layer.renderer().setSymbol(QgsLineSymbol.createSimple({
            'color': '#ff3300', 'width': '1.0',
        }))

        # ---- 3D rendering (best-effort) ------------------------------
        self._apply_3d_rendering(
            orbit_layer, ground_layer, swath_layer,
            sat_layer, nadir_layer, alt_m,
        )

        # ---- Add to project -----------------------------------------
        layers = [swath_layer, ground_layer, orbit_layer, nadir_layer, sat_layer]
        for lyr in layers:
            if lyr is not None:
                proj.addMapLayer(lyr)

        self._3d_orbit_layer = orbit_layer
        self._3d_ground_layer = ground_layer
        self._3d_swath_layer = swath_layer
        self._3d_sat_layer = sat_layer
        self._3d_nadir_layer = nadir_layer

        logger.info(
            f'3D overpass: {op.get("satellite", "?")} at '
            f'({lat:.2f}, {lon:.2f}), alt={alt_km:.0f} km, '
            f'orbit={len(orbit_track)} pts, swath={len(swath_ribbon)} pts'
        )

    def _apply_3d_rendering(
        self, orbit_layer, ground_layer, swath_layer,
        sat_layer, nadir_layer, alt_m: float,
    ):
        """Configure QGIS native 3D renderers (silently degrades to 2D)."""
        if not _3D_AVAILABLE:
            return
        try:
            # Resolve altitude-clamping constant (API changed in 3.36)
            try:
                from qgis.core import Qgis
                _CLAMP = Qgis.AltitudeClamping.Absolute
            except (ImportError, AttributeError):
                _CLAMP = 0  # Qgs3DTypes.AltClampAbsolute

            # ---- Orbit track: white tube at orbital altitude ----
            if orbit_layer is not None:
                ol_sym = QgsLine3DSymbol()
                ol_mat = QgsPhongMaterialSettings()
                ol_mat.setDiffuse(QColor(255, 255, 255))
                ol_mat.setAmbient(QColor(200, 200, 200))
                ol_sym.setMaterialSettings(ol_mat)
                ol_sym.setWidth(max(500.0, alt_m * 0.002))
                ol_sym.setAltitudeClamping(_CLAMP)
                r_o = QgsVectorLayer3DRenderer()
                r_o.setSymbol(ol_sym)
                r_o.setLayer(orbit_layer)
                orbit_layer.setRenderer3D(r_o)

            # ---- Ground track: cyan line on surface ----
            if ground_layer is not None:
                gl_sym = QgsLine3DSymbol()
                gl_mat = QgsPhongMaterialSettings()
                gl_mat.setDiffuse(QColor(0, 204, 204))
                gl_mat.setAmbient(QColor(0, 160, 160))
                gl_sym.setMaterialSettings(gl_mat)
                gl_sym.setWidth(max(300.0, alt_m * 0.001))
                gl_sym.setAltitudeClamping(_CLAMP)
                r_g = QgsVectorLayer3DRenderer()
                r_g.setSymbol(gl_sym)
                r_g.setLayer(ground_layer)
                ground_layer.setRenderer3D(r_g)

            # ---- Swath corridor: semi-transparent cyan ----
            if swath_layer is not None:
                sw_sym = QgsPolygon3DSymbol()
                sw_mat = QgsPhongMaterialSettings()
                sw_mat.setDiffuse(QColor(0, 204, 204, 80))
                sw_mat.setAmbient(QColor(0, 160, 160, 50))
                sw_sym.setMaterialSettings(sw_mat)
                sw_sym.setExtrusionHeight(200.0)
                sw_sym.setAltitudeClamping(_CLAMP)
                r_s = QgsVectorLayer3DRenderer()
                r_s.setSymbol(sw_sym)
                r_s.setLayer(swath_layer)
                swath_layer.setRenderer3D(r_s)

            # ---- Satellite: red sphere ----
            pt_sym = QgsPoint3DSymbol()
            pt_mat = QgsPhongMaterialSettings()
            pt_mat.setDiffuse(QColor(255, 0, 0))
            pt_mat.setAmbient(QColor(204, 0, 0))
            pt_sym.setMaterialSettings(pt_mat)
            pt_sym.setShape(1)                       # 1 = Sphere
            radius = max(3000.0, alt_m * 0.008)
            pt_sym.setShapeProperties({'radius': radius})
            pt_sym.setAltitudeClamping(_CLAMP)
            r1 = QgsVectorLayer3DRenderer()
            r1.setSymbol(pt_sym)
            r1.setLayer(sat_layer)
            sat_layer.setRenderer3D(r1)

            # ---- Nadir axis: thick red/orange tube ----
            ln_sym = QgsLine3DSymbol()
            ln_mat = QgsPhongMaterialSettings()
            ln_mat.setDiffuse(QColor(255, 60, 0))
            ln_mat.setAmbient(QColor(204, 40, 0))
            ln_sym.setMaterialSettings(ln_mat)
            ln_sym.setWidth(max(800.0, alt_m * 0.003))
            ln_sym.setAltitudeClamping(_CLAMP)
            r2 = QgsVectorLayer3DRenderer()
            r2.setSymbol(ln_sym)
            r2.setLayer(nadir_layer)
            nadir_layer.setRenderer3D(r2)

            logger.debug('3D rendering configured for overpass layers')

        except Exception as exc:
            logger.warning(f'3D rendering setup failed (2D fallback active): {exc}')

    def _remove_3d_layers(self):
        """Remove all SmartTasking 3D layers from the project."""
        if not QGIS_AVAILABLE:
            return
        proj = QgsProject.instance()
        for attr in ('_3d_orbit_layer', '_3d_ground_layer', '_3d_swath_layer',
                    '_3d_sat_layer', '_3d_nadir_layer'):
            layer = getattr(self, attr, None)
            if layer is not None:
                try:
                    proj.removeMapLayer(layer.id())
                except Exception:
                    pass
                setattr(self, attr, None)

    # ------------------------------------------------------------------
    # Footprints layer (for archive results)
    # ------------------------------------------------------------------

    def _refresh_footprints_layer(self):
        if not QGIS_AVAILABLE or not self._search_results:
            return
        try:
            existing = QgsProject.instance().mapLayersByName('SmartTasking Footprints')
            if existing:
                QgsProject.instance().removeMapLayer(existing[0].id())

            layer = QgsVectorLayer('Polygon?crs=EPSG:4326', 'SmartTasking Footprints', 'memory')
            pr = layer.dataProvider()

            fields = QgsFields()
            fields.append(QgsField('index', QVariant.Int))
            fields.append(QgsField('provider', QVariant.String))
            fields.append(QgsField('date', QVariant.String))
            fields.append(QgsField('id', QVariant.String))
            pr.addAttributes(fields)
            layer.updateFields()

            features: List[QgsFeature] = []
            for idx, item in enumerate(self._search_results):
                geom = self._item_to_geometry(item)
                if geom is None:
                    continue
                props = item.get('properties', item)
                feat = QgsFeature(layer.fields())
                feat.setGeometry(geom)
                feat.setAttribute('index', idx)
                feat.setAttribute('provider', str(item.get('_provider', '')))
                feat.setAttribute('date', str(props.get('datetime', ''))[:10])
                feat.setAttribute('id', str(item.get('id', '')))
                features.append(feat)

            pr.addFeatures(features)
            layer.updateExtents()

            sym = QgsFillSymbol.createSimple({
                'color': '0,120,255,60',
                'outline_color': '#0078ff',
                'outline_width': '0.4',
            })
            layer.renderer().setSymbol(sym)
            QgsProject.instance().addMapLayer(layer)
            self._footprints_layer = layer
        except Exception as exc:
            logger.warning(f'Footprint layer failed: {exc}')

    @staticmethod
    def _item_to_geometry(item: Dict) -> Optional[Any]:
        """Convert a STAC item geometry to QgsGeometry."""
        geom_data = item.get('geometry')
        if not geom_data:
            bbox = item.get('bbox')
            if bbox and len(bbox) >= 4:
                pts = [
                    QgsPointXY(bbox[0], bbox[1]),
                    QgsPointXY(bbox[2], bbox[1]),
                    QgsPointXY(bbox[2], bbox[3]),
                    QgsPointXY(bbox[0], bbox[3]),
                ]
                return QgsGeometry.fromPolygonXY([pts])
            return None
        gtype = geom_data.get('type', '').lower()
        coords = geom_data.get('coordinates', [])
        if gtype == 'polygon' and coords:
            rings = []
            for ring in coords:
                rings.append([QgsPointXY(c[0], c[1]) for c in ring])
            return QgsGeometry.fromPolygonXY(rings)
        if gtype == 'multipolygon' and coords:
            polys = []
            for poly in coords:
                rings = []
                for ring in poly:
                    rings.append([QgsPointXY(c[0], c[1]) for c in ring])
                polys.append(rings)
            return QgsGeometry.fromMultiPolygonXY(polys)
        return None

    # ------------------------------------------------------------------
    # Overpass prediction
    # ------------------------------------------------------------------

    def _launch_overpass_prediction(self, satellites: List[Dict], bbox, start_d, end_d):
        center = self._get_aoi_center()
        if not center:
            self.overpass_count_label.setText('Cannot determine AOI centre.')
            return

        lat, lon = center
        start_dt = datetime(start_d.year, start_d.month, start_d.day, tzinfo=timezone.utc)
        end_dt = datetime(end_d.year, end_d.month, end_d.day, 23, 59, 59, tzinfo=timezone.utc)

        self.status_label.setText('Predicting overpasses …')
        self.status_label.setStyleSheet('color: #88ccff; font-size: 10px;')

        if QGIS_AVAILABLE and hasattr(QgsApplication, 'taskManager'):
            task = _OverpassTask(satellites, lat, lon, start_dt, end_dt)
            self._active_overpass_task = task
            task.taskCompleted.connect(lambda: self._on_overpass_done(task))
            task.taskTerminated.connect(lambda: self._on_overpass_error(task))
            QgsApplication.taskManager().addTask(task)
        else:
            # Synchronous fallback
            task = _OverpassTask(satellites, lat, lon, start_dt, end_dt)
            task.run()
            self._on_overpass_done(task)

    def _on_overpass_done(self, task: _OverpassTask):
        self.go_btn.setEnabled(True)
        self._overpass_results = task.results or []
        self._populate_overpass_table()
        self.results_tabs.setCurrentIndex(1)
        n = len(self._overpass_results)
        method = 'SGP4' if _SGP4_OK else 'analytical model'
        self.status_label.setText(f'Prediction complete — {n} overpass(es) ({method})')
        self.status_label.setStyleSheet('color: #00e5ff; font-size: 10px;')

    def _on_overpass_error(self, task: _OverpassTask):
        self.go_btn.setEnabled(True)
        msg = task.error_message or 'Unknown error'
        self.status_label.setText(f'Overpass prediction failed: {msg}')
        self.status_label.setStyleSheet('color: #ff6b6b; font-size: 10px;')

    def _populate_overpass_table(self):
        self.overpass_table.blockSignals(True)
        self.overpass_table.setSortingEnabled(False)
        self.overpass_table.setRowCount(0)

        for row_idx, p in enumerate(self._overpass_results):
            self.overpass_table.insertRow(row_idx)
            sat_item = QTableWidgetItem(str(p.get('satellite', '')))
            sat_item.setData(Qt.UserRole, row_idx)
            self.overpass_table.setItem(row_idx, self._OV_SAT, sat_item)
            self.overpass_table.setItem(row_idx, self._OV_OPERATOR,
                                        QTableWidgetItem(str(p.get('operator', ''))))
            self.overpass_table.setItem(row_idx, self._OV_TIME,
                                        QTableWidgetItem(str(p.get('datetime_utc', ''))))
            self.overpass_table.setItem(row_idx, self._OV_DIR,
                                        QTableWidgetItem(str(p.get('direction', ''))))
            ei = _NumItem(str(p.get('max_elevation', '')))
            ei.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.overpass_table.setItem(row_idx, self._OV_ELEV, ei)
            oi = _NumItem(str(p.get('off_nadir_deg', '')))
            oi.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.overpass_table.setItem(row_idx, self._OV_ONA, oi)
            gi = _NumItem(str(p.get('ground_dist_km', '')))
            gi.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.overpass_table.setItem(row_idx, self._OV_DIST, gi)
            di = _NumItem(str(p.get('duration_min', '')))
            di.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.overpass_table.setItem(row_idx, self._OV_DUR, di)
            self.overpass_table.setItem(row_idx, self._OV_CONF,
                                        QTableWidgetItem(str(p.get('confidence', ''))))

        self.overpass_table.setSortingEnabled(True)
        self.overpass_table.blockSignals(False)
        count = len(self._overpass_results)
        self.overpass_count_label.setText(f'{count} overpass(es) predicted')

    # ------------------------------------------------------------------
    # Text summary (tab 3)
    # ------------------------------------------------------------------

    def _generate_summary(self, selected: List[Dict], bbox):
        """Build a human-readable mission summary."""
        start_str = self.date_start.date().toString('yyyy-MM-dd')
        end_str = self.date_end.date().toString('yyyy-MM-dd')

        today = date.today()
        end_py = self.date_end.date().toPyDate()
        start_py = self.date_start.date().toPyDate()
        if end_py <= today:
            mode = 'ARCHIVE SEARCH'
        elif start_py > today:
            mode = 'OVERPASS PREDICTION'
        else:
            mode = 'MIXED (Archive + Prediction)'

        bbox_str = (
            f'[{bbox[0]:.4f}, {bbox[1]:.4f}, {bbox[2]:.4f}, {bbox[3]:.4f}]'
            if bbox else 'Not defined'
        )

        sgp4_tag = '✅ SGP4 available' if _SGP4_OK else '⚠️ SGP4 not installed — using analytical model'

        lines = [
            '═══════════════════════════════════════',
            '         SMART TASKING SUMMARY',
            '═══════════════════════════════════════',
            '',
            f'  Mode          : {mode}',
            f'  Time Window   : {start_str}  →  {end_str}',
            f'  AOI (WGS84)   : {bbox_str}',
            f'  Sensor        : {self.sensor_combo.currentText()}',
            f'  Resolution    : {self.resolution_combo.currentText()}',
            f'  Access        : {self.access_combo.currentText()}',
            f'  Daylight      : {self.daylight_combo.currentText()}',
            f'  Orbit engine  : {sgp4_tag}',
            '',
            '───────────────────────────────────────',
            f'  Selected satellites: {len(selected)}',
            '───────────────────────────────────────',
        ]

        for s in selected:
            res_tag = _resolution_label(s['gsd_m'])
            connectors = ', '.join(s.get('connector_ids', [])) or 'none'
            lines.append(
                f'  • {s["constellation"]:26s}  '
                f'{s["operator"]:22s}  '
                f'{s["gsd_m"]:6.2f} m  '
                f'{res_tag:6s}  '
                f'{s["access"]:5s}  '
                f'[{connectors}]'
            )

        if self._search_results:
            lines += [
                '',
                '───────────────────────────────────────',
                f'  Archive results: {len(self._search_results)} scene(s)',
                '───────────────────────────────────────',
            ]
        if self._overpass_results:
            lines += [
                '',
                '───────────────────────────────────────',
                f'  Predicted overpasses: {len(self._overpass_results)} pass(es)',
                '───────────────────────────────────────',
            ]
            # Top-5 overpasses by elevation
            top = sorted(self._overpass_results, key=lambda p: -p.get('max_elevation', 0))[:5]
            for p in top:
                lines.append(
                    f'  ▸ {p["satellite"]:22s}  {p["datetime_utc"]:20s}  '
                    f'elev {p["max_elevation"]:5.1f}°  {p["direction"]}'
                )

        lines += [
            '',
            '───────────────────────────────────────',
            '  Tip: narrow filters → fewer options → less indecision.',
            '  Or just pick the cheapest one. We won\'t tell.',
            '═══════════════════════════════════════',
        ]

        self.summary_text.setPlainText('\n'.join(lines))
        self.results_tabs.setCurrentIndex(2)
        logger.info(f'Smart Tasking summary: {len(selected)} satellites, mode={mode}')

    # ------------------------------------------------------------------
    # Satellite selection helper
    # ------------------------------------------------------------------

    def _selected_satellites(self) -> List[Dict]:
        """Return the satellite(s) matching current operator/constellation selection."""
        cname = self.constellation_combo.currentText()
        op_text = self.operator_combo.currentText()

        if cname not in ('All constellations', '(none available)'):
            return [s for s in self._filtered_catalogue if s['constellation'] == cname]
        if op_text not in ('All operators', '') and not op_text.startswith('('):
            return [s for s in self._filtered_catalogue if s['operator'] == op_text]
        return list(self._filtered_catalogue)

    # ------------------------------------------------------------------
    # Connector authentication helper
    # ------------------------------------------------------------------

    def _try_authenticate(self, connector_id: str) -> bool:
        """Best-effort authentication for a connector. Returns True if ready."""
        if not self._connector_manager:
            return False

        ci = getattr(self._connector_manager, '_connectors', {}).get(connector_id)
        if not ci:
            return False

        caps = ci.get('capabilities', [])
        from ..connectors.connector_manager import ConnectorCapability
        needs_auth = ConnectorCapability.AUTHENTICATION in caps
        if not needs_auth:
            ci['authenticated'] = True
            return True

        # Read credentials from secure storage / QSettings
        creds = self._read_credentials(connector_id)
        if not creds:
            return False

        try:
            return bool(self._connector_manager.authenticate_connector(connector_id, creds))
        except Exception:
            return False

    def _read_credentials(self, connector_id: str) -> Optional[Dict[str, Any]]:
        """Read credentials from secure storage / QSettings (mirrors archive_dock)."""
        try:
            from ..secrets.secure_storage import get_secure_storage
            ss = get_secure_storage()
        except ImportError:
            ss = None

        s = QSettings()

        if connector_id == 'planet':
            creds = (ss.get_credentials('planet') if ss else {}) or {}
            token = (creds.get('access_token') or '').strip()
            if not token:
                return {}
            return {
                'access_token': token,
                'api_base_url': str(s.value('altair/planet_api_base_url',
                                             'https://services.sentinel-hub.com')).strip(),
            }

        if connector_id == 'oneatlas':
            return (ss.get_credentials('oneatlas') if ss else {}) or {}

        if connector_id == 'copernicus_stac':
            return (ss.get_credentials('copernicus') if ss else {}) or {}

        if connector_id == 'iceye_stac':
            creds = (ss.get_credentials('iceye') if ss else {}) or {}
            token = (creds.get('access_token') or '').strip()
            if not token:
                return {}
            return {
                'access_token': token,
                'api_base_url': str(s.value('altair/iceye_endpoint', 'https://api.iceye.com')).strip(),
                'contract_id': str(s.value('altair/iceye_contract_id', '')).strip() or None,
                'collections': str(s.value('altair/iceye_collections', '')).strip() or None,
            }

        if connector_id == 'umbra_stac':
            creds = (ss.get_credentials('umbra') if ss else {}) or {}
            token = (creds.get('access_token') or '').strip()
            cid = (creds.get('client_id') or '').strip()
            csec = (creds.get('client_secret') or '').strip()
            if not token and not (cid and csec):
                return {}
            return {
                'access_token': token,
                'client_id': cid or None,
                'client_secret': csec or None,
                'api_base_url': str(s.value('altair/umbra_api_base_url',
                                             'https://api.canopy.umbra.space')).strip(),
            }

        if connector_id == 'capella_stac':
            return (ss.get_credentials('capella') if ss else {}) or {}

        if connector_id == 'nasa_earthdata':
            creds = (ss.get_credentials('nasa_earthdata') if ss else {}) or {}
            username = (creds.get('username') or '').strip()
            password = (creds.get('password') or '').strip()
            token = (creds.get('access_token') or creds.get('token') or '').strip()
            if not username:
                username = str(s.value('altair/nasa_earthdata_username',
                                        s.value('altair/nasa_username', ''))).strip()
            if not password:
                password = str(s.value('altair/nasa_earthdata_password',
                                        s.value('altair/nasa_password', ''))).strip()
            if not token:
                token = str(s.value('altair/nasa_earthdata_token',
                                     s.value('altair/nasa_access_token', ''))).strip()
            if not (token or (username and password)):
                return {}
            return {
                'username': username or None,
                'password': password or None,
                'access_token': token or None,
            }

        return {}

    # ------------------------------------------------------------------
    # Reset
    # ------------------------------------------------------------------

    def _reset_all(self):
        self.date_start.setDate(QDate.currentDate().addMonths(-1))
        self.date_end.setDate(QDate.currentDate().addDays(14))
        self.sensor_combo.setCurrentIndex(0)
        self.resolution_combo.setCurrentIndex(0)
        self.access_combo.setCurrentIndex(0)
        self.daylight_combo.setCurrentIndex(0)
        if self.extent_widget and self.iface:
            canvas = self.iface.mapCanvas()
            ext = canvas.extent()
            crs = canvas.mapSettings().destinationCrs()
            self.extent_widget.setCurrentExtent(ext, crs)
            self.extent_widget.setOriginalExtent(ext, crs)
            self.extent_widget.setOutputCrs(crs)
        self.archive_table.setRowCount(0)
        self.overpass_table.setRowCount(0)
        self.summary_text.clear()
        self._search_results.clear()
        self._overpass_results.clear()
        self._remove_3d_layers()
        self.fun_fact_label.setText('')
        self.archive_count_label.setText('No search performed')
        self.overpass_count_label.setText('No prediction performed')
        self.status_label.setText('Reset complete — switches back to default. Go again!')
        self.status_label.setStyleSheet(f'color: {self._LABEL_COLOR}; font-size: 10px;')
