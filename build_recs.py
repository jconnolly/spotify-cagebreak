#!/usr/bin/env python3
"""Resolve recs.md albums -> 2 signature tracks each -> one Spotify playlist per bucket.

Track pick: prefer tracks from the album that appear in the artist's top-tracks
(= signature songs); fall back to opener + a mid-album cut. Dry run prints a
match report; without --dry it creates the playlists live.

Usage:  python3 build_recs.py [--dry]
"""
import os
import re
import sys
import time
import unicodedata

import spotify_client as sc

MARKET = "US"
HERE = os.path.dirname(os.path.abspath(__file__))

BUCKET_META = {
    "punk":        ("\U0001F525 cage-break: punk / hardcore (go weird)",
                    "Algorithm cage-break — metallic/noise/screamo/sludge adjacent to your Cave In/Botch/Converge axis. Not in your library."),
    "folk":        ("\U0001F33E cage-break: instrumental folk + drone",
                    "Algorithm cage-break — Irish-trad/american-primitive/drone-classical adjacent to your Lankum/Fahey/post-rock axis."),
    "electronic":  ("\U0001F4FC cage-break: electronica / triphop / dub",
                    "Algorithm cage-break — IDM/ambient/dub-techno adjacent to your Burial/Boards/Augustus Pablo axis."),
    "indie":       ("\U0001F30A cage-break: indie (vocals)",
                    "Algorithm cage-break — shoegaze/slowcore/art-rock adjacent to your Modest Mouse/Beach House/Slint axis."),
    "hipstercore": ("⚡ cage-break: hipstercore",
                    "Algorithm cage-break — indie-sleaze/dance-punk/NYC art-punk. You own LCD + Parquet Courts; these go deeper."),
    "chiptune":    ("\U0001F47E cage-break: 8-bit / chiptune",
                    "Algorithm cage-break — chip/bitpop/breakcore/game-ambient. Anchored to your Crystal Castles + Battles."),
}
BUCKET_ORDER = ["punk", "folk", "electronic", "indie", "hipstercore", "chiptune"]


