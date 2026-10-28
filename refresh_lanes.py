#!/usr/bin/env python3
"""Weekly lane refresh: grow each themed playlist with fresh artists.

Each run:
  1. refresh Spotify taste (liked songs, top artists, recent plays)
  2. ask Claude (headless `claude -p`) for new artists per lane, seeded by
     what John has been liking lately
  3. resolve to Spotify, skipping owned / previously sent / already in the lane
  4. append PER new tracks to each lane playlist (grow-only, nothing removed)
  5. record in history.json + write digests/lanes-<date>.md

Run:    python3 refresh_lanes.py [--dry] [--per 5] [--lanes "Noise Rock,Drone"]
"""
import argparse
import datetime as dt
import json
import os
import sys
import time
from itertools import zip_longest

import spotify_client as sc
import analyze_taste
import build_recs as br
import weekly_recs as wr

HERE = os.path.dirname(os.path.abspath(__file__))
DIGEST_DIR = os.path.join(HERE, "digests")
MODEL = "sonnet"
PER = 5          # new tracks added per lane per run
ASK = 9          # artists requested per lane (buffer for owned/not-found skips)

# (playlist_id, name, brief). Names stay <=12 chars: car display truncates.
LANES = [
    ("3pZ9McS9zQOYL5k6vSXLxP", "Noise Rock",  "obscure underground noise rock, small-label / self-released"),
    ("1snK0DMiW43wpjWJl087ol", "Weird Math",  "angular odd-time weird math rock, deep underground"),
    ("6LALUQTOFj3CKV2aYb3VGL", "Odd Electro", "outsider / leftfield / homemade experimental electronic"),
    ("4mru1A0vGvqPVdAFds0sPM", "Drone",       "underground drone and heavy ambient"),
    ("0Odd1WdiPXE4hnEDcCp7bO", "Kraut Psych", "krautrock-style motorik psych, modern underground"),
    ("1hJEnVjA0RQ62PtqpBjMg2", "Avant Jazz",  "avant-garde / free / spiritual jazz, small labels"),
    ("6Aw46nLUVbjcR8ffwvzxbG", "DIY Heavy",   "lo-fi DIY sludge, post-hardcore and noisy metal"),
    ("4Pf7PW0K53dGvYWMwpK4qH", "Bright Metal", "uplifting major-key post-metal / blackgaze with harsh vocals (Pijn & Conjurer, Møl, Svalbard)"),
    ("1E1DBxxG3ya5QF27uwgkdt", "Hipstercore", "indie-sleaze / dance-punk, deeper than LCD + Parquet Courts"),
    ("1Ywcj6c3OiCMiRlhw4wLz6", "Art Punk",    "NYC / UK art-punk, dance-punk, no-wave (BODEGA, Model Actriz, ESG vein)"),
    ("2nHsyGKct8Y7pzq7NJySZB", "Chiptune",    "chip / bitpop / breakcore / game-ambient (Crystal Castles, Battles axis)"),
    ("2tWfiFunW9ROaj1ZgGB40D", "Sludge",      "atmospheric sludge & post-metal (Isis, Pelican, Russian Circles axis)"),
    ("1WRAp5jtnAIkH9ue3P8pHu", "Reggae Dub",  "roots reggae & dub (Augustus Pablo, King Tubby, Scientist vein)"),
    ("1Lq08wBXeK3hVG8eC1EkE5", "Shoegaze",    "shoegaze / dream-pop / slowcore with vocals"),
    ("2tZDIcsN1RYcDkY7sDvNlX", "Post-Rock",   "crescendo & cinematic instrumental post-rock"),
    ("3QInZAMPxGSmQRwlssv5Dc", "Folk Drone",  "instrumental folk + drone-classical"),
    ("3zSd4nB7Xj41YrQ9ZfHyJG", "Dub Techno",  "dub-techno, IDM & deep ambient (Burial, Boards of Canada axis)"),
    ("3lYGaZnjxm6tgbvwYWc0go", "Garage Punk", "garage / post-punk revival, deep cuts"),
    ("3eKcCYj2GjRtmZvUSH4dba", "Trip Hop",    "electronica / trip-hop / dub"),
    ("5s9mae1mqWOI1enKwpUK2O", "Trad Folk",   "Irish trad + american-primitive guitar (Lankum, Fahey axis)"),
]

PROMPT = """\
You are John's music scout. Spotify's algorithm keeps feeding him the same \
things; your job is freshness. For each lane below, name {ask} REAL artists \
that are on Spotify, ALTERNATING two tiers so the playlist interweaves them:
- deep: college-radio-at-midnight, small labels, Bandcamp-scene, low monthly \
listeners, critic-respected.
- canon: the genre's essential, well-regarded names (the records a good \
record-store clerk says you must know), still not chart-pop.
Start with deep, then canon, then deep, and so on. Never invented. Both tiers \
must respect the exclusion list.

What he has liked lately (artist — track):
{liked}

His top artists right now:
{top}

Do NOT name any of these (already owned, sent before, or in the lane):
{exclude}

Lanes:
{lanes}

Reply with ONLY a JSON object, no prose, no code fence:
{{"<lane name>": [{{"artist": "...", "tier": "deep|canon", "why": "<=12 words"}}, ...], ...}}
"""


