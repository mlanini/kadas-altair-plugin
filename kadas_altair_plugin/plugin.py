"""
KADAS Altair EO Data Plugin - Main Module
"""
import os
import socket
from qgis.PyQt.QtCore import QObject, QSettings, QStandardPaths
from qgis.PyQt.QtWidgets import QAction, QMenu, QMessageBox
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtNetwork import QNetworkProxy, QNetworkProxyFactory

# Setup plugin logging
from .logger import setup_logging, get_logger

# Get user profile path for logging
try:
    user_profile = QStandardPaths.writableLocation(QStandardPaths.HomeLocation)
except:
    import os
    user_profile = os.path.expanduser("~")

# Initialize logging system
setup_logging(user_profile)
logger = get_logger('plugin')

# Apply user's preferred log level from settings
try:
    from qgis.PyQt.QtCore import QSettings
    from .logger import set_log_level
    settings = QSettings()
    log_level = settings.value("AltairEOData/log_level", "INFO")
    set_log_level(log_level)
    logger.info(f"Log level set to: {log_level}")
except Exception as e:
    logger.warning(f"Could not load log level setting, using default INFO: {e}")

logger.info("KADAS Altair Plugin module loaded")

try:
    from kadas.kadasgui import KadasPluginInterface
    logger.debug("Using KADAS interface")
except ImportError:
    # Fallback for test/dev environments
    logger.warning("KADAS interface not available, using fallback")
    class KadasPluginInterface:
        @staticmethod
        def cast(iface):
            return iface


