"""
공유 이미지(canvas)를 만들 때 커버 이미지를 읽기 위한 프록시.
브라우저는 다른 사이트의 이미지를 canvas 에 그린 뒤 PNG 로 저장할 수 없으므로(CORS), 백엔드가 대신 받아서
CORS 가 열린 응답으로 돌려준다. 아무 주소나 받아 주면 내부 서버를 건드릴 수 있어서(SSRF), 앨범 커버(Last.fm)와
아티스트 사진(Deezer) 호스트만 허용하고 리다이렉트·큰 파일·이미지가 아닌 응답은 거부한다.
"""

from urllib.parse import urlparse

import requests

ALLOWED_HOSTS = {"lastfm-img.freetls.fastly.net"}
ALLOWED_SUFFIXES = (".dzcdn.net",)
MAX_BYTES = 5 * 1024 * 1024


def is_allowed(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in ("http", "https") or not host or parsed.username or parsed.password:
        return False
    return host in ALLOWED_HOSTS or host.endswith(ALLOWED_SUFFIXES)


def fetch_image(url: str) -> tuple[bytes, str]:
    """(이미지 바이트, content-type). 허용되지 않은 주소나 이미지가 아닌 응답이면 ValueError."""
    if not is_allowed(url):
        raise ValueError("허용되지 않은 이미지 주소입니다.")
    resp = requests.get(url, timeout=10, stream=True, allow_redirects=False)
    if resp.status_code != 200:
        raise ValueError(f"이미지를 받지 못했습니다 ({resp.status_code}).")
    ctype = resp.headers.get("content-type", "").split(";")[0].strip().lower()
    if not ctype.startswith("image/") or ctype == "image/svg+xml":
        raise ValueError("이미지가 아닌 응답입니다.")
    data = b""
    for chunk in resp.iter_content(65536):
        data += chunk
        if len(data) > MAX_BYTES:
            raise ValueError("이미지가 너무 큽니다.")
    return data, ctype
