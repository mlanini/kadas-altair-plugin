"""Clean Altair dock implementation (fallback) used when `dock.py` is corrupted.

This module mirrors the intended functionality and is safe to import.
"""
from PyQt5 import QtWidgets, QtCore, QtGui
from ..connectors import (
    OneAtlasConnector,
    PlanetConnector,
    CopernicusConnector,
    VantorStacConnector,
)


class AltairDockWidget(QtWidgets.QDockWidget):
    def __init__(self, iface=None):
        super().__init__("Altair / Satellite Data")
        self.iface = iface
        self.setObjectName('AltairDockWidget')

        self.container = QtWidgets.QWidget()
        self.setWidget(self.container)
        self.main_layout = QtWidgets.QHBoxLayout(self.container)

        # Left: filters
        self.filters_widget = QtWidgets.QWidget()
        self.filters_layout = QtWidgets.QVBoxLayout(self.filters_widget)
        self.main_layout.addWidget(self.filters_widget, 1)

        self.service_combo = QtWidgets.QComboBox()
        self.service_combo.addItems(['OneAtlas', 'Planet', 'Copernicus', 'Maxar OpenData (Vantor STAC)'])
        self.filters_layout.addWidget(QtWidgets.QLabel('Service'))
        self.filters_layout.addWidget(self.service_combo)

        self.creds_input = QtWidgets.QLineEdit()
        self.filters_layout.addWidget(QtWidgets.QLabel('Credentials'))
        self.filters_layout.addWidget(self.creds_input)

        self.verify_checkbox = QtWidgets.QCheckBox('Verify (network)')
        self.filters_layout.addWidget(self.verify_checkbox)

        self.auth_button = QtWidgets.QPushButton('Authenticate')
        self.auth_button.clicked.connect(self.on_authenticate)
        self.search_button = QtWidgets.QPushButton('Search')
        self.search_button.clicked.connect(self.on_search)
        self.filters_layout.addWidget(self.auth_button)
        self.filters_layout.addWidget(self.search_button)

        self.collections_list = QtWidgets.QListWidget()
        self.filters_layout.addWidget(QtWidgets.QLabel('Collections'))
        self.filters_layout.addWidget(self.collections_list)

        self.results_table = QtWidgets.QTableWidget(0, 3)
        self.results_table.setHorizontalHeaderLabels(['Title', 'Date', 'Cloud%'])
        self.results_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.results_table.itemSelectionChanged.connect(self.on_result_selected)
        self.main_layout.addWidget(self.results_table, 2)

        # Preview
        self.preview_label = QtWidgets.QLabel('Preview')
        self.preview_label.setFixedSize(300, 200)
        self.preview_label.setFrameShape(QtWidgets.QFrame.Box)
        self.preview_label.setAlignment(QtCore.Qt.AlignCenter)
        self.main_layout.addWidget(self.preview_label, 1)

        self.meta_text = QtWidgets.QTextEdit()
        self.meta_text.setReadOnly(True)
        self.main_layout.addWidget(self.meta_text, 1)

        self.connectors = {
            'OneAtlas': OneAtlasConnector(),
            'Planet': PlanetConnector(),
            'Copernicus': CopernicusConnector(),
            'Maxar OpenData (Vantor STAC)': VantorStacConnector(),
        }

        self.results = []

    def current_connector(self):
        return self.connectors[self.service_combo.currentText()]

    def on_authenticate(self):
        conn = self.current_connector()
        creds = self.creds_input.text().strip()
        svc = self.service_combo.currentText()
        credentials = {}
        if svc == 'Planet':
            credentials['api_key'] = creds
        elif svc == 'Copernicus':
            if ':' in creds:
                u, p = creds.split(':', 1)
                credentials['username'] = u
                credentials['password'] = p
            else:
                credentials['token'] = creds
        elif svc.startswith('OneAtlas'):
            if ':' in creds:
                credentials['client_id'], credentials['client_secret'] = creds.split(':', 1)
            else:
                credentials['token'] = creds
        verify = self.verify_checkbox.isChecked()
        try:
            ok = conn.authenticate(credentials or None, verify=verify)
        except TypeError:
            ok = conn.authenticate(credentials or None)
        QtWidgets.QMessageBox.information(self, 'Authentication', f'Authenticated: {ok}')

        # Populate collections if connector supports it
        try:
            if hasattr(conn, 'get_collections'):
                cols = conn.get_collections() or []
                if cols:
                    self.collections_list.clear()
                    for c in cols:
                        label = c.get('title') or c.get('id')
                        item = QtWidgets.QListWidgetItem(label)
                        item.setData(QtCore.Qt.UserRole, c.get('id'))
                        self.collections_list.addItem(item)
        except Exception:
            pass

    def on_search(self):
        conn = self.current_connector()
        results = conn.search('', bbox=None, datetime=None, collections=[], limit=50)
        self.results = results or []
        self._populate_results()

    def _populate_results(self):
        self.results_table.setRowCount(0)
        for r in self.results:
            row = self.results_table.rowCount()
            self.results_table.insertRow(row)
            title = r.get('title') or r.get('id')
            date = r.get('stac_feature', {}).get('properties', {}).get('datetime', '')
            cloud = r.get('stac_feature', {}).get('properties', {}).get('eo:cloud_cover', '')
            self.results_table.setItem(row, 0, QtWidgets.QTableWidgetItem(title))
            self.results_table.setItem(row, 1, QtWidgets.QTableWidgetItem(str(date)))
            self.results_table.setItem(row, 2, QtWidgets.QTableWidgetItem(str(cloud)))

    def on_result_selected(self):
        sel = self.results_table.currentRow()
        if sel < 0 or sel >= len(self.results):
            return
        r = self.results[sel]
        assets = r.get('assets', {})
        preview_url = ''
        for key in ('preview', 'thumbnail', 'overview'):
            a = assets.get(key)
            if isinstance(a, dict) and a.get('href'):
                preview_url = a.get('href')
                break
        if preview_url:
            try:
                def _build_auth_headers(conn):
                    headers = {}
                    try:
                        if getattr(conn, 'token', None):
                            headers['Authorization'] = f'Bearer {conn.token}'
                        elif getattr(conn, 'api_key', None):
                            headers['Authorization'] = f'ApiKey {conn.api_key}'
                        elif getattr(conn, 'username', None) and getattr(conn, 'password', None):
                            import base64
                            cred = f"{conn.username}:{conn.password}"
                            b64 = base64.b64encode(cred.encode()).decode()
                            headers['Authorization'] = f'Basic {b64}'
                    except Exception:
                        pass
                    return headers

                conn = self.current_connector()
                headers = _build_auth_headers(conn)
                manager = None
                try:
                    from qgis.core import QgsNetworkAccessManager
                    manager = QgsNetworkAccessManager.instance()
                except Exception:
                    try:
                        from PyQt5.QtNetwork import QNetworkAccessManager
                        manager = QNetworkAccessManager()
                    except Exception:
                        manager = None

                if manager is None:
                    raise RuntimeError('No network manager available')

                from PyQt5.QtCore import QUrl
                from PyQt5.QtNetwork import QNetworkRequest
                from PyQt5.QtGui import QPixmap

                req = QNetworkRequest(QUrl(preview_url))
                req.setRawHeader(b'User-Agent', b'kadas-altair-plugin/1.0')
                for k, v in headers.items():
                    try:
                        req.setRawHeader(k.encode('utf-8'), v.encode('utf-8'))
                    except Exception:
                        continue

                reply = manager.get(req)

                def _on_finished():
                    try:
                        if reply.error():
                            self.preview_label.setText('No preview')
                        else:
                            data = reply.readAll()
                            pix = QPixmap()
                            pix.loadFromData(data)
                            self.preview_label.setPixmap(pix.scaled(self.preview_label.size(), QtCore.Qt.KeepAspectRatio))
                    except Exception:
                        self.preview_label.setText('No preview')
                    try:
                        reply.deleteLater()
                    except Exception:
                        pass

                try:
                    reply.finished.connect(_on_finished)
                except Exception:
                    reply.connect(reply, reply.finished, _on_finished)
            except Exception:
                try:
                    from urllib.request import urlopen
                    from PyQt5.QtGui import QPixmap
                    data = urlopen(preview_url, timeout=8).read()
                    pix = QPixmap()
                    pix.loadFromData(data)
                    self.preview_label.setPixmap(pix.scaled(self.preview_label.size(), QtCore.Qt.KeepAspectRatio))
                except Exception:
                    self.preview_label.setText('No preview')
        else:
            self.preview_label.setText('No preview')

    def on_add_layer(self):
        sel = self.results_table.currentRow()
        if sel < 0 or sel >= len(self.results):
            QtWidgets.QMessageBox.warning(self, 'Add Layer', 'No result selected')
            return
        r = self.results[sel]
        conn = self.current_connector()
        url = conn.get_tile_url(r, '{z}', '{x}', '{y}')
        try:
            from qgis.core import QgsRasterLayer, QgsProject
            layer_name = r.get('title') or r.get('id') or 'sat_layer'
            raster = None
            if '{z}' in url or '{x}' in url or '{y}' in url:
                try:
                    raster = QgsRasterLayer(url, layer_name, 'xyz')
                except Exception:
                    raster = None
                if raster is None or not raster.isValid():
                    uri = f"type=xyz&url={url}"
                    raster = QgsRasterLayer(uri, layer_name, 'wms')
            else:
                raster = QgsRasterLayer(url, layer_name)

            if not raster or not raster.isValid():
                QtWidgets.QMessageBox.warning(self, 'Add Layer', 'Failed to create layer')
                return
            QgsProject.instance().addMapLayer(raster)
            QtWidgets.QMessageBox.information(self, 'Add Layer', 'Layer added')
        except Exception:
            QtWidgets.QMessageBox.information(self, 'Add Layer (fallback)', f'URL: {url}')
            if hasattr(conn, 'get_collections'):
                cols = conn.get_collections() or []
                if cols:
                    self.collections_list.clear()
                    for c in cols:
                        label = c.get('title') or c.get('id')
                        item = QtWidgets.QListWidgetItem(label)
                        item.setData(QtCore.Qt.UserRole, c.get('id'))
                        self.collections_list.addItem(item)
            elif hasattr(conn, '_catalog') and conn._catalog:
                collections = []
                if 'collections' in conn._catalog:
                    for c in conn._catalog.get('collections', []):
                        title = c.get('title') or c.get('id')
                        collections.append(title)
                if collections:
                    self.collections_list.clear()
                    self.collections_list.addItems(collections)
        except Exception:
            pass
        super().__init__("Altair / Satellite Data")
        self.iface = iface
        self.setObjectName('AltairDockWidget')

        self.container = QtWidgets.QWidget()
        self.setWidget(self.container)
        self.main_layout = QtWidgets.QHBoxLayout(self.container)

        # Left: filters
        self.filters_widget = QtWidgets.QWidget()
        self.filters_layout = QtWidgets.QVBoxLayout(self.filters_widget)
        self.main_layout.addWidget(self.filters_widget, 1)

        self.service_combo = QtWidgets.QComboBox()
        self.service_combo.addItems(['OneAtlas', 'Planet', 'Copernicus', 'Maxar OpenData (Vantor STAC)'])
        self.filters_layout.addWidget(QtWidgets.QLabel('Service'))
        self.filters_layout.addWidget(self.service_combo)

        self.creds_input = QtWidgets.QLineEdit()
        self.filters_layout.addWidget(QtWidgets.QLabel('Credentials'))
        self.filters_layout.addWidget(self.creds_input)

        self.verify_checkbox = QtWidgets.QCheckBox('Verify (network)')
        self.filters_layout.addWidget(self.verify_checkbox)

        self.auth_button = QtWidgets.QPushButton('Authenticate')
        self.auth_button.clicked.connect(self.on_authenticate)
        self.search_button = QtWidgets.QPushButton('Search')
        self.search_button.clicked.connect(self.on_search)
        self.filters_layout.addWidget(self.auth_button)
        self.filters_layout.addWidget(self.search_button)

        self.results_table = QtWidgets.QTableWidget(0, 3)
        self.results_table.setHorizontalHeaderLabels(['Title', 'Date', 'Cloud%'])
        self.results_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.results_table.itemSelectionChanged.connect(self.on_result_selected)
        self.main_layout.addWidget(self.results_table, 2)

        # Preview
        self.preview_label = QtWidgets.QLabel('Preview')
        self.preview_label.setFixedSize(300, 200)
        self.preview_label.setFrameShape(QtWidgets.QFrame.Box)
        self.preview_label.setAlignment(QtCore.Qt.AlignCenter)
        self.main_layout.addWidget(self.preview_label, 1)

        self.meta_text = QtWidgets.QTextEdit()
        self.meta_text.setReadOnly(True)
        self.main_layout.addWidget(self.meta_text, 1)

        self.connectors = {
            'OneAtlas': OneAtlasConnector(),
            'Planet': PlanetConnector(),
            'Copernicus': CopernicusConnector(),
            'Maxar OpenData (Vantor STAC)': VantorStacConnector(),
        }

        self.results = []

    def current_connector(self):
        return self.connectors[self.service_combo.currentText()]

    def on_authenticate(self):
        conn = self.current_connector()
        creds = self.creds_input.text().strip()
        svc = self.service_combo.currentText()
        """Clean Altair dock implementation (fallback) used when `dock.py` is corrupted.

        This module mirrors the intended functionality and is safe to import.
        """
        from PyQt5 import QtWidgets, QtCore, QtGui
        from ..connectors import (
            OneAtlasConnector,
            PlanetConnector,
            CopernicusConnector,
            VantorStacConnector,
        )


        class AltairDockWidget(QtWidgets.QDockWidget):
            def __init__(self, iface=None):
                super().__init__("Altair / Satellite Data")
                self.iface = iface
                self.setObjectName('AltairDockWidget')

                self.container = QtWidgets.QWidget()
                self.setWidget(self.container)
                self.main_layout = QtWidgets.QHBoxLayout(self.container)

                # Left: filters
                self.filters_widget = QtWidgets.QWidget()
                self.filters_layout = QtWidgets.QVBoxLayout(self.filters_widget)
                self.main_layout.addWidget(self.filters_widget, 1)

                self.service_combo = QtWidgets.QComboBox()
                self.service_combo.addItems(['OneAtlas', 'Planet', 'Copernicus', 'Maxar OpenData (Vantor STAC)'])
                self.filters_layout.addWidget(QtWidgets.QLabel('Service'))
                self.filters_layout.addWidget(self.service_combo)

                self.creds_input = QtWidgets.QLineEdit()
                self.filters_layout.addWidget(QtWidgets.QLabel('Credentials'))
                self.filters_layout.addWidget(self.creds_input)

                self.verify_checkbox = QtWidgets.QCheckBox('Verify (network)')
                self.filters_layout.addWidget(self.verify_checkbox)

                self.auth_button = QtWidgets.QPushButton('Authenticate')
                self.auth_button.clicked.connect(self.on_authenticate)
                self.search_button = QtWidgets.QPushButton('Search')
                self.search_button.clicked.connect(self.on_search)
                self.filters_layout.addWidget(self.auth_button)
                self.filters_layout.addWidget(self.search_button)

                self.results_table = QtWidgets.QTableWidget(0, 3)
                self.results_table.setHorizontalHeaderLabels(['Title', 'Date', 'Cloud%'])
                self.results_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
                self.results_table.itemSelectionChanged.connect(self.on_result_selected)
                self.main_layout.addWidget(self.results_table, 2)

                # Preview
                self.preview_label = QtWidgets.QLabel('Preview')
                self.preview_label.setFixedSize(300, 200)
                self.preview_label.setFrameShape(QtWidgets.QFrame.Box)
                self.preview_label.setAlignment(QtCore.Qt.AlignCenter)
                self.main_layout.addWidget(self.preview_label, 1)

                self.meta_text = QtWidgets.QTextEdit()
                self.meta_text.setReadOnly(True)
                self.main_layout.addWidget(self.meta_text, 1)

                self.connectors = {
                    'OneAtlas': OneAtlasConnector(),
                    'Planet': PlanetConnector(),
                    'Copernicus': CopernicusConnector(),
                    'Maxar OpenData (Vantor STAC)': VantorStacConnector(),
                }

                self.collections_list = QtWidgets.QListWidget()

                self.results = []

            def current_connector(self):
                return self.connectors[self.service_combo.currentText()]

            def on_authenticate(self):
                conn = self.current_connector()
                creds = self.creds_input.text().strip()
                svc = self.service_combo.currentText()
                credentials = {}
                if svc == 'Planet':
                    credentials['api_key'] = creds
                elif svc == 'Copernicus':
                    if ':' in creds:
                        u, p = creds.split(':', 1)
                        credentials['username'] = u
                        credentials['password'] = p
                    else:
                        credentials['token'] = creds
                elif svc.startswith('OneAtlas'):
                    if ':' in creds:
                        credentials['client_id'], credentials['client_secret'] = creds.split(':', 1)
                    else:
                        credentials['token'] = creds
                verify = self.verify_checkbox.isChecked()
                try:
                    ok = conn.authenticate(credentials or None, verify=verify)
                except TypeError:
                    ok = conn.authenticate(credentials or None)
                QtWidgets.QMessageBox.information(self, 'Authentication', f'Authenticated: {ok}')

                # Populate collections if connector supports it
                try:
                    if hasattr(conn, 'get_collections'):
                        cols = conn.get_collections() or []
                        if cols:
                            self.collections_list.clear()
                            for c in cols:
                                label = c.get('title') or c.get('id')
                                item = QtWidgets.QListWidgetItem(label)
                                item.setData(QtCore.Qt.UserRole, c.get('id'))
                                self.collections_list.addItem(item)
                except Exception:
                    pass

            def on_search(self):
                conn = self.current_connector()
                dt_from = None
                dt_to = None
                results = conn.search('', bbox=None, datetime=None, collections=[], limit=50)
                self.results = results or []
                self._populate_results()

            def _populate_results(self):
                self.results_table.setRowCount(0)
                for r in self.results:
                    row = self.results_table.rowCount()
                    self.results_table.insertRow(row)
                    title = r.get('title') or r.get('id')
                    date = r.get('stac_feature', {}).get('properties', {}).get('datetime', '')
                    cloud = r.get('stac_feature', {}).get('properties', {}).get('eo:cloud_cover', '')
                    self.results_table.setItem(row, 0, QtWidgets.QTableWidgetItem(title))
                    self.results_table.setItem(row, 1, QtWidgets.QTableWidgetItem(str(date)))
                    self.results_table.setItem(row, 2, QtWidgets.QTableWidgetItem(str(cloud)))

            def on_result_selected(self):
                sel = self.results_table.currentRow()
                if sel < 0 or sel >= len(self.results):
                    return
                r = self.results[sel]
                assets = r.get('assets', {})
                preview_url = ''
                for key in ('preview', 'thumbnail', 'overview'):
                    a = assets.get(key)
                    if isinstance(a, dict) and a.get('href'):
                        preview_url = a.get('href')
                        break
                if preview_url:
                    try:
                        def _build_auth_headers(conn):
                            headers = {}
                            try:
                                if getattr(conn, 'token', None):
                                    headers['Authorization'] = f'Bearer {conn.token}'
                                elif getattr(conn, 'api_key', None):
                                    headers['Authorization'] = f'ApiKey {conn.api_key}'
                                elif getattr(conn, 'username', None) and getattr(conn, 'password', None):
                                    import base64
                                    cred = f"{conn.username}:{conn.password}"
                                    b64 = base64.b64encode(cred.encode()).decode()
                                    headers['Authorization'] = f'Basic {b64}'
                            except Exception:
                                pass
                            return headers

                        conn = self.current_connector()
                        headers = _build_auth_headers(conn)
                        manager = None
                        try:
                            from qgis.core import QgsNetworkAccessManager
                            manager = QgsNetworkAccessManager.instance()
                        except Exception:
                            try:
                                from PyQt5.QtNetwork import QNetworkAccessManager
                                manager = QNetworkAccessManager()
                            except Exception:
                                manager = None

                        if manager is None:
                            raise RuntimeError('No network manager available')

                        from PyQt5.QtCore import QUrl
                        from PyQt5.QtNetwork import QNetworkRequest
                        from PyQt5.QtGui import QPixmap

                        req = QNetworkRequest(QUrl(preview_url))
                        req.setRawHeader(b'User-Agent', b'kadas-altair-plugin/1.0')
                        for k, v in headers.items():
                            try:
                                req.setRawHeader(k.encode('utf-8'), v.encode('utf-8'))
                            except Exception:
                                continue

                        reply = manager.get(req)

                        def _on_finished():
                            try:
                                if reply.error():
                                    self.preview_label.setText('No preview')
                                else:
                                    data = reply.readAll()
                                    pix = QPixmap()
                                    pix.loadFromData(data)
                                    self.preview_label.setPixmap(pix.scaled(self.preview_label.size(), QtCore.Qt.KeepAspectRatio))
                            except Exception:
                                self.preview_label.setText('No preview')
                            try:
                                reply.deleteLater()
                            except Exception:
                                pass

                        try:
                            reply.finished.connect(_on_finished)
                        except Exception:
                            reply.connect(reply, reply.finished, _on_finished)
                    except Exception:
                        try:
                            from urllib.request import urlopen
                            from PyQt5.QtGui import QPixmap
                            data = urlopen(preview_url, timeout=8).read()
                            pix = QPixmap()
                            pix.loadFromData(data)
                            self.preview_label.setPixmap(pix.scaled(self.preview_label.size(), QtCore.Qt.KeepAspectRatio))
                        except Exception:
                            self.preview_label.setText('No preview')
                else:
                    self.preview_label.setText('No preview')

            def on_add_layer(self):
                sel = self.results_table.currentRow()
                if sel < 0 or sel >= len(self.results):
                    QtWidgets.QMessageBox.warning(self, 'Add Layer', 'No result selected')
                    return
                r = self.results[sel]
                conn = self.current_connector()
                url = conn.get_tile_url(r, '{z}', '{x}', '{y}')
                try:
                    from qgis.core import QgsRasterLayer, QgsProject
                    layer_name = r.get('title') or r.get('id') or 'sat_layer'
                    raster = None
                    if '{z}' in url or '{x}' in url or '{y}' in url:
                        try:
                            raster = QgsRasterLayer(url, layer_name, 'xyz')
                        except Exception:
                            raster = None
                        if raster is None or not raster.isValid():
                            uri = f"type=xyz&url={url}"
                            raster = QgsRasterLayer(uri, layer_name, 'wms')
                    else:
                        raster = QgsRasterLayer(url, layer_name)

                    if not raster or not raster.isValid():
                        QtWidgets.QMessageBox.warning(self, 'Add Layer', 'Failed to create layer')
                        return
                    QgsProject.instance().addMapLayer(raster)
                    QtWidgets.QMessageBox.information(self, 'Add Layer', 'Layer added')
                except Exception:
                    QtWidgets.QMessageBox.information(self, 'Add Layer (fallback)', f'URL: {url}')
