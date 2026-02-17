"""Khan Academy scraping utilities (display-only)."""
import re
from typing import Optional

import requests
from bs4 import BeautifulSoup
from django.core.cache import cache

from .models import KhanLessonCache


KhanVideoResult = Optional[str]



def _extract_youtube_id(html: str) -> Optional[str]:
    soup = BeautifulSoup(html, 'html.parser')

    iframe = soup.find('iframe')
    if iframe and iframe.get('src'):
        src = str(iframe.get('src'))
        match = re.search(r"youtube(?:-nocookie)?\.com/embed/([\w-]+)", src)
        if match:
            return match.group(1)

    for script in soup.find_all('script'):
        if not script.string:
            continue
        match = re.search(r"\"youtubeId\"\s*:\s*\"([\w-]+)\"", script.string)
        if match:
            return match.group(1)

    return None


def _try_fetch_oembed(khan_slug: str) -> Optional[str]:
    url = "https://www.khanacademy.org/api/internal/oembed"
    target = f"https://www.khanacademy.org/{khan_slug}"
    response = requests.get(url, params={'url': target}, timeout=12)
    if response.status_code != 200:
        return None
    data = response.json()
    html = data.get('html')
    if not html:
        return None
    return _extract_youtube_id(html)


def fetch_khan_youtube_id(khan_slug: str) -> KhanVideoResult:
    cache_key = f"khan:youtube:{khan_slug}"
    cached = cache.get(cache_key)
    if cached:
        return cached

    db_cache = KhanLessonCache.objects.filter(khan_slug=khan_slug).first()
    if db_cache and db_cache.youtube_id:
        cache.set(cache_key, db_cache.youtube_id, timeout=60 * 60 * 12)
        return db_cache.youtube_id

    youtube_id = _try_fetch_oembed(khan_slug)

    if not youtube_id:
        url = f"https://www.khanacademy.org/{khan_slug}"
        response = requests.get(url, timeout=12)
        response.raise_for_status()
        youtube_id = _extract_youtube_id(response.text)

    KhanLessonCache.objects.update_or_create(
        khan_slug=khan_slug,
        defaults={'youtube_id': youtube_id or '', 'raw_data': {}},
    )
    if youtube_id:
        cache.set(cache_key, youtube_id, timeout=60 * 60 * 12)
    return youtube_id
