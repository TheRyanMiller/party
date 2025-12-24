NYE Party Slideshow – Code Audit
================================

Primary findings (ordered by reliability risk for party playback)

- Video play-count mismatch under concurrency: `backend/server.py:560-584` increments the *current* least-played video for a slide, not the video path that the client actually fetched. If two displays fetch simultaneously, the “played” report can increment the wrong file, skewing rotation and repeatedly serving the same clip. Fix: have the client send the specific `video_path` it started, and validate/exact-match on the server before incrementing.
- Missing fallback on local video failure: `ui/2016-slideshow.html:1184-1190` removes the `<video>` on error and leaves the slide without video; no retry or switch to another source/YouTube. This manifests as a black background for the entire slide duration. Fix: on `error`/`stalled`/`waiting` timeout, request the next least-played video (or YouTube fallback) and retry; at minimum, keep the previous playable video instead of removing.
- Codec support risk (AV1-heavy library): local inventory is mostly AV1 (42 AV1 vs 18 VP9 vs 6 H.264). Brave usually supports AV1, but decode can fail on some GPUs/OS configs, causing the “1s then black” symptom with no JS error. Fix: verify failing files in `chrome://media-internals`; transcode only problematic AV1 files to high-quality VP9/H.264, or add a codec check/warning in the inventory scan to flag unsupported files before showtime.
- Global in-memory state not safe for multi-worker: play counts, inventory, and injected slides live in-process (`backend/server.py:78-122, 205-265`). Running uvicorn with multiple workers will desynchronize counts and injected slides. Fix: enforce single-process run or move these to SQLite/redis with locking.
- Admin auth defaults to “kaya” in config and CORS is `*` (`backend/server.py:74-105, 166-183`), so anyone on the LAN can hit admin endpoints if they learn the password. For a public/party Wi‑Fi, set a strong password and tighten `allow_origins`.
- Slideshow hide state can drift after reload: `ui/2016-slideshow.html:1689-1721` clears `localVideos` and reloads slides, but does not reconcile the current `hiddenSlides` list with the fresh slide set. If slides were hidden before reload, the re-render might briefly show them until the next poll. Fix: reapply `hiddenSlides` when re-rendering.

Follow-ups / quick improvements
- Add a watchdog around `video.readyState` plus a timeout to re-trigger `play()` or swap sources when stalled.
- Log/alert on `/api/video/{slide}` when a directory is empty, so missing files are caught before showtime.
- Pin `yt-dlp` version in tooling to avoid CLI incompatibilities during last-minute downloads.
