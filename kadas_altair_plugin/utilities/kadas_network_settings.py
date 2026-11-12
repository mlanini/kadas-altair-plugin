"""Apply KADAS-compatible GDAL HTTP proxy settings."""

from __future__ import annotations

import os
from urllib.parse import urlsplit

from qgis.PyQt.QtCore import QSettings, QUrl
from qgis.PyQt.QtNetwork import QNetworkProxyFactory, QNetworkProxyQuery


def apply_gdal_proxy_settings(secure_storage=None) -> None:
    """Apply KADAS GDAL proxy keys to the GDAL HTTP environment."""
    settings = QSettings()
    proxy = str(settings.value('proxy/gdalHttpProxy', '') or '').strip()
    auth_method = str(settings.value('proxy/gdalProxyAuth', '') or '').strip()

    if secure_storage is None:
        try:
            from ..secrets.secure_storage import get_secure_storage
            secure_storage = get_secure_storage()
        except Exception:
            secure_storage = None

    username = ''
    password = ''
    if secure_storage:
        credentials = secure_storage.get_credentials('gdal_proxy') or {}
        username = str(credentials.get('username') or '').strip()
        password = str(credentials.get('password') or '')

    legacy_userpwd = str(
        settings.value('proxy/gdalProxyUserPwd', '') or ''
    ).strip()
    if not username and not password and legacy_userpwd:
        username, separator, password = legacy_userpwd.partition(':')
        if not separator:
            username, password = '', ''

    if not proxy:
        try:
            candidates = QNetworkProxyFactory.systemProxyForQuery(
                QNetworkProxyQuery(QUrl('https://kadas.example'))
            )
        except Exception:
            candidates = []

        for candidate in candidates:
            if not candidate.hostName():
                continue
            proxy = f'{candidate.hostName()}:{candidate.port()}'
            username = username or candidate.user()
            password = password or candidate.password()
            break

    if proxy.startswith(('http://', 'https://')):
        proxy = urlsplit(proxy).netloc or proxy

    if proxy:
        os.environ['GDAL_HTTP_PROXY'] = proxy
    else:
        os.environ.pop('GDAL_HTTP_PROXY', None)

    user_password = f'{username}:{password}' if username or password else legacy_userpwd
    if user_password:
        os.environ['GDAL_HTTP_PROXYUSERPWD'] = user_password
    else:
        os.environ.pop('GDAL_HTTP_PROXYUSERPWD', None)

    if auth_method:
        os.environ['GDAL_PROXY_AUTH'] = auth_method
    else:
        os.environ.pop('GDAL_PROXY_AUTH', None)