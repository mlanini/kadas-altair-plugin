"""
Altair EO Data Settings Dock Widget
"""
from qgis.PyQt.QtWidgets import (
    QDockWidget, QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QLineEdit, QPushButton, QCheckBox, QSpinBox, QComboBox,
    QTabWidget, QGroupBox, QFileDialog, QMessageBox, QApplication
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
        super().__init__("Altair Settings", parent)
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
        widget = QWidget()
        self.setWidget(widget)
        
        layout = QVBoxLayout(widget)
        layout.setSpacing(10)
        
        # Header
        header_label = QLabel("Plugin Settings")
        header_font = QFont()
        header_font.setPointSize(12)
        header_font.setBold(True)
        header_label.setFont(header_font)
        header_label.setAlignment(Qt.AlignCenter)
        header_label.setStyleSheet("color: #ffffff;")
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
        
        # Copernicus tab
        copernicus_tab = self._create_copernicus_tab()
        tab_widget.addTab(copernicus_tab, "Copernicus")
        
        # Google Earth Engine tab
        gee_tab = self._create_gee_tab()
        tab_widget.addTab(gee_tab, "Google Earth Engine")
        
        # NASA EarthData tab
        nasa_tab = self._create_nasa_tab()
        tab_widget.addTab(nasa_tab, "NASA EarthData")
        
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
        self.status_label.setStyleSheet("color: gray; font-size: 10px;")
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
        """Create Planet API key settings tab"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # Planet auth group
        planet_group = QGroupBox("Planet API Authentication")
        planet_layout = QFormLayout(planet_group)
        
        # Info label
        info_label = QLabel(
            "Get your Planet API key from <a href='https://www.planet.com/account/'>Planet Account Settings</a>."
        )
        info_label.setOpenExternalLinks(True)
        info_label.setWordWrap(True)
        info_label.setStyleSheet("color: #cccccc; font-size: 9px;")
        planet_layout.addRow("", info_label)
        
        # API Key
        self.planet_api_key = QLineEdit()
        self.planet_api_key.setPlaceholderText("Enter API Key (PLAKxxxxxxxxxxxxxxxx)")
        self.planet_api_key.setEchoMode(QLineEdit.Password)
        planet_layout.addRow("API Key:", self.planet_api_key)
        
        # Test connection button
        test_planet_btn = QPushButton("Verify API Key")
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
            "Vantor STAC provides direct access to Maxar Open Data via STAC API endpoint. "
            "This is an alternative to the AWS STAC connector."
        )
        info_label.setWordWrap(True)
        info_label.setStyleSheet("color: #cccccc; font-size: 9px;")
        vantor_layout.addRow("", info_label)
        
        # STAC Endpoint URL
        self.vantor_endpoint = QLineEdit()
        self.vantor_endpoint.setPlaceholderText("https://maxar-opendata.s3.amazonaws.com/events/catalog.json")
        vantor_layout.addRow("STAC Endpoint:", self.vantor_endpoint)
        
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
        """Create ICEYE SAR Open Data settings tab"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # ICEYE configuration group
        iceye_group = QGroupBox("ICEYE SAR Open Data Configuration")
        iceye_layout = QFormLayout(iceye_group)
        
        # Info label
        info_label = QLabel(
            "ICEYE SAR Open Data provides free SAR imagery via STAC API. "
            "No authentication required."
        )
        info_label.setWordWrap(True)
        info_label.setStyleSheet("color: #cccccc; font-size: 9px;")
        iceye_layout.addRow("", info_label)
        
        # STAC Endpoint URL
        self.iceye_endpoint = QLineEdit()
        self.iceye_endpoint.setPlaceholderText("https://iceye-open-data-catalog.s3.amazonaws.com/catalog.json")
        iceye_layout.addRow("STAC Endpoint:", self.iceye_endpoint)
        
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
        test_btn = QPushButton("Test STAC Connection")
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
    
    def _create_copernicus_tab(self):
        """Create Copernicus Dataspace settings tab"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # Copernicus configuration group
        copernicus_group = QGroupBox("Copernicus Dataspace Configuration")
        copernicus_layout = QFormLayout(copernicus_group)
        
        # Info label
        info_label = QLabel(
            "Copernicus Dataspace provides Sentinel-1/2 data via Sentinel Hub API. "
            "Requires free account registration at dataspace.copernicus.eu. "
            "Create OAuth2 credentials (client_id/client_secret) in your account settings."
        )
        info_label.setWordWrap(True)
        info_label.setStyleSheet("color: #cccccc; font-size: 9px;")
        copernicus_layout.addRow("", info_label)
        
        # Client ID (NOT secret - should be visible)
        self.copernicus_client_id = QLineEdit()
        self.copernicus_client_id.setPlaceholderText("Enter OAuth2 client ID (e.g., sh-1234abcd-...)")
        # Client ID is NOT secret - do not mask it
        copernicus_layout.addRow("Client ID:", self.copernicus_client_id)
        
        # Client Secret (this IS secret - mask it)
        self.copernicus_client_secret = QLineEdit()
        self.copernicus_client_secret.setPlaceholderText("Enter OAuth2 client secret")
        self.copernicus_client_secret.setEchoMode(QLineEdit.Password)
        copernicus_layout.addRow("Client Secret:", self.copernicus_client_secret)
        
        # Timeout settings
        self.copernicus_timeout = QSpinBox()
        self.copernicus_timeout.setRange(5, 60)
        self.copernicus_timeout.setValue(15)
        self.copernicus_timeout.setSuffix(" sec")
        copernicus_layout.addRow("Request Timeout:", self.copernicus_timeout)
        
        # Default button
        default_btn = QPushButton("Restore Defaults")
        default_btn.clicked.connect(self._restore_default_copernicus)
        copernicus_layout.addRow("", default_btn)
        
        # Test connection button
        test_btn = QPushButton("Test Connection")
        test_btn.clicked.connect(self._test_copernicus_connection)
        copernicus_layout.addRow("", test_btn)
        
        # Results display
        self.copernicus_results = QLabel("")
        self.copernicus_results.setWordWrap(True)
        self.copernicus_results.setStyleSheet("color: #cccccc; font-size: 9px; font-family: monospace;")
        copernicus_layout.addRow("", self.copernicus_results)
        
        layout.addWidget(copernicus_group)
        layout.addStretch()
        
        return widget

    def _create_gee_tab(self):
        """Create Google Earth Engine settings tab"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # GEE configuration group
        gee_group = QGroupBox("Google Earth Engine Configuration")
        gee_layout = QFormLayout(gee_group)
        
        # Info label with setup instructions
        info_label = QLabel(
            "Google Earth Engine provides access to 5,140+ Earth observation datasets "
            "(Landsat, Sentinel, MODIS, etc.). Requires free Google account and Google Cloud Project."
        )
        info_label.setWordWrap(True)
        info_label.setStyleSheet("color: #cccccc; font-size: 9px;")
        gee_layout.addRow("", info_label)
        
        # Setup instructions link
        setup_label = QLabel(
            "📖 <a href='https://developers.google.com/earth-engine/guides/getstarted'>GEE Setup Guide</a> | "
            "<a href='https://console.cloud.google.com/'>Google Cloud Console</a>"
        )
        setup_label.setOpenExternalLinks(True)
        setup_label.setStyleSheet("color: #4CAF50; font-size: 9px;")
        gee_layout.addRow("", setup_label)
        
        # Google Cloud Project ID (required)
        self.gee_project_id = QLineEdit()
        self.gee_project_id.setPlaceholderText("your-gcp-project-id")
        gee_layout.addRow("Project ID*:", self.gee_project_id)
        
        project_info = QLabel(
            "* Required: Your Google Cloud Project ID (not the project name). "
            "Enable 'Earth Engine API' in the project."
        )
        project_info.setWordWrap(True)
        project_info.setStyleSheet("color: #ffaa00; font-size: 9px; font-style: italic;")
        gee_layout.addRow("", project_info)
        
        # Catalog cache timeout
        self.gee_cache_timeout = QSpinBox()
        self.gee_cache_timeout.setRange(5, 120)
        self.gee_cache_timeout.setValue(60)
        self.gee_cache_timeout.setSuffix(" minutes")
        gee_layout.addRow("Catalog Cache:", self.gee_cache_timeout)
        
        cache_info = QLabel("How long to cache the GEE catalog locally (reduces loading time)")
        cache_info.setStyleSheet("color: gray; font-size: 8px; font-style: italic;")
        gee_layout.addRow("", cache_info)
        
        # Authentication status
        self.gee_auth_status = QLabel("")
        self.gee_auth_status.setWordWrap(True)
        self.gee_auth_status.setStyleSheet("color: #cccccc; font-size: 9px;")
        gee_layout.addRow("Auth Status:", self.gee_auth_status)
        
        # Authentication button
        auth_btn = QPushButton("Authenticate with Google")
        auth_btn.clicked.connect(self._authenticate_gee)
        auth_btn.setStyleSheet("background-color: #4CAF50; font-weight: bold;")
        gee_layout.addRow("", auth_btn)
        
        auth_info = QLabel(
            "⚠️ First-time setup: Click 'Authenticate' to login with your Google account. "
            "This opens a browser window for OAuth2 authentication."
        )
        auth_info.setWordWrap(True)
        auth_info.setStyleSheet("color: #ffaa00; font-size: 9px;")
        gee_layout.addRow("", auth_info)
        
        # Test connection button
        test_btn = QPushButton("Test Connection")
        test_btn.clicked.connect(self._test_gee_connection)
        gee_layout.addRow("", test_btn)
        
        # Results display
        self.gee_results = QLabel("")
        self.gee_results.setWordWrap(True)
        self.gee_results.setStyleSheet("color: #cccccc; font-size: 9px; font-family: monospace;")
        gee_layout.addRow("", self.gee_results)
        
        layout.addWidget(gee_group)
        
        # Installation instructions group
        install_group = QGroupBox("Installation")
        install_layout = QVBoxLayout(install_group)
        
        install_info = QLabel(
            "The Google Earth Engine connector requires the 'earthengine-api' Python package.\n\n"
            "To install in QGIS Python Console:\n"
            ">>> import subprocess, sys\n"
            ">>> subprocess.check_call([sys.executable, '-m', 'pip', 'install', 'earthengine-api'])"
        )
        install_info.setWordWrap(True)
        install_info.setStyleSheet("color: #cccccc; font-size: 9px; font-family: monospace;")
        install_layout.addWidget(install_info)
        
        layout.addWidget(install_group)
        layout.addStretch()
        
        return widget

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
        
        cred_info = QLabel(
            "* Required: Credentials are saved securely and used for authentication.\n"
            "Stored in ~/.netrc file for persistent access."
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
        
        self.max_results = QSpinBox()
        self.max_results.setRange(10, 1000)
        self.max_results.setValue(100)
        layer_layout.addRow("Maximum results:", self.max_results)
        
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
        self.max_results.setValue(
            self.settings.value(f"{self.SETTINGS_PREFIX}max_results", 100, type=int)
        )
        
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
                self.planet_api_key.setText(planet_creds.get('api_key', ''))
        
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
        default_iceye_endpoint = 'https://iceye-open-data-catalog.s3.amazonaws.com/catalog.json'
        self.iceye_endpoint.setText(
            self.settings.value(f"{self.SETTINGS_PREFIX}iceye_endpoint", default_iceye_endpoint)
        )
        self.iceye_catalog_timeout.setValue(
            self.settings.value(f"{self.SETTINGS_PREFIX}iceye_catalog_timeout", 12, type=int)
        )
        self.iceye_search_timeout.setValue(
            self.settings.value(f"{self.SETTINGS_PREFIX}iceye_search_timeout", 15, type=int)
        )
        
        # Copernicus (credentials from secure storage)
        if self.secure_storage:
            copernicus_creds = self.secure_storage.get_credentials('copernicus')
            logger.debug(f"Loading Copernicus credentials from secure storage: {copernicus_creds is not None}")
            if copernicus_creds:
                client_id = copernicus_creds.get('client_id', '')
                client_secret = copernicus_creds.get('client_secret', '')
                logger.debug(f"Copernicus client_id length: {len(client_id)}, client_secret length: {len(client_secret)}")
                self.copernicus_client_id.setText(client_id)
                self.copernicus_client_secret.setText(client_secret)
        
        self.copernicus_timeout.setValue(
            self.settings.value(f"{self.SETTINGS_PREFIX}copernicus_timeout", 15, type=int)
        )
        
        # Google Earth Engine
        gee_project_id = self.settings.value("altair/gee_project_id", "")
        if gee_project_id:
            self.gee_project_id.setText(gee_project_id)
        
        self.gee_cache_timeout.setValue(
            self.settings.value(f"{self.SETTINGS_PREFIX}gee_cache_timeout", 60, type=int)
        )
        
        # Check GEE authentication status
        self._check_gee_auth_status()
        
        # NASA EarthData
        nasa_username = self.settings.value("altair/nasa_username", "")
        if nasa_username:
            self.nasa_username.setText(nasa_username)
        
        # Load password from secure storage
        if self.secure_storage:
            nasa_creds = self.secure_storage.get_credentials('nasa_earthdata')
            if nasa_creds:
                self.nasa_password.setText(nasa_creds.get('password', ''))
        else:
            # Fallback: load from QSettings
            nasa_password = self.settings.value("altair/nasa_password", "")
            if nasa_password:
                self.nasa_password.setText(nasa_password)
        
        self.nasa_cache_timeout.setValue(
            self.settings.value(f"{self.SETTINGS_PREFIX}nasa_cache_timeout", 7, type=int)
        )
        
        # Check NASA authentication status
        self._check_nasa_auth_status()

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
        if self.secure_storage:
            planet_api_key = self.planet_api_key.text().strip()
            if planet_api_key:
                self.secure_storage.store_credentials('planet', {
                    'api_key': planet_api_key
                })
                logger.info("Planet API key saved to secure storage")
        
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
            self.iceye_endpoint.text()
        )
        self.settings.setValue(
            f"{self.SETTINGS_PREFIX}iceye_catalog_timeout",
            self.iceye_catalog_timeout.value()
        )
        self.settings.setValue(
            f"{self.SETTINGS_PREFIX}iceye_search_timeout",
            self.iceye_search_timeout.value()
        )
        
        # Copernicus (save to secure storage)
        if self.secure_storage:
            copernicus_client_id = self.copernicus_client_id.text().strip()
            copernicus_client_secret = self.copernicus_client_secret.text().strip()
            if copernicus_client_id and copernicus_client_secret:
                logger.info(f"Saving Copernicus credentials - client_id length: {len(copernicus_client_id)}")
                self.secure_storage.store_credentials('copernicus', {
                    'client_id': copernicus_client_id,
                    'client_secret': copernicus_client_secret
                })
                logger.info("Copernicus credentials saved to secure storage")
            else:
                logger.debug("Copernicus credentials empty, not saving")
        
        self.settings.setValue(
            f"{self.SETTINGS_PREFIX}copernicus_timeout",
            self.copernicus_timeout.value()
        )
        
        # Google Earth Engine
        gee_project_id = self.gee_project_id.text().strip()
        if gee_project_id:
            self.settings.setValue("altair/gee_project_id", gee_project_id)
            logger.info(f"GEE Project ID saved: {gee_project_id}")
        else:
            self.settings.remove("altair/gee_project_id")
            logger.info("GEE Project ID cleared")
        
        self.settings.setValue(
            f"{self.SETTINGS_PREFIX}gee_cache_timeout",
            self.gee_cache_timeout.value()
        )
        
        # NASA EarthData
        nasa_username = self.nasa_username.text().strip()
        nasa_password = self.nasa_password.text().strip()
        
        if nasa_username and nasa_password:
            self.settings.setValue("altair/nasa_username", nasa_username)
            # Save password to secure storage
            if self.secure_storage:
                self.secure_storage.store_credentials('nasa_earthdata', {
                    'username': nasa_username,
                    'password': nasa_password
                })
                logger.info("NASA EarthData credentials saved to secure storage")
            else:
                # Fallback: save password to QSettings (less secure)
                self.settings.setValue("altair/nasa_password", nasa_password)
                logger.warning("NASA EarthData password saved to QSettings (secure storage not available)")
        else:
            self.settings.remove("altair/nasa_username")
            self.settings.remove("altair/nasa_password")
            if self.secure_storage:
                self.secure_storage.store_credentials('nasa_earthdata', {})
            logger.info("NASA EarthData credentials cleared")
        
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
        """Test Planet API key"""
        api_key = self.planet_api_key.text().strip()
        
        if not api_key:
            QMessageBox.warning(
                self,
                "Missing API Key",
                "Please enter your Planet API Key."
            )
            return
        
        try:
            from ..connectors import PlanetConnector
            
            connector = PlanetConnector()
            credentials = {'api_key': api_key}
            
            # Test authentication with network verification
            success = connector.authenticate(credentials, verify=True)
            
            if success:
                QMessageBox.information(
                    self,
                    "API Key Valid",
                    "✅ Planet API key verified!\n\n"
                    "Your API key is valid and active."
                )
                logger.info("Planet API key verification successful")
            else:
                QMessageBox.warning(
                    self,
                    "Verification Failed",
                    "❌ Planet API key verification failed.\n\n"
                    "Please check your API key and try again.\n"
                    "Ensure your Planet account is active."
                )
                logger.warning("Planet API key verification failed")
                
        except Exception as e:
            logger.error(f"Planet API key verification error: {e}")
            QMessageBox.critical(
                self,
                "Verification Error",
                f"Error verifying Planet API key:\n\n{str(e)}"
            )
    
    def _restore_default_iceye(self):
        """Restore default ICEYE endpoint"""
        self.iceye_endpoint.setText('https://iceye-open-data-catalog.s3.amazonaws.com/catalog.json')
        self.iceye_catalog_timeout.setValue(12)
        self.iceye_search_timeout.setValue(15)
        logger.info("Restored default ICEYE settings")
    
    def _restore_default_copernicus(self):
        """Restore default Copernicus settings"""
        self.copernicus_client_id.clear()
        self.copernicus_client_secret.clear()
        self.copernicus_timeout.setValue(15)
        logger.info("Restored default Copernicus settings")
    
    def _test_iceye_connection(self):
        """Test ICEYE STAC connection and count available data"""
        import time
        import json
        
        endpoint = self.iceye_endpoint.text().strip()
        timeout = self.iceye_catalog_timeout.value()
        
        if not endpoint:
            QMessageBox.warning(self, "Missing URL", "Please enter STAC endpoint URL.")
            return
        
        self.iceye_results.setText("Testing connection...")
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
                self.iceye_results.setText(
                    f"❌ Connection failed\n"
                    f"Error: {blocking_request.errorMessage()}"
                )
                self.iceye_results.setStyleSheet("color: #ff6666; font-size: 9px; font-family: monospace;")
                return
            
            # Parse STAC catalog
            reply = blocking_request.reply()
            content = reply.content().data().decode('utf-8')
            catalog = json.loads(content)
            
            # Count collections
            collections = []
            for link in catalog.get('links', []):
                if link.get('rel') == 'child':
                    collections.append(link.get('title', link.get('href', 'Unknown')))
            
            num_collections = len(collections)
            
            # Try to count items in first collection (sample)
            sample_items = 0
            sample_cog_assets = 0
            
            if collections and catalog.get('links'):
                # Find first child link
                for link in catalog.get('links', []):
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
                                    
                                    # Count items
                                    for item_link in collection_data.get('links', []):
                                        if item_link.get('rel') == 'item':
                                            sample_items += 1
                                    
                                    # If collection has features array (GeoJSON)
                                    if 'features' in collection_data:
                                        sample_items = len(collection_data['features'])
                                        
                                        # Count COG/TIF assets
                                        for feature in collection_data['features']:
                                            for asset_key, asset in feature.get('assets', {}).items():
                                                asset_type = asset.get('type', '').lower()
                                                asset_href = asset.get('href', '').lower()
                                                if 'tif' in asset_type or 'tif' in asset_href or 'cog' in asset_type:
                                                    sample_cog_assets += 1
                                
                                break  # Only sample first collection
                            except:
                                pass
            
            # Build result text
            result_text = (
                f"✅ Connection successful\n"
                f"Response time: {response_time_ms} ms\n"
                f"─────────────────────\n"
                f"Collections: {num_collections}\n"
            )
            
            if sample_items > 0:
                result_text += (
                    f"Sample collection items: {sample_items}\n"
                    f"COG/TIF assets (sample): {sample_cog_assets}\n"
                )
            
            result_text += f"─────────────────────\n"
            result_text += "Collections:\n"
            
            for i, coll in enumerate(collections[:5]):
                result_text += f"  • {coll}\n"
            
            if num_collections > 5:
                result_text += f"  ... and {num_collections - 5} more"
            
            self.iceye_results.setText(result_text)
            self.iceye_results.setStyleSheet("color: #226633; font-size: 9px; font-family: monospace;")
            
            logger.info(f"ICEYE test: {num_collections} collections, {response_time_ms}ms")
            
        except Exception as e:
            logger.error(f"ICEYE connection test error: {e}")
            self.iceye_results.setText(
                f"❌ Test failed\n"
                f"Error: {str(e)}"
            )
            self.iceye_results.setStyleSheet("color: #ff6666; font-size: 9px; font-family: monospace;")
    
    def _test_copernicus_connection(self):
        """Test Copernicus OAuth2 authentication and API access"""
        import time
        import json
        
        client_id = self.copernicus_client_id.text().strip()
        client_secret = self.copernicus_client_secret.text().strip()
        timeout = self.copernicus_timeout.value()
        
        if not client_id or not client_secret:
            QMessageBox.warning(
                self, 
                "Missing Credentials", 
                "Please enter both client ID and client secret."
            )
            return
        
        self.copernicus_results.setText("Testing authentication...")
        QApplication.processEvents()
        
        try:
            # Import Copernicus connector
            from ..connectors.copernicus import CopernicusConnector
            
            connector = CopernicusConnector()
            
            # Test authentication
            start_time = time.time()
            
            success = connector.authenticate({
                'client_id': client_id,
                'client_secret': client_secret
            })
            
            auth_time_ms = int((time.time() - start_time) * 1000)
            
            if not success:
                self.copernicus_results.setText(
                    f"❌ Authentication failed\n"
                    f"Check your credentials at dataspace.copernicus.eu"
                )
                self.copernicus_results.setStyleSheet("color: #ff6666; font-size: 9px; font-family: monospace;")
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
                f"API Endpoint: Sentinel Hub Catalog\n"
                f"Coverage: 2014-present (global)"
            )
            
            self.copernicus_results.setText(result_text)
            self.copernicus_results.setStyleSheet("color: #226633; font-size: 9px; font-family: monospace;")
            
            logger.info(f"Copernicus test: authenticated in {auth_time_ms}ms")
            
        except ImportError as e:
            logger.error(f"Copernicus connector not available: {e}")
            self.copernicus_results.setText(
                f"❌ Copernicus connector not available\n"
                f"Error: {str(e)}"
            )
            self.copernicus_results.setStyleSheet("color: #ff6666; font-size: 9px; font-family: monospace;")
        except Exception as e:
            logger.error(f"Copernicus connection test error: {e}")
            self.copernicus_results.setText(
                f"❌ Test failed\n"
                f"Error: {str(e)}"
            )
            self.copernicus_results.setStyleSheet("color: #ff6666; font-size: 9px; font-family: monospace;")

    def _check_gee_auth_status(self):
        """Check Google Earth Engine authentication status"""
        try:
            import ee
            
            # Try to initialize and test connection
            ee.Number(1).getInfo()
            
            self.gee_auth_status.setText("✅ Authenticated")
            self.gee_auth_status.setStyleSheet("color: #00ff00; font-size: 9px;")
            
        except ImportError:
            self.gee_auth_status.setText("⚠️ earthengine-api not installed")
            self.gee_auth_status.setStyleSheet("color: #ffaa00; font-size: 9px;")
        except Exception:
            self.gee_auth_status.setText("❌ Not authenticated - Click 'Authenticate' button")
            self.gee_auth_status.setStyleSheet("color: #ff6666; font-size: 9px;")

    def _authenticate_gee(self):
        """Authenticate with Google Earth Engine"""
        try:
            import ee
            
            QMessageBox.information(
                self,
                "GEE Authentication",
                "A browser window will open for Google authentication.\n\n"
                "1. Login with your Google account\n"
                "2. Authorize Earth Engine access\n"
                "3. Return to QGIS after success\n\n"
                "Click OK to continue..."
            )
            
            self.gee_auth_status.setText("⏳ Opening browser for authentication...")
            self.gee_auth_status.setStyleSheet("color: #ffaa00; font-size: 9px;")
            QApplication.processEvents()
            
            # Trigger authentication (opens browser)
            ee.Authenticate()
            
            # Test the authentication
            ee.Initialize()
            ee.Number(1).getInfo()
            
            self.gee_auth_status.setText("✅ Authentication successful!")
            self.gee_auth_status.setStyleSheet("color: #00ff00; font-size: 9px;")
            
            QMessageBox.information(
                self,
                "Success",
                "Google Earth Engine authentication successful!\n\n"
                "Don't forget to set your Project ID above."
            )
            
        except ImportError:
            QMessageBox.critical(
                self,
                "Missing Library",
                "earthengine-api not installed.\n\n"
                "Install in QGIS Python Console:\n"
                ">>> import subprocess, sys\n"
                ">>> subprocess.check_call([sys.executable, '-m', 'pip', 'install', 'earthengine-api'])"
            )
            self.gee_auth_status.setText("⚠️ earthengine-api not installed")
            self.gee_auth_status.setStyleSheet("color: #ffaa00; font-size: 9px;")
        except Exception as e:
            error_msg = str(e)
            QMessageBox.critical(
                self,
                "Authentication Failed",
                f"Failed to authenticate with Google Earth Engine:\n\n{error_msg}"
            )
            self.gee_auth_status.setText(f"❌ Authentication failed: {error_msg[:50]}")
            self.gee_auth_status.setStyleSheet("color: #ff6666; font-size: 9px;")

    def _test_gee_connection(self):
        """Test Google Earth Engine connection and catalog access"""
        import time
        
        project_id = self.gee_project_id.text().strip()
        
        if not project_id:
            QMessageBox.warning(
                self,
                "Missing Project ID",
                "Please enter your Google Cloud Project ID.\n\n"
                "Get your Project ID from:\n"
                "https://console.cloud.google.com/"
            )
            return
        
        self.gee_results.setText("Testing connection...")
        QApplication.processEvents()
        
        try:
            from ..connectors.gee import GeeConnector
            
            connector = GeeConnector(project_id=project_id)
            
            # Test authentication
            start_time = time.time()
            
            success = connector.authenticate(verify=True)
            
            auth_time_ms = int((time.time() - start_time) * 1000)
            
            if not success:
                self.gee_results.setText(
                    f"❌ Connection failed\n"
                    f"Check authentication and project ID"
                )
                self.gee_results.setStyleSheet("color: #ff6666; font-size: 9px; font-family: monospace;")
                return
            
            # Load catalog
            start_time = time.time()
            catalog = connector._load_catalog()
            catalog_time_ms = int((time.time() - start_time) * 1000)
            
            # Count by source
            official_count = sum(1 for d in catalog if d.get('source') == 'official')
            community_count = sum(1 for d in catalog if d.get('source') == 'community')
            
            # Get categories
            categories = {}
            for dataset in catalog:
                category = dataset.get('category', 'Other')
                categories[category] = categories.get(category, 0) + 1
            
            top_categories = sorted(categories.items(), key=lambda x: x[1], reverse=True)[:5]
            
            # Build result text
            result_text = (
                f"✅ Connection successful\n"
                f"Auth time: {auth_time_ms} ms\n"
                f"Catalog load: {catalog_time_ms} ms\n"
                f"─────────────────────\n"
                f"Available Datasets:\n"
                f"  • Official: {official_count}\n"
                f"  • Community: {community_count}\n"
                f"  • TOTAL: {len(catalog)}\n"
                f"─────────────────────\n"
                f"Top Categories:\n"
            )
            
            for category, count in top_categories:
                result_text += f"  • {category}: {count}\n"
            
            result_text += (
                f"─────────────────────\n"
                f"Project: {project_id}\n"
                f"API: Google Earth Engine\n"
                f"Coverage: 1972-present (varies by dataset)"
            )
            
            self.gee_results.setText(result_text)
            self.gee_results.setStyleSheet("color: #226633; font-size: 9px; font-family: monospace;")
            
            logger.info(f"GEE test: loaded {len(catalog)} datasets in {catalog_time_ms}ms")
            
        except ImportError as e:
            logger.error(f"GEE connector not available: {e}")
            self.gee_results.setText(
                f"❌ Google Earth Engine not available\n"
                f"Install: pip install earthengine-api\n"
                f"Error: {str(e)}"
            )
            self.gee_results.setStyleSheet("color: #ff6666; font-size: 9px; font-family: monospace;")
        except Exception as e:
            logger.error(f"GEE connection test error: {e}")
            self.gee_results.setText(
                f"❌ Test failed\n"
                f"Error: {str(e)}\n\n"
                f"Check:\n"
                f"  1. Authentication (click 'Authenticate' button)\n"
                f"  2. Project ID is correct\n"
                f"  3. Earth Engine API is enabled in GCP project"
            )
            self.gee_results.setStyleSheet("color: #ff6666; font-size: 9px; font-family: monospace;")

    def _check_nasa_auth_status(self):
        """Check NASA EarthData authentication status"""
        try:
            import earthaccess
            
            # Try to check if authenticated
            auth = earthaccess.login(strategy="environment", persist=False)
            
            if auth.authenticated:
                self.nasa_auth_status.setText("✅ Authenticated")
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
        
        if not username or not password:
            QMessageBox.warning(
                self,
                "Missing Credentials",
                "Please enter both username and password.\n\n"
                "Register at: https://urs.earthdata.nasa.gov/"
            )
            return
        
        self.nasa_results.setText("Testing credentials...")
        QApplication.processEvents()
        
        try:
            from ..connectors.nasa_earthdata import NasaEarthdataConnector
            
            connector = NasaEarthdataConnector(username=username, password=password)
            
            # Test authentication
            start_time = time.time()
            
            # Set environment variables
            os.environ['EARTHDATA_USERNAME'] = username
            os.environ['EARTHDATA_PASSWORD'] = password
            
            success = connector.authenticate(verify=True)
            
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
                    if pd.notna(cat):
                        categories_info += f"  • {cat}: {count}\n"
            
            # Build result text
            result_text = (
                f"✅ Authentication successful\n"
                f"Auth time: {auth_time_ms} ms\n"
                f"Catalog load: {catalog_time_ms} ms\n"
                f"─────────────────────\n"
                f"Available Datasets: {dataset_count}\n"
                f"{categories_info}"
                f"─────────────────────\n"
                f"Username: {username}\n"
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
                f"  1. Credentials are correct\n"
                f"  2. earthaccess and pandas are installed\n"
                f"  3. Internet connection is active"
            )
            self.nasa_results.setStyleSheet("color: #ff6666; font-size: 9px; font-family: monospace;")