def norm(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def parse_recs(path=os.path.join(HERE, "recs.md")):
    rows = []
    for line in open(path):
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("##"):
            continue
        parts = line.split("|")
        if len(parts) < 4:
            continue
        bucket, year = parts[0], parts[-1]
        if bucket not in BUCKET_META:
            continue
        album = parts[-2]
        artist = "|".join(parts[1:-2])  # handles artist names containing '|'
        rows.append({"bucket": bucket, "artist": artist, "album": album, "year": year})
    return rows


def _artist_match(a, b):
    a, b = norm(a), norm(b)
    return a == b or a in b or b in a


def _album_match(a, b):
    a, b = norm(a), norm(b)
    return a == b or a in b or b in a


def _fetch_artist_albums(artist_id):
    # NOTE: this endpoint rejects the `limit` param for our token; page via offset only.
    out, offset = [], 0
    for _ in range(6):
        page = sc.get(f"/artists/{artist_id}/albums",
                      {"include_groups": "album,single,compilation", "market": MARKET, "offset": offset})
        items = page.get("items", [])
        out.extend(items)
        if len(items) < 20 or not page.get("next"):
            break
        offset += 20
    return out


def _best_album_for_artist(artist_id, album):
    albums = _fetch_artist_albums(artist_id)
    cands = [al for al in albums if _album_match(al["name"], album)]
    if not cands:
        return None
    cands.sort(key=lambda a: (a.get("album_type") != "album", abs(len(a["name"]) - len(album))))
    return cands[0]


def search_album(artist, album):
    # 1. strict album search, require BOTH artist and album to line up
    data = sc.get("/search", {"q": f'album:"{album}" artist:"{artist}"',
                              "type": "album", "limit": 10, "market": MARKET})
    for it in data.get("albums", {}).get("items", []):
        if _artist_match(it["artists"][0]["name"], artist) and _album_match(it["name"], album):
            return it
    # 2. artist-first: find the right artist, then fuzzy-match their catalog
    asr = sc.get("/search", {"q": artist, "type": "artist", "limit": 5, "market": MARKET})
    for ar in asr.get("artists", {}).get("items", []):
        if _artist_match(ar["name"], artist):
            al = _best_album_for_artist(ar["id"], album)
            if al:
                return al
    # 3. loose album search but still validate the artist
    data = sc.get("/search", {"q": f"{album} {artist}",
                              "type": "album", "limit": 10, "market": MARKET})
    for it in data.get("albums", {}).get("items", []):
        if _artist_match(it["artists"][0]["name"], artist):
            return it
    return None


def pick_tracks(album_id, artist_id):
    tracks = sc.get(f"/albums/{album_id}/tracks", {"limit": 50, "market": MARKET}).get("items", [])
    if not tracks:
        return []
    chosen = []
    # signature: artist top-tracks that live on this album, in popularity order
    try:
        tt = sc.get(f"/artists/{artist_id}/top-tracks", {"market": MARKET}).get("tracks", [])
        on_album = [t for t in tt if t.get("album", {}).get("id") == album_id]
        for t in on_album:
            if t["uri"] not in [c["uri"] for c in chosen]:
                chosen.append({"uri": t["uri"], "name": t["name"]})
            if len(chosen) >= 2:
                break
    except Exception:
        pass
    # fallback: opener + mid cut, skipping <60s interludes when possible
    if len(chosen) < 2:
        usable = [t for t in tracks if t.get("duration_ms", 0) >= 60000] or tracks
        cand = []
        cand.append(usable[0])
        if len(usable) > 2:
            cand.append(usable[len(usable) // 2])
        elif len(usable) > 1:
            cand.append(usable[1])
        for t in cand:
            if t["uri"] not in [c["uri"] for c in chosen]:
                chosen.append({"uri": t["uri"], "name": t["name"]})
            if len(chosen) >= 2:
                break
    return chosen[:2]


def main():
    dry = "--dry" in sys.argv
    rows = parse_recs()
    me = sc.get("/me")
    user_id = me["id"]
    print(f"user: {user_id}  albums to resolve: {len(rows)}  mode: {'DRY' if dry else 'PUSH'}\n")

    by_bucket = {b: [] for b in BUCKET_ORDER}
    misses = []
    for r in rows:
        alb = search_album(r["artist"], r["album"])
        if not alb:
            misses.append(f"NO MATCH: [{r['bucket']}] {r['artist']} — {r['album']}")
            print(f"  ✗ {r['artist']} — {r['album']}")
            continue
        got_artist = alb["artists"][0]["name"]
        flag = "" if (norm(r["artist"]) in norm(got_artist) or norm(got_artist) in norm(r["artist"])) else "  ⚠ARTIST?"
        tr = pick_tracks(alb["id"], alb["artists"][0]["id"])
        if not tr:
            misses.append(f"NO TRACKS: {r['artist']} — {alb['name']}")
            print(f"  ✗ no tracks: {r['artist']} — {alb['name']}")
            continue
        by_bucket[r["bucket"]].extend(t["uri"] for t in tr)
        print(f"  ✓ [{r['bucket']:11}] {got_artist} — {alb['name']}{flag}: " + " / ".join(t["name"] for t in tr))
        time.sleep(0.08)

    print("\n=== bucket totals ===")
    for b in BUCKET_ORDER:
        print(f"  {b:11} {len(by_bucket[b])} tracks")
    if misses:
        print("\n=== MISSES ===")
        print("\n".join("  " + m for m in misses))

    if dry:
        print("\nDRY run — no playlists created.")
        return

    print("\n=== creating playlists ===")
    created = []
    for b in BUCKET_ORDER:
        uris = by_bucket[b]
        if not uris:
            continue
        name, desc = BUCKET_META[b]
        # NOTE: /users/{id}/playlists and /playlists/{id}/tracks both 403 now
        # (deprecated). Current endpoints: /me/playlists and /playlists/{id}/items.
        pl = sc.post("/me/playlists",
                     {"name": name, "public": False, "description": desc})
        for i in range(0, len(uris), 100):
            sc.post(f"/playlists/{pl['id']}/items", {"uris": uris[i:i + 100]})
        url = pl["external_urls"]["spotify"]
        created.append((name, len(uris), url))
        print(f"  + {name}  ({len(uris)} tracks)  {url}")

    print("\nDONE")
    for name, n, url in created:
        print(f"{url}  — {name} ({n})")


if __name__ == "__main__":
    main()
