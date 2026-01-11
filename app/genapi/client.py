from __future__ import annotations

import random
import time
from dataclasses import dataclass
from typing import Any, Mapping

import httpx


@dataclass
class GenApiResult:
    status: str
    payload: dict
    file_url: str | None = None
    text: str | None = None


class GenApiClient:
    """
    GenAPI endpoints:
      - Functions: POST {base}/functions/{id}
      - Networks:  POST {base}/networks/{id}
      - Status:    GET  {base}/request/get/{request_id}

    Key behavior:
      - If there are NO files -> send JSON body (keeps booleans as booleans, fixes 422 validation).
      - If files exist        -> send multipart/form-data (convert primitives to strings).
      - Retries on transient errors (5xx, 419) for both submit and poll.
    """

    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        timeout_submit_sec: float = 180.0,
        timeout_poll_http_sec: float = 60.0,
        max_submit_retries: int = 6,
        max_poll_retries: int = 6,
        poll_timeout_sec: int = 240,
    ):
        self.base_url = base_url.rstrip("/")
        self.headers = {"Authorization": f"Bearer {token}"}

        self.timeout_submit_sec = timeout_submit_sec
        self.timeout_poll_http_sec = timeout_poll_http_sec

        self.max_submit_retries = max_submit_retries
        self.max_poll_retries = max_poll_retries
        self.default_poll_timeout_sec = poll_timeout_sec

    def submit_function(
        self,
        function_id: str,
        implementation: str,
        files: dict[str, tuple[str, bytes, str]] | None = None,
        params: dict[str, Any] | None = None,
    ) -> int:
        url = f"{self.base_url}/functions/{function_id}"
        data = {"implementation": implementation}
        return self._submit(url=url, base_data=data, files=files or {}, params=params)

    def submit_network(
        self,
        network_id: str,
        files: dict[str, tuple[str, bytes, str]] | None = None,
        params: dict[str, Any] | None = None,
    ) -> int:
        url = f"{self.base_url}/networks/{network_id}"
        return self._submit(url=url, base_data={}, files=files or {}, params=params)

    def poll(self, request_id: int, timeout_sec: int | None = None) -> GenApiResult:
        """
        Long-polling:
          - processing -> wait and retry
          - success/failed -> return parsed best output
        """
        timeout_sec = timeout_sec or self.default_poll_timeout_sec
        url = f"{self.base_url}/request/get/{request_id}"
        deadline = time.time() + timeout_sec

        delay = 1.0

        with httpx.Client(timeout=self.timeout_poll_http_sec, trust_env=False) as client:
            while True:
                if time.time() > deadline:
                    return GenApiResult(
                        status="failed",
                        payload={},
                        file_url=None,
                        text="Timeout waiting GenAPI result",
                    )

                r = self._request_with_retry(
                    client=client,
                    method="GET",
                    url=url,
                    headers=self.headers,
                    max_retries=self.max_poll_retries,
                    base_delay=delay,
                    hard_deadline=deadline,
                )

                # non-retryable client errors
                if r.status_code >= 400:
                    raise RuntimeError(f"GenAPI HTTP {r.status_code} while polling {url}: {r.text}")

                js = r.json()
                status = js.get("status") or js.get("state") or "unknown"

                if status in ("success", "failed"):
                    file_url, text = _extract_best_output(js)
                    return GenApiResult(status=status, payload=js, file_url=file_url, text=text)

                # still processing
                time.sleep(delay)
                delay = min(delay * 1.4, 5.0)

    # --------------------------
    # Internals
    # --------------------------

    def _submit(
        self,
        url: str,
        base_data: dict[str, Any],
        files: dict[str, tuple[str, bytes, str]],
        params: dict[str, Any] | None,
    ) -> int:
        # Merge and clean payload
        payload: dict[str, Any] = dict(base_data)
        if params:
            payload.update(params)

        payload = _clean_payload(payload)

        has_files = bool(files)
        timeout = self.timeout_submit_sec

        with httpx.Client(timeout=timeout, trust_env=False) as client:
            if not has_files:
                # ✅ JSON keeps types (bool stays bool)
                r = self._request_with_retry(
                    client=client,
                    method="POST",
                    url=url,
                    headers=self.headers,
                    json=payload,
                    max_retries=self.max_submit_retries,
                )
            else:
                # multipart/form-data: values must be strings/bytes
                form = _to_form_fields(payload)
                r = self._request_with_retry(
                    client=client,
                    method="POST",
                    url=url,
                    headers=self.headers,
                    data=form,
                    files=files,
                    max_retries=self.max_submit_retries,
                )

        if r.status_code >= 400:
            raise RuntimeError(f"GenAPI HTTP {r.status_code} for {url}: {r.text}")

        js = r.json()
        request_id = js.get("request_id")
        if request_id is None:
            raise RuntimeError(f"GenAPI: no request_id in response from {url}: {js}")
        return int(request_id)

    def _request_with_retry(
        self,
        *,
        client: httpx.Client,
        method: str,
        url: str,
        headers: Mapping[str, str],
        max_retries: int,
        base_delay: float = 1.0,
        hard_deadline: float | None = None,
        **kwargs: Any,
    ) -> httpx.Response:
        """
        Retries on transient errors:
          - 5xx (500, 502, 503, 504)
          - 419 (rate limit)
          - network errors (timeouts, connection)
        Uses exponential backoff with small jitter.
        """
        delay = max(0.6, float(base_delay))
        last_exc: Exception | None = None

        for attempt in range(max_retries + 1):
            if hard_deadline is not None and time.time() > hard_deadline:
                break

            try:
                r = client.request(method, url, headers=headers, **kwargs)

                if r.status_code in (419, 500, 502, 503, 504):
                    if attempt == max_retries:
                        return r
                    sleep_for = _jitter(delay)
                    _sleep_bounded(sleep_for, hard_deadline)
                    delay = min(delay * 1.6, 10.0)
                    continue

                return r

            except (httpx.TimeoutException, httpx.NetworkError) as e:
                last_exc = e
                if attempt == max_retries:
                    break

                sleep_for = _jitter(delay)
                _sleep_bounded(sleep_for, hard_deadline)
                delay = min(delay * 1.6, 10.0)

        if last_exc is not None:
            raise RuntimeError(f"GenAPI request failed after retries: {method} {url}") from last_exc

        raise RuntimeError(f"GenAPI request aborted by deadline: {method} {url}")


