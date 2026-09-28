"""HTTP layer shared by every source.

- One pooled requests.Session per thread (connection reuse, thread-safe).
- Retries with exponential backoff + jitter on timeouts, 429 and 5xx; honours Retry-After.
- Per-host politeness: a minimum delay between requests to the same host.
- robots.txt is checked (and cached) for anything we *crawl*; official APIs are called as documented.
- Honest User-Agent that identifies the tool.
"""
import random
import socket
import threading
import time
import urllib.robotparser
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter

USER_AGENT = "JobRadar/1.0 (personal job search tool; +https://github.com/)"
BROWSER_ACCEPT = "text/html,application/xhtml+xml,application/xml;q=0.9,application/json;q=0.8,*/*;q=0.5"

_local = threading.local()
_host_lock = threading.Lock()
_host_next = {}          # host -> earliest monotonic time for next request
_robots = {}             # base -> (RobotFileParser|None, fetched_at)
_robots_lock = threading.Lock()

DEFAULT_HOST_DELAY = 0.35   # seconds between two requests to the same host
HOST_DELAYS = {             # stricter for small community-run boards
    "remoteok.com": 1.5, "www.arbeitnow.com": 1.0, "jobicy.com": 1.0, "himalayas.app": 0.8,
    "remotive.com": 1.0, "www.workingnomads.com": 1.0, "weworkremotely.com": 1.0,
    "www.keejob.com": 0.8, "www.jobberman.com": 0.8, "www.brightermonday.co.ke": 0.8,
}


class FetchError(Exception):
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


class Blocked(FetchError):
    """robots.txt disallows this URL - we respect it."""


def session():
    s = getattr(_local, "s", None)
    if s is None:
        s = requests.Session()
        adapter = HTTPAdapter(pool_connections=32, pool_maxsize=32, max_retries=0)
        s.mount("http://", adapter)
        s.mount("https://", adapter)
        s.headers.update({"User-Agent": USER_AGENT, "Accept": BROWSER_ACCEPT, "Accept-Language": "en;q=0.9,*;q=0.5"})
        _local.s = s
    return s


def _wait_turn(host):
    delay = HOST_DELAYS.get(host, DEFAULT_HOST_DELAY)
    while True:
        with _host_lock:
            now = time.monotonic()
            nxt = _host_next.get(host, 0)
            if now >= nxt:
                _host_next[host] = now + delay
                return
            wait = nxt - now
        time.sleep(min(wait, 2.0))


def robots_allowed(url):
    p = urlparse(url)
    base = "%s://%s" % (p.scheme, p.netloc)
    with _robots_lock:
        entry = _robots.get(base)
    if entry is None or time.time() - entry[1] > 6 * 3600:
        rp = urllib.robotparser.RobotFileParser()
        try:
            r = session().get(base + "/robots.txt", timeout=10)
            if r.status_code >= 400:
                rp = None                      # no robots.txt = allowed
            else:
                rp.parse(r.text.splitlines())
        except requests.RequestException:
            rp = None
        entry = (rp, time.time())
        with _robots_lock:
            _robots[base] = entry
    rp = entry[0]
    return True if rp is None else rp.can_fetch(USER_AGENT, url)


def fetch(url, *, method="GET", params=None, json_body=None, headers=None, timeout=25, retries=3,
          check_robots=False, stop=None, expect="json"):
    """Fetch with retries. expect: 'json' | 'text' | 'response'. `stop` is a threading.Event to abort."""
    if check_robots and not robots_allowed(url):
        raise Blocked("robots.txt disallows %s" % url)
    host = urlparse(url).netloc.lower()
    last = None
    attempt = 0
    while attempt <= retries:
        if stop is not None and stop.is_set():
            raise FetchError("stopped")
        _wait_turn(host)
        try:
            r = session().request(method, url, params=params, json=json_body, headers=headers, timeout=timeout)
        except requests.RequestException as e:
            last = FetchError("%s: %s" % (type(e).__name__, str(e)[:160]))
            # Our own internet is down (not just this site): wait for it to come back, then retry
            # without spending an attempt - a Wi-Fi drop must not fail the search.
            if isinstance(e, (requests.ConnectionError, requests.Timeout)) and not online():
                if wait_online(stop):
                    continue
                raise FetchError("stopped" if stop is not None and stop.is_set() else "offline for too long")
        else:
            if r.status_code == 429 or r.status_code >= 500:
                last = FetchError("HTTP %d" % r.status_code, r.status_code)
                ra = r.headers.get("Retry-After")
                if ra and ra.isdigit():
                    time.sleep(min(int(ra), 30))
            elif r.status_code >= 400:
                raise FetchError("HTTP %d" % r.status_code, r.status_code)
            else:
                if expect == "response":
                    return r
                if expect == "text":
                    r.encoding = r.encoding or r.apparent_encoding
                    return r.text
                try:
                    return r.json()
                except ValueError:
                    raise FetchError("Invalid JSON from %s" % host, r.status_code)
        if attempt < retries:
            time.sleep(min(20, (2 ** attempt) + random.uniform(0, 0.8)))
        attempt += 1
    raise last or FetchError("request failed")


# ---------------------------------------------------------------- connectivity

OFFLINE = {"since": None}          # set while JobRadar is waiting for the internet to come back
_PROBES = (("1.1.1.1", 443), ("8.8.8.8", 443), ("9.9.9.9", 443))


def online():
    """True if this computer can reach the internet (any of three public resolvers answers)."""
    for addr in _PROBES:
        try:
            socket.create_connection(addr, timeout=3).close()
            return True
        except OSError:
            continue
    return False


WAIT_EVERY = 5      # seconds between connectivity checks while offline


def wait_online(stop=None, max_wait=6 * 3600, every=None):
    """Block until the internet is back (True), or stop is set / max_wait passes (False)."""
    started = time.monotonic()
    while not online():
        if OFFLINE["since"] is None:
            OFFLINE["since"] = time.time()
        if stop is not None and stop.is_set():
            return False
        if time.monotonic() - started > max_wait:
            return False
        if stop is not None:
            stop.wait(every or WAIT_EVERY)
        else:
            time.sleep(every or WAIT_EVERY)
    OFFLINE["since"] = None
    return True
