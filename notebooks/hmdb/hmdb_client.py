
"""
hmdb_client.py — Minimal Python client for HMDB API (header + query auth)

What's new (v2)
---------------
- Supports **Authorization header** auth (recommended for search POST)
- Keeps fallback **api-key** query param for endpoints that expect it
- Adds `search_metabolites(...)`:
    POST /hmdb/metabolites/search/
    Body fields (all optional): hmdb_id, name, inchi, inchi_key, formula, smiles, cas

Requirements
------------
pip install requests

Usage
-----
# Prefer header token:
export HMDB_TOKEN="your.token"   # sent as Authorization: <token>

# Or legacy query key:
export HMDB_API_KEY="your.api.key"

from hmdb_client import HMDBClient
client = HMDBClient(token=os.environ.get("HMDB_TOKEN"), api_key=os.environ.get("HMDB_API_KEY"))

# Single metabolite by ID (GET)
m = client.get_metabolite("HMDB0000001")

# Search (POST)
hits = client.search_metabolites(name="1-methylhistidine", inchi_key="GQZTWGAKDGORNB-UHFFFAOYSA-N")
"""
from __future__ import annotations

import os
from typing import Any, Dict, Iterable, List, Optional

import requests
from requests.adapters import HTTPAdapter
try:
    from urllib3.util.retry import Retry
except Exception:
    Retry = None  # type: ignore

DEFAULT_BASE_URL = "http://35.184.189.38/api"
HMDB_PREFIX = "/hmdb"
DEFAULT_TIMEOUT = 30  # seconds


class HMDBClient:
    def __init__(
        self,
        token: Optional[str] = None,         # Authorization header token
        api_key: Optional[str] = None,       # legacy query param ?api-key=...
        base_url: str = DEFAULT_BASE_URL,
        timeout: int = DEFAULT_TIMEOUT,
        max_retries: int = 4,
        backoff_factor: float = 0.5,
    ) -> None:
        if not token and not api_key:
            raise ValueError("Provide either token (Authorization header) or api_key (?api-key=...).")

        self.token = (token or "").strip() or None
        self.api_key = (api_key or "").strip() or None
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

        self.session = requests.Session()

        if Retry is not None:
            retry = Retry(
                total=max_retries,
                backoff_factor=backoff_factor,
                status_forcelist=(429, 500, 502, 503, 504),
                allowed_methods=frozenset(["GET", "POST", "OPTIONS"]),
                raise_on_status=False,
            )
            adapter = HTTPAdapter(max_retries=retry)
            self.session.mount("http://", adapter)
            self.session.mount("https://", adapter)

    # -----------------------------
    # Internal helpers
    # -----------------------------
    def _headers(self, extra: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        h = {"accept": "application/json"}
        if self.token:
            h["Authorization"] = self.token  # as per Swagger example
        if extra:
            h.update(extra)
        return h

    def _params(self, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        params = dict(params or {})
        if self.api_key and "api-key" not in params:
            params["api-key"] = self.api_key
        return params

    def _url(self, path: str) -> str:
        if path.startswith("http://") or path.startswith("https://"):
            return path
        return f"{self.base_url}{path}"

    # -----------------------------
    # Generic GET/POST
    # -----------------------------
    def get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        url = self._url(path)
        resp = self.session.get(url, headers=self._headers(), params=self._params(params), timeout=self.timeout)
        self._raise_for_bad_status(resp)
        return self._parse_json(resp)

    def post(self, path: str, json_body: Dict[str, Any], params: Optional[Dict[str, Any]] = None) -> Any:
        url = self._url(path)
        headers = self._headers({"Content-Type": "application/json"})
        resp = self.session.post(url, headers=headers, params=self._params(params), json=json_body, timeout=self.timeout)
        self._raise_for_bad_status(resp)
        return self._parse_json(resp)

    # -----------------------------
    # Convenience endpoints
    # -----------------------------
    def get_metabolite(self, hmdb_id: str) -> Dict[str, Any]:
        """
        GET /hmdb/metabolites/{HMDB_ID}/
        """
        path = f"{HMDB_PREFIX}/metabolites/{hmdb_id}/"
        return self.get(path)

    def get_pathways(self, hmdb_ids: Iterable[str]) -> Any:
        """
        POST /hmdb/metabolites/pathways/
        Body: {"hmdb_id": ["HMDB0000001", "HMDB0000002"]}
        """
        path = f"{HMDB_PREFIX}/metabolites/pathways/"
        body = {"hmdb_id": list(hmdb_ids)}
        return self.post(path, json_body=body)

    def search_metabolites(
        self,
        hmdb_id: Optional[str] = None,
        name: Optional[str] = None,
        inchi: Optional[str] = None,
        inchi_key: Optional[str] = None,
        formula: Optional[str] = None,
        smiles: Optional[str] = None,
        cas: Optional[str] = None,
    ) -> Any:
        """
        POST /hmdb/metabolites/search/
        Fields are optional; only provided ones are sent.
        Mirrors the Swagger curl example with Authorization header.
        """
        path = f"{HMDB_PREFIX}/metabolites/search/"
        body: Dict[str, Any] = {}
        if hmdb_id:  body["hmdb_id"] = hmdb_id
        if name:     body["name"] = name
        if inchi:    body["inchi"] = inchi
        if inchi_key:body["inchi_key"] = inchi_key
        if formula:  body["formula"] = formula
        if smiles:   body["smiles"] = smiles
        if cas:      body["cas"] = cas
        return self.post(path, json_body=body)

    # -----------------------------
    # Helpers
    # -----------------------------
    @staticmethod
    def _parse_json(resp: requests.Response) -> Any:
        try:
            return resp.json()
        except ValueError:
            return {"raw": resp.text, "status_code": resp.status_code}

    @staticmethod
    def _raise_for_bad_status(resp: requests.Response) -> None:
        if 400 <= resp.status_code:
            try:
                detail = resp.json()
            except Exception:
                detail = resp.text
            raise requests.HTTPError(f"HMDB API error {resp.status_code}: {detail}")


if __name__ == "__main__":
    # Example smoke test shape (requires network + real token or api key)
    token = os.environ.get("HMDB_TOKEN", "").strip() or None
    key   = os.environ.get("HMDB_API_KEY", "").strip() or None
    client = HMDBClient(token=token, api_key=key)
    # print("Metabolite:", client.get_metabolite("HMDB0000001"))
    # print("Search:", client.search_metabolites(name="1-methylhistidine"))
