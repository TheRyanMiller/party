#!/usr/bin/env python3
"""
Database module for NYE Party Slideshow.

Manages SQLite database for:
- Guest submissions (memories and resolutions)
- Admin sessions
- Slideshow state
"""

import json
import sqlite3
import secrets
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
from contextlib import contextmanager

# Project root is one level up from backend/
PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = PROJECT_ROOT / "data"
DATABASE_FILE = DATA_DIR / "party.db"

# Admin password from environment or default
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "kaya")


@contextmanager
def get_db():
    """Context manager for database connections."""
    conn = sqlite3.connect(DATABASE_FILE)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    """Initialize database tables."""
    with get_db() as conn:
        cursor = conn.cursor()

        # Guest submissions table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS submissions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guest_name TEXT,
                memory_2025 TEXT NOT NULL,
                resolution_2026 TEXT NOT NULL,
                status TEXT DEFAULT 'pending',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                reviewed_at TEXT
            )
        """)

        # Admin sessions table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS admin_sessions (
                token TEXT PRIMARY KEY,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                expires_at TEXT NOT NULL
            )
        """)

        # Slideshow state table (single row)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS slideshow_state (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                is_paused INTEGER DEFAULT 0,
                current_slide TEXT DEFAULT '',
                current_slide_index INTEGER DEFAULT 0,
                slide_duration INTEGER DEFAULT 30000,
                slide_started_at TEXT DEFAULT CURRENT_TIMESTAMP,
                last_updated TEXT DEFAULT CURRENT_TIMESTAMP,
                request_video_switch INTEGER DEFAULT 0
            )
        """)

        # Initialize slideshow state if not exists
        cursor.execute("""
            INSERT OR IGNORE INTO slideshow_state (id, is_paused, current_slide, current_slide_index)
            VALUES (1, 0, '', 0)
        """)

        # Migration: Add request_video_switch column if it doesn't exist
        cursor.execute("PRAGMA table_info(slideshow_state)")
        columns = [row[1] for row in cursor.fetchall()]
        if 'request_video_switch' not in columns:
            cursor.execute("ALTER TABLE slideshow_state ADD COLUMN request_video_switch INTEGER DEFAULT 0")
            # Refresh columns list after adding new column
            cursor.execute("PRAGMA table_info(slideshow_state)")
            columns = [row[1] for row in cursor.fetchall()]

        # Migration: Add total_slides column if it doesn't exist
        if 'total_slides' not in columns:
            cursor.execute("ALTER TABLE slideshow_state ADD COLUMN total_slides INTEGER DEFAULT 0")
            cursor.execute("PRAGMA table_info(slideshow_state)")
            columns = [row[1] for row in cursor.fetchall()]

        # Migration: Add hidden_slides column if it doesn't exist (stores JSON array of slide IDs)
        if 'hidden_slides' not in columns:
            cursor.execute("ALTER TABLE slideshow_state ADD COLUMN hidden_slides TEXT DEFAULT '[]'")
            cursor.execute("PRAGMA table_info(slideshow_state)")
            columns = [row[1] for row in cursor.fetchall()]

        # Migration: Add is_muted column if it doesn't exist
        if 'is_muted' not in columns:
            cursor.execute("ALTER TABLE slideshow_state ADD COLUMN is_muted INTEGER DEFAULT 1")

        conn.commit()


# ============================================
# SUBMISSIONS
# ============================================

def create_submission(memory: str, resolution: str, guest_name: Optional[str] = None) -> int:
    """Create a new guest submission. Returns the submission ID."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """INSERT INTO submissions (guest_name, memory_2025, resolution_2026, status, created_at)
               VALUES (?, ?, ?, 'pending', ?)""",
            (guest_name, memory, resolution, datetime.utcnow().isoformat())
        )
        return cursor.lastrowid


def get_submissions(status: Optional[str] = None) -> list[dict]:
    """Get submissions, optionally filtered by status."""
    with get_db() as conn:
        cursor = conn.cursor()
        if status:
            cursor.execute(
                "SELECT * FROM submissions WHERE status = ? ORDER BY created_at DESC",
                (status,)
            )
        else:
            cursor.execute("SELECT * FROM submissions ORDER BY created_at DESC")
        return [dict(row) for row in cursor.fetchall()]


def get_submission_by_id(submission_id: int) -> Optional[dict]:
    """Get a single submission by ID."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM submissions WHERE id = ?", (submission_id,))
        row = cursor.fetchone()
        return dict(row) if row else None


