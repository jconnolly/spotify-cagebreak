#!/usr/bin/env python3
"""Fetch tracks for each album in albums.txt via Spotify search + album/tracks."""
import json
import time
import urllib.parse
import urllib.request
import sys

TOKEN = json.load(open("/tmp/bee/token.json"))["access_token"]
HEADERS = {"Authorization": f"Bearer {TOKEN}"}


def req(url):
    r = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(r) as resp:
        return json.loads(resp.read())


def search_album(artist, album):
    q = f'album:"{album}" artist:"{artist}"'
    url = "https://api.spotify.com/v1/search?" + urllib.parse.urlencode(
        {"q": q, "type": "album", "limit": 10}
    )
    try:
        data = req(url)
        items = data.get("albums", {}).get("items", [])
        if not items:
            # fallback: loose query
            url2 = "https://api.spotify.com/v1/search?" + urllib.parse.urlencode(
                {"q": f"{album} {artist}", "type": "album", "limit": 10}
            )
            data = req(url2)
            items = data.get("albums", {}).get("items", [])
        return items
    except Exception as e:
        return {"_error": str(e)}


def album_tracks(album_id):
    url = f"https://api.spotify.com/v1/albums/{album_id}/tracks?limit=50"
    return req(url)


def main():
    out = []
    with open("/tmp/bee/albums.txt") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rank, artist, album = line.split("|", 2)
            print(f"[{rank}] {artist} - {album}", file=sys.stderr)
            items = search_album(artist, album)
            if isinstance(items, dict) and "_error" in items:
                out.append({"rank": int(rank), "artist": artist, "album": album, "error": items["_error"]})
                continue
            if not items:
                out.append({"rank": int(rank), "artist": artist, "album": album, "error": "no_search_result"})
                continue
            # pick first item; could refine
            picked = items[0]
            album_id = picked["id"]
            try:
                tracks_resp = album_tracks(album_id)
                tracks = [
                    {"name": t["name"], "id": t["id"], "uri": t["uri"], "track_number": t["track_number"], "duration_ms": t["duration_ms"]}
                    for t in tracks_resp.get("items", [])
                ]
            except Exception as e:
                tracks = []
                out.append({"rank": int(rank), "artist": artist, "album": album, "spotify_album": picked["name"], "spotify_artist": picked["artists"][0]["name"], "album_id": album_id, "error": f"tracks_fetch: {e}"})
                continue
            out.append(
                {
                    "rank": int(rank),
                    "artist": artist,
                    "album": album,
                    "spotify_album": picked["name"],
                    "spotify_artist": picked["artists"][0]["name"],
                    "album_id": album_id,
                    "tracks": tracks,
                    "candidates": [{"artist": i["artists"][0]["name"], "album": i["name"], "id": i["id"]} for i in items[:3]],
                }
            )
            time.sleep(0.1)  # be polite

    with open("/tmp/bee/album_tracks.json", "w") as f:
        json.dump(out, f, indent=2)
    print(f"saved {len(out)} albums", file=sys.stderr)


if __name__ == "__main__":
    main()
