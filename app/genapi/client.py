from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import httpx


@dataclass
class GenApiResult:
    status: str
    payload: dict
    file_url: str | None = None
    text: str | None = None


class GenApiClient:
    """
    Functions: POST {base}/functions/{id}
    Networks:  POST {base}/networks/{id}
    Status:    GET  {base}/request/get/{request_id}
    """
    def __init__(self, base_url: str, token: str):
        self.base_url = base_url.rstrip("/")
        self.headers = {"Authorization": f"Bearer {token}"}

    def submit_function(
        self,
        function_id: str,
        implementation: str,
        files: dict[str, tuple[str, bytes, str]],
        params: dict[str, Any] | None = None,
    ) -> int:
        url = f"{self.base_url}/functions/{function_id}"
        data = {"implementation": implementation}
        return self._submit(url=url, data=data, files=files, params=params)

    def submit_network(
        self,
        network_id: str,
        files: dict[str, tuple[str, bytes, str]] | None = None,
        params: dict[str, Any] | None = None,
    ) -> int:
        url = f"{self.base_url}/networks/{network_id}"
        return self._submit(url=url, data={}, files=files or {}, params=params)

    def poll(self, request_id: int, timeout_sec: int = 240) -> GenApiResult:
        url = f"{self.base_url}/request/get/{request_id}"
        deadline = time.time() + timeout_sec
        delay = 1.0

        with httpx.Client(timeout=60, trust_env=False) as client:
            while True:
                r = client.get(url, headers=self.headers)
                if r.status_code >= 400:
                    raise RuntimeError(f"GenAPI HTTP {r.status_code} while polling {url}: {r.text}")

                js = r.json()
                status = js.get("status") or js.get("state") or "unknown"

                if status in ("success", "failed"):
                    file_url, text = _extract_best_output(js)
                    return GenApiResult(status=status, payload=js, file_url=file_url, text=text)

                if time.time() > deadline:
                    return GenApiResult(status="failed", payload=js, file_url=None, text="Timeout waiting GenAPI result")

                time.sleep(delay)
                delay = min(delay * 1.4, 5.0)

    def _submit(
        self,
        url: str,
        data: dict[str, Any],
        files: dict[str, tuple[str, bytes, str]],
        params: dict[str, Any] | None,
    ) -> int:
        # GenAPI любит form-data строками
        if params:
            for k, v in params.items():
                if v is None:
                    continue

                # IMPORTANT: bool должны быть "true"/"false" (lowercase), иначе 422
                if isinstance(v, bool):
                    data[k] = "true" if v else "false"
                elif isinstance(v, (int, float)):
                    data[k] = str(v)
                else:
                    data[k] = v

        with httpx.Client(timeout=180, trust_env=False) as client:
            r = client.post(url, headers=self.headers, data=data, files=files)

        if r.status_code >= 400:
            raise RuntimeError(f"GenAPI HTTP {r.status_code} for {url}: {r.text}")

        js = r.json()
        request_id = js.get("request_id")
        if request_id is None:
            raise RuntimeError(f"GenAPI: no request_id in response from {url}: {js}")
        return int(request_id)


def _extract_best_output(payload: dict) -> tuple[str | None, str | None]:
    def find_url(x):
        if isinstance(x, str) and (x.startswith("http://") or x.startswith("https://")):
            return x
        if isinstance(x, dict):
            for k in ("url", "file", "image", "video", "audio", "mesh", "result_url"):
                u = find_url(x.get(k))
                if u:
                    return u
            for v in x.values():
                u = find_url(v)
                if u:
                    return u
        if isinstance(x, list):
            for v in x:
                u = find_url(v)
                if u:
                    return u
        return None

    def find_text(x):
        if isinstance(x, str):
            if x.startswith("http://") or x.startswith("https://"):
                return None
            return x.strip() or None
        if isinstance(x, dict):
            for k in ("text", "output_text", "message", "content"):
                v = x.get(k)
                if isinstance(v, str) and v.strip():
                    return v
            for v in x.values():
                t = find_text(v)
                if t:
                    return t
        if isinstance(x, list):
            for v in x:
                t = find_text(v)
                if t:
                    return t
        return None

    candidates = []
    for key in ("output", "result", "response", "data"):
        if key in payload:
            candidates.append(payload[key])
    candidates.append(payload)

    return find_url(candidates), find_text(candidates)
