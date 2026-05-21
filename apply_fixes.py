#!/usr/bin/env python3
"""Apply manual album_id fixes for mismatched entries."""
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


# rank -> correct album_id (or None to mark unavailable)
FIXES = {
    98: "5ECmjyU9ebLjE1PZLeNDh5",  # Faith - Subject to Change Plus First Demo
    84: None,                       # Frightwig Cat Farm Faboo not on Spotify
    70: "1zg9WoVOStqPNH0aJdrED7",  # Mekons - Fear and Whiskey
    55: "2Rv1kIWFeIYeq8kAtdhY6m",  # Operation Ivy (2007 Remaster)
    43: "4CLnHCjgBVBEoCU6e4kts1",  # Johnny Thunders L.A.M.F. Lost '77 Mixes
    38: "69b7nBXWwREudaeDgIhZXA",  # Richard Hell - Blank Generation
    35: "4pEcCqGx1RFaXWJD0mrG10",  # Misfits - Collection
    34: None,                       # Wanna Buy a Bridge - not on Spotify
    2:  "6O0hDvYYCjEoOzJdXkiaXa",  # X-Ray Spex - Germ Free Adolescents
}

data = json.load(open("/tmp/bee/album_tracks.json"))

for entry in data:
    rank = entry["rank"]
    if rank not in FIXES:
        continue
    new_id = FIXES[rank]
    if new_id is None:
        entry["tracks"] = []
        entry["unavailable"] = True
        entry["spotify_album"] = "NOT ON SPOTIFY"
        entry["album_id"] = None
        print(f"#{rank} marked unavailable")
        continue
    album = get_album(new_id)
    entry["album_id"] = new_id
    entry["spotify_album"] = album["name"]
    entry["spotify_artist"] = album["artists"][0]["name"]
    entry["tracks"] = [
        {"name": t["name"], "id": t["id"], "uri": t["uri"], "track_number": t["track_number"], "duration_ms": t["duration_ms"]}
        for t in album["tracks"]["items"]
    ]
    entry.pop("unavailable", None)
    print(f"#{rank} -> {entry['spotify_artist']} / {entry['spotify_album']} ({len(entry['tracks'])} tracks)")

with open("/tmp/bee/album_tracks.json", "w") as f:
    json.dump(data, f, indent=2)
print("saved.")
