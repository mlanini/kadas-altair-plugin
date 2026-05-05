"""
Altair Commercial Archive Search Dock Widget

Provides unified search across commercial satellite image archives:
  - Planet Labs (PlanetScope, SkySat, RapidEye, …)
  - Airbus OneAtlas (Pléiades, SPOT, Vision-1)
    - Jilin-1 Gaofen constellation
  - ICEYE SAR constellation
  - Capella Space SAR
  - Maxar (via Vantor STAC)
  - Copernicus Dataspace (Sentinel-1/2/3/5P) [optional]

Search runs in a background QgsTask; footprints are displayed on the map
as a temporary vector layer that stays in sync with the results table.
"""
from __future__ import annotations

import json
import os
import tempfile
from urllib.parse import urlparse
from typing import Any, Dict, List, Optional, Tuple

from qgis.PyQt.QtCore import (
    QDate, QItemSelectionModel, QSettings, Qt, QTimer, QUrl, QVariant, pyqtSignal,
)
from qgis.PyQt.QtGui import QDesktopServices, QFont, QPixmap
from qgis.PyQt.QtNetwork import QNetworkRequest
from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
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
    QSlider,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..logger import get_logger
from .footprint_tool import FootprintSelectionTool

logger = get_logger('gui.archive')

try:
    from ..secrets.secure_storage import get_secure_storage
except ImportError:
    logger.warning('Secure storage not available — using fallback')

    def get_secure_storage():
        return None


# ---------------------------------------------------------------------------
# QGIS core imports (guarded for test environments)
# ---------------------------------------------------------------------------
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
        QgsPointXY,
        QgsProject,
        QgsRasterLayer,
        QgsRectangle,
        QgsRuleBasedRenderer,
        QgsTask,
        QgsVectorLayer,
    )
    QGIS_AVAILABLE = True
except ImportError:
    logger.warning('QGIS core not available')
    QGIS_AVAILABLE = False
    QgsTask = object  # type: ignore

try:
    from qgis.gui import QgsExtentWidget
    QGIS_GUI_AVAILABLE = True
except ImportError:
    QgsExtentWidget = None
    QGIS_GUI_AVAILABLE = False

# ---------------------------------------------------------------------------
# KADAS-specific modules
# ---------------------------------------------------------------------------
try:
    from kadas.kadasgui import KadasItemLayer, KadasMapCanvasItemManager
    KADAS_AVAILABLE = True
except ImportError:
    KadasItemLayer = None
    KadasMapCanvasItemManager = None
    KADAS_AVAILABLE = False


# ---------------------------------------------------------------------------
# Provider catalogue — display name → connector_id
# ---------------------------------------------------------------------------
ARCHIVE_PROVIDERS: Dict[str, str] = {
    'Planet Labs':        'planet',
    'OneAtlas (Airbus)':  'oneatlas',
    'Jilin-1 Gaofen':     'jilin_gaofen_stac',
    'Umbra SAR':          'umbra_stac',
    'ICEYE SAR':          'iceye_stac',
    'Capella Space':      'capella_stac',
    'Vantor':             'vantor',
    'NASA EarthData':     'nasa_earthdata',
    'Copernicus':         'copernicus_stac',
    'swisstopo S2-SR':    'swisstopo_stac',
}


# ---------------------------------------------------------------------------
# Background search task
# ---------------------------------------------------------------------------
class ArchiveSearchTask(QgsTask if QGIS_AVAILABLE else object):  # type: ignore
    """Run a unified archive search in a background thread."""

    def __init__(self, connector_manager, search_params: Dict[str, Any]):
        if QGIS_AVAILABLE:
            super().__init__('Archive Search', QgsTask.CanCancel)
        self.connector_manager = connector_manager
        self.search_params = search_params
        self.results: List[Dict] = []
        self.error_message: Optional[str] = None

    def run(self) -> bool:
        try:
            logger.debug(f'ArchiveSearchTask params: {self.search_params}')
            bbox = self.search_params.get('bbox')
            start_date = self.search_params.get('start_date') or self.search_params.get('date_from')
            end_date = self.search_params.get('end_date') or self.search_params.get('date_to')
            max_cloud_cover = self.search_params.get('max_cloud_cover')
            if max_cloud_cover is None:
                max_cloud_cover = self.search_params.get('cloud_cover')
            limit = int(self.search_params.get('limit', 100))
            sensor_type = str(self.search_params.get('sensor_type', 'All'))
            connector_ids = list(self.search_params.get('connector_ids', []))

            aggregated: List[Dict[str, Any]] = []
            for connector_id in connector_ids:
                items, _ = self.connector_manager.search(
                    bbox=bbox,
                    start_date=start_date,
                    end_date=end_date,
                    max_cloud_cover=max_cloud_cover,
                    limit=limit,
                    connector_id=connector_id,
                )

                display_name = connector_id
                connector_info = getattr(self.connector_manager, '_connectors', {}).get(connector_id, {})
                if connector_info:
                    display_name = connector_info.get('display_name', connector_id)

                for item in items or []:
                    item['_provider'] = display_name
                    item['_source'] = connector_id
                    item['_source_name'] = display_name

                    if self._matches_sensor_filter(item, sensor_type):
                        aggregated.append(item)

            self.results = aggregated
            logger.info(f'ArchiveSearchTask: {len(self.results)} scene(s) found')
            return True
        except Exception as exc:
            logger.error(f'ArchiveSearchTask failed: {exc}', exc_info=True)
            self.error_message = str(exc)
            return False

    @staticmethod
    def _matches_sensor_filter(item: Dict[str, Any], sensor_type: str) -> bool:
        """Apply a lightweight post-filter on sensor family."""
        sensor_type = (sensor_type or 'All').strip().lower()
        if sensor_type == 'all':
            return True

        props = item.get('properties', item)
        text = ' '.join(
            str(props.get(key, ''))
            for key in ('platform', 'instruments', 'constellation', 'mission', 'sar:instrument_mode')
        ).lower()

        is_sar = any(token in text for token in ('sar', 'radar', 'iceye', 'capella', 'umbra'))
        if sensor_type == 'sar':
            return is_sar
        if sensor_type == 'optical':
            return not is_sar
        return True

    def finished(self, result: bool) -> None:
        if result:
            logger.debug('ArchiveSearchTask finished OK')
        else:
            logger.error(f'ArchiveSearchTask error: {self.error_message}')


# ---------------------------------------------------------------------------
# Sortable numeric table item
# ---------------------------------------------------------------------------
class _NumItem(QTableWidgetItem):
    def __lt__(self, other: QTableWidgetItem) -> bool:
        try:
            return float(self.text()) < float(other.text())
        except ValueError:
            return super().__lt__(other)


