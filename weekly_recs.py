#!/usr/bin/env python3
"""Weekly algorithm-cage-break discovery.

Each run:
  1. refresh Spotify taste (headless token refresh, no browser)
  2. ask a local Ollama model for fresh opinionated picks adjacent to John's
     taste but NOT in his library and NOT recommended before
  3. resolve picks to Spotify, build ONE dated discovery playlist
  4. record picks in history.json (so next week never repeats) + write a digest

Needs:  Ollama running locally (`ollama serve`) with the model below pulled.
Run:    python3 weekly_recs.py [--dry] [--n 24] [--model glm-4.7-flash:latest]
"""
import argparse
import datetime as dt
import json
import os
import sys
import time
import urllib.error
import urllib.request

import spotify_client as sc
import analyze_taste
import build_recs as br

HERE = os.path.dirname(os.path.abspath(__file__))
TASTE_PATH = os.path.join(HERE, "taste.json")
HISTORY_PATH = os.path.join(HERE, "history.json")
RECS_SEED = os.path.join(HERE, "recs.md")
DIGEST_DIR = os.path.join(HERE, "digests")

OLLAMA_URL = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
MODEL = "gpt-oss:20b"  # fast MoE; override with --model (glm-4.7-flash richer but slow/OOM-prone)
TARGET = 24            # tracks in the weekly playlist (1 per artist)
LLM_TIMEOUT = 900      # seconds; covers cold model load + generation

BUCKETS = ["punk", "folk", "electronic", "indie", "hipstercore", "chiptune"]

PERSONA = """\
You are John's personal music scout. Your whole job is to break him out of \
the streaming-algorithm cage: surface genuinely new artists he does not \
already own, adjacent to his taste but weirder, deeper-catalog, and \
critic-respected (Pitchfork/Quietus/Bandcamp Daily/Aquarium Drunkard tier). \
You are opinionated. You never recommend the obvious or the mainstream.

John's taste, by mood bucket:
- punk: metallic hardcore / mathcore / post-metal / sludge / noise-rock / screamo.
  Axis: Cave In, Botch, Converge, ISIS, Old Man Gloom, Dillinger, Shellac, Mclusky.
- folk: Irish trad + american-primitive guitar + drone-classical.
  Axis: Lankum, OXN, John Fahey, Jake Xerxes Fussell, plus post-rock (Mogwai, EITS).
- electronic: IDM / ambient / dub-techno / triphop / dub.
  Axis: Burial, Boards of Canada, Aphex Twin, Floating Points, Augustus Pablo, Tortoise.
- indie: shoegaze / slowcore / dream-pop / art-rock (vocals).
  Axis: Modest Mouse, DIIV, Beach House, Slint, Alex G, Big Thief, Mazzy Star.
- hipstercore: indie-sleaze / dance-punk / NYC art-punk / garage revival.
  Axis: The Strokes, Yeah Yeah Yeahs (he already owns LCD + Parquet Courts; go deeper).
- chiptune: chip/bitpop / breakcore / hyperpop-adjacent / game-music ambient.
  Axis: Crystal Castles, Battles.

Rules:
- Recommend ARTISTS (not specific albums). Name only REAL, existing artists you
  are confident about — do not invent names. We pick the album from Spotify later.
- Spread picks across all 6 buckets.
- Lean toward active/current artists (2020s) and rotate emphasis week to week.
- NEVER name an artist in the exclusion list (already owned or already sent).
- Each `why` is ONE sharp sentence: the cage-break angle, not a genre label."""

BUCKET_AXIS = {
    "punk": "metallic hardcore / mathcore / post-metal / sludge / noise-rock / screamo",
    "folk": "Irish trad + american-primitive guitar + drone-classical + post-rock",
    "electronic": "IDM / ambient / dub-techno / triphop / dub",
    "indie": "shoegaze / slowcore / dream-pop / art-rock (with vocals)",
    "hipstercore": "indie-sleaze / dance-punk / NYC art-punk / garage revival",
    "chiptune": "chip/bitpop / breakcore / hyperpop-adjacent / game-music ambient",
}

# Output schema for ONE bucket. We ask only for ARTIST names (local models recall
# artists far better than exact album titles, which they hallucinate); the actual
# album is grounded in Spotify data later. One small array per call stays well
# under the model's limits — large arrays make the constrained decoder 500.
ARTIST_SCHEMA = {
    "type": "object",
    "properties": {
        "artists": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "artist": {"type": "string"},
                    "why": {"type": "string"},
                },
                "required": ["artist", "why"],
            },
        }
    },
    "required": ["artists"],
}