def get_pending_submissions() -> list[dict]:
    """Get all pending submissions."""
    return get_submissions(status="pending")


def get_approved_submissions() -> list[dict]:
    """Get all approved submissions."""
    return get_submissions(status="approved")


def update_submission_status(submission_id: int, status: str) -> bool:
    """Update a submission's status. Returns True if found and updated."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """UPDATE submissions
               SET status = ?, reviewed_at = ?
               WHERE id = ?""",
            (status, datetime.utcnow().isoformat(), submission_id)
        )
        return cursor.rowcount > 0


def approve_submission(submission_id: int) -> bool:
    """Approve a submission."""
    return update_submission_status(submission_id, "approved")


def reject_submission(submission_id: int) -> bool:
    """Reject a submission."""
    return update_submission_status(submission_id, "rejected")


def delete_submission(submission_id: int) -> bool:
    """Delete a submission permanently. Returns True if found and deleted."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM submissions WHERE id = ?", (submission_id,))
        return cursor.rowcount > 0


def get_submission_counts() -> dict:
    """Get counts of submissions by status."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT status, COUNT(*) as count
            FROM submissions
            GROUP BY status
        """)
        counts = {"pending": 0, "approved": 0, "rejected": 0}
        for row in cursor.fetchall():
            counts[row["status"]] = row["count"]
        return counts


# ============================================
# ADMIN SESSIONS
# ============================================

def create_admin_session() -> str:
    """Create a new admin session. Returns the session token."""
    token = secrets.token_urlsafe(32)
    expires_at = (datetime.utcnow() + timedelta(hours=12)).isoformat()

    with get_db() as conn:
        cursor = conn.cursor()
        # Clean up expired sessions
        cursor.execute(
            "DELETE FROM admin_sessions WHERE expires_at < ?",
            (datetime.utcnow().isoformat(),)
        )
        # Create new session
        cursor.execute(
            "INSERT INTO admin_sessions (token, expires_at) VALUES (?, ?)",
            (token, expires_at)
        )

    return token


def validate_admin_session(token: str) -> bool:
    """Check if an admin session token is valid."""
    if not token:
        return False

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """SELECT token FROM admin_sessions
               WHERE token = ? AND expires_at > ?""",
            (token, datetime.utcnow().isoformat())
        )
        return cursor.fetchone() is not None


def delete_admin_session(token: str) -> bool:
    """Delete an admin session (logout). Returns True if session existed."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM admin_sessions WHERE token = ?", (token,))
        return cursor.rowcount > 0


def verify_admin_password(password: str) -> bool:
    """Verify admin password."""
    return password == ADMIN_PASSWORD


# ============================================
# SLIDESHOW STATE
# ============================================

def get_slideshow_state() -> dict:
    """Get current slideshow state."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM slideshow_state WHERE id = 1")
        row = cursor.fetchone()
        if row:
            keys = row.keys()
            # Parse hidden_slides from JSON
            hidden_slides_raw = row["hidden_slides"] if "hidden_slides" in keys else "[]"
            try:
                hidden_slides = json.loads(hidden_slides_raw) if hidden_slides_raw else []
            except (json.JSONDecodeError, TypeError):
                hidden_slides = []

            return {
                "is_paused": bool(row["is_paused"]),
                "current_slide": row["current_slide"],
                "current_slide_index": row["current_slide_index"],
                "slide_duration": row["slide_duration"] if "slide_duration" in keys else 30000,
                "slide_started_at": row["slide_started_at"] if "slide_started_at" in keys else None,
                "last_updated": row["last_updated"],
                "request_video_switch": bool(row["request_video_switch"]) if "request_video_switch" in keys else False,
                "total_slides": row["total_slides"] if "total_slides" in keys else 0,
                "hidden_slides": hidden_slides,
                "is_muted": bool(row["is_muted"]) if "is_muted" in keys else True
            }
        return {"is_paused": False, "current_slide": "", "current_slide_index": 0, "slide_duration": 30000, "slide_started_at": None, "request_video_switch": False, "total_slides": 0, "hidden_slides": [], "is_muted": True}


