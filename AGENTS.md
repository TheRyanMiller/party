# NYE Party Slideshow - Project Context

## Purpose

A full-featured New Year's Eve party slideshow application designed to:
1. Display a curated "Year in Review" slideshow (2016 theme) with video backgrounds
2. Allow party guests to submit memories and resolutions via mobile-friendly form
3. Give party hosts admin controls to manage the presentation in real-time
4. Synchronize playback across multiple displays

## Project Initialization

### For Fresh Clone
Run `python scripts/setup.py` to:
1. Create `videos/{slide-id}/` directories for each slide in slideshow.yaml
2. Generate `youtube_download_plan.yaml` with template entries
3. Preserve any existing download entries (safe to run multiple times)

### Video Management
- Videos are NOT stored in git (too large, ~10GB+)
- `youtube_download_plan.yaml` tracks download sources and status
- Use `python scripts/download_videos.py` to download videos
- Prefix video filename with `_` to hide without deleting (e.g., `_video.mp4`)

### Files NOT in Git
- `videos/` - Downloaded video files
- `background_images/*` - Custom background images (add your own)
- `data/*` - Runtime data (party.db, play_counts.json)
- `__pycache__/` - Python cache

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│  CLIENTS                                                        │
├─────────────────┬──────────────────┬───────────────────────────┤
│  Slideshow      │  Admin Panel     │  Guest Form               │
│  (Main Display) │  (Host Phone)    │  (Guest Phones)           │
│                 │                  │                           │
│  - Video player │  - Remote ctrl   │  - Submit memories        │
│  - Auto-advance │  - Live status   │  - Submit resolutions     │
│  - Countdown    │  - Approve/rej   │  - Optional name          │
└────────┬────────┴────────┬─────────┴─────────────┬─────────────┘
         │                 │                       │
         └─────────────────┼───────────────────────┘
                           │ HTTP/REST
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│  SERVER (FastAPI)                                               │
│  server.py                                                      │
├─────────────────────────────────────────────────────────────────┤
│  Video API        │  Submissions API   │  Slideshow State API  │
│  - /api/video/*   │  - /api/submissions│  - /api/slideshow/*   │
│  - Play counts    │  - Approval flow   │  - Pause/resume/goto  │
│  - Least-played   │  - Admin auth      │  - Real-time sync     │
└─────────┬─────────┴──────────┬─────────┴──────────┬─────────────┘
          │                    │                    │
          ▼                    ▼                    ▼
┌─────────────────┐  ┌─────────────────┐  ┌─────────────────────┐
│ play_counts.json│  │   party.db      │  │  videos/            │
│ (video tracking)│  │   (SQLite)      │  │  (MP4 files)        │
└─────────────────┘  └─────────────────┘  └─────────────────────┘
```

## Core Components

| File | Lines | Purpose |
|------|-------|---------|
| `backend/server.py` | ~970 | FastAPI backend - routes, video API, auth, static serving |
| `backend/database.py` | ~300 | SQLite module - submissions, sessions, slideshow state |
| `ui/2016-slideshow.html` | ~1640 | Main slideshow - video playback, transitions, countdown |
| `ui/admin.html` | ~1055 | Admin panel - remote control, submission moderation |
| `ui/guest.html` | ~470 | Guest form - memory/resolution submission |
| `slideshow.yaml` | ~600 | Slide definitions - 40 slides with layouts, moods, videos |
| `scripts/download_videos.py` | ~850 | CLI tool for downloading YouTube videos |
| `scripts/setup.py` | ~210 | Project initialization script |

## Video System

### Selection Algorithm
```python
def select_least_played(slide_id):
    # Sort by (play_count, path) for determinism
    # Returns video with lowest count, alphabetically first if tie
```

### Priority Order
1. **Local MP4** (`videos/{slide_id}/*.mp4`) - Preferred, no buffering
2. **YouTube Primary** - Fallback if local fails
3. **YouTube Fallbacks** - Array of backup video IDs

### Codec Compatibility
- **VP9/H.264** - Works in all browsers
- **AV1** - Limited support (Safari issues) - should be transcoded

## Database Schema

**SQLite (`party.db`):**
```sql
-- Guest submissions with approval workflow
submissions (id, guest_name, memory_2025, resolution_2026, status, created_at)
-- status: 'pending' | 'approved' | 'rejected'

-- Admin session tokens (12-hour expiry)
admin_sessions (token, created_at, expires_at)

-- Slideshow playback state (single row)
slideshow_state (id, is_paused, current_slide, current_slide_index,
                 slide_duration, slide_started_at, last_updated)
```

## API Endpoints

### Video Management
```
GET  /api/video/{slide_id}        → Returns least-played video path
POST /api/video/{slide_id}/played → Increments play count
GET  /api/inventory               → Full inventory with counts
POST /api/inventory/reload        → Rescan videos/ directory
```

### Guest Submissions
```
POST /api/submissions             → Submit memory/resolution
GET  /api/submissions?status=...  → List by status (admin)
GET  /api/submissions/approved    → Public approved list
PUT  /api/submissions/{id}/approve
PUT  /api/submissions/{id}/reject
```

### Admin & Slideshow
```
POST /api/admin/login             → Returns session token
POST /api/admin/logout
GET  /api/admin/verify            → Validate token
GET  /api/slideshow/state         → Current playback state
POST /api/slideshow/control       → pause/resume/goto
POST /api/slideshow/sync          → Main display syncs position
```

### Static Files
```
GET  /                            → Slideshow
GET  /admin                       → Admin panel
GET  /guest                       → Guest form
GET  /api/family-pics             → Background images list
```

## Configuration

### slideshow.yaml Structure
```yaml
meta:
  title: "2016 - What A Year"
  transition: 1200
  loop: true

defaults:
  layout: standard
  mood: warm
  duration: 30000
  overlay: 0.4

slides:
  - id: slide-id           # Maps to videos/slide-id/
    layout: hero           # hero, standard, meme, quote, split
    mood: warm             # warm, cool, dark, neon, retro, meme, golden
    emoji: "🎉"
    category: "Section"
    title: "TITLE"
    subtitle: "Body text"
    video:
      youtube: "VIDEO_ID"
      fallbacks: ["ID1", "ID2"]
      # Per-video playback timestamps (use filename as key)
      my-video.mp4:
        start: 10          # Start playback at 10s
        end: 45            # Stop at 45s (optional)
```

## Key Implementation Details

### Slideshow Lifecycle
1. Fetch slideshow.yaml, parse with js-yaml
2. Build invisible DOM elements for all slides
3. On slide enter: `fetchVideoForSlide()` → API returns least-played
4. Create video element, start playback (muted for autoplay)
5. Report played: `POST /api/video/{id}/played`
6. Countdown timer (SVG circular progress)
7. Auto-advance or await user input

### Admin Synchronization
- Admin polls `/api/slideshow/state` every 1000ms
- Main display calls `/api/slideshow/sync` on slide change
- All connected clients stay within ~1 second sync

### Authentication
- Password: env `ADMIN_PASSWORD` or default "kaya"
- Token: 43-character random string, 12-hour expiry
- Stored in localStorage, validated per request

## Directory Structure

```
nye-party/
├── backend/                     # Python backend
│   ├── __init__.py
│   ├── server.py               # FastAPI server
│   └── database.py             # SQLite database module
│
├── scripts/                     # CLI utilities
│   ├── setup.py                # Initialize project structure
│   └── download_videos.py      # Video downloader
│
├── ui/                          # Frontend HTML
│   ├── 2016-slideshow.html     # Main slideshow
│   ├── admin.html              # Admin panel
│   └── guest.html              # Guest submission form
│
├── data/                        # Runtime data (not in git)
│   ├── party.db                # SQLite database
│   └── play_counts.json        # Video play tracking
│
├── slideshow.yaml               # 40 slide definitions
├── youtube_download_plan.yaml   # Video download manifest
├── requirements.txt             # Python deps
│
├── videos/                      # Video files by slide (not in git)
│   ├── one-dance/              # Multiple MP4s per slide
│   ├── lemonade/
│   └── ...
│
├── images/                      # Meme/reference images
└── background_images/           # Custom slide backgrounds (not in git)
```

## Development Commands

```bash
# Start server (with auto-reload) - run from project root
uvicorn backend.server:app --reload --port 8000

# Serve on local network
uvicorn backend.server:app --host 0.0.0.0 --port 8000

# Initialize project structure (creates video dirs + download plan)
python scripts/setup.py

# Download videos
python scripts/download_videos.py                    # All pending
python scripts/download_videos.py --slide one-dance # Specific slide
python scripts/download_videos.py --dry-run          # Preview only

# Transcode AV1 to VP9 (browser compatibility)
ffmpeg -i input.mp4 -c:v libvpx-vp9 -crf 30 -b:v 0 -c:a copy output.mp4
```

## Known Issues & Fixes

### Video Not Playing
- Check codec: `ffprobe -v error -show_entries stream=codec_name file.mp4`
- AV1 codec not supported in Safari - transcode to VP9
- Ensure file > 1KB (server filters small/corrupt files)

### Slow Loading
- Large images: optimize to ~500-900KB before adding to `background_images/`
- Video transcoding in background consumes CPU

### Admin 401 Loops
- Token check before requests
- `isLoggingOut` flag prevents recursive calls
- Funny error messages cycle on failed login

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `ADMIN_PASSWORD` | `kaya` | Password for admin login |

## Performance Notes

- Video inventory: Scanned once on startup, cached in memory
- Play counts: In-memory + atomic JSON persistence
- Polling intervals: Admin 1000ms, countdown 100ms
- API timeout: 2 seconds for video requests