def load_history():
    """All artist|album ever recommended. Seeds from recs.md on first run."""
    if os.path.exists(HISTORY_PATH):
        return json.load(open(HISTORY_PATH))
    seed = []
    if os.path.exists(RECS_SEED):
        for r in br.parse_recs(RECS_SEED):
            seed.append({"artist": r["artist"], "album": r["album"], "week": "seed"})
    return {"recommended": seed}


def exclusion_artists(taste, history):
    """Lowercased artist names to never recommend: owned + previously sent."""
    ex = set()
    for a in taste.get("saved_albums", []):
        ex.add(br.norm(a["artist"]))
    for rec in history["recommended"]:
        ex.add(br.norm(rec["artist"]))
    return ex


def ollama_up():
    try:
        urllib.request.urlopen(f"{OLLAMA_URL}/api/tags", timeout=5)
        return True
    except Exception:
        return False


def _ollama_chat(model, system, user, schema, tries=3):
    payload = {
        "model": model,
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": user}],
        "format": schema,
        "stream": False,
        "options": {"temperature": 0.9, "num_ctx": 4096},
    }
    data = json.dumps(payload).encode()
    last = None
    for attempt in range(tries):
        try:
            req = urllib.request.Request(
                f"{OLLAMA_URL}/api/chat", data=data,
                headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=LLM_TIMEOUT) as resp:
                return json.loads(json.loads(resp.read())["message"]["content"])
        except Exception as e:                 # 500 / RemoteDisconnected: runner hiccup
            last = e
            time.sleep(5 * (attempt + 1))      # back off; daemon often recovers
    raise last


def _ask_bucket(model, bucket, n, known, sent):
    user = (
        f"Lane: {bucket} — {BUCKET_AXIS[bucket]}.\n\n"
        f"Name exactly {n} REAL, existing artists in this lane for me to discover: "
        f"adjacent to my taste but weirder/deeper, critic-respected, none mainstream. "
        f"Do not invent names.\n\n"
        f"Do NOT name artists I already own:\n{json.dumps(known)}\n\n"
        f"Do NOT repeat ones you sent recently:\n{json.dumps(sent)}"
    )
    out = _ollama_chat(model, PERSONA, user, ARTIST_SCHEMA)
    return [{"bucket": bucket, "artist": a["artist"], "why": a.get("why", "")}
            for a in out.get("artists", []) if a.get("artist")]


def ask_llm(taste, history, want, model):
    """One small call per bucket (large arrays 500 the constrained decoder).
    Returns candidates round-robin-interleaved so buckets fill evenly."""
    recent_recs = [r for r in history["recommended"] if r["week"] != "seed"][-40:]
    sent = sorted({r["artist"] for r in recent_recs})
    # Hint only — the full 500+ owned set is enforced after resolve, so keep small.
    known = sorted({a["name"] for a in taste.get("top_artists_short_term", [])}
                   | {a["name"] for a in taste.get("top_artists_medium_term", [])})[:40]
    per = want // len(BUCKETS) + 3   # buffer for owned/dupe/not-found skips

    by_bucket = {}
    for b in BUCKETS:
        try:
            by_bucket[b] = _ask_bucket(model, b, per, known, sent)
            print(f"  {b:11} {len(by_bucket[b])} candidates")
        except Exception as e:
            print(f"  {b:11} FAILED ({type(e).__name__})")
            by_bucket[b] = []
        time.sleep(2)                          # let the runner settle between calls

    picks, i = [], 0
    while any(i < len(by_bucket[b]) for b in BUCKETS):
        for b in BUCKETS:
            if i < len(by_bucket[b]):
                picks.append(by_bucket[b][i])
        i += 1
    return picks


def _find_artist(name):
    """Return (artist_id, canonical_name) for the best Spotify match, or None."""
    res = sc.get("/search", {"q": name, "type": "artist", "limit": 5, "market": "US"})
    for a in res.get("artists", {}).get("items", []):
        if br._artist_match(a["name"], name):
            return a["id"], a["name"]
    return None


