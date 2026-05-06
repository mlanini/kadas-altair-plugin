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
        self._tasking_dock = None
        self._archive_dock = None
        self._smart_tasking_dock = None
        
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

        # Open Data search action
        self.main_action = self.add_action(
            main_icon,
            self.tr("Open Data Search"),
            self.toggle_main_dock,
            status_tip=self.tr("Toggle Open Data Search Panel"),
            checkable=True,
            parent=self.iface.mainWindow(),
        )

        # Archive action
        self.archive_action = self.add_action(
            main_icon,
            self.tr("Archive Search"),
            self.toggle_archive_dock,
            status_tip=self.tr("Toggle Archive Search Panel"),
            checkable=True,
            parent=self.iface.mainWindow(),
        )
        
        # Tasking order action
        self.tasking_action = self.add_action(
            main_icon,
            self.tr("Tasking Order"),
            self.toggle_tasking_dock,
            status_tip=self.tr("Toggle Tasking Order Panel"),
            checkable=True,
            parent=self.iface.mainWindow(),
        )

        # Smart Tasking action
        self.smart_tasking_action = self.add_action(
            main_icon,
            self.tr("Smart Tasking"),
            self.toggle_smart_tasking_dock,
            status_tip=self.tr("Toggle Smart Tasking Panel"),
            checkable=True,
            parent=self.iface.mainWindow(),
        )
        
        # Separator
        self.menu.addSeparator()
        
        # Settings action
        self.settings_action = self.add_action(
            settings_icon,
            self.tr("Settings"),
            self.toggle_settings_dock,
            status_tip=self.tr("Toggle Settings Panel"),
            checkable=True,
            parent=self.iface.mainWindow(),
        )

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

        if self._tasking_dock is not None:
            self._tasking_dock.close()
            self._tasking_dock = None

        if self._archive_dock is not None:
            self._archive_dock.close()
            self._archive_dock = None

        if self._smart_tasking_dock is not None:
            self._smart_tasking_dock.close()
            self._smart_tasking_dock = None
        
        # Remove menu
        if self.menu:
            self.iface.removeActionMenu(self.menu, self.iface.PLUGIN_MENU, self.iface.CUSTOM_TAB, "EO")
            self.menu = None
        
        # Clear actions
        for action in self.actions:
            if action:
                action.triggered.disconnect()
        self.actions.clear()

    def _tabify_dock(self, new_dock):
        """Tabify *new_dock* with the first existing Altair dock so panels
        always appear superimposed (tabbed) rather than stacked vertically."""
        mw = self.iface.mainWindow()
        for candidate in (
            self._main_dock,
            self._settings_dock,
            self._tasking_dock,
            self._archive_dock,
            self._smart_tasking_dock,
        ):
            if candidate is not None and candidate is not new_dock:
                mw.tabifyDockWidget(candidate, new_dock)
                return

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
                self._tabify_dock(self._main_dock)
                self._main_dock.show()
                self._main_dock.raise_()
                return

            except Exception as e:
                error_msg = str(e)
                logger.error(
                    f"Failed to create Altair EO Data panel: {error_msg}",
                    exc_info=True
                )
                
                # Handle OpenSSL legacy provider error gracefully
                if "legacy provider" in error_msg.lower():
                    logger.warning(f"OpenSSL legacy provider issue detected: {error_msg}")
                    
                    # Set environment variable to bypass legacy requirement
                    import os
                    os.environ['CRYPTOGRAPHY_OPENSSL_NO_LEGACY'] = '1'
                    logger.info("Set CRYPTOGRAPHY_OPENSSL_NO_LEGACY=1, retrying dock creation...")
                    
                    # Retry creating the dock
                    try:
                        from .gui.dock import AltairDockWidget
                        
                        self._main_dock = AltairDockWidget(self.iface, self.iface.mainWindow())
                        self._main_dock.setObjectName("AltairEODataDock")
                        self._main_dock.visibilityChanged.connect(self._on_main_visibility_changed)
                        
                        if self._settings_dock:
                            self._settings_dock.settings_saved.connect(self._main_dock.refresh_collections)
                        
                        self.iface.mainWindow().addDockWidget(Qt.RightDockWidgetArea, self._main_dock)
                        self._tabify_dock(self._main_dock)
                        self._main_dock.show()
                        self._main_dock.raise_()
                        
                        logger.info("Dock created successfully after OpenSSL workaround")
                        return
                    except Exception as retry_error:
                        error_msg = f"Failed after OpenSSL workaround: {str(retry_error)}"
                        logger.error(error_msg)
                
                # Show error message for other errors or if retry failed
                QMessageBox.critical(
                    self.iface.mainWindow(), 
                    "Error", 
                    f"Failed to create Altair EO Data panel:\n{error_msg}"
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
                self._tabify_dock(self._settings_dock)
                self._settings_dock.show()
                self._settings_dock.raise_()
                return

            except Exception as e:
                error_msg = str(e)
                logger.error(
                    f"Failed to create Settings panel: {error_msg}",
                    exc_info=True
                )
                
                # Handle OpenSSL legacy provider error gracefully
                if "legacy provider" in error_msg.lower():
                    logger.warning(f"OpenSSL legacy provider issue in settings dock: {error_msg}")
                    
                    # Set environment variable to bypass legacy requirement
                    import os
                    os.environ['CRYPTOGRAPHY_OPENSSL_NO_LEGACY'] = '1'
                    logger.info("Set CRYPTOGRAPHY_OPENSSL_NO_LEGACY=1, retrying settings dock creation...")
                    
                    # Retry creating the dock
                    try:
                        from .gui.settings_dock import SettingsDockWidget
                        
                        self._settings_dock = SettingsDockWidget(self.iface, self.iface.mainWindow())
                        self._settings_dock.setObjectName("AltairSettingsDock")
                        self._settings_dock.visibilityChanged.connect(self._on_settings_visibility_changed)
                        
                        if self._main_dock:
                            self._settings_dock.settings_saved.connect(self._main_dock.refresh_collections)
                        
                        self.iface.mainWindow().addDockWidget(Qt.RightDockWidgetArea, self._settings_dock)
                        self._tabify_dock(self._settings_dock)
                        self._settings_dock.show()
                        self._settings_dock.raise_()
                        
                        logger.info("Settings dock created successfully after OpenSSL workaround")
                        return
                    except Exception as retry_error:
                        error_msg = f"Failed after OpenSSL workaround: {str(retry_error)}"
                        logger.error(error_msg)
                
                # Show error message for other errors or if retry failed
                QMessageBox.critical(
                    self.iface.mainWindow(),
                    "Error",
                    f"Failed to create Settings panel:\n{error_msg}"
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

    def toggle_tasking_dock(self):
        """Toggle tasking order dock"""
        if self._tasking_dock is None:
            try:
                from .gui.tasking_dock import TaskingDockWidget

                self._tasking_dock = TaskingDockWidget(self.iface, self.iface.mainWindow())
                self._tasking_dock.setObjectName("AltairTaskingDock")
                self._tasking_dock.visibilityChanged.connect(self._on_tasking_visibility_changed)

                self.iface.mainWindow().addDockWidget(Qt.RightDockWidgetArea, self._tasking_dock)
                self._tabify_dock(self._tasking_dock)
                self._tasking_dock.show()
                self._tasking_dock.raise_()
                return

            except Exception as e:
                error_msg = str(e)
                logger.error(
                    f"Failed to create Tasking Order panel: {error_msg}",
                    exc_info=True
                )
                QMessageBox.critical(
                    self.iface.mainWindow(),
                    "Error",
                    f"Failed to create Tasking Order panel:\n{error_msg}"
                )
                self.tasking_action.setChecked(False)
                return

        if self._tasking_dock.isVisible():
            self._tasking_dock.hide()
        else:
            self._tasking_dock.show()
            self._tasking_dock.raise_()

    def _on_tasking_visibility_changed(self, visible):
        """Sync action checked state with tasking dock visibility"""
        self.tasking_action.setChecked(visible)

    def toggle_archive_dock(self):
        """Toggle archive search dock"""
        if self._archive_dock is None:
            try:
                from .gui.archive_dock import ArchiveDockWidget

                self._archive_dock = ArchiveDockWidget(self.iface, self.iface.mainWindow())
                self._archive_dock.setObjectName("AltairArchiveDock")
                self._archive_dock.visibilityChanged.connect(self._on_archive_visibility_changed)
                self._archive_dock.order_requested.connect(self._open_tasking_from_archive)

                self.iface.mainWindow().addDockWidget(Qt.RightDockWidgetArea, self._archive_dock)
                self._tabify_dock(self._archive_dock)
                self._archive_dock.show()
                self._archive_dock.raise_()
                return

            except Exception as e:
                error_msg = str(e)
                logger.error(
                    f"Failed to create Archive Search panel: {error_msg}",
                    exc_info=True
                )
                QMessageBox.critical(
                    self.iface.mainWindow(),
                    "Error",
                    f"Failed to create Archive Search panel:\n{error_msg}"
                )
                self.archive_action.setChecked(False)
                return

        if self._archive_dock.isVisible():
            self._archive_dock.hide()
        else:
            self._archive_dock.show()
            self._archive_dock.raise_()

    def _on_archive_visibility_changed(self, visible):
        """Sync action checked state with archive dock visibility"""
        self.archive_action.setChecked(visible)

    def toggle_smart_tasking_dock(self):
        """Toggle Smart Tasking dock"""
        if self._smart_tasking_dock is None:
            try:
                from .gui.smart_tasking_dock import SmartTaskingDockWidget

                self._smart_tasking_dock = SmartTaskingDockWidget(self.iface, self.iface.mainWindow())
                self._smart_tasking_dock.setObjectName('AltairSmartTaskingDock')
                self._smart_tasking_dock.visibilityChanged.connect(self._on_smart_tasking_visibility_changed)
                self._smart_tasking_dock.order_requested.connect(self._open_tasking_from_smart_tasking)

                self.iface.mainWindow().addDockWidget(Qt.RightDockWidgetArea, self._smart_tasking_dock)
                self._tabify_dock(self._smart_tasking_dock)
                self._smart_tasking_dock.show()
                self._smart_tasking_dock.raise_()
                return

            except Exception as e:
                error_msg = str(e)
                logger.error(f'Failed to create Smart Tasking panel: {error_msg}', exc_info=True)
                QMessageBox.critical(
                    self.iface.mainWindow(), 'Error',
                    f'Failed to create Smart Tasking panel:\n{error_msg}',
                )
                self.smart_tasking_action.setChecked(False)
                return

        if self._smart_tasking_dock.isVisible():
            self._smart_tasking_dock.hide()
        else:
            self._smart_tasking_dock.show()
            self._smart_tasking_dock.raise_()

    def _on_smart_tasking_visibility_changed(self, visible):
        """Sync action checked state with Smart Tasking dock visibility"""
        self.smart_tasking_action.setChecked(visible)

    def _open_tasking_from_archive(self, item):
        """Open Tasking dock and prefill minimal provider/AOI context from archive result."""
        try:
            if self._tasking_dock is None:
                self.toggle_tasking_dock()
            if self._tasking_dock is None:
                return

            provider = item.get('_provider', '')
            if provider:
                idx = self._tasking_dock.provider_combo.findText(provider)
                if idx >= 0:
                    self._tasking_dock.provider_combo.setCurrentIndex(idx)

            bbox = item.get('bbox') or []
            if len(bbox) >= 4 and self._tasking_dock.extent_widget:
                from qgis.core import QgsRectangle, QgsCoordinateReferenceSystem
                rect = QgsRectangle(float(bbox[0]), float(bbox[1]),
                                    float(bbox[2]), float(bbox[3]))
                wgs84 = QgsCoordinateReferenceSystem('EPSG:4326')
                self._tasking_dock.extent_widget.setCurrentExtent(rect, wgs84)
                self._tasking_dock.extent_widget.setOriginalExtent(rect, wgs84)
                self._tasking_dock.extent_widget.setOutputCrs(wgs84)

            self._tasking_dock.show()
            self._tasking_dock.raise_()
        except Exception as e:
            logger.warning(f"Could not prefill Tasking dock from archive result: {e}")

    def _open_tasking_from_smart_tasking(self, data: dict):
        """Open Tasking dock and prefill from Smart Tasking payload."""
        try:
            if self._tasking_dock is None:
                self.toggle_tasking_dock()
            if self._tasking_dock is None:
                return

            self._tasking_dock.prefill_from_smart_tasking(data)
            self._tasking_dock.show()
            self._tasking_dock.raise_()
        except Exception as e:
            logger.warning(f'Could not prefill Tasking dock from Smart Tasking: {e}')

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
            repository = config.get('general', 'repository', fallback='https://github.com/mlanini/kadas-altair-plugin')
            description = config.get('general', 'description', fallback='Unified satellite imagery browser for KADAS')
            
            about_text = f"""
<h2 style="color: #2c5aa0;">{name}</h2>

<p><b>Version:</b> {version}</p>
<p><b>Author:</b> {author} (<a href="mailto:{email}">{email}</a>)</p>
<p><b>Repository:</b> <a href="{repository}">{repository}</a></p>

<hr>

<h3>📋 Description</h3>
<p>{description}</p>

<h3>Key Features</h3>
<ul>
    <li><b>50+ STAC Catalogs:</b> Automatic discovery via AWS Open Data</li>
    <li><b>Interactive Selection:</b> Map-based footprint selection with table sync</li>
    <li><b>COG Support:</b> Cloud-Optimized GeoTIFF loading via GDAL vsicurl</li>
    <li><b>Advanced Filters:</b> BBox, date range, cloud cover, collections</li>
    <li><b>Native Integration:</b> Inherits QGIS proxy and SSL settings</li>
    <li><b>Single Connector:</b> Unified access to Sentinel-2, Landsat, Vantor, CBERS</li>
</ul>

<h3>Supported Datasets</h3>
<p>Sentinel-2, Landsat Collection 2, Vantor Open Data, CBERS-4, NAIP, and many more through AWS Open Data STAC catalog.</p>

<hr>

<p style="font-size: 9px; color: gray;">
KADAS Altair is open source software.<br>
Licensed under the MIT License.<br>
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
