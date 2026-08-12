"""
Altair EO Data Settings Dock Widget
"""
import importlib

from qgis.PyQt.QtWidgets import (
    QDockWidget, QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QLineEdit, QPushButton, QCheckBox, QSpinBox, QComboBox,
    QTabWidget, QGroupBox, QFileDialog, QMessageBox, QApplication, QScrollArea
)
from qgis.PyQt.QtCore import QSettings, Qt, pyqtSignal
from qgis.PyQt.QtGui import QFont
from ..logger import get_logger

logger = get_logger('gui.settings')

try:
    from ..secrets.secure_storage import get_secure_storage
except ImportError:
    # Fallback if secure_storage not available
    logger.warning("Secure storage not available, using fallback")
    def get_secure_storage():
        return None


class SettingsDockWidget(QDockWidget):
    """Dock widget for plugin settings adapted for KADAS."""
    
    # Signal emitted when settings are saved
    settings_saved = pyqtSignal()
    
    SETTINGS_PREFIX = "AltairEOData/"

    def __init__(self, iface, parent=None):
        super().__init__("Settings", parent)
        logger.info("Initializing settings dock widget")
        
        self.setObjectName("AltairEODataSettingsDock")
        self.iface = iface
        self.settings = QSettings()
        self.secure_storage = get_secure_storage()
        
        # Setup dockable behavior - kadas-vantor pattern
        self.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        
        self._setup_ui()

    def _setup_ui(self):
        """Set up the settings UI"""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.setWidget(scroll)

        widget = QWidget()
        scroll.setWidget(widget)
        widget.setStyleSheet(
            "QLabel { color: #303030; }"
            "QCheckBox { color: #303030; }"
            "QGroupBox { color: #303030; font-weight: bold; }"
        )
        
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)
        layout.setAlignment(Qt.AlignTop)
        
        # Header
        header_label = QLabel("Plugin Settings")
        header_font = QFont()
        header_font.setPointSize(12)
        header_font.setBold(True)
        header_label.setFont(header_font)
        header_label.setAlignment(Qt.AlignCenter)
        header_label.setStyleSheet("color: #1f1f1f;")
        layout.addWidget(header_label)
        
        # Tab widget for organized settings
        tab_widget = QTabWidget()
        layout.addWidget(tab_widget)
        
        # Security info label
        if self.secure_storage:
            storage_method = self.secure_storage.get_storage_method()
            security_label = QLabel(f"🔒 Protected credentials: {storage_method}")
            security_label.setStyleSheet("color: #00ff00; font-size: 9px; font-style: italic;")
            layout.addWidget(security_label)
        
        # Build connector panels and add only those backed by available connectors.
        provider_panels = [
            ("oneatlas", "OneAtlas", self._create_oneatlas_tab),
            ("planet", "Planet", self._create_planet_tab),
            ("vantor", "Vantor", self._create_vantor_tab),
            ("iceye", "ICEYE", self._create_iceye_tab),
            ("umbra", "Umbra", self._create_umbra_tab),
            (
                "element84_stac",
                "Earth Search",
                self._create_element84_stac_tab,
            ),
            (
                "planetary_computer_stac",
                "Planetary Computer",
                self._create_planetary_computer_stac_tab,
            ),
            ("nasa_earthdata", "NASA EarthData", self._create_nasa_tab),
            ("capella", "Capella Space", self._create_capella_tab),
            ("jilin_gaofen_stac", "Jilin-1 Gaofen", self._create_jilin_tab),
            ("jaxa_earth_stac", "JAXA Earth", self._create_jaxa_tab),
        ]

        for connector_id, tab_title, builder in provider_panels:
            panel_widget = builder()
            if self._is_connector_available(connector_id):
                tab_widget.addTab(panel_widget, tab_title)
            else:
                logger.info(
                    "Settings panel skipped (connector unavailable): %s",
                    connector_id,
                )

        # Display settings tab
        display_tab = self._create_display_tab()
        tab_widget.addTab(display_tab, "Display")
        
        # Buttons
        button_layout = QHBoxLayout()
        
        self.save_btn = QPushButton("Save Settings")
        self.save_btn.clicked.connect(self._save_settings)
        button_layout.addWidget(self.save_btn)
        
        self.reset_btn = QPushButton("Reset Defaults")
        self.reset_btn.clicked.connect(self._reset_defaults)
        button_layout.addWidget(self.reset_btn)
        
        layout.addLayout(button_layout)
        
        # Status label
        self.status_label = QLabel("Settings loaded")
        self.status_label.setStyleSheet("color: #404040; font-size: 10px;")
        layout.addWidget(self.status_label)
        
        # Load current settings
        self._load_settings()

    def _is_connector_available(self, connector_id: str) -> bool:
        """Return True when the connector module/class can be imported."""
        connector_imports = {
            "oneatlas": ("..connectors.oneatlas", "OneAtlasConnector"),
            "planet": ("..connectors.planet", "PlanetConnector"),
            "vantor": ("..connectors.vantor", "VantorConnector"),
            "iceye": ("..connectors.iceye", "IceyeConnector"),
            "umbra": ("..connectors.umbra", "UmbraConnector"),
            "element84_stac": (
                "..connectors.element84_stac",
                "Element84StacConnector",
            ),
            "planetary_computer_stac": (
                "..connectors.planetary_computer_stac",
                "PlanetaryComputerStacConnector",
            ),
            "nasa_earthdata": ("..connectors.nasa_earthdata", "NasaEarthdataConnector"),
            "capella": ("..connectors.capella", "CapellaConnector"),
            "jilin_gaofen_stac": ("..connectors.jilin_gaofen_stac", "JilinGaofenStacConnector"),
            "jaxa_earth_stac": ("..connectors.jaxa_earth_stac", "JaxaEarthStacConnector"),
        }
        module_name, class_name = connector_imports.get(connector_id, (None, None))
        if not module_name:
            return False
        try:
            module = importlib.import_module(module_name, __package__)
            return hasattr(module, class_name)
        except Exception as exc:
            logger.debug(f"Connector availability check failed for {connector_id}: {exc}")
            return False

    def _create_oneatlas_tab(self):
        """Create OneAtlas authentication settings tab"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # OneAtlas auth group
        oneatlas_group = QGroupBox("OneAtlas Authentication (OAuth2)")
        oneatlas_layout = QFormLayout(oneatlas_group)
        
        # Info label
        info_label = QLabel(
            "OneAtlas uses OAuth2 client credentials flow. Obtain your API credentials from "
            "<a href='https://www.intelligence-airbusds.com/access-to-our-products/'>Airbus Intelligence Portal</a>."
        )
        info_label.setOpenExternalLinks(True)
        info_label.setWordWrap(True)
        info_label.setStyleSheet("color: #404040; font-size: 9px;")
        oneatlas_layout.addRow("", info_label)
        
        # Client ID (NOT secret - should be visible)
        self.oneatlas_client_id = QLineEdit()
        self.oneatlas_client_id.setPlaceholderText("Enter Client ID")
        # Client ID is NOT secret - do not mask it
        oneatlas_layout.addRow("Client ID:", self.oneatlas_client_id)
        
        # Client Secret (this IS secret - mask it)
        self.oneatlas_client_secret = QLineEdit()
        self.oneatlas_client_secret.setPlaceholderText("Enter Client Secret")
        self.oneatlas_client_secret.setEchoMode(QLineEdit.Password)
        oneatlas_layout.addRow("Client Secret:", self.oneatlas_client_secret)
        
        # Test connection button
        test_oneatlas_btn = QPushButton("Test Connection")
        test_oneatlas_btn.clicked.connect(self._test_oneatlas_connection)
        oneatlas_layout.addRow("", test_oneatlas_btn)
        
        # Commercial notice
        commercial_label = QLabel(
            "⚠️ OneAtlas is a commercial service. Valid subscription required."
        )
        commercial_label.setStyleSheet("color: #ff9900; font-size: 10px; font-weight: bold;")
        commercial_label.setWordWrap(True)
        oneatlas_layout.addRow("", commercial_label)
        
        layout.addWidget(oneatlas_group)
        layout.addStretch()
        
        return widget

    def _create_planet_tab(self):
        """Create Planet API settings tab"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # Planet auth group
        planet_group = QGroupBox("Planet API Authentication")
        planet_layout = QFormLayout(planet_group)
        
        # Info label
        info_label = QLabel(
            "Planet uses an API key with Basic authentication for imagery, "
            "basemap, order, and tasking workflows. "
            "See <a href='https://docs.planet.com/platform/integrations/qgis/"
            "planet-qgis-plugin/'>QGIS plugin docs</a>."
        )
        info_label.setOpenExternalLinks(True)
        info_label.setWordWrap(True)
        info_label.setStyleSheet("color: #404040; font-size: 9px;")
        planet_layout.addRow("", info_label)

        # API base URL
        self.planet_api_base_url = QLineEdit()
        self.planet_api_base_url.setPlaceholderText("https://api.planet.com")
        self.planet_api_base_url.setText("https://api.planet.com")
        planet_layout.addRow("API Base URL:", self.planet_api_base_url)
        
        # API key
        self.planet_api_key = QLineEdit()
        self.planet_api_key.setPlaceholderText("Enter Planet API Key")
        self.planet_api_key.setEchoMode(QLineEdit.Password)
        planet_layout.addRow("API Key:", self.planet_api_key)

        tasking_label = QLabel(
            "Tasking API (per docs.planet.com): /tasking/v2/orders and /tasking/v2/pricing. "
            "Override only if your tenant uses custom routing."
        )
        tasking_label.setWordWrap(True)
        tasking_label.setStyleSheet("color: #404040; font-size: 9px;")
        planet_layout.addRow("", tasking_label)

        self.planet_tasking_base_url = QLineEdit()
        self.planet_tasking_base_url.setPlaceholderText("https://api.planet.com")
        planet_layout.addRow("Tasking Base URL:", self.planet_tasking_base_url)

        self.planet_tasking_orders_path = QLineEdit()
        self.planet_tasking_orders_path.setPlaceholderText("/tasking/v2/orders/")
        planet_layout.addRow("Orders Path:", self.planet_tasking_orders_path)

        self.planet_tasking_pricing_path = QLineEdit()
        self.planet_tasking_pricing_path.setPlaceholderText("/tasking/v2/pricing/")
        planet_layout.addRow("Pricing Path:", self.planet_tasking_pricing_path)

        # Test connection button
        test_planet_btn = QPushButton("Verify API Key")
        test_planet_btn.clicked.connect(self._test_planet_connection)
        planet_layout.addRow("", test_planet_btn)
        
        # Commercial notice
        commercial_label = QLabel(
            "⚠️ Planet is a commercial service. Valid subscription or "
            "trial required."
        )
        commercial_label.setStyleSheet(
            "color: #ff9900; font-size: 10px; font-weight: bold;"
        )
        commercial_label.setWordWrap(True)
        planet_layout.addRow("", commercial_label)
        
        layout.addWidget(planet_group)
        layout.addStretch()
        
        return widget

    def _create_vantor_tab(self):
        """Create Vantor Discovery API settings tab"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # Vantor Discovery group
        vantor_group = QGroupBox("Vantor Hub Discovery API")
        vantor_layout = QFormLayout(vantor_group)
        
        # Info label
        info_label = QLabel(
            "Archive search uses the Vantor Discovery API, not the legacy open-data STAC URL. "
            "Configure the Discovery endpoint, credentials, and optional imagery filters here."
        )
        info_label.setWordWrap(True)
        info_label.setStyleSheet("color: #404040; font-size: 9px;")
        vantor_layout.addRow("", info_label)

        self.vantor_discovery_enabled = QCheckBox("Enable Discovery API for archive search")
        self.vantor_discovery_enabled.setChecked(True)
        vantor_layout.addRow("Discovery:", self.vantor_discovery_enabled)
        
        self.vantor_discovery_base_url = QLineEdit()
        self.vantor_discovery_base_url.setPlaceholderText("https://api.maxar.com/discovery/v1")
        vantor_layout.addRow("Base URL:", self.vantor_discovery_base_url)

        self.vantor_discovery_search_path = QLineEdit()
        self.vantor_discovery_search_path.setPlaceholderText("/catalogs/imagery/search")
        vantor_layout.addRow("Search Path:", self.vantor_discovery_search_path)

        self.vantor_discovery_api_key = QLineEdit()
        self.vantor_discovery_api_key.setEchoMode(QLineEdit.Password)
        self.vantor_discovery_api_key.setPlaceholderText("Optional maxar-api-key")
        vantor_layout.addRow("API Key:", self.vantor_discovery_api_key)

        self.vantor_discovery_access_token = QLineEdit()
        self.vantor_discovery_access_token.setEchoMode(QLineEdit.Password)
        self.vantor_discovery_access_token.setPlaceholderText("Optional Bearer access token")
        vantor_layout.addRow("Access Token:", self.vantor_discovery_access_token)

        self.vantor_discovery_collections = QLineEdit()
        self.vantor_discovery_collections.setPlaceholderText("ge01,wv01,wv02,wv03-vnir,lg01")
        vantor_layout.addRow("Collections:", self.vantor_discovery_collections)

        self.vantor_discovery_sortby = QLineEdit()
        self.vantor_discovery_sortby.setPlaceholderText("Optional sort expression")
        vantor_layout.addRow("Sort By:", self.vantor_discovery_sortby)

        self.vantor_discovery_area_based_calc = QCheckBox("Enable area-based-calc")
        vantor_layout.addRow("Advanced:", self.vantor_discovery_area_based_calc)
        
        # Timeout settings
        self.vantor_discovery_timeout = QSpinBox()
        self.vantor_discovery_timeout.setRange(5, 120)
        self.vantor_discovery_timeout.setValue(60)
        self.vantor_discovery_timeout.setSuffix(" sec")
        vantor_layout.addRow("Request Timeout:", self.vantor_discovery_timeout)

        tasking_info = QLabel(
            "Tasking API (Maxar/Vantor Tasking v2) is optional and used for order submission workflows."
        )
        tasking_info.setWordWrap(True)
        tasking_info.setStyleSheet("color: #404040; font-size: 9px;")
        vantor_layout.addRow("", tasking_info)

        self.vantor_tasking_base_url = QLineEdit()
        self.vantor_tasking_base_url.setPlaceholderText("https://api.maxar.com")
        vantor_layout.addRow("Tasking Base URL:", self.vantor_tasking_base_url)

        self.vantor_tasking_create_path = QLineEdit()
        self.vantor_tasking_create_path.setPlaceholderText("/tasking/v2/requests")
        vantor_layout.addRow("Create Path:", self.vantor_tasking_create_path)

        self.vantor_tasking_list_path = QLineEdit()
        self.vantor_tasking_list_path.setPlaceholderText("/tasking/v2/requests")
        vantor_layout.addRow("List Path:", self.vantor_tasking_list_path)

        self.vantor_tasking_timeout = QSpinBox()
        self.vantor_tasking_timeout.setRange(5, 120)
        self.vantor_tasking_timeout.setValue(30)
        self.vantor_tasking_timeout.setSuffix(" sec")
        vantor_layout.addRow("Tasking Timeout:", self.vantor_tasking_timeout)

        self.vantor_tasking_access_token = QLineEdit()
        self.vantor_tasking_access_token.setEchoMode(QLineEdit.Password)
        self.vantor_tasking_access_token.setPlaceholderText("Optional Bearer token for tasking")
        vantor_layout.addRow("Tasking Token:", self.vantor_tasking_access_token)

        legacy_label = QLabel(
            "Note: the old open-data STAC URL setting is not used by archive search. "
            "Open-data fallback remains internal to the connector and is not configured here."
        )
        legacy_label.setWordWrap(True)
        legacy_label.setStyleSheet("color: #805d00; font-size: 9px; font-style: italic;")
        vantor_layout.addRow("", legacy_label)
        
        # Default button
        default_btn = QPushButton("Restore Defaults")
        default_btn.clicked.connect(self._restore_default_vantor_endpoint)
        vantor_layout.addRow("", default_btn)
        
        # Test connection button
        test_btn = QPushButton("Test Discovery Connection")
        test_btn.clicked.connect(self._test_vantor_connection)
        vantor_layout.addRow("", test_btn)
        
        # Results display
        self.vantor_results = QLabel("")
        self.vantor_results.setWordWrap(True)
        self.vantor_results.setStyleSheet("color: #404040; font-size: 9px; font-family: monospace;")
        vantor_layout.addRow("", self.vantor_results)
        
        layout.addWidget(vantor_group)
        layout.addStretch()
        
        return widget
    
    def _create_iceye_tab(self):
        """Create ICEYE Catalog API settings tab"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # ICEYE configuration group
        iceye_group = QGroupBox("ICEYE Catalog API Configuration")
        iceye_layout = QFormLayout(iceye_group)
        
        # Info label
        info_label = QLabel(
            "ICEYE commercial archive search uses Catalog API v2. "
            "Requires a valid API access token (Bearer) and optional contract/collection scope."
        )
        info_label.setWordWrap(True)
        info_label.setStyleSheet("color: #404040; font-size: 9px;")
        iceye_layout.addRow("", info_label)
        
        # API base URL
        self.iceye_endpoint = QLineEdit()
        self.iceye_endpoint.setPlaceholderText("https://api.iceye.com")
        iceye_layout.addRow("API Base URL:", self.iceye_endpoint)

        # Access token (secure)
        self.iceye_access_token = QLineEdit()
        self.iceye_access_token.setEchoMode(QLineEdit.Password)
        self.iceye_access_token.setPlaceholderText("Paste ICEYE API access token")
        iceye_layout.addRow("Access Token:", self.iceye_access_token)

        # Optional contract scope
        self.iceye_contract_id = QLineEdit()
        self.iceye_contract_id.setPlaceholderText("Optional contractID")
        iceye_layout.addRow("Contract ID:", self.iceye_contract_id)

        # Optional collections filter
        self.iceye_collections = QLineEdit()
        self.iceye_collections.setPlaceholderText("public,private (optional)")
        iceye_layout.addRow("Collections:", self.iceye_collections)
        
        # Timeout settings
        self.iceye_catalog_timeout = QSpinBox()
        self.iceye_catalog_timeout.setRange(5, 60)
        self.iceye_catalog_timeout.setValue(10)
        self.iceye_catalog_timeout.setSuffix(" sec")
        iceye_layout.addRow("Catalog Timeout:", self.iceye_catalog_timeout)
        
        self.iceye_search_timeout = QSpinBox()
        self.iceye_search_timeout.setRange(5, 60)
        self.iceye_search_timeout.setValue(60)
        self.iceye_search_timeout.setSuffix(" sec")
        iceye_layout.addRow("Search Timeout:", self.iceye_search_timeout)
        
        # Default button
        default_btn = QPushButton("Restore Defaults")
        default_btn.clicked.connect(self._restore_default_iceye)
        iceye_layout.addRow("", default_btn)
        
        # Test connection button
        test_btn = QPushButton("Test Catalog API Connection")
        test_btn.clicked.connect(self._test_iceye_connection)
        iceye_layout.addRow("", test_btn)
        
        # Results display
        self.iceye_results = QLabel("")
        self.iceye_results.setWordWrap(True)
        self.iceye_results.setStyleSheet("color: #404040; font-size: 9px; font-family: monospace;")
        iceye_layout.addRow("", self.iceye_results)
        
        layout.addWidget(iceye_group)
        layout.addStretch()
        
        return widget

    def _create_umbra_tab(self):
        """Create Umbra Canopy API settings tab."""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        umbra_group = QGroupBox("Umbra Canopy API Configuration")
        umbra_layout = QFormLayout(umbra_group)

        info_label = QLabel(
            "Umbra commercial archive search uses STAC API v2 with Bearer token. "
            "Reference: <a href='https://docs.canopy.umbra.space/reference/v2-stac-overview'>Umbra STAC v2 overview</a>."
        )
        info_label.setOpenExternalLinks(True)
        info_label.setWordWrap(True)
        info_label.setStyleSheet("color: #404040; font-size: 9px;")
        umbra_layout.addRow("", info_label)

        self.umbra_api_base_url = QLineEdit()
        self.umbra_api_base_url.setPlaceholderText("https://api.canopy.umbra.space")
        self.umbra_api_base_url.setText("https://api.canopy.umbra.space")
        umbra_layout.addRow("API Base URL:", self.umbra_api_base_url)

        self.umbra_access_token = QLineEdit()
        self.umbra_access_token.setEchoMode(QLineEdit.Password)
        self.umbra_access_token.setPlaceholderText("Paste Umbra Bearer access token")
        umbra_layout.addRow("Access Token:", self.umbra_access_token)

        self.umbra_client_id = QLineEdit()
        self.umbra_client_id.setPlaceholderText("Umbra OAuth2 client_id (optional)")
        umbra_layout.addRow("Client ID:", self.umbra_client_id)

        self.umbra_client_secret = QLineEdit()
        self.umbra_client_secret.setEchoMode(QLineEdit.Password)
        self.umbra_client_secret.setPlaceholderText("Umbra OAuth2 client_secret (optional)")
        umbra_layout.addRow("Client Secret:", self.umbra_client_secret)

        self.umbra_catalog_timeout = QSpinBox()
        self.umbra_catalog_timeout.setRange(5, 60)
        self.umbra_catalog_timeout.setValue(10)
        self.umbra_catalog_timeout.setSuffix(" sec")
        umbra_layout.addRow("Catalog Timeout:", self.umbra_catalog_timeout)

        self.umbra_search_timeout = QSpinBox()
        self.umbra_search_timeout.setRange(5, 60)
        self.umbra_search_timeout.setValue(60)
        self.umbra_search_timeout.setSuffix(" sec")
        umbra_layout.addRow("Search Timeout:", self.umbra_search_timeout)

        default_btn = QPushButton("Restore Defaults")
        default_btn.clicked.connect(self._restore_default_umbra)
        umbra_layout.addRow("", default_btn)

        test_btn = QPushButton("Test API Connection")
        test_btn.clicked.connect(self._test_umbra_connection)
        umbra_layout.addRow("", test_btn)

        self.umbra_results = QLabel("")
        self.umbra_results.setWordWrap(True)
        self.umbra_results.setStyleSheet("color: #404040; font-size: 9px; font-family: monospace;")
        umbra_layout.addRow("", self.umbra_results)

        layout.addWidget(umbra_group)
        layout.addStretch()

        return widget

    def _create_element84_stac_tab(self):
        """Create Earth Search (Element84) STAC settings tab."""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        group = QGroupBox("Earth Search (Element84) STAC")
        form = QFormLayout(group)

        info = QLabel(
            "Open-data STAC search endpoint used for archive search only. "
            "Collections are restricted to Sentinel and Landsat; "
            "results expose direct COG assets for map loading."
        )
        info.setWordWrap(True)
        info.setStyleSheet("color: #404040; font-size: 9px;")
        form.addRow("", info)

        self.element84_stac_api_url = QLineEdit()
        self.element84_stac_api_url.setPlaceholderText(
            "https://earth-search.aws.element84.com/v1"
        )
        form.addRow("API Root:", self.element84_stac_api_url)

        collections_label = QLabel(
            "Allowed collections: Sentinel + Landsat only "
            "(for example sentinel-2-l2a, sentinel-1-grd, landsat-c2-l2)."
        )
        collections_label.setWordWrap(True)
        collections_label.setStyleSheet("color: #404040; font-size: 9px;")
        form.addRow("Scope:", collections_label)

        self.element84_stac_timeout = QSpinBox()
        self.element84_stac_timeout.setRange(5, 120)
        self.element84_stac_timeout.setValue(60)
        self.element84_stac_timeout.setSuffix(" sec")
        form.addRow("Request Timeout:", self.element84_stac_timeout)

        default_btn = QPushButton("Restore Defaults")
        default_btn.clicked.connect(self._restore_default_element84_stac)
        form.addRow("", default_btn)

        test_btn = QPushButton("Test STAC Access")
        test_btn.clicked.connect(self._test_element84_stac_connection)
        form.addRow("", test_btn)

        self.element84_stac_results = QLabel("")
        self.element84_stac_results.setWordWrap(True)
        self.element84_stac_results.setStyleSheet(
            "color: #404040; font-size: 9px; font-family: monospace;"
        )
        form.addRow("", self.element84_stac_results)

        layout.addWidget(group)
        layout.addStretch()
        return widget

    def _create_planetary_computer_stac_tab(self):
        """Create Microsoft Planetary Computer STAC settings tab."""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        group = QGroupBox("Microsoft Planetary Computer STAC")
        form = QFormLayout(group)

        info = QLabel(
            "Open-data STAC endpoint used for archive search only. "
            "The connector prioritizes optical RGB assets "
            "(visual > render > preview > first COG)."
        )
        info.setWordWrap(True)
        info.setStyleSheet("color: #404040; font-size: 9px;")
        form.addRow("", info)

        self.planetary_computer_stac_api_url = QLineEdit()
        self.planetary_computer_stac_api_url.setPlaceholderText(
            "https://planetarycomputer.microsoft.com/api/stac/v1"
        )
        form.addRow("API Root:", self.planetary_computer_stac_api_url)

        collections_label = QLabel(
            "Default scope: optical satellite collections with RGB-ready assets."
        )
        collections_label.setWordWrap(True)
        collections_label.setStyleSheet("color: #404040; font-size: 9px;")
        form.addRow("Scope:", collections_label)

        self.planetary_computer_stac_timeout = QSpinBox()
        self.planetary_computer_stac_timeout.setRange(5, 120)
        self.planetary_computer_stac_timeout.setValue(60)
        self.planetary_computer_stac_timeout.setSuffix(" sec")
        form.addRow("Request Timeout:", self.planetary_computer_stac_timeout)

        default_btn = QPushButton("Restore Defaults")
        default_btn.clicked.connect(self._restore_default_planetary_computer_stac)
        form.addRow("", default_btn)

        test_btn = QPushButton("Test STAC Access")
        test_btn.clicked.connect(self._test_planetary_computer_stac_connection)
        form.addRow("", test_btn)

        self.planetary_computer_stac_results = QLabel("")
        self.planetary_computer_stac_results.setWordWrap(True)
        self.planetary_computer_stac_results.setStyleSheet(
            "color: #404040; font-size: 9px; font-family: monospace;"
        )
        form.addRow("", self.planetary_computer_stac_results)

        layout.addWidget(group)
        layout.addStretch()
        return widget
    
    def _create_capella_tab(self):
        """Create Capella API settings tab."""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        capella_group = QGroupBox("Capella Catalog API")
        capella_layout = QFormLayout(capella_group)

        info_label = QLabel(
            "Capella commercial archive search uses an authenticated STAC-compatible API. "
            "Provide your API base URL and Bearer token to enable archive search."
        )
        info_label.setWordWrap(True)
        info_label.setStyleSheet("color: #404040; font-size: 9px;")
        capella_layout.addRow("", info_label)

        self.capella_api_base_url = QLineEdit()
        self.capella_api_base_url.setPlaceholderText("https://api.capellaspace.com")
        capella_layout.addRow("API Base URL:", self.capella_api_base_url)

        self.capella_access_token = QLineEdit()
        self.capella_access_token.setEchoMode(QLineEdit.Password)
        self.capella_access_token.setPlaceholderText("Paste Capella Bearer access token")
        capella_layout.addRow("Access Token:", self.capella_access_token)

        self.capella_collections_path = QLineEdit()
        self.capella_collections_path.setPlaceholderText("/stac/collections")
        capella_layout.addRow("Collections Path:", self.capella_collections_path)

        self.capella_search_path = QLineEdit()
        self.capella_search_path.setPlaceholderText("/stac/search")
        capella_layout.addRow("Search Path:", self.capella_search_path)

        test_capella_btn = QPushButton("Test Connection")
        test_capella_btn.clicked.connect(self._test_capella_connection)
        capella_layout.addRow("", test_capella_btn)

        default_btn = QPushButton("Restore Defaults")
        default_btn.clicked.connect(self._restore_default_capella)
        capella_layout.addRow("", default_btn)

        self.capella_results = QLabel("")
        self.capella_results.setWordWrap(True)
        self.capella_results.setStyleSheet(
            "color: #404040; font-size: 9px; font-family: monospace;"
        )
        capella_layout.addRow("", self.capella_results)

        layout.addWidget(capella_group)
        layout.addStretch()
        return widget

    def _test_capella_connection(self):
        """Verify Capella API credentials and collections endpoint."""
        api_base_url = self.capella_api_base_url.text().strip() or "https://api.capellaspace.com"
        access_token = self.capella_access_token.text().strip()
        collections_path = self.capella_collections_path.text().strip() or "/stac/collections"
        search_path = self.capella_search_path.text().strip() or "/stac/search"

        if not access_token:
            QMessageBox.warning(self, "Missing Token", "Please enter Capella access token.")
            return

        self.capella_results.setText("Testing connection...")
        QApplication.processEvents()

        try:
            from ..connectors.capella import CapellaConnector

            connector = CapellaConnector()
            auth_ok = connector.authenticate(
                {
                    "api_base_url": api_base_url,
                    "access_token": access_token,
                    "collections_path": collections_path,
                    "search_path": search_path,
                }
            )
            if not auth_ok:
                raise RuntimeError("Authentication failed")

            collections = connector.get_collections()
            self.capella_results.setText(
                f"\u2705 Connected\nCollections discovered: {len(collections)}"
            )
            self.capella_results.setStyleSheet(
                "color: #00ff00; font-size: 9px; font-family: monospace;"
            )
        except Exception as exc:
            self.capella_results.setText(f"\u274c {exc}")
            self.capella_results.setStyleSheet(
                "color: #ff6b6b; font-size: 9px; font-family: monospace;"
            )

    def _create_nasa_tab(self):
        """Create NASA EarthData settings tab"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # NASA EarthData configuration group
        nasa_group = QGroupBox("NASA EarthData Configuration")
        nasa_layout = QFormLayout(nasa_group)
        
        # Info label with registration link
        info_label = QLabel(
            "NASA EarthData provides access to 9,000+ Earth science datasets including "
            "GEDI, MODIS, Landsat, Sentinel, VIIRS, and more. Requires free account."
        )
        info_label.setWordWrap(True)
        info_label.setStyleSheet("color: #404040; font-size: 9px;")
        nasa_layout.addRow("", info_label)
        
        # Registration link
        reg_label = QLabel(
            "📖 <a href='https://urs.earthdata.nasa.gov/'>Register for NASA Earthdata Account</a> | "
            "<a href='https://earthdata.nasa.gov/'>NASA Earthdata Portal</a>"
        )
        reg_label.setOpenExternalLinks(True)
        reg_label.setStyleSheet("color: #4CAF50; font-size: 9px;")
        nasa_layout.addRow("", reg_label)
        
        # Username
        self.nasa_username = QLineEdit()
        self.nasa_username.setPlaceholderText("Your NASA Earthdata username")
        nasa_layout.addRow("Username*:", self.nasa_username)
        
        # Password
        self.nasa_password = QLineEdit()
        self.nasa_password.setPlaceholderText("Your NASA Earthdata password")
        self.nasa_password.setEchoMode(QLineEdit.Password)
        nasa_layout.addRow("Password*:", self.nasa_password)

        # Optional EDL bearer token
        self.nasa_access_token = QLineEdit()
        self.nasa_access_token.setPlaceholderText("Optional EARTHDATA_TOKEN (Bearer)")
        self.nasa_access_token.setEchoMode(QLineEdit.Password)
        nasa_layout.addRow("Access Token:", self.nasa_access_token)
        
        cred_info = QLabel(
            "Authentication options:\n"
            "• Username + Password, or\n"
            "• Access Token (EARTHDATA_TOKEN / Bearer).\n"
            "Credentials are saved securely when available."
        )
        cred_info.setWordWrap(True)
        cred_info.setStyleSheet("color: #ffaa00; font-size: 9px; font-style: italic;")
        nasa_layout.addRow("", cred_info)
        
        # Catalog cache timeout
        self.nasa_cache_timeout = QSpinBox()
        self.nasa_cache_timeout.setRange(1, 30)
        self.nasa_cache_timeout.setValue(7)
        self.nasa_cache_timeout.setSuffix(" days")
        nasa_layout.addRow("Catalog Cache:", self.nasa_cache_timeout)
        
        cache_info = QLabel("How long to cache the NASA dataset catalog locally")
        cache_info.setStyleSheet("color: gray; font-size: 8px; font-style: italic;")
        nasa_layout.addRow("", cache_info)
        
        # Authentication status
        self.nasa_auth_status = QLabel("")
        self.nasa_auth_status.setWordWrap(True)
        self.nasa_auth_status.setStyleSheet("color: #404040; font-size: 9px;")
        nasa_layout.addRow("Auth Status:", self.nasa_auth_status)
        
        # Test credentials button
        test_btn = QPushButton("Test Credentials")
        test_btn.clicked.connect(self._test_nasa_connection)
        test_btn.setStyleSheet("background-color: #0B3D91; color: white; font-weight: bold;")
        nasa_layout.addRow("", test_btn)
        
        # Results display
        self.nasa_results = QLabel("")
        self.nasa_results.setWordWrap(True)
        self.nasa_results.setStyleSheet("color: #404040; font-size: 9px; font-family: monospace;")
        nasa_layout.addRow("", self.nasa_results)
        
        layout.addWidget(nasa_group)
        
        # Dataset info group
        info_group = QGroupBox("Available Datasets")
        info_layout = QVBoxLayout(info_group)
        
        datasets_info = QLabel(
            "• GEDI: Global Ecosystem Dynamics Investigation\n"
            "• MODIS: Moderate Resolution Imaging Spectroradiometer\n"
            "• Landsat: 50+ years of Earth imagery\n"
            "• Sentinel: ESA Copernicus missions\n"
            "• VIIRS: Visible Infrared Imaging Radiometer Suite\n"
            "• ASTER: Advanced Spaceborne Thermal Emission\n"
            "• HLS: Harmonized Landsat Sentinel-2\n"
            "• And 9,000+ more Earth science datasets"
        )
        datasets_info.setStyleSheet("color: #404040; font-size: 9px;")
        info_layout.addWidget(datasets_info)
        
        layout.addWidget(info_group)
        layout.addStretch()
        
        return widget

    # ------------------------------------------------------------------
    # Jilin-1 Gaofen tab
    # ------------------------------------------------------------------

    def _create_jilin_tab(self):
        """Create Jilin-1 Gaofen catalog + tasking settings tab."""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        group = QGroupBox("Jilin-1 Gaofen API")
        form = QFormLayout(group)

        info = QLabel(
            "Configure STAC-compatible Catalog API and optional Tasking API endpoints "
            "for your Jilin tenant."
        )
        info.setWordWrap(True)
        info.setStyleSheet("color: #404040; font-size: 9px;")
        form.addRow("", info)

        self.jilin_catalog_base_url = QLineEdit()
        self.jilin_catalog_base_url.setPlaceholderText("https://<tenant>/stac")
        form.addRow("Catalog Base URL:", self.jilin_catalog_base_url)

        self.jilin_default_collection = QLineEdit()
        self.jilin_default_collection.setPlaceholderText("Optional default collection ID")
        form.addRow("Default Collection:", self.jilin_default_collection)

        self.jilin_access_token = QLineEdit()
        self.jilin_access_token.setEchoMode(QLineEdit.Password)
        self.jilin_access_token.setPlaceholderText("Optional token / API key")
        form.addRow("Catalog Token:", self.jilin_access_token)

        tasking_label = QLabel("Optional Tasking API configuration")
        tasking_label.setWordWrap(True)
        tasking_label.setStyleSheet("color: #404040; font-size: 9px;")
        form.addRow("", tasking_label)

        self.jilin_tasking_base_url = QLineEdit()
        self.jilin_tasking_base_url.setPlaceholderText("https://<tenant>")
        form.addRow("Tasking Base URL:", self.jilin_tasking_base_url)

        self.jilin_tasking_create_path = QLineEdit()
        self.jilin_tasking_create_path.setPlaceholderText("/tasking/v2/requests")
        form.addRow("Create Path:", self.jilin_tasking_create_path)

        self.jilin_tasking_list_path = QLineEdit()
        self.jilin_tasking_list_path.setPlaceholderText("/tasking/v2/requests")
        form.addRow("List Path:", self.jilin_tasking_list_path)

        self.jilin_tasking_access_token = QLineEdit()
        self.jilin_tasking_access_token.setEchoMode(QLineEdit.Password)
        self.jilin_tasking_access_token.setPlaceholderText("Optional tasking token")
        form.addRow("Tasking Token:", self.jilin_tasking_access_token)

        test_btn = QPushButton("Test Jilin Catalog Connection")
        test_btn.clicked.connect(self._test_jilin_connection)
        form.addRow("", test_btn)

        self.jilin_results = QLabel("")
        self.jilin_results.setWordWrap(True)
        self.jilin_results.setStyleSheet("color: #404040; font-size: 9px; font-family: monospace;")
        form.addRow("", self.jilin_results)

        layout.addWidget(group)
        layout.addStretch()
        return widget

    # ------------------------------------------------------------------
    # JAXA Earth tab
    # ------------------------------------------------------------------

    def _create_jaxa_tab(self):
        """Create JAXA Earth catalog + optional tasking settings tab."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(8)
        layout.setContentsMargins(8, 8, 8, 8)

        group = QGroupBox("JAXA Earth API")
        form = QFormLayout(group)

        info = QLabel(
            "JAXA catalog is public STAC/COG. Optional Tasking API fields are available "
            "for broker/partner workflows."
        )
        info.setWordWrap(True)
        info.setStyleSheet("color: #303030; font-size: 9px;")
        form.addRow("", info)

        self.jaxa_catalog_url = QLineEdit()
        self.jaxa_catalog_url.setPlaceholderText("https://data.earth.jaxa.jp/stac/cog/v1/catalog.json")
        form.addRow("Catalog URL:", self.jaxa_catalog_url)

        self.jaxa_search_url = QLineEdit()
        self.jaxa_search_url.setPlaceholderText("https://data.earth.jaxa.jp/stac/cog/v1/search")
        form.addRow("Search URL:", self.jaxa_search_url)

        self.jaxa_tasking_base_url = QLineEdit()
        self.jaxa_tasking_base_url.setPlaceholderText("Optional tasking base URL")
        form.addRow("Tasking Base URL:", self.jaxa_tasking_base_url)

        self.jaxa_tasking_create_path = QLineEdit()
        self.jaxa_tasking_create_path.setPlaceholderText("/tasking/v2/requests")
        form.addRow("Create Path:", self.jaxa_tasking_create_path)

        self.jaxa_tasking_list_path = QLineEdit()
        self.jaxa_tasking_list_path.setPlaceholderText("/tasking/v2/requests")
        form.addRow("List Path:", self.jaxa_tasking_list_path)

        self.jaxa_tasking_access_token = QLineEdit()
        self.jaxa_tasking_access_token.setEchoMode(QLineEdit.Password)
        self.jaxa_tasking_access_token.setPlaceholderText("Optional tasking token")
        form.addRow("Tasking Token:", self.jaxa_tasking_access_token)

        test_btn = QPushButton("Test JAXA Catalog Connection")
        test_btn.clicked.connect(self._test_jaxa_connection)
        form.addRow("", test_btn)

        self.jaxa_status_label = QLabel("")
        self.jaxa_status_label.setStyleSheet("font-size: 9px;")
        form.addRow("", self.jaxa_status_label)

        layout.addWidget(group)
        layout.addStretch()
        return widget

    def _test_jilin_connection(self):
        """Verify Jilin endpoint and basic search/collections access."""
        self.jilin_results.setText("Testing Jilin catalog endpoint...")
        QApplication.processEvents()

        try:
            from ..connectors.jilin_gaofen_stac import JilinGaofenStacConnector

            connector = JilinGaofenStacConnector()
            ok = connector.authenticate({
                'base_url': self.jilin_catalog_base_url.text().strip(),
                'collection': self.jilin_default_collection.text().strip(),
                'access_token': self.jilin_access_token.text().strip(),
                'tasking_base_url': self.jilin_tasking_base_url.text().strip(),
                'tasking_create_path': self.jilin_tasking_create_path.text().strip(),
                'tasking_list_path': self.jilin_tasking_list_path.text().strip(),
                'tasking_access_token': self.jilin_tasking_access_token.text().strip(),
            })
            if not ok:
                raise RuntimeError('Authentication/configuration failed')

            results, _ = connector.search(limit=3)
            self.jilin_results.setText(
                f"✅ Jilin endpoint reachable\n"
                f"Sample items: {len(results)}\n"
                f"Tasking endpoint: {connector.tasking_url() or '(not configured)'}"
            )
            self.jilin_results.setStyleSheet("color: #226633; font-size: 9px; font-family: monospace;")
        except Exception as exc:
            self.jilin_results.setText(f"❌ Jilin test failed\nError: {exc}")
            self.jilin_results.setStyleSheet("color: #ff6666; font-size: 9px; font-family: monospace;")
            logger.warning(f"Jilin catalog test failed: {exc}")

    def _test_jaxa_connection(self):
        """Verify access to the JAXA Earth STAC catalog."""
        self.jaxa_status_label.setText("Testing...")
        self.jaxa_status_label.setStyleSheet("color: #88ccff; font-size: 9px;")
        try:
            from ..connectors.jaxa_earth_stac import JaxaEarthStacConnector
            connector = JaxaEarthStacConnector()
            if connector.authenticate({
                'catalog_url': self.jaxa_catalog_url.text().strip(),
                'search_url': self.jaxa_search_url.text().strip(),
                'tasking_base_url': self.jaxa_tasking_base_url.text().strip(),
                'tasking_create_path': self.jaxa_tasking_create_path.text().strip(),
                'tasking_list_path': self.jaxa_tasking_list_path.text().strip(),
                'tasking_access_token': self.jaxa_tasking_access_token.text().strip(),
            }):
                collections = connector.get_collections()
                n = len(collections)
                self.jaxa_status_label.setText(
                    f"✅ Catalog reachable - {n} collection(s) found\n"
                    f"Tasking endpoint: {connector.tasking_url() or '(not configured)'}"
                )
                self.jaxa_status_label.setStyleSheet("color: #00cc66; font-size: 9px;")
                logger.info(f"JAXA Earth catalog test OK: {n} collections")
            else:
                self.jaxa_status_label.setText("❌ Could not reach JAXA catalog")
                self.jaxa_status_label.setStyleSheet("color: #ff6666; font-size: 9px;")
        except Exception as exc:
            self.jaxa_status_label.setText(f"❌ Error: {exc}")
            self.jaxa_status_label.setStyleSheet("color: #ff6666; font-size: 9px;")
            logger.warning(f"JAXA catalog test failed: {exc}")

    def _create_display_tab(self):
        """Create display settings tab"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # Download settings group
        download_group = QGroupBox("Download")
        download_layout = QFormLayout(download_group)
        
        # Download folder selection
        folder_layout = QHBoxLayout()
        self.download_folder = QLineEdit()
        self.download_folder.setPlaceholderText("Select download folder...")
        folder_layout.addWidget(self.download_folder)
        
        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self._browse_download_folder)
        folder_layout.addWidget(browse_btn)
        
        download_layout.addRow("Default Download Folder:", folder_layout)
        
        folder_info = QLabel(
            "COG files will be downloaded to this folder when using the Download button.\n"
            "If not set, you'll be prompted to select a folder each time."
        )
        folder_info.setWordWrap(True)
        folder_info.setStyleSheet("color: gray; font-size: 9px; font-style: italic;")
        download_layout.addRow("", folder_info)
        
        layout.addWidget(download_group)
        
        # Layer settings group
        layer_group = QGroupBox("Layers")
        layer_layout = QFormLayout(layer_group)
        
        self.auto_zoom = QCheckBox()
        self.auto_zoom.setChecked(True)
        layer_layout.addRow("Auto-zoom to results:", self.auto_zoom)
        
        self.limit_results_check = QCheckBox("Enable result limit")
        self.limit_results_check.setChecked(False)
        layer_layout.addRow("", self.limit_results_check)
        
        self.max_results = QSpinBox()
        self.max_results.setRange(10, 8888)
        self.max_results.setValue(250)
        self.max_results.setEnabled(False)
        layer_layout.addRow("Maximum results:", self.max_results)
        
        self.limit_results_check.toggled.connect(self.max_results.setEnabled)
        
        layout.addWidget(layer_group)
        
        # Logging group
        logging_group = QGroupBox("Logging")
        logging_layout = QFormLayout(logging_group)
        
        self.log_level_combo = QComboBox()
        self.log_level_combo.addItem("Standard (INFO)", "INFO")
        self.log_level_combo.addItem("Detailed (DEBUG)", "DEBUG")
        self.log_level_combo.addItem("Errors Only (WARNING)", "WARNING")
        logging_layout.addRow("Log Level:", self.log_level_combo)
        
        log_info = QLabel(
            "• Standard: General operations and results\n"
            "• Detailed: Full diagnostic info (may slow down plugin)\n"
            "• Errors Only: Only warnings and errors"
        )
        log_info.setWordWrap(True)
        log_info.setStyleSheet("color: gray; font-size: 9px; font-style: italic;")
        logging_layout.addRow("", log_info)
        
        # Log file location button
        log_location_btn = QPushButton("Open Log File Location")
        log_location_btn.clicked.connect(self._open_log_location)
        logging_layout.addRow("", log_location_btn)
        
        layout.addWidget(logging_group)
        layout.addStretch()
        
        return widget
    
    def _browse_download_folder(self):
        """Open folder selection dialog for download folder"""
        import os
        
        current_folder = self.download_folder.text()
        if not current_folder or not os.path.exists(current_folder):
            current_folder = os.path.expanduser("~")
        
        folder = QFileDialog.getExistingDirectory(
            self,
            "Select Download Folder",
            current_folder,
            QFileDialog.ShowDirsOnly
        )
        
        if folder:
            self.download_folder.setText(folder)

    def _load_settings(self):
        """Load settings from QSettings and SecureStorage"""
        # Logging
        log_level = self.settings.value(f"{self.SETTINGS_PREFIX}log_level", "INFO")
        index = self.log_level_combo.findData(log_level)
        if index >= 0:
            self.log_level_combo.setCurrentIndex(index)
        
        # Display
        self.auto_zoom.setChecked(
            self.settings.value(f"{self.SETTINGS_PREFIX}auto_zoom", True, type=bool)
        )
        self.limit_results_check.setChecked(
            self.settings.value(f"{self.SETTINGS_PREFIX}limit_results_enabled", False, type=bool)
        )
        self.max_results.setValue(
            self.settings.value(f"{self.SETTINGS_PREFIX}max_results", 100, type=int)
        )
        self.max_results.setEnabled(self.limit_results_check.isChecked())
        
        # Download folder
        download_folder = self.settings.value("altair/download_folder", "")
        if download_folder:
            self.download_folder.setText(download_folder)
        
        # OneAtlas (credentials from secure storage)
        if self.secure_storage:
            oneatlas_creds = self.secure_storage.get_credentials('oneatlas')
            logger.debug(f"Loading OneAtlas credentials from secure storage: {oneatlas_creds is not None}")
            if oneatlas_creds:
                client_id = oneatlas_creds.get('client_id', '')
                client_secret = oneatlas_creds.get('client_secret', '')
                logger.debug(f"OneAtlas client_id length: {len(client_id)}, client_secret length: {len(client_secret)}")
                self.oneatlas_client_id.setText(client_id)
                self.oneatlas_client_secret.setText(client_secret)
        
        # Planet (credentials from secure storage)
        if self.secure_storage:
            planet_creds = self.secure_storage.get_credentials('planet')
            if planet_creds:
                token = planet_creds.get('api_key', '') or planet_creds.get('access_token', '')
                self.planet_api_key.setText(token)

        default_planet_api_base_url = 'https://api.planet.com'
        self.planet_api_base_url.setText(
            self.settings.value(f"{self.SETTINGS_PREFIX}planet_api_base_url", default_planet_api_base_url)
        )
        self.planet_tasking_base_url.setText(
            self.settings.value(f"{self.SETTINGS_PREFIX}planet_tasking_base_url", 'https://api.planet.com')
        )
        self.planet_tasking_orders_path.setText(
            self.settings.value(f"{self.SETTINGS_PREFIX}planet_tasking_orders_path", '/tasking/v2/orders/')
        )
        self.planet_tasking_pricing_path.setText(
            self.settings.value(f"{self.SETTINGS_PREFIX}planet_tasking_pricing_path", '/tasking/v2/pricing/')
        )
        
        # Vantor Discovery API
        self.vantor_discovery_enabled.setChecked(
            self.settings.value(f"{self.SETTINGS_PREFIX}vantor_discovery_enabled", True, type=bool)
        )
        self.vantor_discovery_base_url.setText(
            self.settings.value(
                f"{self.SETTINGS_PREFIX}vantor_discovery_base_url",
                'https://api.maxar.com/discovery/v1'
            )
        )
        self.vantor_discovery_search_path.setText(
            self.settings.value(
                f"{self.SETTINGS_PREFIX}vantor_discovery_search_path",
                '/catalogs/imagery/search'
            )
        )
        self.vantor_discovery_timeout.setValue(
            self.settings.value(f"{self.SETTINGS_PREFIX}vantor_discovery_timeout", 60, type=int)
        )
        self.vantor_discovery_collections.setText(
            self.settings.value(f"{self.SETTINGS_PREFIX}vantor_discovery_collections", '')
        )
        self.vantor_discovery_sortby.setText(
            self.settings.value(f"{self.SETTINGS_PREFIX}vantor_discovery_sortby", '')
        )
        self.vantor_discovery_area_based_calc.setChecked(
            self.settings.value(
                f"{self.SETTINGS_PREFIX}vantor_discovery_area_based_calc", False, type=bool
            )
        )
        if self.secure_storage:
            vantor_creds = self.secure_storage.get_credentials('vantor') or {}
            self.vantor_discovery_api_key.setText(
                vantor_creds.get('discovery_api_key', vantor_creds.get('api_key', ''))
            )
            self.vantor_discovery_access_token.setText(
                vantor_creds.get(
                    'discovery_access_token', vantor_creds.get('access_token', '')
                )
            )
            self.vantor_tasking_access_token.setText(
                vantor_creds.get('tasking_access_token', vantor_creds.get('access_token', ''))
            )
        
        self.vantor_tasking_base_url.setText(
            self.settings.value(f"{self.SETTINGS_PREFIX}vantor_tasking_base_url", '')
        )
        self.vantor_tasking_create_path.setText(
            self.settings.value(f"{self.SETTINGS_PREFIX}vantor_tasking_create_path", '/tasking/v2/requests')
        )
        self.vantor_tasking_list_path.setText(
            self.settings.value(f"{self.SETTINGS_PREFIX}vantor_tasking_list_path", '/tasking/v2/requests')
        )
        self.vantor_tasking_timeout.setValue(
            self.settings.value(f"{self.SETTINGS_PREFIX}vantor_tasking_timeout", 30, type=int)
        )

        # ICEYE
        default_iceye_endpoint = 'https://api.iceye.com'
        self.iceye_endpoint.setText(
            self.settings.value(f"{self.SETTINGS_PREFIX}iceye_endpoint", default_iceye_endpoint)
        )
        self.iceye_contract_id.setText(
            self.settings.value(f"{self.SETTINGS_PREFIX}iceye_contract_id", "")
        )
        self.iceye_collections.setText(
            self.settings.value(f"{self.SETTINGS_PREFIX}iceye_collections", "")
        )

        if self.secure_storage:
            iceye_creds = self.secure_storage.get_credentials('iceye')
            if iceye_creds:
                self.iceye_access_token.setText(iceye_creds.get('access_token', ''))

        self.iceye_catalog_timeout.setValue(
            self.settings.value(f"{self.SETTINGS_PREFIX}iceye_catalog_timeout", 10, type=int)
        )
        self.iceye_search_timeout.setValue(
            self.settings.value(f"{self.SETTINGS_PREFIX}iceye_search_timeout", 60, type=int)
        )

        # Umbra
        default_umbra_endpoint = 'https://api.canopy.umbra.space'
        self.umbra_api_base_url.setText(
            self.settings.value(f"{self.SETTINGS_PREFIX}umbra_api_base_url", default_umbra_endpoint)
        )

        if self.secure_storage:
            umbra_creds = self.secure_storage.get_credentials('umbra')
            if umbra_creds:
                self.umbra_access_token.setText(umbra_creds.get('access_token', ''))
                self.umbra_client_id.setText(umbra_creds.get('client_id', ''))
                self.umbra_client_secret.setText(umbra_creds.get('client_secret', ''))

        self.umbra_catalog_timeout.setValue(
            self.settings.value(f"{self.SETTINGS_PREFIX}umbra_catalog_timeout", 10, type=int)
        )
        self.umbra_search_timeout.setValue(
            self.settings.value(f"{self.SETTINGS_PREFIX}umbra_search_timeout", 60, type=int)
        )

        # Earth Search (Element84 STAC)
        if hasattr(self, 'element84_stac_api_url'):
            self.element84_stac_api_url.setText(
                self.settings.value(
                    f"{self.SETTINGS_PREFIX}element84_stac_api_url",
                    'https://earth-search.aws.element84.com/v1'
                )
            )
            self.element84_stac_timeout.setValue(
                self.settings.value(
                    f"{self.SETTINGS_PREFIX}element84_stac_timeout",
                    60,
                    type=int,
                )
            )

        if hasattr(self, 'planetary_computer_stac_api_url'):
            self.planetary_computer_stac_api_url.setText(
                self.settings.value(
                    f"{self.SETTINGS_PREFIX}planetary_computer_stac_api_url",
                    'https://planetarycomputer.microsoft.com/api/stac/v1'
                )
            )
            self.planetary_computer_stac_timeout.setValue(
                self.settings.value(
                    f"{self.SETTINGS_PREFIX}planetary_computer_stac_timeout",
                    60,
                    type=int,
                )
            )
        
        # NASA EarthData
        nasa_username = self.settings.value("altair/nasa_username", "")
        if nasa_username:
            self.nasa_username.setText(nasa_username)
        
        # Load password/token from secure storage
        if self.secure_storage:
            nasa_creds = self.secure_storage.get_credentials('nasa_earthdata')
            if nasa_creds:
                self.nasa_password.setText(nasa_creds.get('password', ''))
                self.nasa_access_token.setText(
                    nasa_creds.get('access_token', nasa_creds.get('token', ''))
                )
        else:
            # Fallback: load from QSettings
            nasa_password = self.settings.value("altair/nasa_password", "")
            if nasa_password:
                self.nasa_password.setText(nasa_password)
            nasa_token = self.settings.value("altair/nasa_access_token", "")
            if nasa_token:
                self.nasa_access_token.setText(nasa_token)
        
        self.nasa_cache_timeout.setValue(
            self.settings.value(f"{self.SETTINGS_PREFIX}nasa_cache_timeout", 7, type=int)
        )

        # Do not auto-validate NASA credentials on settings load.
        # Validation is network-bound and should be user-triggered via Test Credentials.
        self.nasa_auth_status.setText("Not verified (click Test Credentials)")
        self.nasa_auth_status.setStyleSheet("color: #404040; font-size: 9px;")

        # Capella API
        self.capella_api_base_url.setText(
            self.settings.value(
                f"{self.SETTINGS_PREFIX}capella_api_base_url",
                'https://api.capellaspace.com'
            )
        )
        self.capella_collections_path.setText(
            self.settings.value(
                f"{self.SETTINGS_PREFIX}capella_collections_path",
                '/stac/collections'
            )
        )
        self.capella_search_path.setText(
            self.settings.value(
                f"{self.SETTINGS_PREFIX}capella_search_path",
                '/stac/search'
            )
        )
        if self.secure_storage:
            capella_creds = self.secure_storage.get_credentials('capella') or {}
            self.capella_access_token.setText(
                capella_creds.get('access_token', '')
            )

        # Jilin catalog/tasking
        if hasattr(self, 'jilin_catalog_base_url'):
            self.jilin_catalog_base_url.setText(
                self.settings.value(f"{self.SETTINGS_PREFIX}jilin_catalog_base_url", '')
            )
            self.jilin_default_collection.setText(
                self.settings.value(f"{self.SETTINGS_PREFIX}jilin_default_collection", '')
            )
            self.jilin_tasking_base_url.setText(
                self.settings.value(f"{self.SETTINGS_PREFIX}jilin_tasking_base_url", '')
            )
            self.jilin_tasking_create_path.setText(
                self.settings.value(f"{self.SETTINGS_PREFIX}jilin_tasking_create_path", '/tasking/v2/requests')
            )
            self.jilin_tasking_list_path.setText(
                self.settings.value(f"{self.SETTINGS_PREFIX}jilin_tasking_list_path", '/tasking/v2/requests')
            )

        # JAXA catalog/tasking
        if hasattr(self, 'jaxa_catalog_url'):
            self.jaxa_catalog_url.setText(
                self.settings.value(
                    f"{self.SETTINGS_PREFIX}jaxa_catalog_url",
                    'https://data.earth.jaxa.jp/stac/cog/v1/catalog.json'
                )
            )
            self.jaxa_search_url.setText(
                self.settings.value(
                    f"{self.SETTINGS_PREFIX}jaxa_search_url",
                    'https://data.earth.jaxa.jp/stac/cog/v1/search'
                )
            )
            self.jaxa_tasking_base_url.setText(
                self.settings.value(f"{self.SETTINGS_PREFIX}jaxa_tasking_base_url", '')
            )
            self.jaxa_tasking_create_path.setText(
                self.settings.value(f"{self.SETTINGS_PREFIX}jaxa_tasking_create_path", '/tasking/v2/requests')
            )
            self.jaxa_tasking_list_path.setText(
                self.settings.value(f"{self.SETTINGS_PREFIX}jaxa_tasking_list_path", '/tasking/v2/requests')
            )

        if self.secure_storage:
            if hasattr(self, 'jilin_access_token'):
                jilin_creds = self.secure_storage.get_credentials('jilin_gaofen_stac') or {}
                self.jilin_access_token.setText(jilin_creds.get('access_token', ''))
                self.jilin_tasking_access_token.setText(
                    jilin_creds.get('tasking_access_token', jilin_creds.get('access_token', ''))
                )

            if hasattr(self, 'jaxa_tasking_access_token'):
                jaxa_creds = self.secure_storage.get_credentials('jaxa_earth_stac') or {}
                self.jaxa_tasking_access_token.setText(
                    jaxa_creds.get('tasking_access_token', jaxa_creds.get('access_token', ''))
                )

    def _save_settings(self):
        """Save settings to QSettings and SecureStorage"""
        # Logging
        log_level = self.log_level_combo.currentData()
        self.settings.setValue(
            f"{self.SETTINGS_PREFIX}log_level",
            log_level
        )
        
        # Apply log level immediately
        from ..logger import set_log_level
        set_log_level(log_level)
        logger.info(f"Log level changed to: {log_level}")
        
        # Display
        self.settings.setValue(
            f"{self.SETTINGS_PREFIX}auto_zoom",
            self.auto_zoom.isChecked()
        )
        self.settings.setValue(
            f"{self.SETTINGS_PREFIX}limit_results_enabled",
            self.limit_results_check.isChecked()
        )
        self.settings.setValue(
            f"{self.SETTINGS_PREFIX}max_results",
            self.max_results.value()
        )
        
        # Download folder
        download_folder = self.download_folder.text().strip()
        if download_folder:
            self.settings.setValue("altair/download_folder", download_folder)
            logger.info(f"Download folder set to: {download_folder}")
        else:
            self.settings.remove("altair/download_folder")
            logger.info("Download folder cleared")
        
        # OneAtlas (save to secure storage)
        if self.secure_storage:
            oneatlas_client_id = self.oneatlas_client_id.text().strip()
            oneatlas_client_secret = self.oneatlas_client_secret.text().strip()
            if oneatlas_client_id and oneatlas_client_secret:
                logger.info(f"Saving OneAtlas credentials - client_id length: {len(oneatlas_client_id)}")
                self.secure_storage.store_credentials('oneatlas', {
                    'client_id': oneatlas_client_id,
                    'client_secret': oneatlas_client_secret
                })
                logger.info("OneAtlas credentials saved to secure storage")
            else:
                logger.debug("OneAtlas credentials empty, not saving")
        
        # Planet (save to secure storage)
        self.settings.setValue(
            f"{self.SETTINGS_PREFIX}planet_api_base_url",
            self.planet_api_base_url.text().strip()
        )
        self.settings.setValue(
            f"{self.SETTINGS_PREFIX}planet_tasking_base_url",
            self.planet_tasking_base_url.text().strip()
        )
        self.settings.setValue(
            f"{self.SETTINGS_PREFIX}planet_tasking_orders_path",
            self.planet_tasking_orders_path.text().strip()
        )
        self.settings.setValue(
            f"{self.SETTINGS_PREFIX}planet_tasking_pricing_path",
            self.planet_tasking_pricing_path.text().strip()
        )

        if self.secure_storage:
            planet_api_key = self.planet_api_key.text().strip()
            if planet_api_key:
                self.secure_storage.store_credentials('planet', {
                    'api_key': planet_api_key,
                    'access_token': planet_api_key
                })
                logger.info("Planet API key saved to secure storage")
        
        # Vantor Discovery API
        self.settings.setValue(
            f"{self.SETTINGS_PREFIX}vantor_discovery_enabled",
            self.vantor_discovery_enabled.isChecked()
        )
        self.settings.setValue(
            f"{self.SETTINGS_PREFIX}vantor_discovery_base_url",
            self.vantor_discovery_base_url.text().strip()
        )
        self.settings.setValue(
            f"{self.SETTINGS_PREFIX}vantor_discovery_search_path",
            self.vantor_discovery_search_path.text().strip()
        )
        self.settings.setValue(
            f"{self.SETTINGS_PREFIX}vantor_discovery_timeout",
            self.vantor_discovery_timeout.value()
        )
        self.settings.setValue(
            f"{self.SETTINGS_PREFIX}vantor_discovery_collections",
            self.vantor_discovery_collections.text().strip()
        )
        self.settings.setValue(
            f"{self.SETTINGS_PREFIX}vantor_discovery_sortby",
            self.vantor_discovery_sortby.text().strip()
        )
        self.settings.setValue(
            f"{self.SETTINGS_PREFIX}vantor_discovery_area_based_calc",
            self.vantor_discovery_area_based_calc.isChecked()
        )
        self.settings.setValue(
            f"{self.SETTINGS_PREFIX}vantor_search_timeout",
            self.vantor_discovery_timeout.value()
        )
        self.settings.setValue(
            f"{self.SETTINGS_PREFIX}vantor_tasking_base_url",
            self.vantor_tasking_base_url.text().strip()
        )
        self.settings.setValue(
            f"{self.SETTINGS_PREFIX}vantor_tasking_create_path",
            self.vantor_tasking_create_path.text().strip()
        )
        self.settings.setValue(
            f"{self.SETTINGS_PREFIX}vantor_tasking_list_path",
            self.vantor_tasking_list_path.text().strip()
        )
        self.settings.setValue(
            f"{self.SETTINGS_PREFIX}vantor_tasking_timeout",
            self.vantor_tasking_timeout.value()
        )
        self.settings.remove(f"{self.SETTINGS_PREFIX}vantor_endpoint")
        self.settings.remove(f"{self.SETTINGS_PREFIX}vantor_catalog_timeout")
        if self.secure_storage:
            vantor_payload = {}
            api_key = self.vantor_discovery_api_key.text().strip()
            access_token = self.vantor_discovery_access_token.text().strip()
            tasking_token = self.vantor_tasking_access_token.text().strip()
            if api_key:
                vantor_payload['discovery_api_key'] = api_key
                vantor_payload['api_key'] = api_key
            if access_token:
                vantor_payload['discovery_access_token'] = access_token
                vantor_payload['access_token'] = access_token
            if tasking_token:
                vantor_payload['tasking_access_token'] = tasking_token
            self.secure_storage.store_credentials('vantor', vantor_payload)
        
        # ICEYE
        self.settings.setValue(
            f"{self.SETTINGS_PREFIX}iceye_endpoint",
            self.iceye_endpoint.text().strip()
        )
        self.settings.setValue(
            f"{self.SETTINGS_PREFIX}iceye_contract_id",
            self.iceye_contract_id.text().strip()
        )
        self.settings.setValue(
            f"{self.SETTINGS_PREFIX}iceye_collections",
            self.iceye_collections.text().strip()
        )
        self.settings.setValue(
            f"{self.SETTINGS_PREFIX}iceye_catalog_timeout",
            self.iceye_catalog_timeout.value()
        )
        self.settings.setValue(
            f"{self.SETTINGS_PREFIX}iceye_search_timeout",
            self.iceye_search_timeout.value()
        )

        if self.secure_storage:
            iceye_access_token = self.iceye_access_token.text().strip()
            if iceye_access_token:
                self.secure_storage.store_credentials('iceye', {
                    'access_token': iceye_access_token
                })

        # Umbra
        self.settings.setValue(
            f"{self.SETTINGS_PREFIX}umbra_api_base_url",
            self.umbra_api_base_url.text().strip()
        )
        self.settings.setValue(
            f"{self.SETTINGS_PREFIX}umbra_catalog_timeout",
            self.umbra_catalog_timeout.value()
        )
        self.settings.setValue(
            f"{self.SETTINGS_PREFIX}umbra_search_timeout",
            self.umbra_search_timeout.value()
        )
        if self.secure_storage:
            umbra_access_token = self.umbra_access_token.text().strip()
            umbra_client_id = self.umbra_client_id.text().strip()
            umbra_client_secret = self.umbra_client_secret.text().strip()
            umbra_payload = {}
            if umbra_access_token:
                umbra_payload['access_token'] = umbra_access_token
            if umbra_client_id:
                umbra_payload['client_id'] = umbra_client_id
            if umbra_client_secret:
                umbra_payload['client_secret'] = umbra_client_secret
            if umbra_payload:
                self.secure_storage.store_credentials('umbra', umbra_payload)

        # Earth Search (Element84 STAC)
        if hasattr(self, 'element84_stac_api_url'):
            self.settings.setValue(
                f"{self.SETTINGS_PREFIX}element84_stac_api_url",
                self.element84_stac_api_url.text().strip()
            )
            self.settings.setValue(
                f"{self.SETTINGS_PREFIX}element84_stac_timeout",
                self.element84_stac_timeout.value()
            )

        if hasattr(self, 'planetary_computer_stac_api_url'):
            self.settings.setValue(
                f"{self.SETTINGS_PREFIX}planetary_computer_stac_api_url",
                self.planetary_computer_stac_api_url.text().strip()
            )
            self.settings.setValue(
                f"{self.SETTINGS_PREFIX}planetary_computer_stac_timeout",
                self.planetary_computer_stac_timeout.value()
            )
        
        # NASA EarthData
        nasa_username = self.nasa_username.text().strip()
        nasa_password = self.nasa_password.text().strip()
        nasa_access_token = self.nasa_access_token.text().strip()
        
        if nasa_username or nasa_password or nasa_access_token:
            self.settings.setValue("altair/nasa_username", nasa_username)
            # Save sensitive fields to secure storage
            if self.secure_storage:
                nasa_payload = {}
                if nasa_username:
                    nasa_payload['username'] = nasa_username
                if nasa_password:
                    nasa_payload['password'] = nasa_password
                if nasa_access_token:
                    nasa_payload['access_token'] = nasa_access_token
                self.secure_storage.store_credentials('nasa_earthdata', nasa_payload)
                logger.info("NASA EarthData credentials saved to secure storage")
            else:
                # Fallback: save sensitive values to QSettings (less secure)
                self.settings.setValue("altair/nasa_password", nasa_password)
                self.settings.setValue("altair/nasa_access_token", nasa_access_token)
                logger.warning("NASA EarthData credentials saved to QSettings (secure storage not available)")
        else:
            self.settings.remove("altair/nasa_username")
            self.settings.remove("altair/nasa_password")
            self.settings.remove("altair/nasa_access_token")
            if self.secure_storage:
                self.secure_storage.store_credentials('nasa_earthdata', {})
            logger.info("NASA EarthData credentials cleared")

        # Capella API
        self.settings.setValue(
            f"{self.SETTINGS_PREFIX}capella_api_base_url",
            self.capella_api_base_url.text().strip()
        )
        self.settings.setValue(
            f"{self.SETTINGS_PREFIX}capella_collections_path",
            self.capella_collections_path.text().strip()
        )
        self.settings.setValue(
            f"{self.SETTINGS_PREFIX}capella_search_path",
            self.capella_search_path.text().strip()
        )
        if self.secure_storage:
            capella_payload = {}
            capella_token = self.capella_access_token.text().strip()
            if capella_token:
                capella_payload['access_token'] = capella_token
            self.secure_storage.store_credentials('capella', capella_payload)

        # Jilin catalog/tasking
        if hasattr(self, 'jilin_catalog_base_url'):
            self.settings.setValue(
                f"{self.SETTINGS_PREFIX}jilin_catalog_base_url",
                self.jilin_catalog_base_url.text().strip()
            )
            self.settings.setValue(
                f"{self.SETTINGS_PREFIX}jilin_default_collection",
                self.jilin_default_collection.text().strip()
            )
            self.settings.setValue(
                f"{self.SETTINGS_PREFIX}jilin_tasking_base_url",
                self.jilin_tasking_base_url.text().strip()
            )
            self.settings.setValue(
                f"{self.SETTINGS_PREFIX}jilin_tasking_create_path",
                self.jilin_tasking_create_path.text().strip()
            )
            self.settings.setValue(
                f"{self.SETTINGS_PREFIX}jilin_tasking_list_path",
                self.jilin_tasking_list_path.text().strip()
            )

        # JAXA catalog/tasking
        if hasattr(self, 'jaxa_catalog_url'):
            self.settings.setValue(
                f"{self.SETTINGS_PREFIX}jaxa_catalog_url",
                self.jaxa_catalog_url.text().strip()
            )
            self.settings.setValue(
                f"{self.SETTINGS_PREFIX}jaxa_search_url",
                self.jaxa_search_url.text().strip()
            )
            self.settings.setValue(
                f"{self.SETTINGS_PREFIX}jaxa_tasking_base_url",
                self.jaxa_tasking_base_url.text().strip()
            )
            self.settings.setValue(
                f"{self.SETTINGS_PREFIX}jaxa_tasking_create_path",
                self.jaxa_tasking_create_path.text().strip()
            )
            self.settings.setValue(
                f"{self.SETTINGS_PREFIX}jaxa_tasking_list_path",
                self.jaxa_tasking_list_path.text().strip()
            )

        if self.secure_storage:
            if hasattr(self, 'jilin_access_token'):
                jilin_payload = {}
                jilin_token = self.jilin_access_token.text().strip()
                jilin_tasking_token = self.jilin_tasking_access_token.text().strip()
                if jilin_token:
                    jilin_payload['access_token'] = jilin_token
                if jilin_tasking_token:
                    jilin_payload['tasking_access_token'] = jilin_tasking_token
                self.secure_storage.store_credentials('jilin_gaofen_stac', jilin_payload)

            if hasattr(self, 'jaxa_tasking_access_token'):
                jaxa_payload = {}
                jaxa_tasking_token = self.jaxa_tasking_access_token.text().strip()
                if jaxa_tasking_token:
                    jaxa_payload['tasking_access_token'] = jaxa_tasking_token
                self.secure_storage.store_credentials('jaxa_earth_stac', jaxa_payload)
        
        self.settings.setValue(
            f"{self.SETTINGS_PREFIX}nasa_cache_timeout",
            self.nasa_cache_timeout.value()
        )
        
        # Sync settings
        self.settings.sync()
        
        self.status_label.setText("Settings saved successfully")
        self.status_label.setStyleSheet("color: green; font-size: 10px;")
        
        # Emit signal so main dock can refresh collections if needed
        self.settings_saved.emit()
        logger.debug("Emitted settings_saved signal")
        
        QMessageBox.information(
            self,
            "Settings Saved",
            "Settings saved successfully."
        )

    def _reset_defaults(self):
        """Reset all settings to defaults"""
        logger.info("Resetting all settings to defaults")
        
        # Logging
        index = self.log_level_combo.findData("INFO")
        if index >= 0:
            self.log_level_combo.setCurrentIndex(index)
        
        # Display
        self.auto_zoom.setChecked(True)
        self.max_results.setValue(100)
        
        # Planet
        self._restore_default_planet()

        # Vantor
        self._restore_default_vantor_endpoint()

        # ICEYE
        self._restore_default_iceye()

        # Umbra
        self._restore_default_umbra()

        # Capella
        self._restore_default_capella()

        # Earth Search
        self._restore_default_element84_stac()

        # Planetary Computer
        self._restore_default_planetary_computer_stac()
        
        # Jilin and JAXA
        self._restore_default_jilin()
        self._restore_default_jaxa()

        # Copernicus
        self._restore_default_copernicus()
        
        self.status_label.setText("Settings reset to default values")
        self.status_label.setStyleSheet("color: blue; font-size: 10px;")
    
    def _open_log_location(self):
        """Open the directory containing the log file"""
        from ..logger import get_log_file_path
        import subprocess
        import platform
        
        log_path = get_log_file_path()
        if not log_path:
            QMessageBox.warning(
                self,
                "Log File",
                "Log file path not available."
            )
            return
        
        log_dir = log_path.parent
        
        try:
            # Open directory in file explorer
            if platform.system() == 'Windows':
                subprocess.Popen(['explorer', str(log_dir)])
            elif platform.system() == 'Darwin':  # macOS
                subprocess.Popen(['open', str(log_dir)])
            else:  # Linux
                subprocess.Popen(['xdg-open', str(log_dir)])
            
            logger.info(f"Opened log directory: {log_dir}")
        except Exception as e:
            logger.error(f"Failed to open log directory: {e}")
            QMessageBox.information(
                self,
                "Log File Location",
                f"Log file location:\n\n{log_path}\n\n"
                f"Directory: {log_dir}"
            )
    
    def _restore_default_planet(self):
        """Restore default Planet settings."""
        self.planet_api_base_url.setText('https://api.planet.com')
        self.planet_tasking_base_url.setText('https://api.planet.com')
        self.planet_tasking_orders_path.setText('/tasking/v2/orders/')
        self.planet_tasking_pricing_path.setText('/tasking/v2/pricing/')
        logger.info('Restored default Planet settings')

    def _restore_default_vantor_endpoint(self):
        """Restore default Vantor Discovery API settings"""
        self.vantor_discovery_enabled.setChecked(True)
        self.vantor_discovery_base_url.setText('https://api.maxar.com/discovery/v1')
        self.vantor_discovery_search_path.setText('/catalogs/imagery/search')
        self.vantor_discovery_timeout.setValue(60)
        self.vantor_discovery_collections.clear()
        self.vantor_discovery_sortby.clear()
        self.vantor_discovery_area_based_calc.setChecked(False)
        self.vantor_discovery_api_key.clear()
        self.vantor_discovery_access_token.clear()
        self.vantor_tasking_base_url.clear()
        self.vantor_tasking_create_path.setText('/tasking/v2/requests')
        self.vantor_tasking_list_path.setText('/tasking/v2/requests')
        self.vantor_tasking_timeout.setValue(30)
        self.vantor_tasking_access_token.clear()
        logger.info('Restored default Vantor Discovery/Tasking API settings')
    
    def _test_vantor_connection(self):
        """Test Vantor Discovery API connection and query flow"""
        import time

        base_url = self.vantor_discovery_base_url.text().strip()
        search_path = self.vantor_discovery_search_path.text().strip()
        timeout = self.vantor_discovery_timeout.value()
        collections = [
            part.strip()
            for part in self.vantor_discovery_collections.text().split(',')
            if part.strip()
        ]

        if not base_url:
            QMessageBox.warning(self, "Missing URL", "Please enter Discovery API base URL.")
            return

        self.vantor_results.setText("Testing Discovery connection...")
        QApplication.processEvents()

        try:
            from ..connectors.vantor import VantorConnector

            connector = VantorConnector()
            payload = {
                'discovery_enabled': self.vantor_discovery_enabled.isChecked(),
                'discovery_base_url': base_url,
                'discovery_search_path': search_path or '/catalogs/imagery/search',
                'discovery_timeout': timeout,
                'discovery_api_key': self.vantor_discovery_api_key.text().strip(),
                'discovery_access_token': self.vantor_discovery_access_token.text().strip(),
                'tasking_base_url': self.vantor_tasking_base_url.text().strip(),
                'tasking_create_path': self.vantor_tasking_create_path.text().strip(),
                'tasking_list_path': self.vantor_tasking_list_path.text().strip(),
                'tasking_timeout': self.vantor_tasking_timeout.value(),
                'tasking_access_token': self.vantor_tasking_access_token.text().strip(),
            }

            connector.authenticate(**payload)

            start_time = time.time()
            results = connector.search(
                limit=3,
                timeout=timeout,
                use_discovery_api=self.vantor_discovery_enabled.isChecked(),
                discovery_search_path=payload['discovery_search_path'],
                discovery_collections=collections or None,
                discovery_sortby=self.vantor_discovery_sortby.text().strip() or None,
                discovery_area_based_calc=self.vantor_discovery_area_based_calc.isChecked(),
            )
            response_time_ms = int((time.time() - start_time) * 1000)

            result_count = len(results or [])
            result_text = (
                f"✅ Discovery request successful\n"
                f"Response time: {response_time_ms} ms\n"
                f"Endpoint: {base_url.rstrip('/')}{payload['discovery_search_path']}\n"
                f"Collections filter: {', '.join(collections) if collections else '(none)'}\n"
                f"Sample results: {result_count}\n"
            )

            if results:
                result_text += "─────────────────────\n"
                result_text += "Sample scene IDs:\n"
                for item in results[:3]:
                    result_text += f"  • {item.get('id', 'unknown')}\n"

            self.vantor_results.setText(result_text)
            self.vantor_results.setStyleSheet("color: #226633; font-size: 9px; font-family: monospace;")
            logger.info(f"Vantor Discovery test successful: {result_count} sample result(s)")

        except Exception as e:
            logger.error(f"Vantor Discovery connection test error: {e}")
            self.vantor_results.setText(
                f"❌ Discovery test failed\n"
                f"Error: {str(e)}"
            )
            self.vantor_results.setStyleSheet("color: #ff6666; font-size: 9px; font-family: monospace;")
    
    def _test_oneatlas_connection(self):
        """Test OneAtlas authentication"""
        client_id = self.oneatlas_client_id.text().strip()
        client_secret = self.oneatlas_client_secret.text().strip()
        
        if not client_id or not client_secret:
            QMessageBox.warning(
                self,
                "Missing Credentials",
                "Please enter both Client ID and Client Secret."
            )
            return
        
        try:
            from ..connectors import OneAtlasConnector
            
            connector = OneAtlasConnector()
            credentials = {
                'client_id': client_id,
                'client_secret': client_secret
            }
            
            # Test authentication with network verification
            success = connector.authenticate(credentials, verify=True)
            
            if success:
                QMessageBox.information(
                    self,
                    "Connection Successful",
                    "✅ OneAtlas authentication successful!\n\n"
                    "Your credentials are valid and have been verified."
                )
                logger.info("OneAtlas connection test successful")
            else:
                QMessageBox.warning(
                    self,
                    "Authentication Failed",
                    "❌ OneAtlas authentication failed.\n\n"
                    "Please check your credentials and try again.\n"
                    "Ensure you have an active OneAtlas subscription."
                )
                logger.warning("OneAtlas connection test failed")
                
        except Exception as e:
            logger.error(f"OneAtlas connection test error: {e}")
            QMessageBox.critical(
                self,
                "Connection Error",
                f"Error testing OneAtlas connection:\n\n{str(e)}"
            )
    
    def _test_planet_connection(self):
        """Test Planet API key"""
        api_key = self.planet_api_key.text().strip()
        api_base_url = self.planet_api_base_url.text().strip()
        if not api_base_url:
            api_base_url = 'https://api.planet.com'

        if not api_key:
            QMessageBox.warning(
                self,
                'Missing API Key',
                'Please enter your Planet API key.',
            )
            return

        try:
            from ..connectors import PlanetConnector

            connector = PlanetConnector()
            credentials = {
                'api_key': api_key,
                'access_token': api_key,
                'api_base_url': api_base_url,
                'tasking_base_url': self.planet_tasking_base_url.text().strip() or api_base_url,
                'tasking_orders_path': self.planet_tasking_orders_path.text().strip(),
                'tasking_pricing_path': self.planet_tasking_pricing_path.text().strip(),
            }

            success = connector.authenticate(credentials, verify=True)

            if success:
                QMessageBox.information(
                    self,
                    'API Key Valid',
                    '✅ Planet API key verified!\n\n'
                    'The key was accepted by the Planet API.',
                )
                logger.info('Planet API key verification successful')
            else:
                QMessageBox.warning(
                    self,
                    'Verification Failed',
                    '❌ Planet API key verification failed.\n\n'
                    'Please check the API key and base URL and try again.\n'
                    'Ensure your Planet account has access to the requested services.',
                )
                logger.warning('Planet API key verification failed')

        except Exception as e:
            logger.error(f'Planet API key verification error: {e}')
            QMessageBox.critical(
                self,
                'Connection Error',
                f'Error verifying Planet connection:\n\n{str(e)}',
            )

    def _restore_default_iceye(self):
        """Restore default ICEYE settings"""
        self.iceye_endpoint.setText('https://api.iceye.com')
        self.iceye_access_token.clear()
        self.iceye_contract_id.clear()
        self.iceye_collections.setText('public')
        self.iceye_catalog_timeout.setValue(10)
        self.iceye_search_timeout.setValue(60)
        self.iceye_results.clear()
        logger.info("Restored default ICEYE settings")

    def _restore_default_umbra(self):
        """Restore default Umbra endpoint"""
        self.umbra_api_base_url.setText('https://api.canopy.umbra.space')
        self.umbra_access_token.clear()
        self.umbra_client_id.clear()
        self.umbra_client_secret.clear()
        self.umbra_catalog_timeout.setValue(10)
        self.umbra_search_timeout.setValue(60)
        logger.info("Restored default Umbra settings")

    def _restore_default_capella(self):
        """Restore default Capella API settings."""
        self.capella_api_base_url.setText('https://api.capellaspace.com')
        self.capella_access_token.clear()
        self.capella_collections_path.setText('/stac/collections')
        self.capella_search_path.setText('/stac/search')
        self.capella_results.clear()
        logger.info("Restored default Capella API settings")

    def _restore_default_element84_stac(self):
        """Restore default Earth Search STAC settings."""
        if hasattr(self, 'element84_stac_api_url'):
            self.element84_stac_api_url.setText(
                'https://earth-search.aws.element84.com/v1'
            )
            self.element84_stac_timeout.setValue(60)
            self.element84_stac_results.clear()
        logger.info("Restored default Earth Search STAC settings")

    def _restore_default_planetary_computer_stac(self):
        """Restore default Planetary Computer STAC settings."""
        if hasattr(self, 'planetary_computer_stac_api_url'):
            self.planetary_computer_stac_api_url.setText(
                'https://planetarycomputer.microsoft.com/api/stac/v1'
            )
            self.planetary_computer_stac_timeout.setValue(60)
            self.planetary_computer_stac_results.clear()
        logger.info("Restored default Planetary Computer STAC settings")

    def _restore_default_jilin(self):
        """Restore default Jilin API settings."""
        self.jilin_catalog_base_url.clear()
        self.jilin_default_collection.clear()
        self.jilin_access_token.clear()
        self.jilin_tasking_base_url.clear()
        self.jilin_tasking_create_path.setText('/tasking/v2/requests')
        self.jilin_tasking_list_path.setText('/tasking/v2/requests')
        self.jilin_tasking_access_token.clear()
        self.jilin_results.clear()
        logger.info("Restored default Jilin API settings")

    def _restore_default_jaxa(self):
        """Restore default JAXA API settings."""
        self.jaxa_catalog_url.setText('https://data.earth.jaxa.jp/stac/cog/v1/catalog.json')
        self.jaxa_search_url.setText('https://data.earth.jaxa.jp/stac/cog/v1/search')
        self.jaxa_tasking_base_url.clear()
        self.jaxa_tasking_create_path.setText('/tasking/v2/requests')
        self.jaxa_tasking_list_path.setText('/tasking/v2/requests')
        self.jaxa_tasking_access_token.clear()
        self.jaxa_status_label.clear()
        logger.info("Restored default JAXA API settings")
    
    def _test_iceye_connection(self):
        """Test ICEYE Catalog API v2 connection and credentials"""
        import time
        import json
        from urllib.parse import urlencode
        
        endpoint = self.iceye_endpoint.text().strip().rstrip('/')
        access_token = self.iceye_access_token.text().strip()
        contract_id = self.iceye_contract_id.text().strip()
        collections = self.iceye_collections.text().strip()
        timeout = self.iceye_catalog_timeout.value()
        
        if not endpoint:
            QMessageBox.warning(self, "Missing URL", "Please enter ICEYE API Base URL.")
            return

        if not access_token:
            QMessageBox.warning(self, "Missing Token", "Please enter ICEYE Access Token.")
            return
        
        self.iceye_results.setText("Testing connection...")
        QApplication.processEvents()
        
        try:
            from qgis.core import QgsBlockingNetworkRequest, QgsNetworkAccessManager
            from qgis.PyQt.QtNetwork import QNetworkRequest
            from qgis.PyQt.QtCore import QUrl
            
            # Setup proxy
            QgsNetworkAccessManager.instance().setupDefaultProxyAndCache()
            
            # Build Catalog API URL
            items_url = endpoint
            if not items_url.endswith('/api/catalog/v2/items'):
                items_url = f"{items_url}/api/catalog/v2/items"

            params = {'limit': '5'}
            if contract_id:
                params['contractID'] = contract_id
            if collections:
                params['collections'] = collections
            url = f"{items_url}?{urlencode(params)}"

            # Test connection with timing
            start_time = time.time()
            
            request = QNetworkRequest(QUrl(url))
            request.setRawHeader(b"Accept", b"application/json, application/problem+json")
            request.setRawHeader(b"Authorization", f"Bearer {access_token}".encode("utf-8"))
            blocking_request = QgsBlockingNetworkRequest()
            error = blocking_request.get(request, forceRefresh=True)
            
            response_time_ms = int((time.time() - start_time) * 1000)
            
            if error != QgsBlockingNetworkRequest.NoError:
                self.iceye_results.setText(
                    f"❌ Connection failed\n"
                    f"Error: {blocking_request.errorMessage()}"
                )
                self.iceye_results.setStyleSheet("color: #ff6666; font-size: 9px; font-family: monospace;")
                return
            
            # Parse response
            reply = blocking_request.reply()
            content = reply.content().data().decode('utf-8')
            payload = json.loads(content)
            features = payload.get('features', [])
            if not isinstance(features, list):
                features = []
            cursor = payload.get('cursor')
            
            # Build result text
            result_text = (
                f"✅ Connection successful\n"
                f"Response time: {response_time_ms} ms\n"
                f"─────────────────────\n"
                f"Endpoint: {items_url}\n"
                f"Items returned: {len(features)}\n"
            )
            
            if cursor:
                result_text += "More results available (cursor present)\n"

            if features:
                result_text += "─────────────────────\n"
                result_text += "Sample items:\n"
                for feature in features[:3]:
                    item_id = feature.get('id', 'unknown')
                    item_dt = feature.get('properties', {}).get('datetime', 'n/a')
                    result_text += f"  • {item_id} ({item_dt})\n"
            
            self.iceye_results.setText(result_text)
            self.iceye_results.setStyleSheet("color: #226633; font-size: 9px; font-family: monospace;")
            
            logger.info(f"ICEYE Catalog API test OK: {len(features)} items, {response_time_ms}ms")
            
        except Exception as e:
            logger.error(f"ICEYE connection test error: {e}")
            self.iceye_results.setText(
                f"❌ Test failed\n"
                f"Error: {str(e)}"
            )
            self.iceye_results.setStyleSheet("color: #ff6666; font-size: 9px; font-family: monospace;")

    def _test_umbra_connection(self):
        """Test Umbra STAC v2 connection and credentials/token"""
        api_base_url = self.umbra_api_base_url.text().strip().rstrip('/')
        access_token = self.umbra_access_token.text().strip()
        client_id = self.umbra_client_id.text().strip()
        client_secret = self.umbra_client_secret.text().strip()

        if not api_base_url:
            QMessageBox.warning(self, "Missing URL", "Please enter Umbra API Base URL.")
            return

        if not access_token and not (client_id and client_secret):
            QMessageBox.warning(
                self,
                "Missing Credentials",
                "Provide either Access Token or Client ID + Client Secret."
            )
            return

        self.umbra_results.setText("Testing connection...")
        QApplication.processEvents()

        try:
            from ..connectors import UmbraConnector

            connector = UmbraConnector()
            success = connector.authenticate({
                'access_token': access_token,
                'client_id': client_id,
                'client_secret': client_secret,
                'api_base_url': api_base_url,
            })

            if not success:
                self.umbra_results.setText(
                    "❌ Authentication failed\n"
                    "Please verify token and endpoint"
                )
                self.umbra_results.setStyleSheet("color: #ff6666; font-size: 9px; font-family: monospace;")
                return

            collections = connector.get_collections() or []
            auth_mode = "token" if access_token else "client_credentials"
            self.umbra_results.setText(
                f"✅ Connection successful\n"
                f"Endpoint: {api_base_url}/v2/stac\n"
                f"Auth mode: {auth_mode}\n"
                f"Collections: {len(collections)}"
            )
            self.umbra_results.setStyleSheet("color: #226633; font-size: 9px; font-family: monospace;")
            logger.info(f"Umbra STAC v2 test OK: {len(collections)} collections")

        except Exception as e:
            logger.error(f"Umbra connection test error: {e}")
            self.umbra_results.setText(
                f"❌ Test failed\n"
                f"Error: {str(e)}"
            )
            self.umbra_results.setStyleSheet("color: #ff6666; font-size: 9px; font-family: monospace;")

    def _test_element84_stac_connection(self):
        """Test Earth Search STAC endpoint and Sentinel/Landsat collections."""
        import time

        api_root = self.element84_stac_api_url.text().strip().rstrip('/')
        timeout = self.element84_stac_timeout.value()

        if not api_root:
            QMessageBox.warning(self, "Missing URL", "Please enter Earth Search API root URL.")
            return

        self.element84_stac_results.setText("Testing endpoint...")
        QApplication.processEvents()

        try:
            from ..connectors.element84_stac import Element84StacConnector

            connector = Element84StacConnector()

            started = time.time()
            connector.authenticate({
                'api_root': api_root,
                'timeout': timeout,
            })
            elapsed_ms = int((time.time() - started) * 1000)

            collections = connector.get_collections() or []
            collection_ids = [str(c.get('id', '')) for c in collections if isinstance(c, dict)]

            items, error = connector.search_unified(
                bbox=[13.0, 45.0, 14.0, 46.0],
                start_date='2024-01-01',
                end_date='2024-01-31',
                limit=1,
                timeout=float(timeout),
            )

            if error:
                self.element84_stac_results.setText(
                    f"❌ Search probe failed\n"
                    f"Error: {error}"
                )
                self.element84_stac_results.setStyleSheet(
                    "color: #ff6666; font-size: 9px; font-family: monospace;"
                )
                return

            self.element84_stac_results.setText(
                f"✅ Endpoint reachable\n"
                f"Response time: {elapsed_ms} ms\n"
                f"─────────────────────\n"
                f"Collections (Sentinel/Landsat): {len(collection_ids)}\n"
                f"Sample search items: {len(items)}\n"
                f"API Root: {api_root}"
            )
            self.element84_stac_results.setStyleSheet(
                "color: #226633; font-size: 9px; font-family: monospace;"
            )
            logger.info(
                "Earth Search STAC test OK: collections=%s, sample_items=%s",
                len(collection_ids),
                len(items),
            )

        except Exception as e:
            logger.error(f"Earth Search STAC connection test error: {e}")
            self.element84_stac_results.setText(
                f"❌ Test failed\n"
                f"Error: {str(e)}"
            )
            self.element84_stac_results.setStyleSheet(
                "color: #ff6666; font-size: 9px; font-family: monospace;"
            )

    def _test_planetary_computer_stac_connection(self):
        """Test Planetary Computer STAC endpoint and RGB-ready archive items."""
        import time

        api_root = self.planetary_computer_stac_api_url.text().strip().rstrip('/')
        timeout = self.planetary_computer_stac_timeout.value()

        if not api_root:
            QMessageBox.warning(
                self,
                "Missing URL",
                "Please enter Planetary Computer STAC API root URL.",
            )
            return

        self.planetary_computer_stac_results.setText("Testing endpoint...")
        QApplication.processEvents()

        try:
            from ..connectors.planetary_computer_stac import (
                PlanetaryComputerStacConnector,
            )

            connector = PlanetaryComputerStacConnector()

            started = time.time()
            connector.authenticate({
                'api_root': api_root,
                'timeout': timeout,
            })
            elapsed_ms = int((time.time() - started) * 1000)

            collections = connector.get_collections() or []
            collection_ids = [
                str(c.get('id', ''))
                for c in collections
                if isinstance(c, dict)
            ]

            items, error = connector.search_unified(
                bbox=[13.0, 45.0, 14.0, 46.0],
                start_date='2024-01-01',
                end_date='2024-01-31',
                limit=3,
                timeout=float(timeout),
            )

            if error:
                self.planetary_computer_stac_results.setText(
                    f"❌ Search probe failed\n"
                    f"Error: {error}"
                )
                self.planetary_computer_stac_results.setStyleSheet(
                    "color: #ff6666; font-size: 9px; font-family: monospace;"
                )
                return

            rgb_ready = 0
            for item in items:
                assets = item.get('assets') if isinstance(item, dict) else {}
                visual = (
                    (assets or {}).get('visual')
                    if isinstance(assets, dict)
                    else None
                )
                if isinstance(visual, dict) and str(visual.get('href') or '').strip():
                    rgb_ready += 1

            self.planetary_computer_stac_results.setText(
                f"✅ Endpoint reachable\n"
                f"Response time: {elapsed_ms} ms\n"
                f"─────────────────────\n"
                f"Optical collections: {len(collection_ids)}\n"
                f"Sample items: {len(items)}\n"
                f"RGB-ready items: {rgb_ready}\n"
                f"API Root: {api_root}"
            )
            self.planetary_computer_stac_results.setStyleSheet(
                "color: #226633; font-size: 9px; font-family: monospace;"
            )
            logger.info(
                (
                    "Planetary Computer STAC test OK: collections=%s, "
                    "sample_items=%s, rgb_ready=%s"
                ),
                len(collection_ids),
                len(items),
                rgb_ready,
            )

        except Exception as e:
            logger.error(f"Planetary Computer STAC connection test error: {e}")
            self.planetary_computer_stac_results.setText(
                f"❌ Test failed\n"
                f"Error: {str(e)}"
            )
            self.planetary_computer_stac_results.setStyleSheet(
                "color: #ff6666; font-size: 9px; font-family: monospace;"
            )
    
    def _check_nasa_auth_status(self):
        """Check NASA EarthData authentication status"""
        try:
            from ..connectors.nasa_earthdata import NasaEarthdataConnector

            connector = NasaEarthdataConnector(
                username=self.nasa_username.text().strip(),
                password=self.nasa_password.text().strip(),
                access_token=self.nasa_access_token.text().strip(),
            )
            if connector.authenticate(
                credentials={"allow_deferred_validation": True},
                verify=True,
            ):
                self.nasa_auth_status.setText("✅ Authenticated")
                self.nasa_auth_status.setStyleSheet("color: #00ff00; font-size: 9px;")
            else:
                kind = connector.get_last_auth_error_kind()
                if kind == "proxy_auth_required":
                    self.nasa_auth_status.setText("⚠️ Proxy authentication required")
                    self.nasa_auth_status.setStyleSheet("color: #ffaa00; font-size: 9px;")
                elif kind == "proxy_connection_error":
                    self.nasa_auth_status.setText("⚠️ Proxy connection failed")
                    self.nasa_auth_status.setStyleSheet("color: #ffaa00; font-size: 9px;")
                elif kind == "invalid_credentials":
                    self.nasa_auth_status.setText("❌ Invalid credentials")
                    self.nasa_auth_status.setStyleSheet("color: #ff6666; font-size: 9px;")
                else:
                    self.nasa_auth_status.setText("❌ Not authenticated")
                    self.nasa_auth_status.setStyleSheet("color: #ff6666; font-size: 9px;")
                
        except ImportError:
            self.nasa_auth_status.setText("⚠️ NASA connector module unavailable")
            self.nasa_auth_status.setStyleSheet("color: #ffaa00; font-size: 9px;")
        except Exception:
            self.nasa_auth_status.setText("❌ Authentication check failed")
            self.nasa_auth_status.setStyleSheet("color: #ff6666; font-size: 9px;")

    def _test_nasa_connection(self):
        """Test NASA EarthData connection and credentials"""
        import time
        import os
        
        username = self.nasa_username.text().strip()
        password = self.nasa_password.text().strip()
        access_token = self.nasa_access_token.text().strip()
        
        has_userpass = bool(username and password)
        has_token = bool(access_token)

        if not has_userpass and not has_token:
            QMessageBox.warning(
                self,
                "Missing Credentials",
                "Provide either:\n"
                "• Username + Password, or\n"
                "• Access Token (EARTHDATA_TOKEN).\n\n"
                "Register at: https://urs.earthdata.nasa.gov/"
            )
            return
        
        self.nasa_results.setText("Testing credentials...")
        QApplication.processEvents()
        
        try:
            from ..connectors.nasa_earthdata import NasaEarthdataConnector
            
            connector = NasaEarthdataConnector(
                username=username,
                password=password,
                access_token=access_token,
            )
            
            # Test authentication
            start_time = time.time()
            
            # Set environment variables for explicit test path
            if access_token:
                os.environ['EARTHDATA_TOKEN'] = access_token
            if username and password:
                os.environ['EARTHDATA_USERNAME'] = username
                os.environ['EARTHDATA_PASSWORD'] = password
            
            success = connector.authenticate(
                credentials={
                    'username': username,
                    'password': password,
                    'access_token': access_token,
                    'allow_deferred_validation': True,
                },
                verify=True,
            )
            
            auth_time_ms = int((time.time() - start_time) * 1000)
            
            if not success:
                failure_hint = ""
                if hasattr(connector, "get_auth_failure_hint"):
                    try:
                        failure_hint = connector.get_auth_failure_hint()
                    except Exception:
                        failure_hint = ""

                if not failure_hint:
                    failure_hint = "Check your credentials and proxy settings."

                self.nasa_results.setText(
                    f"❌ Authentication failed\n"
                    f"{failure_hint}"
                )
                self.nasa_results.setStyleSheet("color: #ff6666; font-size: 9px; font-family: monospace;")

                kind = ""
                if hasattr(connector, "get_last_auth_error_kind"):
                    try:
                        kind = connector.get_last_auth_error_kind()
                    except Exception:
                        kind = ""

                if kind == "proxy_auth_required":
                    self.nasa_auth_status.setText("⚠️ Proxy authentication required")
                    self.nasa_auth_status.setStyleSheet("color: #ffaa00; font-size: 9px;")
                elif kind == "proxy_connection_error":
                    self.nasa_auth_status.setText("⚠️ Proxy connection failed")
                    self.nasa_auth_status.setStyleSheet("color: #ffaa00; font-size: 9px;")
                elif kind == "invalid_credentials":
                    self.nasa_auth_status.setText("❌ Invalid credentials")
                    self.nasa_auth_status.setStyleSheet("color: #ff6666; font-size: 9px;")
                else:
                    self.nasa_auth_status.setText("❌ Not authenticated")
                    self.nasa_auth_status.setStyleSheet("color: #ff6666; font-size: 9px;")
                return
            
            # Load catalog
            start_time = time.time()
            catalog = connector._load_catalog()
            catalog_time_ms = int((time.time() - start_time) * 1000)
            
            # Check if catalog is empty (supports CatalogData, DataFrame, and list)
            catalog_is_empty = catalog is None
            if not catalog_is_empty:
                if hasattr(catalog, '__len__'):
                    catalog_is_empty = len(catalog) == 0
                elif hasattr(catalog, 'empty'):
                    # Fallback for DataFrame
                    catalog_is_empty = catalog.empty
            
            if catalog_is_empty:
                self.nasa_results.setText(
                    f"✅ Authentication successful\n"
                    f"⚠️ Catalog loading failed"
                )
                self.nasa_results.setStyleSheet("color: #ff9900; font-size: 9px; font-family: monospace;")
                return
            
            # Get dataset count
            dataset_count = len(catalog)
            
            # Get top collections by category (if available)
            categories_info = ""
            if hasattr(catalog, 'get_category_counts'):
                # CatalogData path
                category_counts = catalog.get_category_counts()
                if category_counts:
                    top_categories = sorted(category_counts.items(), key=lambda kv: kv[1], reverse=True)[:5]
                    categories_info = "\nTop Categories:\n"
                    for cat, count in top_categories:
                        categories_info += f"  • {cat}: {count}\n"
            elif hasattr(catalog, 'columns'):
                # Legacy DataFrame fallback path
                if 'Category' in catalog.columns:
                    top_categories = catalog['Category'].value_counts().head(5)
                    categories_info = "\nTop Categories:\n"
                    for cat, count in top_categories.items():
                        if str(cat).strip() and str(cat).lower() != 'nan':
                            categories_info += f"  • {cat}: {count}\n"
            elif isinstance(catalog, list):
                # stdlib CSV fallback path
                category_counts = {}
                for row in catalog:
                    category = str(row.get('Category', '') or '').strip()
                    if category:
                        category_counts[category] = category_counts.get(category, 0) + 1
                if category_counts:
                    top_categories = sorted(category_counts.items(), key=lambda kv: kv[1], reverse=True)[:5]
                    categories_info = "\nTop Categories:\n"
                    for cat, count in top_categories:
                        categories_info += f"  • {cat}: {count}\n"

            auth_mode = "token" if has_token else "username/password"
            
            # Build result text
            result_text = (
                f"✅ Authentication successful\n"
                f"Auth time: {auth_time_ms} ms\n"
                f"Auth mode: {auth_mode}\n"
                f"Catalog load: {catalog_time_ms} ms\n"
                f"─────────────────────\n"
                f"Available Datasets: {dataset_count}\n"
                f"{categories_info}"
                f"─────────────────────\n"
                f"Username: {username or '(token mode)'}\n"
                f"API: NASA CMR (Common Metadata Repository)\n"
                f"Coverage: 1970s-present (varies by dataset)"
            )
            
            self.nasa_results.setText(result_text)
            self.nasa_results.setStyleSheet("color: #226633; font-size: 9px; font-family: monospace;")
            
            self.nasa_auth_status.setText("✅ Authenticated")
            self.nasa_auth_status.setStyleSheet("color: #00ff00; font-size: 9px;")
            
            logger.info(f"NASA EarthData test: loaded {dataset_count} datasets in {catalog_time_ms}ms")
            
        except ImportError as e:
            logger.error(f"NASA EarthData connector not available: {e}")
            self.nasa_results.setText(
                f"❌ NASA EarthData not available\n"
                f"Error: {str(e)}"
            )
            self.nasa_results.setStyleSheet("color: #ff6666; font-size: 9px; font-family: monospace;")
        except Exception as e:
            logger.error(f"NASA EarthData connection test error: {e}")
            self.nasa_results.setText(
                f"❌ Test failed\n"
                f"Error: {str(e)}\n\n"
                f"Check:\n"
                f"  1. Token or credentials are correct\n"
                f"  2. Internet/proxy connectivity is active\n"
                f"  3. NASA CMR endpoint is reachable"
            )
            self.nasa_results.setStyleSheet("color: #ff6666; font-size: 9px; font-family: monospace;")



