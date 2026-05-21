#!/usr/bin/env python3
"""Pull listening data and dump a taste profile to /tmp/bee/taste.json.

Collects: top artists + top tracks across short/medium/long term, saved
albums, saved tracks, followed artists, recently played. Aggregates genres.
Run after spotify_auth.py.
"""
import json
import os
from collections import Counter

import spotify_client as sc

TASTE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "taste.json")


def top(kind, time_range):
    return sc.get(f"/me/top/{kind}", {"time_range": time_range, "limit": 50}).get("items", [])


def main():
    out = {}

    # Top artists/tracks across the three Spotify windows
    for tr in ("short_term", "medium_term", "long_term"):
        out[f"top_artists_{tr}"] = [
            {"name": a["name"], "id": a["id"], "genres": a.get("genres", []),
             "popularity": a.get("popularity")}
            for a in top("artists", tr)
        ]
        out[f"top_tracks_{tr}"] = [
            {"name": t["name"], "artist": t["artists"][0]["name"], "id": t["id"],
             "album": t["album"]["name"], "popularity": t.get("popularity")}
            for t in top("tracks", tr)
        ]

    # Saved albums (what you own = what NOT to recommend)
    saved_albums = sc.get_all("/me/albums", {"limit": 50})
    out["saved_albums"] = [
        {"name": x["album"]["name"], "artist": x["album"]["artists"][0]["name"],
         "id": x["album"]["id"], "added_at": x.get("added_at")}
        for x in saved_albums
    ]

    # Saved tracks (a sample is enough to build the exclusion set)
    saved_tracks = sc.get_all("/me/tracks", {"limit": 50}, limit_pages=8)
    out["saved_tracks"] = [
        {"name": x["track"]["name"], "artist": x["track"]["artists"][0]["name"],
         "id": x["track"]["id"]}
        for x in saved_tracks
    ]

    # Followed artists
    fol = sc.get("/me/following", {"type": "artist", "limit": 50}).get("artists", {}).get("items", [])
    out["followed_artists"] = [{"name": a["name"], "id": a["id"], "genres": a.get("genres", [])} for a in fol]

    # Recently played
    rp = sc.get("/me/player/recently-played", {"limit": 50}).get("items", [])
    out["recently_played"] = [
        {"name": x["track"]["name"], "artist": x["track"]["artists"][0]["name"]}
        for x in rp
    ]

    # Genre aggregation across all artist sources, weighted toward recent
    genre_counts = Counter()
    artist_set = set()
    for tr, w in (("short_term", 3), ("medium_term", 2), ("long_term", 1)):
        for a in out[f"top_artists_{tr}"]:
            artist_set.add(a["name"])
            for g in a["genres"]:
                genre_counts[g] += w
    for a in out["followed_artists"]:
        artist_set.add(a["name"])
        for g in a["genres"]:
            genre_counts[g] += 1
    out["genre_ranking"] = genre_counts.most_common(60)
    out["distinct_artists_in_top"] = sorted(artist_set)

    with open(TASTE_PATH, "w") as f:
        json.dump(out, f, indent=2)

    # Console summary
    print("=== TOP GENRES (weighted) ===")
    for g, c in genre_counts.most_common(30):
        print(f"  {c:>3}  {g}")
    print(f"\n=== TOP ARTISTS short_term ===")
    print(", ".join(a["name"] for a in out["top_artists_short_term"][:30]))
    print(f"\n=== TOP ARTISTS long_term ===")
    print(", ".join(a["name"] for a in out["top_artists_long_term"][:30]))
    print(f"\nsaved_albums={len(out['saved_albums'])} saved_tracks={len(out['saved_tracks'])} "
          f"followed={len(out['followed_artists'])} distinct_top_artists={len(artist_set)}")
    print(f"\nWrote {TASTE_PATH}")


if __name__ == "__main__":
    main()