# ===========================================================================
# Main dock widget
# ===========================================================================
class ArchiveDockWidget(QDockWidget):
    """Dock for commercial satellite archive search."""

    # Emitted when the user wants to create a tasking order from a result
    order_requested = pyqtSignal(dict)   # payload: basic scene dict

    _LABEL_COLOR = '#303030'
    _SETTINGS_PREFIX = 'AltairEOData/'

    # Table column indices
    _COL_PROVIDER  = 0
    _COL_DATE      = 1
    _COL_SATELLITE = 2
    _COL_CLOUD     = 3
    _COL_GSD       = 4
    _COL_ID        = 5

    def __init__(self, iface, parent=None):
        super().__init__('Archive Search', parent)
        logger.info('Initializing Archive Search dock widget')

        self.iface = iface
        self.settings = QSettings()
        self.secure_storage = get_secure_storage()

        self.setObjectName('AltairArchiveDock')
        self.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)

        self._search_results: List[Dict] = []
        self._footprints_layer: Optional[Any] = None
        self._updating_selection: bool = False
        self._feature_id_to_result_index: Dict[int, int] = {}
        self._result_index_to_feature_id: Dict[int, int] = {}
        self._active_task: Optional[ArchiveSearchTask] = None
        self._connector_manager = None
        self._selection_tool = None
        self._previous_map_tool = None
        self._quicklook_source_pixmap: Optional[QPixmap] = None

        self._setup_ui()
        self._init_connector_manager()

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
            f'QCheckBox {{ color: {self._LABEL_COLOR}; }}'
        )

        layout = QVBoxLayout(root)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)
        layout.setAlignment(Qt.AlignTop)

        # --- Header ---
        header = QLabel('TEST Archive Search')
        hf = QFont()
        hf.setPointSize(12)
        hf.setBold(True)
        header.setFont(hf)
        header.setAlignment(Qt.AlignCenter)
        header.setStyleSheet('color: #1f1f1f;')
        layout.addWidget(header)

        subtitle = QLabel(
            'Search commercial satellite archives (Planet, Airbus, Jilin-1, Umbra, ICEYE, Capella, Maxar, '
            'Copernicus). Credentials are configured in Settings.'
        )
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet(f'color: {self._LABEL_COLOR}; font-size: 10px;')
        layout.addWidget(subtitle)

        # --- Providers ---
        prov_group = QGroupBox('Available Providers')
        prov_layout = QVBoxLayout(prov_group)

        self._provider_checks: Dict[str, QCheckBox] = {}
        prov_row1 = QHBoxLayout()
        prov_row2 = QHBoxLayout()
        names = list(ARCHIVE_PROVIDERS.keys())
        split_idx = (len(names) + 1) // 2
        for i, name in enumerate(names):
            cb = QCheckBox(name)
            cb.setChecked(True)
            self._provider_checks[name] = cb
            (prov_row1 if i < split_idx else prov_row2).addWidget(cb)

        prov_row1.addStretch()
        prov_row2.addStretch()
        prov_layout.addLayout(prov_row1)
        prov_layout.addLayout(prov_row2)
        layout.addWidget(prov_group)

        # --- Filters ---
        filter_group = QGroupBox('Search Filters')
        filter_form = QFormLayout(filter_group)
        filter_form.setRowWrapPolicy(QFormLayout.WrapAllRows)

        # Sensor type
        self.sensor_combo = QComboBox()
        self.sensor_combo.addItems(['All', 'Optical', 'SAR'])
        self.sensor_combo.currentTextChanged.connect(self._on_sensor_changed)
        filter_form.addRow('Sensor Type:', self.sensor_combo)

        # Date range
        date_row = QHBoxLayout()
        self.date_start = QDateEdit()
        self.date_start.setCalendarPopup(True)
        self.date_start.setDate(QDate.currentDate().addMonths(-3))
        self.date_start.setDisplayFormat('yyyy-MM-dd')
        date_row.addWidget(QLabel('From:'))
        date_row.addWidget(self.date_start)
        self.date_end = QDateEdit()
        self.date_end.setCalendarPopup(True)
        self.date_end.setDate(QDate.currentDate())
        self.date_end.setDisplayFormat('yyyy-MM-dd')
        date_row.addWidget(QLabel('To:'))
        date_row.addWidget(self.date_end)
        filter_form.addRow('Date Range:', date_row)

        # Cloud cover (optical only)
        cloud_row = QHBoxLayout()
        self.cloud_slider = QSlider(Qt.Horizontal)
        self.cloud_slider.setRange(0, 100)
        self.cloud_slider.setValue(30)
        self.cloud_slider.setTickPosition(QSlider.TicksBelow)
        self.cloud_slider.setTickInterval(10)
        self.cloud_label = QLabel('30 %')
        self.cloud_label.setMinimumWidth(40)
        self.cloud_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.cloud_slider.valueChanged.connect(
            lambda v: self.cloud_label.setText(f'{v} %')
        )
        cloud_row.addWidget(self.cloud_slider)
        cloud_row.addWidget(self.cloud_label)
        filter_form.addRow('Max Cloud Cover:', cloud_row)

        # Result limit
        self.limit_combo = QComboBox()
        for v in ['25', '50', '100', '200', '500']:
            self.limit_combo.addItem(v)
        self.limit_combo.setCurrentText('100')
        filter_form.addRow('Max Results:', self.limit_combo)

        layout.addWidget(filter_group)

        # --- AOI ---
        aoi_group = QGroupBox('Area Of Interest')
        aoi_form = QFormLayout(aoi_group)

        self.extent_widget = None
        if QGIS_AVAILABLE and QGIS_GUI_AVAILABLE and QgsExtentWidget and self.iface:
            self.extent_widget = QgsExtentWidget(parent=aoi_group)
            self.extent_widget.setMapCanvas(self.iface.mapCanvas())

            canvas_extent = self.iface.mapCanvas().extent()
            canvas_crs = self.iface.mapCanvas().mapSettings().destinationCrs()
            self.extent_widget.setCurrentExtent(canvas_extent, canvas_crs)
            self.extent_widget.setOriginalExtent(canvas_extent, canvas_crs)
            self.extent_widget.setOutputCrs(canvas_crs)

            aoi_form.addRow('Search Area:', self.extent_widget)
        else:
            fallback = QLabel('QgsExtentWidget unavailable. AOI controls are disabled in this environment.')
            fallback.setWordWrap(True)
            fallback.setStyleSheet(f'color: {self._LABEL_COLOR}; font-size: 10px;')
            aoi_form.addRow('', fallback)
        layout.addWidget(aoi_group)

        # --- Search actions ---
        search_row = QHBoxLayout()
        self.search_btn = QPushButton('Search')
        self.search_btn.setToolTip('Run archive search with current filters')
        self.search_btn.clicked.connect(self._on_search_clicked)
        search_row.addWidget(self.search_btn)

        self.clear_btn = QPushButton('Clear Results')
        self.clear_btn.setEnabled(False)
        self.clear_btn.clicked.connect(self._on_clear_results)
        search_row.addWidget(self.clear_btn)
        layout.addLayout(search_row)

        # --- Results table ---
        results_group = QGroupBox('Results')
        results_layout = QVBoxLayout(results_group)

        self.results_table = QTableWidget()
        self.results_table.setColumnCount(6)
        self.results_table.setHorizontalHeaderLabels(
            ['Provider', 'Date', 'Satellite', 'Cloud %', 'GSD (m)', 'Scene ID']
        )
        hh = self.results_table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeToContents)
        hh.setStretchLastSection(True)
        self.results_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.results_table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.results_table.setAlternatingRowColors(True)
        self.results_table.setSortingEnabled(True)
        self.results_table.itemSelectionChanged.connect(self._on_table_selection_changed)
        results_layout.addWidget(self.results_table)

        result_count_row = QHBoxLayout()
        self.result_count_label = QLabel('No search performed')
        self.result_count_label.setStyleSheet(f'color: {self._LABEL_COLOR}; font-size: 10px;')
        result_count_row.addWidget(self.result_count_label)
        result_count_row.addStretch()
        results_layout.addLayout(result_count_row)

        layout.addWidget(results_group)

        # --- In-panel quicklook preview (fallback if map georef is not possible) ---
        preview_group = QGroupBox('Quicklook Preview')
        preview_layout = QVBoxLayout(preview_group)

        self.quicklook_preview = QLabel('No scene selected')
        self.quicklook_preview.setAlignment(Qt.AlignCenter)
        self.quicklook_preview.setMinimumHeight(120)
        self.quicklook_preview.setWordWrap(True)
        self.quicklook_preview.setStyleSheet(
            f'color: {self._LABEL_COLOR}; background-color: rgba(255,255,255,0.04); '
            f'border: 1px solid rgba(255,255,255,0.12); font-size: 10px;'
        )
        preview_layout.addWidget(self.quicklook_preview)
        layout.addWidget(preview_group)

        # --- Action buttons ---
        actions_row = QHBoxLayout()

        self.select_from_map_btn = QPushButton('Select from Map')
        self.select_from_map_btn.setCheckable(True)
        self.select_from_map_btn.setEnabled(False)
        self.select_from_map_btn.setToolTip('Click footprints on map to select rows. Ctrl+Click for multi-select.')
        self.select_from_map_btn.toggled.connect(self._on_selection_mode_toggled)
        actions_row.addWidget(self.select_from_map_btn)

        self.zoom_btn = QPushButton('Zoom to Selection')
        self.zoom_btn.setEnabled(False)
        self.zoom_btn.clicked.connect(self._zoom_to_selected)
        actions_row.addWidget(self.zoom_btn)

        self.quicklook_btn = QPushButton('Open Quicklook')
        self.quicklook_btn.setEnabled(False)
        self.quicklook_btn.setToolTip('Load quicklook georeferenced in map when possible, otherwise show in panel')
        self.quicklook_btn.clicked.connect(self._open_quicklook)
        actions_row.addWidget(self.quicklook_btn)

        self.load_cog_btn = QPushButton('Load COG')
        self.load_cog_btn.setEnabled(False)
        self.load_cog_btn.setToolTip('Add COG visual layer to map')
        self.load_cog_btn.clicked.connect(self._load_cog)
        actions_row.addWidget(self.load_cog_btn)

        self.order_btn = QPushButton('Create Tasking Order')
        self.order_btn.setEnabled(False)
        self.order_btn.setToolTip('Open Tasking Order panel pre-filled for this provider')
        self.order_btn.clicked.connect(self._on_order_clicked)
        actions_row.addWidget(self.order_btn)

        layout.addLayout(actions_row)

        # --- Status ---
        self.status_label = QLabel('Ready — configure credentials in Settings, then search.')
        self.status_label.setStyleSheet(f'color: {self._LABEL_COLOR}; font-size: 10px;')
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        # Spinner state
        self._spinner_timer: Optional[QTimer] = None
        self._spinner_state: int = 0
        self._spinner_frames = ['◐ Searching', '◓ Searching', '◑ Searching', '◒ Searching']

    # ------------------------------------------------------------------
    # Connector manager initialisation
    # ------------------------------------------------------------------

    def _init_connector_manager(self):
        """Lazy-init ConnectorManager with all registered connectors."""
        try:
            from ..connectors.connector_manager import ConnectorManager, ConnectorType, ConnectorCapability

            self._connector_manager = ConnectorManager()

            # Planet
            try:
                from ..connectors.planet import PlanetConnector
                planet = PlanetConnector()
                self._connector_manager.register_connector(
                    'planet', planet, 'Planet Labs',
                    capabilities=[
                        ConnectorCapability.BBOX_SEARCH,
                        ConnectorCapability.DATE_RANGE,
                        ConnectorCapability.CLOUD_COVER,
                        ConnectorCapability.AUTHENTICATION,
                        ConnectorCapability.COMMERCIAL,
                    ]
                )
                logger.debug('Planet connector registered')
            except Exception as exc:
                logger.warning(f'Planet connector unavailable: {exc}')

            # OneAtlas
            try:
                from ..connectors.oneatlas import OneAtlasConnector
                oneatlas = OneAtlasConnector()
                self._connector_manager.register_connector(
                    'oneatlas', oneatlas, 'OneAtlas (Airbus)',
                    capabilities=[
                        ConnectorCapability.BBOX_SEARCH,
                        ConnectorCapability.DATE_RANGE,
                        ConnectorCapability.CLOUD_COVER,
                        ConnectorCapability.AUTHENTICATION,
                        ConnectorCapability.COMMERCIAL,
                    ]
                )
                logger.debug('OneAtlas connector registered')
            except Exception as exc:
                logger.warning(f'OneAtlas connector unavailable: {exc}')

            # ICEYE STAC
            try:
                from ..connectors.iceye_stac import IceyeStacConnector
                iceye = IceyeStacConnector()
                self._connector_manager.register_connector(
                    'iceye_stac', iceye, 'ICEYE SAR',
                    capabilities=[
                        ConnectorCapability.BBOX_SEARCH,
                        ConnectorCapability.DATE_RANGE,
                        ConnectorCapability.AUTHENTICATION,
                        ConnectorCapability.COMMERCIAL,
                    ]
                )
                logger.debug('ICEYE connector registered')
            except Exception as exc:
                logger.warning(f'ICEYE connector unavailable: {exc}')

            # Umbra STAC v2 (commercial archive)
            try:
                from ..connectors.umbra_stac import UmbraSTACConnector
                umbra = UmbraSTACConnector()
                self._connector_manager.register_connector(
                    'umbra_stac', umbra, 'Umbra SAR',
                    capabilities=[
                        ConnectorCapability.BBOX_SEARCH,
                        ConnectorCapability.DATE_RANGE,
                        ConnectorCapability.COLLECTIONS,
                        ConnectorCapability.AUTHENTICATION,
                        ConnectorCapability.COMMERCIAL,
                    ]
                )
                logger.debug('Umbra connector registered')
            except Exception as exc:
                logger.warning(f'Umbra connector unavailable: {exc}')

            # Capella Space
            try:
                from ..connectors.capella_stac import CapellaSTACConnector
                capella = CapellaSTACConnector()
                self._connector_manager.register_connector(
                    'capella_stac', capella, 'Capella Space',
                    capabilities=[
                        ConnectorCapability.BBOX_SEARCH,
                        ConnectorCapability.DATE_RANGE,
                        ConnectorCapability.COLLECTIONS,
                        ConnectorCapability.COG_SUPPORT,
                    ]
                )
                logger.debug('Capella connector registered')
            except Exception as exc:
                logger.warning(f'Capella connector unavailable: {exc}')

            # Maxar / Vantor
            try:
                from ..connectors.vantor import VantorConnector
                vantor = VantorConnector()
                self._connector_manager.register_connector(
                    'vantor', vantor, 'Maxar (Vantor)',
                    capabilities=[
                        ConnectorCapability.BBOX_SEARCH,
                        ConnectorCapability.DATE_RANGE,
                        ConnectorCapability.CLOUD_COVER,
                    ]
                )
                logger.debug('Vantor/Maxar connector registered')
            except Exception as exc:
                logger.warning(f'Vantor connector unavailable: {exc}')

            # Copernicus
            try:
                from ..connectors.copernicus_stac import CopernicusStacConnector
                copernicus = CopernicusStacConnector()
                self._connector_manager.register_connector(
                    'copernicus_stac', copernicus, 'Copernicus',
                    capabilities=[
                        ConnectorCapability.BBOX_SEARCH,
                        ConnectorCapability.DATE_RANGE,
                        ConnectorCapability.CLOUD_COVER,
                        ConnectorCapability.AUTHENTICATION,
                    ]
                )
                logger.debug('Copernicus connector registered')
            except Exception as exc:
                logger.warning(f'Copernicus connector unavailable: {exc}')

            # NASA EarthData
            try:
                from ..connectors.nasa_earthdata import NasaEarthdataConnector
                nasa = NasaEarthdataConnector()
                self._connector_manager.register_connector(
                    'nasa_earthdata', nasa, 'NASA EarthData',
                    capabilities=[
                        ConnectorCapability.BBOX_SEARCH,
                        ConnectorCapability.DATE_RANGE,
                        ConnectorCapability.COLLECTIONS,
                        ConnectorCapability.AUTHENTICATION,
                        ConnectorCapability.COG_SUPPORT,
                    ]
                )
                logger.debug('NASA EarthData connector registered')
            except Exception as exc:
                logger.warning(f'NASA EarthData connector unavailable: {exc}')

            # swisstopo SWISSEO S2-SR (open-data STAC)
            try:
                from ..connectors.swisstopo_stac import SwisstopoStacConnector
                swisstopo = SwisstopoStacConnector()
                self._connector_manager.register_connector(
                    'swisstopo_stac', swisstopo, 'swisstopo S2-SR',
                    capabilities=[
                        ConnectorCapability.BBOX_SEARCH,
                        ConnectorCapability.DATE_RANGE,
                        ConnectorCapability.CLOUD_COVER,
                        ConnectorCapability.COG_SUPPORT,
                    ]
                )
                logger.debug('swisstopo STAC connector registered')
            except Exception as exc:
                logger.warning(f'swisstopo STAC connector unavailable: {exc}')

            # Jilin-1 Gaofen (STAC-compatible endpoint)
            try:
                from ..connectors.jilin_gaofen_stac import JilinGaofenStacConnector
                jilin = JilinGaofenStacConnector()
                self._connector_manager.register_connector(
                    'jilin_gaofen_stac', jilin, 'Jilin-1 Gaofen',
                    capabilities=[
                        ConnectorCapability.BBOX_SEARCH,
                        ConnectorCapability.DATE_RANGE,
                        ConnectorCapability.CLOUD_COVER,
                        ConnectorCapability.COLLECTIONS,
                        ConnectorCapability.TEXT_SEARCH,
                        ConnectorCapability.COG_SUPPORT,
                    ]
                )
                logger.debug('Jilin-1 Gaofen connector registered')
            except Exception as exc:
                logger.warning(f'Jilin-1 Gaofen connector unavailable: {exc}')

            logger.info('ArchiveDockWidget: connector manager ready')

        except Exception as exc:
            logger.error(f'Failed to initialize connector manager: {exc}', exc_info=True)
            self._connector_manager = None

    # ------------------------------------------------------------------
    # Sensor type toggle (show/hide cloud cover)
    # ------------------------------------------------------------------

    def _on_sensor_changed(self, text: str):
        optical = text in ('All', 'Optical')
        self.cloud_slider.setEnabled(optical)
        self.cloud_label.setEnabled(optical)

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def _on_search_clicked(self):
        if not self._connector_manager:
            QMessageBox.warning(self, 'Connector Error',
                                'Connector manager not available. Check the log for details.')
            return

        selected_providers = [ARCHIVE_PROVIDERS[n]
                               for n, cb in self._provider_checks.items() if cb.isChecked()]
        if not selected_providers:
            QMessageBox.warning(self, 'No Provider', 'Please select at least one provider.')
            return

        ready_providers, skipped_providers = self._prepare_selected_connectors(selected_providers)
        if not ready_providers:
            skipped_text = ', '.join(skipped_providers) if skipped_providers else 'all selected providers'
            QMessageBox.warning(
                self,
                'Authentication Required',
                f'No selected provider is ready for search. Check credentials in Settings.\n\nSkipped: {skipped_text}'
            )
            return

        if not self.extent_widget:
            QMessageBox.warning(self, 'AOI Error', 'QgsExtentWidget is not available in this environment.')
            return

        try:
            current_map_crs = self.iface.mapCanvas().mapSettings().destinationCrs()
            widget_crs = self.extent_widget.outputCrs()
            if not widget_crs.isValid() or widget_crs.authid() != current_map_crs.authid():
                self.extent_widget.setOutputCrs(current_map_crs)

            extent = self.extent_widget.outputExtent()
            if not extent or extent.isEmpty():
                QMessageBox.warning(self, 'Missing AOI', 'Please define an Area of Interest before searching.')
                return

            if current_map_crs.authid() != 'EPSG:4326':
                tr = QgsCoordinateTransform(current_map_crs, QgsCoordinateReferenceSystem('EPSG:4326'), QgsProject.instance())
                extent = tr.transformBoundingBox(extent)

            bbox = [
                extent.xMinimum(),
                extent.yMinimum(),
                extent.xMaximum(),
                extent.yMaximum(),
            ]
            if bbox[0] >= bbox[2] or bbox[1] >= bbox[3]:
                QMessageBox.warning(self, 'Invalid BBox',
                                    'BBox must satisfy minLon < maxLon and minLat < maxLat.')
                return
        except Exception as exc:
            QMessageBox.warning(self, 'AOI Error', f'Could not read AOI from extent widget: {exc}')
            return

        date_from = self.date_start.date().toString('yyyy-MM-dd')
        date_to   = self.date_end.date().toString('yyyy-MM-dd')
        cloud_max = self.cloud_slider.value() / 100.0  # 0.0–1.0 for most connectors
        limit     = int(self.limit_combo.currentText())
        sensor    = self.sensor_combo.currentText()

        search_params = {
            'bbox':          bbox,
            'start_date':    date_from,
            'end_date':      date_to,
            'max_cloud_cover': cloud_max,
            'limit':         limit,
            'sensor_type':   sensor,
            'connector_ids': ready_providers,
        }

        if skipped_providers:
            self.status_label.setText(
                f'Ready to search. Skipping unauthenticated providers: {", ".join(skipped_providers)}'
            )
            self.status_label.setStyleSheet('color: #ffaa00; font-size: 10px;')

        self._start_search(search_params)

    def _prepare_selected_connectors(self, connector_ids: List[str]) -> Tuple[List[str], List[str]]:
        """Authenticate selected connectors when credentials are required."""
        ready: List[str] = []
        skipped: List[str] = []

        for connector_id in connector_ids:
            if self._authenticate_connector_if_needed(connector_id):
                ready.append(connector_id)
            else:
                skipped.append(connector_id)

        return ready, skipped

    def _authenticate_connector_if_needed(self, connector_id: str) -> bool:
        """Authenticate a connector from stored settings/secure storage when needed."""
        if not self._connector_manager:
            return False

        connector_info = getattr(self._connector_manager, '_connectors', {}).get(connector_id)
        if not connector_info:
            logger.warning(f'Archive search: connector not registered: {connector_id}')
            return False

        capabilities = connector_info.get('capabilities', [])
        needs_auth = any(getattr(cap, 'value', '') == 'authentication' for cap in capabilities)
        if not needs_auth:
            connector_info['authenticated'] = True
            return True

        credentials = self._get_credentials_for_connector(connector_id)
        if not credentials and connector_id != 'nasa_earthdata':
            logger.warning(f'Archive search: missing credentials for {connector_id}')
            return False

        try:
            authenticated = self._connector_manager.authenticate_connector(
                connector_id=connector_id,
                credentials=credentials,
            )
            return bool(authenticated)
        except Exception as exc:
            logger.warning(f'Archive search: authentication failed for {connector_id}: {exc}')
            return False

    def _get_credentials_for_connector(self, connector_id: str) -> Optional[Dict[str, Any]]:
        """Read provider credentials from secure storage/QSettings."""
        if connector_id == 'planet':
            planet_creds = self.secure_storage.get_credentials('planet') if self.secure_storage else {}
            planet_creds = planet_creds or {}
            token = (planet_creds.get('access_token') or '').strip()

            settings = QSettings()
            api_base_url = str(
                settings.value('altair/planet_api_base_url', 'https://services.sentinel-hub.com')
            ).strip()

            if not token:
                return {}

            return {
                'access_token': token,
                'api_base_url': api_base_url,
            }

        if connector_id == 'oneatlas' and self.secure_storage:
            return self.secure_storage.get_credentials('oneatlas')

        if connector_id == 'copernicus_stac' and self.secure_storage:
            return self.secure_storage.get_credentials('copernicus')

        if connector_id == 'capella_stac' and self.secure_storage:
            return self.secure_storage.get_credentials('capella') or {}

        if connector_id == 'iceye_stac':
            token = ''
            if self.secure_storage:
                iceye_creds = self.secure_storage.get_credentials('iceye') or {}
                token = (iceye_creds.get('access_token') or '').strip()

            settings = QSettings()
            api_base_url = str(settings.value('altair/iceye_endpoint', 'https://api.iceye.com')).strip()
            contract_id = str(settings.value('altair/iceye_contract_id', '')).strip()
            collections = str(settings.value('altair/iceye_collections', '')).strip()

            if not token:
                return {}

            return {
                'access_token': token,
                'api_base_url': api_base_url,
                'contract_id': contract_id or None,
                'collections': collections or None,
            }

        if connector_id == 'umbra_stac':
            token = ''
            client_id = ''
            client_secret = ''
            if self.secure_storage:
                umbra_creds = self.secure_storage.get_credentials('umbra') or {}
                token = (umbra_creds.get('access_token') or '').strip()
                client_id = (umbra_creds.get('client_id') or '').strip()
                client_secret = (umbra_creds.get('client_secret') or '').strip()

            settings = QSettings()
            api_base_url = str(settings.value('altair/umbra_api_base_url', 'https://api.canopy.umbra.space')).strip()

            if not token and not (client_id and client_secret):
                return {}

            return {
                'access_token': token,
                'client_id': client_id or None,
                'client_secret': client_secret or None,
                'api_base_url': api_base_url,
            }

        if connector_id == 'nasa_earthdata':
            username = ''
            password = ''
            access_token = ''
            if self.secure_storage:
                nasa_creds = self.secure_storage.get_credentials('nasa_earthdata') or {}
                username = (nasa_creds.get('username') or '').strip()
                password = (nasa_creds.get('password') or '').strip()
                access_token = (
                    nasa_creds.get('access_token')
                    or nasa_creds.get('token')
                    or ''
                ).strip()

            settings = QSettings()
            if not username:
                username = str(
                    settings.value(
                        'altair/nasa_earthdata_username',
                        settings.value('altair/nasa_username', ''),
                    )
                ).strip()
            if not password:
                password = str(
                    settings.value(
                        'altair/nasa_earthdata_password',
                        settings.value('altair/nasa_password', ''),
                    )
                ).strip()
            if not access_token:
                access_token = str(
                    settings.value(
                        'altair/nasa_earthdata_token',
                        settings.value('altair/nasa_access_token', ''),
                    )
                ).strip()

            if not (access_token or (username and password)):
                return {}

            return {
                'username': username or None,
                'password': password or None,
                'access_token': access_token or None,
            }

        return {}

    def _start_search(self, params: Dict[str, Any]):
        if not QGIS_AVAILABLE:
            self._run_search_direct(params)
            return

        task = ArchiveSearchTask(self._connector_manager, params)
        self._active_task = task
        task.taskCompleted.connect(lambda: self._on_search_done(task))
        task.taskTerminated.connect(lambda: self._on_search_error(task))

        self.search_btn.setEnabled(False)
        self.clear_btn.setEnabled(False)
        self._start_spinner()
        self.status_label.setText('Searching …')
        self.status_label.setStyleSheet('color: #88ccff; font-size: 10px;')

        QgsApplication.taskManager().addTask(task)

    def _run_search_direct(self, params: Dict[str, Any]):
        """Synchronous fallback when QgsTask is unavailable."""
        try:
            task = ArchiveSearchTask(self._connector_manager, params)
            if not task.run():
                raise RuntimeError(task.error_message or 'Search failed')
            self._search_results = task.results or []
            self._populate_results()
        except Exception as exc:
            logger.error(f'Sync search failed: {exc}', exc_info=True)
            self.status_label.setText(f'Search error: {exc}')
            self.status_label.setStyleSheet('color: #ff6b6b; font-size: 10px;')

    def _on_search_done(self, task: ArchiveSearchTask):
        self._stop_spinner()
        self.search_btn.setEnabled(True)
        self._search_results = task.results
        self._populate_results()

    def _on_search_error(self, task: ArchiveSearchTask):
        self._stop_spinner()
        self.search_btn.setEnabled(True)
        msg = task.error_message or 'Unknown error'
        self.status_label.setText(f'Search failed: {msg}')
        self.status_label.setStyleSheet('color: #ff6b6b; font-size: 10px;')

    # ------------------------------------------------------------------
    # Results population
    # ------------------------------------------------------------------

    def _populate_results(self):
        self.results_table.setSortingEnabled(False)
        self.results_table.setRowCount(0)

        results = self._search_results
        count = len(results)
        self.result_count_label.setText(f'{count} result(s) found')

        for row_idx, item in enumerate(results):
            props = item.get('properties', item)

            provider  = str(item.get('_provider', props.get('provider', '')))
            date_str  = str(props.get('datetime', props.get('date', '')))[:10]
            satellite = str(props.get('platform', props.get('satellite_id', props.get('constellation', ''))))
            cloud_raw = props.get('eo:cloud_cover', props.get('cloud_cover', ''))
            cloud_str = f'{float(cloud_raw):.1f}' if cloud_raw != '' else 'N/A'
            gsd_raw   = props.get('gsd', props.get('eo:gsd', ''))
            gsd_str   = f'{float(gsd_raw):.1f}' if gsd_raw != '' else 'N/A'
            scene_id  = str(item.get('id', props.get('id', '')))

            self.results_table.insertRow(row_idx)
            provider_item = QTableWidgetItem(provider)
            provider_item.setData(Qt.UserRole, row_idx)
            self.results_table.setItem(row_idx, self._COL_PROVIDER,  provider_item)
            self.results_table.setItem(row_idx, self._COL_DATE,      QTableWidgetItem(date_str))
            self.results_table.setItem(row_idx, self._COL_SATELLITE, QTableWidgetItem(satellite))
            cloud_item = _NumItem(cloud_str)
            cloud_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.results_table.setItem(row_idx, self._COL_CLOUD, cloud_item)
            gsd_item = _NumItem(gsd_str)
            gsd_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.results_table.setItem(row_idx, self._COL_GSD, gsd_item)
            self.results_table.setItem(row_idx, self._COL_ID, QTableWidgetItem(scene_id))

        self.results_table.setSortingEnabled(True)
        self.clear_btn.setEnabled(count > 0)

        self.status_label.setText(f'Search complete — {count} scene(s)')
        self.status_label.setStyleSheet('color: #00ffbf; font-size: 10px;')

        if count > 0:
            self._refresh_footprints_layer()

    # ------------------------------------------------------------------
    # Footprints layer
    # ------------------------------------------------------------------

    def _refresh_footprints_layer(self):
        if not QGIS_AVAILABLE or not self._search_results:
            return
        try:
            layer_id = 'AltairArchiveFootprints'
            existing = QgsProject.instance().mapLayersByName('Archive Footprints')
            if existing:
                QgsProject.instance().removeMapLayer(existing[0].id())

            layer = QgsVectorLayer('Polygon?crs=EPSG:4326', 'Archive Footprints', 'memory')
            pr = layer.dataProvider()

            fields = QgsFields()
            fields.append(QgsField('index',    QVariant.Int))
            fields.append(QgsField('provider', QVariant.String))
            fields.append(QgsField('date',     QVariant.String))
            fields.append(QgsField('id',       QVariant.String))
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
                feat.setAttribute('index',    idx)
                feat.setAttribute('provider', str(item.get('_provider', '')))
                feat.setAttribute('date',     str(props.get('datetime', ''))[:10])
                feat.setAttribute('id',       str(item.get('id', '')))
                features.append(feat)

            pr.addFeatures(features)
            layer.updateExtents()

            # Normal (unselected) footprints — blue, semi-transparent
            sym_normal = QgsFillSymbol.createSimple({
                'color':         '0,120,255,60',
                'outline_color': '#0078ff',
                'outline_width': '0.4',
            })
            # Selected footprints — yellow, semi-transparent (map still visible beneath)
            sym_selected = QgsFillSymbol.createSimple({
                'color':         '255,220,0,120',
                'outline_color': '#ffcc00',
                'outline_width': '0.7',
            })

            root_rule = QgsRuleBasedRenderer.Rule(None)
            sel_rule = QgsRuleBasedRenderer.Rule(
                sym_selected, filterExp='is_selected()', label='Selected'
            )
            else_rule = QgsRuleBasedRenderer.Rule(
                sym_normal, elseRule=True, label='Default'
            )
            root_rule.appendChild(sel_rule)
            root_rule.appendChild(else_rule)
            layer.setRenderer(QgsRuleBasedRenderer(root_rule))

            QgsProject.instance().addMapLayer(layer)
            self._footprints_layer = layer
            self._footprints_layer.selectionChanged.connect(self._on_layer_selection_changed)
            self._footprints_layer.willBeDeleted.connect(self._on_footprints_layer_deleted)
            self._build_feature_id_mapping()
            self.select_from_map_btn.setEnabled(True)
            logger.debug(f'Archive footprints layer: {len(features)} features')
        except Exception as exc:
            logger.warning(f'Footprints layer update failed: {exc}')

    @staticmethod
    def _item_to_geometry(item: Dict) -> Optional[Any]:
        """Convert a STAC item to a QgsGeometry polygon."""
        if not QGIS_AVAILABLE:
            return None
        try:
            geom_raw = item.get('geometry') or {}
            gtype = (geom_raw.get('type') or '').lower()
            coords = geom_raw.get('coordinates')

            if gtype == 'polygon' and coords:
                pts = [QgsPointXY(c[0], c[1]) for c in coords[0]]
                return QgsGeometry.fromPolygonXY([pts])

            if gtype == 'multipolygon' and coords:
                polygons = [[QgsPointXY(c[0], c[1]) for c in ring]
                             for poly in coords for ring in poly]
                return QgsGeometry.fromMultiPolygonXY([[p] for p in polygons])

            # Fallback: bbox
            bbox = item.get('bbox')
            if bbox and len(bbox) >= 4:
                min_lon, min_lat, max_lon, max_lat = bbox[:4]
                pts = [
                    QgsPointXY(min_lon, min_lat),
                    QgsPointXY(max_lon, min_lat),
                    QgsPointXY(max_lon, max_lat),
                    QgsPointXY(min_lon, max_lat),
                    QgsPointXY(min_lon, min_lat),
                ]
                return QgsGeometry.fromPolygonXY([pts])
        except Exception:
            pass
        return None

    # ------------------------------------------------------------------
    # Table ↔ layer selection sync
    # ------------------------------------------------------------------

    def _is_footprints_layer_valid(self) -> bool:
        if self._footprints_layer is None:
            return False
        try:
            _ = self._footprints_layer.id()
            return True
        except RuntimeError:
            self._footprints_layer = None
            return False

    def _build_feature_id_mapping(self):
        self._feature_id_to_result_index = {}
        self._result_index_to_feature_id = {}

        if not self._is_footprints_layer_valid():
            return

        try:
            for feature in self._footprints_layer.getFeatures():
                fid = feature.id()
                result_index = feature.attribute('index')
                if result_index is None:
                    continue
                result_index = int(result_index)
                self._feature_id_to_result_index[fid] = result_index
                self._result_index_to_feature_id[result_index] = fid
        except Exception as exc:
            logger.warning(f'Feature mapping build failed: {exc}')

    def _on_table_selection_changed(self):
        selected_rows = self.results_table.selectionModel().selectedRows()
        rows = [idx.row() for idx in selected_rows]
        has_sel = bool(rows)
        self.zoom_btn.setEnabled(has_sel)
        self.quicklook_btn.setEnabled(has_sel and len(rows) == 1)
        self.load_cog_btn.setEnabled(has_sel)
        self.order_btn.setEnabled(has_sel and len(rows) == 1)

        if len(rows) == 1:
            row = next(iter(rows))
            item = self._search_results[row] if row < len(self._search_results) else None
            self._update_quicklook_preview(item)
        else:
            self._update_quicklook_preview(None)

        if not self._updating_selection and self._is_footprints_layer_valid():
            self._updating_selection = True
            try:
                selected_indices: List[int] = []
                for model_index in selected_rows:
                    item = self.results_table.item(model_index.row(), self._COL_PROVIDER)
                    if not item:
                        continue
                    result_index = item.data(Qt.UserRole)
                    if result_index is not None:
                        selected_indices.append(int(result_index))

                selected_feature_ids: List[int] = []
                for result_index in selected_indices:
                    feature_id = self._result_index_to_feature_id.get(result_index)
                    if feature_id is not None:
                        selected_feature_ids.append(feature_id)

                self._footprints_layer.selectByIds(selected_feature_ids)
            except Exception as exc:
                logger.warning(f'Failed syncing table selection to map: {exc}')
            finally:
                self._updating_selection = False

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

            selection_model = self.results_table.selectionModel()
            selection_model.clearSelection()

            first_row = None
            for row_idx in range(self.results_table.rowCount()):
                item = self.results_table.item(row_idx, self._COL_PROVIDER)
                if not item:
                    continue
                table_result_index = item.data(Qt.UserRole)
                if table_result_index in selected_result_indices:
                    selection_model.select(
                        self.results_table.model().index(row_idx, 0),
                        QItemSelectionModel.Select | QItemSelectionModel.Rows,
                    )
                    if first_row is None:
                        first_row = row_idx

            if first_row is not None:
                self.results_table.scrollTo(
                    self.results_table.model().index(first_row, 0),
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
        self.select_from_map_btn.setEnabled(False)
        if self.select_from_map_btn.isChecked():
            self.select_from_map_btn.setChecked(False)

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

    # ------------------------------------------------------------------
    # Action handlers
    # ------------------------------------------------------------------

    def _zoom_to_selected(self):
        rows = sorted(set(idx.row() for idx in self.results_table.selectedIndexes()))
        if not rows or not QGIS_AVAILABLE:
            return
        try:
            from qgis.core import QgsRectangle
            combined = None
            for row in rows:
                item = self._search_results[row] if row < len(self._search_results) else None
                if item is None:
                    continue
                bbox = item.get('bbox')
                if bbox and len(bbox) >= 4:
                    rect = QgsRectangle(bbox[0], bbox[1], bbox[2], bbox[3])
                    combined = rect if combined is None else combined.combineExtentWith(rect)
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
        rows = sorted(set(idx.row() for idx in self.results_table.selectedIndexes()))
        if not rows:
            return
        item = self._search_results[rows[0]] if rows[0] < len(self._search_results) else None
        if not item:
            return

        url = self._extract_quicklook_url(item)
        if not url:
            self.status_label.setText('No quicklook URL available for this scene.')
            self.status_label.setStyleSheet(f'color: {self._LABEL_COLOR}; font-size: 10px;')
            return

        if self._try_load_quicklook_georeferenced(item, url):
            return

        # Fallback: keep the preview in panel (already updated on row selection).
        self.status_label.setText('Quicklook shown in panel (georeferenced map portrayal not available).')
        self.status_label.setStyleSheet(f'color: {self._LABEL_COLOR}; font-size: 10px;')

    def _extract_quicklook_url(self, item: Dict[str, Any]) -> Optional[str]:
        """Extract quicklook/thumbnail URL from a STAC item."""
        assets = item.get('assets', {})
        for key in ('thumbnail', 'quicklook', 'overview', 'preview'):
            asset = assets.get(key, {})
            if isinstance(asset, dict):
                href = asset.get('href')
                if href:
                    return str(href)
            elif isinstance(asset, str):
                return asset

        links = item.get('links', [])
        for link in links:
            if link.get('rel') in ('thumbnail', 'preview', 'quicklook') and link.get('href'):
                return str(link.get('href'))

        return None

    def _fetch_quicklook_bytes(self, url: str, timeout_s: int = 15) -> Optional[bytes]:
        """Fetch quicklook bytes using QGIS network manager (proxy-aware)."""
        if not QGIS_AVAILABLE:
            return None
        try:
            request = QNetworkRequest(QUrl(url))
            request.setRawHeader(b'Accept', b'image/*,*/*;q=0.8')
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

    def _update_quicklook_preview(self, item: Optional[Dict[str, Any]]):
        """Update in-dock quicklook preview panel."""
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

        payload = self._fetch_quicklook_bytes(url)
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
        if ext == '.tif' or ext == '.tiff':
            return '.tfw'
        if ext == '.jp2':
            return '.j2w'
        return '.wld'

    def _try_load_quicklook_georeferenced(self, item: Dict[str, Any], url: str) -> bool:
        """Try to portray quicklook as georeferenced raster in map viewer."""
        if not QGIS_AVAILABLE:
            return False

        scene_id = str(item.get('id', 'quicklook'))[:30]

        # Fast path: georeferenced raster over HTTP
        if any(token in url.lower() for token in ('.tif', '.tiff', '.jp2', 'geotiff')):
            uri = f'/vsicurl/{url}' if url.startswith('http') else url
            layer = QgsRasterLayer(uri, f'{scene_id}_quicklook')
            if layer.isValid():
                QgsProject.instance().addMapLayer(layer)
                self.status_label.setText('Quicklook loaded as georeferenced raster in map.')
                self.status_label.setStyleSheet('color: #00ffbf; font-size: 10px;')
                return True

        # Fallback: build worldfile from bbox for image quicklooks
        bbox = item.get('bbox')
        if not bbox or len(bbox) < 4:
            return False

        payload = self._fetch_quicklook_bytes(url)
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

        fd, image_path = tempfile.mkstemp(prefix='altair_quicklook_', suffix=ext)
        os.close(fd)
        with open(image_path, 'wb') as fout:
            fout.write(payload)

        worldfile_path = os.path.splitext(image_path)[0] + self._quicklook_worldfile_ext(ext)
        with open(worldfile_path, 'w', encoding='utf-8') as wf:
            wf.write(f"{pixel_x}\n")
            wf.write("0.0\n")
            wf.write("0.0\n")
            wf.write(f"{pixel_y}\n")
            wf.write(f"{x_origin}\n")
            wf.write(f"{y_origin}\n")

        prj_path = os.path.splitext(image_path)[0] + '.prj'
        try:
            with open(prj_path, 'w', encoding='utf-8') as prj:
                prj.write(QgsCoordinateReferenceSystem('EPSG:4326').toWkt())
        except Exception:
            pass

        layer = QgsRasterLayer(image_path, f'{scene_id}_quicklook')
        if not layer.isValid():
            return False

        # Explicitly assign WGS84 so QGIS/KADAS reprojects to the map CRS correctly,
        # regardless of whether the companion .prj file is honoured by the host application.
        wgs84 = QgsCoordinateReferenceSystem('EPSG:4326')
        layer.setCrs(wgs84)

        QgsProject.instance().addMapLayer(layer)
        self.status_label.setText('Quicklook georeferenced from bbox and loaded in map.')
        self.status_label.setStyleSheet('color: #00ffbf; font-size: 10px;')
        return True

    # Asset keys to try in priority order when loading a COG layer.
    # Copernicus Dataspace uses keys like TCI / TCI_10m / B04_10m;
    # other providers use visual, analytic, data, cog, image, B_TCI.
    _COG_ASSET_PRIORITY = (
        'visual', 'TCI', 'TCI_10m', 'B_TCI',
        'B04_10m', 'B04', 'B03_10m', 'B03',
        'data', 'analytic', 'cog', 'image',
    )
    # Media types that identify raster COG/GeoTIFF/JP2 assets.
    _COG_MEDIA_TYPES = {
        'image/tiff', 'image/geotiff', 'image/jp2',
        'image/vnd.stac.geotiff; cloud-optimized=true',
        'image/x.geotiff',
    }

    def _pick_cog_href(self, assets: Dict) -> Optional[str]:
        """Return the best COG href from a STAC assets dict."""
        # 1. Priority key list
        for key in self._COG_ASSET_PRIORITY:
            a = assets.get(key)
            if not a:
                continue
            href = a.get('href') if isinstance(a, dict) else a if isinstance(a, str) else None
            if href and not href.endswith('.SAFE') and not href.endswith('/'):
                return href

        # 2. Fallback: first asset whose media type indicates a raster
        for key, a in assets.items():
            if key == 'thumbnail':
                continue
            if not isinstance(a, dict):
                continue
            media_type = (a.get('type') or '').lower()
            href = a.get('href', '')
            if any(mt in media_type for mt in self._COG_MEDIA_TYPES):
                if href and not href.endswith('.SAFE') and not href.endswith('/'):
                    return href

        # 3. Last resort: any .tif / .jp2 href that is not the SAFE product folder
        for key, a in assets.items():
            if key == 'thumbnail':
                continue
            href = (a.get('href') if isinstance(a, dict) else a if isinstance(a, str) else '') or ''
            if href.lower().endswith(('.tif', '.tiff', '.jp2')) and not href.endswith('.SAFE'):
                return href

        return None

    def _gdal_set_bearer(self, token: Optional[str]) -> None:
        """Configure GDAL HTTP Authorization header for /vsicurl/ requests."""
        if not token:
            return
        try:
            from osgeo import gdal
            gdal.SetConfigOption('GDAL_HTTP_HEADERS', f'Authorization: Bearer {token}')
        except Exception as exc:
            logger.debug(f'GDAL bearer config skipped: {exc}')

    def _gdal_clear_bearer(self) -> None:
        """Remove the custom GDAL HTTP Authorization header."""
        try:
            from osgeo import gdal
            gdal.SetConfigOption('GDAL_HTTP_HEADERS', None)
        except Exception:
            pass

    def _gdal_set_aws_s3(self, access_id: str, secret: str, endpoint: str = 'eodata.dataspace.copernicus.eu') -> None:
        try:
            from osgeo import gdal
            gdal.SetConfigOption('AWS_ACCESS_KEY_ID', access_id)
            gdal.SetConfigOption('AWS_SECRET_ACCESS_KEY', secret)
            gdal.SetConfigOption('AWS_S3_ENDPOINT', endpoint)
            gdal.SetConfigOption('AWS_HTTPS', 'YES')
            gdal.SetConfigOption('AWS_VIRTUAL_HOSTING', 'FALSE')
        except Exception as exc:
            logger.debug(f'GDAL AWS S3 config skipped: {exc}')

    def _gdal_clear_aws_s3(self) -> None:
        try:
            from osgeo import gdal
            gdal.SetConfigOption('AWS_ACCESS_KEY_ID', None)
            gdal.SetConfigOption('AWS_SECRET_ACCESS_KEY', None)
            gdal.SetConfigOption('AWS_S3_ENDPOINT', None)
            gdal.SetConfigOption('AWS_HTTPS', None)
            gdal.SetConfigOption('AWS_VIRTUAL_HOSTING', None)
        except Exception:
            pass

    def _build_copernicus_vsis3_uri(self, href: str) -> Optional[str]:
        try:
            parsed = urlparse(href)
            if parsed.scheme != 'https' or parsed.netloc.lower() != 'eodata.dataspace.copernicus.eu':
                return None
            path = (parsed.path or '').lstrip('/')
            if not path:
                return None
            return f'/vsis3/eodata/{path}'
        except Exception:
            return None

    def _get_connector_instance(self, item: Dict[str, Any]) -> Optional[Any]:
        source = item.get('_source', '')
        if not source or not self._connector_manager:
            return None
        connector_info = getattr(self._connector_manager, '_connectors', {}).get(source, {})
        return connector_info.get('instance') if connector_info else None

    def _get_bearer_for_item(self, item: Dict) -> Optional[str]:
        """Return a valid Bearer token for the given result item, if available."""
        source = item.get('_source', '')
        if not source or not self._connector_manager:
            return None
        try:
            connector_info = getattr(self._connector_manager, '_connectors', {}).get(source, {})
            connector = connector_info.get('instance') if connector_info else None
            if connector is None:
                return None
            token = getattr(connector, '_access_token', None)
            return str(token) if token else None
        except Exception:
            return None

    def _load_cog(self):
        rows = sorted(set(idx.row() for idx in self.results_table.selectedIndexes()))
        if not rows or not QGIS_AVAILABLE:
            return
        loaded = 0
        errors: List[str] = []
        for row in rows[:5]:  # cap at 5 to avoid flooding
            if row >= len(self._search_results):
                continue
            item = self._search_results[row]
            assets = item.get('assets', {})
            href = self._pick_cog_href(assets)
            if not href:
                logger.warning(f'No COG asset found for row {row}; available keys: {list(assets.keys())}')
                errors.append(str(item.get('id', row))[:20])
                continue
            scene_id = str(item.get('id', f'archive_{row}'))[:20]
            uri = f'/vsicurl/{href}' if href.startswith('http') else href

            # Inject Bearer token for providers that require HTTP auth (e.g. Copernicus)
            bearer = self._get_bearer_for_item(item)
            if bearer:
                self._gdal_set_bearer(bearer)
            try:
                lyr = QgsRasterLayer(uri, scene_id)
                if not lyr.isValid() and href.startswith('http'):
                    lyr = QgsRasterLayer(href, scene_id)

                if not lyr.isValid() and item.get('_source') == 'copernicus_stac':
                    connector = self._get_connector_instance(item)
                    if connector and hasattr(connector, 'get_s3_credentials'):
                        creds = connector.get_s3_credentials()
                        access_id = (creds or {}).get('access_id') if isinstance(creds, dict) else None
                        secret = (creds or {}).get('secret') if isinstance(creds, dict) else None
                        s3_uri = self._build_copernicus_vsis3_uri(href)

                        if access_id and secret and s3_uri:
                            self._gdal_set_aws_s3(access_id, secret)
                            try:
                                lyr = QgsRasterLayer(s3_uri, scene_id)
                            finally:
                                self._gdal_clear_aws_s3()

                            if hasattr(connector, 'delete_s3_credentials'):
                                try:
                                    connector.delete_s3_credentials(access_id)
                                except Exception as exc:
                                    logger.debug(f'Copernicus S3 credentials cleanup failed: {exc}')

                if lyr.isValid():
                    QgsProject.instance().addMapLayer(lyr)
                    loaded += 1
                else:
                    logger.warning(f'Invalid COG layer for {scene_id}: {uri}')
                    errors.append(scene_id)
            finally:
                if bearer:
                    self._gdal_clear_bearer()

        if loaded:
            self.status_label.setText(f'{loaded} COG layer(s) added to map.')
            self.status_label.setStyleSheet('color: #00ffbf; font-size: 10px;')
        else:
            msg = 'No valid COG layer loaded.'
            if errors:
                msg += f' Failed: {", ".join(errors[:3])}'
            self.status_label.setText(msg)
            self.status_label.setStyleSheet('color: #ff6b6b; font-size: 10px;')

    def _on_order_clicked(self):
        rows = sorted(set(idx.row() for idx in self.results_table.selectedIndexes()))
        if not rows:
            return
        item = self._search_results[rows[0]] if rows[0] < len(self._search_results) else None
        if item:
            self.order_requested.emit(item)

    # ------------------------------------------------------------------
    # Clear results
    # ------------------------------------------------------------------

    def _on_clear_results(self):
        self._search_results.clear()
        self.results_table.setRowCount(0)
        self.result_count_label.setText('No search performed')
        self.clear_btn.setEnabled(False)
        self.select_from_map_btn.setEnabled(False)
        if self.select_from_map_btn.isChecked():
            self.select_from_map_btn.setChecked(False)
        self.zoom_btn.setEnabled(False)
        self.quicklook_btn.setEnabled(False)
        self.load_cog_btn.setEnabled(False)
        self.order_btn.setEnabled(False)
        self._feature_id_to_result_index = {}
        self._result_index_to_feature_id = {}
        self.status_label.setText('Results cleared.')
        self.status_label.setStyleSheet(f'color: {self._LABEL_COLOR}; font-size: 10px;')
        if QGIS_AVAILABLE and self._footprints_layer:
            try:
                QgsProject.instance().removeMapLayer(self._footprints_layer.id())
            except Exception:
                pass
            self._footprints_layer = None

    # ------------------------------------------------------------------
    # Spinner animation
    # ------------------------------------------------------------------

    def _start_spinner(self):
        self._spinner_state = 0
        self._spinner_timer = QTimer(self)
        self._spinner_timer.timeout.connect(self._tick_spinner)
        self._spinner_timer.start(300)

    def _tick_spinner(self):
        frame = self._spinner_frames[self._spinner_state % len(self._spinner_frames)]
        self.search_btn.setText(frame)
        self._spinner_state += 1

    def _stop_spinner(self):
        if self._spinner_timer:
            self._spinner_timer.stop()
            self._spinner_timer = None
        self.search_btn.setText('Search')
        self.search_btn.setEnabled(True)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._refresh_quicklook_preview_pixmap()