class KadasAltair(QObject):
    """KADAS-compatible plugin for EO data browsing."""

    def __init__(self, iface):
        QObject.__init__(self)
        logger.info("Initializing KADAS Altair plugin")
        
        self.iface = KadasPluginInterface.cast(iface)
        self.plugin_dir = os.path.dirname(__file__)
        self.actions = []
        self.menu = None
        self._main_dock = None
        self._settings_dock = None
        
        logger.info(f"Plugin directory: {self.plugin_dir}")
        logger.debug(f"QGIS interface type: {type(self.iface)}")

    def tr(self, message):
        """Translate message"""
        return message

    def add_action(self, icon_path, text, callback, add_to_menu=True, 
                   status_tip=None, checkable=False, parent=None):
        """Add action to menu"""
        icon = QIcon(icon_path) if icon_path else QIcon()
        action = QAction(icon, text, parent)
        action.triggered.connect(callback)
        action.setCheckable(checkable)
        if status_tip:
            action.setStatusTip(status_tip)
        if add_to_menu and self.menu:
            self.menu.addAction(action)
        self.actions.append(action)
        return action

    def _apply_proxy_settings(self):
        """Apply proxy settings from KADAS/QGIS to Qt and HTTP libraries.
        
        Based on kadas-vantor-plugin proxy handling for KADAS Albireo 2.
        Propagates KADAS proxy configuration to:
        - Qt network layer (QNetworkProxy)
        - Environment variables (HTTP_PROXY, HTTPS_PROXY, etc.)
        - Detects VPN connections
        """
        settings = QSettings()
        enabled = settings.value("proxy/enabled", False, type=bool)
        
        # Environment variables for external libraries (requests, urllib, etc.)
        proxy_vars = (
            "HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy",
            "ALL_PROXY", "all_proxy", "NO_PROXY", "no_proxy"
        )
        
        if not enabled:
            # No proxy: use system configuration
            QNetworkProxyFactory.setUseSystemConfiguration(True)
            QNetworkProxy.setApplicationProxy(QNetworkProxy(QNetworkProxy.NoProxy))
            logger.info("Proxy disabled: using system configuration")
            
            # Remove all proxy environment variables
            for var in proxy_vars:
                if var in os.environ:
                    del os.environ[var]
                    logger.debug(f"Removed environment variable: {var}")
            return
        
        # Proxy enabled: read configuration
        proxy_type = settings.value("proxy/type", "HttpProxy")
        host = settings.value("proxy/host", "", type=str)
        port = settings.value("proxy/port", 0, type=int)
        user = settings.value("proxy/user", "", type=str)
        password = settings.value("proxy/password", "", type=str)
        excludes = settings.value("proxy/excludes", "", type=str)
        
        # Map QGIS proxy types to Qt types
        qt_type_map = {
            "HttpProxy": QNetworkProxy.HttpProxy,
            "HttpCachingProxy": QNetworkProxy.HttpCachingProxy,
            "Socks5Proxy": QNetworkProxy.Socks5Proxy,
            "FtpCachingProxy": QNetworkProxy.FtpCachingProxy,
        }
        
        # Apply Qt proxy
        qproxy = QNetworkProxy(
            qt_type_map.get(proxy_type, QNetworkProxy.HttpProxy),
            host, port, user, password
        )
        QNetworkProxy.setApplicationProxy(qproxy)
        QNetworkProxyFactory.setUseSystemConfiguration(False)
        logger.info(f"Proxy applied: {proxy_type}://{host}:{port} (user: {user or 'none'})")
        
        # Propagate to external libraries (requests/urllib, etc.)
        if host and port:
            scheme = "socks5h" if proxy_type.startswith("Socks5") else "http"
            cred = f"{user}:{password}@" if user else ""
            proxy_url = f"{scheme}://{cred}{host}:{port}"
            
            for var in proxy_vars:
                if var.lower().startswith("no_proxy"):
                    continue
                os.environ[var] = proxy_url
                logger.debug(f"Environment variable set: {var}={proxy_url}")
            
            if excludes:
                os.environ["NO_PROXY"] = excludes
                os.environ["no_proxy"] = excludes
                logger.debug(f"NO_PROXY set: {excludes}")
        else:
            # Remove variables if host/port invalid
            for var in proxy_vars:
                if var in os.environ:
                    del os.environ[var]
                    logger.debug(f"Environment variable removed: {var}")
        
        # VPN detection (as in kadas-albireo2 and kadas-vantor-plugin)
        try:
            gw = socket.gethostbyname(socket.gethostname())
            if gw.startswith("10.") or gw.startswith("172.") or gw.startswith("192.168."):
                logger.info("Connection probably NOT via VPN (private network detected)")
            else:
                logger.info("Connection probably via VPN or public network")
        except Exception as e:
            logger.warning(f"Unable to determine VPN status: {e}")

    def initGui(self):
        """Initialize GUI - setup menu and actions"""
        # Apply KADAS proxy settings (propagate to Qt and environment variables)
        # This ensures all network operations (QgsNetworkAccessManager, requests, urllib)
        # use the same proxy configuration from KADAS Settings → Network
        self._apply_proxy_settings()
        logger.info("Proxy configuration applied from KADAS settings")
        
        # Create menu
        self.menu = QMenu(self.tr("Altair"))

        # Icon paths
        icon_base = os.path.join(self.plugin_dir, "icons")
        main_icon = os.path.join(icon_base, "icon.svg")
        settings_icon = os.path.join(icon_base, "settings.svg")
        about_icon = os.path.join(icon_base, "about.svg")
        help_icon = os.path.join(icon_base, "help.svg")  # Will fallback to default if not exists

        # Main dock action
        self.main_action = self.add_action(
            main_icon,
            self.tr("Altair EO Data Panel"),
            self.toggle_main_dock,
            status_tip=self.tr("Toggle Altair EO Data Panel"),
            checkable=True,
            parent=self.iface.mainWindow(),
        )

        # Settings action
        self.settings_action = self.add_action(
            settings_icon,
            self.tr("Settings"),
            self.toggle_settings_dock,
            status_tip=self.tr("Toggle Settings Panel"),
            checkable=True,
            parent=self.iface.mainWindow(),
        )

        # Separator
        self.menu.addSeparator()

        # View Logs action
        self.add_action(
            None,  # No icon for now
            self.tr("View Log"),
            self.show_log_viewer,
            add_to_menu=True,
            status_tip=self.tr("Open Plugin Log Viewer"),
            parent=self.iface.mainWindow(),
        )

        # Help action
        self.add_action(
            help_icon if os.path.exists(help_icon) else None,
            self.tr("Help"),
            self.show_help,
            add_to_menu=True,
            status_tip=self.tr("Open Altair Plugin Help"),
            parent=self.iface.mainWindow(),
        )

        # About action
        self.add_action(
            about_icon,
            self.tr("About Altair EO Data Plugin"),
            self.show_about,
            add_to_menu=True,
            status_tip=self.tr("About Altair EO Data Plugin"),
            parent=self.iface.mainWindow(),
        )

        # Register menu with KADAS interface - create custom "EO" tab
        # Pattern from kadas-vantor: addActionMenu(title, icon, menu, PLUGIN_MENU, CUSTOM_TAB, tab_name)
        self.iface.addActionMenu(
            self.tr("Altair EO"), 
            QIcon(main_icon), 
            self.menu, 
            self.iface.PLUGIN_MENU, 
            self.iface.CUSTOM_TAB,
            "EO"
        )

    def unload(self):
        """Clean up and unload the plugin"""
        # Close dock widgets
        if self._main_dock is not None:
            self._main_dock.close()
            self._main_dock = None
        
        if self._settings_dock is not None:
            self._settings_dock.close()
            self._settings_dock = None
        
        # Remove menu
        if self.menu:
            self.iface.removeActionMenu(self.menu, self.iface.PLUGIN_MENU, self.iface.CUSTOM_TAB, "EO")
            self.menu = None
        
        # Clear actions
        for action in self.actions:
            if action:
                action.triggered.disconnect()
        self.actions.clear()

    def toggle_main_dock(self):
        """Toggle main EO data dock"""
        if self._main_dock is None:
            try:
                from .gui.dock import AltairDockWidget
                
                self._main_dock = AltairDockWidget(self.iface, self.iface.mainWindow())
                self._main_dock.setObjectName("AltairEODataDock")
                self._main_dock.visibilityChanged.connect(self._on_main_visibility_changed)
                
                # Connect settings_saved signal if settings dock already exists
                if self._settings_dock:
                    self._settings_dock.settings_saved.connect(self._main_dock.refresh_collections)
                    logger.debug("Connected settings_saved signal to main dock refresh_collections")
                
                # Add as dock widget to main window - kadas-vantor pattern
                self.iface.mainWindow().addDockWidget(Qt.RightDockWidgetArea, self._main_dock)
                self._main_dock.show()
                self._main_dock.raise_()
                return

            except Exception as e:
                QMessageBox.critical(
                    self.iface.mainWindow(), 
                    "Error", 
                    f"Failed to create Altair EO Data panel:\n{str(e)}"
                )
                self.main_action.setChecked(False)
                return

        # Toggle visibility
        if self._main_dock.isVisible():
            self._main_dock.hide()
        else:
            self._main_dock.show()
            self._main_dock.raise_()

    def _on_main_visibility_changed(self, visible):
        """Sync action checked state with dock visibility"""
        self.main_action.setChecked(visible)

    def toggle_settings_dock(self):
        """Toggle settings dock"""
        if self._settings_dock is None:
            try:
                from .gui.settings_dock import SettingsDockWidget
                
                self._settings_dock = SettingsDockWidget(self.iface, self.iface.mainWindow())
                self._settings_dock.setObjectName("AltairSettingsDock")
                self._settings_dock.visibilityChanged.connect(self._on_settings_visibility_changed)
                
                # Connect settings_saved signal to refresh collections in main dock
                if self._main_dock:
                    self._settings_dock.settings_saved.connect(self._main_dock.refresh_collections)
                    logger.debug("Connected settings_saved signal to main dock refresh_collections")
                
                # Add as dock widget to main window - kadas-vantor pattern
                self.iface.mainWindow().addDockWidget(Qt.RightDockWidgetArea, self._settings_dock)
                
                # Tabify with main dock if it exists (dock widgets will overlap in tabs)
                if self._main_dock:
                    self.iface.mainWindow().tabifyDockWidget(self._main_dock, self._settings_dock)
                    logger.debug("Tabified settings dock with main dock")
                
                self._settings_dock.show()
                self._settings_dock.raise_()
                return

            except Exception as e:
                QMessageBox.critical(
                    self.iface.mainWindow(),
                    "Error",
                    f"Failed to create Settings panel:\n{str(e)}"
                )
                self.settings_action.setChecked(False)
                return

        # Toggle visibility
        if self._settings_dock.isVisible():
            self._settings_dock.hide()
        else:
            self._settings_dock.show()
            self._settings_dock.raise_()

    def _on_settings_visibility_changed(self, visible):
        """Sync action checked state with dock visibility"""
        self.settings_action.setChecked(visible)

    def show_help(self):
        """Show online documentation in browser"""
        import webbrowser
        
        help_url = "https://github.com/mlanini/kadas-altair-plugin/blob/main/GUIDE.md"
        
        try:
            webbrowser.open(help_url)
            logger.info(f"Opened online documentation: {help_url}")
            
        except Exception as e:
            logger.error(f"Failed to open documentation URL: {e}")
            QMessageBox.information(
                self.iface.mainWindow(),
                "Altair Plugin Help",
                f"Please visit the documentation online:\n\n{help_url}\n\n"
                f"Full documentation is also available in:\n"
                f"• README.md - Overview and features\n"
                f"• GUIDE.md - Complete user guide\n"
                f"• ARCHITECTURE.md - System architecture & technical reference\n"
                f"• CONTRIBUTING.md - Development guidelines"
            )

    def show_log_viewer(self):
        """Show log viewer dialog"""
        try:
            from .gui.log_viewer import LogViewerDialog
            from .logger import get_log_file_path
            
            logger.info("Opening log viewer")
            
            log_file = get_log_file_path()
            
            if not log_file:
                QMessageBox.warning(
                    self.iface.mainWindow(),
                    "Log Viewer",
                    "Log file path not available.\n\n"
                    "The logging system may not be initialized properly."
                )
                return
            
            # Create and show dialog
            dialog = LogViewerDialog(log_file, parent=self.iface.mainWindow())
            dialog.exec_()
            
            logger.info("Log viewer closed")
            
        except Exception as e:
            logger.error(f"Failed to open log viewer: {e}", exc_info=True)
            QMessageBox.critical(
                self.iface.mainWindow(),
                "Error",
                f"Failed to open log viewer:\n{str(e)}"
            )

    def show_about(self):
        """Show About dialog with detailed plugin information"""
        try:
            import configparser
            config = configparser.ConfigParser()
            metadata_path = os.path.join(self.plugin_dir, 'metadata.txt')
            config.read(metadata_path, encoding='utf-8')
            
            name = config.get('general', 'name', fallback='KADAS Altair')
            version = config.get('general', 'version', fallback='0.1.0')
            author = config.get('general', 'author', fallback='Michael Lanini')
            email = config.get('general', 'email', fallback='michael@intelligeo.ch')
            repository = config.get('general', 'repository', fallback='https://github.com/mlanini/kadas-altair')
            description = config.get('general', 'description', fallback='Unified satellite imagery browser for KADAS')
            
            about_text = f"""
<h2 style="color: #2c5aa0;">🛰️ {name}</h2>

<p><b>Version:</b> {version}</p>
<p><b>Author:</b> {author} (<a href="mailto:{email}">{email}</a>)</p>
<p><b>Repository:</b> <a href="{repository}">{repository}</a></p>

<hr>

<h3>📋 Description</h3>
<p>{description}</p>

<h3>✨ Key Features</h3>
<ul>
    <li><b>50+ STAC Catalogs:</b> Automatic discovery via AWS Open Data</li>
    <li><b>Interactive Selection:</b> Map-based footprint selection with table sync</li>
    <li><b>COG Support:</b> Cloud-Optimized GeoTIFF loading via GDAL vsicurl</li>
    <li><b>Advanced Filters:</b> BBox, date range, cloud cover, collections</li>
    <li><b>Native Integration:</b> Inherits QGIS proxy and SSL settings</li>
    <li><b>Single Connector:</b> Unified access to Sentinel-2, Landsat, Maxar, CBERS</li>
</ul>

<h3>🗂️ Supported Datasets</h3>
<p>Sentinel-2, Landsat Collection 2, Maxar Open Data, CBERS-4, NAIP, and many more through AWS Open Data STAC catalog.</p>

<hr>

<p style="font-size: 9px; color: gray;">
KADAS Altair is open source software.<br>
Licensed under GNU GPL v2 or later.<br>
© 2026 {author}
</p>
"""
            
            msg_box = QMessageBox(self.iface.mainWindow())
            msg_box.setWindowTitle("About KADAS Altair")
            msg_box.setTextFormat(Qt.RichText)
            msg_box.setText(about_text)
            msg_box.setIcon(QMessageBox.Information)
            msg_box.setStandardButtons(QMessageBox.Ok)
            
            # Try to set icon if exists
            icon_path = os.path.join(self.plugin_dir, "icons", "icon.svg")
            if os.path.exists(icon_path):
                msg_box.setIconPixmap(QIcon(icon_path).pixmap(64, 64))
            
            msg_box.exec_()
            
        except Exception as e:
            logger.error(f"Error showing About dialog: {str(e)}", exc_info=True)
            QMessageBox.about(
                self.iface.mainWindow(),
                "About KADAS Altair",
                f"KADAS Altair EO Data Plugin\n\nVersion: 0.1.0\nAuthor: Michael Lanini\n\nError loading full metadata: {str(e)}"
            )