def _signature(artist_id):
    """A signature track for an artist: newest full album, signature/opener cut.
    Avoids /top-tracks (403 on this app). Returns (uri, track, album, year) or None."""
    albums = br._fetch_artist_albums(artist_id)        # offset-paged, known-good
    full = [a for a in albums if a.get("album_type") == "album"] or albums
    if not full:
        return None
    full.sort(key=lambda a: a.get("release_date", ""), reverse=True)  # newest first
    al = full[0]
    tr = br.pick_tracks(al["id"], artist_id)           # top-tracks(403)→album-cut fallback
    if not tr:
        return None
    return tr[0]["uri"], tr[0]["name"], al["name"], (al.get("release_date", "") or "")[:4]


def resolve(picks, exclude, want):
    """Ground each artist pick in real Spotify data until `want` land.
    Skips owned, already-sent, dupes-this-run, and artists not on Spotify."""
    out, seen = [], set()
    for p in picks:
        if len(out) >= want:
            break
        if br.norm(p["artist"]) in exclude:
            print(f"  skip (owned/sent): {p['artist']}")
            continue
        found = _find_artist(p["artist"])
        if not found:
            print(f"  ✗ not on Spotify: {p['artist']}")
            continue
        aid, canon = found
        key = br.norm(canon)
        if key in exclude or key in seen:      # match landed on owned, or repeated
            print(f"  skip (owned/dupe): {canon}")
            continue
        sig = _signature(aid)
        if not sig:
            print(f"  ✗ no tracks: {canon}")
            continue
        uri, track, album, year = sig
        seen.add(key)
        out.append((uri, {"bucket": p["bucket"], "artist": canon, "album": album,
                          "year": year, "track": track, "why": p.get("why", "")}))
        print(f"  ✓ [{p['bucket']:11}] {canon} — {album} ({year}): {track}")
    return out


def write_digest(week, resolved):
    os.makedirs(DIGEST_DIR, exist_ok=True)
    path = os.path.join(DIGEST_DIR, f"week-{week}.md")
    lines = [f"# Cage-break — week of {week}", ""]
    for b in BUCKETS:
        rows = [m for _, m in resolved if m["bucket"] == b]
        if not rows:
            continue
        lines.append(f"## {b}")
        for m in rows:
            lines.append(f"- **{m['artist']} — {m['album']}** ({m['year']}) · _{m['track']}_  \n  {m['why']}")
        lines.append("")
    open(path, "w").write("\n".join(lines))
    return path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true", help="resolve + print, no playlist, no history write")
    ap.add_argument("--n", type=int, default=TARGET)
    ap.add_argument("--model", default=MODEL, help="Ollama model tag")
    args = ap.parse_args()

    if not ollama_up():
        sys.exit(f"ERROR: Ollama not reachable at {OLLAMA_URL}. Start it: ollama serve")

    week = dt.date.today().isoformat()
    print(f"=== weekly cage-break: {week} ===")

    print("refreshing taste profile…")
    analyze_taste.main()                       # writes/refreshes taste.json
    taste = json.load(open(TASTE_PATH))
    history = load_history()
    exclude = exclusion_artists(taste, history)
    print(f"exclusion set: {len(exclude)} artists\n")

    print(f"asking Ollama ({args.model}) per bucket…")
    picks = ask_llm(taste, history, args.n, args.model)
    print(f"got {len(picks)} candidate artists. resolving on Spotify…\n")

    resolved = resolve(picks, exclude, args.n)
    if not resolved:
        sys.exit("nothing resolved — aborting")
    print(f"\nresolved {len(resolved)}/{args.n} target.")

    digest = write_digest(week, resolved)
    print(f"digest: {digest}")

    if args.dry:
        print("\nDRY run — no playlist created, history not updated.")
        return

    name = f"🗓 cage-break — week of {week}"
    desc = (f"Weekly algorithm-cage-break discovery, {len(resolved)} new artists "
            f"adjacent to your taste. Generated {week} locally by {args.model}.")
    pl = sc.post("/me/playlists", {"name": name, "public": False, "description": desc})
    uris = [u for u, _ in resolved]
    for i in range(0, len(uris), 100):
        sc.post(f"/playlists/{pl['id']}/items", {"uris": uris[i:i + 100]})
    url = pl["external_urls"]["spotify"]
    print(f"\n+ {name}  ({len(uris)} tracks)\n{url}")

    history["recommended"].extend(
        {"artist": m["artist"], "album": m["album"], "week": week} for _, m in resolved
    )
    json.dump(history, open(HISTORY_PATH, "w"), indent=2)
    print(f"history updated: {len(history['recommended'])} total recommendations")


if __name__ == "__main__":
    main()
