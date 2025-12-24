#!/usr/bin/env python3
"""
NYE 2016 Slideshow Video Server

A FastAPI server that manages video playback for the slideshow:
- Scans videos/ directory to build inventory
- Tracks play counts per video (persisted to JSON)
- Returns least-played video for each slide
- Serves static files (HTML, videos, images)

Usage (from project root):
    uvicorn backend.server:app --reload --port 8000
    # Then open http://localhost:8000/
"""

import json
import logging
import time
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Optional

import yaml
from fastapi import FastAPI, HTTPException, Header, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import database as db

# ============================================
# CONFIGURATION
# ============================================

# Project root is one level up from backend/
PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = PROJECT_ROOT / "data"

VIDEO_DIR = PROJECT_ROOT / "videos"
PLAY_COUNTS_FILE = DATA_DIR / "play_counts.json"
CONFIG_FILE = PROJECT_ROOT / "config.yaml"
UI_DIR = PROJECT_ROOT / "ui"

# App configuration (loaded from config.yaml)
app_config: dict = {}


def load_app_config() -> dict:
    """Load application configuration from config.yaml."""
    global app_config

    defaults = {
        "admin": {"password": "kaya"},
        "polling": {
            "slideshow_state": 2000,
            "admin_state": 2000,
            "admin_submissions": 5000
        },
        "video": {"api_timeout": 10000},
        "slideshow": {
            "default_duration": 30000,
            "transition_duration": 1200
        }
    }

    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE) as f:
                app_config = yaml.safe_load(f) or {}
                logger.info(f"Loaded config from {CONFIG_FILE}")
        except Exception as e:
            logger.error(f"Error loading config: {e}")
            app_config = {}
    else:
        app_config = {}
        logger.info("No config.yaml found, using defaults")

    # Merge with defaults (config values override defaults)
    def deep_merge(defaults, overrides):
        result = defaults.copy()
        for key, value in overrides.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = deep_merge(result[key], value)
            else:
                result[key] = value
        return result

    app_config = deep_merge(defaults, app_config)
    return app_config


def get_admin_password() -> str:
    """Get admin password from config."""
    return app_config.get("admin", {}).get("password", "kaya")

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger(__name__)

# ============================================
# APPLICATION STATE
# ============================================

# Video inventory: {slide_id: [video_path, ...]}
inventory: dict[str, list[str]] = {}

# Play counts: {video_path: count}
play_counts: dict[str, int] = {}

# Lock for thread-safe count updates
count_lock = Lock()

# Server start time for health check
start_time = datetime.now()

# Injected slides from approved guest submissions
# These slides get added to the slideshow when admin approves a submission
injected_slides: list[dict] = []
injected_slides_lock = Lock()  # Thread safety for concurrent access


def generate_slides_from_submission(submission: dict) -> tuple[dict, dict]:
    """
    Generate memory and resolution slide objects from a submission.

    Args:
        submission: Dict with id, guest_name, memory_2025, resolution_2026, reviewed_at

    Returns:
        Tuple of (memory_slide, resolution_slide) dicts
    """
    submission_id = submission["id"]
    guest_name = submission.get("guest_name") or "Anonymous"

    # Use reviewed_at timestamp for ordering, fallback to current time
    reviewed_at = submission.get("reviewed_at")
    if reviewed_at:
        # Convert ISO timestamp to milliseconds
        try:
            dt = datetime.fromisoformat(reviewed_at.replace('Z', '+00:00'))
            base_timestamp = int(dt.timestamp() * 1000)
        except:
            base_timestamp = int(time.time() * 1000)
    else:
        base_timestamp = int(time.time() * 1000)

    memory_slide = {
        "id": f"submission-{submission_id}-memory",
        "type": "guest-submission",
        "template": "memory",
        "text": submission["memory_2025"],
        "guestName": guest_name,
        "duration": 25000,
        "background": "/images/memories.png",
        "injectedAt": base_timestamp
    }

    resolution_slide = {
        "id": f"submission-{submission_id}-resolution",
        "type": "guest-submission",
        "template": "resolution",
        "text": submission["resolution_2026"],
        "guestName": guest_name,
        "duration": 25000,
        "background": "/images/resolutions.png",
        "injectedAt": base_timestamp + 1  # Slightly later so resolution comes after memory
    }

    return memory_slide, resolution_slide