def lane_artists(pid):
    """Normalized artist names already in a playlist."""
    names = set()
    for it in sc.get_all(f"/playlists/{pid}/items", {"limit": 100}):
        tr = it.get("item") or it.get("track") or {}
        for a in tr.get("artists", []):
            names.add(br.norm(a["name"]))
    return names


def ask_claude(lanes, taste, exclude_names, ask):
    liked = [f"{t.get('artist', '')} — {t.get('name', '')}" for t in taste.get("saved_tracks", [])[:60]]
    top = [a["name"] for a in taste.get("top_artists_short_term", [])[:30]]
    prompt = PROMPT.format(
        ask=ask,
        liked="\n".join(liked),
        top=", ".join(top),
        exclude=", ".join(sorted(exclude_names)),
        lanes="\n".join(f"- {name}: {brief}" for _, name, brief in lanes),
    )
    return wr.claude_json(prompt, MODEL)


def write_digest(day, added):
    os.makedirs(DIGEST_DIR, exist_ok=True)
    path = os.path.join(DIGEST_DIR, f"lanes-{day}.md")
    lines = [f"# Lane refresh — {day}", ""]
    for name, rows in added.items():
        if not rows:
            continue
        lines.append(f"## {name}")
        for m in rows:
            lines.append(f"- **{m['artist']} — {m['album']}** ({m['year']}) · _{m['track']}_  \n  {m['why']}")
        lines.append("")
    open(path, "w").write("\n".join(lines))
    return path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true", help="resolve + print, no playlist or history writes")
    ap.add_argument("--per", type=int, default=PER)
    ap.add_argument("--lanes", help="comma-separated lane names to refresh (default: all)")
    args = ap.parse_args()

    lanes = LANES
    if args.lanes:
        want = {s.strip().lower() for s in args.lanes.split(",")}
        lanes = [l for l in LANES if l[1].lower() in want]
        if not lanes:
            sys.exit(f"no lanes match {args.lanes!r}")
    # Starved lanes first: a rate-limit stop hits the tail, so the tail must rotate.
    last = {}
    for r in wr.load_history()["recommended"]:
        if r.get("lane"):
            last[r["lane"]] = max(last.get(r["lane"], ""), r["week"])
    lanes = sorted(lanes, key=lambda l: last.get(l[1], ""))

    day = dt.date.today().isoformat()
    print(f"=== lane refresh: {day} ({len(lanes)} lanes, +{args.per} each) ===")

    print("refreshing taste profile…")
    analyze_taste.main()
    taste = json.load(open(wr.TASTE_PATH))
    history = wr.load_history()
    exclude = wr.exclusion_artists(taste, history)
    for t in taste.get("saved_tracks", []):
        exclude.add(br.norm(t.get("artist", "")))

    in_lane = {}
    for pid, name, _ in lanes:
        in_lane[name] = lane_artists(pid)
        exclude |= in_lane[name]
    print(f"exclusion set: {len(exclude)} artists\n")

    print(f"asking Claude ({MODEL})…")
    picks = ask_claude(lanes, taste, exclude, ASK)

    added = {}
    for pid, name, _ in lanes:
        cands = [{"bucket": name, "artist": p["artist"], "tier": p.get("tier", "deep"),
                  "why": f"[{p.get('tier', 'deep')}] {p.get('why', '')}"}
                 for p in picks.get(name, []) if p.get("artist")]
        print(f"\n[{name}] {len(cands)} candidates")
        # resolve each tier to its quota, then interweave deep/canon/deep/...
        quota = {"deep": (args.per + 1) // 2, "canon": args.per // 2}
        tiers = {}
        try:
            for tier, want in quota.items():
                tiers[tier] = wr.resolve([c for c in cands if c["tier"] == tier], exclude, want)
                for _, m in tiers[tier]:
                    exclude.add(br.norm(m["artist"]))   # no artist lands in two lanes
        except sc.RateLimited as e:
            print(f"\nSTOPPING: {e}. Lanes done so far are saved; rerun later.")
            break
        resolved = [x for pair in zip_longest(tiers["deep"], tiers["canon"]) for x in pair if x]
        added[name] = [m for _, m in resolved]
        if resolved and not args.dry:
            sc.post(f"/playlists/{pid}/items", {"uris": [u for u, _ in resolved]})
            for _, m in resolved:
                history["recommended"].append(
                    {"artist": m["artist"], "album": m["album"], "week": day, "lane": name})
            json.dump(history, open(wr.HISTORY_PATH, "w"), indent=2)   # per lane: survives a kill
        time.sleep(10)                                # album endpoint bans for ~24h when hammered

    digest = write_digest(day, added)
    total = sum(len(v) for v in added.values())
    print(f"\n{total} tracks across {sum(1 for v in added.values() if v)} lanes. digest: {digest}")
    if args.dry:
        print("DRY run — no playlist or history writes.")
        return
    print(f"history: {len(history['recommended'])} total recommendations")


if __name__ == "__main__":
    main()