def _clean_payload(d: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in d.items():
        if v is None:
            continue
        if isinstance(v, (list, tuple, set)) and len(v) == 0:
            continue
        if isinstance(v, dict) and len(v) == 0:
            continue
        out[k] = v
    return out


def _to_form_fields(payload: dict[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    for k, v in payload.items():
        if v is None:
            continue
        if isinstance(v, bool):
            out[k] = "true" if v else "false"
        elif isinstance(v, (int, float)):
            out[k] = str(v)
        else:
            out[k] = str(v)
    return out


def _jitter(x: float) -> float:
    return x * (0.85 + random.random() * 0.30)


def _sleep_bounded(seconds: float, hard_deadline: float | None) -> None:
    if hard_deadline is None:
        time.sleep(seconds)
        return
    remaining = hard_deadline - time.time()
    if remaining <= 0:
        return
    time.sleep(min(seconds, max(0.0, remaining)))


def _extract_best_output(payload: dict) -> tuple[str | None, str | None]:
    """
    Robust extractor:
      - Prefer OpenAI-like text: choices[0].message.content
      - Prefer meaningful text fields (ignore control strings like "stop")
      - Prefer best file url by extension priority if multiple are present
    """

    # 1) Prefer OpenAI-like structure (Grok / chat.completion style)
    try:
        ch = payload.get("choices")
        if isinstance(ch, list) and ch:
            m = ch[0].get("message") if isinstance(ch[0], dict) else None
            if isinstance(m, dict):
                c = m.get("content")
                if isinstance(c, str) and c.strip():
                    text = c.strip()
                    file_url = _pick_best_url(_collect_urls(payload))
                    return file_url, text
    except Exception:
        pass

    # 2) Then try common explicit fields
    for k in ("text", "output_text", "content", "message"):
        v = payload.get(k)
        if isinstance(v, str) and _is_meaningful_text(v):
            file_url = _pick_best_url(_collect_urls(payload))
            return file_url, v.strip()

    # 3) Fallback: deep search but ignore "control" strings
    text = _find_text_deep(payload)
    file_url = _pick_best_url(_collect_urls(payload))
    return file_url, text


def _collect_urls(x: Any) -> list[str]:
    urls: list[str] = []

    def rec(v: Any):
        if isinstance(v, str) and (v.startswith("http://") or v.startswith("https://")):
            urls.append(v)
            return
        if isinstance(v, dict):
            for vv in v.values():
                rec(vv)
            return
        if isinstance(v, list):
            for vv in v:
                rec(vv)
            return

    rec(x)
    # unique keep order
    seen = set()
    out = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def _pick_best_url(urls: list[str]) -> str | None:
    if not urls:
        return None

    # Prefer media/output files over input/previews.
    # Priority: audio > video > images > everything else
    prio_ext = [
        ".mp3", ".wav",
        ".mp4", ".mov", ".webm",
        ".png", ".jpg", ".jpeg", ".webp", ".gif",
        ".zip",
        ".json", ".txt",
    ]

    def score(u: str) -> tuple[int, int]:
        low = u.lower()
        # penalize input_files / uploads references if present
        penalty = 0
        if "/input_files/" in low:
            penalty += 5
        if "/uploads/" in low:
            penalty += 2
        # extension priority
        ext_rank = 999
        for i, ext in enumerate(prio_ext):
            if ext in low:
                ext_rank = i
                break
        return (ext_rank, penalty)

    return sorted(urls, key=score)[0]


def _is_meaningful_text(s: str) -> bool:
    t = (s or "").strip()
    if not t:
        return False

    # Drop common control tokens
    bad = {
        "stop",
        "assistant",
        "user",
        "chat.completion",
        "completed",
        "success",
        "failed",
        "queued",
        "processing",
    }
    if t.lower() in bad:
        return False

    # too short and looks like a flag
    if len(t) <= 4 and t.isalpha():
        return False

    return True


def _find_text_deep(x: Any) -> str | None:
    # Prefer known keys in nested dicts first
    if isinstance(x, dict):
        # direct hit keys
        for k in ("content", "text", "output_text", "message"):
            v = x.get(k)
            if isinstance(v, str) and _is_meaningful_text(v):
                return v.strip()
        # then recurse
        for v in x.values():
            t = _find_text_deep(v)
            if t:
                return t
        return None

    if isinstance(x, list):
        for v in x:
            t = _find_text_deep(v)
            if t:
                return t
        return None

    if isinstance(x, str):
        if x.startswith("http://") or x.startswith("https://"):
            return None
        return x.strip() if _is_meaningful_text(x) else None

    return None