def load_injected_slides_from_db():
    """
    Load all approved submissions and reconstruct the injected_slides list.
    Called on server startup to restore state from database.
    """
    global injected_slides

    # Get all approved submissions ordered by reviewed_at
    approved = db.get_approved_submissions()

    # Sort by reviewed_at to maintain original approval order
    approved_sorted = sorted(
        approved,
        key=lambda s: s.get("reviewed_at") or "9999"
    )

    new_slides = []
    for submission in approved_sorted:
        memory_slide, resolution_slide = generate_slides_from_submission(submission)
        new_slides.extend([memory_slide, resolution_slide])

    with injected_slides_lock:
        injected_slides = new_slides

    if new_slides:
        logger.info(f"Loaded {len(new_slides)} injected slides from {len(approved_sorted)} approved submissions")

# ============================================
# INVENTORY MANAGEMENT
# ============================================

def scan_videos() -> dict[str, list[str]]:
    """
    Scan the videos/ directory and build inventory.

    Structure expected:
        videos/
        ├── one-dance/
        │   ├── video1.mp4
        │   └── video2.mp4
        └── lemonade/
            └── video1.mp4

    Skips:
        - Incomplete downloads (.part files)
        - Hidden videos (prefix with "_" to hide without deleting)
        - Corrupt/empty files (< 1KB)

    Returns:
        Dict mapping slide_id to list of video paths
    """
    global inventory
    inventory = {}

    if not VIDEO_DIR.exists():
        logger.warning(f"Video directory not found: {VIDEO_DIR}")
        return inventory

    for slide_dir in sorted(VIDEO_DIR.iterdir()):
        if not slide_dir.is_dir():
            continue

        slide_id = slide_dir.name
        videos = []

        for video_file in sorted(slide_dir.iterdir()):
            # Only include .mp4 files, skip incomplete downloads and hidden files (prefix "_")
            if (video_file.suffix.lower() == ".mp4"
                and not video_file.name.endswith(".part")
                and not video_file.name.startswith("_")):
                # Check file is not empty/corrupt
                if video_file.stat().st_size > 1000:  # At least 1KB
                    # Store path relative to PROJECT_ROOT for use as URL
                    relative_path = video_file.relative_to(PROJECT_ROOT)
                    videos.append(str(relative_path))
                else:
                    logger.warning(f"Skipping small/corrupt file: {video_file}")

        inventory[slide_id] = videos

        if videos:
            logger.info(f"  {slide_id}: {len(videos)} videos")

    total = sum(len(v) for v in inventory.values())
    logger.info(f"Inventory loaded: {len(inventory)} slides, {total} videos")

    return inventory


def load_play_counts() -> dict[str, int]:
    """Load play counts from JSON file."""
    global play_counts

    if PLAY_COUNTS_FILE.exists():
        try:
            with open(PLAY_COUNTS_FILE) as f:
                data = json.load(f)
                play_counts = data.get("counts", {})
                logger.info(f"Loaded {len(play_counts)} play count entries")
        except (json.JSONDecodeError, IOError) as e:
            logger.error(f"Error loading play counts: {e}")
            play_counts = {}
    else:
        play_counts = {}
        logger.info("No existing play counts file, starting fresh")

    # Clean up counts for videos that no longer exist
    existing_videos = set()
    for videos in inventory.values():
        existing_videos.update(videos)

    removed = [v for v in play_counts if v not in existing_videos]
    for v in removed:
        del play_counts[v]

    if removed:
        logger.info(f"Cleaned up {len(removed)} stale play count entries")

    return play_counts


def save_play_counts():
    """Save play counts to JSON file atomically."""
    data = {
        "version": 1,
        "last_updated": datetime.utcnow().isoformat() + "Z",
        "counts": play_counts
    }

    # Write to temp file, then rename (atomic on POSIX)
    temp_file = PLAY_COUNTS_FILE.with_suffix(".tmp")
    try:
        with open(temp_file, "w") as f:
            json.dump(data, f, indent=2)
        temp_file.rename(PLAY_COUNTS_FILE)
    except IOError as e:
        logger.error(f"Error saving play counts: {e}")


