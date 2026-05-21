# spotify-cagebreak

Weekly "algorithm cage-break" music discovery. Pulls your Spotify taste, asks a
**local Ollama model** for opinionated picks *adjacent to* your taste but not in
your library and not recommended before, then builds a dated discovery playlist
and a markdown digest. No recommender-algorithm feedback loop.

## How it works

1. `spotify_auth.py` — one-time PKCE login, writes `token.json` (gitignored).
2. `spotify_client.py` — headless token refresh + thin Spotify REST wrapper.
3. `analyze_taste.py` — dumps your listening profile to `taste.json`.
4. `weekly_recs.py` — asks Ollama for fresh picks, resolves to Spotify, builds
   one dated playlist, records history so weeks never repeat, writes a digest.

Supporting scripts: `build_recs.py` / `picks.py` (album → signature tracks →
per-bucket playlists), `fetch_tracks.py`, `fix_mismatches.py`, `apply_fixes*.py`.

## Setup

```bash
# 1. Spotify app: create one at developer.spotify.com, note the client_id.
#    Redirect URI must include http://127.0.0.1:8888/callback
python3 spotify_auth.py <CLIENT_ID>     # or set SPOTIFY_CLIENT_ID

# 2. Local LLM
ollama serve
ollama pull glm-4.7-flash:latest         # or any model; pass --model

# 3. Run
python3 weekly_recs.py --dry             # preview
python3 weekly_recs.py                    # build live playlist
```

## Notes

- `token.json` holds your OAuth tokens and is **gitignored** — never commit it.
- `taste.json` / `digests/` here are sample data from one run.
- Pure stdlib + Ollama; no pip deps.
