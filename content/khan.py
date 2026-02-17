"""Khan Academy scraping utilities (display-only)."""
from dataclasses import dataclass
from datetime import timedelta
import json
import logging
import os
import re
import tempfile
from typing import Iterable, Optional
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
from django.core.cache import cache
from django.db import transaction
from django.utils import timezone

from .models import KhanLessonCache, KhanClass


logger = logging.getLogger(__name__)


KhanVideoResult = Optional[str]
KhanClassResult = list[KhanClass]


class KhanScrapeError(RuntimeError):
    pass


class KhanScrapeChallenge(KhanScrapeError):
    pass


class KhanScrapeDependencyError(KhanScrapeError):
    pass


@dataclass(frozen=True)
class KhanClassSync:
    classes: KhanClassResult
    refreshed: bool
    warning: Optional[str] = None



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


def _subjects_from_urls(urls: Iterable[str]) -> set[str]:
    subjects: set[str] = set()
    for url in urls:
        try:
            path = urlparse(url).path
        except Exception:
            continue
        parts = [part for part in path.split('/') if part]
        if parts:
            subjects.add(parts[0])
    return subjects


SCRAPE_URLS = (
    "https://www.khanacademy.org/math",
    "https://www.khanacademy.org/math/k-8-grades",
    "https://www.khanacademy.org/science",
    "https://www.khanacademy.org/humanities",
    "https://www.khanacademy.org/computing",
    "https://www.khanacademy.org/economics-finance-domain",
    "https://www.khanacademy.org/college-careers-more",
)
SCRAPE_SUBJECTS = _subjects_from_urls(SCRAPE_URLS)
SCRAPE_CACHE_KEY = "khan:classes:cached"
SCRAPE_CACHE_TTL = 60 * 60 * 6
SCRAPE_REFRESH_TTL = timedelta(hours=24)
SCRAPE_DRIVER_ENV = "KHAN_SCRAPE_DRIVER"
SCRAPE_DRIVER_AUTO = "auto"
SCRAPE_DRIVER_REQUESTS = "requests"
SCRAPE_DRIVER_PLAYWRIGHT = "playwright"
SCRAPE_DRIVER_DEFAULT = SCRAPE_DRIVER_PLAYWRIGHT
SCRAPE_REQUEST_TIMEOUT = 15
SCRAPE_PLAYWRIGHT_TIMEOUT = 30_000
SCRAPE_DUMP_DIR_ENV = "KHAN_SCRAPE_DUMP_DIR"
SCRAPE_DUMP_DEFAULT_DIRNAME = "khan-scrape-debug"
SCRAPE_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15"
)
CLIENT_CHALLENGE_MARKERS = (
    "Client Challenge",
    "_fs-ch-",
)
CLASS_KIND_ALLOWLIST = {"Course", "Topic", "Domain", "Subject"}
EXCLUDED_SLUG_SNIPPETS = (
    "/video",
    "/exercise",
    "/quiz",
    "/test",
    "/mission",
    "/practice",
)


def get_khan_classes(force_refresh: bool = False) -> KhanClassSync:
    cached = cache.get(SCRAPE_CACHE_KEY)
    if cached and not force_refresh:
        return cached

    existing = list(KhanClass.objects.filter(is_active=True).order_by('subject', 'title'))
    if existing and not force_refresh:
        latest = max(item.fetched_at for item in existing)
        if timezone.now() - latest < SCRAPE_REFRESH_TTL:
            result = KhanClassSync(classes=existing, refreshed=False)
            cache.set(SCRAPE_CACHE_KEY, result, timeout=SCRAPE_CACHE_TTL)
            return result

    try:
        fresh = sync_khan_classes()
        cache.set(SCRAPE_CACHE_KEY, fresh, timeout=SCRAPE_CACHE_TTL)
        return fresh
    except KhanScrapeError as exc:
        if existing:
            warning = str(exc)
            result = KhanClassSync(classes=existing, refreshed=False, warning=warning)
            cache.set(SCRAPE_CACHE_KEY, result, timeout=SCRAPE_CACHE_TTL)
            return result
        warning = str(exc)
        result = KhanClassSync(classes=[], refreshed=False, warning=warning)
        cache.set(SCRAPE_CACHE_KEY, result, timeout=SCRAPE_CACHE_TTL)
        return result