# ============================================
# VIDEO SELECTION
# ============================================

def select_least_played(slide_id: str) -> Optional[str]:
    """
    Select the least-played video for a slide.

    If multiple videos have the same play count, returns the first
    alphabetically for determinism.

    Returns:
        Video path, or None if slide has no videos
    """
    videos = inventory.get(slide_id, [])
    if not videos:
        return None

    # Sort by (play_count, path) for determinism
    videos_with_counts = [(v, play_counts.get(v, 0)) for v in videos]
    videos_with_counts.sort(key=lambda x: (x[1], x[0]))

    return videos_with_counts[0][0]


def increment_play_count(video_path: str) -> int:
    """
    Increment play count for a video (thread-safe).

    Returns:
        New play count
    """
    with count_lock:
        play_counts[video_path] = play_counts.get(video_path, 0) + 1
        new_count = play_counts[video_path]
        save_play_counts()

    return new_count


# ============================================
# FASTAPI APPLICATION
# ============================================

app = FastAPI(
    title="NYE 2016 Video Server",
    description="Serves videos for the 2016 Year in Review slideshow",
    version="1.0.0"
)

# CORS middleware for development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup():
    """Initialize server on startup."""
    logger.info("=" * 50)
    logger.info("NYE 2016 Video Server starting...")
    logger.info("=" * 50)
    load_app_config()
    scan_videos()
    load_play_counts()
    load_injected_slides_from_db()  # Restore injected slides from approved submissions
    logger.info("Server ready!")


# ============================================
# API ENDPOINTS
# ============================================

@app.get("/api/video/{slide_id}")
async def get_video(slide_id: str):
    """
    Get the next video to play for a slide.

    Returns the least-played video from the slide's directory.
    If the slide has no videos, returns video_path: null.
    """
    video_path = select_least_played(slide_id)
    videos = inventory.get(slide_id, [])

    return {
        "slide_id": slide_id,
        "video_path": video_path,
        "video_count": len(videos),
        "play_count": play_counts.get(video_path, 0) if video_path else 0
    }


class PlayedRequest(BaseModel):
    video_path: Optional[str] = None


@app.post("/api/video/{slide_id}/played")
async def report_played(slide_id: str, request: PlayedRequest = None):
    """
    Report that a video started playing.

    If video_path is provided, increments that specific video's count.
    Otherwise falls back to incrementing the least-played video (legacy behavior).
    """
    # Get valid videos for this slide
    valid_videos = inventory.get(slide_id, [])

    # Determine which video to increment
    video_path = None
    if request and request.video_path:
        # Client specified the video - validate it belongs to this slide
        # Normalize path (remove leading slash if present)
        requested_path = request.video_path.lstrip('/')
        if requested_path in valid_videos:
            video_path = requested_path
        else:
            logger.warning(f"Invalid video_path for {slide_id}: {requested_path}")
            # Fall back to least-played
            video_path = select_least_played(slide_id)
    else:
        # Legacy: use least-played
        video_path = select_least_played(slide_id)

    if not video_path:
        # Not an error - slide may legitimately have no videos
        return {
            "slide_id": slide_id,
            "video_path": None,
            "new_play_count": 0
        }

    new_count = increment_play_count(video_path)
    logger.info(f"Play reported: {slide_id} -> {Path(video_path).name} (count: {new_count})")

    return {
        "slide_id": slide_id,
        "video_path": video_path,
        "new_play_count": new_count
    }


@app.get("/api/inventory")
async def get_inventory():
    """
    Get full video inventory with play counts (debug/admin endpoint).
    """
    slides_data = {}
    for slide_id, videos in sorted(inventory.items()):
        slides_data[slide_id] = [
            {
                "path": v,
                "filename": Path(v).name,
                "play_count": play_counts.get(v, 0)
            }
            for v in videos
        ]

    return {
        "slides": slides_data,
        "total_slides": len(inventory),
        "total_videos": sum(len(v) for v in inventory.values()),
        "total_plays": sum(play_counts.values())
    }


