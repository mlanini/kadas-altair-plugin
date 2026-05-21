"""
Altair EO Data Settings Dock Widget
"""
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
        
        # OneAtlas tab
        oneatlas_tab = self._create_oneatlas_tab()
        tab_widget.addTab(oneatlas_tab, "OneAtlas")
        
        # Planet tab
        planet_tab = self._create_planet_tab()
        tab_widget.addTab(planet_tab, "Planet")
        
        # Vantor STAC tab
        vantor_tab = self._create_vantor_tab()
        tab_widget.addTab(vantor_tab, "Vantor STAC")
        
        # ICEYE tab
        iceye_tab = self._create_iceye_tab()
        tab_widget.addTab(iceye_tab, "ICEYE SAR")

        # Umbra tab
        umbra_tab = self._create_umbra_tab()
        tab_widget.addTab(umbra_tab, "Umbra SAR")
        
        # Copernicus tab
        copernicus_tab = self._create_copernicus_tab()
        tab_widget.addTab(copernicus_tab, "Copernicus")
        
        # NASA EarthData tab
        nasa_tab = self._create_nasa_tab()
        tab_widget.addTab(nasa_tab, "NASA EarthData")

        # Capella Space tab
        capella_tab = self._create_capella_tab()
        tab_widget.addTab(capella_tab, "Capella Space")

        # JAXA Earth tab
        jaxa_tab = self._create_jaxa_tab()
        tab_widget.addTab(jaxa_tab, "JAXA Earth")

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
        self.status_label.setStyleSheet("color: #505050; font-size: 10px;")
        layout.addWidget(self.status_label)
        
        # Load current settings
        self._load_settings()

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
        info_label.setStyleSheet("color: #cccccc; font-size: 9px;")
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
        """Create Planet Catalog API settings tab"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # Planet auth group
        planet_group = QGroupBox("Planet API Authentication")
        planet_layout = QFormLayout(planet_group)
        
        # Info label
        info_label = QLabel(
            "Planet Catalog API uses OAuth2 Bearer token. "
            "See <a href='https://docs.planet.com/develop/apis/catalog/reference/'>Catalog API Reference</a>."
        )
        info_label.setOpenExternalLinks(True)
        info_label.setWordWrap(True)
        info_label.setStyleSheet("color: #cccccc; font-size: 9px;")
        planet_layout.addRow("", info_label)

        # API base URL
        self.planet_api_base_url = QLineEdit()
        self.planet_api_base_url.setPlaceholderText("https://services.sentinel-hub.com")
        self.planet_api_base_url.setText("https://services.sentinel-hub.com")
        planet_layout.addRow("API Base URL:", self.planet_api_base_url)
        
        # Access token
        self.planet_access_token = QLineEdit()
        self.planet_access_token.setPlaceholderText("Enter OAuth2 Access Token")
        self.planet_access_token.setEchoMode(QLineEdit.Password)
        planet_layout.addRow("Access Token:", self.planet_access_token)
        
        # Test connection button
        test_planet_btn = QPushButton("Verify Token")
        test_planet_btn.clicked.connect(self._test_planet_connection)
        planet_layout.addRow("", test_planet_btn)
        
        # Commercial notice
        commercial_label = QLabel(
            "⚠️ Planet is a commercial service. Valid subscription or trial required."
        )
        commercial_label.setStyleSheet("color: #ff9900; font-size: 10px; font-weight: bold;")
        commercial_label.setWordWrap(True)
        planet_layout.addRow("", commercial_label)
        
        layout.addWidget(planet_group)
        layout.addStretch()
        
        return widget

    def _create_vantor_tab(self):
        """Create Vantor STAC endpoint settings tab"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # Vantor STAC group
        vantor_group = QGroupBox("Vantor STAC Configuration")
        vantor_layout = QFormLayout(vantor_group)
        
        # Info label
        info_label = QLabel(
            "Vantor STAC provides direct access to Vantor Open Data via STAC API endpoint. "
            "This is an alternative to the AWS STAC connector."
        )
        info_label.setWordWrap(True)
        info_label.setStyleSheet("color: #cccccc; font-size: 9px;")
        vantor_layout.addRow("", info_label)
        
        # Open Data STAC URL
        self.vantor_endpoint = QLineEdit()
        self.vantor_endpoint.setPlaceholderText("https://maxar-opendata.s3.amazonaws.com/events/catalog.json")
        vantor_layout.addRow("Open Data STAC URL:", self.vantor_endpoint)
        
        # Timeout settings
        self.vantor_catalog_timeout = QSpinBox()
        self.vantor_catalog_timeout.setRange(5, 60)
        self.vantor_catalog_timeout.setValue(12)
        self.vantor_catalog_timeout.setSuffix(" sec")
        vantor_layout.addRow("Catalog Timeout:", self.vantor_catalog_timeout)
        
        self.vantor_search_timeout = QSpinBox()
        self.vantor_search_timeout.setRange(5, 60)
        self.vantor_search_timeout.setValue(15)
        self.vantor_search_timeout.setSuffix(" sec")
        vantor_layout.addRow("Search Timeout:", self.vantor_search_timeout)
        
        # Default button
        default_btn = QPushButton("Restore Defaults")
        default_btn.clicked.connect(self._restore_default_vantor_endpoint)
        vantor_layout.addRow("", default_btn)
        
        # Test connection button
        test_btn = QPushButton("Test STAC Connection")
        test_btn.clicked.connect(self._test_vantor_connection)
        vantor_layout.addRow("", test_btn)
        
        # Results display
        self.vantor_results = QLabel("")
        self.vantor_results.setWordWrap(True)
        self.vantor_results.setStyleSheet("color: #cccccc; font-size: 9px; font-family: monospace;")
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
        info_label.setStyleSheet("color: #cccccc; font-size: 9px;")
        iceye_layout.addRow("", info_label)
        
        # API base URL
        self.iceye_endpoint = QLineEdit()
        self.iceye_endpoint.setPlaceholderText("https://api.iceye.com")
        iceye_layout.addRow("Open Data STAC URL:", self.iceye_endpoint)

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
        self.iceye_catalog_timeout.setValue(12)
        self.iceye_catalog_timeout.setSuffix(" sec")
        iceye_layout.addRow("Catalog Timeout:", self.iceye_catalog_timeout)
        
        self.iceye_search_timeout = QSpinBox()
        self.iceye_search_timeout.setRange(5, 60)
        self.iceye_search_timeout.setValue(15)
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
        self.iceye_results.setStyleSheet("color: #cccccc; font-size: 9px; font-family: monospace;")
        iceye_layout.addRow("", self.iceye_results)
        
        layout.addWidget(iceye_group)
        layout.addStretch()
        
        return widget

    def _create_umbra_tab(self):
        """Create Umbra Canopy STAC v2 settings tab"""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        umbra_group = QGroupBox("Umbra Canopy STAC v2 Configuration")
        umbra_layout = QFormLayout(umbra_group)

        info_label = QLabel(
            "Umbra commercial archive search uses STAC API v2 with Bearer token. "
            "Reference: <a href='https://docs.canopy.umbra.space/reference/v2-stac-overview'>Umbra STAC v2 overview</a>."
        )
        info_label.setOpenExternalLinks(True)
        info_label.setWordWrap(True)
        info_label.setStyleSheet("color: #cccccc; font-size: 9px;")
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
        self.umbra_catalog_timeout.setValue(12)
        self.umbra_catalog_timeout.setSuffix(" sec")
        umbra_layout.addRow("Catalog Timeout:", self.umbra_catalog_timeout)

        self.umbra_search_timeout = QSpinBox()
        self.umbra_search_timeout.setRange(5, 60)
        self.umbra_search_timeout.setValue(15)
        self.umbra_search_timeout.setSuffix(" sec")
        umbra_layout.addRow("Search Timeout:", self.umbra_search_timeout)

        default_btn = QPushButton("Restore Defaults")
        default_btn.clicked.connect(self._restore_default_umbra)
        umbra_layout.addRow("", default_btn)

        test_btn = QPushButton("Test STAC v2 Connection")
        test_btn.clicked.connect(self._test_umbra_connection)
        umbra_layout.addRow("", test_btn)

        self.umbra_results = QLabel("")
        self.umbra_results.setWordWrap(True)
        self.umbra_results.setStyleSheet("color: #cccccc; font-size: 9px; font-family: monospace;")
        umbra_layout.addRow("", self.umbra_results)

        layout.addWidget(umbra_group)
        layout.addStretch()

        return widget
    
    def _create_copernicus_tab(self):
        """Create Copernicus Dataspace settings tab"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # === COPERNICUS (Data Space Ecosystem) ===
        copernicus_stac_group = QGroupBox("Copernicus (Data Space Ecosystem)")
        copernicus_stac_layout = QFormLayout(copernicus_stac_group)
        
        # Info label
        stac_info_label = QLabel(
            "Copernicus Dataspace provides Sentinel-1/2/3/5P data via STAC API. "
            "Requires free account registration at dataspace.copernicus.eu. "
            "Create OAuth2 credentials (client_id/client_secret) in your account settings."
        )
        stac_info_label.setWordWrap(True)
        stac_info_label.setStyleSheet("color: #cccccc; font-size: 9px;")
        copernicus_stac_layout.addRow("", stac_info_label)
        
        # Client ID (NOT secret - should be visible)
        self.copernicus_client_id = QLineEdit()
        self.copernicus_client_id.setPlaceholderText("Enter OAuth2 client ID (e.g., sh-1234abcd-...)")
        # Client ID is NOT secret - do not mask it
        copernicus_stac_layout.addRow("Client ID:", self.copernicus_client_id)
        
        # Client Secret (this IS secret - mask it)
        self.copernicus_client_secret = QLineEdit()
        self.copernicus_client_secret.setPlaceholderText("Enter OAuth2 client secret")
        self.copernicus_client_secret.setEchoMode(QLineEdit.Password)
        copernicus_stac_layout.addRow("Client Secret:", self.copernicus_client_secret)

        # Timeout settings for STAC
        self.copernicus_stac_timeout = QSpinBox()
        self.copernicus_stac_timeout.setRange(5, 60)
        self.copernicus_stac_timeout.setValue(15)
        self.copernicus_stac_timeout.setSuffix(" sec")
        copernicus_stac_layout.addRow("Request Timeout:", self.copernicus_stac_timeout)
        
        # Default button for STAC
        stac_default_btn = QPushButton("Restore Defaults")
        stac_default_btn.clicked.connect(self._restore_default_copernicus_stac)
        copernicus_stac_layout.addRow("", stac_default_btn)
        
        # Test connection button for STAC
        stac_test_btn = QPushButton("Test STAC Connection")
        stac_test_btn.clicked.connect(self._test_copernicus_stac_connection)
        copernicus_stac_layout.addRow("", stac_test_btn)
        
        # Results display for STAC
        self.copernicus_stac_results = QLabel("")
        self.copernicus_stac_results.setWordWrap(True)
        self.copernicus_stac_results.setStyleSheet("color: #cccccc; font-size: 9px; font-family: monospace;")
        copernicus_stac_layout.addRow("", self.copernicus_stac_results)
        
        layout.addWidget(copernicus_stac_group)
        layout.addStretch()
        
        return widget

    def _create_capella_tab(self):
        """Create Capella Space API credentials settings tab"""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        capella_group = QGroupBox("Capella Space STAC / API Credentials")
        capella_layout = QFormLayout(capella_group)

        info_label = QLabel(
            "Capella Space provides SAR satellite imagery via STAC API. "
            "Obtain credentials from "
            "<a href='https://console.capellaspace.com/'>Capella Console</a>."
        )
        info_label.setOpenExternalLinks(True)
        info_label.setWordWrap(True)
        info_label.setStyleSheet("color: #cccccc; font-size: 9px;")
        capella_layout.addRow("", info_label)

        self.capella_username = QLineEdit()
        self.capella_username.setPlaceholderText("Capella account email")
        capella_layout.addRow("Username:", self.capella_username)

        self.capella_password = QLineEdit()
        self.capella_password.setPlaceholderText("Capella account password")
        self.capella_password.setEchoMode(QLineEdit.Password)
        capella_layout.addRow("Password:", self.capella_password)

        self.capella_stac_url = QLineEdit()
        self.capella_stac_url.setPlaceholderText(
            "https://api.capellaspace.com/catalog/stac/v1"
        )
        capella_layout.addRow("Open Data STAC URL:", self.capella_stac_url)

        test_capella_btn = QPushButton("Test Connection")
        test_capella_btn.clicked.connect(self._test_capella_connection)
        capella_layout.addRow("", test_capella_btn)

        commercial_label = QLabel(
            "\u26a0\ufe0f Capella Space is a commercial service. Valid subscription required."
        )
        commercial_label.setStyleSheet(
            "color: #ff9900; font-size: 10px; font-weight: bold;"
        )
        commercial_label.setWordWrap(True)
        capella_layout.addRow("", commercial_label)

        self.capella_results = QLabel("")
        self.capella_results.setWordWrap(True)
        self.capella_results.setStyleSheet(
            "color: #cccccc; font-size: 9px; font-family: monospace;"
        )
        capella_layout.addRow("", self.capella_results)

        layout.addWidget(capella_group)
        layout.addStretch()
        return widget

    def _test_capella_connection(self):
        """Quick connectivity test for the Capella STAC endpoint."""
        import requests
        url = self.capella_stac_url.text().strip() or \
            "https://api.capellaspace.com/catalog/stac/v1"
        try:
            resp = requests.get(url, timeout=10)
            if resp.status_code < 400:
                self.capella_results.setText(f"\u2705 Reachable (HTTP {resp.status_code})")
                self.capella_results.setStyleSheet(
                    "color: #00ff00; font-size: 9px; font-family: monospace;"
                )
            else:
                self.capella_results.setText(f"\u26a0\ufe0f HTTP {resp.status_code}")
                self.capella_results.setStyleSheet(
                    "color: #ffaa00; font-size: 9px; font-family: monospace;"
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
        info_label.setStyleSheet("color: #cccccc; font-size: 9px;")
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
        self.nasa_auth_status.setStyleSheet("color: #cccccc; font-size: 9px;")
        nasa_layout.addRow("Auth Status:", self.nasa_auth_status)
        
        # Test credentials button
        test_btn = QPushButton("Test Credentials")
        test_btn.clicked.connect(self._test_nasa_connection)
        test_btn.setStyleSheet("background-color: #0B3D91; color: white; font-weight: bold;")
        nasa_layout.addRow("", test_btn)
        
        # Results display
        self.nasa_results = QLabel("")
        self.nasa_results.setWordWrap(True)
        self.nasa_results.setStyleSheet("color: #cccccc; font-size: 9px; font-family: monospace;")
        nasa_layout.addRow("", self.nasa_results)
        
        layout.addWidget(nasa_group)
        
        # Installation instructions group
        install_group = QGroupBox("Installation")
        install_layout = QVBoxLayout(install_group)
        
        install_info = QLabel(
            "The NASA EarthData connector requires 'earthaccess' and 'pandas' Python packages.\n\n"
            "Authentication supports either:\n"
            "• Username + Password, or\n"
            "• EARTHDATA_TOKEN (Bearer token).\n\n"
            "To install in QGIS Python Console:\n"
            ">>> import subprocess, sys\n"
            ">>> subprocess.check_call([sys.executable, '-m', 'pip', 'install', 'earthaccess', 'pandas'])"
        )
        install_info.setWordWrap(True)
        install_info.setStyleSheet("color: #cccccc; font-size: 9px; font-family: monospace;")
        install_layout.addWidget(install_info)
        
        layout.addWidget(install_group)
        
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
        datasets_info.setStyleSheet("color: #cccccc; font-size: 9px;")
        info_layout.addWidget(datasets_info)
        
        layout.addWidget(info_group)
        layout.addStretch()
        
        return widget

    # ------------------------------------------------------------------
    # JAXA Earth tab
    # ------------------------------------------------------------------

    def _create_jaxa_tab(self):
        """Create JAXA Earth settings tab (public data, no credentials required)."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(8)
        layout.setContentsMargins(8, 8, 8, 8)

        # Info group
        info_group = QGroupBox("JAXA Earth — Open EO Data")
        info_layout = QVBoxLayout(info_group)

        info_text = (
            "JAXA Earth provides free access to multi-sensor earth observation data "
            "via a public STAC/COG catalogue.\n\n"
            "No registration or API key is required.\n\n"
            "Available datasets include:\n"
            "  • ALOS/PRISM AW3D30 – 30 m global DSM (elevation)\n"
            "  • ALOS-2 / PALSAR-2 – SAR backscatter & forest/wetland mosaics\n"
            "  • GCOM-C / SGLI – Land surface temperature, NDVI, ocean products\n"
            "  • GPM IMERG – Global precipitation\n"
            "  • Himawari-8/9 – Near-real-time meteorological imagery\n\n"
            "Catalog root:\n"
            "  https://data.earth.jaxa.jp/stac/cog/v1/catalog.json"
        )
        info_label = QLabel(info_text)
        info_label.setWordWrap(True)
        info_label.setStyleSheet("color: #303030; font-size: 9px;")
        info_layout.addWidget(info_label)

        # Test connection button
        test_btn = QPushButton("Test JAXA Catalog Connection")
        test_btn.clicked.connect(self._test_jaxa_connection)
        info_layout.addWidget(test_btn)

        self.jaxa_status_label = QLabel("")
        self.jaxa_status_label.setStyleSheet("font-size: 9px;")
        info_layout.addWidget(self.jaxa_status_label)

        layout.addWidget(info_group)
        layout.addStretch()
        return widget

    def _test_jaxa_connection(self):
        """Verify access to the JAXA Earth STAC catalog."""
        self.jaxa_status_label.setText("Testing…")
        self.jaxa_status_label.setStyleSheet("color: #88ccff; font-size: 9px;")
        try:
            from ..connectors.jaxa_earth_stac import JaxaEarthStacConnector
            connector = JaxaEarthStacConnector()
            if connector.authenticate():
                collections = connector.get_collections()
                n = len(collections)
                self.jaxa_status_label.setText(
                    f"✅  Catalog reachable — {n} collection(s) found"
                )
                self.jaxa_status_label.setStyleSheet("color: #00cc66; font-size: 9px;")
                logger.info(f"JAXA Earth catalog test OK: {n} collections")
            else:
                self.jaxa_status_label.setText("❌  Could not reach JAXA catalog")
                self.jaxa_status_label.setStyleSheet("color: #ff6666; font-size: 9px;")
        except Exception as exc:
            self.jaxa_status_label.setText(f"❌  Error: {exc}")
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
                token = planet_creds.get('access_token', '') or planet_creds.get('api_key', '')
                self.planet_access_token.setText(token)

        default_planet_api_base_url = 'https://services.sentinel-hub.com'
        self.planet_api_base_url.setText(
            self.settings.value(f"{self.SETTINGS_PREFIX}planet_api_base_url", default_planet_api_base_url)
        )
        
        # Vantor STAC
        default_vantor_endpoint = 'https://maxar-opendata.s3.amazonaws.com/events/catalog.json'
        self.vantor_endpoint.setText(
            self.settings.value(f"{self.SETTINGS_PREFIX}vantor_endpoint", default_vantor_endpoint)
        )
        self.vantor_catalog_timeout.setValue(
            self.settings.value(f"{self.SETTINGS_PREFIX}vantor_catalog_timeout", 12, type=int)
        )
        self.vantor_search_timeout.setValue(
            self.settings.value(f"{self.SETTINGS_PREFIX}vantor_search_timeout", 15, type=int)
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
            self.settings.value(f"{self.SETTINGS_PREFIX}iceye_catalog_timeout", 12, type=int)
        )
        self.iceye_search_timeout.setValue(
            self.settings.value(f"{self.SETTINGS_PREFIX}iceye_search_timeout", 15, type=int)
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
            self.settings.value(f"{self.SETTINGS_PREFIX}umbra_catalog_timeout", 12, type=int)
        )
        self.umbra_search_timeout.setValue(
            self.settings.value(f"{self.SETTINGS_PREFIX}umbra_search_timeout", 15, type=int)
        )
        
        # Copernicus STAC (OAuth2 credentials from secure storage service 'copernicus')
        if self.secure_storage:
            copernicus_stac_creds = self.secure_storage.get_credentials('copernicus')
            logger.debug(f"Loading Copernicus STAC credentials from secure storage: {copernicus_stac_creds is not None}")
            if copernicus_stac_creds:
                client_id = copernicus_stac_creds.get('client_id', '')
                client_secret = copernicus_stac_creds.get('client_secret', '')
                logger.debug(f"Copernicus STAC client_id length: {len(client_id)}, client_secret length: {len(client_secret)}")
                self.copernicus_client_id.setText(client_id)
                self.copernicus_client_secret.setText(client_secret)
        
        self.copernicus_stac_timeout.setValue(
            self.settings.value(f"{self.SETTINGS_PREFIX}copernicus_stac_timeout", 15, type=int)
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
        
        # Check NASA authentication status
        self._check_nasa_auth_status()

        # Capella Space (credentials from secure storage)
        if self.secure_storage:
            capella_creds = self.secure_storage.get_credentials('capella')
            if capella_creds:
                self.capella_username.setText(capella_creds.get('username', ''))
                self.capella_password.setText(capella_creds.get('password', ''))
        default_capella_url = 'https://api.capellaspace.com/catalog/stac/v1'
        self.capella_stac_url.setText(
            self.settings.value(f"{self.SETTINGS_PREFIX}capella_stac_url", default_capella_url)
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

        if self.secure_storage:
            planet_access_token = self.planet_access_token.text().strip()
            if planet_access_token:
                self.secure_storage.store_credentials('planet', {
                    'access_token': planet_access_token
                })
                logger.info("Planet access token saved to secure storage")
        
        # Vantor STAC
        self.settings.setValue(
            f"{self.SETTINGS_PREFIX}vantor_endpoint",
            self.vantor_endpoint.text()
        )
        self.settings.setValue(
            f"{self.SETTINGS_PREFIX}vantor_catalog_timeout",
            self.vantor_catalog_timeout.value()
        )
        self.settings.setValue(
            f"{self.SETTINGS_PREFIX}vantor_search_timeout",
            self.vantor_search_timeout.value()
        )
        
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
        
        # Copernicus STAC (save OAuth2 to secure storage service 'copernicus')
        if self.secure_storage:
            copernicus_stac_client_id = self.copernicus_client_id.text().strip()
            copernicus_stac_client_secret = self.copernicus_client_secret.text().strip()
            if copernicus_stac_client_id and copernicus_stac_client_secret:
                logger.info(f"Saving Copernicus STAC credentials - client_id length: {len(copernicus_stac_client_id)}")
                self.secure_storage.store_credentials('copernicus', {
                    'client_id': copernicus_stac_client_id,
                    'client_secret': copernicus_stac_client_secret
                })
                logger.info("Copernicus STAC credentials saved to secure storage")
            else:
                logger.debug("Copernicus STAC credentials empty, not saving")
        
        self.settings.setValue(
            f"{self.SETTINGS_PREFIX}copernicus_stac_timeout",
            self.copernicus_stac_timeout.value()
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

        # Capella Space
        if self.secure_storage:
            capella_username = self.capella_username.text().strip()
            capella_password = self.capella_password.text().strip()
            if capella_username and capella_password:
                self.secure_storage.store_credentials('capella', {
                    'username': capella_username,
                    'password': capella_password,
                })
                logger.info('Capella credentials saved to secure storage')
        self.settings.setValue(
            f"{self.SETTINGS_PREFIX}capella_stac_url",
            self.capella_stac_url.text().strip()
        )
        
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
        
        # Vantor
        self._restore_default_vantor_endpoint()
        
        # ICEYE
        self._restore_default_iceye()

        # Umbra
        self._restore_default_umbra()
        
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
    
    def _restore_default_vantor_endpoint(self):
        """Restore default Vantor STAC endpoint"""
        default_url = 'https://maxar-opendata.s3.amazonaws.com/events/catalog.json'
        self.vantor_endpoint.setText(default_url)
        logger.info(f"Restored default Vantor STAC endpoint: {default_url}")
    
    def _test_vantor_connection(self):
        """Test Vantor STAC connection and count available data"""
        import time
        import json
        
        endpoint = self.vantor_endpoint.text().strip()
        timeout = self.vantor_catalog_timeout.value()
        
        if not endpoint:
            QMessageBox.warning(self, "Missing URL", "Please enter STAC endpoint URL.")
            return
        
        self.vantor_results.setText("Testing connection...")
        QApplication.processEvents()
        
        try:
            from qgis.core import QgsBlockingNetworkRequest, QgsNetworkAccessManager
            from qgis.PyQt.QtNetwork import QNetworkRequest
            from qgis.PyQt.QtCore import QUrl
            
            # Setup proxy
            QgsNetworkAccessManager.instance().setupDefaultProxyAndCache()
            
            # Test connection with timing
            start_time = time.time()
            
            request = QNetworkRequest(QUrl(endpoint))
            blocking_request = QgsBlockingNetworkRequest()
            error = blocking_request.get(request, forceRefresh=True)
            
            response_time_ms = int((time.time() - start_time) * 1000)
            
            if error != QgsBlockingNetworkRequest.NoError:
                self.vantor_results.setText(
                    f"❌ Connection failed\n"
                    f"Error: {blocking_request.errorMessage()}"
                )
                self.vantor_results.setStyleSheet("color: #ff6666; font-size: 9px; font-family: monospace;")
                return
            
            # Parse STAC catalog
            reply = blocking_request.reply()
            content = reply.content().data().decode('utf-8')
            catalog = json.loads(content)
            
            # Count collections (events)
            collections = []
            for link in catalog.get('links', []):
                if link.get('rel') == 'child':
                    coll_title = link.get('title', link.get('href', 'Unknown'))
                    collections.append(coll_title)
            
            num_collections = len(collections)
            
            # Try to count total items and COG assets across all collections
            total_items = 0
            total_cog_assets = 0
            collections_sampled = 0
            max_sample = 3  # Sample first 3 collections
            
            for link in catalog.get('links', [])[:max_sample]:
                if link.get('rel') == 'child':
                    child_url = link.get('href')
                    if child_url:
                        try:
                            # Fetch collection
                            child_request = QNetworkRequest(QUrl(child_url))
                            child_blocking = QgsBlockingNetworkRequest()
                            child_error = child_blocking.get(child_request, forceRefresh=True)
                            
                            if child_error == QgsBlockingNetworkRequest.NoError:
                                child_reply = child_blocking.reply()
                                child_content = child_reply.content().data().decode('utf-8')
                                collection_data = json.loads(child_content)
                                
                                # Count items in this collection
                                coll_items = 0
                                coll_cog_assets = 0
                                
                                # Check for features array (GeoJSON)
                                if 'features' in collection_data:
                                    coll_items = len(collection_data['features'])
                                    
                                    # Count COG/TIF/JP2 assets
                                    for feature in collection_data['features']:
                                        for asset_key, asset in feature.get('assets', {}).items():
                                            asset_type = asset.get('type', '').lower()
                                            asset_href = asset.get('href', '').lower()
                                            
                                            # Check if it's a COG, TIF, or JP2
                                            if any(ext in asset_type or ext in asset_href for ext in ['tif', 'tiff', 'cog', 'jp2', 'jpeg2000']):
                                                coll_cog_assets += 1
                                
                                total_items += coll_items
                                total_cog_assets += coll_cog_assets
                                collections_sampled += 1
                        except:
                            pass
            
            # Build result text
            result_text = (
                f"✅ Connection successful\n"
                f"Response time: {response_time_ms} ms\n"
                f"─────────────────────\n"
                f"Collections (events): {num_collections}\n"
            )
            
            if collections_sampled > 0:
                avg_items = total_items // collections_sampled if collections_sampled > 0 else 0
                avg_cogs = total_cog_assets // collections_sampled if collections_sampled > 0 else 0
                estimated_total_cogs = avg_cogs * num_collections
                
                result_text += (
                    f"Sampled: {collections_sampled} collections\n"
                    f"Total items (sample): {total_items}\n"
                    f"COG/TIF/JP2 assets (sample): {total_cog_assets}\n"
                    f"Estimated total assets: ~{estimated_total_cogs}\n"
                )
            
            result_text += f"─────────────────────\n"
            result_text += "Sample events:\n"
            
            for i, coll in enumerate(collections[:5]):
                result_text += f"  • {coll}\n"
            
            if num_collections > 5:
                result_text += f"  ... and {num_collections - 5} more"
            
            self.vantor_results.setText(result_text)
            self.vantor_results.setStyleSheet("color: #226633; font-size: 9px; font-family: monospace;")
            
            logger.info(f"Vantor test: {num_collections} collections, {total_cog_assets} COG assets (sample), {response_time_ms}ms")
            
        except Exception as e:
            logger.error(f"Vantor connection test error: {e}")
            self.vantor_results.setText(
                f"❌ Test failed\n"
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
        """Test Planet Catalog API access token"""
        access_token = self.planet_access_token.text().strip()
        api_base_url = self.planet_api_base_url.text().strip() or 'https://services.sentinel-hub.com'
        
        if not access_token:
            QMessageBox.warning(
                self,
                "Missing Access Token",
                "Please enter your Planet OAuth2 Access Token."
            )
            return
        
        try:
            from ..connectors import PlanetConnector
            
            connector = PlanetConnector()
            credentials = {
                'access_token': access_token,
                'api_base_url': api_base_url,
            }
            
            # Test authentication with network verification
            success = connector.authenticate(credentials, verify=True)
            
            if success:
                QMessageBox.information(
                    self,
                    "Token Valid",
                    "✅ Planet Catalog token verified!\n\n"
                    "Token accepted by Catalog API."
                )
                logger.info("Planet token verification successful")
            else:
                QMessageBox.warning(
                    self,
                    "Verification Failed",
                    "❌ Planet Catalog token verification failed.\n\n"
                    "Please check token/base URL and try again.\n"
                    "Ensure your Planet access is active for Catalog API."
                )
                logger.warning("Planet token verification failed")
                
        except Exception as e:
            logger.error(f"Planet token verification error: {e}")
            QMessageBox.critical(
                self,
                "Verification Error",
                f"Error verifying Planet token:\n\n{str(e)}"
            )
    
    def _restore_default_iceye(self):
        """Restore default ICEYE endpoint"""
        self.iceye_endpoint.setText('https://api.iceye.com')
        self.iceye_contract_id.clear()
        self.iceye_collections.setText('public')
        self.iceye_catalog_timeout.setValue(12)
        self.iceye_search_timeout.setValue(15)
        logger.info("Restored default ICEYE settings")

    def _restore_default_umbra(self):
        """Restore default Umbra endpoint"""
        self.umbra_api_base_url.setText('https://api.canopy.umbra.space')
        self.umbra_client_id.clear()
        self.umbra_client_secret.clear()
        self.umbra_catalog_timeout.setValue(12)
        self.umbra_search_timeout.setValue(15)
        logger.info("Restored default Umbra settings")
    
    def _restore_default_copernicus(self):
        """Restore default Copernicus settings (DEPRECATED - redirects to STAC)"""
        # This function is deprecated but kept for backward compatibility
        # HDA connector has been removed, only STAC remains
        logger.warning("_restore_default_copernicus() is deprecated, redirecting to STAC")
        self._restore_default_copernicus_stac()
    
    def _restore_default_copernicus_stac(self):
        """Restore default Copernicus STAC settings"""
        self.copernicus_client_id.clear()
        self.copernicus_client_secret.clear()
        self.copernicus_stac_timeout.setValue(15)
        self.copernicus_stac_results.clear()
        logger.info("Restored default Copernicus STAC settings")
    
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
            from ..connectors import UmbraSTACConnector

            connector = UmbraSTACConnector()
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
    
    def _test_copernicus_connection(self):
        """Test Copernicus connection (DEPRECATED - redirects to STAC test)"""
        # This function is deprecated but kept for backward compatibility
        # Redirect to the new STAC-specific test
        logger.warning("_test_copernicus_connection() is deprecated, redirecting to _test_copernicus_stac_connection()")
        self._test_copernicus_stac_connection()
    
    def _test_copernicus_stac_connection(self):
        """Test Copernicus STAC OAuth2 authentication and API access"""
        import time
        
        client_id = self.copernicus_client_id.text().strip()
        client_secret = self.copernicus_client_secret.text().strip()
        timeout = self.copernicus_stac_timeout.value()
        
        if not client_id or not client_secret:
            QMessageBox.warning(
                self, 
                "Missing Credentials", 
                "Please enter both client ID and client secret."
            )
            return
        
        self.copernicus_stac_results.setText("Testing authentication...")
        QApplication.processEvents()
        
        try:
            # Import Copernicus STAC connector
            from ..connectors.copernicus_stac import CopernicusStacConnector
            
            connector = CopernicusStacConnector()
            
            # Test authentication
            start_time = time.time()
            
            success = connector.authenticate({
                'client_id': client_id,
                'client_secret': client_secret
            })
            
            auth_time_ms = int((time.time() - start_time) * 1000)
            
            if not success:
                self.copernicus_stac_results.setText(
                    f"❌ Authentication failed\n"
                    f"Check your credentials at dataspace.copernicus.eu"
                )
                self.copernicus_stac_results.setStyleSheet("color: #ff6666; font-size: 9px; font-family: monospace;")
                return
            
            # Get available collections
            collections_info = [
                ('Sentinel-1 GRD', 'sentinel-1-grd', 'SAR Ground Range Detected'),
                ('Sentinel-2 L2A', 'sentinel-2-l2a', 'Surface Reflectance'),
                ('Sentinel-2 L1C', 'sentinel-2-l1c', 'Top of Atmosphere')
            ]
            
            # Build result text
            result_text = (
                f"✅ Authentication successful\n"
                f"Auth time: {auth_time_ms} ms\n"
                f"─────────────────────\n"
                f"Available Collections:\n"
            )
            
            for name, collection_id, description in collections_info:
                result_text += f"  • {name}\n    ({description})\n"
            
            result_text += (
                f"─────────────────────\n"
                f"API Endpoint: Copernicus STAC\n"
                f"Coverage: 2014-present (global)"
            )
            
            self.copernicus_stac_results.setText(result_text)
            self.copernicus_stac_results.setStyleSheet("color: #226633; font-size: 9px; font-family: monospace;")
            
            logger.info(f"Copernicus STAC test: authenticated in {auth_time_ms}ms")
            
        except ImportError as e:
            logger.error(f"Copernicus STAC connector not available: {e}")
            self.copernicus_stac_results.setText(
                f"❌ Copernicus STAC connector not available\n"
                f"Error: {str(e)}"
            )
            self.copernicus_stac_results.setStyleSheet("color: #ff6666; font-size: 9px; font-family: monospace;")
        except Exception as e:
            logger.error(f"Copernicus STAC connection test error: {e}")
            self.copernicus_stac_results.setText(
                f"❌ Test failed\n"
                f"Error: {str(e)}"
            )
            self.copernicus_stac_results.setStyleSheet("color: #ff6666; font-size: 9px; font-family: monospace;")
    
    def _check_nasa_auth_status(self):
        """Check NASA EarthData authentication status"""
        try:
            import earthaccess
            import os

            # Prefer token path if available, then env username/password
            token = self.nasa_access_token.text().strip()
            if token:
                os.environ['EARTHDATA_TOKEN'] = token
            
            # Try to check if authenticated
            auth = earthaccess.login(strategy="environment", persist=False)
            
            if auth.authenticated:
                self.nasa_auth_status.setText("✅ Authenticated (environment/token)")
                self.nasa_auth_status.setStyleSheet("color: #00ff00; font-size: 9px;")
            else:
                self.nasa_auth_status.setText("❌ Not authenticated")
                self.nasa_auth_status.setStyleSheet("color: #ff6666; font-size: 9px;")
                
        except ImportError:
            self.nasa_auth_status.setText("⚠️ earthaccess not installed")
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
                },
                verify=True,
            )
            
            auth_time_ms = int((time.time() - start_time) * 1000)
            
            if not success:
                self.nasa_results.setText(
                    f"❌ Authentication failed\n"
                    f"Check your credentials and try again"
                )
                self.nasa_results.setStyleSheet("color: #ff6666; font-size: 9px; font-family: monospace;")
                self.nasa_auth_status.setText("❌ Not authenticated")
                self.nasa_auth_status.setStyleSheet("color: #ff6666; font-size: 9px;")
                return
            
            # Load catalog
            start_time = time.time()
            catalog = connector._load_catalog()
            catalog_time_ms = int((time.time() - start_time) * 1000)
            
            if catalog is None or catalog.empty:
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
            if 'Category' in catalog.columns:
                top_categories = catalog['Category'].value_counts().head(5)
                categories_info = "\nTop Categories:\n"
                for cat, count in top_categories.items():
                    if str(cat).strip() and str(cat).lower() != 'nan':
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
                f"Install: pip install earthaccess pandas\n"
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
                f"  2. earthaccess and pandas are installed\n"
                f"  3. Internet connection is active"
            )
            self.nasa_results.setStyleSheet("color: #ff6666; font-size: 9px; font-family: monospace;")