def sync_khan_classes() -> KhanClassSync:
    class_data = scrape_khan_classes()
    if not class_data:
        raise KhanScrapeError("No classes discovered from Khan Academy HTML.")

    slugs_seen: set[str] = set()
    classes: KhanClassResult = []

    with transaction.atomic():
        for item in class_data:
            slug = item['slug']
            slugs_seen.add(slug)
            obj, _ = KhanClass.objects.update_or_create(
                slug=slug,
                defaults={
                    'title': item['title'],
                    'subject': item.get('subject', ''),
                    'url': item['url'],
                    'raw_data': item.get('raw_data', {}),
                    'is_active': True,
                },
            )
            classes.append(obj)

        KhanClass.objects.exclude(slug__in=slugs_seen).update(is_active=False)

    return KhanClassSync(classes=classes, refreshed=True)


def scrape_khan_classes() -> list[dict]:
    driver = os.environ.get(SCRAPE_DRIVER_ENV, SCRAPE_DRIVER_DEFAULT).lower()
    if driver == SCRAPE_DRIVER_REQUESTS:
        return _scrape_with_requests()
    if driver == SCRAPE_DRIVER_PLAYWRIGHT:
        return _scrape_with_playwright()

    errors: list[str] = []
    try:
        return _scrape_with_requests()
    except KhanScrapeError as exc:
        errors.append(str(exc))

    try:
        return _scrape_with_playwright()
    except KhanScrapeError as exc:
        message = str(exc)
        if message not in errors:
            errors.append(message)

    raise KhanScrapeError("; ".join(errors) or "Failed to fetch Khan Academy classes.")


def _scrape_with_requests() -> list[dict]:
    headers = {
        'User-Agent': SCRAPE_USER_AGENT,
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    }
    errors: list[str] = []
    for url in SCRAPE_URLS:
        try:
            response = requests.get(url, headers=headers, timeout=SCRAPE_REQUEST_TIMEOUT)
            response.raise_for_status()
            html = response.text
            if any(marker in html for marker in CLIENT_CHALLENGE_MARKERS):
                logger.warning(
                    "Khan requests scrape hit client challenge page (url=%s, status=%s, html_len=%s).",
                    url,
                    response.status_code,
                    len(html),
                )
                raise KhanScrapeChallenge(
                    "Khan Academy returned a client challenge page; "
                    "HTML content is unavailable for scraping."
                )
            html_stats: dict[str, int | bool] = {}
            classes = _extract_classes_from_html(html, html_stats)
            if classes:
                return classes
            dump_html, dump_dom = _dump_scrape_artifacts(url, html, None, source='requests')
            detail = (
                "Khan requests scrape found no classes ("
                f"url={url}, final_url={response.url}, status={response.status_code}, html_len={len(html)}, "
                f"scripts={html_stats.get('script_count')}, json_blobs={html_stats.get('json_blob_count')}, "
                f"embedded_json={html_stats.get('embedded_json_count')}, has_next_data={html_stats.get('has_next_data')}, "
                f"has_app_json={html_stats.get('has_app_json')}, unit_headers={html_stats.get('unit_header_count')}, "
                f"lesson_links={html_stats.get('lesson_link_count')}, html_classes={html_stats.get('html_classes_count')}, "
                f"dump_html={dump_html}, dump_dom={dump_dom})."
            )
            logger.warning(detail)
            if detail not in errors:
                errors.append(detail)
        except (requests.RequestException, KhanScrapeError) as exc:
            message = str(exc)
            if message not in errors:
                logger.warning("Khan requests scrape error for %s: %s", url, message)
                errors.append(message)

    if errors:
        raise KhanScrapeError("; ".join(errors))
    raise KhanScrapeError("Failed to fetch Khan Academy classes.")