@app.post("/api/inventory/reload")
async def reload_inventory():
    """
    Reload video inventory from disk.

    Use this after adding new videos without restarting the server.
    """
    scan_videos()
    load_play_counts()

    return {
        "status": "reloaded",
        "total_slides": len(inventory),
        "total_videos": sum(len(v) for v in inventory.values())
    }


@app.get("/api/health")
async def health():
    """Health check endpoint."""
    uptime = (datetime.now() - start_time).total_seconds()

    return {
        "status": "ok",
        "uptime_seconds": int(uptime),
        "total_slides": len(inventory),
        "total_videos": sum(len(v) for v in inventory.values()),
        "total_plays": sum(play_counts.values())
    }


@app.get("/api/config")
async def get_config():
    """
    Get app configuration for frontend.
    Note: Sensitive values (like admin password) are excluded.
    """
    # Return safe config values only
    return {
        "polling": app_config.get("polling", {}),
        "video": app_config.get("video", {}),
        "slideshow": app_config.get("slideshow", {})
    }


# ============================================
# PYDANTIC MODELS
# ============================================

class LoginRequest(BaseModel):
    password: str


class SubmissionRequest(BaseModel):
    memory: str
    resolution: str
    guest_name: Optional[str] = None


class SlideshowControlRequest(BaseModel):
    action: str  # "pause", "resume", "next", "prev", "goto"
    slide_index: Optional[int] = None
    slide_id: Optional[str] = None


class SlideshowSyncRequest(BaseModel):
    slide_id: str
    slide_index: int
    slide_duration: Optional[int] = None
    slide_started_at: Optional[str] = None
    total_slides: Optional[int] = None  # Actual slide count including injected


# ============================================
# AUTH HELPERS
# ============================================

def get_admin_token(authorization: Optional[str] = Header(None)) -> Optional[str]:
    """Extract admin token from Authorization header."""
    if authorization and authorization.startswith("Bearer "):
        return authorization[7:]
    return None


def require_admin(authorization: Optional[str] = Header(None)):
    """Dependency that requires valid admin authentication."""
    token = get_admin_token(authorization)
    if not token or not db.validate_admin_session(token):
        raise HTTPException(status_code=401, detail="Unauthorized")
    return token


# ============================================
# ADMIN AUTH ENDPOINTS
# ============================================

@app.post("/api/admin/login")
async def admin_login(request: LoginRequest):
    """Admin login. Returns session token on success."""
    if request.password != get_admin_password():
        raise HTTPException(status_code=401, detail="Invalid password")

    token = db.create_admin_session()
    return {"token": token, "message": "Login successful"}


@app.post("/api/admin/logout")
async def admin_logout(token: str = Depends(require_admin)):
    """Admin logout. Invalidates session token."""
    db.delete_admin_session(token)
    return {"message": "Logged out"}


@app.get("/api/admin/verify")
async def admin_verify(token: str = Depends(require_admin)):
    """Verify admin session is valid."""
    return {"valid": True}


# ============================================
# GUEST SUBMISSION ENDPOINTS
# ============================================

@app.post("/api/submissions")
async def create_submission(request: SubmissionRequest):
    """Create a new guest submission."""
    if not request.memory.strip() or not request.resolution.strip():
        raise HTTPException(status_code=400, detail="Both fields are required")

    submission_id = db.create_submission(
        memory=request.memory.strip(),
        resolution=request.resolution.strip(),
        guest_name=request.guest_name.strip() if request.guest_name else None
    )

    logger.info(f"New submission #{submission_id} from {request.guest_name or 'Anonymous'}")
    return {"id": submission_id, "message": "Submission received!"}


@app.get("/api/submissions")
async def get_submissions(
    status: Optional[str] = None,
    token: str = Depends(require_admin)
):
    """Get submissions (admin only). Optionally filter by status."""
    submissions = db.get_submissions(status=status)
    counts = db.get_submission_counts()
    return {"submissions": submissions, "counts": counts}


@app.get("/api/submissions/approved")
async def get_approved_submissions():
    """Get approved submissions (public endpoint for slideshow)."""
    return {"submissions": db.get_approved_submissions()}


