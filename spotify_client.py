#!/usr/bin/env python3
"""Shared Spotify helpers: token load + auto-refresh + GET/paged GET.

Reads token.json (next to this file) (must contain refresh_token + client_id, written
by spotify_auth.py). Refreshes the access token in-place when it 401s.
"""
import json
import os
import time
import urllib.parse
import urllib.request
import urllib.error

TOKEN_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "token.json")
API = "https://api.spotify.com/v1"
MAX_WAIT = 300  # seconds; longer Retry-After means a ban, not a blip


class RateLimited(RuntimeError):
    pass


def _load():
    with open(TOKEN_PATH) as f:
        return json.load(f)


def _save(tok):
    with open(TOKEN_PATH, "w") as f:
        json.dump(tok, f, indent=2)


def _refresh():
    tok = _load()
    if "client_id" not in tok or "refresh_token" not in tok:
        raise SystemExit("token.json missing client_id/refresh_token; re-run spotify_auth.py")
    body = urllib.parse.urlencode({
        "grant_type": "refresh_token",
        "refresh_token": tok["refresh_token"],
        "client_id": tok["client_id"],
    }).encode()
    req = urllib.request.Request(
        "https://accounts.spotify.com/api/token",
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        new = json.loads(resp.read())
    tok["access_token"] = new["access_token"]
    if "refresh_token" in new:
        tok["refresh_token"] = new["refresh_token"]
    _save(tok)
    return tok["access_token"]


def get(path, params=None, _retry=True):
    """GET an absolute path (starting with /) or full URL; returns parsed JSON."""
    tok = _load()
    url = path if path.startswith("http") else API + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {tok['access_token']}"})
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        if e.code == 401 and _retry:
            _refresh()
            return get(path, params, _retry=False)
        if e.code == 429:
            wait = int(e.headers.get("Retry-After", "2")) + 1
            if wait > MAX_WAIT:                    # multi-hour ban: fail fast, don't hang
                raise RateLimited(f"Spotify rate-limited {path.split('?')[0]} for {wait}s") from e
            time.sleep(wait)
            return get(path, params, _retry=_retry)
        raise


def post(path, body, _retry=True):
    """POST JSON to an absolute path (starting with /) or full URL; returns parsed JSON."""
    tok = _load()
    url = path if path.startswith("http") else API + path
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        url, data=data,
        headers={"Authorization": f"Bearer {tok['access_token']}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        if e.code == 401 and _retry:
            _refresh()
            return post(path, body, _retry=False)
        if e.code == 429:
            wait = int(e.headers.get("Retry-After", "2")) + 1
            if wait > MAX_WAIT:                    # multi-hour ban: fail fast, don't hang
                raise RateLimited(f"Spotify rate-limited {path.split('?')[0]} for {wait}s") from e
            time.sleep(wait)
            return post(path, body, _retry=_retry)
        raise


def delete(path, body, _retry=True):
    """DELETE with a JSON body to an absolute path (starting with /); returns parsed JSON."""
    tok = _load()
    url = path if path.startswith("http") else API + path
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {tok['access_token']}", "Content-Type": "application/json"},
        method="DELETE",
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as e:
        if e.code == 401 and _retry:
            _refresh()
            return delete(path, body, _retry=False)
        raise


def get_all(path, params=None, limit_pages=20):
    """Follow .next pagination, collecting .items."""
    params = dict(params or {})
    items = []
    page = get(path, params)
    for _ in range(limit_pages):
        items.extend(page.get("items", []))
        nxt = page.get("next")
        if not nxt:
            break
        page = get(nxt)
    return items
