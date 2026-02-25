"""
Altair EO Data Main Dock Widget
"""
import json
from typing import List, Dict, Any

from qgis.PyQt.QtWidgets import (
    QDockWidget, QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QLineEdit, QPushButton, QComboBox, QSpinBox, QCheckBox,
    QGroupBox, QTableWidget, QTableWidgetItem, QHeaderView,
    QAbstractItemView, QSplitter, QMessageBox, QDateEdit, QApplication,
    QProgressBar, QSlider, QFileDialog
)
from qgis.PyQt.QtCore import Qt, QDate, QSettings, QTimer, QModelIndex, QVariant
from qgis.PyQt.QtGui import QFont, QColor
from ..logger import get_logger
from .footprint_tool import FootprintSelectionTool

logger = get_logger('gui.dock')

try:
    from ..secrets.secure_storage import get_secure_storage
except ImportError:
    # Fallback if secure_storage not available
    logger.warning("Secure storage not available, using fallback")
    def get_secure_storage():
        return None

try:
    from qgis.core import (
        QgsProject,
        QgsRasterLayer,
        QgsVectorLayer,
        QgsCoordinateReferenceSystem,
        QgsCoordinateTransform,
        QgsRectangle,
        QgsGeometry,
        QgsPointXY,
        QgsWkbTypes,
        QgsFeature,
        QgsFields,
        QgsField,
        QgsFillSymbol,
        QgsJsonUtils,
        QgsTask,
        QgsApplication
    )
    from qgis.gui import QgsExtentWidget
    from qgis.PyQt.QtCore import QVariant
    QGIS_AVAILABLE = True
except ImportError:
    # Fallback for environments without QGIS
    logger.warning("QGIS core modules not available, using fallback")
    QgsProject = None
    QgsRasterLayer = None
    QgsVectorLayer = None
    QgsCoordinateReferenceSystem = None
    QgsCoordinateTransform = None
    QgsRectangle = None
    QgsGeometry = None
    QgsPointXY = None
    QgsWkbTypes = None
    QgsFeature = None
    QgsFields = None
    QgsField = None
    QgsFillSymbol = None
    QVariant = None
    QgsExtentWidget = None
    QgsJsonUtils = None
    QgsTask = None
    QgsApplication = None
    QGIS_AVAILABLE = False


class NumericTableWidgetItem(QTableWidgetItem):
    """Custom table item that sorts numerically.
    
    Similar to kadas-vantor-plugin pattern for proper numeric sorting.
    """
    def __lt__(self, other):
        try:
            return float(self.text()) < float(other.text())
        except ValueError:
            return super().__lt__(other)


class SearchTask(QgsTask):
    """Background task for STAC catalog search.
    
    Similar to kadas-stac-plugin ContentFetcherTask pattern.
    Runs search in background thread, keeping UI responsive.
    """
    
    def __init__(self, connector_manager, search_params, description='STAC Search'):
        """Initialize search task.
        
        Args:
            connector_manager: ConnectorManager instance
            search_params: Dict with search parameters (bbox, dates, cloud, collection, limit)
            description: Task description for UI
        """
        super().__init__(description, QgsTask.CanCancel)
        self.connector_manager = connector_manager
        self.search_params = search_params
        self.results = None
        self.next_token = None
        self.error_message = None
        
    def run(self):
        """Execute search in background thread.
        
        Returns:
            bool: True if successful, False if error
        """
        try:
            logger.debug(f"SearchTask starting with params: {self.search_params}")
            
            # Execute search via ConnectorManager
            self.results, self.next_token = self.connector_manager.search(**self.search_params)
            
            logger.info(f"SearchTask completed: {len(self.results) if self.results else 0} results")
            return True
            
        except Exception as e:
            logger.error(f"SearchTask failed: {e}", exc_info=True)
            self.error_message = str(e)
            return False
    
    def finished(self, result):
        """Called when task completes (runs in main thread).
        
        Override this in subclass or connect to taskCompleted signal.
        """
        if result:
            logger.debug("SearchTask finished successfully")
        else:
            logger.error(f"SearchTask finished with error: {self.error_message}")


class AllSourcesSearchTask(QgsTask):
    """Background task for aggregated multi-source search.
    
    Searches across all authenticated connectors and merges results.
    """
    
    def __init__(self, connector_manager, search_params, description='All Sources Search'):
        """Initialize aggregated search task.
        
        Args:
            connector_manager: ConnectorManager instance
            search_params: Dict with search parameters (bbox, dates, cloud, collection, limit)
            description: Task description for UI
        """
        super().__init__(description, QgsTask.CanCancel)
        self.connector_manager = connector_manager
        self.search_params = search_params
        self.results = None
        self.next_token = None
        self.error_message = None
        
    def run(self):
        """Execute aggregated search in background thread.
        
        Returns:
            bool: True if successful, False if error
        """
        try:
            logger.debug(f"AllSourcesSearchTask starting with params: {self.search_params}")
            
            # Execute aggregated search via ConnectorManager
            self.results, self.next_token = self.connector_manager.search_all_sources(**self.search_params)
            
            logger.info(f"AllSourcesSearchTask completed: {len(self.results) if self.results else 0} total results from all sources")
            return True
            
        except Exception as e:
            logger.error(f"AllSourcesSearchTask failed: {e}", exc_info=True)
            self.error_message = str(e)
            return False
    
    def finished(self, result):
        """Called when task completes (runs in main thread).
        
        Override this in subclass or connect to taskCompleted signal.
        """
        if result:
            logger.debug("AllSourcesSearchTask finished successfully")
        else:
            logger.error(f"AllSourcesSearchTask finished with error: {self.error_message}")


# KADAS-specific imports
try:
    from kadas.kadasgui import (
        KadasItemLayer,
        KadasMapCanvasItemManager
    )
    KADAS_AVAILABLE = True
    logger.info("KADAS modules loaded successfully")
except ImportError:
    logger.warning("KADAS modules not available, using standard QGIS widgets")
    KadasItemLayer = None
    KadasMapCanvasItemManager = None
    KADAS_AVAILABLE = False