@app.put("/api/submissions/{submission_id}/approve")
async def approve_submission(submission_id: int, token: str = Depends(require_admin)):
    """Approve a submission and generate slideshow slides (admin only)."""
    # Get submission data before approving
    submission = db.get_submission_by_id(submission_id)
    if not submission:
        raise HTTPException(status_code=404, detail="Submission not found")

    if not db.approve_submission(submission_id):
        raise HTTPException(status_code=404, detail="Submission not found")

    # Re-fetch submission to get the updated reviewed_at timestamp
    updated_submission = db.get_submission_by_id(submission_id)

    # Generate slides using the shared function for consistency
    memory_slide, resolution_slide = generate_slides_from_submission(updated_submission)

    with injected_slides_lock:
        injected_slides.extend([memory_slide, resolution_slide])
        total = len(injected_slides)

    guest_name = updated_submission.get("guest_name") or "Anonymous"
    logger.info(f"Submission #{submission_id} approved - created 2 slides for {guest_name}")
    logger.info(f"Total injected slides now: {total}")

    return {"message": "Approved", "slides_created": 2}


@app.put("/api/submissions/{submission_id}/reject")
async def reject_submission(submission_id: int, token: str = Depends(require_admin)):
    """Reject a submission (admin only)."""
    if not db.reject_submission(submission_id):
        raise HTTPException(status_code=404, detail="Submission not found")
    logger.info(f"Submission #{submission_id} rejected")
    return {"message": "Rejected"}


@app.put("/api/submissions/{submission_id}/pending")
async def move_to_pending(submission_id: int, token: str = Depends(require_admin)):
    """Move a submission back to pending status (undo approve/reject)."""
    global injected_slides

    # Get current submission to check if it was approved
    submission = db.get_submission_by_id(submission_id)
    if not submission:
        raise HTTPException(status_code=404, detail="Submission not found")

    was_approved = submission.get("status") == "approved"

    # Update status to pending
    if not db.update_submission_status(submission_id, "pending"):
        raise HTTPException(status_code=404, detail="Submission not found")

    # Remove from injected_slides if it was approved
    slides_removed = 0
    if was_approved:
        memory_id = f"submission-{submission_id}-memory"
        resolution_id = f"submission-{submission_id}-resolution"
        with injected_slides_lock:
            original_len = len(injected_slides)
            injected_slides = [s for s in injected_slides if s["id"] not in (memory_id, resolution_id)]
            slides_removed = original_len - len(injected_slides)
        logger.info(f"Submission #{submission_id} moved to pending - removed {slides_removed} slides from slideshow")
    else:
        logger.info(f"Submission #{submission_id} moved to pending")

    return {"message": "Moved to pending", "slides_removed": slides_removed}


@app.delete("/api/submissions/{submission_id}")
async def delete_submission(submission_id: int, token: str = Depends(require_admin)):
    """Delete a submission completely (admin only)."""
    global injected_slides

    # Get submission to check status before deletion
    submission = db.get_submission_by_id(submission_id)
    if not submission:
        raise HTTPException(status_code=404, detail="Submission not found")

    was_approved = submission.get("status") == "approved"

    # Remove from injected_slides if it was approved
    slides_removed = 0
    if was_approved:
        memory_id = f"submission-{submission_id}-memory"
        resolution_id = f"submission-{submission_id}-resolution"
        with injected_slides_lock:
            original_len = len(injected_slides)
            injected_slides = [s for s in injected_slides if s["id"] not in (memory_id, resolution_id)]
            slides_removed = original_len - len(injected_slides)
        logger.info(f"Removed {slides_removed} slides for submission #{submission_id} from slideshow")

    # Delete from database
    if not db.delete_submission(submission_id):
        raise HTTPException(status_code=404, detail="Failed to delete submission")

    logger.info(f"Submission #{submission_id} deleted permanently")
    return {"message": "Deleted", "slides_removed": slides_removed}


# ============================================
# SLIDESHOW CONTROL ENDPOINTS
# ============================================

@app.get("/api/slideshow/state")
async def get_slideshow_state():
    """Get current slideshow state (public for syncing)."""
    return db.get_slideshow_state()


