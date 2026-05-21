#!/usr/bin/env python3
"""Fix mismatched album searches by trying alternative queries."""
import json
import urllib.parse
import urllib.request
import sys

TOKEN = json.load(open("/tmp/bee/token.json"))["access_token"]
HEADERS = {"Authorization": f"Bearer {TOKEN}"}


def req(url):
    r = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(r) as resp:
        return json.loads(resp.read())


def search_album_q(q):
    url = "https://api.spotify.com/v1/search?" + urllib.parse.urlencode(
        {"q": q, "type": "album", "limit": 10}
    )
    return req(url).get("albums", {}).get("items", [])


def album_tracks(aid):
    return req(f"https://api.spotify.com/v1/albums/{aid}/tracks?limit=50").get("items", [])


# ranks to refix with alternative queries
fixes = {
    98: ['artist:"Faith" album:"Subject to Change"', 'artist:"Void" album:"Faith / Void"', '"Faith Void split"'],
    84: ['artist:"Frightwig" album:"Cat Farm Faboo"', '"Frightwig"', 'artist:"Frightwig"'],
    70: ['artist:"The Mekons" album:"Fear and Whiskey"', 'artist:"Mekons" album:"Fear and Whiskey"', '"Fear and Whiskey" Mekons'],
    55: ['artist:"Operation Ivy" album:"Energy"', '"Operation Ivy" Energy'],
    43: ['artist:"Johnny Thunders" "L.A.M.F." "Lost"', 'artist:"Johnny Thunders" L.A.M.F.'],
    38: ['artist:"Richard Hell" album:"Blank Generation"', '"Voidoids" "Blank Generation"'],
    35: ['artist:"Misfits" album:"Collection"', 'artist:"Misfits" "Static Age"', 'artist:"Misfits"'],
    34: ['"Wanna Buy a Bridge"', 'compilation "Wanna Buy a Bridge"'],
    2: ['artist:"X-Ray Spex" album:"Germfree Adolescents"', '"X-Ray Spex"', 'X-Ray Spex Germfree'],
}

data = json.load(open("/tmp/bee/album_tracks.json"))
by_rank = {d["rank"]: d for d in data}

for rank, queries in fixes.items():
    entry = by_rank[rank]
    print(f"\n=== #{rank}: {entry['artist']} - {entry['album']} ===", file=sys.stderr)
    print(f"  CURRENT: {entry.get('spotify_artist','?')} / {entry.get('spotify_album','?')}", file=sys.stderr)
    for q in queries:
        try:
            items = search_album_q(q)
        except Exception as e:
            print(f"  Q={q!r}: ERROR {e}", file=sys.stderr)
            continue
        print(f"  Q={q!r}:", file=sys.stderr)
        for it in items[:5]:
            print(f"    - {it['artists'][0]['name']} / {it['name']} (id={it['id']})", file=sys.stderr)
        if not items and q == queries[0]:
            continue
        # don't auto-pick yet, let me inspect