class AltairDockWidget(QDockWidget):
    """Main dockable panel for browsing EO data."""

    def __init__(self, iface, parent=None):
        """Initialize the dock widget"""
        super().__init__("Altair EO", parent)
        logger.info("Initializing Altair dock widget")
        
        self.iface = iface
        self.settings = QSettings()
        self.secure_storage = get_secure_storage()  # Initialize secure storage
        self._search_results = []  # Store search results
        self._loaded_layers = []  # Track loaded layers
        self.footprints_layer = None  # Vector layer for search results
        self._updating_selection = False  # Prevent selection feedback loops
        self._feature_id_to_result_index = {}  # Map layer feature IDs to result indices
        self._result_index_to_feature_id = {}  # Map result indices to layer feature IDs
        self.selection_tool = None  # Custom map tool for interactive selection
        self._previous_map_tool = None  # Store previous tool when entering selection mode
        
        # Setup dockable behavior - kadas-vantor pattern
        self.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        
        # Check GDAL capabilities for format support
        self._check_gdal_support()
        
        self._setup_ui()
        logger.debug("Dock widget UI setup completed")

    def _check_gdal_support(self):
        """Check GDAL format support and log capabilities.
        
        Verifies support for:
        - GeoTIFF (required for most data)
        - JPEG2000 (required for Copernicus/Sentinel data)
        - VSICURL (required for S3/HTTP streaming)
        """
        if not QGIS_AVAILABLE:
            logger.warning("QGIS not available - cannot check GDAL support")
            return
        
        try:
            from osgeo import gdal
            
            # Check JPEG2000 drivers
            jp2_drivers = ['JP2OpenJPEG', 'JP2KAK', 'JP2ECW', 'JPEG2000']
            jp2_available = False
            jp2_driver_found = None
            
            for driver_name in jp2_drivers:
                driver = gdal.GetDriverByName(driver_name)
                if driver:
                    jp2_available = True
                    jp2_driver_found = driver_name
                    break
            
            if jp2_available:
                logger.info(f"✓ GDAL JPEG2000 support available (driver: {jp2_driver_found})")
            else:
                logger.warning("⚠ GDAL JPEG2000 support not available - Copernicus/Sentinel data may fail to load")
                logger.warning("  To fix: Ensure GDAL is compiled with OpenJPEG support")
            
            # Check GeoTIFF driver
            gtiff_driver = gdal.GetDriverByName('GTiff')
            if gtiff_driver:
                logger.info("✓ GDAL GeoTIFF support available")
            else:
                logger.error("✗ GDAL GeoTIFF support not available - plugin will not function correctly")
            
            # Check VSICURL support (for S3/HTTP streaming)
            has_vsicurl = '/vsicurl/' in gdal.GetConfigOption('GDAL_DRIVER_PATH', '') or True  # Always available in modern GDAL
            if has_vsicurl:
                logger.info("✓ GDAL VSICURL support available (S3/HTTP streaming)")
            
            # Log GDAL version
            gdal_version = gdal.VersionInfo('VERSION_NUM')
            gdal_version_str = f"{gdal_version[0]}.{gdal_version[1]}.{gdal_version[2]}"
            logger.info(f"GDAL version: {gdal_version_str}")
            
        except ImportError:
            logger.warning("GDAL Python bindings not available - cannot check format support")
        except Exception as e:
            logger.warning(f"Failed to check GDAL support: {e}")

    def _setup_ui(self):
        """Set up the dock widget UI"""
        main_widget = QWidget()
        self.setWidget(main_widget)

        layout = QVBoxLayout(main_widget)
        layout.setSpacing(10)

        # Header
        header_label = QLabel("Altair EO Data")
        header_font = QFont()
        header_font.setPointSize(12)
        header_font.setBold(True)
        header_label.setFont(header_font)
        header_label.setAlignment(Qt.AlignCenter)
        header_label.setStyleSheet("color: #cccccc;")
        layout.addWidget(header_label)

        # Description
        desc_label = QLabel(
            "Unified access to multiple STAC catalogs of satellite imagery via AWS Open Data.\n"
            "Includes: Copernicus, Landsat, Umbra, Capella, ICEYE and many more."
        )
        desc_label.setWordWrap(True)
        desc_label.setStyleSheet("color: #b0b0b0; font-size: 10px;")
        layout.addWidget(desc_label)

        # Filters group (including search area)
        filters_group = QGroupBox("Filters")
        filters_group.setStyleSheet("QGroupBox { color: #cccccc; font-weight: bold; }")
        filters_layout = QFormLayout(filters_group)

        # Connector selection dropdown (NEW)
        self.connector_combo = QComboBox()
        self.connector_combo.setToolTip(
            "Select data source connector:\n"
            "• ICEYE: SAR open data\n"
            "• Umbra: High-resolution SAR (up to 16cm)\n"
            "• Capella: High-resolution SAR (~1000 images)\n"
            "• OneAtlas: Airbus commercial imagery\n"
            "• Planet: High-resolution satellite data\n"
            "• Copernicus: Sentinel Hub data access"
        )
        self.connector_combo.currentIndexChanged.connect(self._on_connector_changed)
        connector_label = QLabel("Data Source:")
        connector_label.setStyleSheet("color: #cccccc; font-weight: bold;")
        filters_layout.addRow(connector_label, self.connector_combo)

        # STAC Endpoint dropdown with reload button (for AWS STAC connector)
        endpoint_layout = QHBoxLayout()
        
        self.endpoint_combo = QComboBox()
        self.endpoint_combo.setToolTip(
            "Select a STAC endpoint from AWS Open Data catalog.\n"
            "Includes: Sentinel-2, Landsat, CBERS, and many more."
        )
        self.endpoint_combo.addItem("Loading catalog...", userData=None)
        endpoint_layout.addWidget(self.endpoint_combo)
        
        self.reload_catalog_btn = QPushButton("⟳")
        self.reload_catalog_btn.setMaximumWidth(30)
        self.reload_catalog_btn.setToolTip("Reload AWS catalog endpoints")
        self.reload_catalog_btn.clicked.connect(self.load_aws_endpoints)
        endpoint_layout.addWidget(self.reload_catalog_btn)
        
        self.endpoint_label = QLabel("Catalogue:")
        self.endpoint_label.setStyleSheet("color: #cccccc;")
        self.endpoint_row = filters_layout.rowCount()  # Store row index for show/hide
        filters_layout.addRow(self.endpoint_label, endpoint_layout)

        # STAC Collections dropdown  
        self.collections_combo = QComboBox()
        self.collections_combo.setToolTip(
            "Select a collection from the active STAC endpoint.\n"
            "Select 'All' to search across all available collections."
        )
        self.collections_combo.setEnabled(False)  # Disabled until endpoint selected
        self.collections_combo.addItem("N/A - Select endpoint", userData=None)
        collection_label = QLabel("Collection:")
        collection_label.setStyleSheet("color: #cccccc;")
        filters_layout.addRow(collection_label, self.collections_combo)

        # Search Area - QgsExtentWidget for area selection
        if QGIS_AVAILABLE and QgsExtentWidget and self.iface:
            self.extent_widget = QgsExtentWidget(parent=filters_group)
            
            # Connect to map canvas for current extent
            self.extent_widget.setMapCanvas(self.iface.mapCanvas())
            
            # Set initial extent to current map extent
            self.extent_widget.setCurrentExtent(
                self.iface.mapCanvas().extent(),
                self.iface.mapCanvas().mapSettings().destinationCrs()
            )
            
            # Set original extent for reset button
            self.extent_widget.setOriginalExtent(
                self.iface.mapCanvas().extent(),
                self.iface.mapCanvas().mapSettings().destinationCrs()
            )
            
            # Output CRS will be the current map CRS
            self.extent_widget.setOutputCrs(
                self.iface.mapCanvas().mapSettings().destinationCrs()
            )
            
            # Area checkbox
            area_checkbox_layout = QHBoxLayout()
            self.use_area_check = QCheckBox("Use Search Area")
            self.use_area_check.setChecked(True)
            self.use_area_check.setStyleSheet("color: #cccccc;")
            self.use_area_check.stateChanged.connect(self._on_use_area_changed)
            area_checkbox_layout.addWidget(self.use_area_check)
            area_checkbox_layout.addStretch()
            filters_layout.addRow("", area_checkbox_layout)
            
            area_label = QLabel("Search Area:")
            area_label.setStyleSheet("color: #cccccc;")
            filters_layout.addRow(area_label, self.extent_widget)
            
            logger.info("QgsExtentWidget initialized successfully")
        else:
            # Fallback: simple manual bbox input
            logger.warning("QgsExtentWidget not available, using manual input fallback")
            self.extent_widget = None
            
            fallback_label = QLabel(
                "QgsExtentWidget not available. Enter coordinates manually:"
            )
            fallback_label.setWordWrap(True)
            fallback_label.setStyleSheet("color: #cccccc;")
            filters_layout.addRow(fallback_label)
            
            # Manual bbox input fields
            self.bbox_minx = QLineEdit("-180.0")
            self.bbox_miny = QLineEdit("-90.0")
            self.bbox_maxx = QLineEdit("180.0")
            self.bbox_maxy = QLineEdit("90.0")
            
            filters_layout.addRow("Min X (Lon):", self.bbox_minx)
            filters_layout.addRow("Min Y (Lat):", self.bbox_miny)
            filters_layout.addRow("Max X (Lon):", self.bbox_maxx)
            filters_layout.addRow("Max Y (Lat):", self.bbox_maxy)

        # Date range checkbox and fields
        date_checkbox_layout = QHBoxLayout()
        self.use_date_check = QCheckBox("Use Date Range")
        self.use_date_check.setChecked(False)
        self.use_date_check.setStyleSheet("color: #cccccc;")
        self.use_date_check.stateChanged.connect(self._on_use_date_changed)
        date_checkbox_layout.addWidget(self.use_date_check)
        date_checkbox_layout.addStretch()
        filters_layout.addRow("", date_checkbox_layout)
        
        # Date range
        self.start_date = QDateEdit()
        self.start_date.setDate(QDate.currentDate().addMonths(-36))
        self.start_date.setCalendarPopup(True)
        self.start_date.setEnabled(False)
        start_label = QLabel("Start Date:")
        start_label.setStyleSheet("color: #cccccc;")
        filters_layout.addRow(start_label, self.start_date)
        
        self.end_date = QDateEdit()
        self.end_date.setDate(QDate.currentDate())
        self.end_date.setCalendarPopup(True)
        self.end_date.setEnabled(False)
        end_label = QLabel("End Date:")
        end_label.setStyleSheet("color: #cccccc;")
        filters_layout.addRow(end_label, self.end_date)

        # Cloud cover checkbox and slider
        cloud_checkbox_layout = QHBoxLayout()
        self.use_cloud_check = QCheckBox("Use Cloud Cover Filter")
        self.use_cloud_check.setChecked(False)
        self.use_cloud_check.setStyleSheet("color: #cccccc;")
        self.use_cloud_check.stateChanged.connect(self._on_use_cloud_changed)
        cloud_checkbox_layout.addWidget(self.use_cloud_check)
        cloud_checkbox_layout.addStretch()
        filters_layout.addRow("", cloud_checkbox_layout)
        
        # Cloud cover slider
        cloud_cover_layout = QHBoxLayout()
        self.cloud_cover_slider = QSlider(Qt.Horizontal)
        self.cloud_cover_slider.setRange(0, 100)
        self.cloud_cover_slider.setValue(20)
        self.cloud_cover_slider.setTickPosition(QSlider.TicksBelow)
        self.cloud_cover_slider.setTickInterval(10)
        self.cloud_cover_slider.setToolTip("Drag to set maximum cloud cover percentage")
        cloud_cover_layout.addWidget(self.cloud_cover_slider)
        
        self.cloud_cover_label = QLabel("20%")
        self.cloud_cover_label.setMinimumWidth(40)
        self.cloud_cover_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.cloud_cover_label.setStyleSheet("color: #cccccc; font-weight: bold;")
        cloud_cover_layout.addWidget(self.cloud_cover_label)
        
        # Update label when slider changes
        self.cloud_cover_slider.valueChanged.connect(
            lambda val: self.cloud_cover_label.setText(f"{val}%")
        )
        
        cloud_label = QLabel("Max Cloud Cover:")
        cloud_label.setStyleSheet("color: #cccccc;")
        filters_layout.addRow(cloud_label, cloud_cover_layout)

        layout.addWidget(filters_group)

        # Search and clear buttons row
        search_layout = QHBoxLayout()
        
        # Search button with integrated spinner
        self.search_btn = QPushButton("Search")
        self.search_btn.setToolTip("Start search with selected parameters")
        search_layout.addWidget(self.search_btn)
        
        # Clear results button
        self.clear_results_btn = QPushButton("Clear Results")
        self.clear_results_btn.setToolTip("Clear search results and remove footprints layer")
        self.clear_results_btn.setEnabled(False)  # Disabled until there are results
        self.clear_results_btn.clicked.connect(self._on_clear_results_clicked)
        search_layout.addWidget(self.clear_results_btn)
        
        layout.addLayout(search_layout)
        
        # Store original button text for spinner animation
        self._search_btn_original_text = "Search"
        self._search_spinner_timer = None
        self._search_spinner_state = 0

        # Results table
        results_group = QGroupBox("Results")
        results_group.setStyleSheet("QGroupBox { color: #cccccc; font-weight: bold; }")
        results_layout = QVBoxLayout(results_group)

        # Use QTableWidget with 5 columns
        self.results_table = QTableWidget()
        self.results_table.setColumnCount(5)
        self.results_table.setHorizontalHeaderLabels(
            ["Date", "Satellite", "Cloud %", "Resolution", "ID"]
        )
        self.results_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.results_table.horizontalHeader().setStretchLastSection(True)
        self.results_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.results_table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.results_table.setAlternatingRowColors(True)
        self.results_table.setSortingEnabled(True)
        self.results_table.itemSelectionChanged.connect(self._on_footprint_selection_changed)
        self.results_table.horizontalHeader().sectionDoubleClicked.connect(self._on_header_double_clicked)
        results_layout.addWidget(self.results_table)
        
        # Track sorting order per column
        self._sort_order = {}

        layout.addWidget(results_group)

        # Action buttons group
        actions_group = QGroupBox("Actions")
        actions_group.setStyleSheet("QGroupBox { color: #cccccc; font-weight: bold; }")
        actions_layout = QVBoxLayout(actions_group)

        # Selection and zoom buttons row (horizontal)
        selection_layout = QHBoxLayout()
        
        # Select from Map button
        self.select_from_map_btn = QPushButton("Select from Map")
        self.select_from_map_btn.setCheckable(True)
        self.select_from_map_btn.setToolTip("Click on map to select footprints. Ctrl+Click for multiple selection.")
        self.select_from_map_btn.toggled.connect(self._on_selection_mode_toggled)
        self.select_from_map_btn.setEnabled(False)
        selection_layout.addWidget(self.select_from_map_btn)

        # Zoom to selected
        self.zoom_btn = QPushButton("Zoom to Selection")
        self.zoom_btn.setEnabled(False)
        self.zoom_btn.setToolTip("Zoom to selected image(s)")
        self.zoom_btn.clicked.connect(self._zoom_to_selected)
        selection_layout.addWidget(self.zoom_btn)
        
        actions_layout.addLayout(selection_layout)

        # Load imagery buttons row
        imagery_layout = QHBoxLayout()
        
        # Load COG button
        self.preview_btn = QPushButton("Load COG")
        self.preview_btn.setEnabled(False)
        self.preview_btn.setToolTip("Load GeoTIFF/COG raster as activable layer")
        self.preview_btn.clicked.connect(self._preview_imagery)
        imagery_layout.addWidget(self.preview_btn)

        # Download button
        self.download_btn = QPushButton("Download")
        self.download_btn.setEnabled(False)
        self.download_btn.setToolTip("Download selected COG imagery to local folder")
        self.download_btn.clicked.connect(self._download_imagery)
        imagery_layout.addWidget(self.download_btn)

        actions_layout.addLayout(imagery_layout)

        # Clear layers button
        self.clear_btn = QPushButton("Clear All Layers")
        self.clear_btn.setToolTip("Remove all layers loaded by Altair")
        self.clear_btn.clicked.connect(self._clear_layers)
        actions_layout.addWidget(self.clear_btn)

        layout.addWidget(actions_group)

        # Status label
        self.status_label = QLabel("Ready - Load a STAC endpoint to begin")
        self.status_label.setStyleSheet("color: #f0f0f0; font-size: 10px; font-weight: 500;")
        self.status_label.setWordWrap(False)  # Disable word wrap to enforce truncation
        layout.addWidget(self.status_label)

        # Initialize connector manager and register connectors
        self._init_connector_manager()

        # Connect signals
        self.results_table.selectionModel().selectionChanged.connect(self._on_selection_changed)
        self.search_btn.clicked.connect(self._on_search_clicked)
        
        # Connect endpoint and collections combo to update
        self.endpoint_combo.currentIndexChanged.connect(self._on_endpoint_changed)
        self.collections_combo.currentIndexChanged.connect(self._on_collection_changed)
        
        # AWS STAC auto-load removed (connector masked from UI)

    def _set_status(self, text, style="color: #f0f0f0; font-size: 10px; font-weight: 500;"):
        """
        Set status label text with automatic truncation and tooltip.
        
        Args:
            text: Full status text
            style: CSS style for the label (default: normal style)
        """
        MAX_LENGTH = 80
        
        # Set full text as tooltip
        self.status_label.setToolTip(text)
        
        # Truncate display text if needed
        if len(text) > MAX_LENGTH:
            display_text = text[:MAX_LENGTH] + "..."
        else:
            display_text = text
        
        self.status_label.setText(display_text)
        self.status_label.setStyleSheet(style)

    def _start_search_spinner(self):
        """Start spinner animation in search button"""
        from PyQt5.QtCore import QTimer
        
        self._search_spinner_state = 0
        spinner_chars = ['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏']
        
        def update_spinner():
            if self._search_spinner_timer and self._search_spinner_timer.isActive():
                char = spinner_chars[self._search_spinner_state % len(spinner_chars)]
                self.search_btn.setText(f"{char} Searching...")
                self._search_spinner_state += 1
        
        # Stop existing timer if any
        if self._search_spinner_timer:
            self._search_spinner_timer.stop()
        
        self._search_spinner_timer = QTimer()
        self._search_spinner_timer.timeout.connect(update_spinner)
        self._search_spinner_timer.start(80)  # Update every 80ms
        update_spinner()  # Initial update
    
    def _stop_search_spinner(self):
        """Stop spinner animation and restore button text"""
        if self._search_spinner_timer:
            self._search_spinner_timer.stop()
            self._search_spinner_timer = None
        
        self.search_btn.setText(self._search_btn_original_text)
        self._search_spinner_state = 0

    def _on_clear_results_clicked(self):
        """Handle Clear Results button click - clear table and remove footprints layer.
        
        Asks for user confirmation before clearing results.
        """
        # Check if there are results to clear
        if not self._search_results and self.results_table.rowCount() == 0:
            logger.debug("No results to clear")
            return
        
        # Ask for confirmation
        reply = QMessageBox.question(
            self,
            "Clear Results",
            "Are you sure you want to clear all search results?\n\n"
            "This will:\n"
            "• Clear the results table\n"
            "• Remove the footprints layer from the map\n"
            "• Reset the selection\n\n"
            "This action cannot be undone.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No  # Default to No for safety
        )
        
        if reply != QMessageBox.Yes:
            logger.info("Clear results cancelled by user")
            return
        
        logger.info("Clearing search results...")
        
        # Clear internal results storage
        self._search_results = []
        
        # Clear results table
        self.results_table.setRowCount(0)
        
        # Clear selection mappings
        self._feature_id_to_result_index.clear()
        self._result_index_to_feature_id.clear()
        
        # Remove footprints layer if it exists
        if self.footprints_layer and QGIS_AVAILABLE:
            try:
                from qgis.core import QgsProject
                QgsProject.instance().removeMapLayer(self.footprints_layer.id())
                logger.info("Removed footprints layer from map")
            except Exception as e:
                logger.error(f"Failed to remove footprints layer: {e}")
            finally:
                self.footprints_layer = None
        
        # Disable action buttons
        self.preview_btn.setEnabled(False)
        self.download_btn.setEnabled(False)
        self.zoom_btn.setEnabled(False)
        self.select_from_map_btn.setEnabled(False)
        self.clear_results_btn.setEnabled(False)
        
        # Exit selection mode if active
        if self.select_from_map_btn.isChecked():
            self.select_from_map_btn.setChecked(False)
        
        # Update status
        self._set_status(
            "Results cleared",
            "color: #FFA500; font-size: 10px; font-weight: 500;"
        )
        
        logger.info("Search results cleared successfully")

    def _init_connector_manager(self):
        """Initialize ConnectorManager and register all available connectors"""
        from ..connectors import ConnectorManager, ConnectorType, ConnectorCapability
        
        self.connector_manager = ConnectorManager()
        
        # AWS STAC connector removed (masked from UI)
        self.aws_connector = None
        self.swisstopo_connector = None  # Removed swisstopo connector
        
        # Register OneAtlas connector (commercial - requires authentication)
        try:
            from ..connectors import OneAtlasConnector
            oneatlas_connector = OneAtlasConnector()
            
            self.connector_manager.register_connector(
                connector_id='oneatlas',
                connector_instance=oneatlas_connector,
                display_name='OneAtlas (Airbus)',
                capabilities=[
                    ConnectorCapability.BBOX_SEARCH,
                    ConnectorCapability.DATE_RANGE,
                    ConnectorCapability.CLOUD_COVER,
                    ConnectorCapability.COLLECTIONS,
                    ConnectorCapability.COG_SUPPORT,
                    ConnectorCapability.AUTHENTICATION,
                    ConnectorCapability.COMMERCIAL
                ],
                description='Airbus OneAtlas commercial high-resolution imagery (0.3-1.5m)'
            )
            logger.info("Registered OneAtlas connector")
            
            self.oneatlas_connector = oneatlas_connector
            
        except ImportError as e:
            logger.warning(f"OneAtlas connector not available: {e}")
            self.oneatlas_connector = None
        except Exception as e:
            logger.error(f"Failed to register OneAtlas connector: {e}")
            self.oneatlas_connector = None
        
        # Register Planet connector (commercial - requires API key)
        try:
            from ..connectors import PlanetConnector
            planet_connector = PlanetConnector()
            
            self.connector_manager.register_connector(
                connector_id='planet',
                connector_instance=planet_connector,
                display_name='Planet Labs',
                capabilities=[
                    ConnectorCapability.BBOX_SEARCH,
                    ConnectorCapability.DATE_RANGE,
                    ConnectorCapability.CLOUD_COVER,
                    ConnectorCapability.COLLECTIONS,
                    ConnectorCapability.COG_SUPPORT,
                    ConnectorCapability.AUTHENTICATION,
                    ConnectorCapability.COMMERCIAL
                ],
                description='Planet Labs daily satellite imagery (0.5-5m resolution)'
            )
            logger.info("Registered Planet connector")
            
            self.planet_connector = planet_connector
            
        except ImportError as e:
            logger.warning(f"Planet connector not available: {e}")
            self.planet_connector = None
        except Exception as e:
            logger.error(f"Failed to register Planet connector: {e}")
            self.planet_connector = None
        
        # Register Vantor connector (Maxar Open Data via GitHub)
        try:
            from ..connectors import VantorConnector
            vantor_connector = VantorConnector()
            
            self.connector_manager.register_connector(
                connector_id='vantor',
                connector_instance=vantor_connector,
                display_name='Vantor Open Data',
                capabilities=[
                    ConnectorCapability.BBOX_SEARCH,
                    ConnectorCapability.DATE_RANGE,
                    ConnectorCapability.CLOUD_COVER,
                    ConnectorCapability.COLLECTIONS,
                    ConnectorCapability.COG_SUPPORT
                ],
                description='Vantor/Maxar Open Data via GitHub dataset'
            )
            
            logger.info("Registered Vantor connector")
            self.vantor_connector = vantor_connector
            
        except ImportError as e:
            logger.warning(f"Vantor connector not available: {e}")
            self.vantor_connector = None
        except Exception as e:
            logger.error(f"Failed to register Vantor connector: {e}")
            self.vantor_connector = None
        
        # Register ICEYE STAC connector (ICEYE SAR Open Data)
        try:
            from ..connectors.iceye_stac import IceyeStacConnector
            iceye_connector = IceyeStacConnector()
            
            self.connector_manager.register_connector(
                connector_id='iceye_stac',
                connector_instance=iceye_connector,
                display_name='ICEYE SAR Open Data',
                capabilities=[
                    ConnectorCapability.BBOX_SEARCH,
                    ConnectorCapability.DATE_RANGE,
                    ConnectorCapability.COLLECTIONS,
                    ConnectorCapability.COG_SUPPORT
                ],
                description='ICEYE Synthetic Aperture Radar open data via STAC'
            )
            logger.info("Registered ICEYE STAC connector")
            
            self.iceye_connector = iceye_connector
            
        except ImportError as e:
            logger.warning(f"ICEYE STAC connector not available: {e}")
            self.iceye_connector = None
        except Exception as e:
            logger.error(f"Failed to register ICEYE STAC connector: {e}")
            self.iceye_connector = None
        
        # Register Umbra STAC connector (Umbra SAR Open Data)
        try:
            from ..connectors.umbra_stac import UmbraSTACConnector
            umbra_connector = UmbraSTACConnector()
            
            self.connector_manager.register_connector(
                connector_id='umbra_stac',
                connector_instance=umbra_connector,
                display_name='Umbra SAR Open Data',
                capabilities=[
                    ConnectorCapability.BBOX_SEARCH,
                    ConnectorCapability.DATE_RANGE,
                    ConnectorCapability.COLLECTIONS,
                    ConnectorCapability.COG_SUPPORT
                ],
                description='Umbra high-resolution SAR imagery (up to 16cm) via STAC'
            )
            logger.info("Registered Umbra STAC connector")
            
            self.umbra_connector = umbra_connector
            
        except ImportError as e:
            logger.warning(f"Umbra STAC connector not available: {e}")
            self.umbra_connector = None
        except Exception as e:
            logger.error(f"Failed to register Umbra STAC connector: {e}")
            self.umbra_connector = None
        
        # Register Capella STAC connector (Capella SAR Open Data)
        try:
            from ..connectors.capella_stac import CapellaSTACConnector
            capella_connector = CapellaSTACConnector()
            
            self.connector_manager.register_connector(
                connector_id='capella_stac',
                connector_instance=capella_connector,
                display_name='Capella SAR Open Data',
                capabilities=[
                    ConnectorCapability.BBOX_SEARCH,
                    ConnectorCapability.DATE_RANGE,
                    ConnectorCapability.COLLECTIONS,
                    ConnectorCapability.COG_SUPPORT
                ],
                description='Capella Space high-resolution SAR imagery (~1000 images) via STAC'
            )
            logger.info("Registered Capella STAC connector")
            
            self.capella_connector = capella_connector
            
        except ImportError as e:
            logger.warning(f"Capella STAC connector not available: {e}")
            self.capella_connector = None
        except Exception as e:
            logger.error(f"Failed to register Capella STAC connector: {e}")
            self.capella_connector = None
        
        # Register Copernicus Dataspace connector (Sentinel-1/2)
        try:
            from ..connectors.copernicus import CopernicusConnector
            copernicus_connector = CopernicusConnector()
            
            self.connector_manager.register_connector(
                connector_id='copernicus',
                connector_instance=copernicus_connector,
                display_name='Copernicus Dataspace (Sentinel)',
                capabilities=[
                    ConnectorCapability.BBOX_SEARCH,
                    ConnectorCapability.DATE_RANGE,
                    ConnectorCapability.CLOUD_COVER,
                    ConnectorCapability.COLLECTIONS,
                    ConnectorCapability.COG_SUPPORT,
                    ConnectorCapability.AUTHENTICATION
                ],
                description='Copernicus Sentinel-1/2 data via Sentinel Hub Catalog API'
            )
            logger.info("Registered Copernicus connector")
            
            self.copernicus_connector = copernicus_connector
            
        except ImportError as e:
            logger.warning(f"Copernicus connector not available: {e}")
            self.copernicus_connector = None
        except Exception as e:
            logger.error(f"Failed to register Copernicus connector: {e}")
            self.copernicus_connector = None
        
        # Register Google Earth Engine connector (cloud-based Earth observation data)
        try:
            from ..connectors import GeeConnector
            
            # Try to get project_id from settings or environment
            settings = QSettings()
            project_id = settings.value('altair/gee_project_id', None)
            
            gee_connector = GeeConnector(project_id=project_id)
            
            self.connector_manager.register_connector(
                connector_id='gee',
                connector_instance=gee_connector,
                display_name='Google Earth Engine',
                capabilities=[
                    ConnectorCapability.TEXT_SEARCH,
                    ConnectorCapability.COLLECTIONS,
                    ConnectorCapability.AUTHENTICATION
                ],
                description='Browse 5,140+ Earth Engine datasets (Landsat, Sentinel, MODIS, etc.)'
            )
            logger.info("Registered Google Earth Engine connector")
            
            self.gee_connector = gee_connector
            
        except ImportError as e:
            logger.warning(f"Google Earth Engine connector not available: {e}")
            logger.info("Install earthengine-api to enable GEE: pip install earthengine-api")
            self.gee_connector = None
        except Exception as e:
            logger.error(f"Failed to register Google Earth Engine connector: {e}")
            self.gee_connector = None
        
        # Register NASA EarthData connector (9,000+ Earth science datasets)
        try:
            from ..connectors import NasaEarthdataConnector
            
            # Try to get credentials from settings or environment
            settings = QSettings()
            username = settings.value('altair/nasa_username', None)
            password = settings.value('altair/nasa_password', None)
            
            nasa_connector = NasaEarthdataConnector(username=username, password=password)
            
            self.connector_manager.register_connector(
                connector_id='nasa_earthdata',
                connector_instance=nasa_connector,
                display_name='NASA EarthData',
                capabilities=[
                    ConnectorCapability.BBOX_SEARCH,
                    ConnectorCapability.DATE_RANGE,
                    ConnectorCapability.CLOUD_COVER,
                    ConnectorCapability.COLLECTIONS,
                    ConnectorCapability.COG_SUPPORT,
                    ConnectorCapability.DOWNLOAD,
                    ConnectorCapability.AUTHENTICATION
                ],
                description='Browse 9,000+ NASA Earth science datasets (GEDI, MODIS, Landsat, Sentinel, etc.)'
            )
            logger.info("Registered NASA EarthData connector")
            
            self.nasa_connector = nasa_connector
            
        except ImportError as e:
            logger.warning(f"NASA EarthData connector not available: {e}")
            logger.info("Install earthaccess to enable NASA EarthData: pip install earthaccess pandas")
            self.nasa_connector = None
        except Exception as e:
            logger.error(f"Failed to register NASA EarthData connector: {e}")
            self.nasa_connector = None
        
        # Populate connector dropdown
        self._populate_connector_combo()
        
        num_connectors = len(self.connector_manager._connectors)  # Access internal dict
        logger.info(f"ConnectorManager initialized with {num_connectors} connectors")
    
    def _populate_connector_combo(self):
        """Populate the connector selection combo box"""
        self.connector_combo.clear()
        
        # Add "All Sources" as first option for aggregated search
        self.connector_combo.addItem("🌐 All Sources (Aggregated)", userData="__all_sources__")
        
        # Add separator (visual only, not selectable in most Qt versions)
        # self.connector_combo.insertSeparator(1)  # Would be nice but may not work in all Qt versions
        
        # List of connector IDs to hide from UI
        hidden_connectors = ['aws_stac']  # Mask AWS STAC from selection
        
        for conn_id, conn_info in self.connector_manager._connectors.items():
            # Skip hidden connectors
            if conn_id in hidden_connectors:
                logger.debug(f"Skipping hidden connector: {conn_id}")
                continue
            
            display_text = conn_info['display_name']
            
            self.connector_combo.addItem(display_text, userData=conn_id)
        
        # Set active connector as selected (if not hidden)
        active_conn = self.connector_manager.get_active_connector()
        if active_conn:
            active_id = active_conn['id']
            # Only select if not hidden
            if active_id not in hidden_connectors:
                for i in range(self.connector_combo.count()):
                    if self.connector_combo.itemData(i) == active_id:
                        self.connector_combo.setCurrentIndex(i)
                        break
            else:
                # If active connector is hidden, select first available
                if self.connector_combo.count() > 0:
                    self.connector_combo.setCurrentIndex(0)
        
        logger.info(f"Populated connector combo with {self.connector_combo.count()} connectors (including 'All Sources', hidden: {len(hidden_connectors)})")
    
    def _on_connector_changed(self, index):
        """Handle connector selection change"""
        if index < 0:
            return
        
        connector_id = self.connector_combo.itemData(index)
        if not connector_id:
            return
        
        # Handle "All Sources" special case
        if connector_id == "__all_sources__":
            logger.info("Switched to 'All Sources' aggregated mode")
            
            self._set_status(
                "All Sources - Search across all available connectors",
                "color: #00BFFF; font-size: 10px; font-weight: 500;"
            )
            
            # Load aggregated collections from all connectors
            self._load_all_sources_collections()
            
            return
        
        # Standard single-connector mode
        try:
            self.connector_manager.set_active_connector(connector_id)
            
            conn_info = self.connector_manager._connectors[connector_id]
            display_name = conn_info['display_name']
            
            # Auto-authenticate public connectors (Vantor)
            if connector_id == 'vantor' and not conn_info.get('authenticated', False):
                logger.info(f"Auto-authenticating public connector: {connector_id}")
                self.connector_manager.authenticate_connector(connector_id)
                # Clear cache after authentication
                self.connector_manager.clear_collections_cache()
            
            self._set_status(
                f"Switched to {display_name}",
                "color: #00FF00; font-size: 10px; font-weight: 500;"
            )
            
            logger.info(f"Switched to connector: {connector_id} ({display_name})")
            
            # Refresh UI based on connector capabilities
            self._update_ui_for_connector(connector_id)
            
        except Exception as e:
            logger.error(f"Failed to switch connector: {e}")
            QMessageBox.warning(
                self,
                "Connector Error",
                f"Failed to switch to connector: {e}"
            )
    
    def _update_ui_for_connector(self, connector_id):
        """Update UI controls based on active connector capabilities"""
        from ..connectors import ConnectorCapability
        
        # Get connector capabilities
        has_collections = self.connector_manager.has_capability(ConnectorCapability.COLLECTIONS)
        has_cloud_cover = self.connector_manager.has_capability(ConnectorCapability.CLOUD_COVER)
        has_bbox = self.connector_manager.has_capability(ConnectorCapability.BBOX_SEARCH)
        
        # Clear collections combo when switching connectors
        self.collections_combo.clear()
        self.collections_combo.addItem("Loading...", userData=None)
        self.collections_combo.setEnabled(False)
        
        # Enable/disable controls based on capabilities
        if hasattr(self, 'collections_combo'):
            self.collections_combo.setEnabled(has_collections)
        
        if hasattr(self, 'cloud_slider'):
            self.cloud_slider.setEnabled(has_cloud_cover)
        
        # Always hide catalogue row (AWS STAC is masked)
        # Keep the widgets hidden regardless of connector
        self.endpoint_label.setVisible(False)
        self.endpoint_combo.setVisible(False)
        self.reload_catalog_btn.setVisible(False)
        
        # Load collections for specific connectors
        if connector_id == 'vantor':
            self._load_vantor_collections()
        elif connector_id == 'iceye_stac':
            self._load_iceye_collections()
        elif connector_id == 'umbra_stac':
            self._load_umbra_collections()
        elif connector_id == 'capella_stac':
            self._load_capella_collections()
        elif connector_id == 'copernicus':
            self._load_copernicus_collections()
        
        logger.debug(f"UI updated for connector: {connector_id} (collections={has_collections}, cloud={has_cloud_cover}, bbox={has_bbox})")
    
    def _load_all_sources_collections(self):
        """Load collections from ALL available connectors (All Sources mode)"""
        try:
            self._set_status("Loading collections from all sources...", "color: #FFA500;")
            
            # Get aggregated collections from all connectors
            all_collections = self.connector_manager.get_all_collections()
            
            self.collections_combo.clear()
            self.collections_combo.addItem("All Collections (All Sources)", userData=None)
            
            # Group collections by source for better organization
            collections_by_source = {}
            for collection in all_collections:
                source_name = collection.get('_source_name', 'Unknown')
                if source_name not in collections_by_source:
                    collections_by_source[source_name] = []
                collections_by_source[source_name].append(collection)
            
            # Add collections grouped by source
            for source_name in sorted(collections_by_source.keys()):
                source_collections = collections_by_source[source_name]
                
                for collection in source_collections:
                    collection_id = collection.get('id', 'unknown')
                    source_id = collection.get('_source', 'unknown')
                    title = collection.get('title', collection_id)
                    asset_count = collection.get('asset_count', 0)
                    
                    # Format: "[Source] Collection Name [N items]"
                    display_parts = [f"[{source_name}]", title]
                    if asset_count > 0:
                        display_parts.append(f"[{asset_count}]")
                    
                    display_text = " ".join(display_parts)
                    
                    # Store with source prefix for disambiguation
                    collection_with_source = dict(collection)
                    collection_with_source['id'] = f"{source_id}::{collection_id}"
                    
                    self.collections_combo.addItem(display_text, userData=collection_with_source)
            
            self.collections_combo.setEnabled(True)
            
            total_sources = len(collections_by_source)
            total_collections = len(all_collections)
            
            self._set_status(
                f"Loaded {total_collections} collections from {total_sources} sources",
                "color: #00FF00;"
            )
            
            logger.info(f"Loaded {total_collections} collections from {total_sources} sources in 'All Sources' mode")
            
        except Exception as e:
            logger.error(f"Failed to load collections from all sources: {e}")
            self._set_status(f"Error loading collections: {e}", "color: #FF0000;")
    
    def _load_vantor_collections(self):
        """Load collections from Vantor Open Data connector"""
        if not self.vantor_connector:
            return
        
        try:
            self._set_status("Loading Vantor Open Data events...", "color: #FFA500;")
            
            # Load events from GitHub
            collections = self.vantor_connector.get_collections()
            
            self.collections_combo.clear()
            self.collections_combo.addItem("All Events", userData=None)
            
            for collection in collections:
                collection_id = collection.get('id', 'unknown')
                title = collection.get('title', collection_id)
                asset_count = collection.get('asset_count', 0)
                
                # Format: "Event Name [N tiles]"
                if asset_count > 0:
                    display_text = f"{title} [{asset_count} tiles]"
                else:
                    display_text = title
                
                self.collections_combo.addItem(display_text, userData=collection)
            
            self.collections_combo.setEnabled(True)
            
            self._set_status(
                f"Loaded {len(collections)} Vantor events",
                "color: #00FF00;"
            )
            
            logger.info(f"Loaded {len(collections)} Vantor collections")
            
        except Exception as e:
            logger.error(f"Failed to load Vantor collections: {e}")
            self._set_status(f"Error loading Vantor events: {e}", "color: #FF0000;")
    
    def _load_iceye_collections(self):
        """Load collections from ICEYE STAC connector"""
        if not self.iceye_connector:
            return
        
        try:
            self._set_status("Loading ICEYE SAR collections...", "color: #FFA500;")
            
            # Authenticate to load catalog
            if not self.iceye_connector.authenticate():
                logger.error("Failed to authenticate ICEYE STAC connector")
                self._set_status("Failed to load ICEYE catalog", "color: #FF0000;")
                return
            
            # Get collections
            collections = self.iceye_connector.get_collections()
            
            self.collections_combo.clear()
            self.collections_combo.addItem("All Collections", userData=None)
            
            for collection in collections:
                collection_id = collection.get('id', 'unknown')
                title = collection.get('title', collection_id)
                
                # Get asset count if available
                asset_count = collection.get('asset_count', 0)
                
                # Format: "Collection Name [N assets]"
                if asset_count > 0:
                    display_text = f"{title} [{asset_count} items]"
                else:
                    # No asset count available - just show title
                    display_text = title
                
                # Add collection dict as userData
                self.collections_combo.addItem(display_text, userData=collection)
            
            self.collections_combo.setEnabled(True)
            
            self._set_status(
                f"Loaded {len(collections)} ICEYE SAR collections",
                "color: #00FF00;"
            )
            
            logger.info(f"Loaded {len(collections)} ICEYE collections")
            
        except Exception as e:
            logger.error(f"Failed to load ICEYE collections: {e}")
            self._set_status(f"Error loading collections: {e}", "color: #FF0000;")
    
    def _load_umbra_collections(self):
        """Load collections from Umbra STAC connector"""
        if not self.umbra_connector:
            return
        
        try:
            self._set_status("Loading Umbra SAR collections...", "color: #FFA500;")
            
            # Authenticate to load catalog
            if not self.umbra_connector.authenticate({}):
                logger.error("Failed to authenticate Umbra STAC connector")
                self._set_status("Failed to load Umbra catalog", "color: #FF0000;")
                return
            
            # Get collections (year catalogs)
            collections = self.umbra_connector.get_collections()
            
            self.collections_combo.clear()
            self.collections_combo.addItem("All Years", userData=None)
            
            for collection in collections:
                collection_id = collection.get('id', 'unknown')
                title = collection.get('title', collection_id)
                
                # Get month count (stored as asset_count)
                month_count = collection.get('asset_count', 0)
                
                # Format: "2024 [12 months]"
                if month_count > 0:
                    display_text = f"{title} [{month_count} months]"
                else:
                    display_text = title
                
                # Add collection dict as userData
                self.collections_combo.addItem(display_text, userData=collection)
            
            self.collections_combo.setEnabled(True)
            
            self._set_status(
                f"Loaded {len(collections)} Umbra year catalogs",
                "color: #00FF00;"
            )
            
            logger.info(f"Loaded {len(collections)} Umbra year catalogs")
            
        except Exception as e:
            logger.error(f"Failed to load Umbra collections: {e}")
            self._set_status(f"Error loading collections: {e}", "color: #FF0000;")
    
    def _load_capella_collections(self):
        """Load collections from Capella STAC connector"""
        if not self.capella_connector:
            return
        
        try:
            self._set_status("Loading Capella SAR collections...", "color: #FFA500;")
            
            # Authenticate to load catalog
            if not self.capella_connector.authenticate({}):
                logger.error("Failed to authenticate Capella STAC connector")
                self._set_status("Failed to load Capella catalog", "color: #FF0000;")
                return
            
            # Get collections (organizational views)
            collections = self.capella_connector.get_collections()
            
            self.collections_combo.clear()
            self.collections_combo.addItem("All Collections", userData=None)
            
            for collection in collections:
                collection_id = collection.get('id', 'unknown')
                title = collection.get('title', collection_id)
                
                # Get subcollection count
                sub_count = collection.get('asset_count', 0)
                
                # Format: "By Product Type [5 categories]"
                if sub_count > 0:
                    display_text = f"{title} [{sub_count} items]"
                else:
                    display_text = title
                
                # Add collection dict as userData
                self.collections_combo.addItem(display_text, userData=collection)
            
            self.collections_combo.setEnabled(True)
            
            self._set_status(
                f"Loaded {len(collections)} Capella organizational views",
                "color: #00FF00;"
            )
            
            logger.info(f"Loaded {len(collections)} Capella collections")
            
        except Exception as e:
            logger.error(f"Failed to load Capella collections: {e}")
            self._set_status(f"Error loading collections: {e}", "color: #FF0000;")
    
    def refresh_collections(self):
        """Refresh collections for the currently active connector.
        
        This is useful when credentials have been updated in settings
        and we need to reload collections without switching connectors.
        """
        current_index = self.connector_combo.currentIndex()
        if current_index < 0:
            return
        
        connector_id = self.connector_combo.itemData(current_index)
        if not connector_id:
            return
        
        logger.info(f"Refreshing collections for connector: {connector_id}")
        
        # Reload collections based on current connector
        if connector_id == 'vantor':
            self._load_vantor_collections()
        elif connector_id == 'iceye_stac':
            self._load_iceye_collections()
        elif connector_id == 'umbra_stac':
            self._load_umbra_collections()
        elif connector_id == 'capella_stac':
            self._load_capella_collections()
        elif connector_id == 'copernicus':
            self._load_copernicus_collections()
    
    def _load_copernicus_collections(self):
        """Load collections from Copernicus Dataspace connector"""
        logger.info("=" * 60)
        logger.info("COPERNICUS: _load_copernicus_collections() called")
        logger.info("=" * 60)
        
        if not self.copernicus_connector:
            logger.error("COPERNICUS: copernicus_connector is None!")
            return
        
        logger.info(f"COPERNICUS: connector object exists: {self.copernicus_connector}")
        
        try:
            self._set_status("Loading Copernicus Sentinel collections...", "color: #FFA500;")
            
            # Get credentials from secure storage
            if not self.secure_storage:
                self._set_status("Secure storage not available", "color: #FF0000;")
                logger.error("COPERNICUS: Secure storage not available!")
                return
            
            logger.info("COPERNICUS: Attempting to retrieve credentials from secure storage...")
            creds = self.secure_storage.get_credentials('copernicus')
            
            logger.info(f"COPERNICUS: Retrieved credentials: {creds is not None}")
            if creds:
                logger.info(f"COPERNICUS: Credentials keys: {list(creds.keys())}")
                client_id = creds.get('client_id', '')
                client_secret = creds.get('client_secret', '')
                logger.info(f"COPERNICUS: client_id length: {len(client_id)}")
                logger.info(f"COPERNICUS: client_secret length: {len(client_secret)}")
                logger.info(f"COPERNICUS: client_id first 20 chars: {client_id[:20] if client_id else 'EMPTY'}")
            else:
                logger.error("COPERNICUS: get_credentials('copernicus') returned None!")
            
            if not creds or not creds.get('client_id') or not creds.get('client_secret'):
                self._set_status("Copernicus credentials not configured", "color: #FF0000;")
                self.collections_combo.clear()
                self.collections_combo.addItem("Configure credentials in Settings", userData=None)
                self.collections_combo.setEnabled(False)
                logger.error("COPERNICUS: Credentials missing or incomplete!")
                return
            
            # Authenticate with OAuth2 via ConnectorManager (this updates the 'authenticated' flag)
            logger.info("COPERNICUS: Calling authenticate_connector() via ConnectorManager...")
            auth_result = self.connector_manager.authenticate_connector(
                connector_id='copernicus',
                credentials=creds
            )
            logger.info(f"COPERNICUS: authenticate_connector() returned: {auth_result}")
            
            if not auth_result:
                self._set_status("Failed to authenticate Copernicus", "color: #FF0000;")
                self.collections_combo.clear()
                self.collections_combo.addItem("Authentication failed - check credentials", userData=None)
                self.collections_combo.setEnabled(False)
                logger.error("COPERNICUS: OAuth2 authentication FAILED")
                return
            
            logger.info("COPERNICUS: Authentication SUCCESSFUL!")
            logger.info(f"COPERNICUS: ConnectorManager authenticated flag updated")
            logger.info(f"COPERNICUS: is_authenticated = {self.copernicus_connector.is_authenticated}")
            logger.info(f"COPERNICUS: _access_token exists = {self.copernicus_connector._access_token is not None}")
            if self.copernicus_connector._access_token:
                logger.info(f"COPERNICUS: token preview: {self.copernicus_connector._access_token[:30]}...")
            
            # Clear collections cache since new connector is authenticated
            self.connector_manager.clear_collections_cache()
            
            # Get collections from connector (now properly authenticated)
            collections = self.copernicus_connector.get_collections()
            
            if not collections:
                self._set_status("No Copernicus collections available", "color: #FFA500;")
                logger.warning("Copernicus connector returned no collections")
                return
            
            self.collections_combo.clear()
            self.collections_combo.addItem("All Collections", userData=None)
            
            for collection in collections:
                collection_id = collection.get('id', 'unknown')
                title = collection.get('title', collection_id)
                description = collection.get('description', '')
                
                # Format display with description
                if description:
                    display_text = f"{title} - {description}"
                else:
                    display_text = title
                
                self.collections_combo.addItem(display_text, userData=collection)
            
            self.collections_combo.setEnabled(True)
            
            self._set_status(
                f"Loaded {len(collections)} Copernicus Sentinel collections",
                "color: #00FF00;"
            )
            
            logger.info(f"Loaded {len(collections)} Copernicus collections")
            
        except Exception as e:
            logger.error(f"Failed to load Copernicus collections: {e}")
            self._set_status(f"Error loading collections: {e}", "color: #FF0000;")


    def _on_endpoint_changed(self, index):
        """Handle STAC endpoint selection change"""
        if index < 0:
            return
        
        endpoint_data = self.endpoint_combo.itemData(index)
        
        if not endpoint_data:
            # "Load catalog..." selected
            self._set_status(
                "Loading AWS catalog...",
                "color: #FFA500; font-size: 10px; font-weight: 500;"
            )
            return
        
        # Set endpoint in connector
        if self.aws_connector:
            endpoint_url = endpoint_data['url']
            self.aws_connector.set_endpoint(endpoint_url)
            
            # Load collections for this endpoint
            self._load_endpoint_collections(endpoint_data)
        
        endpoint_name = endpoint_data.get('name', 'Unknown')
        self._set_status(
            f"Active endpoint: {endpoint_name}",
            "color: #4CAF50; font-size: 10px; font-weight: 500;"
        )

    def _load_endpoint_collections(self, endpoint_data):
        """Load collections from selected endpoint"""
        if not self.aws_connector:
            logger.error("AWS connector not initialized")
            return
        
        endpoint_url = endpoint_data['url']
        endpoint_name = endpoint_data.get('name', 'Unknown')
        
        logger.info(f"Loading collections from endpoint: {endpoint_name} ({endpoint_url})")
        
        self._set_status(
            f"Loading collections from {endpoint_name}...",
            "color: #FFA500; font-size: 10px; font-weight: 500;"
        )
        
        QApplication.processEvents()
        
        try:
            logger.debug(f"Calling get_collections with URL: {endpoint_url}")
            collections = self.aws_connector.get_collections(endpoint_url)
            logger.info(f"get_collections returned {len(collections) if collections else 0} collections")
            
            if collections:
                logger.info(f"Populating dropdown with {len(collections)} collections")
                self._populate_stac_collections(collections)
                self._set_status(
                    f"{len(collections)} collections available from {endpoint_name}",
                    "color: #4CAF50; font-size: 10px; font-weight: 500;"
                )
            else:
                logger.warning(f"No collections returned for {endpoint_name}")
                self.collections_combo.clear()
                self.collections_combo.addItem("N/A - No collections", userData=None)
                self.collections_combo.setEnabled(False)
                self._set_status(
                    f"No collections found for {endpoint_name}",
                    "color: #FFA500; font-size: 10px; font-weight: 500;"
                )
        
        except Exception as e:
            logger.error(f"Error loading collections from {endpoint_name}: {e}", exc_info=True)
            self.collections_combo.clear()
            self.collections_combo.addItem("Loading error", userData=None)
            self.collections_combo.setEnabled(False)
            self._set_status(
                f"Error loading collections: {str(e)}",
                "color: #FF0000; font-size: 10px; font-weight: 500;"
            )

    def load_aws_endpoints(self, silent=False):
        """
        Load AWS STAC endpoints into dropdown.
        
        Args:
            silent: If True, suppress error dialogs (for auto-load on startup)
        """
        if not self.aws_connector:
            if not silent:
                QMessageBox.warning(
                    self,
                    "Error",
                    "AWS STAC connector not available"
                )
            logger.error("AWS STAC connector not available")
            return False
        
        # Update status
        self._set_status(
            "Loading AWS catalog...",
            "color: #FFA500; font-size: 10px; font-weight: 500;"
        )
        QApplication.processEvents()
        
        # Authenticate/load catalog
        success = self.aws_connector.authenticate()
        
        if not success:
            if not silent:
                QMessageBox.critical(
                    self,
                    "Catalog Loading Error",
                    "Unable to load AWS Open Data catalog.\n\n"
                    "Check your internet connection and try again."
                )
            self._set_status(
                "Failed to load catalog - Check connection",
                "color: #FF0000; font-size: 10px; font-weight: 500;"
            )
            logger.error("Failed to authenticate AWS connector")
            return False
        
        # Get endpoints
        endpoints = self.aws_connector.get_stac_endpoints()
        
        if not endpoints:
            if not silent:
                QMessageBox.warning(
                    self,
                    "No Endpoints",
                    "No STAC endpoints found in AWS catalog."
                )
            self._set_status(
                "No endpoints found in catalog",
                "color: #FFA500; font-size: 10px; font-weight: 500;"
            )
            logger.warning("No STAC endpoints found")
            return False
        
        # Populate endpoint dropdown
        self.endpoint_combo.clear()
        self.endpoint_combo.addItem("-- Select STAC Endpoint --", userData=None)
        
        for endpoint in endpoints:
            display_name = f"{endpoint['name'][:60]}..." if len(endpoint['name']) > 60 else endpoint['name']
            self.endpoint_combo.addItem(display_name, userData=endpoint)
        
        self._set_status(
            f"Catalog loaded: {len(endpoints)} STAC endpoints available",
            "color: #4CAF50; font-size: 10px; font-weight: 500;"
        )
        
        logger.info(f"Loaded {len(endpoints)} STAC endpoints")
        return True

    def refresh_stac_collections(self, stac_connector):
        """
        [DEPRECATED] Legacy method for compatibility
        Use load_aws_endpoints() instead
        """
        logger.warning("refresh_stac_collections() is deprecated, use load_aws_endpoints()")

    def disable_stac_collections(self):
        """
        [DEPRECATED] Legacy method for compatibility  
        Collections are now loaded per-endpoint
        """
        logger.warning("disable_stac_collections() is deprecated")

    def _on_collection_changed(self, index):
        """Handle STAC collection dropdown selection change"""
        if index < 0:
            return
        
        # Only update status if dropdown is enabled (STAC connector active)
        if not self.collections_combo.isEnabled():
            return
        
        current_text = self.collections_combo.currentText()
        if current_text.startswith("All STAC Collections"):
            self._set_status("Ready - Search across all STAC catalog collections")
        elif current_text == "N/A":
            self._set_status("STAC Collections not available - Load a STAC catalog")
        else:
            # Remove item count from display (e.g., "Collection [5 items]" -> "Collection")
            collection_name = current_text.split('[')[0].strip() if '[' in current_text else current_text
            self._set_status(f"Ready - STAC search on collection: {collection_name}")
        # Default style already set by _set_status

    def _on_use_area_changed(self, state):
        """Enable/disable search area widget based on checkbox state"""
        enabled = state == Qt.Checked
        if self.extent_widget:
            self.extent_widget.setEnabled(enabled)
        else:
            # Manual bbox inputs
            self.bbox_minx.setEnabled(enabled)
            self.bbox_miny.setEnabled(enabled)
            self.bbox_maxx.setEnabled(enabled)
            self.bbox_maxy.setEnabled(enabled)
        
        logger.debug(f"Use area filter: {enabled}")
    
    def _on_use_date_changed(self, state):
        """Enable/disable date range fields based on checkbox state"""
        enabled = state == Qt.Checked
        self.start_date.setEnabled(enabled)
        self.end_date.setEnabled(enabled)
        logger.debug(f"Use date filter: {enabled}")
    
    def _on_use_cloud_changed(self, state):
        """Enable/disable cloud cover slider based on checkbox state"""
        enabled = state == Qt.Checked
        self.cloud_cover_slider.setEnabled(enabled)
        self.cloud_cover_label.setEnabled(enabled)
        logger.debug(f"Use cloud cover filter: {enabled}")

    def _populate_collections_combo(self):
        """Populate the STAC collections dropdown"""
        self.collections_combo.clear()
        
        # Default: No STAC collections available
        self.collections_combo.addItem("N/A", userData=None)
        self.collections_combo.setEnabled(False)
        
        # TODO: When STAC connector is active, call this method with actual collections:
        # self._populate_stac_collections(stac_collections)
        
        logger.info("Collections combo initialized (waiting for STAC connector)")
    
    def _populate_stac_collections(self, stac_collections):
        """
        Populate dropdown with STAC collections from active STAC connector.
        
        Args:
            stac_collections: List of STAC collection objects/dicts with 'id' and optional 'title'
        
        Example:
            stac_collections = [
                {'id': 'hurricane-harvey', 'title': 'Hurricane Harvey'},
                {'id': 'hurricane-matthew', 'title': 'Hurricane Matthew'},
                ...
            ]
        """
        self.collections_combo.clear()
        
        if not stac_collections:
            # No collections available
            self.collections_combo.addItem("N/A", userData=None)
            self.collections_combo.setEnabled(False)
            logger.warning("No STAC collections to populate")
            return
        
        # Add "All Collections" option with count
        self.collections_combo.addItem(f"All STAC Collections [{len(stac_collections)}]", userData=None)
        
        # Add separator
        self.collections_combo.insertSeparator(1)
        
        # Add individual STAC collections
        for collection in stac_collections:
            # Get collection ID (required) and title (optional)
            collection_id = collection.get('id', 'unknown')
            collection_title = collection.get('title') or collection.get('description') or collection_id
            
            # Display format: "title (id)" or just "id" if no title
            display_name = f"{collection_title}" if collection_title != collection_id else collection_id
            
            # Try to get item count from collection links (for static catalogs)
            item_count = None
            links = collection.get('links', [])
            
            if links:
                # Count child/item links
                item_count = sum(1 for link in links if link.get('rel') in ['child', 'item'])
            
            # Build display string with item count only
            # Note: Asset counting removed as it was too slow (2-5 sec per collection)
            # Asset info can be fetched on-demand if needed
            if item_count and item_count > 0:
                display_name = f"{display_name} [{item_count} items]"
            
            # Store full collection data
            self.collections_combo.addItem(display_name, userData=collection)
        
        # Enable dropdown and set default to "All"
        self.collections_combo.setEnabled(True)
        self.collections_combo.setCurrentIndex(0)
        
        logger.info(f"Populated STAC collections dropdown with {len(stac_collections)} collections")
    
    def get_selected_stac_collection(self):
        """
        Get the currently selected STAC collection from the dropdown.
        
        Returns:
            dict or None: Selected STAC collection dict, or None if "All" is selected or N/A
        """
        if not self.collections_combo.isEnabled():
            # Dropdown disabled, no STAC connector active
            return None
        
        current_data = self.collections_combo.currentData()
        
        if current_data is None:
            # "All Collections" or "N/A" selected
            return None
        else:
            # Specific STAC collection selected
            return current_data

    def get_search_area(self):
        """
        Get the current search area from QgsExtentWidget or manual input.

        Returns:
            dict: {'bbox': [min_x, min_y, max_x, max_y], 'crs': 'EPSG:XXXX', 'wkt': 'POLYGON(...)' or None}
        """
        if self.extent_widget:
            try:
                # Update extent widget CRS to match current map canvas
                # This ensures CRS changes are reflected
                current_map_crs = self.iface.mapCanvas().mapSettings().destinationCrs()
                widget_crs = self.extent_widget.outputCrs()
                
                if not widget_crs.isValid() or widget_crs.authid() != current_map_crs.authid():
                    logger.info(f"Updating extent widget CRS from {widget_crs.authid()} to {current_map_crs.authid()}")
                    self.extent_widget.setOutputCrs(current_map_crs)
                
                extent = self.extent_widget.outputExtent()
                crs = self.extent_widget.outputCrs()

                if not extent or extent.isEmpty():
                    logger.warning("QgsExtentWidget returned empty extent, using map extent")
                    extent = self.iface.mapCanvas().extent()
                    crs = self.iface.mapCanvas().mapSettings().destinationCrs()

                bbox = [
                    extent.xMinimum(),
                    extent.yMinimum(),
                    extent.xMaximum(),
                    extent.yMaximum()
                ]

                # Validate CRS
                crs_string = crs.authid() if crs and crs.isValid() else 'EPSG:4326'
                
                if not crs or not crs.isValid():
                    logger.warning(f"Invalid CRS from extent widget, defaulting to EPSG:4326")
                    crs_string = 'EPSG:4326'

                wkt = None
                if hasattr(self.extent_widget, 'extentLayerName') and self.extent_widget.extentLayerName():
                    layer_name = self.extent_widget.extentLayerName()
                    logger.info(f"Search area from layer: {layer_name}")

                    if QgsProject:
                        for layer in QgsProject.instance().mapLayers().values():
                            if layer.name() == layer_name and hasattr(layer, 'getFeatures'):
                                features = list(layer.getFeatures())
                                if features and QGIS_AVAILABLE:
                                    combined_geom = None
                                    for feature in features:
                                        geom = feature.geometry()
                                        if geom and not geom.isNull():
                                            if combined_geom is None:
                                                combined_geom = QgsGeometry(geom)
                                            else:
                                                combined_geom = combined_geom.combine(geom)

                                    if combined_geom and not combined_geom.isEmpty():
                                        wkt = combined_geom.asWkt()
                                        logger.info(f"Extracted WKT from layer: {len(wkt)} chars")
                                break

                logger.info(f"Search area: bbox={bbox}, crs={crs_string}, has_wkt={wkt is not None}")

                return {
                    'bbox': bbox,
                    'crs': crs_string,
                    'wkt': wkt
                }

            except Exception as e:
                logger.error(f"Error getting extent from QgsExtentWidget: {str(e)}", exc_info=True)
                try:
                    extent = self.iface.mapCanvas().extent()
                    crs = self.iface.mapCanvas().mapSettings().destinationCrs()
                    return {
                        'bbox': [extent.xMinimum(), extent.yMinimum(), extent.xMaximum(), extent.yMaximum()],
                        'crs': crs.authid() if crs else 'EPSG:4326',
                        'wkt': None
                    }
                except Exception:
                    return {
                        'bbox': [-180, -90, 180, 90],
                        'crs': 'EPSG:4326',
                        'wkt': None
                    }
        else:
            try:
                bbox = [
                    float(self.bbox_minx.text()),
                    float(self.bbox_miny.text()),
                    float(self.bbox_maxx.text()),
                    float(self.bbox_maxy.text())
                ]
                logger.info(f"Manual bbox input: {bbox}")
                return {
                    'bbox': bbox,
                    'crs': 'EPSG:4326',
                    'wkt': None
                }
            except ValueError as e:
                logger.error(f"Invalid manual bbox input: {str(e)}")
                QMessageBox.warning(
                    self,
                    "Invalid Coordinates",
                    "The entered coordinates are not valid.\n"
                    "Use valid decimal numbers (e.g., -180.0, 90.0)"
                )
                return None

    def _on_selection_changed(self):
        """Enable/disable buttons based on selection (LEGACY - use _on_footprint_selection_changed)"""
        self._on_footprint_selection_changed()
    
    def _on_footprint_selection_changed(self):
        """Handle footprint selection change in table."""
        selected_rows = self.results_table.selectionModel().selectedRows()
        has_selection = len(selected_rows) > 0
        
        # Update button states
        self.zoom_btn.setEnabled(has_selection)
        self.download_btn.setEnabled(has_selection)
        self.preview_btn.setEnabled(has_selection)
        
        # Update status
        if has_selection:
            self._set_status(f"{len(selected_rows)} image(s) selected")
        else:
            # Restore collection-based status
            self._on_collection_changed(self.collections_combo.currentIndex())
        
        # Sync selection to map layer (table -> map)
        if not self._updating_selection and self._is_footprints_layer_valid():
            self._updating_selection = True
            try:
                # Get result indices from selected rows (using item data)
                selected_indices = []
                for model_index in selected_rows:
                    row = model_index.row()
                    # Get result index from first column item data
                    item = self.results_table.item(row, 0)
                    if item:
                        result_index = item.data(Qt.UserRole)
                        if result_index is not None:
                            selected_indices.append(result_index)
                
                logger.debug(f"Table selected result indices: {selected_indices}")
                
                # Convert result indices to feature IDs using mapping
                selected_feature_ids = []
                for result_index in selected_indices:
                    feature_id = self._result_index_to_feature_id.get(result_index)
                    if feature_id is not None:
                        selected_feature_ids.append(feature_id)
                    else:
                        logger.warning(f"Result index {result_index} not found in reverse mapping")
                
                logger.debug(f"Mapped to feature IDs: {selected_feature_ids}")
                
                # Select features on the map layer
                if selected_feature_ids:
                    self.footprints_layer.selectByIds(selected_feature_ids)
                else:
                    # No valid feature IDs found, deselect all
                    self.footprints_layer.selectByIds([])
            except Exception as e:
                logger.error(f"Error syncing table selection to map: {e}", exc_info=True)
            finally:
                self._updating_selection = False

    def _on_search_clicked(self):
        """Handle search button click"""
        # Get active connector info
        active_conn = self.connector_manager.get_active_connector()
        if not active_conn:
            QMessageBox.warning(
                self,
                "No Connector Selected",
                "Please select a data source connector first."
            )
            return
        
        active_connector_id = active_conn['id']
        
        # Check if "All Sources" mode is active
        is_all_sources_mode = (active_connector_id == '__all_sources__')
        
        if is_all_sources_mode:
            # Use special handler for aggregated multi-source search
            self._on_search_all_sources()
            return
        
        # Validate connector-specific requirements
        if active_connector_id == 'aws_stac':
            # Check AWS STAC endpoint is selected
            if not self.aws_connector or not self.aws_connector.is_authenticated():
                QMessageBox.warning(
                    self,
                    "No Endpoint Selected",
                    "Please load the AWS catalog and select a STAC endpoint first.\n\n"
                    "Click 'Load Catalog' to begin."
                )
                return
            
            if not self.aws_connector._current_endpoint:
                QMessageBox.warning(
                    self,
                    "No Endpoint Selected",
                    "Please select a STAC endpoint from the dropdown."
                )
                return
        
        self.search_btn.setEnabled(False)
        self._start_search_spinner()
        
        # Get search parameters based on checkbox states
        # Area filter (optional)
        bbox = None
        crs = 'EPSG:4326'
        has_wkt = False
        area_info = "No area filter"
        
        if self.use_area_check.isChecked():
            area = self.get_search_area()
            if area and area.get('bbox'):
                bbox = area['bbox']
                crs = area['crs']
                has_wkt = area.get('wkt') is not None
                area_type = "Polygon" if has_wkt else "BBox"
                area_info = f"Area: {area_type}"
            else:
                QMessageBox.warning(
                    self,
                    "Invalid Area",
                    "Search area filter is enabled but no valid area is defined.\n\n"
                    "Either define a search area or uncheck 'Use Search Area'."
                )
                self.search_btn.setEnabled(True)
                self._stop_search_spinner()
                return
        
        # Date range filter (optional)
        start_date = None
        end_date = None
        date_info = "No date filter"
        
        if self.use_date_check.isChecked():
            start_date = self.start_date.date().toString("yyyy-MM-dd")
            end_date = self.end_date.date().toString("yyyy-MM-dd")
            date_info = f"Date: {start_date} to {end_date}"
        
        # Cloud cover filter (optional)
        max_cloud = None
        cloud_info = "No cloud filter"
        
        if self.use_cloud_check.isChecked():
            max_cloud = self.cloud_cover_slider.value()
            cloud_info = f"Cloud: ≤{max_cloud}%"
        
        # Get selected collection (if any)
        selected_stac_collection = self.get_selected_stac_collection()
        collection_id = None
        collection_info = ""
        
        if self.collections_combo.isEnabled():
            # Collections dropdown active
            if selected_stac_collection:
                collection_id = selected_stac_collection.get('id')
                collection_info = f"Collection: {collection_id} | "
            else:
                collection_info = "All Collections | "
        
        # Get connector display name
        connector_name = active_conn.get('display_name', active_connector_id)
        
        # Update status with filter info
        self._set_status(
            f"Searching {connector_name}... {collection_info}{area_info} | {date_info} | {cloud_info}",
            "color: #FFA500; font-size: 10px; font-weight: 500;"
        )
        
        QApplication.processEvents()
        
        try:
            # Transform bbox to WGS84 if needed (STAC uses EPSG:4326)
            search_bbox = bbox
            if bbox and crs != 'EPSG:4326' and QGIS_AVAILABLE:
                try:
                    logger.info(f"Transforming bbox from {crs} to EPSG:4326")
                    logger.debug(f"Original bbox: {bbox}")
                    
                    source_crs = QgsCoordinateReferenceSystem(crs)
                    dest_crs = QgsCoordinateReferenceSystem('EPSG:4326')
                    
                    # Validate source CRS
                    if not source_crs.isValid():
                        logger.error(f"Invalid source CRS: {crs}")
                        raise ValueError(f"Invalid source CRS: {crs}")
                    
                    if not dest_crs.isValid():
                        logger.error("Failed to create EPSG:4326 CRS")
                        raise ValueError("Failed to create EPSG:4326 CRS")
                    
                    transform = QgsCoordinateTransform(source_crs, dest_crs, QgsProject.instance())
                    
                    rect = QgsRectangle(bbox[0], bbox[1], bbox[2], bbox[3])
                    transformed_rect = transform.transformBoundingBox(rect)
                    
                    search_bbox = [
                        transformed_rect.xMinimum(),
                        transformed_rect.yMinimum(),
                        transformed_rect.xMaximum(),
                        transformed_rect.yMaximum()
                    ]
                    
                    # Validate transformed coordinates are within WGS84 bounds
                    # Longitude: -180 to 180, Latitude: -90 to 90
                    if not (-180 <= search_bbox[0] <= 180 and -180 <= search_bbox[2] <= 180):
                        logger.warning(f"Transformed longitude out of bounds: {search_bbox[0]}, {search_bbox[2]}")
                        # Clamp longitude
                        search_bbox[0] = max(-180, min(180, search_bbox[0]))
                        search_bbox[2] = max(-180, min(180, search_bbox[2]))
                    
                    if not (-90 <= search_bbox[1] <= 90 and -90 <= search_bbox[3] <= 90):
                        logger.warning(f"Transformed latitude out of bounds: {search_bbox[1]}, {search_bbox[3]}")
                        # Clamp latitude
                        search_bbox[1] = max(-90, min(90, search_bbox[1]))
                        search_bbox[3] = max(-90, min(90, search_bbox[3]))
                    
                    logger.info(f"Transformed bbox from {crs} to EPSG:4326: {search_bbox}")
                    logger.debug(f"Transformation details: source={source_crs.authid()}, dest={dest_crs.authid()}, "
                               f"isValid={source_crs.isValid() and dest_crs.isValid()}")
                    
                except Exception as e:
                    logger.error(f"Failed to transform bbox from {crs} to WGS84: {e}", exc_info=True)
                    QMessageBox.warning(
                        self,
                        "Coordinate Transformation Error",
                        f"Failed to transform search area from {crs} to WGS84.\n\n"
                        f"Error: {str(e)}\n\n"
                        "Please verify your map CRS is correctly configured."
                    )
                    self.search_btn.setEnabled(True)
                    self._stop_search_spinner()
                    return
            elif bbox and crs == 'EPSG:4326':
                logger.info(f"Bbox already in EPSG:4326, no transformation needed: {bbox}")
            
            # Execute search via SearchTask (background thread)
            # NOTE: No limit - retrieve all available results matching filters
            # Users want to see all imagery matching their search criteria
            logger.info(f"Executing search via {connector_name} with bbox={search_bbox}, dates={start_date} to {end_date}, cloud={max_cloud}%, collection={collection_id}")
            
            # Create search task
            search_params = {
                'bbox': search_bbox,
                'start_date': start_date,
                'end_date': end_date,
                'max_cloud_cover': max_cloud,
                'collection': collection_id,
                'limit': 10000  # High limit to retrieve all results (effectively unlimited)
            }
            
            # Create task with description for progress indicator
            task_description = f"Searching {connector_name}..."
            search_task = SearchTask(self.connector_manager, search_params, task_description)
            
            # Connect finished signal to handler
            search_task.taskCompleted.connect(lambda: self._on_search_completed(search_task, connector_name))
            search_task.taskTerminated.connect(lambda: self._on_search_terminated(search_task, connector_name))
            
            # Add to task manager for background execution
            if QGIS_AVAILABLE and QgsApplication.taskManager():
                QgsApplication.taskManager().addTask(search_task)
                logger.info("Search task added to QGIS task manager")
            else:
                # Fallback: run synchronously if task manager not available
                logger.warning("QGIS task manager not available, running search synchronously")
                search_task.run()
                self._on_search_completed(search_task, connector_name)
            
        except Exception as e:
            logger.error(f"Search initialization failed: {e}", exc_info=True)
            self._stop_search_spinner()
            self.search_btn.setEnabled(True)
            
            self._set_status(
                f"Search failed: {str(e)}",
                "color: #FF0000; font-size: 10px; font-weight: 500;"
            )
            
            QMessageBox.critical(
                self,
                "Search Error",
                f"Search failed:\n\n{str(e)}\n\nCheck the log for details."
            )
    
    def _on_search_all_sources(self):
        """Handle search for 'All Sources' aggregated mode"""
        self.search_btn.setEnabled(False)
        self._start_search_spinner()
        
        # Get search parameters
        bbox = None
        crs = 'EPSG:4326'
        area_info = "No area filter"
        
        if self.use_area_check.isChecked():
            area = self.get_search_area()
            if area and area.get('bbox'):
                bbox = area['bbox']
                crs = area['crs']
                area_type = "Polygon" if area.get('wkt') else "BBox"
                area_info = f"Area: {area_type}"
            else:
                QMessageBox.warning(
                    self,
                    "Invalid Area",
                    "Search area filter is enabled but no valid area is defined.\n\n"
                    "Either define a search area or uncheck 'Use Search Area'."
                )
                self.search_btn.setEnabled(True)
                self._stop_search_spinner()
                return
        
        # Date range filter
        start_date = None
        end_date = None
        date_info = "No date filter"
        
        if self.use_date_check.isChecked():
            start_date = self.start_date.date().toString("yyyy-MM-dd")
            end_date = self.end_date.date().toString("yyyy-MM-dd")
            date_info = f"Date: {start_date} to {end_date}"
        
        # Cloud cover filter
        max_cloud = None
        cloud_info = "No cloud filter"
        
        if self.use_cloud_check.isChecked():
            max_cloud = self.cloud_cover_slider.value()
            cloud_info = f"Cloud: ≤{max_cloud}%"
        
        # Get selected collection (may have "connector_id::collection_id" format)
        selected_stac_collection = self.get_selected_stac_collection()
        collection_filter = None
        collection_info = ""
        
        if self.collections_combo.isEnabled() and selected_stac_collection:
            full_collection_id = selected_stac_collection.get('id')
            if full_collection_id:
                collection_filter = full_collection_id  # Pass full "source::collection" format
                # Extract display name
                if '::' in full_collection_id:
                    _, col_id = full_collection_id.split('::', 1)
                    collection_info = f"Collection: {col_id} | "
                else:
                    collection_info = f"Collection: {full_collection_id} | "
        else:
            collection_info = "All Collections | "
        
        # Update status
        self._set_status(
            f"Searching ALL SOURCES... {collection_info}{area_info} | {date_info} | {cloud_info}",
            "color: #FFA500; font-size: 10px; font-weight: 600;"
        )
        
        QApplication.processEvents()
        
        try:
            # Transform bbox to WGS84 if needed
            search_bbox = bbox
            if bbox and crs != 'EPSG:4326' and QGIS_AVAILABLE:
                try:
                    logger.info(f"Transforming bbox from {crs} to EPSG:4326")
                    source_crs = QgsCoordinateReferenceSystem(crs)
                    dest_crs = QgsCoordinateReferenceSystem('EPSG:4326')
                    
                    if not source_crs.isValid():
                        raise ValueError(f"Invalid source CRS: {crs}")
                    if not dest_crs.isValid():
                        raise ValueError("Failed to create EPSG:4326 CRS")
                    
                    transform = QgsCoordinateTransform(source_crs, dest_crs, QgsProject.instance())
                    rect = QgsRectangle(bbox[0], bbox[1], bbox[2], bbox[3])
                    transformed_rect = transform.transformBoundingBox(rect)
                    
                    search_bbox = [
                        max(-180, min(180, transformed_rect.xMinimum())),
                        max(-90, min(90, transformed_rect.yMinimum())),
                        max(-180, min(180, transformed_rect.xMaximum())),
                        max(-90, min(90, transformed_rect.yMaximum()))
                    ]
                    
                    logger.info(f"Transformed bbox to EPSG:4326: {search_bbox}")
                    
                except Exception as e:
                    logger.error(f"Failed to transform bbox: {e}", exc_info=True)
                    QMessageBox.warning(
                        self,
                        "Coordinate Transformation Error",
                        f"Failed to transform search area from {crs} to WGS84.\n\nError: {str(e)}"
                    )
                    self.search_btn.setEnabled(True)
                    self._stop_search_spinner()
                    return
            
            # Call aggregated search
            logger.info(f"Executing ALL SOURCES search: bbox={search_bbox}, dates={start_date} to {end_date}, cloud={max_cloud}%, collection={collection_filter}")
            
            search_params = {
                'bbox': search_bbox,
                'start_date': start_date,
                'end_date': end_date,
                'max_cloud_cover': max_cloud,
                'collection': collection_filter,
                'limit': 10000
            }
            
            # Create task for aggregated search
            task_description = "Searching All Sources (Aggregated)..."
            search_task = AllSourcesSearchTask(self.connector_manager, search_params, task_description)
            
            # Connect signals
            search_task.taskCompleted.connect(lambda: self._on_search_completed(search_task, "All Sources"))
            search_task.taskTerminated.connect(lambda: self._on_search_terminated(search_task, "All Sources"))
            
            # Add to task manager
            if QGIS_AVAILABLE and QgsApplication.taskManager():
                QgsApplication.taskManager().addTask(search_task)
                logger.info("All Sources search task added to QGIS task manager")
            else:
                logger.warning("QGIS task manager not available, running search synchronously")
                search_task.run()
                self._on_search_completed(search_task, "All Sources")
        
        except Exception as e:
            logger.error(f"All Sources search initialization failed: {e}", exc_info=True)
            self._stop_search_spinner()
            self.search_btn.setEnabled(True)
            
            self._set_status(
                f"Search failed: {str(e)}",
                "color: #FF0000; font-size: 10px; font-weight: 500;"
            )
            
            QMessageBox.critical(
                self,
                "Search Error",
                f"All Sources search failed:\n\n{str(e)}\n\nCheck the log for details."
            )

    def _on_search_completed(self, task, connector_name):
        """Handle search task completion.
        
        Args:
            task: SearchTask instance that completed
            connector_name: Display name of connector
        """
        try:
            logger.debug(f"Search task completed for {connector_name}")
            
            # Check if task succeeded
            if task.error_message:
                # Task failed
                logger.error(f"Search task failed: {task.error_message}")
                
                self._stop_search_spinner()
                self.search_btn.setEnabled(True)
                
                self._set_status(
                    f"Search failed: {task.error_message}",
                    "color: #FF0000; font-size: 10px; font-weight: 500;"
                )
                
                QMessageBox.critical(
                    self,
                    "Search Error",
                    f"Search failed:\n\n{task.error_message}\n\nCheck the log for details."
                )
                return
            
            # Task succeeded - get results
            results = task.results
            logger.info(f"Search returned {len(results) if results else 0} results from {connector_name}")
            
            # Populate results table
            self._populate_results_table(results)
            
            # Create footprints layer
            if results and QGIS_AVAILABLE:
                self._create_footprints_layer(results)
            
            self._stop_search_spinner()
            self.search_btn.setEnabled(True)
            
            # Update status
            if results:
                self._set_status(
                    f"Search completed - {len(results)} result(s) found from {connector_name}",
                    "color: #4CAF50; font-size: 10px; font-weight: 500;"
                )
            else:
                self._set_status(
                    f"Search completed - No results found in {connector_name}",
                    "color: #FFA500; font-size: 10px; font-weight: 500;"
                )
        
        except Exception as e:
            logger.error(f"Error handling search completion: {e}", exc_info=True)
            self._stop_search_spinner()
            self.search_btn.setEnabled(True)
            
            self._set_status(
                f"Error processing results: {str(e)}",
                "color: #FF0000; font-size: 10px; font-weight: 500;"
            )

    def _on_search_terminated(self, task, connector_name):
        """Handle search task termination (cancelled).
        
        Args:
            task: SearchTask instance that was terminated
            connector_name: Display name of connector
        """
        logger.warning(f"Search task was terminated for {connector_name}")
        
        self._stop_search_spinner()
        self.search_btn.setEnabled(True)
        
        self._set_status(
            f"Search cancelled",
            "color: #FFA500; font-size: 10px; font-weight: 500;"
        )
    
    def _on_header_double_clicked(self, column):
        """Handle table header double-click for sorting.
        
        Similar to kadas-vantor-plugin pattern.
        """
        current_order = self._sort_order.get(column, Qt.DescendingOrder)
        new_order = (
            Qt.AscendingOrder
            if current_order == Qt.DescendingOrder
            else Qt.DescendingOrder
        )
        self._sort_order[column] = new_order
        self.results_table.sortItems(column, new_order)
    
    def _populate_results_table(self, results: List[Dict[str, Any]]):
        """Populate results table with STAC search results.
        
        Uses QTableWidget with 5-6 columns (6th column for All Sources mode):
        Date, Satellite, Cloud %, Resolution, ID, [Source]
        
        Args:
            results: List of STAC feature items
        """
        self._search_results = results
        
        if not results:
            logger.info("No results to populate")
            self.results_table.setRowCount(0)
            self.clear_results_btn.setEnabled(False)  # Disable when no results
            return
        
        logger.info(f"Populating table with {len(results)} results")
        
        # Check if any result has source information (All Sources mode)
        has_source_info = any('_source_name' in r.get('properties', {}) for r in results)
        
        # Configure columns dynamically
        if has_source_info:
            self.results_table.setColumnCount(6)
            self.results_table.setHorizontalHeaderLabels(
                ["Date", "Satellite", "Cloud %", "Resolution", "ID", "Source"]
            )
            source_col_idx = 5
        else:
            self.results_table.setColumnCount(5)
            self.results_table.setHorizontalHeaderLabels(
                ["Date", "Satellite", "Cloud %", "Resolution", "ID"]
            )
            source_col_idx = None
        
        # Disable sorting during population (vantor pattern)
        self.results_table.setSortingEnabled(False)
        
        try:
            # Clear and populate table
            self.results_table.setRowCount(0)
            
            for result_index, result in enumerate(results):
                props = result.get('properties', {})
                
                row = self.results_table.rowCount()
                self.results_table.insertRow(row)
                
                # Column 0: Date - store result_index and result data in first column item
                datetime_str = props.get('datetime', props.get('acquired', ''))
                date_str = datetime_str[:10] if datetime_str else 'N/A'
                date_item = QTableWidgetItem(date_str)
                date_item.setData(Qt.UserRole, result_index)  # Store result index for selection sync
                date_item.setData(Qt.UserRole + 1, result)    # Store full result for retrieval
                self.results_table.setItem(row, 0, date_item)
                
                # Column 1: Satellite/Platform
                platform = props.get('platform', props.get('constellation', result.get('satellite', 'Unknown')))
                self.results_table.setItem(row, 1, QTableWidgetItem(str(platform)))
                
                # Column 2: Cloud % (numeric sort)
                cloud_cover = props.get('eo:cloud_cover', props.get('cloud_cover'))
                if cloud_cover is not None:
                    cloud_str = f"{cloud_cover:.1f}" if isinstance(cloud_cover, (int, float)) else str(cloud_cover)
                    self.results_table.setItem(row, 2, NumericTableWidgetItem(cloud_str))
                else:
                    self.results_table.setItem(row, 2, QTableWidgetItem('N/A'))
                
                # Column 3: Resolution/GSD (numeric sort)
                gsd = props.get('gsd', props.get('eo:gsd', result.get('resolution')))
                if gsd:
                    # Format GSD value
                    if isinstance(gsd, (int, float)):
                        gsd_str = f"{gsd:.2f}" if gsd < 10 else f"{gsd:.0f}"
                    else:
                        gsd_str = str(gsd)
                    self.results_table.setItem(row, 3, NumericTableWidgetItem(gsd_str))
                else:
                    self.results_table.setItem(row, 3, QTableWidgetItem('N/A'))
                
                # Column 4: ID (truncate if too long)
                item_id = result.get('id', 'Unknown')
                if len(item_id) > 40:
                    item_id = item_id[:37] + '...'
                self.results_table.setItem(row, 4, QTableWidgetItem(item_id))
                
                # Column 5 (optional): Source - only in All Sources mode
                if source_col_idx is not None:
                    source_name = props.get('_source_name', 'Unknown')
                    self.results_table.setItem(row, source_col_idx, QTableWidgetItem(source_name))
            
            logger.info(f"Table populated with {len(results)} rows (source column: {'yes' if has_source_info else 'no'})")
            
            # Enable Clear Results button when there are results
            self.clear_results_btn.setEnabled(len(results) > 0)
        finally:
            # Re-enable sorting after population
            self.results_table.setSortingEnabled(True)
            self.results_table.setSortingEnabled(True)
    
    def _create_footprints_layer(self, results: List[Dict[str, Any]]):
        """Create a vector layer with footprints of search results.
        
        Args:
            results: List of STAC feature items
        """
        if not QGIS_AVAILABLE:
            logger.warning("QGIS not available, cannot create footprints layer")
            return
        
        try:
            # Create memory layer for footprints
            layer = QgsVectorLayer(
                "Polygon?crs=EPSG:4326",
                "Altair Search Results",
                "memory"
            )
            
            if not layer.isValid():
                logger.error("Failed to create footprints layer")
                return
            
            # Add fields
            provider = layer.dataProvider()
            provider.addAttributes([
                QgsField("result_index", QVariant.Int),
                QgsField("date", QVariant.String),
                QgsField("platform", QVariant.String),
                QgsField("cloud_cover", QVariant.Double),
                QgsField("collection", QVariant.String),
                QgsField("item_id", QVariant.String)
            ])
            layer.updateFields()
            
            # Add features
            features = []
            for idx, result in enumerate(results):
                geometry = result.get('geometry')
                bbox = result.get('bbox')
                
                # Try to get geometry from GeoJSON or bbox
                qgs_geom = None
                
                if geometry:
                    # Convert GeoJSON geometry to QGIS geometry
                    # Use QgsJsonUtils for compatibility (QgsGeometry.fromJson not available in older versions)
                    try:
                        # Create a temporary GeoJSON feature
                        geojson_feature = {
                            "type": "Feature",
                            "geometry": geometry,
                            "properties": {}
                        }
                        geojson_str = json.dumps(geojson_feature)
                        
                        # Parse using QgsJsonUtils
                        fields = QgsFields()
                        parsed_features = QgsJsonUtils.stringToFeatureList(geojson_str, fields)
                        
                        if parsed_features:
                            qgs_geom = parsed_features[0].geometry()
                            if qgs_geom.isNull() or qgs_geom.isEmpty():
                                qgs_geom = None
                    except Exception as e:
                        logger.debug(f"Result {idx} geometry conversion failed: {e}")
                        qgs_geom = None
                
                # Fallback: generate geometry from bbox if available
                if not qgs_geom and bbox:
                    try:
                        # bbox format: [west, south, east, north] or [xmin, ymin, xmax, ymax]
                        if len(bbox) >= 4:
                            west, south, east, north = bbox[0], bbox[1], bbox[2], bbox[3]
                            
                            # Create polygon from bbox
                            rect = QgsRectangle(west, south, east, north)
                            qgs_geom = QgsGeometry.fromRect(rect)
                            
                            logger.debug(f"Result {idx} - generated geometry from bbox: [{west:.4f}, {south:.4f}, {east:.4f}, {north:.4f}]")
                    except Exception as e:
                        logger.debug(f"Result {idx} bbox conversion failed: {e}")
                        qgs_geom = None
                
                # Skip if no valid geometry could be created
                if not qgs_geom or qgs_geom.isNull() or qgs_geom.isEmpty():
                    logger.debug(f"Result {idx} has no valid geometry or bbox, skipping")
                    continue
                
                # Create feature
                feature = QgsFeature(layer.fields())
                feature.setGeometry(qgs_geom)
                
                # Set attributes
                props = result.get('properties', {})
                datetime_str = props.get('datetime', '')
                date_str = datetime_str[:10] if datetime_str else ''
                
                feature.setAttribute("result_index", idx)
                feature.setAttribute("date", date_str)
                feature.setAttribute("platform", props.get('platform', props.get('constellation', '')))
                feature.setAttribute("cloud_cover", props.get('eo:cloud_cover', props.get('cloud_cover', -1)))
                feature.setAttribute("collection", result.get('collection', ''))
                feature.setAttribute("item_id", result.get('id', ''))
                
                features.append(feature)
            
            if not features:
                logger.warning("No valid geometries found in results")
                return
            
            # Add features to layer
            provider.addFeatures(features)
            layer.updateExtents()
            
            # Style the layer
            self._apply_footprints_style(layer)
            
            # Remove old footprints layer if it exists
            if self.footprints_layer and self._is_footprints_layer_valid():
                try:
                    QgsProject.instance().removeMapLayer(self.footprints_layer.id())
                except RuntimeError:
                    pass
            
            # Add layer to project
            QgsProject.instance().addMapLayer(layer, addToLegend=True)
            
            # Store reference and connect signals
            self.footprints_layer = layer
            self.footprints_layer.selectionChanged.connect(self._on_layer_selection_changed)
            self.footprints_layer.willBeDeleted.connect(self._on_footprints_layer_deleted)
            
            # Build feature ID mapping
            self._build_feature_id_mapping()
            
            # Enable selection mode button
            self.select_from_map_btn.setEnabled(True)
            
            # Auto-zoom to layer extent
            self._zoom_to_layer_extent(layer)
            
            logger.info(f"Created footprints layer with {len(features)} features")
            
        except Exception as e:
            logger.error(f"Error creating footprints layer: {e}", exc_info=True)
    
    def _apply_footprints_style(self, layer):
        """Apply semi-transparent styling to footprints layer.
        
        Args:
            layer: QgsVectorLayer to style
        """
        if not QGIS_AVAILABLE or not QgsFillSymbol:
            logger.warning("QGIS modules not available for styling")
            return
        
        try:
            if layer is None or layer.renderer() is None:
                return
            
            # Get opacity from settings (default 80%)
            opacity = self.settings.value("AltairEOData/opacity", 80, type=int)
            
            # Create fill symbol with semi-transparent blue
            symbol = QgsFillSymbol.createSimple({
                "color": "31,120,180,128",  # Blue with transparency
                "outline_color": "0,0,255,255",  # Solid blue border
                "outline_width": "0.5",
            })
            
            # Set opacity (0.0 - 1.0)
            try:
                symbol.setOpacity(opacity / 100.0)
            except Exception:
                # Fallback if setOpacity not available
                pass
            
            # Apply symbol to renderer
            renderer = layer.renderer()
            if renderer is not None:
                renderer.setSymbol(symbol)
            
            layer.triggerRepaint()
            logger.debug(f"Applied footprints style with opacity {opacity}%")
            
        except Exception as e:
            logger.warning(f"Failed to apply footprints style: {e}")
    
    def _zoom_to_layer_extent(self, layer):
        """Zoom map canvas to the extent of the layer respecting CRS.
        
        Args:
            layer: QgsVectorLayer to zoom to
        """
        try:
            if not layer or not layer.isValid():
                return
            
            canvas = self.iface.mapCanvas()
            extent = layer.extent()
            
            # Transform extent from layer CRS to map CRS if needed
            layer_crs = layer.crs()
            canvas_crs = canvas.mapSettings().destinationCrs()
            
            if layer_crs != canvas_crs:
                transform = QgsCoordinateTransform(layer_crs, canvas_crs, QgsProject.instance())
                extent = transform.transformBoundingBox(extent)
            
            # Add 10% buffer for better visualization
            extent.scale(1.1)
            
            canvas.setExtent(extent)
            canvas.refresh()
            
            logger.info(f"Zoomed to layer extent: {extent.toString()}")
            
        except Exception as e:
            logger.warning(f"Failed to zoom to layer extent: {e}")

    def _get_selected_results(self):
        """Get selected result items from table"""
        selected_items = []
        selected_rows = self.results_table.selectionModel().selectedRows()
        
        for model_index in selected_rows:
            row = model_index.row()
            # Get the stored result data from item
            item = self.results_table.item(row, 0)
            if item:
                result_data = item.data(Qt.UserRole + 1)
                if result_data:
                    selected_items.append(result_data)
        
        return selected_items
    
    def _is_footprints_layer_valid(self):
        """Check if the cached footprints layer reference is still valid."""
        if self.footprints_layer is None:
            return False
        try:
            _ = self.footprints_layer.id()
            return True
        except RuntimeError:
            self.footprints_layer = None
            return False
    
    def _build_feature_id_mapping(self):
        """Build mapping between layer feature IDs and result indices."""
        self._feature_id_to_result_index = {}
        self._result_index_to_feature_id = {}
        
        if not self._is_footprints_layer_valid():
            logger.warning("Cannot build feature mapping: layer is invalid")
            return
        
        try:
            # Iterate through all features in the layer and build mapping
            for feature in self.footprints_layer.getFeatures():
                fid = feature.id()
                # Get result_index from feature attributes
                result_index = feature.attribute('result_index')
                if result_index is not None:
                    self._feature_id_to_result_index[fid] = result_index
                    self._result_index_to_feature_id[result_index] = fid
            
            logger.info(f"Built feature ID mapping: {len(self._feature_id_to_result_index)} features mapped")
            logger.debug(f"Feature ID to Result Index mapping sample: {dict(list(self._feature_id_to_result_index.items())[:3])}")
        except Exception as e:
            logger.error(f"Failed to build feature ID mapping: {e}", exc_info=True)
    
    def _on_layer_selection_changed(self):
        """Sync map selection to table selection (map -> table)."""
        if self._updating_selection or not self._is_footprints_layer_valid():
            return
        
        self._updating_selection = True
        try:
            selected_ids = set(self.footprints_layer.selectedFeatureIds())
            logger.info(f"Layer selection changed: {len(selected_ids)} features selected")
            logger.debug(f"Selected feature IDs: {selected_ids}")
            
            if not selected_ids:
                self.results_table.clearSelection()
                return

            # Use the pre-built mapping if available, otherwise build it
            if not self._feature_id_to_result_index:
                logger.warning("Feature ID mapping is empty, rebuilding...")
                self._build_feature_id_mapping()

            # Convert feature IDs to result indices
            selected_indices = set()
            for fid in selected_ids:
                result_index = self._feature_id_to_result_index.get(fid)
                if result_index is not None:
                    selected_indices.add(result_index)
                    logger.debug(f"Feature ID {fid} -> Result index {result_index}")
                else:
                    logger.warning(f"Feature ID {fid} not found in mapping")
            
            logger.info(f"Selected result indices: {selected_indices}")

            # Find rows with matching result indices and select them (using item data)
            selection_model = self.results_table.selectionModel()
            selection_model.clearSelection()
            first_row = None
            matched_rows = []
            
            for row_idx in range(self.results_table.rowCount()):
                # Get result index from item data
                item = self.results_table.item(row_idx, 0)
                if item:
                    table_result_index = item.data(Qt.UserRole)
                    if table_result_index in selected_indices:
                        logger.debug(f"Row {row_idx}: result_index {table_result_index} MATCHES")
                        # Select the entire row
                        selection_model.select(
                            self.results_table.model().index(row_idx, 0),
                            selection_model.Select | selection_model.Rows
                        )
                        matched_rows.append(row_idx)
                        if first_row is None:
                            first_row = row_idx
                    else:
                        logger.debug(f"Row {row_idx}: result_index {table_result_index} does not match")
            
            logger.info(f"Matched {len(matched_rows)} rows: {matched_rows}")

            # Scroll to first selected row
            if first_row is not None:
                try:
                    self.results_table.scrollTo(
                        self.results_table.model().index(first_row, 0),
                        QAbstractItemView.PositionAtCenter
                    )
                    logger.debug(f"Scrolled to row {first_row}")
                except Exception as scroll_error:
                    logger.warning(f"Failed to scroll to row {first_row}: {scroll_error}")
        except Exception as e:
            logger.error(f"Error in layer selection sync: {e}", exc_info=True)
        finally:
            self._updating_selection = False
    
    def _on_footprints_layer_deleted(self):
        """Clear cached reference when the layer is deleted externally."""
        self.footprints_layer = None
        self._feature_id_to_result_index = {}
        self._result_index_to_feature_id = {}
        
        # Disable selection mode button and deactivate if active
        self.select_from_map_btn.setEnabled(False)
        if self.select_from_map_btn.isChecked():
            self.select_from_map_btn.setChecked(False)
        
        logger.info("Footprints layer deleted, cleared references")
    
    def _on_selection_mode_toggled(self, checked):
        """Handle selection mode toggle."""
        if not self._is_footprints_layer_valid():
            self.select_from_map_btn.setChecked(False)
            QMessageBox.warning(
                self,
                "Warning",
                "No footprints layer loaded.\n"
                "Run a search first to load footprints."
            )
            return
        
        if checked:
            self._activate_selection_mode()
        else:
            self._deactivate_selection_mode()
    
    def _activate_selection_mode(self):
        """Activate interactive selection mode from map."""
        try:
            canvas = self.iface.mapCanvas()
            
            # Verify layer validity
            if not self.footprints_layer or not self.footprints_layer.isValid():
                logger.error("Footprints layer is not valid, cannot activate selection mode")
                self.select_from_map_btn.setChecked(False)
                return
            
            # Always create a new selection tool (old one may have been deleted by QGIS)
            self.selection_tool = FootprintSelectionTool(
                canvas,
                self.footprints_layer
            )
            logger.info(f"FootprintSelectionTool created with layer: {self.footprints_layer.name()}")
            logger.info(f"Layer feature count: {sum(1 for _ in self.footprints_layer.getFeatures())}")
            
            # Store previous tool and activate selection tool
            self._previous_map_tool = canvas.mapTool()
            canvas.setMapTool(self.selection_tool)
            logger.info("Selection tool set as active map tool")
            
            self.select_from_map_btn.setText("✓ Map Selection Active")
            self.select_from_map_btn.setStyleSheet("QPushButton { background-color: #4CAF50; color: white; }")
            logger.info("Selection mode activated")
        except Exception as e:
            logger.error(f"Error activating selection mode: {e}", exc_info=True)
            self.select_from_map_btn.setChecked(False)
    
    def _deactivate_selection_mode(self):
        """Deactivate interactive selection mode."""
        try:
            canvas = self.iface.mapCanvas()
            
            # Restore previous tool (check if it still exists)
            if self._previous_map_tool:
                try:
                    # Try to set the previous tool, but it might have been deleted
                    canvas.setMapTool(self._previous_map_tool)
                    logger.info("Restored previous map tool")
                except RuntimeError:
                    # Previous tool was deleted, just unset the current tool
                    canvas.unsetMapTool(self.selection_tool)
                    logger.warning("Previous map tool was deleted, unset current tool")
                self._previous_map_tool = None
            
            self.select_from_map_btn.setText("Select from Map")
            self.select_from_map_btn.setStyleSheet("")
            logger.info("Selection mode deactivated")
        except Exception as e:
            logger.error(f"Error deactivating selection mode: {e}", exc_info=True)

    def _zoom_to_selected(self):
        """Zoom map to selected imagery footprints"""
        selected = self._get_selected_results()
        if not selected:
            return
        
        if not QGIS_AVAILABLE:
            logger.error("QGIS modules not available for zoom operation")
            return
        
        try:
            # Calculate bounding box from all selected footprints
            min_x = min_y = float("inf")
            max_x = max_y = float("-inf")
            
            for result in selected:
                # Try to get geometry from STAC result
                geometry = result.get("geometry")
                if not geometry:
                    continue
                
                geom_type = geometry.get("type", "")
                coords = geometry.get("coordinates", [])
                
                if not coords:
                    continue
                
                # Handle different geometry types
                if geom_type == "Polygon":
                    # coords is [[lon, lat], [lon, lat], ...]
                    for ring in coords:
                        for coord in ring:
                            if len(coord) >= 2:
                                min_x = min(min_x, coord[0])
                                max_x = max(max_x, coord[0])
                                min_y = min(min_y, coord[1])
                                max_y = max(max_y, coord[1])
                
                elif geom_type == "MultiPolygon":
                    # coords is [[[lon, lat], ...], ...]
                    for polygon in coords:
                        for ring in polygon:
                            for coord in ring:
                                if len(coord) >= 2:
                                    min_x = min(min_x, coord[0])
                                    max_x = max(max_x, coord[0])
                                    min_y = min(min_y, coord[1])
                                    max_y = max(max_y, coord[1])
                
                elif geom_type == "Point":
                    # coords is [lon, lat]
                    if len(coords) >= 2:
                        min_x = min(min_x, coords[0])
                        max_x = max(max_x, coords[0])
                        min_y = min(min_y, coords[1])
                        max_y = max(max_y, coords[1])
            
            if min_x == float("inf"):
                logger.warning("No valid geometries found in selected results")
                QMessageBox.warning(
                    self,
                    "Zoom Not Available",
                    "No valid geometry found in selected results."
                )
                return
            
            # Create extent and zoom
            canvas = self.iface.mapCanvas()
            extent = QgsRectangle(min_x, min_y, max_x, max_y)
            
            # Transform from WGS84 (STAC uses EPSG:4326) if needed
            source_crs = QgsCoordinateReferenceSystem("EPSG:4326")
            dest_crs = canvas.mapSettings().destinationCrs()
            
            if source_crs != dest_crs:
                transform = QgsCoordinateTransform(source_crs, dest_crs, QgsProject.instance())
                extent = transform.transformBoundingBox(extent)
            
            # Add 10% buffer for better visualization
            extent.scale(1.1)
            
            canvas.setExtent(extent)
            canvas.refresh()
            
            logger.info(f"Zoomed to {len(selected)} selected footprints")
            
        except Exception as e:
            logger.error(f"Error zooming to selected footprints: {e}", exc_info=True)
            QMessageBox.critical(
                self,
                "Zoom Error",
                f"Error zooming to selected footprints:\n{str(e)}"
            )

    def _preview_imagery(self):
        """Load COG (Cloud Optimized GeoTIFF) assets from selected results as activable layers"""
        selected = self._get_selected_results()
        if not selected:
            QMessageBox.warning(
                self,
                "No Selection",
                "Select one or more images from the table."
            )
            return
        
        if not QGIS_AVAILABLE:
            QMessageBox.critical(
                self,
                "Error",
                "QGIS modules not available for preview loading."
            )
            return
        
        # Disable buttons during loading
        self.preview_btn.setEnabled(False)
        self.download_btn.setEnabled(False)
        QApplication.setOverrideCursor(Qt.WaitCursor)
        
        # Create progress dialog for better UX
        progress = None
        if len(selected) > 3:
            from PyQt5.QtWidgets import QProgressDialog
            progress = QProgressDialog("Loading COG assets...", "Cancel", 0, len(selected), self)
            progress.setWindowModality(Qt.WindowModal)
            progress.setMinimumDuration(0)
        
        loaded_count = 0
        no_cog_count = 0
        failed_count = 0
        
        try:
            for idx, result in enumerate(selected):
                # Update progress
                if progress:
                    if progress.wasCanceled():
                        break
                    progress.setValue(idx)
                    QApplication.processEvents()  # Keep UI responsive
                
                props = result.get('properties', {})
                assets = result.get('assets', {})
                
                # Universal COG/Raster asset lookup based on STAC MIME types
                # Following STAC Best Practices for Asset Media Types
                cog_url = None
                asset_name_used = None
                asset_mime_type = None
                
                # STAC standard MIME types for COG (PRIORITY ORDER):
                # 1. Cloud-Optimized GeoTIFF (preferred)
                # 2. GeoTIFF (any profile)
                # 3. JPEG2000 (Copernicus/Sentinel format)
                # 4. Generic image/tiff
                
                cog_mime_priorities = [
                    # Cloud-Optimized GeoTIFF (STAC best practice)
                    'image/tiff; application=geotiff; profile=cloud-optimized',
                    'image/tiff;application=geotiff;profile=cloud-optimized',  # No spaces variant
                    'image/tiff; profile=cloud-optimized',
                    # GeoTIFF with specific profiles
                    'image/tiff; application=geotiff',
                    'image/tiff;application=geotiff',
                    # JPEG2000 (Copernicus/ESA format)
                    'image/jp2',
                    'image/jpeg2000',
                    'application/jp2',
                    # Generic GeoTIFF
                    'image/tiff',
                    'image/geotiff',
                ]
                
                # Scan assets for COG by MIME type (universal approach)
                best_match_score = -1
                
                for asset_name, asset in assets.items():
                    if not isinstance(asset, dict):
                        continue
                    
                    href = asset.get('href', '')
                    if not href:
                        continue
                    
                    # Get asset MIME type
                    asset_type = asset.get('type', '').strip().lower()
                    
                    # Check against priority MIME types
                    for priority_idx, mime_type in enumerate(cog_mime_priorities):
                        if mime_type in asset_type or asset_type == mime_type:
                            # Score: lower index = higher priority
                            score = len(cog_mime_priorities) - priority_idx
                            
                            # Boost score for visual/data/analytic assets (prefer over bands)
                            if asset_name.lower() in ('visual', 'data', 'analytic', 'tci', 'overview', 'cog'):
                                score += 100
                            
                            # Boost score for True Color composites
                            if 'tci' in asset_name.lower():
                                score += 50
                            
                            if score > best_match_score:
                                best_match_score = score
                                cog_url = href
                                asset_name_used = asset_name
                                asset_mime_type = asset_type
                                logger.debug(f"COG candidate: {asset_name} (type={asset_type}, score={score})")
                
                # Fallback: If no MIME type match, check file extensions
                if not cog_url:
                    logger.debug("No MIME type match, trying file extension fallback")
                    for asset_name, asset in assets.items():
                        if not isinstance(asset, dict):
                            continue
                        
                        href = asset.get('href', '')
                        if not href:
                            continue
                        
                        href_lower = href.lower()
                        
                        # Check for raster file extensions
                        if href_lower.endswith(('.tif', '.tiff', '.cog', '.jp2', '.j2k')):
                            # Prefer visual/data assets
                            score = 10
                            if asset_name.lower() in ('visual', 'data', 'analytic', 'tci', 'overview', 'cog'):
                                score = 50
                            
                            if score > best_match_score:
                                best_match_score = score
                                cog_url = href
                                asset_name_used = asset_name
                                asset_type = asset.get('type', 'unknown')
                                logger.debug(f"COG candidate (by extension): {asset_name} (href={href[:50]}..., score={score})")
                
                # Final check: log best match
                if cog_url:
                    logger.info(f"✓ Selected COG asset: '{asset_name_used}' (type={asset_mime_type or 'extension-based'}, score={best_match_score})")
                    logger.debug(f"  URL: {cog_url[:100]}...")
                
                if not cog_url:
                    no_cog_count += 1
                    logger.warning(f"Result {idx+1} ({result.get('id', 'unknown')}): No COG/GeoTIFF asset found")
                    logger.debug(f"Available assets: {list(assets.keys())}")
                    continue
                
                # Resolve relative URLs to absolute HTTP URLs for public S3 access
                if cog_url.startswith(('./', '../')):
                    logger.debug(f"Resolving relative URL: {cog_url}")
                    
                    connector_id = result.get('_source', '').lower()
                    clean_path = cog_url.lstrip('./')
                    
                    # PRIORITY 1: Always try STAC self link first (most accurate)
                    # This handles subdirectories like /ard/acquisition_collections/
                    base_url = None
                    stac_feature = result.get('stac_feature', {})
                    for link in stac_feature.get('links', []):
                        if link.get('rel') == 'self' and link.get('href'):
                            # Remove items.geojson or filename to get base directory
                            href = link['href']
                            base_url = '/'.join(href.split('/')[:-1])
                            logger.info(f"✅ Resolved URL from STAC self link")
                            logger.debug(f"   Self link: {href}")
                            break
                    
                    # PRIORITY 2: Connector-specific fallback patterns (if no self link)
                    if not base_url:
                        event_id = result.get('event_id') or result.get('collection', '')
                        
                        # ICEYE, Umbra, Capella: No fallback (require self link)
                        logger.error(f"❌ Cannot resolve relative URL: {cog_url}")
                        logger.error(f"   Connector: {connector_id}")
                        logger.error(f"   Event ID: {event_id}")
                        logger.error(f"   No STAC 'self' link found in feature")
                        continue
                    
                    # Construct final URL
                    cog_url = f"{base_url}/{clean_path}"
                    logger.info(f"   Filename: {clean_path}")
                    logger.info(f"   Full URL: {cog_url[:120]}...")
                    
                    # Normalize S3 URL (remove dualstack if present for consistency)
                    if '.s3.dualstack.' in cog_url:
                        cog_url = cog_url.replace('.s3.dualstack.', '.s3.')
                        logger.debug(f"   Normalized S3 URL (removed dualstack): {cog_url[:120]}...")
                
                # Create descriptive layer name
                collection = props.get('collection', result.get('collection', 'unknown'))
                item_id = result.get('id', 'unknown')[:20]
                date_str = (props.get('datetime', '') or '')[:10] or 'no-date'
                
                layer_name = f"COG - {collection} - {item_id} - {asset_name_used} ({date_str})"
                
                logger.info(f"Loading COG asset '{asset_name_used}' from {cog_url[:100]}...")
                
                # Detect format for logging
                is_jp2 = cog_url.lower().endswith(('.jp2', '.j2k'))
                format_type = "JPEG2000" if is_jp2 else "GeoTIFF"
                logger.info(f"  Format: {format_type}")
                
                # Check if Copernicus requires authentication
                needs_copernicus_auth = 'dataspace.copernicus.eu' in cog_url
                if needs_copernicus_auth and hasattr(self, 'copernicus_connector'):
                    # Ensure valid token
                    if self.copernicus_connector._ensure_valid_token():
                        token = self.copernicus_connector._access_token
                        # Configure GDAL to use OAuth2 token
                        import os
                        os.environ['GDAL_HTTP_HEADERS'] = f'Authorization: Bearer {token}'
                        logger.debug("Copernicus: GDAL configured with OAuth2 token for COG access")
                    else:
                        logger.warning("Copernicus: Failed to get valid token for COG access")
                
                # Validate URL is HTTP/HTTPS (required for vsicurl)
                if not cog_url.startswith(('http://', 'https://')):
                    logger.error(f"❌ Invalid URL scheme: {cog_url[:100]}")
                    logger.error(f"   vsicurl requires HTTP/HTTPS URLs")
                    failed_count += 1
                    continue
                
                # Check if URL is from S3 (AWS Open Data)
                is_s3_url = 's3.amazonaws.com' in cog_url or 's3-us-west-2.amazonaws.com' in cog_url
                if is_s3_url:
                    # Extract bucket name for logging
                    if 'iceye-open-data-catalog' in cog_url:
                        bucket_name = 'iceye-open-data-catalog (ICEYE SAR)'
                    elif 'umbra-open-data-catalog' in cog_url:
                        bucket_name = 'umbra-open-data-catalog (Umbra SAR)'
                    elif 'capella-open-data' in cog_url:
                        bucket_name = 'capella-open-data (Capella SAR)'
                    else:
                        bucket_name = 'unknown S3 bucket'
                    
                    logger.info(f"  ☁️  AWS S3 public bucket: {bucket_name}")
                    logger.info(f"  📡 Using GDAL vsicurl for HTTP streaming (no credentials needed)")
                    logger.info(f"  🔗 {cog_url[:100]}...")
                
                # Load COG using GDAL vsicurl (streaming HTTP access to public S3)
                # This is the qgis-maxar-plugin pattern: /vsicurl/{https-url}
                cog_url_gdal = f"/vsicurl/{cog_url}"
                logger.debug(f"  GDAL path: {cog_url_gdal[:100]}")
                
                layer = QgsRasterLayer(cog_url_gdal, layer_name, "gdal")
                
                if layer.isValid():
                    QgsProject.instance().addMapLayer(layer)
                    layer.setCustomProperty("altair_cog_preview", True)
                    layer.setCustomProperty("altair_asset_name", asset_name_used)
                    layer.setCustomProperty("altair_source_url", cog_url)
                    
                    # Set opacity for overlay
                    try:
                        layer.renderer().setOpacity(0.8)
                        layer.triggerRepaint()
                    except Exception as e:
                        logger.debug(f"Could not set opacity: {e}")
                    
                    self._loaded_layers.append(layer_name)
                    loaded_count += 1
                    logger.info(f"✅ Loaded COG layer: {layer_name}")
                else:
                    # Retry without vsicurl (direct URL)
                    logger.debug(f"vsicurl failed, trying direct URL...")
                    layer = QgsRasterLayer(cog_url, layer_name, "gdal")
                    if layer.isValid():
                        QgsProject.instance().addMapLayer(layer)
                        layer.setCustomProperty("altair_cog_preview", True)
                        layer.setCustomProperty("altair_asset_name", asset_name_used)
                        layer.setCustomProperty("altair_source_url", cog_url)
                        try:
                            layer.renderer().setOpacity(0.8)
                        except Exception:
                            pass
                        self._loaded_layers.append(layer_name)
                        loaded_count += 1
                        logger.info(f"✅ Loaded COG layer (direct): {layer_name}")
                    else:
                        failed_count += 1
                        error_msg = layer.error().message() if layer.error() else "Unknown GDAL error"
                        logger.error(f"❌ Failed to load COG: {layer_name}")
                        logger.error(f"   URL: {cog_url[:100]}...")
                        logger.error(f"   Format: {format_type}")
                        logger.error(f"   GDAL error: {error_msg}")
                        
                        # Provide specific guidance based on error
                        if is_s3_url and "404" in error_msg:
                            logger.warning("   S3 object not found - URL may be incorrect")
                        elif is_s3_url and ("403" in error_msg or "Access Denied" in error_msg):
                            logger.warning("   S3 access denied - bucket may require authentication")
                        elif is_jp2 and "not recognized" in error_msg.lower():
                            logger.warning("   JPEG2000 driver not available - install GDAL with JP2 support")
                        elif needs_copernicus_auth and "401" in error_msg:
                            logger.warning("   Copernicus authentication failed - check token validity")
            
            # Clean up GDAL environment (remove Copernicus authentication headers only)
            import os
            if 'GDAL_HTTP_HEADERS' in os.environ:
                del os.environ['GDAL_HTTP_HEADERS']
                logger.debug("Cleaned up GDAL HTTP headers")
            
            QApplication.restoreOverrideCursor()
            
            # Re-enable buttons
            self.preview_btn.setEnabled(True)
            self.download_btn.setEnabled(True)
            
            # Refresh canvas
            if self.iface and hasattr(self.iface, 'mapCanvas'):
                self.iface.mapCanvas().refresh()
            
            # Report results
            logger.info(
                f"COG loading complete: {loaded_count} loaded, "
                f"{no_cog_count} no COG asset, {failed_count} failed"
            )
            
            if loaded_count > 0:
                self._set_status(
                    f"✅ Loaded {loaded_count} COG layer(s) - Click layer to activate/deactivate",
                    "color: #00ffbf; font-size: 10px; font-weight: 500;"
                )
                
                # Show success message
                QMessageBox.information(
                    self,
                    "COG Layers Loaded",
                    f"✓ Successfully loaded: {loaded_count} COG layer(s)\n"
                    + (f"⚠ No COG assets: {no_cog_count}\n" if no_cog_count > 0 else "")
                    + (f"✗ Failed: {failed_count}\n\n" if failed_count > 0 else "\n")
                    + "COG layers loaded with 80% opacity.\n"
                    + "Click on layers in the layer panel to activate/deactivate them.\n"
                    + "Use 'Zoom to Selection' to view the imagery.",
                    QMessageBox.Ok
                )
            else:
                QMessageBox.warning(
                    self,
                    "No COG Layers Loaded",
                    f"Unable to load COG imagery.\n\n"
                    f"No COG assets found: {no_cog_count}\n"
                    f"Failed to load: {failed_count}\n\n"
                    f"Note: Not all results may have COG assets available.\n"
                    f"Try selecting different results or use 'Load Layer' button."
                )
        
        except Exception as e:
            QApplication.restoreOverrideCursor()
            self.preview_btn.setEnabled(True)
            self.load_nitf_btn.setEnabled(True)
            self.load_btn.setEnabled(True)
            
            logger.error(f"Error loading preview: {e}", exc_info=True)
            QMessageBox.critical(
                self,
                "Error",
                f"Error during preview loading:\n{str(e)}"
            )


    def _download_imagery(self):
        """Download selected COG imagery to local folder"""
        import os
        import urllib.request
        from pathlib import Path
        
        selected = self._get_selected_results()
        if not selected:
            QMessageBox.warning(
                self,
                "No Selection",
                "Select one or more images from the table."
            )
            return
        
        # Get download folder from settings or ask user
        download_folder = self.settings.value("altair/download_folder", "")
        
        if not download_folder or not os.path.exists(download_folder):
            download_folder = QFileDialog.getExistingDirectory(
                self,
                "Select Download Folder",
                os.path.expanduser("~"),
                QFileDialog.ShowDirsOnly
            )
            
            if not download_folder:
                return  # User cancelled
            
            # Save folder to settings
            self.settings.setValue("altair/download_folder", download_folder)
        
        # Disable buttons during download
        self.download_btn.setEnabled(False)
        self.preview_btn.setEnabled(False)
        QApplication.setOverrideCursor(Qt.WaitCursor)
        
        # Create progress dialog
        from PyQt5.QtWidgets import QProgressDialog
        progress = QProgressDialog("Downloading COG files...", "Cancel", 0, len(selected), self)
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)
        
        downloaded_count = 0
        no_cog_count = 0
        failed_count = 0
        downloaded_files = []
        
        try:
            for idx, result in enumerate(selected):
                # Update progress
                if progress.wasCanceled():
                    break
                progress.setValue(idx)
                progress.setLabelText(f"Downloading {idx+1}/{len(selected)}...")
                QApplication.processEvents()
                
                props = result.get('properties', {})
                assets = result.get('assets', {})
                
                # Universal COG/Raster asset lookup (same logic as Load COG)
                cog_url = None
                asset_name_used = None
                asset_mime_type = None
                
                # STAC standard MIME types for COG (PRIORITY ORDER)
                cog_mime_priorities = [
                    'image/tiff; application=geotiff; profile=cloud-optimized',
                    'image/tiff;application=geotiff;profile=cloud-optimized',
                    'image/tiff; profile=cloud-optimized',
                    'image/tiff; application=geotiff',
                    'image/tiff;application=geotiff',
                    'image/jp2',
                    'image/jpeg2000',
                    'application/jp2',
                    'image/tiff',
                    'image/geotiff',
                ]
                
                # Scan assets for COG by MIME type
                best_match_score = -1
                
                for asset_name, asset in assets.items():
                    if not isinstance(asset, dict):
                        continue
                    
                    href = asset.get('href', '')
                    if not href:
                        continue
                    
                    asset_type = asset.get('type', '').strip().lower()
                    
                    # Check against priority MIME types
                    for priority_idx, mime_type in enumerate(cog_mime_priorities):
                        if mime_type in asset_type or asset_type == mime_type:
                            score = len(cog_mime_priorities) - priority_idx
                            
                            if asset_name.lower() in ('visual', 'data', 'analytic', 'tci', 'overview', 'cog'):
                                score += 100
                            
                            if 'tci' in asset_name.lower():
                                score += 50
                            
                            if score > best_match_score:
                                best_match_score = score
                                cog_url = href
                                asset_name_used = asset_name
                                asset_mime_type = asset_type
                
                # Fallback: file extension
                if not cog_url:
                    for asset_name, asset in assets.items():
                        if not isinstance(asset, dict):
                            continue
                        
                        href = asset.get('href', '')
                        if not href:
                            continue
                        
                        if href.lower().endswith(('.tif', '.tiff', '.cog', '.jp2', '.j2k')):
                            score = 10
                            if asset_name.lower() in ('visual', 'data', 'analytic', 'tci', 'overview', 'cog'):
                                score = 50
                            
                            if score > best_match_score:
                                best_match_score = score
                                cog_url = href
                                asset_name_used = asset_name
                                asset_mime_type = asset_type
                
                if not cog_url:
                    no_cog_count += 1
                    logger.warning(f"No COG asset found for {result.get('id', 'unknown')}")
                    continue
                
                # Resolve relative URLs using stac_feature links or result metadata
                if cog_url.startswith(('./', '../')):
                    logger.debug(f"Resolving relative URL for download: {cog_url}")
                    
                    # Try to get base URL from stac_feature links
                    stac_feature = result.get('stac_feature', {})
                    links = stac_feature.get('links', [])
                    
                    base_url = None
                    for link in links:
                        if link.get('rel') == 'self' and link.get('href'):
                            href = link['href']
                            # Remove filename to get base directory
                            base_url = '/'.join(href.split('/')[:-1])
                            logger.debug(f"Found self link base URL: {base_url}")
                            break
                    
                    if base_url:
                        # Remove leading ./ or ../
                        clean_path = cog_url.lstrip('./')
                        cog_url = f"{base_url}/{clean_path}"
                        logger.info(f"Resolved download URL to: {cog_url[:100]}...")
                    else:
                        logger.warning(f"Cannot resolve relative URL {cog_url} for download - no base URL found")
                        logger.debug(f"Result keys: {list(result.keys())}")
                        continue
                
                # Create filename
                collection = props.get('collection', result.get('collection', 'unknown'))
                item_id = result.get('id', 'unknown')
                date_str = (props.get('datetime', '') or '')[:10] or 'no-date'
                
                # Sanitize filename
                safe_collection = "".join(c for c in collection if c.isalnum() or c in ('-', '_'))
                safe_id = "".join(c for c in item_id if c.isalnum() or c in ('-', '_'))[:40]
                
                filename = f"{safe_collection}_{date_str}_{safe_id}_{asset_name_used}.tif"
                filepath = os.path.join(download_folder, filename)
                
                # Download file
                try:
                    logger.info(f"Downloading {cog_url} to {filepath}")
                    
                    # Check if Copernicus requires authentication
                    needs_copernicus_auth = 'dataspace.copernicus.eu' in cog_url
                    
                    if needs_copernicus_auth and hasattr(self, 'copernicus_connector'):
                        # Copernicus requires OAuth2 token
                        if self.copernicus_connector._ensure_valid_token():
                            token = self.copernicus_connector._access_token
                            # Create authenticated request
                            import urllib.request
                            req = urllib.request.Request(cog_url)
                            req.add_header('Authorization', f'Bearer {token}')
                            logger.debug("Copernicus: Using OAuth2 token for download")
                            
                            # Download with authentication
                            with urllib.request.urlopen(req) as response:
                                with open(filepath, 'wb') as out_file:
                                    out_file.write(response.read())
                        else:
                            logger.warning("Copernicus: Failed to get valid token for download")
                            import urllib.request
                            urllib.request.urlretrieve(cog_url, filepath)
                    else:
                        # Standard download (works for Vantor/Maxar S3 public buckets)
                        import urllib.request
                        urllib.request.urlretrieve(cog_url, filepath)
                    
                    downloaded_count += 1
                    downloaded_files.append(filepath)
                    logger.info(f"✓ Downloaded: {filename}")
                except Exception as dl_error:
                    failed_count += 1
                    logger.error(f"✗ Failed to download {filename}: {dl_error}")
            
            progress.setValue(len(selected))
            QApplication.restoreOverrideCursor()
            
            # Re-enable buttons
            self.download_btn.setEnabled(True)
            self.preview_btn.setEnabled(True)
            
            # Report results
            logger.info(
                f"Download complete: {downloaded_count} downloaded, "
                f"{no_cog_count} no COG, {failed_count} failed"
            )
            
            if downloaded_count > 0:
                self._set_status(
                    f"Downloaded {downloaded_count} COG file(s) to {download_folder}",
                    "color: #00ffbf; font-size: 10px; font-weight: 500;"
                )
                
                # Ask if user wants to load downloaded files
                reply = QMessageBox.question(
                    self,
                    "Download Complete",
                    f"✓ Downloaded: {downloaded_count} file(s)\n"
                    + (f"⚠ No COG: {no_cog_count}\n" if no_cog_count > 0 else "")
                    + (f"✗ Failed: {failed_count}\n\n" if failed_count > 0 else "\n")
                    + f"Folder: {download_folder}\n\n"
                    + "Load downloaded files as layers?",
                    QMessageBox.Yes | QMessageBox.No
                )
                
                if reply == QMessageBox.Yes and QGIS_AVAILABLE:
                    # Load downloaded files as layers
                    for filepath in downloaded_files:
                        layer_name = f"Altair Download - {Path(filepath).stem}"
                        layer = QgsRasterLayer(filepath, layer_name, "gdal")
                        if layer.isValid():
                            QgsProject.instance().addMapLayer(layer)
                            self._loaded_layers.append(layer_name)
                        else:
                            logger.warning(f"Failed to load {filepath} as layer")
                    
                    if self.iface and hasattr(self.iface, 'mapCanvas'):
                        self.iface.mapCanvas().refresh()
            else:
                QMessageBox.warning(
                    self,
                    "No Files Downloaded",
                    f"Unable to download selected images.\n\n"
                    f"No COG assets: {no_cog_count}\n"
                    f"Failed: {failed_count}\n\n"
                    f"Verify that results contain valid COG assets."
                )
        
        except Exception as e:
            QApplication.restoreOverrideCursor()
            self.download_btn.setEnabled(True)
            self.preview_btn.setEnabled(True)
            
            logger.error(f"Error downloading imagery: {e}", exc_info=True)
            QMessageBox.critical(
                self,
                "Error",
                f"Error during download:\n{str(e)}"
            )


    def _clear_layers(self):
        """Clear all Altair layers from the project"""
        if not self._loaded_layers and QgsProject:
            # Check for any Altair layers in project
            layers_to_remove = []
            for layer_id, layer in QgsProject.instance().mapLayers().items():
                if layer.name().startswith("Altair") or layer.name().startswith("Preview"):
                    layers_to_remove.append(layer_id)
            
            if not layers_to_remove:
                self._set_status(
                    "No layers to remove",
                    "color: #b0b0b0; font-size: 10px; font-weight: 500;"
                )
                return
            
            for layer_id in layers_to_remove:
                QgsProject.instance().removeMapLayer(layer_id)
        else:
            # Remove tracked layers
            if QgsProject:
                for layer_id, layer in list(QgsProject.instance().mapLayers().items()):
                    if layer.name() in self._loaded_layers:
                        QgsProject.instance().removeMapLayer(layer_id)
        
        # Clear tracking
        self._loaded_layers.clear()
        
        # Clear table selection
        self.results_table.clearSelection()
        
        # Refresh canvas
        if self.iface and hasattr(self.iface, 'mapCanvas'):
            self.iface.mapCanvas().refresh()
        
        self._set_status(
            "All Altair layers removed",
            "color: #b0b0b0; font-size: 10px; font-weight: 500;"
        )
        
        logger.info("Cleared all Altair and Preview layers")
    
    def cleanup(self):
        """Cleanup resources when closing the dock widget"""
        logger.info("Cleaning up Altair dock widget resources")
        
        try:
            # Deactivate selection mode if active
            if self.select_from_map_btn.isChecked():
                self.select_from_map_btn.setChecked(False)
            
            # Disconnect layer signals to prevent errors
            if self.footprints_layer is not None:
                try:
                    self.footprints_layer.selectionChanged.disconnect(self._on_layer_selection_changed)
                except (RuntimeError, TypeError):
                    pass
                try:
                    self.footprints_layer.willBeDeleted.disconnect(self._on_footprints_layer_deleted)
                except (RuntimeError, TypeError):
                    pass
                self.footprints_layer = None
        except Exception as e:
            logger.debug(f"Error during layer cleanup: {e}")
        
        # Clear any temporary resources
        self._search_results.clear()
        self._loaded_layers.clear()
        self._feature_id_to_result_index.clear()
        self._result_index_to_feature_id.clear()
        
        # Cleanup QgsExtentWidget (handled automatically by Qt)
        if self.extent_widget:
            logger.debug("QgsExtentWidget will be cleaned up by Qt parent")
    
    def closeEvent(self, event):
        """Handle dock widget close event"""
        self.cleanup()
        event.accept()