def _scrape_with_playwright() -> list[dict]:
    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
    except Exception as exc:
        raise KhanScrapeDependencyError(
            "Playwright is required for Khan scraping. Install with "
            "`pip install playwright` and run `python -m playwright install chromium`."
        ) from exc

    errors: list[str] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page(user_agent=SCRAPE_USER_AGENT)
            for url in SCRAPE_URLS:
                try:
                    response = page.goto(url, wait_until='networkidle', timeout=SCRAPE_PLAYWRIGHT_TIMEOUT)
                    response_status = response.status if response else None
                    response_url = response.url if response else None
                    page_url = page.url
                    dom_waited = False
                    dom_scrolled = False
                    try:
                        page.wait_for_selector(
                            'a[data-testid="unit-header"], a[data-testid="lesson-link"]',
                            timeout=5000,
                        )
                        dom_waited = True
                    except PlaywrightTimeoutError:
                        dom_scrolled = True
                        page.evaluate("() => window.scrollTo(0, document.body.scrollHeight)")
                        try:
                            page.wait_for_selector(
                                'a[data-testid="unit-header"], a[data-testid="lesson-link"]',
                                timeout=5000,
                            )
                            dom_waited = True
                        except PlaywrightTimeoutError:
                            dom_waited = False
                    try:
                        page_title = page.title()
                    except Exception as exc:
                        page_title = f"<title error: {type(exc).__name__}>"
                    data = page.evaluate(
                        "() => window.__NEXT_DATA__ || window.__INITIAL_STATE__ || window.__APOLLO_STATE__ || null"
                    )
                    data_type = type(data).__name__
                    data_keys = len(data) if isinstance(data, dict) else None
                    if isinstance(data, dict):
                        classes = _extract_classes_from_data([data])
                        if classes:
                            return classes
                    dom_links = page.evaluate(
                        """() => Array.from(
                            document.querySelectorAll('a[data-testid="unit-header"], a[data-testid="lesson-link"]')
                        ).map(link => ({
                            href: link.getAttribute('href') || '',
                            ariaLabel: link.getAttribute('aria-label') || '',
                            title: link.getAttribute('title') || '',
                            text: link.textContent || '',
                            testId: link.getAttribute('data-testid') || ''
                        }))"""
                    )
                    dom_unit_headers = sum(
                        1 for item in dom_links if item.get('testId') == 'unit-header'
                    )
                    dom_lesson_links = sum(
                        1 for item in dom_links if item.get('testId') == 'lesson-link'
                    )
                    dom_classes = _extract_classes_from_links(
                        dom_links,
                        link_kind='dom',
                    )
                    if dom_classes:
                        return dom_classes

                    html = page.content()
                    if any(marker in html for marker in CLIENT_CHALLENGE_MARKERS):
                        logger.warning(
                            "Khan Playwright scrape hit client challenge page (url=%s, page_url=%s, status=%s, title=%s, html_len=%s).",
                            url,
                            page_url,
                            response_status,
                            page_title,
                            len(html),
                        )
                        raise KhanScrapeChallenge(
                            "Khan Academy returned a client challenge page; "
                            "HTML content is unavailable for scraping."
                        )
                    html_stats: dict[str, int | bool] = {}
                    classes = _extract_classes_from_html(html, html_stats)
                    if classes:
                        return classes

                    dump_html, dump_dom = _dump_scrape_artifacts(url, html, dom_links, source='playwright')
                    detail = (
                        "Khan Playwright scrape found no classes ("
                        f"url={url}, page_url={page_url}, status={response_status}, response_url={response_url}, title={page_title}, "
                        f"data_type={data_type}, data_keys={data_keys}, html_len={len(html)}, "
                        f"scripts={html_stats.get('script_count')}, json_blobs={html_stats.get('json_blob_count')}, "
                        f"embedded_json={html_stats.get('embedded_json_count')}, has_next_data={html_stats.get('has_next_data')}, "
                        f"has_app_json={html_stats.get('has_app_json')}, unit_headers={html_stats.get('unit_header_count')}, "
                        f"lesson_links={html_stats.get('lesson_link_count')}, html_classes={html_stats.get('html_classes_count')}, "
                        f"dom_unit_headers={dom_unit_headers}, dom_lesson_links={dom_lesson_links}, "
                        f"dom_classes={len(dom_classes)}, dom_waited={dom_waited}, dom_scrolled={dom_scrolled}, "
                        f"dump_html={dump_html}, dump_dom={dump_dom})."
                    )
                    logger.warning(detail)
                    if detail not in errors:
                        errors.append(detail)
                except PlaywrightTimeoutError:
                    message = f"Playwright timed out loading {url}."
                    if message not in errors:
                        logger.warning("Khan Playwright timeout for %s.", url)
                        errors.append(message)
                except KhanScrapeError as exc:
                    message = str(exc)
                    if message not in errors:
                        logger.warning("Khan Playwright scrape error for %s: %s", url, message)
                        errors.append(message)
                except Exception as exc:
                    message = f"Playwright error for {url}: {type(exc).__name__}: {exc}"
                    if message not in errors:
                        logger.exception("Khan Playwright unexpected error for %s.", url)
                        errors.append(message)
        finally:
            browser.close()

    if errors:
        raise KhanScrapeError("; ".join(errors))
    raise KhanScrapeError("Failed to fetch Khan Academy classes with Playwright.")


