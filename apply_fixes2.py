#!/usr/bin/env python3
"""Round 2 fixes: S-K, Minor Threat."""
import json
import urllib.request

TOKEN = json.load(open("/tmp/bee/token.json"))["access_token"]
HEADERS = {"Authorization": f"Bearer {TOKEN}"}


def req(url):
    r = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(r) as resp:
        return json.loads(resp.read())


def get_album(aid):
    return req(f"https://api.spotify.com/v1/albums/{aid}")


FIXES = {
    5: "3tshnNFNhHrO6NUQ0BHw42",   # Sleater-Kinney - Dig Me Out (Remastered)
    22: "6Sty6rLnMTXFjKxKUZEfmy",  # Minor Threat - First Two Seven Inches (early canon)
}

data = json.load(open("/tmp/bee/album_tracks.json"))
for entry in data:
    if entry["rank"] not in FIXES:
        continue
    new_id = FIXES[entry["rank"]]
    album = get_album(new_id)
    entry["album_id"] = new_id
    entry["spotify_album"] = album["name"]
    entry["spotify_artist"] = album["artists"][0]["name"]
    entry["tracks"] = [
        {"name": t["name"], "id": t["id"], "uri": t["uri"], "track_number": t["track_number"], "duration_ms": t["duration_ms"]}
        for t in album["tracks"]["items"]
    ]
    print(f"#{entry['rank']} -> {entry['spotify_artist']} / {entry['spotify_album']} ({len(entry['tracks'])} tracks)")

with open("/tmp/bee/album_tracks.json", "w") as f:
    json.dump(data, f, indent=2)
