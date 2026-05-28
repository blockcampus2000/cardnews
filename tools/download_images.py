"""
이미지 다운로드 — Google Custom Search 우선, Pixabay fallback.

사용법:
    python tools/download_images.py "키워드" path/to/output.jpg

환경변수 (또는 .env / GitHub Secrets):
    GOOGLE_API_KEY      — Google Cloud API key
    GOOGLE_CSE_ID       — Programmable Search Engine ID
    PIXABAY_API_KEY     — Pixabay API key (fallback)

흐름:
    1. Google Custom Search 시도 (cc 라이선스 + 사진)
    2. forbidden / quota / 결과 0개 등 실패시 → Pixabay
    3. 둘 다 실패시 None
"""
import os
import sys
import json
import urllib.parse
import urllib.request
from pathlib import Path

GOOGLE_KEY = os.environ.get("GOOGLE_API_KEY", "")
GOOGLE_CX = os.environ.get("GOOGLE_CSE_ID", "")
PIXABAY_KEY = os.environ.get("PIXABAY_API_KEY", "")

UA = "Mozilla/5.0 (cardnews-bot)"


def try_google(keyword: str) -> str | None:
    if not GOOGLE_KEY or not GOOGLE_CX:
        return None
    params = {
        "key": GOOGLE_KEY,
        "cx": GOOGLE_CX,
        "q": keyword,
        "searchType": "image",
        "num": 5,
        "imgType": "photo",
        "imgSize": "huge",
        "safe": "high",
        "rights": "cc_publicdomain,cc_attribute,cc_sharealike",
    }
    url = "https://www.googleapis.com/customsearch/v1?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(url, timeout=15) as r:
            data = json.loads(r.read())
    except Exception as e:
        print(f"  [google] fetch error: {e}", file=sys.stderr)
        return None
    if "error" in data:
        print(f"  [google] api error: {data['error'].get('message','?')}", file=sys.stderr)
        return None
    items = data.get("items", [])
    if not items:
        print(f"  [google] 0 results for '{keyword}'", file=sys.stderr)
        return None
    # 가장 큰 이미지 선호
    items.sort(key=lambda x: -(x.get("image", {}).get("width", 0)))
    return items[0]["link"]


def try_pixabay(keyword: str) -> str | None:
    if not PIXABAY_KEY:
        return None
    params = {
        "key": PIXABAY_KEY,
        "q": keyword,
        "image_type": "photo",
        "orientation": "horizontal",
        "safesearch": "true",
        "per_page": 5,
        "order": "popular",
    }
    url = "https://pixabay.com/api/?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(url, timeout=15) as r:
            data = json.loads(r.read())
    except Exception as e:
        print(f"  [pixabay] fetch error: {e}", file=sys.stderr)
        return None
    hits = data.get("hits", [])
    if not hits:
        print(f"  [pixabay] 0 results for '{keyword}'", file=sys.stderr)
        return None
    # largeImageURL 우선
    return hits[0].get("largeImageURL") or hits[0].get("webformatURL")


def download(url: str, out_path: Path) -> bool:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            data = r.read()
    except Exception as e:
        print(f"  [download] error: {e}", file=sys.stderr)
        return False
    if len(data) < 5000:
        print(f"  [download] too small ({len(data)} bytes)", file=sys.stderr)
        return False
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(data)
    return True


def fetch_image(keyword: str, out_path: Path) -> str:
    """
    Returns: 'google' | 'pixabay' | 'failed'
    """
    # 1. Google 시도
    url = try_google(keyword)
    if url and download(url, out_path):
        return "google"
    # 2. Pixabay fallback
    url = try_pixabay(keyword)
    if url and download(url, out_path):
        return "pixabay"
    return "failed"


def main():
    if len(sys.argv) < 3:
        print("usage: download_images.py KEYWORD OUTPUT_PATH", file=sys.stderr)
        sys.exit(2)
    keyword = sys.argv[1]
    out = Path(sys.argv[2])
    print(f"[*] '{keyword}' → {out}")
    src = fetch_image(keyword, out)
    if src == "failed":
        print(f"  [!] ALL sources failed for '{keyword}'")
        sys.exit(1)
    print(f"  -> ok ({src}, {out.stat().st_size // 1024}KB)")


if __name__ == "__main__":
    main()
