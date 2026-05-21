#!/usr/bin/env python3
"""Build URI list from picks and add to playlist via /me/playlists/{id}/items."""
import json
import sys
import time
import urllib.request

sys.path.insert(0, "/tmp/bee")
from picks import PICKS

TOKEN = json.load(open("/tmp/bee/token.json"))["access_token"]
PLAYLIST = json.load(open("/tmp/bee/playlist.json"))["id"]
HEADERS = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}


def post(url, body):
    data = json.dumps(body).encode()
    r = urllib.request.Request(url, data=data, headers=HEADERS, method="POST")
    with urllib.request.urlopen(r) as resp:
        return json.loads(resp.read())


def build_uri_list():
    data = json.load(open("/tmp/bee/album_tracks.json"))
    by_rank = {d["rank"]: d for d in data}
    uris = []
    log = []
    # countdown 100 -> 1
    for rank in sorted(PICKS.keys(), reverse=True):
        fav_idx, slp_idx = PICKS[rank]
        entry = by_rank.get(rank)
        if not entry or entry.get("unavailable"):
            log.append(f"#{rank} SKIP (unavailable)")
            continue
        tracks = entry["tracks"]
        picked = []
        for i in fav_idx + slp_idx:
            if 1 <= i <= len(tracks):
                t = tracks[i - 1]
                uris.append(t["uri"])
                picked.append(t["name"])
            else:
                log.append(f"#{rank} bad idx {i} (album has {len(tracks)} tracks)")
        log.append(f"#{rank} {entry['spotify_artist']}/{entry['spotify_album']}: {len(picked)} picks")
    return uris, log


def main():
    uris, log = build_uri_list()
    print("\n".join(log))
    print(f"\nTotal URIs: {len(uris)}")
    with open("/tmp/bee/uri_list.json", "w") as f:
        json.dump(uris, f, indent=2)

    if "--dry" in sys.argv:
        return

    # Spotify max 100 URIs per POST
    url = f"https://api.spotify.com/v1/playlists/{PLAYLIST}/items"
    for i in range(0, len(uris), 100):
        chunk = uris[i:i + 100]
        try:
            r = post(url, {"uris": chunk})
            print(f"Added chunk {i}-{i + len(chunk) - 1}: snapshot={r.get('snapshot_id', '?')[:12]}")
        except urllib.error.HTTPError as e:
            body = e.read().decode()
            print(f"FAIL chunk {i}: {e.code} {body}")
            return
        time.sleep(0.2)
    print("DONE")


if __name__ == "__main__":
    main()
