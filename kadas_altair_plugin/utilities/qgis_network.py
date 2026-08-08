"""QGIS network helper utilities.

Provides a small adapter to execute JSON HTTP requests through
QgsNetworkAccessManager/QgsBlockingNetworkRequest so connector traffic can
follow KADAS proxy/cache/auth behavior.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlencode

from ..logger import get_logger

logger = get_logger('utilities.qgis_network')

try:
    from qgis.core import QgsBlockingNetworkRequest, QgsNetworkAccessManager
    from qgis.PyQt.QtCore import QUrl
    from qgis.PyQt.QtNetwork import QNetworkRequest

    QGIS_NETWORK_AVAILABLE = True
except Exception:
    QGIS_NETWORK_AVAILABLE = False


def qgis_request_json(
    method: str,
    url: str,
    headers: Optional[Dict[str, str]] = None,
    payload: Optional[Dict[str, Any]] = None,
    params: Optional[Dict[str, Any]] = None,
    timeout: float = 30.0,
) -> Tuple[Optional[Dict[str, Any]], Optional[str], Optional[int]]:
    """Execute an HTTP JSON request with QGIS network APIs.

    Returns:
        (data, error_message, http_status)
    """
    if not QGIS_NETWORK_AVAILABLE:
        return None, 'QGIS network APIs unavailable', None

    method_upper = str(method or 'GET').strip().upper()
    if method_upper not in ('GET', 'POST'):
        return None, f'Unsupported QGIS method: {method_upper}', None

    try:
        QgsNetworkAccessManager.instance().setupDefaultProxyAndCache()
    except Exception:
        # Continue; request may still work if NAM is already configured.
        pass

    full_url = str(url or '').strip()
    if not full_url:
        return None, 'Empty URL', None

    if params:
        query = urlencode(params, doseq=True)
        sep = '&' if '?' in full_url else '?'
        full_url = f'{full_url}{sep}{query}'

    try:
        request = QNetworkRequest(QUrl(full_url))
        for key, value in (headers or {}).items():
            if value is None:
                continue
            request.setRawHeader(
                str(key).encode('utf-8'),
                str(value).encode('utf-8'),
            )

        body = b''
        if payload is not None:
            has_content_type = any(
                (k or '').lower() == 'content-type'
                for k in (headers or {})
            )
            content_type = ''
            for k, v in (headers or {}).items():
                if (k or '').lower() == 'content-type':
                    content_type = str(v or '').lower()
                    break

            if 'application/x-www-form-urlencoded' in content_type:
                body = urlencode(payload, doseq=True).encode('utf-8')
            else:
                body = json.dumps(payload).encode('utf-8')

            if not has_content_type:
                request.setRawHeader(b'Content-Type', b'application/json')

        blocking_request = QgsBlockingNetworkRequest()
        if method_upper == 'GET':
            error = blocking_request.get(request, forceRefresh=True)
        else:
            error = blocking_request.post(request, body, forceRefresh=True)

        if error != QgsBlockingNetworkRequest.NoError:
            return None, blocking_request.errorMessage(), None

        reply = blocking_request.reply()
        status_raw = reply.attribute(QNetworkRequest.HttpStatusCodeAttribute)
        status = int(status_raw) if status_raw is not None else None

        content = reply.content().data().decode('utf-8', errors='replace')
        if status is not None and status >= 400:
            return None, f'HTTP {status}: {content[:300]}', status

        if not content.strip():
            return {}, None, status

        data = json.loads(content)
        if isinstance(data, dict):
            return data, None, status

        return {'items': data}, None, status

    except Exception as exc:
        logger.debug(f'QGIS request failed for {full_url}: {exc}')
        return None, str(exc), None
