"""HTTP client for sending requests to external services."""

import json
import os
import uuid
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from graphops_interface.constants import DEFAULT_GRAPHOPS_API_BASE_URL


class ExternalAPIClient:
    """Lightweight HTTP client for making requests to external services."""

    def __init__(self, timeout: float = 30.0):
        self.base_url = os.environ.get(
            "GRAPHOPS_INTERFACE_BACKEND_URL",
            os.environ.get(
                "AGENT_INTERFACE_BACKEND_URL",
                os.environ.get(
                    "GRAPH_OPS_AGENT_BACKEND_URL",
                    os.environ.get("RUBY_AGENT_BACKEND_URL", DEFAULT_GRAPHOPS_API_BASE_URL),
                ),
            ),
        )
        self.timeout = timeout

    def _make_request(
        self,
        method: str,
        endpoint: str,
        data: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        url = f"{self.base_url}{endpoint}"
        if params:
            url = f"{url}?{urllib.parse.urlencode(params)}"
        request_data = None
        request_headers = dict(headers) if headers else {}
        if data is not None:
            request_data = json.dumps(data).encode("utf-8")
            request_headers.setdefault("Content-Type", "application/json")
        req = urllib.request.Request(url, data=request_data, headers=request_headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                body = response.read().decode("utf-8")
                return json.loads(body) if body else {}
        except urllib.error.HTTPError as e:
            err = e.read().decode("utf-8") if e.fp else ""
            raise urllib.error.HTTPError(e.url, e.code, f"{e.reason}: {err}", e.headers, e.fp)

    def get(self, endpoint: str, params: Optional[Dict[str, Any]] = None, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        return self._make_request("GET", endpoint, params=params, headers=headers)

    def post(self, endpoint: str, data: Optional[Dict[str, Any]] = None, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        return self._make_request("POST", endpoint, data=data, headers=headers)

    def put(self, endpoint: str, data: Optional[Dict[str, Any]] = None, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        return self._make_request("PUT", endpoint, data=data, headers=headers)

    def delete(self, endpoint: str) -> Dict[str, Any]:
        return self._make_request("DELETE", endpoint)

    def post_multipart(
        self,
        endpoint: str,
        fields: Optional[Dict[str, Any]] = None,
        files: Optional[List[Tuple[str, Path, str]]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """POST multipart/form-data.

        files tuples: (field_name, file_path, content_type)
        """
        url = f"{self.base_url}{endpoint}"
        boundary = f"----graphops{uuid.uuid4().hex}"
        body = self._encode_multipart(fields or {}, files or [], boundary)
        request_headers = dict(headers) if headers else {}
        request_headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
        req = urllib.request.Request(url, data=body, headers=request_headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                payload = response.read().decode("utf-8")
                return json.loads(payload) if payload else {}
        except urllib.error.HTTPError as e:
            err = e.read().decode("utf-8") if e.fp else ""
            raise urllib.error.HTTPError(e.url, e.code, f"{e.reason}: {err}", e.headers, e.fp)

    @staticmethod
    def _encode_multipart(
        fields: Dict[str, Any],
        files: List[Tuple[str, Path, str]],
        boundary: str,
    ) -> bytes:
        chunks: List[bytes] = []
        boundary_line = f"--{boundary}\r\n".encode("utf-8")
        for key, value in fields.items():
            chunks.append(boundary_line)
            chunks.append(f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode("utf-8"))
            chunks.append(f"{value}\r\n".encode("utf-8"))
        for field_name, file_path, content_type in files:
            filename = Path(file_path).name
            chunks.append(boundary_line)
            chunks.append(
                (
                    f'Content-Disposition: form-data; name="{field_name}"; '
                    f'filename="{filename}"\r\n'
                ).encode("utf-8")
            )
            chunks.append(f"Content-Type: {content_type}\r\n\r\n".encode("utf-8"))
            chunks.append(Path(file_path).read_bytes())
            chunks.append(b"\r\n")
        chunks.append(f"--{boundary}--\r\n".encode("utf-8"))
        return b"".join(chunks)