@app.post("/api/slideshow/control")
async def control_slideshow(
    request: SlideshowControlRequest,
    token: str = Depends(require_admin)
):
    """Control slideshow playback (admin only)."""
    action = request.action.lower()

    if action == "pause":
        state = db.set_paused(True)
        logger.info("Slideshow paused by admin")
    elif action == "resume":
        state = db.set_paused(False)
        logger.info("Slideshow resumed by admin")
    elif action == "goto" and request.slide_index is not None:
        state = db.set_current_slide(
            request.slide_id or "",
            request.slide_index
        )
        logger.info(f"Slideshow jumped to slide {request.slide_index}")
    elif action == "switch_video":
        state = db.request_video_switch()
        logger.info("Video switch requested by admin")
    else:
        raise HTTPException(status_code=400, detail=f"Unknown action: {action}")

    return state


@app.post("/api/slideshow/sync")
async def sync_slideshow_state(request: SlideshowSyncRequest):
    """
    Sync slideshow state from main display.
    Called by the slideshow to report current position and timer.
    """
    state = db.update_slideshow_state(
        current_slide=request.slide_id,
        current_slide_index=request.slide_index,
        slide_duration=request.slide_duration,
        slide_started_at=request.slide_started_at,
        total_slides=request.total_slides
    )
    return state


@app.post("/api/slideshow/video-switched")
async def video_switched():
    """
    Acknowledge that video switch has been handled.
    Called by the slideshow after switching videos.
    """
    state = db.clear_video_switch_request()
    return state


@app.post("/api/slideshow/hide/{slide_id}")
async def hide_slide(slide_id: str, admin: dict = Depends(require_admin)):
    """
    Hide a slide from the slideshow.
    Admin only - requires valid session token.
    """
    state = db.hide_slide(slide_id)
    logger.info(f"Slide hidden: {slide_id}")
    return state


@app.post("/api/slideshow/unhide/{slide_id}")
async def unhide_slide(slide_id: str, admin: dict = Depends(require_admin)):
    """
    Unhide a slide from the slideshow.
    Admin only - requires valid session token.
    """
    state = db.unhide_slide(slide_id)
    logger.info(f"Slide unhidden: {slide_id}")
    return state


@app.post("/api/slideshow/mute")
async def mute_slideshow(admin: dict = Depends(require_admin)):
    """
    Mute the slideshow.
    Admin only - requires valid session token.
    """
    state = db.set_muted(True)
    logger.info("Slideshow muted")
    return state


@app.post("/api/slideshow/unmute")
async def unmute_slideshow(admin: dict = Depends(require_admin)):
    """
    Unmute the slideshow.
    Admin only - requires valid session token.
    """
    state = db.set_muted(False)
    logger.info("Slideshow unmuted")
    return state


@app.get("/api/injected-slides")
async def get_injected_slides(since: int = 0):
    """
    Get slides injected from approved guest submissions.

    Args:
        since: Only return slides injected after this timestamp (ms since epoch)

    Returns:
        List of slide objects to inject into slideshow
    """
    with injected_slides_lock:
        # Use >= to avoid missing slides on exact timestamp match (Bug 5 fix)
        slides = [s for s in injected_slides if s["injectedAt"] >= since]
    return {"slides": slides}