def update_slideshow_state(
    is_paused: Optional[bool] = None,
    current_slide: Optional[str] = None,
    current_slide_index: Optional[int] = None,
    slide_duration: Optional[int] = None,
    slide_started_at: Optional[str] = None,
    request_video_switch: Optional[bool] = None,
    total_slides: Optional[int] = None,
    is_muted: Optional[bool] = None
) -> dict:
    """Update slideshow state. Only updates provided fields."""
    with get_db() as conn:
        cursor = conn.cursor()

        # Build dynamic update
        updates = []
        params = []

        if is_paused is not None:
            updates.append("is_paused = ?")
            params.append(1 if is_paused else 0)

        if current_slide is not None:
            updates.append("current_slide = ?")
            params.append(current_slide)

        if current_slide_index is not None:
            updates.append("current_slide_index = ?")
            params.append(current_slide_index)

        if slide_duration is not None:
            updates.append("slide_duration = ?")
            params.append(slide_duration)

        if slide_started_at is not None:
            updates.append("slide_started_at = ?")
            params.append(slide_started_at)

        if request_video_switch is not None:
            updates.append("request_video_switch = ?")
            params.append(1 if request_video_switch else 0)

        if total_slides is not None:
            updates.append("total_slides = ?")
            params.append(total_slides)

        if is_muted is not None:
            updates.append("is_muted = ?")
            params.append(1 if is_muted else 0)

        if updates:
            updates.append("last_updated = ?")
            params.append(datetime.utcnow().isoformat())

            query = f"UPDATE slideshow_state SET {', '.join(updates)} WHERE id = 1"
            cursor.execute(query, params)

    return get_slideshow_state()


def set_paused(paused: bool) -> dict:
    """Set slideshow paused state."""
    return update_slideshow_state(is_paused=paused)


def set_current_slide(slide_id: str, index: int) -> dict:
    """Set current slide."""
    return update_slideshow_state(current_slide=slide_id, current_slide_index=index)


def request_video_switch() -> dict:
    """Request the slideshow to switch to the next video."""
    return update_slideshow_state(request_video_switch=True)


def clear_video_switch_request() -> dict:
    """Clear the video switch request (called by slideshow after handling)."""
    return update_slideshow_state(request_video_switch=False)


def set_muted(muted: bool) -> dict:
    """Set slideshow mute state."""
    return update_slideshow_state(is_muted=muted)


def get_hidden_slides() -> list:
    """Get list of hidden slide IDs."""
    state = get_slideshow_state()
    return state.get("hidden_slides", [])


def hide_slide(slide_id: str) -> dict:
    """Hide a slide from the slideshow."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT hidden_slides FROM slideshow_state WHERE id = 1")
        row = cursor.fetchone()

        try:
            hidden = json.loads(row["hidden_slides"]) if row and row["hidden_slides"] else []
        except (json.JSONDecodeError, TypeError):
            hidden = []

        if slide_id not in hidden:
            hidden.append(slide_id)
            cursor.execute(
                "UPDATE slideshow_state SET hidden_slides = ?, last_updated = ? WHERE id = 1",
                (json.dumps(hidden), datetime.utcnow().isoformat())
            )

    return get_slideshow_state()


def unhide_slide(slide_id: str) -> dict:
    """Unhide a slide from the slideshow."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT hidden_slides FROM slideshow_state WHERE id = 1")
        row = cursor.fetchone()

        try:
            hidden = json.loads(row["hidden_slides"]) if row and row["hidden_slides"] else []
        except (json.JSONDecodeError, TypeError):
            hidden = []

        if slide_id in hidden:
            hidden.remove(slide_id)
            cursor.execute(
                "UPDATE slideshow_state SET hidden_slides = ?, last_updated = ? WHERE id = 1",
                (json.dumps(hidden), datetime.utcnow().isoformat())
            )

    return get_slideshow_state()


# Initialize database on import
init_db()
