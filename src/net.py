"""HTTP session: avtomatik retry (429/5xx) + backoff."""
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


def session():
    s = requests.Session()
    retry = Retry(
        total=5,
        backoff_factor=2,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "POST"],
        raise_on_status=False,
    )
    s.mount("https://", HTTPAdapter(max_retries=retry))
    s.headers.update({"User-Agent": "shorts-pipeline/1.0 (+automation)"})
    return s
