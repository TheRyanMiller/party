# NYE Party Slideshow

A full-featured New Year's Eve party slideshow application with video backgrounds, guest submissions, and real-time admin controls. Currently themed around "2016 - Year in Review" with 40 curated slides.

## Features

- **Full-Screen Video Slideshow**: Background videos with smooth transitions and countdown timer
- **Play Count Balancing**: Server rotates through videos to ensure variety
- **Guest Submissions**: Mobile-friendly form for guests to share memories and resolutions
- **Admin Remote Control**: Pause, skip, and control the slideshow from your phone
- **Real-Time Sync**: Multiple displays stay synchronized
- **Approval Workflow**: Admin reviews and approves guest submissions before display

## Quick Start (Fresh Clone)

### 1. Install Dependencies

```bash
# Python packages
pip install -r requirements.txt

# External tools (macOS)
brew install yt-dlp ffmpeg
```

### 2. Initialize Project Structure

```bash
python scripts/setup.py
```

This creates:
- `videos/{slide-id}/` directories for each slide
- `youtube_download_plan.yaml` template with placeholder entries

### 3. Add YouTube URLs & Download Videos

Edit `youtube_download_plan.yaml` and replace `# TODO: Add YouTube URL` with actual YouTube URLs, then:

```bash
python scripts/download_videos.py
```

### 4. Start the Server

```bash
# Development (with auto-reload)
uvicorn backend.server:app --reload --port 8000

# Production / Local Network
uvicorn backend.server:app --host 0.0.0.0 --port 8000
```

### 5. Access the Application

| Page | URL | Description |
|------|-----|-------------|
| Slideshow | http://localhost:8000/ | Main display (TV/projector) |
| Guest Form | http://localhost:8000/guest | Guests submit memories |
| Admin Panel | http://localhost:8000/admin | Host controls (password: `kaya`) |

## Requirements

- Python 3.10+
- yt-dlp (for downloading videos)
- ffmpeg (video processing)

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `ADMIN_PASSWORD` | `kaya` | Password for admin login |

### slideshow.yaml

The main configuration file defining all slides:

```yaml
meta:
  title: "2016 - What A Year"
  transition: 1200        # Fade duration (ms)
  loop: true

defaults:
  layout: standard
  mood: warm
  duration: 30000         # 30 seconds per slide
  overlay: 0.4            # Video overlay opacity

slides:
  - id: one-dance
    layout: standard      # hero, standard, meme, quote, split
    mood: warm            # warm, cool, dark, neon, retro, meme, golden
    emoji: "💃"
    category: "Music"
    title: "ONE DANCE"
    subtitle: "Drake dominated the charts"
    video:
      youtube: "VIDEO_ID"           # YouTube fallback
      fallbacks: ["ID1", "ID2"]     # Additional fallbacks
      # Per-video playback timestamps (optional)
      specific-video.mp4:
        start: 10                   # Start at 10 seconds
        end: 45                     # End at 45 seconds
```

### youtube_download_plan.yaml

Video download manifest with status tracking:

```yaml
slides:
  one-dance:
    videos:
    - url: https://www.youtube.com/watch?v=VIDEO_ID
      start: 30            # Start time (seconds)
      end: 90              # End time (seconds)
      status: pending      # pending, completed, error
```

## Video Management

### Downloading Videos

```bash
# Download all pending videos
python scripts/download_videos.py

# Download specific slide
python scripts/download_videos.py --slide one-dance

# Preview without downloading
python scripts/download_videos.py --dry-run

# Retry failed downloads
python scripts/download_videos.py --retry-errors
```

### Video Organization

Videos are organized by slide ID:
```
videos/
├── one-dance/
│   ├── video1.mp4
│   └── video2.mp4      # Multiple videos = automatic rotation
├── lemonade/
│   └── video.mp4
└── ...
```

### Codec Compatibility

Some videos may be encoded with AV1 codec which has limited browser support (especially Safari). Transcode to VP9:

```bash
# Check codec
ffprobe -v error -show_entries stream=codec_name video.mp4

# Transcode AV1 to VP9
ffmpeg -i input.mp4 -c:v libvpx-vp9 -crf 30 -b:v 0 -c:a copy output.mp4
```

## API Endpoints

### Video API
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/video/{slide_id}` | Get next video for slide |
| POST | `/api/video/{slide_id}/played` | Report video started |
| GET | `/api/inventory` | Full video inventory |
| POST | `/api/inventory/reload` | Rescan videos directory |

### Submissions API
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/submissions` | Submit memory/resolution |
| GET | `/api/submissions?status=pending` | List by status (admin) |
| GET | `/api/submissions/approved` | Public approved list |
| PUT | `/api/submissions/{id}/approve` | Approve (admin) |
| PUT | `/api/submissions/{id}/reject` | Reject (admin) |

### Slideshow Control API
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/slideshow/state` | Current playback state |
| POST | `/api/slideshow/control` | Pause/resume/goto |
| POST | `/api/slideshow/sync` | Sync from main display |

### Admin API
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/admin/login` | Login, returns token |
| POST | `/api/admin/logout` | Invalidate session |
| GET | `/api/admin/verify` | Validate token |

## Keyboard Controls (Slideshow)

| Key | Action |
|-----|--------|
| Left/Right | Previous/Next slide |
| Spacebar | Pause/Resume |
| M | Toggle mute |
| F | Fullscreen |

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
├── requirements.txt             # Python dependencies
│
├── videos/                      # Video files by slide (not in git)
│   ├── one-dance/
│   ├── lemonade/
│   └── ...
│
├── images/                      # Meme/reference images
└── background_images/           # Custom slide backgrounds (not in git)
```

## Database

SQLite database (`party.db`) with three tables:

- **submissions**: Guest memories and resolutions with approval status
- **admin_sessions**: Session tokens for admin authentication (12-hour expiry)
- **slideshow_state**: Current playback position and state

## How It Works

### Video Selection
1. Server scans `videos/{slide_id}/` on startup
2. Tracks play counts per video file
3. Returns least-played video for each request
4. Ensures even rotation across multiple videos

### Synchronization
1. Main slideshow display syncs position to server
2. Admin panel polls server every second
3. All connected displays stay within ~1 second sync

### Guest Flow
1. Guest opens `/guest` on their phone
2. Submits memory and resolution (name optional)
3. Submission stored as "pending"
4. Admin approves/rejects from admin panel
5. Approved submissions can appear in slideshow

## Troubleshooting

### Videos Not Playing
- Check codec compatibility (AV1 needs transcoding)
- Ensure file size > 1KB (corrupt files filtered)
- Check browser console for errors

### Slow Loading
- Images too large: Optimize to ~500-900KB before adding to `background_images/`
- CPU overloaded: Check for background transcoding

### Admin Login Issues
- Default password: `kaya`
- Set custom: `ADMIN_PASSWORD=yourpass uvicorn backend.server:app ...`
- Clear localStorage if token expired

## License

Private project for personal use.
