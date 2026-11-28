"""HTTP checks against the running stack: readiness, and the smoke assertions of scripts/smoke.sh.

Usage: python .github/ci/checks_http.py smokes <report.json>
"""
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import sys
import time
from urllib.error import URLError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bt_ci import NAMES, SERVICES, write_report  # noqa: E402

WEB = 'http://localhost:3000'


def get(url, cookie=None, timeout=5):
    headers = {'Accept-Encoding': 'identity'}
    if cookie:
        headers['Cookie'] = cookie
    with urlopen(Request(url, headers=headers), timeout=timeout) as response:
        if response.status != 200 or response.url != url:
            raise ValueError(f'{url}: status {response.status} at {response.url}')
        return response.read().decode()


def ready(seconds):
    """Wait until every service and the web server report ready with their own names."""
    wanted = {f"http://127.0.0.1:{s['port']}/health/ready": {'status': 'ready', 'service': s['name']} for s in SERVICES}
    wanted[WEB + '/api/health'] = {'status': 'ok', 'service': 'web'}
    deadline, seen = time.monotonic() + seconds, set()
    while wanted.keys() - seen and time.monotonic() < deadline:
        for url in sorted(wanted.keys() - seen):
            try:
                body = json.loads(get(url, timeout=1))
            except (URLError, ConnectionError, TimeoutError, ValueError):
                continue
            if body != wanted[url]:
                raise ValueError(f'{url}: unexpected readiness body {body}')
            seen.add(url)
        if wanted.keys() - seen:
            time.sleep(0.5)
    missing = sorted(wanted.keys() - seen)
    if missing:
        raise TimeoutError(f'not ready after {seconds}s: {missing}')


class Page(HTMLParser):
    def __init__(self):
        super().__init__()
        self.html = {}
        self.mains = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'html' and not self.html:
            self.html = attrs
        if tag == 'main' and attrs.get('id') == 'main-content':
            self.mains += 1


def smokes():
    """Return the names of the checks that passed and the problems found."""
    passed, problems = [], []

    def check(name, action):
        try:
            action()
            passed.append(name)
        except Exception as error:  # every check runs; each failure is reported
            problems.append(f'{name}: {error}')

    for service in SERVICES:
        for leaf, status in (('live', 'ok'), ('ready', 'ready')):
            url = f"http://127.0.0.1:{service['port']}/health/{leaf}"

            def health(url=url, status=status, name=service['name']):
                body = json.loads(get(url))
                if body != {'status': status, 'service': name}:
                    raise ValueError(body)
            check(f"{service['name']} {leaf}", health)
    check('web health', lambda: ready(5))
    for locale in ('en', 'ar'):
        for theme in ('light', 'dark'):
            def page(locale=locale, theme=theme):
                raw = get(f'{WEB}/{locale}', cookie=f'bt-theme={theme}', timeout=10)
                parsed = Page()
                parsed.feed(raw)
                if 'Beirut Time' not in raw or parsed.html.get('lang') != locale \
                        or parsed.html.get('data-theme') != theme or parsed.mains != 1:
                    raise ValueError(f'html {parsed.html}, main-content count {parsed.mains}')
            check(f'page {locale} {theme}', page)

    def gateway():
        info = json.loads(get(f'{WEB}/api/web/v1/status', timeout=10))
        if set(info) != {'services', 'checked_at'} \
                or not re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z', info['checked_at']) \
                or info['services'] != [{'service': s, 'status': 'ready'} for s in NAMES]:
            raise ValueError(info)
    check('web status', gateway)
    return passed, problems


if __name__ == '__main__':
    if sys.argv[1] != 'smokes':
        raise SystemExit('usage: checks_http.py smokes <report.json>')
    done, found = smokes()
    sys.exit(write_report(sys.argv[2], 'http', not found and len(done) == 24, found, passed=len(done),
                          checks=sorted(done)))
