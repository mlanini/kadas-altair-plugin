"""Capella REST/STAC API connector."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from ..logger import get_logger
from .base import ConnectorBase

logger = get_logger("connectors.capella")


class CapellaConnector(ConnectorBase):
    """Dedicated Capella API client for authenticated catalog search."""

    DEFAULT_API_BASE = "https://api.capellaspace.com"
    LANDING_PATH = "/stac"
    COLLECTIONS_PATH = "/stac/collections"
    SEARCH_PATH = "/stac/search"

    timeout_auth: float = 10.0
    timeout_search: float = 60.0

    def __init__(self) -> None:
        super().__init__()
        self._api_base_url = self.DEFAULT_API_BASE
        self._access_token: Optional[str] = None
        self._collections_path = self.COLLECTIONS_PATH
        self._search_path = self.SEARCH_PATH

    def authenticate(self, credentials: Optional[Dict[str, Any]] = None) -> bool:
        credentials = credentials or {}
        self._api_base_url = str(
            credentials.get("api_base_url") or self.DEFAULT_API_BASE
        ).strip().rstrip("/")
        self._access_token = str(credentials.get("access_token") or "").strip() or None
        self._collections_path = str(
            credentials.get("collections_path") or self.COLLECTIONS_PATH
        ).strip() or self.COLLECTIONS_PATH
        self._search_path = str(
            credentials.get("search_path") or self.SEARCH_PATH
        ).strip() or self.SEARCH_PATH

        if not self._access_token:
            logger.warning("Capella API authentication failed: missing access token")
            return False

        try:
            payload = self._get_json(self._build_url(self.LANDING_PATH), timeout=self.timeout_auth)
            ok = isinstance(payload, dict)
            if ok:
                logger.info("Capella API authentication successful")
            return ok
        except Exception as exc:
            logger.error(f"Capella API authentication failed: {exc}")
            return False

    def get_collections(self) -> List[Dict[str, Any]]:
        if not self._access_token:
            return []

        payload = self._get_json(
            self._build_url(self._collections_path), timeout=self.timeout_search
        )
        collections = payload.get("collections", []) if isinstance(payload, dict) else []
        out: List[Dict[str, Any]] = []
        if isinstance(collections, list):
            for collection in collections:
                if not isinstance(collection, dict):
                    continue
                cid = str(collection.get("id") or "").strip()
                if not cid:
                    continue
                out.append(
                    {
                        "id": cid,
                        "title": collection.get("title") or cid,
                        "description": collection.get("description") or "",
                    }
                )
        return out

    def search_unified(
        self,
        bbox: Optional[List[float]] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        max_cloud_cover: Optional[float] = None,
        collection: Optional[str] = None,
        text_query: Optional[str] = None,
        limit: int = 100,
        timeout: Optional[float] = None,
        **kwargs: Any,
    ) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        query = {
            "bbox": bbox,
            "start_date": start_date,
            "end_date": end_date,
            "max_cloud_cover": max_cloud_cover,
            "collection": collection,
            "text_query": text_query,
            "limit": limit,
            "timeout": timeout,
        }
        query.update(kwargs)
        return self.search(query)

    def search(self, query: Optional[Dict[str, Any]] = None) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        if not self._access_token:
            return [], "Missing Capella token"

        query = query or {}
        body: Dict[str, Any] = {"limit": int(query.get("limit") or 100)}
        bbox = query.get("bbox")
        if isinstance(bbox, (list, tuple)) and len(bbox) == 4:
            body["bbox"] = [float(v) for v in bbox]

        start_date = str(query.get("start_date") or "").strip()
        end_date = str(query.get("end_date") or "").strip()
        if start_date or end_date:
            body["datetime"] = f"{start_date or '..'}/{end_date or '..'}"

        collection = str(query.get("collection") or "").strip()
        if collection:
            body["collections"] = [collection]

        max_cloud_cover = query.get("max_cloud_cover")
        if max_cloud_cover is not None:
            body.setdefault("query", {})["eo:cloud_cover"] = {"lte": float(max_cloud_cover)}

        text_query = str(query.get("text_query") or "").strip()
        if text_query:
            body.setdefault("query", {})["platform"] = {"ilike": f"%{text_query}%"}

        payload = self._post_json(
            self._build_url(self._search_path),
            json_body=body,
            timeout=float(query.get("timeout") or self.timeout_search),
        )
        features = [self._normalize_feature(f) for f in self._extract_features(payload)]
        next_token = self._extract_next_token(payload)
        return [f for f in features if f], next_token

    def download(self, item: Dict[str, Any], output_path: str) -> bool:
        _ = output_path
        assets = item.get("assets") or {}
        for key in ("analytic", "image", "data", "cog", "visual"):
            href = (assets.get(key) or {}).get("href")
            if href:
                return True
        return False

    def _build_url(self, path: str) -> str:
        if path.startswith("http://") or path.startswith("https://"):
            return path
        if not path.startswith("/"):
            path = "/" + path
        return f"{self._api_base_url}{path}"

    def _headers(self) -> Dict[str, str]:
        return {
            "Accept": "application/json, application/geo+json",
            "Authorization": f"Bearer {self._access_token}",
            "User-Agent": "KADAS-Altair-Plugin/1.0",
        }

    def _get_json(self, url: str, timeout: float) -> Dict[str, Any]:
        session = self.get_session()
        response = session.get(
            url,
            headers=self._headers(),
            timeout=timeout,
            verify=self._verify_ssl,
        )
        response.raise_for_status()
        data = response.json()
        return data if isinstance(data, dict) else {}

    def _post_json(self, url: str, json_body: Dict[str, Any], timeout: float) -> Dict[str, Any]:
        session = self.get_session()
        response = session.post(
            url,
            headers=self._headers(),
            json=json_body,
            timeout=timeout,
            verify=self._verify_ssl,
        )
        response.raise_for_status()
        data = response.json()
        return data if isinstance(data, dict) else {}

    @staticmethod
    def _extract_features(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        value = payload.get("features")
        if isinstance(value, list):
            return [v for v in value if isinstance(v, dict)]
        return []

    @staticmethod
    def _extract_next_token(payload: Dict[str, Any]) -> Optional[str]:
        links = payload.get("links")
        if isinstance(links, list):
            for link in links:
                if isinstance(link, dict) and link.get("rel") == "next":
                    href = str(link.get("href") or "").strip()
                    if href:
                        return href
        token = payload.get("next") or payload.get("nextToken")
        return str(token).strip() or None

    @staticmethod
    def _normalize_feature(feature: Dict[str, Any]) -> Dict[str, Any]:
        out = dict(feature)
        if out.get("type") != "Feature":
            out["type"] = "Feature"
        out.setdefault("id", str(out.get("id") or "unknown"))
        out.setdefault("properties", {})
        out.setdefault("assets", {})
        return out


CapellaApiConnector = CapellaConnector

__all__ = ["CapellaConnector", "CapellaApiConnector"]
