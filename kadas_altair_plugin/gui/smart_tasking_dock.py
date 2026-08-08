"""
Altair Tasking Dock Widget

A delightfully simple panel that helps you figure out which satellite
operator to throw money at (or beg data from).  Flip a few switches,
pick your favourite space robot, and let the plugin do the rest.

**Archive mode** — searches real catalogues via the connector framework
and lists results in the same tabular format as the Archive dock.

**Tasking mode** — predicts future satellite overpasses above your AOI
using SGP4 orbital propagation (when available) or a fast analytical
sun-synchronous model.  Think *eo-predictor* but inside QGIS.

No animals were harmed.  Probably.
"""

from __future__ import annotations

import math
import os
import tempfile
import urllib.request
import inspect
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from qgis.PyQt.QtCore import QDate, QItemSelectionModel, Qt, QSettings, QUrl, QVariant, pyqtSignal
from qgis.PyQt.QtGui import QColor, QFont, QPixmap
from qgis.PyQt.QtNetwork import QNetworkRequest
from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDateEdit,
    QDockWidget,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
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
        QgsBlockingNetworkRequest,
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
        QgsRasterLayer,
        QgsRectangle,
        QgsTask,
        QgsVectorLayer,
    )
    QGIS_AVAILABLE = True
except ImportError:
    QgsTask = object  # type: ignore
    QGIS_AVAILABLE = False

from ..logger import get_logger
from .aoi_draw_tool import AoiWidget
from .footprint_tool import FootprintSelectionTool

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
# Satellite catalogue
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
        'id': 'vantor_wv3', 'operator': 'Vantor',
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
        'id': 'vantor_wv2', 'operator': 'Vantor',
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
        'id': 'vantor_legion', 'operator': 'Vantor',
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
        'id': 'jilin_gaofen', 'operator': 'CGSTL',
        'constellation': 'Jilin-1 Gaofen', 'sensor': 'Optical',
        'gsd_m': 0.72, 'access': 'Paid', 'daylight': 'Day',
        'fun_fact': 'Large agile fleet focused on high-frequency revisit tasking.',
        'norad_id': 52836, 'connector_ids': ['jilin_gaofen_stac'],
        'orbit_alt_km': 535, 'orbit_inc_deg': 97.5,
        'orbit_period_min': 95.3, 'swath_km': 17.0,
        'revisit_days': 1.0, 'ltan_hour': 10.5,
        'sensor_model': 'off_nadir', 'max_off_nadir_deg': 30.0,
    },
    {
        'id': 'jaxa_alos2', 'operator': 'JAXA',
        'constellation': 'ALOS-2 (PALSAR-2)', 'sensor': 'SAR',
        'gsd_m': 10.0, 'access': 'Free', 'daylight': 'Both',
        'fun_fact': 'L-band SAR from Japan with strong all-weather monitoring capability.',
        'norad_id': 39766, 'connector_ids': ['jaxa_earth_stac'],
        'orbit_alt_km': 628, 'orbit_inc_deg': 97.9,
        'orbit_period_min': 97.4, 'swath_km': 70.0,
        'revisit_days': 14.0, 'ltan_hour': 12.0,
        'sensor_model': 'off_nadir', 'max_off_nadir_deg': 35.0,
    },
    # --- Optical / Free ------------------------------------------------
    {
        'id': 'esa_s2', 'operator': 'ESA / Copernicus',
        'constellation': 'Sentinel-2', 'sensor': 'Optical',
        'gsd_m': 10.0, 'access': 'Free', 'daylight': 'Day',
        'fun_fact': 'Free, 10 m, global. The people\'s satellite.',
        'norad_id': 40697,
        'connector_ids': ['element84_stac', 'planetary_computer_stac'],
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
        'norad_id': 49260,
        'connector_ids': [
            'element84_stac',
            'planetary_computer_stac',
            'nasa_earthdata',
        ],
        'orbit_alt_km': 705, 'orbit_inc_deg': 98.2,
        'orbit_period_min': 98.9, 'swath_km': 185.0,
        'revisit_days': 16.0, 'ltan_hour': 10.0,
        'sensor_model': 'pushbroom', 'max_off_nadir_deg': 0.0,
    },
    #{
    #    'id': 'vantor_opendata', 'operator': 'Vantor Open Data',
    #    'constellation': 'WorldView (open events)', 'sensor': 'Optical',
    #    'gsd_m': 0.50, 'access': 'Free', 'daylight': 'Day',
    #    'fun_fact': 'After disasters Vantor opens the vault. Heroes in orbit.',
    #    'norad_id': 40115, 'connector_ids': ['vantor'],
    #    'orbit_alt_km': 617, 'orbit_inc_deg': 97.7,
    #    'orbit_period_min': 97.0, 'swath_km': 13.1,
    #    'revisit_days': 1.0, 'ltan_hour': 10.5,
    #    'sensor_model': 'off_nadir', 'max_off_nadir_deg': 45.0,
    #},
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
        'norad_id': 43114, 'connector_ids': ['iceye'],
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
        'norad_id': 47474, 'connector_ids': ['capella'],
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
        'norad_id': 48900, 'connector_ids': ['umbra'],
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
        'norad_id': 39634,
        'connector_ids': ['element84_stac', 'planetary_computer_stac'],
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


def _track_bearing_for_direction(inc_deg: float, direction: str) -> float:
    """Approximate ground-track bearing for a sun-synchronous pass direction."""
    if direction == 'Descending':
        return (180.0 + (90.0 - inc_deg)) % 360.0
    return (0.0 - (90.0 - inc_deg)) % 360.0


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
        phase_origin = 0.618033988749895

        def _phase_from_time(pass_time: datetime, dir_shift: float) -> float:
            """Return a deterministic pseudo-phase from absolute pass time.

            Using absolute orbital progress avoids sparse day-stepping artefacts
            that can miss all accesses in short windows.
            """
            elapsed_days = max(0.0, (pass_time - start_dt).total_seconds() / 86400.0)
            orbit_progress = elapsed_days * orbits_per_day
            return (orbit_progress * phase_origin + dir_shift) % 1.0

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

                phase = _phase_from_time(
                    pass_dt,
                    0.0 if direction == 'Descending' else 0.5,
                )
                signed_offset_km = (phase - 0.5) * spacing_km
                offset_km = abs(signed_offset_km)

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

                track_bearing = _track_bearing_for_direction(
                    sat.get('orbit_inc_deg', 98.0), direction,
                )
                if signed_offset_km >= 0:
                    cross_bearing = (track_bearing + 90.0) % 360.0
                else:
                    cross_bearing = (track_bearing - 90.0) % 360.0
                sub_sat_lat, sub_sat_lon = _destination_point(
                    lat, lon, cross_bearing, abs(signed_offset_km),
                )

                orbit_track, ground_track, swath_ribbon = _analytical_tracks(
                    sub_sat_lat, sub_sat_lon, sat.get('orbit_inc_deg', 98.0), alt_km,
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
                    'sub_sat_lat': sub_sat_lat,
                    'sub_sat_lon': sub_sat_lon,
                    'orbit_alt_km': alt_km,
                    'swath_km': swath_km,
                    'sensor_model': model,
                    'orbit_track': orbit_track,
                    'ground_track': ground_track,
                    'swath_ribbon': swath_ribbon,
                })

            # Evaluate every day to avoid dropping valid accesses in short
            # planning windows (e.g. 1-2 weeks).
            current_day += timedelta(days=1)

        return overpasses


# ---------------------------------------------------------------------------
# Analytical orbit-track synthesis (no TLE)
# ---------------------------------------------------------------------------