@app.get("/api/slideshow/slides")
async def get_all_slides():
    """
    Get the complete slide list including injected slides from approved submissions.
    Uses the same insertion algorithm as the client to merge default and injected slides.

    Returns:
        List of all slides in playback order
    """
    # Load default slides from slideshow.yaml
    slideshow_file = PROJECT_ROOT / "slideshow.yaml"
    default_slides = []

    if slideshow_file.exists():
        try:
            with open(slideshow_file) as f:
                config = yaml.safe_load(f) or {}
                default_slides = config.get("slides", [])
        except Exception as e:
            logger.error(f"Error loading slideshow.yaml: {e}")

    # Copy injected slides while holding lock to minimize contention
    with injected_slides_lock:
        injected_copy = list(injected_slides)

    # If no injected slides, just return defaults
    if not injected_copy:
        return {
            "slides": default_slides,
            "total": len(default_slides),
            "injected_count": 0
        }

    # Merge injected slides using the same algorithm as client
    # Group injected slides into pairs (memory + resolution)
    pairs = []
    current_pair = []

    # Sort by injectedAt to maintain order
    sorted_injected = sorted(injected_copy, key=lambda s: s.get("injectedAt", 0))

    for slide in sorted_injected:
        current_pair.append(slide)
        if len(current_pair) == 2:
            pairs.append(current_pair)
            current_pair = []

    # If there's an orphan slide, add it as single-item pair
    if current_pair:
        pairs.append(current_pair)

    # Helper to check if slide is injected
    def is_injected(slide):
        return slide.get("type") == "guest-submission"

    # Insert pairs into merged list
    merged = list(default_slides)  # Start with copy of defaults

    for pair in pairs:
        # Find valid insertion position
        valid_positions = []
        for i in range(len(merged) + 1):
            before = merged[i - 1] if i > 0 else None
            after = merged[i] if i < len(merged) else None
            before_ok = not before or not is_injected(before)
            after_ok = not after or not is_injected(after)
            if before_ok and after_ok:
                valid_positions.append(i)

        if valid_positions:
            # Pick position closest to 1/3 through
            target = len(merged) // 3
            insert_pos = min(valid_positions, key=lambda p: abs(p - target))
        else:
            # Fallback to end
            insert_pos = len(merged)

        # Insert the pair
        for j, slide in enumerate(pair):
            merged.insert(insert_pos + j, slide)

    return {
        "slides": merged,
        "total": len(merged),
        "injected_count": len(injected_copy)
    }


# ============================================
# STATIC FILE SERVING
# ============================================

# Mount videos directory
if VIDEO_DIR.exists():
    app.mount("/videos", StaticFiles(directory=str(VIDEO_DIR)), name="videos")

# Mount images directory
images_dir = PROJECT_ROOT / "images"
if images_dir.exists():
    app.mount("/images", StaticFiles(directory=str(images_dir)), name="images")

# Mount background_images directory for slide backgrounds
backgrounds_dir = PROJECT_ROOT / "background_images"
if backgrounds_dir.exists():
    app.mount("/backgrounds", StaticFiles(directory=str(backgrounds_dir)), name="backgrounds")


@app.get("/api/backgrounds")
async def list_backgrounds():
    """List all images in the background_images directory."""
    pics = []
    if backgrounds_dir.exists():
        for f in backgrounds_dir.iterdir():
            if f.suffix.lower() in ('.jpg', '.jpeg', '.png', '.gif', '.webp'):
                pics.append(f"/backgrounds/{f.name}")
    return {"images": pics}


@app.get("/")
async def index():
    """Serve the main slideshow HTML."""
    html_file = UI_DIR / "2016-slideshow.html"
    if html_file.exists():
        return FileResponse(html_file)
    raise HTTPException(404, "Slideshow not found")


@app.get("/guest")
async def guest_page():
    """Serve the guest submission page."""
    html_file = UI_DIR / "guest.html"
    if html_file.exists():
        return FileResponse(html_file)
    raise HTTPException(404, "Guest page not found")


@app.get("/admin")
async def admin_page():
    """Serve the admin control panel."""
    html_file = UI_DIR / "admin.html"
    if html_file.exists():
        return FileResponse(html_file)
    raise HTTPException(404, "Admin page not found")


@app.get("/slideshow.yaml")
async def slideshow_config():
    """Serve the slideshow configuration."""
    yaml_file = PROJECT_ROOT / "slideshow.yaml"
    if yaml_file.exists():
        return FileResponse(yaml_file, media_type="text/yaml")
    raise HTTPException(404, "Config not found")


@app.get("/{filename:path}")
async def static_files(filename: str):
    """Serve other static files."""
    file_path = PROJECT_ROOT / filename

    # Security: prevent directory traversal
    try:
        file_path.resolve().relative_to(PROJECT_ROOT.resolve())
    except ValueError:
        raise HTTPException(403, "Access denied")

    if file_path.exists() and file_path.is_file():
        return FileResponse(file_path)

    raise HTTPException(404, f"File not found: {filename}")


# ============================================
# MAIN ENTRY POINT
# ============================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