def _extract_classes_from_html(html: str, stats: Optional[dict] = None) -> list[dict]:
    soup = BeautifulSoup(html, 'html.parser')
    json_blobs = []
    scripts = soup.find_all('script')
    embedded_json_count = 0
    has_next_data = False
    has_app_json = False

    for script in scripts:
        if script.get('id') == '__NEXT_DATA__' and script.string:
            has_next_data = True
            data = _safe_json_loads(script.string)
            if data:
                json_blobs.append(data)
        if script.get('type') == 'application/json' and script.string:
            has_app_json = True
            data = _safe_json_loads(script.string)
            if data:
                json_blobs.append(data)
        if script.string:
            embedded = _extract_embedded_json(script.string)
            if embedded:
                json_blobs.extend(embedded)
                embedded_json_count += len(embedded)

    classes = _extract_classes_from_data(json_blobs)
    unit_links = soup.select('a[data-testid="unit-header"]')
    lesson_links: Optional[list] = None
    if not unit_links:
        lesson_links = soup.select('a[data-testid="lesson-link"]')
    course_links = _filter_course_links(soup.select('a[href]'))
    unit_header_count = len(unit_links)
    lesson_link_count = len(lesson_links) if lesson_links is not None else None
    course_link_count = len(course_links)

    html_classes = []
    if not classes:
        if unit_links:
            html_classes = _extract_classes_from_links(unit_links, link_kind='unit-header')
        elif lesson_links:
            html_classes = _extract_classes_from_links(lesson_links, link_kind='lesson-link')
        elif course_links:
            html_classes = _extract_classes_from_links(course_links, link_kind='course-link')
    if stats is not None:
        stats.update({
            'script_count': len(scripts),
            'json_blob_count': len(json_blobs),
            'embedded_json_count': embedded_json_count,
            'has_next_data': has_next_data,
            'has_app_json': has_app_json,
            'unit_header_count': unit_header_count,
            'lesson_link_count': lesson_link_count,
            'course_link_count': course_link_count,
            'html_classes_count': len(html_classes),
            'classes_count': len(classes),
        })
    if classes:
        return classes
    if html_classes:
        return html_classes
    return []


def _extract_classes_from_links(links: Iterable, link_kind: str) -> list[dict]:
    results: dict[str, dict] = {}
    for link in links:
        href = link.get('href')
        if not isinstance(href, str) or not href:
            continue
        slug = _normalize_slug(None, href)
        url = _normalize_url(href, slug)
        title = link.get('aria-label') or link.get('ariaLabel') or link.get('title')
        if not title:
            if hasattr(link, 'get_text'):
                title = link.get_text(' ', strip=True)
            else:
                title = link.get('text') or ''
        if not slug or not title or not url:
            continue
        if not _is_class_candidate(slug, url, None):
            continue
        link_source = link.get('testId') or link_kind
        results[slug] = {
            'slug': slug,
            'title': title.strip(),
            'subject': _subject_from_slug(slug),
            'url': url,
            'raw_data': {
                'source': 'html',
                'link_kind': link_source,
                'href': href,
            },
        }
    return sorted(results.values(), key=lambda item: (item.get('subject') or '', item['title']))


def _filter_course_links(links: Iterable) -> list:
    filtered = []
    for link in links:
        href = link.get('href') if hasattr(link, 'get') else None
        if not isinstance(href, str) or not href:
            continue
        href = href.strip()
        if href.startswith('http'):
            path = urlparse(href).path
        else:
            path = href
        if not path.startswith('/'):
            continue
        parts = [part for part in path.split('/') if part]
        if len(parts) != 2:
            continue
        if parts[0] not in SCRAPE_SUBJECTS:
            continue
        filtered.append(link)
    return filtered