def _analytical_tracks(
    center_lat: float, center_lon: float, inc_deg: float, alt_km: float,
    swath_km: float, period_min: float, direction: str,
    n_points: int = 120,
) -> Tuple[List[Tuple], List[Tuple], List[Tuple]]:
    """Create synthetic orbit/ground/swath tracks centered on sub-satellite point."""
    half_period_s = period_min * 30.0
    ground_speed_kms = (2.0 * math.pi * _R_EARTH_KM) / (period_min * 60.0)
    half_len_km = ground_speed_kms * half_period_s

    track_bearing = _track_bearing_for_direction(inc_deg, direction)

    orbit_pts: List[Tuple] = []
    ground_pts: List[Tuple] = []
    left_edge: List[Tuple] = []
    right_edge: List[Tuple] = []
    alt_m = alt_km * 1000.0
    half_swath = swath_km / 2.0
    step_km = (2.0 * half_len_km) / n_points

    for i in range(n_points + 1):
        d = -half_len_km + i * step_km
        pt = _destination_point(center_lat, center_lon, track_bearing, d)
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
            super().__init__('Altair Tasking — Archive Search', QgsTask.CanCancel)
        self.connector_manager = connector_manager
        self.search_params = search_params
        self.results: List[Dict] = []
        self.error_message: Optional[str] = None

    def run(self) -> bool:
        try:
            started_at = time.perf_counter()
            bbox = self.search_params.get('bbox')
            start_date = self.search_params.get('start_date')
            end_date = self.search_params.get('end_date')
            max_cloud_cover = self.search_params.get('max_cloud_cover')
            limit = int(self.search_params.get('limit', 50))
            connector_ids = list(self.search_params.get('connector_ids', []))
            connector_timeout = float(self.search_params.get('connector_timeout', 20.0) or 20.0)
            connector_timeout = max(5.0, min(60.0, connector_timeout))
            connector_timeouts = self.search_params.get('connector_timeouts', {}) or {}
            auth_payloads = self.search_params.get('auth_payloads', {}) or {}
            max_total_results = int(self.search_params.get('max_total_results', 120) or 120)
            max_total_results = max(20, min(2000, max_total_results))
            search_parallelism = int(self.search_params.get('search_parallelism', 3) or 3)
            search_parallelism = max(1, min(8, search_parallelism))

            if not connector_ids:
                return True

            connector_count = len(connector_ids)
            done_count = 0
            stop_early = False
            seen_ids = set()

            def _timeout_for(cid: str) -> float:
                t = connector_timeout
                try:
                    if cid in connector_timeouts:
                        t = float(connector_timeouts.get(cid) or connector_timeout)
                except (TypeError, ValueError):
                    t = connector_timeout
                return max(5.0, min(60.0, t))

            def _needs_authentication(ci: Dict[str, Any]) -> bool:
                caps = ci.get('capabilities', []) if isinstance(ci, dict) else []
                for cap in caps:
                    if str(getattr(cap, 'value', cap)).lower() == 'authentication':
                        return True
                return False

            def _ensure_connector_ready(cid: str) -> bool:
                ci = getattr(self.connector_manager, '_connectors', {}).get(cid, {})
                if not ci:
                    return False
                if ci.get('authenticated'):
                    return True
                if not _needs_authentication(ci):
                    creds = auth_payloads.get(cid)
                    if isinstance(creds, dict) and creds:
                        try:
                            self.connector_manager.authenticate_connector(cid, creds)
                        except Exception as exc:
                            logger.debug(
                                'SmartSearchTask runtime config skipped for %s: %s',
                                cid,
                                exc,
                            )
                    ci['authenticated'] = True
                    return True

                creds = auth_payloads.get(cid)
                if not creds and cid != 'nasa_earthdata':
                    return False
                try:
                    return bool(self.connector_manager.authenticate_connector(cid, creds))
                except Exception as exc:
                    logger.warning(f'SmartSearchTask auth failed for {cid}: {exc}')
                    return False

            def _search_connector(cid: str):
                if self.isCanceled():
                    return cid, [], 0.0, 'canceled'
                if not _ensure_connector_ready(cid):
                    return cid, [], 0.0, 'auth-not-ready'

                timeout_for_connector = _timeout_for(cid)
                t0 = time.perf_counter()
                items, _token = self.connector_manager.search(
                    bbox=bbox,
                    start_date=start_date,
                    end_date=end_date,
                    max_cloud_cover=max_cloud_cover,
                    limit=limit,
                    connector_id=cid,
                    timeout=timeout_for_connector,
                )
                return cid, (items or []), (time.perf_counter() - t0), None

            max_workers = min(search_parallelism, connector_count)
            executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix='SmartSearch')
            future_map = {
                executor.submit(_search_connector, cid): cid
                for cid in connector_ids
            }

            try:
                for fut in as_completed(future_map):
                    if self.isCanceled():
                        stop_early = True
                        break

                    cid = future_map[fut]
                    done_count += 1

                    try:
                        cid, items, elapsed, failure = fut.result()
                    except Exception as exc:
                        logger.warning(f'SmartSearchTask connector {cid} failed: {exc}')
                        if hasattr(self, 'setProgress'):
                            self.setProgress((done_count / connector_count) * 100.0)
                        continue

                    display = cid
                    ci = getattr(self.connector_manager, '_connectors', {}).get(cid, {})
                    if ci:
                        display = ci.get('display_name', cid)

                    if failure:
                        logger.info(
                            'SmartSearchTask connector skipped id=%s reason=%s',
                            cid,
                            failure,
                        )
                    else:
                        logger.info(
                            'SmartSearchTask connector done id=%s items=%d elapsed=%.2fs',
                            cid,
                            len(items),
                            elapsed,
                        )

                    for item in items:
                        scene_id = str(item.get('id', ''))
                        dedup_key = f'{cid}:{scene_id}'
                        if scene_id and dedup_key in seen_ids:
                            continue
                        if scene_id:
                            seen_ids.add(dedup_key)

                        item['_provider'] = display
                        item['_source'] = cid
                        self.results.append(item)
                        if len(self.results) >= max_total_results:
                            stop_early = True
                            logger.info(
                                'SmartSearchTask max_total_results reached (%d)',
                                max_total_results,
                            )
                            break

                    if hasattr(self, 'setProgress'):
                        self.setProgress((done_count / connector_count) * 100.0)

                    if stop_early:
                        break
            finally:
                executor.shutdown(wait=False, cancel_futures=True)

            if self.isCanceled():
                return False

            elapsed_total = time.perf_counter() - started_at
            logger.info(
                'SmartSearchTask: %d scene(s) found in %.2fs (%d connectors, parallel=%d)',
                len(self.results),
                elapsed_total,
                connector_count,
                max_workers,
            )
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
                 start_dt: datetime, end_dt: datetime,
                 max_results: int = 500, max_workers: int = 4):
        if QGIS_AVAILABLE:
            super().__init__('Altair Tasking — Overpass Prediction', QgsTask.CanCancel)
        self.satellites = satellites
        self.lat = lat
        self.lon = lon
        self.start_dt = start_dt
        self.end_dt = end_dt
        self.max_results = max(50, min(5000, int(max_results or 500)))
        self.max_workers = max(1, min(8, int(max_workers or 4)))
        self.results: List[Dict] = []
        self.error_message: Optional[str] = None
        self.truncated = False

    def run(self) -> bool:
        try:
            started_at = time.perf_counter()
            satellites = list(self.satellites or [])
            if not satellites:
                return True

            sat_count = len(satellites)
            done_count = 0

            def _predict_one(sat: Dict[str, Any]):
                t0 = time.perf_counter()
                engine = _OverpassEngine()
                passes = engine.predict(sat, self.lat, self.lon, self.start_dt, self.end_dt)
                return sat, (passes or []), (time.perf_counter() - t0)

            executor = ThreadPoolExecutor(
                max_workers=min(self.max_workers, sat_count),
                thread_name_prefix='OverpassPredict',
            )
            future_map = {
                executor.submit(_predict_one, sat): sat
                for sat in satellites
            }

            try:
                for fut in as_completed(future_map):
                    if self.isCanceled():
                        return False
                    done_count += 1
                    sat_name = str(future_map[fut].get('constellation', '?'))
                    try:
                        sat, passes, elapsed = fut.result()
                        self.results.extend(passes)
                        logger.info(
                            'OverpassTask satellite done name=%s passes=%d elapsed=%.2fs',
                            sat.get('constellation', sat_name),
                            len(passes),
                            elapsed,
                        )
                    except Exception as exc:
                        logger.warning(f'OverpassTask satellite failed ({sat_name}): {exc}')

                    if len(self.results) >= self.max_results:
                        self.results = self.results[:self.max_results]
                        self.truncated = True
                        logger.info('OverpassTask max_results reached (%d)', self.max_results)
                        break

                    if hasattr(self, 'setProgress'):
                        self.setProgress((done_count / sat_count) * 100.0)
            finally:
                executor.shutdown(wait=False, cancel_futures=True)

            if self.isCanceled():
                return False

            # Sort by time
            self.results.sort(key=lambda p: p.get('datetime_utc', ''))
            logger.info(
                'OverpassTask: %d pass(es) predicted in %.2fs (satellites=%d, parallel=%d, truncated=%s)',
                len(self.results),
                time.perf_counter() - started_at,
                sat_count,
                min(self.max_workers, sat_count),
                self.truncated,
            )
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
    """Altair Tasking dock — flip switches, pick a satellite, search or predict."""

    order_requested = pyqtSignal(dict)   # payload for Tasking dock prefill

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
        super().__init__('Tasking', parent)
        logger.info('Initializing Altair Tasking dock widget')

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
        self._updating_archive_table = False
        self._updating_selection = False
        self._footprints_layer = None
        self._feature_id_to_result_index: Dict[int, int] = {}
        self._result_index_to_feature_id: Dict[int, int] = {}
        self._selection_tool = None
        self._previous_map_tool = None
        self._quicklook_source_pixmap: Optional[QPixmap] = None
        self._quicklook_cache: Dict[str, Optional[bytes]] = {}
        self._quicklook_cache_order: List[str] = []
        self._quicklook_cache_max_entries = 24
        self._3d_orbit_layer = None
        self._3d_ground_layer = None
        self._3d_swath_layer = None
        self._3d_sat_layer = None
        self._3d_nadir_layer = None

        self._init_connector_manager()
        self._setup_ui()
        self._apply_filters()

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
                  ConnectorCapability.COMMERCIAL,
                  ConnectorCapability.PREVIEW]),
                ('oneatlas',        '..connectors.oneatlas',        'OneAtlasConnector',        'OneAtlas',
                 [ConnectorCapability.BBOX_SEARCH, ConnectorCapability.DATE_RANGE,
                  ConnectorCapability.CLOUD_COVER, ConnectorCapability.AUTHENTICATION,
                  ConnectorCapability.COMMERCIAL,
                  ConnectorCapability.PREVIEW]),
                                ('jilin_gaofen_stac', '..connectors.jilin_gaofen_stac', 'JilinGaofenStacConnector', 'Jilin-1 Gaofen',
                                 [ConnectorCapability.BBOX_SEARCH, ConnectorCapability.DATE_RANGE,
                                    ConnectorCapability.CLOUD_COVER, ConnectorCapability.COLLECTIONS,
                                    ConnectorCapability.TEXT_SEARCH, ConnectorCapability.COG_SUPPORT,
                                    ConnectorCapability.PREVIEW,
                                    ConnectorCapability.COMMERCIAL]),
                                          ('jaxa_earth_stac', '..connectors.jaxa_earth_stac', 'JaxaEarthStacConnector', 'JAXA Earth',
                                            [ConnectorCapability.BBOX_SEARCH, ConnectorCapability.DATE_RANGE,
                                                ConnectorCapability.CLOUD_COVER, ConnectorCapability.COLLECTIONS,
                                                ConnectorCapability.TEXT_SEARCH, ConnectorCapability.COG_SUPPORT,
                                                ConnectorCapability.PREVIEW]),
                                ('swisstopo_stac', '..connectors.swisstopo_stac', 'SwisstopoStacConnector', 'swisstopo S2-SR',
                                 [ConnectorCapability.BBOX_SEARCH, ConnectorCapability.DATE_RANGE,
                                  ConnectorCapability.CLOUD_COVER, ConnectorCapability.COLLECTIONS,
                                  ConnectorCapability.COG_SUPPORT, ConnectorCapability.PREVIEW]),
                     ('iceye',           '..connectors.iceye',           'IceyeConnector',           'ICEYE',
                                 [ConnectorCapability.BBOX_SEARCH, ConnectorCapability.DATE_RANGE,
                                    ConnectorCapability.AUTHENTICATION, ConnectorCapability.COMMERCIAL,
                                    ConnectorCapability.COG_SUPPORT, ConnectorCapability.PREVIEW]),
                     ('umbra',           '..connectors.umbra',           'UmbraConnector',           'Umbra',
                                 [ConnectorCapability.BBOX_SEARCH, ConnectorCapability.DATE_RANGE,
                                    ConnectorCapability.AUTHENTICATION, ConnectorCapability.COMMERCIAL,
                                    ConnectorCapability.COG_SUPPORT, ConnectorCapability.PREVIEW]),
                     ('capella',         '..connectors.capella',         'CapellaConnector',         'Capella',
                                 [ConnectorCapability.BBOX_SEARCH, ConnectorCapability.DATE_RANGE,
                                                ConnectorCapability.AUTHENTICATION,
                                                ConnectorCapability.COMMERCIAL,
                                                ConnectorCapability.COG_SUPPORT,
                                                ConnectorCapability.PREVIEW]),
                                ('vantor',          '..connectors.vantor',          'VantorConnector',          'Vantor Hub Discovery',
                 [ConnectorCapability.BBOX_SEARCH, ConnectorCapability.DATE_RANGE,
                  ConnectorCapability.CLOUD_COVER,
                  ConnectorCapability.PREVIEW]),
                                ('cdse_sentinel', '..connectors.cdse_sentinel', 'CdseSentinelConnector',  'CDSE Sentinel',
                 [ConnectorCapability.BBOX_SEARCH, ConnectorCapability.DATE_RANGE,
                  ConnectorCapability.CLOUD_COVER, ConnectorCapability.AUTHENTICATION,
                  ConnectorCapability.COG_SUPPORT, ConnectorCapability.PREVIEW]),
                ('nasa_earthdata',  '..connectors.nasa_earthdata',  'NasaEarthdataConnector',   'NASA EarthData',
                 [ConnectorCapability.BBOX_SEARCH, ConnectorCapability.DATE_RANGE,
                  ConnectorCapability.AUTHENTICATION, ConnectorCapability.COG_SUPPORT,
                  ConnectorCapability.PREVIEW]),
                                ('element84_stac', '..connectors.element84_stac', 'Element84StacConnector',
                                 'Earth Search (Element84)',
                                 [ConnectorCapability.BBOX_SEARCH, ConnectorCapability.DATE_RANGE,
                                    ConnectorCapability.CLOUD_COVER, ConnectorCapability.COLLECTIONS,
                                    ConnectorCapability.TEXT_SEARCH, ConnectorCapability.COG_SUPPORT,
                                    ConnectorCapability.PREVIEW]),
                                ('planetary_computer_stac', '..connectors.planetary_computer_stac',
                                 'PlanetaryComputerStacConnector', 'Microsoft Planetary Computer',
                                 [ConnectorCapability.BBOX_SEARCH, ConnectorCapability.DATE_RANGE,
                                    ConnectorCapability.CLOUD_COVER, ConnectorCapability.COLLECTIONS,
                                    ConnectorCapability.TEXT_SEARCH, ConnectorCapability.COG_SUPPORT,
                                    ConnectorCapability.PREVIEW]),
            ]

            import importlib
            for cid, modpath, clsname, display, caps in _REGISTRATIONS:
                try:
                    mod = importlib.import_module(modpath, package=__package__)
                    cls = getattr(mod, clsname)
                    instance = cls()
                    if bool(getattr(instance, 'IS_STUB', False)):
                        logger.info(f'SmartTasking: skipping stub connector {cid}')
                        continue
                    runtime_caps = self._augment_connector_capabilities(instance, caps)
                    self._connector_manager.register_connector(
                        cid,
                        instance,
                        display,
                        capabilities=runtime_caps,
                    )
                    logger.debug(
                        'SmartTasking: connector %s capabilities=%s',
                        cid,
                        [c.value for c in runtime_caps],
                    )
                    logger.debug(f'SmartTasking: registered connector {cid}')
                except Exception as exc:
                    logger.debug(f'SmartTasking: connector {cid} unavailable: {exc}')

            logger.info('SmartTasking: connector manager ready')
        except Exception as exc:
            logger.error(f'SmartTasking: connector manager init failed: {exc}', exc_info=True)
            self._connector_manager = None

    def _augment_connector_capabilities(self, connector: Any, base_caps: List[Any]) -> List[Any]:
        """Derive media capabilities from connector implementation details."""
        caps = list(base_caps or [])
        try:
            from ..connectors.base import ConnectorBase
            from ..connectors.connector_manager import ConnectorCapability

            cls = connector.__class__
            resolve_preview_impl = inspect.getattr_static(cls, 'resolve_preview_url', None)
            resolve_cog_impl = inspect.getattr_static(cls, 'resolve_cog_url', None)
            base_preview_impl = inspect.getattr_static(ConnectorBase, 'resolve_preview_url', None)
            base_cog_impl = inspect.getattr_static(ConnectorBase, 'resolve_cog_url', None)

            preview_override = resolve_preview_impl is not None and resolve_preview_impl is not base_preview_impl
            cog_override = resolve_cog_impl is not None and resolve_cog_impl is not base_cog_impl

            has_preview_adapter = callable(getattr(connector, 'get_preview_url', None))
            has_cog_adapter = callable(getattr(connector, 'get_cog_url', None))
            has_download_adapter = callable(getattr(connector, 'get_download_url', None))

            supports_preview = bool(getattr(connector, 'SUPPORTS_PREVIEW', False)) or preview_override or has_preview_adapter
            supports_cog = (
                bool(getattr(connector, 'SUPPORTS_COG', False))
                or bool(getattr(connector, 'SUPPORTS_COG_SUPPORT', False))
                or cog_override
                or has_cog_adapter
                or has_download_adapter
            )

            if supports_preview and ConnectorCapability.PREVIEW not in caps:
                caps.append(ConnectorCapability.PREVIEW)
            if supports_cog and ConnectorCapability.COG_SUPPORT not in caps:
                caps.append(ConnectorCapability.COG_SUPPORT)
        except Exception as exc:
            logger.debug(f'SmartTasking: capability augmentation skipped: {exc}')
        return caps

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
        header = QLabel('KADAS Altair - Search & Predict')
        hf = QFont()
        hf.setPointSize(12)
        hf.setBold(True)
        header.setFont(hf)
        header.setAlignment(Qt.AlignCenter)
        header.setStyleSheet('color: #1f1f1f;')
        layout.addWidget(header)

        subtitle = QLabel(
            'Explore available Satellite Images and Predict Overpasses for your Area of Interest (AOI). '
        )
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet(f'color: {self._LABEL_COLOR}; font-size: 10px;')
        layout.addWidget(subtitle)

        # --- Quick filters ---
        filter_group = QGroupBox('What Do You Need?')
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

        # Cloud cover (archive search filter)
        cloud_row = QHBoxLayout()
        self.cloud_slider = QSlider(Qt.Horizontal)
        self.cloud_slider.setRange(0, 100)
        self.cloud_slider.setValue(30)
        self.cloud_slider.setTickPosition(QSlider.TicksBelow)
        self.cloud_slider.setTickInterval(10)
        cloud_row.addWidget(self.cloud_slider, 1)

        self.cloud_spin = QSpinBox()
        self.cloud_spin.setRange(0, 100)
        self.cloud_spin.setValue(30)
        self.cloud_spin.setSuffix(' %')
        self.cloud_spin.setSingleStep(1)
        self.cloud_spin.setToolTip('Maximum cloud cover for archive search results')
        cloud_row.addWidget(self.cloud_spin)

        self.cloud_slider.valueChanged.connect(self._on_cloud_slider_changed)
        self.cloud_spin.valueChanged.connect(self._on_cloud_spin_changed)
        filter_form.addRow('Cloud Cover ≤', cloud_row)

        layout.addWidget(filter_group)

        # --- Operator / constellation selectors ---
        select_group = QGroupBox('Pick Your Constellation')
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

        self.extent_widget = AoiWidget(parent=aoi_group)
        if self.iface:
            canvas = self.iface.mapCanvas()
            canvas_extent = canvas.extent()
            canvas_crs = canvas.mapSettings().destinationCrs()
            self.extent_widget.setMapCanvas(canvas)
            self.extent_widget.setCurrentExtent(canvas_extent, canvas_crs)
            self.extent_widget.setOriginalExtent(canvas_extent, canvas_crs)
            self.extent_widget.setOutputCrs(canvas_crs)
        aoi_form.addRow('AOI:', self.extent_widget)

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

        archive_actions = QHBoxLayout()

        self.select_from_map_btn = QPushButton('Select from Map')
        self.select_from_map_btn.setCheckable(True)
        self.select_from_map_btn.setEnabled(False)
        self.select_from_map_btn.setToolTip('Select archive footprints directly from the map')
        self.select_from_map_btn.toggled.connect(self._on_selection_mode_toggled)
        archive_actions.addWidget(self.select_from_map_btn)

        self.zoom_btn = QPushButton('Zoom to Selection')
        self.zoom_btn.setEnabled(False)
        self.zoom_btn.clicked.connect(self._zoom_to_selected)
        archive_actions.addWidget(self.zoom_btn)

        self.quicklook_btn = QPushButton('Open Quicklook')
        self.quicklook_btn.setEnabled(False)
        self.quicklook_btn.clicked.connect(self._open_quicklook)
        archive_actions.addWidget(self.quicklook_btn)

        self.load_cog_btn = QPushButton('Load COG')
        self.load_cog_btn.setEnabled(False)
        self.load_cog_btn.clicked.connect(self._load_cog)
        archive_actions.addWidget(self.load_cog_btn)

        self.download_asset_btn = QPushButton('Download asset')
        self.download_asset_btn.setEnabled(False)
        self.download_asset_btn.setToolTip(
            'Download the selected scene main asset (COG/download URL) to disk'
        )
        self.download_asset_btn.clicked.connect(self._download_asset)
        archive_actions.addWidget(self.download_asset_btn)

        archive_layout.addLayout(archive_actions)

        quicklook_group = QGroupBox('Quicklook Preview')
        quicklook_layout = QVBoxLayout(quicklook_group)
        quicklook_layout.setContentsMargins(8, 8, 8, 8)

        self.quicklook_preview = QLabel('No scene selected')
        self.quicklook_preview.setAlignment(Qt.AlignCenter)
        self.quicklook_preview.setMinimumHeight(180)
        self.quicklook_preview.setWordWrap(True)
        self.quicklook_preview.setStyleSheet(
            'border: 1px solid #cfcfcf; background: #fafafa; color: #555; padding: 8px;'
        )
        quicklook_layout.addWidget(self.quicklook_preview)
        archive_layout.addWidget(quicklook_group)

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

        # --- Send to Tasking button ---
        self.send_to_tasking_btn = QPushButton('📨 Send Order')
        self.send_to_tasking_btn.setToolTip(
            'Pre-fill the Tasking Order form with the selected archive scene '
            'or predicted overpass.'
        )
        self.send_to_tasking_btn.clicked.connect(self._send_to_tasking)
        layout.addWidget(self.send_to_tasking_btn)

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

    def _get_available_connector_ids(self) -> set[str]:
        """Return the connector IDs that are currently registered in the manager."""
        if not self._connector_manager:
            return set()
        try:
            available = self._connector_manager.get_available_connectors()
            return {str(connector.get('id', '')).strip() for connector in available if str(connector.get('id', '')).strip()}
        except Exception as exc:
            logger.debug(f'Altair Tasking: unable to read available connectors: {exc}')
            return set()

    def _apply_filters(self):
        """Re-filter the catalogue based on current switch positions and available connectors."""
        if not hasattr(self, 'sensor_combo'):
            return

        sensor = self.sensor_combo.currentText()
        res_text = self.resolution_combo.currentText()
        access_text = self.access_combo.currentText()
        daylight_text = self.daylight_combo.currentText()
        available_connector_ids = self._get_available_connector_ids()

        filtered: List[Dict] = []
        for sat in SATELLITE_CATALOGUE:
            connector_ids = sat.get('connector_ids', []) or []
            if not connector_ids:
                continue
            if available_connector_ids and not set(connector_ids) & available_connector_ids:
                continue
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
            self.go_btn.setText('🔍 Search + Predict')

    # ------------------------------------------------------------------
    # AOI helpers
    # ------------------------------------------------------------------

    def _get_aoi_bbox_wgs84(self) -> Optional[Tuple[float, float, float, float]]:
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
            logger.warning(f'Altair Tasking: AOI read failed: {exc}')
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

    def _is_task_active(self, task) -> bool:
        """Return True when a QgsTask is still queued/running."""
        if not task or not QGIS_AVAILABLE:
            return False
        try:
            status = task.status()
            active_states = []
            for name in ('Queued', 'OnHold', 'Running'):
                if hasattr(QgsTask, name):
                    active_states.append(getattr(QgsTask, name))
            return status in active_states
        except Exception:
            return False

    def _has_active_tasks(self) -> bool:
        """Check whether archive search and/or overpass prediction is active."""
        return self._is_task_active(self._active_search_task) or self._is_task_active(self._active_overpass_task)

    def _update_go_button_state(self):
        """Enable the action button only when no background task is active."""
        self.go_btn.setEnabled(not self._has_active_tasks())

    def _on_go_clicked(self):
        """Central dispatch — detect mode and launch appropriate task(s)."""
        if self._has_active_tasks():
            self.status_label.setText('Operation already running — wait for completion before starting a new search.')
            self.status_label.setStyleSheet('color: #ffcc00; font-size: 10px;')
            return

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

        # Smart archive mode should rely on the new open STAC backends.
        # Keep CDSE for service/overpass workflows, not archive catalogue search.
        connector_ids.discard('cdse_sentinel')
        connector_ids.update({'element84_stac', 'planetary_computer_stac'})

        if not connector_ids:
            self.archive_count_label.setText('No archive connectors for selected satellites.')
            return

        if not self._connector_manager:
            self.archive_count_label.setText('Connector manager unavailable.')
            return

        ready_ids, auth_payloads = self._build_archive_auth_payloads(sorted(connector_ids))

        if not ready_ids:
            self.archive_count_label.setText(
                'No connectors authenticated. Configure credentials in Settings.'
            )
            return

        base_timeout = float(self.settings.value('AltairEOData/smart_archive_connector_timeout', 20.0))
        base_timeout = max(5.0, min(60.0, base_timeout))
        jaxa_timeout = float(self.settings.value('AltairEOData/jaxa_search_timeout', min(base_timeout, 15.0)))
        jaxa_timeout = max(5.0, min(60.0, jaxa_timeout))
        vantor_timeout = float(self.settings.value('AltairEOData/vantor_discovery_timeout', min(base_timeout, 12.0)))
        vantor_timeout = max(5.0, min(60.0, vantor_timeout))
        limit_per_connector = int(self.settings.value('AltairEOData/smart_archive_limit_per_connector', 20))
        limit_per_connector = max(5, min(100, limit_per_connector))
        max_total_results = int(self.settings.value('AltairEOData/smart_archive_max_results', 120))
        max_total_results = max(20, min(2000, max_total_results))
        search_parallelism = int(self.settings.value('AltairEOData/smart_archive_parallelism', 3))
        search_parallelism = max(1, min(8, search_parallelism))

        params = {
            'bbox': list(bbox),
            'start_date': str(start_d),
            'end_date': str(end_d),
            'max_cloud_cover': float(self.cloud_spin.value()) / 100.0,
            'limit': limit_per_connector,
            'connector_ids': ready_ids,
            'connector_timeout': base_timeout,
            'auth_payloads': auth_payloads,
            'max_total_results': max_total_results,
            'search_parallelism': search_parallelism,
            'connector_timeouts': {
                'jaxa_earth_stac': jaxa_timeout,
                'vantor': vantor_timeout,
            },
        }

        self.status_label.setText('Searching archives …')
        self.status_label.setStyleSheet('color: #88ccff; font-size: 10px;')

        if QGIS_AVAILABLE and hasattr(QgsApplication, 'taskManager'):
            task = _SmartSearchTask(self._connector_manager, params)
            self._active_search_task = task
            task.taskCompleted.connect(lambda: self._on_search_done(task))
            task.taskTerminated.connect(lambda: self._on_search_error(task))
            self._update_go_button_state()
            QgsApplication.taskManager().addTask(task)
        else:
            # Synchronous fallback
            task = _SmartSearchTask(self._connector_manager, params)
            self._active_search_task = task
            self._update_go_button_state()
            task.run()
            self._on_search_done(task)

    def _on_search_done(self, task: _SmartSearchTask):
        if task is not self._active_search_task:
            logger.debug('Ignoring stale archive-search completion callback')
            return

        self._active_search_task = None
        self._search_results = task.results or []
        self._populate_archive_table()
        self.results_tabs.setCurrentIndex(0)
        n = len(self._search_results)
        self.status_label.setText(f'Archive search complete — {n} scene(s)')
        self.status_label.setStyleSheet('color: #00ffbf; font-size: 10px;')
        self._update_go_button_state()

    def _on_search_error(self, task: _SmartSearchTask):
        if task is not self._active_search_task:
            logger.debug('Ignoring stale archive-search error callback')
            return

        self._active_search_task = None
        msg = task.error_message or 'Unknown error'
        self.status_label.setText(f'Archive search failed: {msg}')
        self.status_label.setStyleSheet('color: #ff6b6b; font-size: 10px;')
        self._update_go_button_state()

    def _populate_archive_table(self):
        self._updating_archive_table = True
        self.archive_table.blockSignals(True)
        self.archive_table.setSortingEnabled(False)
        count = len(self._search_results)
        self.archive_table.setRowCount(count)

        try:
            for row_idx, item in enumerate(self._search_results):
                props = item.get('properties', item)
                provider = str(item.get('_provider', props.get('provider', '')))
                date_str = str(props.get('datetime', props.get('date', '')))[:10]
                satellite = str(props.get('platform', props.get('satellite_id',
                                props.get('constellation', ''))))
                cloud_raw = props.get('eo:cloud_cover', props.get('cloud_cover', ''))
                cloud_str = f'{float(cloud_raw):.1f}' if cloud_raw not in ('', None) else 'N/A'
                gsd_raw = props.get('gsd', props.get('eo:gsd', ''))
                gsd_str = f'{float(gsd_raw):.1f}' if gsd_raw not in ('', None) else 'N/A'
                scene_id = str(item.get('id', props.get('id', '')))

                pi = QTableWidgetItem(provider)
                pi.setData(Qt.UserRole, row_idx)
                self.archive_table.setItem(row_idx, self._COL_PROVIDER, pi)
                self.archive_table.setItem(row_idx, self._COL_DATE, QTableWidgetItem(date_str))
                self.archive_table.setItem(row_idx, self._COL_SATELLITE, QTableWidgetItem(satellite))
                ci = _NumItem(cloud_str); ci.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.archive_table.setItem(row_idx, self._COL_CLOUD, ci)
                gi = _NumItem(gsd_str); gi.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.archive_table.setItem(row_idx, self._COL_GSD, gi)
                self.archive_table.setItem(row_idx, self._COL_ID, QTableWidgetItem(scene_id))
        finally:
            self.archive_table.setSortingEnabled(True)
            self.archive_table.blockSignals(False)
            self._updating_archive_table = False

        self.archive_count_label.setText(f'{count} result(s) found')

        if count > 0:
            self._refresh_footprints_layer()
        else:
            self._clear_footprints_layer()

        self._update_archive_action_state()

    def _on_archive_row_selected(self):
        """Highlight selected footprints on map."""
        if self._updating_archive_table:
            return

        self._update_archive_action_state()

        if not QGIS_AVAILABLE or self._updating_selection or not self._is_footprints_layer_valid():
            return

        selected_indices = self._get_selected_archive_result_indices()
        try:
            self._updating_selection = True
            selected_feature_ids = []
            for result_index in selected_indices:
                feature_id = self._result_index_to_feature_id.get(result_index)
                if feature_id is not None:
                    selected_feature_ids.append(feature_id)
            self._footprints_layer.selectByIds(selected_feature_ids)
        except Exception as exc:
            logger.warning(f'Failed syncing table selection to map: {exc}')
        finally:
            self._updating_selection = False

    def _get_archive_result_index(self, view_row: int) -> Optional[int]:
        item = self.archive_table.item(view_row, self._COL_PROVIDER)
        if item is None:
            return None
        result_index = item.data(Qt.UserRole)
        if result_index is None:
            return None
        try:
            return int(result_index)
        except (TypeError, ValueError):
            return None

    def _get_selected_archive_result_indices(self) -> List[int]:
        model = self.archive_table.selectionModel()
        if model is None:
            return []

        result_indices: List[int] = []
        for model_index in model.selectedRows():
            result_index = self._get_archive_result_index(model_index.row())
            if result_index is not None:
                result_indices.append(result_index)
        return result_indices

    def _get_selected_archive_items(self) -> List[Dict[str, Any]]:
        items: List[Dict[str, Any]] = []
        for result_index in self._get_selected_archive_result_indices():
            if 0 <= result_index < len(self._search_results):
                items.append(self._search_results[result_index])
        return items

    def _is_footprints_layer_valid(self) -> bool:
        layer = self._footprints_layer
        return bool(QGIS_AVAILABLE and layer is not None and layer.isValid())

    def _archive_item_has_spatial_extent(self, item: Dict[str, Any]) -> bool:
        bbox = item.get('bbox')
        if bbox and len(bbox) >= 4:
            return True
        return self._item_to_geometry(item) is not None

    def _archive_source_has_capability(self, item: Dict[str, Any], capability_name: str) -> bool:
        source = item.get('_source')
        if not source or not self._connector_manager:
            return False
        try:
            from ..connectors.connector_manager import ConnectorCapability

            capability = getattr(ConnectorCapability, capability_name, None)
            if capability is None:
                return False
            return bool(self._connector_manager.has_capability(capability, connector_id=source))
        except Exception:
            return False

    def _get_archive_connector_instance(self, item: Dict[str, Any]):
        source = item.get('_source')
        if not source or not self._connector_manager:
            return None
        try:
            connector_info = getattr(self._connector_manager, '_connectors', {}).get(source, {})
            return connector_info.get('instance') if connector_info else None
        except Exception:
            return None

    def _archive_item_can_quicklook(self, item: Dict[str, Any]) -> bool:
        return bool(
            self._extract_quicklook_url(item)
            or self._archive_source_has_capability(item, 'PREVIEW')
        )

    def _archive_item_can_load_cog(self, item: Dict[str, Any]) -> bool:
        return bool(
            self._pick_cog_href(item.get('assets', {}), item)
            or self._archive_source_has_capability(item, 'COG_SUPPORT')
        )

    def _archive_item_can_order(self, item: Dict[str, Any]) -> bool:
        return bool(item.get('id'))

    def _archive_item_can_download_asset(self, item: Dict[str, Any]) -> bool:
        assets = item.get('assets') if isinstance(item, dict) else {}
        assets = assets if isinstance(assets, dict) else {}
        href, _ = self._pick_cog_href_with_reason(assets, item)
        return bool(href)

    def _update_archive_action_state(self):
        selected_items = self._get_selected_archive_items()
        single_item = selected_items[0] if len(selected_items) == 1 else None

        self.select_from_map_btn.setEnabled(self._is_footprints_layer_valid())
        if not self.select_from_map_btn.isEnabled() and self.select_from_map_btn.isChecked():
            self.select_from_map_btn.setChecked(False)

        self.zoom_btn.setEnabled(any(self._archive_item_has_spatial_extent(item) for item in selected_items))
        self.quicklook_btn.setEnabled(bool(single_item and self._archive_item_can_quicklook(single_item)))
        self.load_cog_btn.setEnabled(any(self._archive_item_can_load_cog(item) for item in selected_items))
        self.download_asset_btn.setEnabled(
            bool(single_item and self._archive_item_can_download_asset(single_item))
        )
        self.send_to_tasking_btn.setEnabled(
            bool(single_item and self._archive_item_can_order(single_item))
        )

        if single_item is not None:
            self._update_quicklook_preview(single_item)
        else:
            self._update_quicklook_preview(None)

    def _on_layer_selection_changed(self):
        if self._updating_selection or not self._is_footprints_layer_valid():
            return

        self._updating_selection = True
        try:
            selected_ids = set(self._footprints_layer.selectedFeatureIds())
            selected_result_indices = {
                self._feature_id_to_result_index[fid]
                for fid in selected_ids
                if fid in self._feature_id_to_result_index
            }

            selection_model = self.archive_table.selectionModel()
            if selection_model is None:
                return

            selection_model.clearSelection()

            first_row = None
            for row_idx in range(self.archive_table.rowCount()):
                table_result_index = self._get_archive_result_index(row_idx)
                if table_result_index in selected_result_indices:
                    selection_model.select(
                        self.archive_table.model().index(row_idx, 0),
                        QItemSelectionModel.Select | QItemSelectionModel.Rows,
                    )
                    if first_row is None:
                        first_row = row_idx

            if first_row is not None:
                self.archive_table.scrollTo(
                    self.archive_table.model().index(first_row, 0),
                    QAbstractItemView.PositionAtCenter,
                )
        except Exception as exc:
            logger.warning(f'Failed syncing map selection to table: {exc}')
        finally:
            self._updating_selection = False

    def _on_footprints_layer_deleted(self):
        self._footprints_layer = None
        self._feature_id_to_result_index = {}
        self._result_index_to_feature_id = {}
        self._update_archive_action_state()

    def _on_selection_mode_toggled(self, checked: bool):
        if not self._is_footprints_layer_valid():
            self.select_from_map_btn.setChecked(False)
            QMessageBox.warning(self, 'Warning', 'No footprints layer loaded. Run a search first.')
            return

        if checked:
            self._activate_selection_mode()
        else:
            self._deactivate_selection_mode()

    def _activate_selection_mode(self):
        try:
            canvas = self.iface.mapCanvas()
            self._selection_tool = FootprintSelectionTool(canvas, self._footprints_layer)
            self._previous_map_tool = canvas.mapTool()
            canvas.setMapTool(self._selection_tool)
            self.select_from_map_btn.setText('✓ Map Selection Active')
            self.select_from_map_btn.setStyleSheet('QPushButton { background-color: #4CAF50; color: white; }')
        except Exception as exc:
            logger.warning(f'Could not activate map selection mode: {exc}')
            self.select_from_map_btn.setChecked(False)

    def _deactivate_selection_mode(self):
        try:
            canvas = self.iface.mapCanvas()
            if self._previous_map_tool is not None:
                try:
                    canvas.setMapTool(self._previous_map_tool)
                except Exception:
                    canvas.unsetMapTool(self._selection_tool)
            elif self._selection_tool is not None:
                canvas.unsetMapTool(self._selection_tool)
        except Exception as exc:
            logger.warning(f'Could not deactivate map selection mode: {exc}')
        finally:
            self._selection_tool = None
            self._previous_map_tool = None
            self.select_from_map_btn.setText('Select from Map')
            self.select_from_map_btn.setStyleSheet('')

    def _zoom_to_selected(self):
        rows = self._get_selected_archive_result_indices()
        if not rows or not QGIS_AVAILABLE:
            return
        try:
            combined = None
            for result_index in rows:
                item = self._search_results[result_index] if result_index < len(self._search_results) else None
                if item is None:
                    continue
                bbox = item.get('bbox')
                if bbox and len(bbox) >= 4:
                    rect = QgsRectangle(bbox[0], bbox[1], bbox[2], bbox[3])
                    if combined is None:
                        combined = rect
                    else:
                        combined.combineExtentWith(rect)
                else:
                    geom = self._item_to_geometry(item)
                    if geom is not None and not geom.isEmpty():
                        rect = geom.boundingBox()
                        if combined is None:
                            combined = rect
                        else:
                            combined.combineExtentWith(rect)
            if combined:
                canvas = self.iface.mapCanvas()
                src_crs = QgsCoordinateReferenceSystem('EPSG:4326')
                dst_crs = canvas.mapSettings().destinationCrs()
                if dst_crs.authid() != 'EPSG:4326':
                    tr = QgsCoordinateTransform(src_crs, dst_crs, QgsProject.instance())
                    combined = tr.transformBoundingBox(combined)
                canvas.setExtent(combined)
                canvas.refresh()
        except Exception as exc:
            logger.warning(f'Zoom to selected failed: {exc}')

    def _open_quicklook(self):
        selected_items = self._get_selected_archive_items()
        if len(selected_items) != 1:
            return

        item = selected_items[0]
        url, reason = self._extract_quicklook_url_with_reason(item)
        source = str(item.get('_source', 'unknown'))
        scene_id = str(item.get('id', 'unknown'))
        if not url:
            logger.info(
                'Archive Quicklook unresolved source=%s scene=%s reason=%s',
                source,
                scene_id,
                reason,
            )
            self.status_label.setText('No quicklook URL available for this scene.')
            self.status_label.setStyleSheet(f'color: {self._LABEL_COLOR}; font-size: 10px;')
            return

        logger.info(
            'Archive Quicklook resolved source=%s scene=%s url=%s reason=%s',
            source,
            scene_id,
            url,
            reason,
        )

        if self._try_load_quicklook_georeferenced(item, url):
            logger.info(
                'Archive Quicklook loaded georeferenced source=%s scene=%s url=%s',
                source,
                scene_id,
                url,
            )
            return

        logger.info(
            'Archive Quicklook panel fallback source=%s scene=%s url=%s',
            source,
            scene_id,
            url,
        )
        self.status_label.setText('Quicklook shown in panel (georeferenced map portrayal not available).')
        self.status_label.setStyleSheet(f'color: {self._LABEL_COLOR}; font-size: 10px;')

    def _extract_quicklook_url(self, item: Dict[str, Any]) -> Optional[str]:
        url, _ = self._extract_quicklook_url_with_reason(item)
        return url

    def _extract_quicklook_url_with_reason(self, item: Dict[str, Any]) -> Tuple[Optional[str], str]:
        connector = self._get_archive_connector_instance(item)
        if connector is not None:
            try:
                if hasattr(connector, 'resolve_preview_url'):
                    resolved = connector.resolve_preview_url(item)
                    if resolved:
                        return str(resolved), 'connector.resolve_preview_url'
                if hasattr(connector, 'get_preview_url'):
                    resolved = connector.get_preview_url(item)
                    if resolved:
                        return str(resolved), 'connector.get_preview_url'
            except Exception as exc:
                logger.debug(f'Connector preview resolution failed: {exc}')

        assets = item.get('assets', {})
        for key in ('thumbnail', 'quicklook', 'overview', 'preview'):
            asset = assets.get(key, {})
            if isinstance(asset, dict):
                href = asset.get('href')
                if href:
                    return str(href), f'assets.{key}.href'
            elif isinstance(asset, str):
                return asset, f'assets.{key}'

        props = item.get('properties', {}) if isinstance(item, dict) else {}
        if isinstance(props, dict):
            ql = props.get('quicklook_links')
            if isinstance(ql, list):
                for href in ql:
                    if href:
                        return str(href), 'properties.quicklook_links'

            # Common property thumbnail fields used by various APIs
            for field in (
                'thumbnail', 'thumbnail_url', 'thumbnail_href',
                'quicklook', 'quicklook_url', 'quicklook_href',
                'overview', 'overview_url',
                'browse_url', 'preview_url', 'preview',
            ):
                val = props.get(field)
                if val and isinstance(val, str):
                    return val, f'properties.{field}'

        links = item.get('links', [])
        for link in links:
            if link.get('rel') in ('thumbnail', 'preview', 'quicklook') and link.get('href'):
                return str(link.get('href')), f"links.rel={link.get('rel')}"

        return None, 'no-quicklook-candidate'

    def _fetch_quicklook_bytes(
        self,
        url: str,
        timeout_s: int = 15,
        extra_headers: Optional[Dict[str, str]] = None,
    ) -> Optional[bytes]:
        if not QGIS_AVAILABLE:
            return None
        try:
            request = QNetworkRequest(QUrl(url))
            request.setRawHeader(b'Accept', b'image/*,*/*;q=0.8')
            if extra_headers:
                for hk, hv in extra_headers.items():
                    request.setRawHeader(hk.encode(), hv.encode())
            if hasattr(request, 'setTransferTimeout'):
                request.setTransferTimeout(int(max(1, timeout_s) * 1000))
            blocking_request = QgsBlockingNetworkRequest()
            error = blocking_request.get(request, forceRefresh=True)
            if error != QgsBlockingNetworkRequest.NoError:
                logger.debug(f'Quicklook fetch failed: {blocking_request.errorMessage()}')
                return None
            reply = blocking_request.reply()
            data = reply.content().data()
            return bytes(data) if data else None
        except Exception as exc:
            logger.debug(f'Quicklook fetch exception: {exc}')
            return None

    def _cache_quicklook_payload(self, url: str, payload: Optional[bytes]) -> None:
        self._quicklook_cache[url] = payload
        if url in self._quicklook_cache_order:
            self._quicklook_cache_order.remove(url)
        self._quicklook_cache_order.append(url)
        while len(self._quicklook_cache_order) > self._quicklook_cache_max_entries:
            old = self._quicklook_cache_order.pop(0)
            self._quicklook_cache.pop(old, None)

    def _update_quicklook_preview(self, item: Optional[Dict[str, Any]]):
        self._quicklook_source_pixmap = None

        if not item:
            self.quicklook_preview.setPixmap(QPixmap())
            self.quicklook_preview.setText('No scene selected')
            return

        url = self._extract_quicklook_url(item)
        if not url:
            self.quicklook_preview.setPixmap(QPixmap())
            self.quicklook_preview.setText('No quicklook available for selected scene')
            return

        payload: Optional[bytes]
        if url in self._quicklook_cache:
            payload = self._quicklook_cache.get(url)
        else:
            preview_timeout = int(self.settings.value('AltairEOData/smart_quicklook_timeout', 6))
            preview_timeout = max(2, min(20, preview_timeout))
            auth_headers = self._get_asset_auth_headers_for_item(item, url)
            if not auth_headers:
                bearer = self._get_bearer_for_item(item)
                if bearer:
                    auth_headers = {'Authorization': f'Bearer {bearer}'}
            payload = self._fetch_quicklook_bytes(url, timeout_s=preview_timeout, extra_headers=auth_headers or None)
            self._cache_quicklook_payload(url, payload)

        if not payload:
            self.quicklook_preview.setPixmap(QPixmap())
            self.quicklook_preview.setText('Quicklook unavailable (download failed)')
            return

        pix = QPixmap()
        if not pix.loadFromData(payload):
            self.quicklook_preview.setPixmap(QPixmap())
            self.quicklook_preview.setText('Quicklook format not displayable')
            return

        self._quicklook_source_pixmap = pix
        self._refresh_quicklook_preview_pixmap()

    def _refresh_quicklook_preview_pixmap(self):
        if not self._quicklook_source_pixmap:
            return
        target = self.quicklook_preview.size()
        scaled = self._quicklook_source_pixmap.scaled(
            max(1, target.width() - 8),
            max(1, target.height() - 8),
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation,
        )
        self.quicklook_preview.setText('')
        self.quicklook_preview.setPixmap(scaled)

    def _quicklook_worldfile_ext(self, image_ext: str) -> str:
        ext = image_ext.lower()
        if ext in ('.jpg', '.jpeg'):
            return '.jgw'
        if ext == '.png':
            return '.pgw'
        if ext in ('.tif', '.tiff'):
            return '.tfw'
        if ext == '.jp2':
            return '.j2w'
        return '.wld'

    def _try_load_quicklook_georeferenced(self, item: Dict[str, Any], url: str) -> bool:
        if not QGIS_AVAILABLE:
            return False

        scene_id = str(item.get('id', 'quicklook'))[:30]
        if any(token in url.lower() for token in ('.tif', '.tiff', '.jp2', 'geotiff')):
            uri = f'/vsicurl/{url}' if url.startswith('http') else url
            layer = QgsRasterLayer(uri, f'{scene_id}_quicklook')
            if layer.isValid():
                QgsProject.instance().addMapLayer(layer)
                self.status_label.setText('Quicklook loaded as georeferenced raster in map.')
                self.status_label.setStyleSheet('color: #00ffbf; font-size: 10px;')
                return True

        bbox = item.get('bbox')
        if not bbox or len(bbox) < 4:
            return False

        auth_headers = self._get_asset_auth_headers_for_item(item, url)
        if not auth_headers:
            bearer = self._get_bearer_for_item(item)
            if bearer:
                auth_headers = {'Authorization': f'Bearer {bearer}'}
        payload = self._fetch_quicklook_bytes(url, extra_headers=auth_headers or None)
        if not payload:
            return False

        pix = QPixmap()
        if not pix.loadFromData(payload):
            return False

        width = pix.width()
        height = pix.height()
        if width <= 0 or height <= 0:
            return False

        min_lon, min_lat, max_lon, max_lat = bbox[:4]
        pixel_x = (max_lon - min_lon) / float(width)
        pixel_y = -((max_lat - min_lat) / float(height))
        x_origin = min_lon + (pixel_x / 2.0)
        y_origin = max_lat + (pixel_y / 2.0)

        parsed = urlparse(url)
        _, ext = os.path.splitext(parsed.path)
        if not ext:
            ext = '.png'

        fd, image_path = tempfile.mkstemp(prefix='smarttasking_quicklook_', suffix=ext)
        os.close(fd)
        with open(image_path, 'wb') as fout:
            fout.write(payload)

        worldfile_path = os.path.splitext(image_path)[0] + self._quicklook_worldfile_ext(ext)
        with open(worldfile_path, 'w', encoding='utf-8') as wf:
            wf.write(f'{pixel_x}\n')
            wf.write('0.0\n')
            wf.write('0.0\n')
            wf.write(f'{pixel_y}\n')
            wf.write(f'{x_origin}\n')
            wf.write(f'{y_origin}\n')

        prj_path = os.path.splitext(image_path)[0] + '.prj'
        try:
            with open(prj_path, 'w', encoding='utf-8') as prj:
                prj.write(QgsCoordinateReferenceSystem('EPSG:4326').toWkt())
        except Exception:
            pass

        layer = QgsRasterLayer(image_path, f'{scene_id}_quicklook')
        if not layer.isValid():
            return False

        layer.setCrs(QgsCoordinateReferenceSystem('EPSG:4326'))
        QgsProject.instance().addMapLayer(layer)
        self.status_label.setText('Quicklook georeferenced from bbox and loaded in map.')
        self.status_label.setStyleSheet('color: #00ffbf; font-size: 10px;')
        return True

    _COG_ASSET_PRIORITY = (
        'visual', 'TCI', 'TCI_10m', 'B_TCI',
        'B04_10m', 'B04', 'B03_10m', 'B03',
        'data', 'analytic', 'cog', 'image',
    )
    _COG_MEDIA_TYPES = {
        'image/tiff', 'image/geotiff', 'image/jp2',
        'image/vnd.stac.geotiff; cloud-optimized=true',
        'image/x.geotiff',
    }

    def _pick_cog_href(self, assets: Dict[str, Any], item: Optional[Dict[str, Any]] = None) -> Optional[str]:
        href, _ = self._pick_cog_href_with_reason(assets, item)
        return href

    def _pick_cog_href_with_reason(
        self,
        assets: Dict[str, Any],
        item: Optional[Dict[str, Any]] = None,
    ) -> Tuple[Optional[str], str]:
        if item is not None:
            connector = self._get_archive_connector_instance(item)
            if connector is not None:
                try:
                    if hasattr(connector, 'resolve_cog_url'):
                        resolved = connector.resolve_cog_url(item)
                        if resolved:
                            return str(resolved), 'connector.resolve_cog_url'
                    if hasattr(connector, 'get_cog_url'):
                        resolved = connector.get_cog_url(item)
                        if resolved:
                            return str(resolved), 'connector.get_cog_url'
                    if hasattr(connector, 'get_download_url'):
                        resolved = connector.get_download_url(item)
                        if resolved:
                            return str(resolved), 'connector.get_download_url'
                except Exception as exc:
                    logger.debug(f'Connector COG resolution failed: {exc}')

        for key in self._COG_ASSET_PRIORITY:
            asset = assets.get(key)
            if not asset:
                continue
            href = asset.get('href') if isinstance(asset, dict) else asset if isinstance(asset, str) else None
            if href and not href.endswith('.SAFE') and not href.endswith('/'):
                return href, f'assets-priority.{key}'

        for key, asset in assets.items():
            if key == 'thumbnail' or not isinstance(asset, dict):
                continue
            media_type = (asset.get('type') or '').lower()
            href = asset.get('href', '')
            if any(mt in media_type for mt in self._COG_MEDIA_TYPES):
                if href and not href.endswith('.SAFE') and not href.endswith('/'):
                    return href, f'assets-media-type.{key}'

        for key, asset in assets.items():
            if key == 'thumbnail':
                continue
            href = (asset.get('href') if isinstance(asset, dict) else asset if isinstance(asset, str) else '') or ''
            if href.lower().endswith(('.tif', '.tiff', '.jp2')) and not href.endswith('.SAFE'):
                return href, f'assets-extension.{key}'

        return None, 'no-cog-candidate'

    def _gdal_set_http_headers(self, headers: Dict[str, str]) -> None:
        if not headers:
            return
        try:
            from osgeo import gdal
            header_blob = '\r\n'.join(
                f'{str(k)}: {str(v)}'
                for k, v in headers.items()
                if str(k).strip() and str(v).strip()
            )
            if header_blob:
                gdal.SetConfigOption('GDAL_HTTP_HEADERS', header_blob)
        except Exception as exc:
            logger.debug(f'GDAL HTTP headers config skipped: {exc}')

    def _gdal_clear_http_headers(self) -> None:
        try:
            from osgeo import gdal
            gdal.SetConfigOption('GDAL_HTTP_HEADERS', None)
        except Exception:
            pass

    def _gdal_set_bearer(self, token: Optional[str]) -> None:
        if token:
            self._gdal_set_http_headers({'Authorization': f'Bearer {token}'})

    def _gdal_clear_bearer(self) -> None:
        self._gdal_clear_http_headers()

    def _get_asset_auth_headers_for_item(self, item: Dict[str, Any], href: str) -> Dict[str, str]:
        connector = self._get_archive_connector_instance(item)
        if connector is None:
            return {}
        try:
            if hasattr(connector, 'get_asset_auth_headers'):
                headers = connector.get_asset_auth_headers(item, href)
                if isinstance(headers, dict):
                    return {
                        str(k): str(v)
                        for k, v in headers.items()
                        if str(k).strip() and str(v).strip()
                    }
        except Exception as exc:
            logger.debug(f'Connector asset auth header resolution failed: {exc}')
        return {}

    def _get_bearer_for_item(self, item: Dict[str, Any]) -> Optional[str]:
        source = item.get('_source', '')
        if not source or not self._connector_manager:
            return None
        try:
            connector_info = getattr(self._connector_manager, '_connectors', {}).get(source, {})
            connector = connector_info.get('instance') if connector_info else None
            token = getattr(connector, '_access_token', None) if connector else None
            return str(token) if token else None
        except Exception:
            return None

    def _load_cog(self):
        rows = self._get_selected_archive_result_indices()
        if not rows or not QGIS_AVAILABLE:
            return

        loaded = 0
        errors: List[str] = []
        for result_index in rows[:5]:
            if result_index >= len(self._search_results):
                continue
            item = self._search_results[result_index]
            assets = item.get('assets', {})
            href, reason = self._pick_cog_href_with_reason(assets, item)
            source = str(item.get('_source', 'unknown'))
            if not href:
                logger.info(
                    'Archive COG unresolved source=%s scene=%s reason=%s',
                    source,
                    str(item.get('id', result_index)),
                    reason,
                )
                errors.append(str(item.get('id', result_index))[:20])
                continue

            scene_id = str(item.get('id', f'archive_{result_index}'))[:20]
            uri = f'/vsicurl/{href}' if href.startswith('http') else href
            auth_headers = self._get_asset_auth_headers_for_item(item, href)
            bearer = self._get_bearer_for_item(item)
            logger.info(
                'Archive COG resolved source=%s scene=%s url=%s reason=%s auth=%s',
                source,
                scene_id,
                href,
                reason,
                'asset_headers' if auth_headers else ('bearer' if bearer else 'none'),
            )
            if auth_headers:
                self._gdal_set_http_headers(auth_headers)
            elif bearer:
                self._gdal_set_bearer(bearer)
            try:
                layer = QgsRasterLayer(uri, scene_id)
                if not layer.isValid() and href.startswith('http'):
                    layer = QgsRasterLayer(href, scene_id)

                if layer.isValid():
                    QgsProject.instance().addMapLayer(layer)
                    loaded += 1
                    logger.info(
                        'Archive COG loaded source=%s scene=%s uri=%s',
                        source,
                        scene_id,
                        uri,
                    )
                else:
                    logger.warning(f'Invalid COG layer for {scene_id}: {uri}')
                    errors.append(scene_id)
            finally:
                if auth_headers or bearer:
                    self._gdal_clear_http_headers()

        if loaded:
            self.status_label.setText(f'{loaded} COG layer(s) added to map.')
            self.status_label.setStyleSheet('color: #00ffbf; font-size: 10px;')
        else:
            msg = 'No valid COG layer loaded.'
            if errors:
                msg += f' Failed: {", ".join(errors[:3])}'
            self.status_label.setText(msg)
            self.status_label.setStyleSheet('color: #ff6b6b; font-size: 10px;')

    def _download_asset(self):
        selected_items = self._get_selected_archive_items()
        if len(selected_items) != 1:
            return

        item = selected_items[0]
        assets = item.get('assets') if isinstance(item, dict) else {}
        assets = assets if isinstance(assets, dict) else {}
        href, reason = self._pick_cog_href_with_reason(assets, item)
        source = str(item.get('_source', 'unknown'))
        scene_id = str(item.get('id', 'asset') or 'asset')

        if not href:
            self.status_label.setText('No downloadable asset URL for selected scene.')
            self.status_label.setStyleSheet('color: #ff6b6b; font-size: 10px;')
            logger.info(
                'Archive download unresolved source=%s scene=%s reason=%s',
                source,
                scene_id,
                reason,
            )
            return

        parsed = urlparse(href)
        suggested_name = os.path.basename(parsed.path) or f'{scene_id}.tif'
        if '.' not in suggested_name:
            suggested_name = f'{suggested_name}.tif'

        default_dir = str(self.settings.value('altair/download_folder', '') or '').strip()
        if not default_dir or not os.path.isdir(default_dir):
            default_dir = os.path.join(os.path.expanduser('~'), 'Downloads')
            if not os.path.isdir(default_dir):
                default_dir = os.path.expanduser('~')

        save_path, _ = QFileDialog.getSaveFileName(
            self,
            'Download asset',
            os.path.join(default_dir, suggested_name),
            'GeoTIFF (*.tif *.tiff);;JPEG2000 (*.jp2);;All files (*.*)',
        )
        if not save_path:
            return

        # Persist folder choice as default for next downloads.
        try:
            chosen_dir = os.path.dirname(save_path)
            if chosen_dir:
                self.settings.setValue('altair/download_folder', chosen_dir)
        except Exception:
            pass

        auth_headers = self._get_asset_auth_headers_for_item(item, href)
        if not auth_headers:
            bearer = self._get_bearer_for_item(item)
            if bearer:
                auth_headers = {'Authorization': f'Bearer {bearer}'}

        try:
            request = urllib.request.Request(href)
            for key, value in auth_headers.items():
                request.add_header(str(key), str(value))

            with urllib.request.urlopen(request, timeout=120) as response:
                with open(save_path, 'wb') as output_file:
                    while True:
                        chunk = response.read(1024 * 1024)
                        if not chunk:
                            break
                        output_file.write(chunk)

            self.status_label.setText(
                f'Asset downloaded: {os.path.basename(save_path)}'
            )
            self.status_label.setStyleSheet('color: #00ffbf; font-size: 10px;')
            logger.info(
                'Archive asset downloaded source=%s scene=%s reason=%s path=%s',
                source,
                scene_id,
                reason,
                save_path,
            )
        except Exception as exc:
            self.status_label.setText(f'Download failed: {exc}')
            self.status_label.setStyleSheet('color: #ff6b6b; font-size: 10px;')
            logger.error(
                'Archive asset download failed source=%s scene=%s url=%s: %s',
                source,
                scene_id,
                href,
                exc,
            )

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
            orbit_layer.setCrs(QgsCoordinateReferenceSystem('EPSG:4326'))
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
            ground_layer.setCrs(QgsCoordinateReferenceSystem('EPSG:4326'))
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
            swath_layer.setCrs(QgsCoordinateReferenceSystem('EPSG:4326'))
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
        sat_layer.setCrs(QgsCoordinateReferenceSystem('EPSG:4326'))
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
        nadir_layer.setCrs(QgsCoordinateReferenceSystem('EPSG:4326'))
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

            # QGIS/KADAS API compatibility: setShape() may expect an enum
            # (newer versions) or accept raw integer values (older versions).
            shape_candidates = []
            shape_enum = getattr(QgsPoint3DSymbol, 'Shape', None)
            if shape_enum is not None and hasattr(shape_enum, 'Sphere'):
                shape_candidates.append(getattr(shape_enum, 'Sphere'))
            if hasattr(QgsPoint3DSymbol, 'Sphere'):
                shape_candidates.append(getattr(QgsPoint3DSymbol, 'Sphere'))
            shape_candidates.append(1)  # legacy fallback

            shape_set = False
            for shape_value in shape_candidates:
                try:
                    pt_sym.setShape(shape_value)
                    shape_set = True
                    break
                except TypeError:
                    continue

            if not shape_set:
                logger.debug('QgsPoint3DSymbol shape enum not resolved; using default point shape')

            radius = max(3000.0, alt_m * 0.008)
            try:
                pt_sym.setShapeProperties({'radius': radius})
            except Exception as exc:
                logger.debug(f'Could not apply 3D point radius property: {exc}')
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

    def _clear_footprints_layer(self):
        """Safely remove SmartTasking footprint layers from the project."""
        if not QGIS_AVAILABLE:
            self._footprints_layer = None
            return
        try:
            if self.select_from_map_btn.isChecked():
                self._deactivate_selection_mode()
                self.select_from_map_btn.blockSignals(True)
                self.select_from_map_btn.setChecked(False)
                self.select_from_map_btn.blockSignals(False)

            project = QgsProject.instance()

            # Remove tracked layer first
            layer = self._footprints_layer
            if layer is not None:
                try:
                    project.removeMapLayer(layer.id())
                except Exception:
                    pass

            # Defensive cleanup of any leftover layers with same display name
            for leftover in project.mapLayersByName('SmartTasking Footprints'):
                try:
                    project.removeMapLayer(leftover.id())
                except Exception:
                    pass
        finally:
            self._footprints_layer = None
            self._feature_id_to_result_index = {}
            self._result_index_to_feature_id = {}
            self._update_archive_action_state()

    def _refresh_footprints_layer(self):
        if not QGIS_AVAILABLE or not self._search_results:
            return
        try:
            self._clear_footprints_layer()

            layer = QgsVectorLayer('Polygon?crs=EPSG:4326', 'SmartTasking Footprints', 'memory')
            layer.setCrs(QgsCoordinateReferenceSystem('EPSG:4326'))
            pr = layer.dataProvider()

            fields = QgsFields()
            fields.append(QgsField('index', QVariant.Int))
            fields.append(QgsField('provider', QVariant.String))
            fields.append(QgsField('date', QVariant.String))
            fields.append(QgsField('id', QVariant.String))
            pr.addAttributes(fields)
            layer.updateFields()

            features: List[QgsFeature] = []
            footprint_limit = int(self.settings.value('AltairEOData/smart_archive_footprint_limit', 250))
            footprint_limit = max(25, min(5000, footprint_limit))
            skipped = 0
            for idx, item in enumerate(self._search_results):
                if len(features) >= footprint_limit:
                    skipped += 1
                    continue
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
                'color': '0,120,255,51',
                'outline_color': '#0078ff',
                'outline_width': '0.4',
            })
            layer.renderer().setSymbol(sym)
            QgsProject.instance().addMapLayer(layer)
            self._footprints_layer = layer
            self._feature_id_to_result_index = {}
            self._result_index_to_feature_id = {}
            for feat in layer.getFeatures():
                result_index = feat.attribute('index')
                if result_index is None:
                    continue
                result_index = int(result_index)
                self._feature_id_to_result_index[feat.id()] = result_index
                self._result_index_to_feature_id[result_index] = feat.id()
            layer.selectionChanged.connect(self._on_layer_selection_changed)
            layer.destroyed.connect(self._on_footprints_layer_deleted)
            if skipped > 0:
                logger.info(
                    'SmartTasking footprints limited to %d features (%d skipped)',
                    footprint_limit,
                    skipped,
                )
            self._update_archive_action_state()
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
        max_days = int(self.settings.value('AltairEOData/smart_predict_max_days', 21))
        max_days = max(1, min(120, max_days))
        requested_days = max(1, (end_dt.date() - start_dt.date()).days + 1)
        horizon_clipped = False
        if requested_days > max_days:
            end_dt = start_dt + timedelta(days=max_days, seconds=-1)
            horizon_clipped = True

        max_overpasses = int(self.settings.value('AltairEOData/smart_predict_max_results', 500))
        max_overpasses = max(50, min(5000, max_overpasses))
        predict_parallelism = int(self.settings.value('AltairEOData/smart_predict_parallelism', 4))
        predict_parallelism = max(1, min(8, predict_parallelism))

        self.status_label.setText('Predicting overpasses …')
        self.status_label.setStyleSheet('color: #88ccff; font-size: 10px;')
        if horizon_clipped:
            logger.info(
                'Overpass horizon clipped from %d to %d day(s) for performance',
                requested_days,
                max_days,
            )

        if QGIS_AVAILABLE and hasattr(QgsApplication, 'taskManager'):
            task = _OverpassTask(
                satellites,
                lat,
                lon,
                start_dt,
                end_dt,
                max_results=max_overpasses,
                max_workers=predict_parallelism,
            )
            self._active_overpass_task = task
            task.taskCompleted.connect(lambda: self._on_overpass_done(task))
            task.taskTerminated.connect(lambda: self._on_overpass_error(task))
            self._update_go_button_state()
            QgsApplication.taskManager().addTask(task)
        else:
            # Synchronous fallback
            task = _OverpassTask(
                satellites,
                lat,
                lon,
                start_dt,
                end_dt,
                max_results=max_overpasses,
                max_workers=predict_parallelism,
            )
            self._active_overpass_task = task
            self._update_go_button_state()
            task.run()
            self._on_overpass_done(task)

    def _on_overpass_done(self, task: _OverpassTask):
        if task is not self._active_overpass_task:
            logger.debug('Ignoring stale overpass completion callback')
            return

        self._active_overpass_task = None
        self._overpass_results = task.results or []
        self._populate_overpass_table()
        self.results_tabs.setCurrentIndex(1)
        n = len(self._overpass_results)
        method = 'SGP4' if _SGP4_OK else 'analytical model'
        suffix = ' (truncated for performance)' if getattr(task, 'truncated', False) else ''
        self.status_label.setText(f'Prediction complete — {n} overpass(es) ({method}){suffix}')
        self.status_label.setStyleSheet('color: #00e5ff; font-size: 10px;')
        self._update_go_button_state()

    def _on_overpass_error(self, task: _OverpassTask):
        if task is not self._active_overpass_task:
            logger.debug('Ignoring stale overpass error callback')
            return

        self._active_overpass_task = None
        msg = task.error_message or 'Unknown error'
        self.status_label.setText(f'Overpass prediction failed: {msg}')
        self.status_label.setStyleSheet('color: #ff6b6b; font-size: 10px;')
        self._update_go_button_state()

    def _populate_overpass_table(self):
        self.overpass_table.blockSignals(True)
        self.overpass_table.setSortingEnabled(False)
        count = len(self._overpass_results)
        self.overpass_table.setRowCount(count)

        for row_idx, p in enumerate(self._overpass_results):
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
        self.overpass_count_label.setText(f'{count} overpass(es) predicted')

    def _build_archive_auth_payloads(self, connector_ids: List[str]) -> Tuple[List[str], Dict[str, Dict[str, Any]]]:
        """Build non-blocking auth payloads; network auth happens in search task."""
        ready_ids: List[str] = []
        auth_payloads: Dict[str, Dict[str, Any]] = {}

        if not self._connector_manager:
            return ready_ids, auth_payloads

        from ..connectors.connector_manager import ConnectorCapability

        for cid in connector_ids:
            ci = getattr(self._connector_manager, '_connectors', {}).get(cid, {})
            if not ci:
                continue

            caps = ci.get('capabilities', []) if isinstance(ci, dict) else []
            needs_auth = ConnectorCapability.AUTHENTICATION in caps

            if cid == 'vantor':
                creds = self._read_credentials('vantor') or {}
                discovery_enabled = bool(creds.get('discovery_enabled', True))
                has_discovery_auth = bool(
                    str(creds.get('discovery_api_key') or '').strip()
                    or str(creds.get('discovery_access_token') or '').strip()
                )
                if discovery_enabled and not has_discovery_auth:
                    creds['discovery_enabled'] = False
                    logger.info('Altair Tasking: Vantor Discovery disabled (no credentials), using open-data search')
                auth_payloads[cid] = creds
                ready_ids.append(cid)
                continue

            if cid in ('element84_stac', 'planetary_computer_stac'):
                creds = self._read_credentials(cid) or {}
                if creds:
                    auth_payloads[cid] = creds
                ready_ids.append(cid)
                continue

            if not needs_auth:
                ready_ids.append(cid)
                continue

            creds = self._read_credentials(cid) or {}
            if not creds and cid != 'nasa_earthdata':
                logger.info(f'Altair Tasking: skipping {cid} (missing credentials)')
                continue

            auth_payloads[cid] = creds
            ready_ids.append(cid)

        return ready_ids, auth_payloads

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
        logger.info(f'Altair Tasking summary: {len(selected)} satellites, mode={mode}')

    # ------------------------------------------------------------------
    # Send selected result to the Tasking Order dock
    # ------------------------------------------------------------------

    # Operator name (catalogue) → Tasking dock PROVIDERS list label
    _OPERATOR_TO_PROVIDER = {
        'vantor': 'Vantor',
        'Planet': 'Planet Labs',
        'Airbus': 'Airbus',
        'ICEYE': 'ICEYE',
        'Capella': 'Capella Space',
        'BlackSky': 'BlackSky',
    }

    def _send_to_tasking(self):
        """Build a prefill payload from the active tab's selected row and emit *order_requested*."""
        tab_idx = self.results_tabs.currentIndex()

        payload: Dict[str, Any] = {}

        # Grab AOI from the Altair Tasking extent widget (if available)
        if self.extent_widget:
            try:
                ext = self.extent_widget.outputExtent()
                crs = self.extent_widget.outputCrs()
                if ext and not ext.isEmpty() and crs and crs.isValid():
                    if crs.authid() != 'EPSG:4326':
                        tr = QgsCoordinateTransform(
                            crs, QgsCoordinateReferenceSystem('EPSG:4326'),
                            QgsProject.instance(),
                        )
                        ext = tr.transformBoundingBox(ext)
                    payload['bbox'] = [
                        ext.xMinimum(), ext.yMinimum(),
                        ext.xMaximum(), ext.yMaximum(),
                    ]
            except Exception:
                pass

        if tab_idx == 0:
            # --- Archive result ---
            self._fill_payload_from_archive(payload)
        elif tab_idx == 1:
            # --- Overpass prediction ---
            self._fill_payload_from_overpass(payload)
        else:
            self.status_label.setText('Switch to Archive or Overpass tab first.')
            self.status_label.setStyleSheet('color: #ffcc00; font-size: 10px;')
            return

        if not payload.get('_source'):
            self.status_label.setText('Select a row first, then send to Tasking.')
            self.status_label.setStyleSheet('color: #ffcc00; font-size: 10px;')
            return

        self.order_requested.emit(payload)
        self.status_label.setText('Sent to Tasking Order dock ✔')
        self.status_label.setStyleSheet('color: #00ffbf; font-size: 10px;')
        logger.info(f'Sent to Tasking: {payload.get("_source")} — {payload.get("satellite", "?")}')

    # ---- archive row → payload ----------------------------------------

    def _fill_payload_from_archive(self, payload: Dict):
        result_indices = self._get_selected_archive_result_indices()
        if not result_indices or result_indices[0] >= len(self._search_results):
            return
        item = self._search_results[result_indices[0]]

        payload['_source'] = 'archive'
        payload['_provider'] = item.get('_provider', '')
        payload['satellite'] = item.get('_satellite', '')

        # Sensor type from provider hint or properties
        sensor = 'Optical'
        prov = payload['_provider'].lower()
        if any(k in prov for k in ('iceye', 'umbra', 'capella', 'terrasar', 'sentinel-1')):
            sensor = 'SAR'
        payload['sensor_type'] = sensor

        # Dates from item
        props = item.get('properties', {})
        dt_str = props.get('datetime') or props.get('start_datetime', '')
        if dt_str:
            payload['date'] = dt_str[:10]  # YYYY-MM-DD

        # GSD
        gsd = props.get('gsd') or props.get('eo:gsd')
        if gsd:
            try:
                payload['gsd_m'] = float(gsd)
            except (ValueError, TypeError):
                pass

        # Bbox from item (may override extent widget)
        ibbox = item.get('bbox')
        if ibbox and len(ibbox) >= 4:
            payload['bbox'] = [float(v) for v in ibbox[:4]]

        # Notes
        payload['notes'] = (
            f"Archive scene: {item.get('id', 'N/A')}\n"
            f"Provider: {payload['_provider']}\n"
            f"Satellite: {payload.get('satellite', 'N/A')}\n"
            f"Date: {dt_str or 'N/A'}"
        )

    # ---- overpass row → payload ----------------------------------------

    def _fill_payload_from_overpass(self, payload: Dict):
        rows = sorted(
            {idx.row() for idx in self.overpass_table.selectionModel().selectedRows()}
        )
        if not rows:
            return
        item_widget = self.overpass_table.item(rows[0], self._OV_SAT)
        if not item_widget:
            return
        orig_idx = item_widget.data(Qt.UserRole)
        if orig_idx is None or orig_idx >= len(self._overpass_results):
            return
        op = self._overpass_results[orig_idx]

        payload['_source'] = 'overpass'
        payload['satellite'] = op.get('satellite', '')
        payload['operator'] = op.get('operator', '')

        # Map operator → Tasking dock provider label
        payload['_provider'] = self._OPERATOR_TO_PROVIDER.get(
            payload['operator'], payload['operator']
        )

        # Look up catalogue entry for rich metadata
        cat_entry = None
        for s in SATELLITE_CATALOGUE:
            if s['constellation'] == payload['satellite']:
                cat_entry = s
                break

        # Sensor type
        sensor_raw = (cat_entry or {}).get('sensor', 'Optical')
        if 'sar' in sensor_raw.lower():
            payload['sensor_type'] = 'SAR'
        else:
            payload['sensor_type'] = 'Optical'

        # GSD
        gsd = (cat_entry or {}).get('gsd_m')
        if gsd:
            payload['gsd_m'] = gsd

        # Overpass datetime → acquisition window
        dt_str = op.get('datetime_utc', '')  # "YYYY-MM-DD HH:MM UTC"
        if dt_str:
            payload['date'] = dt_str[:10]

        # Day/Night
        daylight = (cat_entry or {}).get('daylight', 'Day')
        if daylight == 'Both':
            payload['day_night'] = 'Any'
        elif daylight == 'Night':
            payload['day_night'] = 'Night only'
        else:
            payload['day_night'] = 'Day only'

        # SAR specifics
        if payload['sensor_type'] == 'SAR':
            payload['sar_mode'] = 'Any'
            payload['sar_polarization'] = 'Any'

        # Off-nadir / distance → resolution hint
        off_nadir = op.get('off_nadir_deg', 0)
        ground_dist = op.get('ground_dist_km', 0)
        direction = op.get('direction', '')
        confidence = op.get('confidence', '')
        duration = op.get('duration_min', 0)
        elev = op.get('max_elevation', 0)
        alt_km = op.get('orbit_alt_km', 0)

        # Rich notes
        lines = [
            f'Satellite: {payload["satellite"]} ({payload["operator"]})',
            f'Predicted pass: {dt_str}',
            f'Direction: {direction}',
            f'Off-nadir: {off_nadir}°  |  Ground dist: {ground_dist} km',
            f'Max elevation: {elev}°  |  Duration: {duration} min',
            f'Orbit altitude: {alt_km} km  |  Confidence: {confidence}',
        ]
        if cat_entry:
            lines.append(
                f'Sensor model: {cat_entry.get("sensor_model", "?")}  |  '
                f'Max off-nadir: {cat_entry.get("max_off_nadir_deg", "?")}°'
            )
        payload['notes'] = '\n'.join(lines)

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

        if ci.get('authenticated'):
            return True

        caps = ci.get('capabilities', [])
        from ..connectors.connector_manager import ConnectorCapability
        needs_auth = ConnectorCapability.AUTHENTICATION in caps

        # Vantor uses a public fallback, but authenticate() still applies
        # Discovery runtime config and credentials when available.
        if connector_id == 'vantor':
            try:
                creds = self._read_credentials('vantor') or {}
                discovery_enabled = bool(creds.get('discovery_enabled', True))
                has_discovery_auth = bool(
                    str(creds.get('discovery_api_key') or '').strip()
                    or str(creds.get('discovery_access_token') or '').strip()
                )
                if discovery_enabled and not has_discovery_auth:
                    # Avoid repeated 401 + fallback latency when Discovery credentials
                    # are not configured; use public open-data flow directly.
                    creds['discovery_enabled'] = False
                    logger.info('Altair Tasking: Vantor Discovery disabled (no credentials), using open-data search')
                self._connector_manager.authenticate_connector('vantor', creds)
                ci['authenticated'] = True
                return True
            except Exception as exc:
                logger.warning(f'Altair Tasking: Vantor setup failed: {exc}')
                ci['authenticated'] = False
                return False

        if not needs_auth:
            ci['authenticated'] = True
            return True

        # Read credentials from secure storage / QSettings
        creds = self._read_credentials(connector_id)
        if not creds and connector_id != 'nasa_earthdata':
            return False

        try:
            return bool(self._connector_manager.authenticate_connector(connector_id, creds))
        except Exception as exc:
            logger.warning(f'Altair Tasking: authentication failed for {connector_id}: {exc}')
            return False

    def _read_credentials(self, connector_id: str) -> Optional[Dict[str, Any]]:
        """Read credentials from secure storage / QSettings (mirrors archive_dock)."""
        try:
            from ..secrets.secure_storage import get_secure_storage
            ss = get_secure_storage()
        except ImportError:
            ss = None

        s = QSettings()

        if connector_id == 'vantor':
            credentials: Dict[str, Any] = {
                'discovery_enabled': s.value(
                    'AltairEOData/vantor_discovery_enabled', True, type=bool
                ),
                'discovery_base_url': str(
                    s.value(
                        'AltairEOData/vantor_discovery_base_url',
                        'https://api.maxar.com/discovery/v1',
                    )
                ).strip() or 'https://api.maxar.com/discovery/v1',
                'discovery_timeout': int(
                    s.value(
                        'AltairEOData/vantor_discovery_timeout',
                        s.value('AltairEOData/vantor_search_timeout', 30),
                        type=int,
                    )
                ),
                'discovery_search_path': str(
                    s.value(
                        'AltairEOData/vantor_discovery_search_path',
                        '/catalogs/imagery/search',
                    )
                ).strip() or '/catalogs/imagery/search',
                'tasking_base_url': str(
                    s.value('AltairEOData/vantor_tasking_base_url', '')
                ).strip(),
                'tasking_create_path': str(
                    s.value('AltairEOData/vantor_tasking_create_path', '/tasking/v2/requests')
                ).strip() or '/tasking/v2/requests',
                'tasking_list_path': str(
                    s.value('AltairEOData/vantor_tasking_list_path', '/tasking/v2/requests')
                ).strip() or '/tasking/v2/requests',
                'tasking_timeout': int(
                    s.value('AltairEOData/vantor_tasking_timeout', 30, type=int)
                ),
            }

            if ss:
                creds = ss.get_credentials('vantor') or {}
                api_key = (creds.get('discovery_api_key') or creds.get('api_key') or '').strip()
                token = (creds.get('discovery_access_token') or creds.get('access_token') or '').strip()
                if api_key:
                    credentials['discovery_api_key'] = api_key
                if token:
                    credentials['discovery_access_token'] = token
                tasking_token = (creds.get('tasking_access_token') or creds.get('access_token') or '').strip()
                if tasking_token:
                    credentials['tasking_access_token'] = tasking_token

            return credentials

        if connector_id == 'planet':
            creds = (ss.get_credentials('planet') if ss else {}) or {}
            token = (creds.get('api_key') or creds.get('access_token') or '').strip()
            if not token:
                return {}
            return {
                'api_key': token,
                'access_token': token,
                'api_base_url': str(s.value('AltairEOData/planet_api_base_url',
                                             'https://api.planet.com')).strip(),
                'tasking_base_url': str(
                    s.value('AltairEOData/planet_tasking_base_url', 'https://api.planet.com')
                ).strip() or 'https://api.planet.com',
                'tasking_orders_path': str(
                    s.value('AltairEOData/planet_tasking_orders_path', '/tasking/v2/orders/')
                ).strip() or '/tasking/v2/orders/',
                'tasking_pricing_path': str(
                    s.value('AltairEOData/planet_tasking_pricing_path', '/tasking/v2/pricing/')
                ).strip() or '/tasking/v2/pricing/',
            }

        if connector_id == 'jilin_gaofen_stac':
            creds = (ss.get_credentials('jilin_gaofen_stac') if ss else {}) or {}
            return {
                'base_url': str(s.value('AltairEOData/jilin_catalog_base_url', '')).strip(),
                'collection': str(s.value('AltairEOData/jilin_default_collection', '')).strip(),
                'access_token': str(creds.get('access_token') or '').strip(),
                'tasking_base_url': str(s.value('AltairEOData/jilin_tasking_base_url', '')).strip(),
                'tasking_create_path': str(
                    s.value('AltairEOData/jilin_tasking_create_path', '/tasking/v2/requests')
                ).strip() or '/tasking/v2/requests',
                'tasking_list_path': str(
                    s.value('AltairEOData/jilin_tasking_list_path', '/tasking/v2/requests')
                ).strip() or '/tasking/v2/requests',
                'tasking_access_token': str(
                    creds.get('tasking_access_token') or creds.get('access_token') or ''
                ).strip(),
            }

        if connector_id == 'jaxa_earth_stac':
            creds = (ss.get_credentials('jaxa_earth_stac') if ss else {}) or {}
            return {
                'catalog_url': str(
                    s.value('AltairEOData/jaxa_catalog_url', 'https://data.earth.jaxa.jp/stac/cog/v1/catalog.json')
                ).strip(),
                'search_url': str(
                    s.value('AltairEOData/jaxa_search_url', 'https://data.earth.jaxa.jp/stac/cog/v1/search')
                ).strip(),
                'tasking_base_url': str(s.value('AltairEOData/jaxa_tasking_base_url', '')).strip(),
                'tasking_create_path': str(
                    s.value('AltairEOData/jaxa_tasking_create_path', '/tasking/v2/requests')
                ).strip() or '/tasking/v2/requests',
                'tasking_list_path': str(
                    s.value('AltairEOData/jaxa_tasking_list_path', '/tasking/v2/requests')
                ).strip() or '/tasking/v2/requests',
                'tasking_access_token': str(creds.get('tasking_access_token') or '').strip(),
            }

        if connector_id == 'oneatlas':
            return (ss.get_credentials('oneatlas') if ss else {}) or {}

        if connector_id == 'element84_stac':
            return {
                'api_root': str(
                    s.value(
                        'AltairEOData/element84_stac_api_url',
                        'https://earth-search.aws.element84.com/v1',
                    )
                ).strip() or 'https://earth-search.aws.element84.com/v1',
                'timeout': int(
                    s.value('AltairEOData/element84_stac_timeout', 30, type=int)
                ),
            }

        if connector_id == 'planetary_computer_stac':
            return {
                'api_root': str(
                    s.value(
                        'AltairEOData/planetary_computer_stac_api_url',
                        'https://planetarycomputer.microsoft.com/api/stac/v1',
                    )
                ).strip() or 'https://planetarycomputer.microsoft.com/api/stac/v1',
                'timeout': int(
                    s.value(
                        'AltairEOData/planetary_computer_stac_timeout',
                        30,
                        type=int,
                    )
                ),
            }

        if connector_id == 'cdse_sentinel':
            return (ss.get_credentials('cdse_sentinel') if ss else {}) or {}

        if connector_id in ('iceye', 'iceye_stac'):
            creds = (ss.get_credentials('iceye') if ss else {}) or {}
            token = (creds.get('access_token') or '').strip()
            if not token:
                return {}
            return {
                'access_token': token,
                'api_base_url': str(
                    s.value(
                        'AltairEOData/iceye_endpoint',
                        s.value('altair/iceye_endpoint', 'https://api.iceye.com')
                    )
                ).strip(),
                'contract_id': str(
                    s.value(
                        'AltairEOData/iceye_contract_id',
                        s.value('altair/iceye_contract_id', '')
                    )
                ).strip() or None,
                'collections': str(
                    s.value(
                        'AltairEOData/iceye_collections',
                        s.value('altair/iceye_collections', '')
                    )
                ).strip() or None,
            }

        if connector_id in ('umbra', 'umbra_stac'):
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
                'api_base_url': str(
                    s.value(
                        'AltairEOData/umbra_api_base_url',
                        s.value('altair/umbra_api_base_url', 'https://api.canopy.umbra.space')
                    )
                ).strip(),
            }

        if connector_id in ('capella', 'capella_stac'):
            creds = (ss.get_credentials('capella') if ss else {}) or {}
            token = (creds.get('access_token') or '').strip()
            if not token:
                return {}
            return {
                'access_token': token,
                'api_base_url': str(
                    s.value(
                        'AltairEOData/capella_api_base_url',
                        s.value('altair/capella_api_base_url', 'https://api.capellaspace.com')
                    )
                ).strip(),
                'collections_path': str(
                    s.value(
                        'AltairEOData/capella_collections_path',
                        s.value('altair/capella_collections_path', '/stac/collections')
                    )
                ).strip() or '/stac/collections',
                'search_path': str(
                    s.value(
                        'AltairEOData/capella_search_path',
                        s.value('altair/capella_search_path', '/stac/search')
                    )
                ).strip() or '/stac/search',
            }

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
                'allow_deferred_validation': True,
            }

        return {}

    def _on_cloud_slider_changed(self, value: int):
        self.cloud_spin.blockSignals(True)
        try:
            self.cloud_spin.setValue(int(value))
        finally:
            self.cloud_spin.blockSignals(False)

    def _on_cloud_spin_changed(self, value: int):
        self.cloud_slider.blockSignals(True)
        try:
            self.cloud_slider.setValue(int(value))
        finally:
            self.cloud_slider.blockSignals(False)

    # ------------------------------------------------------------------
    # Reset
    # ------------------------------------------------------------------

    def _reset_all(self):
        # Cancel in-flight background work first to avoid stale callbacks
        for task_attr in ('_active_search_task', '_active_overpass_task'):
            task = getattr(self, task_attr, None)
            if task and self._is_task_active(task):
                try:
                    task.cancel()
                except Exception:
                    pass
            setattr(self, task_attr, None)

        self.date_start.setDate(QDate.currentDate().addMonths(-1))
        self.date_end.setDate(QDate.currentDate().addDays(14))
        self.sensor_combo.setCurrentIndex(0)
        self.resolution_combo.setCurrentIndex(0)
        self.access_combo.setCurrentIndex(0)
        self.daylight_combo.setCurrentIndex(0)
        self.cloud_slider.setValue(30)
        self.cloud_spin.setValue(30)
        if self.iface:
            canvas = self.iface.mapCanvas()
            self.extent_widget.setExtent(
                canvas.extent(),
                canvas.mapSettings().destinationCrs(),
            )
        self.archive_table.setRowCount(0)
        self.overpass_table.setRowCount(0)
        self.summary_text.clear()
        self._search_results.clear()
        self._overpass_results.clear()
        self._clear_footprints_layer()
        self._remove_3d_layers()
        self.fun_fact_label.setText('')
        self.archive_count_label.setText('No search performed')
        self.overpass_count_label.setText('No prediction performed')
        self._update_quicklook_preview(None)
        self.status_label.setText('Reset complete — switches back to default. Go again!')
        self.status_label.setStyleSheet(f'color: {self._LABEL_COLOR}; font-size: 10px;')
        self._update_go_button_state()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._refresh_quicklook_preview_pixmap()

    def closeEvent(self, event):
        if self.select_from_map_btn.isChecked():
            self._deactivate_selection_mode()
        super().closeEvent(event)