def _dump_scrape_artifacts(
    url: str,
    html: str,
    dom_links: Optional[list],
    source: str,
) -> tuple[Optional[str], Optional[str]]:
    dump_dir = os.environ.get(SCRAPE_DUMP_DIR_ENV)
    if not dump_dir:
        dump_dir = os.path.join(tempfile.gettempdir(), SCRAPE_DUMP_DEFAULT_DIRNAME)

    try:
        os.makedirs(dump_dir, exist_ok=True)
    except OSError as exc:
        logger.warning("Khan scrape dump failed to create dir %s: %s", dump_dir, exc)
        return None, None

    stamp = timezone.now().strftime("%Y%m%dT%H%M%S%fZ")
    safe = re.sub(r"[^a-zA-Z0-9]+", "-", url).strip("-") or "khan"
    base_name = f"{safe}-{source}-{stamp}"

    html_path = os.path.join(dump_dir, f"{base_name}.html")
    try:
        with open(html_path, "w", encoding="utf-8", errors="ignore") as handle:
            handle.write(html)
    except OSError as exc:
        logger.warning("Khan scrape dump failed to write HTML %s: %s", html_path, exc)
        html_path = None

    dom_path = None
    if dom_links is not None:
        dom_path = os.path.join(dump_dir, f"{base_name}-dom-links.json")
        try:
            with open(dom_path, "w", encoding="utf-8") as handle:
                json.dump(dom_links, handle, ensure_ascii=True, indent=2)
        except OSError as exc:
            logger.warning("Khan scrape dump failed to write DOM links %s: %s", dom_path, exc)
            dom_path = None

    if html_path or dom_path:
        logger.warning(
            "Khan scrape dump saved (url=%s, html=%s, dom_links=%s).",
            url,
            html_path,
            dom_path,
        )
    return html_path, dom_path


def _extract_embedded_json(text: str) -> list[dict]:
    patterns = (
        r"__INITIAL_STATE__\s*=\s*(\{.*?\})\s*;",
        r"__APOLLO_STATE__\s*=\s*(\{.*?\})\s*;",
        r"__KA_DATA__\s*=\s*(\{.*?\})\s*;",
        r"KA\.initialize\((\{.*\})\)\s*;",
    )
    data = []
    for pattern in patterns:
        for match in re.finditer(pattern, text, re.DOTALL):
            payload = match.group(1)
            parsed = _safe_json_loads(payload)
            if parsed:
                data.append(parsed)
    return data


def _safe_json_loads(payload: str) -> Optional[dict]:
    cleaned = payload.strip().rstrip(';')
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        cleaned = cleaned.replace('undefined', 'null')
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            return None


def _extract_classes_from_data(blobs: Iterable[dict]) -> list[dict]:
    results: dict[str, dict] = {}

    def walk(node: object) -> None:
        if isinstance(node, dict):
            slug = _normalize_slug(node.get('slug'), node.get('ka_url') or node.get('url'))
            title = _normalize_title(node)
            url = _normalize_url(node.get('ka_url') or node.get('url') or node.get('relativeUrl'), slug)
            kind = node.get('kind') or node.get('__typename') or node.get('type')
            subject = node.get('subject') or _subject_from_slug(slug)

            if slug and title and url and _is_class_candidate(slug, url, kind):
                results[slug] = {
                    'slug': slug,
                    'title': title,
                    'subject': subject,
                    'url': url,
                    'raw_data': node,
                }

            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    for blob in blobs:
        walk(blob)

    return sorted(results.values(), key=lambda item: (item.get('subject') or '', item['title']))


def _normalize_slug(slug: Optional[str], url: Optional[str]) -> str:
    candidate = slug or url or ''
    if not isinstance(candidate, str):
        return ''
    candidate = candidate.strip()
    if candidate.startswith('http'):
        candidate = candidate.split('khanacademy.org/', 1)[-1]
    candidate = candidate.strip('/')
    return candidate


def _normalize_url(url: Optional[str], slug: str) -> str:
    if isinstance(url, str) and url:
        if url.startswith('http'):
            return url
        if url.startswith('/'):
            return f"https://www.khanacademy.org{url}"
    if slug:
        return f"https://www.khanacademy.org/{slug}"
    return ''


def _normalize_title(node: dict) -> str:
    for key in ('translatedTitle', 'title', 'displayName', 'name'):
        value = node.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ''


def _subject_from_slug(slug: str) -> str:
    if not slug:
        return ''
    return slug.split('/', 1)[0]


def _is_class_candidate(slug: str, url: str, kind: Optional[str]) -> bool:
    if not slug or not url:
        return False
    if any(snippet in slug for snippet in EXCLUDED_SLUG_SNIPPETS):
        return False
    if kind and kind not in CLASS_KIND_ALLOWLIST:
        return False
    return True
