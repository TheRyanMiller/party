#!/usr/bin/env python3
"""
Download videos for NYE 2016 slideshow based on youtube_download_plan.yaml

Usage (from project root):
    python scripts/download_videos.py                    # Download all videos
    python scripts/download_videos.py --slide one-dance # Download specific slide only
    python scripts/download_videos.py --dry-run          # Show what would be downloaded
    python scripts/download_videos.py --retry-errors     # Retry previously failed downloads
    python scripts/download_videos.py --reset            # Clear all status fields and start fresh

Status tracking:
    The script updates youtube_download_plan.yaml with download status:
    - status: pending     (not yet attempted)
    - status: completed   (successfully downloaded)
    - status: error       (failed - see 'error' field for reason)
"""

import json
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import yaml


# Project root is one level up from scripts/
PROJECT_ROOT = Path(__file__).parent.parent


# ============================================
# TERMINAL & PROGRESS BAR UTILITIES
# ============================================

class Colors:
    """ANSI color codes for terminal output."""
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    RED = "\033[31m"
    CYAN = "\033[36m"
    MAGENTA = "\033[35m"

    @classmethod
    def enabled(cls) -> bool:
        """Check if terminal supports colors."""
        return hasattr(sys.stdout, 'isatty') and sys.stdout.isatty()

    @classmethod
    def colorize(cls, text: str, color: str) -> str:
        """Apply color to text if supported."""
        if cls.enabled():
            return f"{color}{text}{cls.RESET}"
        return text


def get_terminal_width() -> int:
    """Get terminal width, default to 80."""
    try:
        return shutil.get_terminal_size().columns
    except Exception:
        return 80


def parse_yt_dlp_progress(line: str) -> dict | None:
    """
    Parse yt-dlp progress line.

    Examples:
        [download]  45.2% of 10.50MiB at  2.30MiB/s ETA 00:05
        [download]  45.2% of ~10.50MiB at  2.30MiB/s ETA 00:05
        [download] 100% of 10.50MiB in 00:05
    """
    # Standard progress with ETA
    match = re.search(
        r'\[download\]\s+(\d+\.?\d*)%\s+of\s+~?([\d.]+\s*\w+)\s+at\s+([\d.]+\s*\w+/s)(?:\s+ETA\s+(\S+))?',
        line
    )
    if match:
        return {
            'percent': float(match.group(1)),
            'size': match.group(2).strip(),
            'speed': match.group(3).strip(),
            'eta': match.group(4) if match.group(4) else '00:00',
        }

    # Completed download (100% of X in Y)
    match = re.search(
        r'\[download\]\s+100%\s+of\s+~?([\d.]+\s*\w+)(?:\s+in\s+(\S+))?',
        line
    )
    if match:
        return {
            'percent': 100.0,
            'size': match.group(1).strip(),
            'speed': 'Done',
            'eta': match.group(2) if match.group(2) else '00:00',
        }

    # Already downloaded
    if '[download]' in line and 'already been downloaded' in line.lower():
        return {
            'percent': 100.0,
            'size': '-',
            'speed': 'Cached',
            'eta': '00:00',
        }

    return None


def format_progress_bar(percent: float, width: int = 25) -> str:
    """Create a Unicode progress bar."""
    filled = int(width * percent / 100)
    remainder = (width * percent / 100) - filled

    # Use partial block characters for smoother progress
    blocks = ['', '▏', '▎', '▍', '▌', '▋', '▊', '▉', '█']

    bar = '█' * filled
    if filled < width:
        partial_idx = int(remainder * 8)
        bar += blocks[partial_idx]
        bar += '░' * (width - filled - 1)

    if Colors.enabled():
        # Color gradient: red -> yellow -> green based on progress
        if percent < 33:
            color = Colors.RED
        elif percent < 66:
            color = Colors.YELLOW
        else:
            color = Colors.GREEN
        return f"{color}{bar}{Colors.RESET}"

    return bar


def print_progress(progress: dict, prefix: str = ""):
    """Print progress bar that overwrites the current line."""
    terminal_width = get_terminal_width()

    bar = format_progress_bar(progress['percent'])
    percent_str = f"{progress['percent']:5.1f}%"

    # Format components
    size_str = progress['size']
    speed_str = progress['speed']
    eta_str = progress['eta']

    # Build the progress line
    if Colors.enabled():
        line = f"     {bar} {Colors.BOLD}{percent_str}{Colors.RESET}"
        line += f" {Colors.DIM}│{Colors.RESET} {size_str}"
        line += f" {Colors.DIM}│{Colors.RESET} {Colors.CYAN}{speed_str}{Colors.RESET}"
        if eta_str and eta_str != '00:00':
            line += f" {Colors.DIM}│{Colors.RESET} ETA: {eta_str}"
    else:
        line = f"     [{bar}] {percent_str} | {size_str} | {speed_str}"
        if eta_str and eta_str != '00:00':
            line += f" | ETA: {eta_str}"

    # Calculate visible length (without ANSI codes) for padding
    visible_line = re.sub(r'\033\[[0-9;]*m', '', line)
    padding = max(0, terminal_width - len(visible_line) - 1)

    sys.stdout.write(f"\r{line}{' ' * padding}")
    sys.stdout.flush()


def clear_progress_line():
    """Clear the current progress line."""
    terminal_width = get_terminal_width()
    sys.stdout.write(f"\r{' ' * (terminal_width - 1)}\r")
    sys.stdout.flush()


# Status constants
STATUS_PENDING = "pending"
STATUS_COMPLETED = "completed"
STATUS_ERROR = "error"


# ============================================
# VIDEO DURATION & TIME VALIDATION
# ============================================

def get_video_duration(url: str) -> float | None:
    """
    Get video duration in seconds using yt-dlp.
    Returns None if duration cannot be determined (live stream, API error, etc.).
    """
    try:
        result = subprocess.run(
            ["yt-dlp", "--dump-json", "--no-download", "--no-warnings", url],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            data = json.loads(result.stdout)
            duration = data.get("duration")
            if duration:
                return float(duration)
    except subprocess.TimeoutExpired:
        pass
    except json.JSONDecodeError:
        pass
    except Exception:
        pass
    return None


def validate_time_range(
    start: int | None,
    end: int | None,
    actual_duration: float,
    default_clip_duration: int = 60,
) -> tuple[int | None, int | None, list[str]]:
    """
    Validate and adjust time range based on actual video duration.

    Handles edge cases:
    - start >= actual_duration: Reset start to 0
    - end > actual_duration: Cap end at actual_duration
    - start >= end after adjustments: Download full video

    Returns (adjusted_start, adjusted_end, list_of_warnings)
    """
    if actual_duration <= 0:
        return start, end, []

    warnings = []
    adjusted_start = start
    adjusted_end = end
    actual_int = int(actual_duration)

    # If only start is specified, calculate end
    if start is not None and end is None:
        adjusted_end = start + default_clip_duration

    # If start is at or beyond video duration, reset to beginning
    if adjusted_start is not None and adjusted_start >= actual_duration:
        warnings.append(f"start {adjusted_start}s >= video length {actual_int}s → using 0s")
        adjusted_start = 0

    # If end is beyond video duration, cap at duration
    if adjusted_end is not None and adjusted_end > actual_duration:
        warnings.append(f"end {adjusted_end}s > video length {actual_int}s → capped to {actual_int}s")
        adjusted_end = actual_int

    # If start >= end after adjustments, download full video
    if adjusted_start is not None and adjusted_end is not None:
        if adjusted_start >= adjusted_end:
            warnings.append(f"start >= end after adjustment → downloading full video (0-{actual_int}s)")
            adjusted_start = 0
            adjusted_end = actual_int

    return adjusted_start, adjusted_end, warnings


def load_download_plan(plan_file: Path) -> dict:
    """Load the youtube download plan from YAML file."""
    with open(plan_file) as f:
        return yaml.safe_load(f)


def save_download_plan(plan_file: Path, plan: dict) -> None:
    """Save the download plan back to YAML file."""
    with open(plan_file, "w") as f:
        yaml.dump(plan, f, default_flow_style=False, sort_keys=False, allow_unicode=True)


def get_youtube_url(video_id: str) -> str:
    """Convert video ID or URL to full YouTube URL."""
    if video_id.startswith("http"):
        return video_id
    return f"https://www.youtube.com/watch?v={video_id}"


def extract_video_id(url: str) -> str:
    """Extract YouTube video ID from URL or return as-is if already an ID."""
    if "/" not in url and "." not in url:
        return url
    if "youtu.be/" in url:
        return url.split("youtu.be/")[1].split("?")[0]
    if "v=" in url:
        return url.split("v=")[1].split("&")[0]
    return url


def build_filename(
    video: dict,
    defaults: dict,
    start_override: int | None = None,
    end_override: int | None = None,
) -> tuple[str, str, str]:
    """
    Build filename that includes YouTube video ID and time range.
    Returns (filename_without_ext, video_id, time_suffix).

    Format: {custom_name}_{video_id}_{start}-{end}.mp4
    Examples:
        - url: v7MGUNV8MxU, start: 0, end: 60       -> v7MGUNV8MxU_0-60
        - url: uxpDa-c-4Mc, filename: drake, start: 10, end: 70 -> drake_uxpDa-c-4Mc_10-70
        - url: abc123 (no times)                     -> abc123_full

    If start_override/end_override are provided, they are used instead of video config.
    """
    url = video.get("url", "")
    video_id = extract_video_id(url)
    custom_name = video.get("filename")

    # Use overrides if provided, otherwise use video config
    start = start_override if start_override is not None else video.get("start")
    end = end_override if end_override is not None else video.get("end")
    duration = defaults.get("duration", 60)

    if start is not None and end is not None:
        time_suffix = f"{start}-{end}"
    elif start is not None:
        time_suffix = f"{start}-{start + duration}"
    else:
        time_suffix = "full"

    # Build filename with video ID and time range
    if custom_name:
        filename = f"{custom_name}_{video_id}_{time_suffix}"
    else:
        filename = f"{video_id}_{time_suffix}"

    return filename, video_id, time_suffix


def find_existing_video(output_dir: Path, slide_id: str, filename: str) -> Path | None:
    """
    Check if a video with this exact filename (including time range) exists.
    Matches by the full filename prefix (before extension).
    """
    slide_dir = output_dir / slide_id
    if not slide_dir.exists():
        return None

    for file in slide_dir.iterdir():
        if file.stem == filename:
            return file
    return None


def parse_yt_dlp_error(stderr: str) -> str:
    """Extract a human-readable error message from yt-dlp stderr."""
    stderr_lower = stderr.lower()

    if "video unavailable" in stderr_lower:
        return "Video unavailable"
    if "private video" in stderr_lower:
        return "Private video"
    if "removed by the uploader" in stderr_lower:
        return "Removed by uploader"
    if "copyright" in stderr_lower:
        return "Copyright claim"
    if "age-restricted" in stderr_lower:
        return "Age-restricted"
    if "sign in" in stderr_lower:
        return "Sign-in required"
    if "geo" in stderr_lower or "country" in stderr_lower:
        return "Geo-restricted"
    if "404" in stderr or "not found" in stderr_lower:
        return "Not found (404)"
    if "403" in stderr:
        return "Forbidden (403)"
    if "no video formats" in stderr_lower:
        return "No video formats available"
    if "unable to download" in stderr_lower:
        return "Unable to download"

    # Return first 100 chars of stderr if no pattern matched
    first_line = stderr.strip().split("\n")[0][:100]
    return first_line if first_line else "Unknown error"


def download_video(
    slide_id: str,
    video: dict,
    defaults: dict,
    output_dir: Path,
    dry_run: bool = False,
) -> tuple[str, str | None, str | None, dict | None]:
    """
    Download a single video using yt-dlp.

    Returns:
        (status, error_message, downloaded_filename, metadata_updates)
        metadata_updates contains any fields to add to the YAML (e.g., time_adjusted)
    """
    url = video.get("url")
    if not url:
        return STATUS_ERROR, "No URL specified", None, None

    youtube_url = get_youtube_url(url)
    video_id = extract_video_id(url)
    default_duration = defaults.get("duration", 60)

    # Get original requested times
    original_start = video.get("start")
    original_end = video.get("end")

    # Use original times initially
    adjusted_start = original_start
    adjusted_end = original_end
    time_warnings = []

    # Get video duration for time validation (skip for dry run to save time)
    if not dry_run and (original_start is not None or original_end is not None):
        if Colors.enabled():
            print(f"  {Colors.DIM}⏱  Checking video duration...{Colors.RESET}", end="", flush=True)
        else:
            print(f"  ⏱  Checking video duration...", end="", flush=True)

        video_duration = get_video_duration(youtube_url)

        if video_duration:
            # Clear the "checking" message
            print(f"\r{' ' * 40}\r", end="", flush=True)

            # Validate and adjust time range
            adjusted_start, adjusted_end, time_warnings = validate_time_range(
                original_start, original_end, video_duration, default_duration
            )
        else:
            print(f" {Colors.YELLOW}unknown{Colors.RESET}" if Colors.enabled() else " unknown")

    # Build filename with (possibly adjusted) times
    filename, _, time_suffix = build_filename(video, defaults, adjusted_start, adjusted_end)

    # Build yt-dlp command
    quality = defaults.get("quality", 720)
    output_path = output_dir / slide_id / f"{filename}.%(ext)s"

    cmd = [
        "yt-dlp",
        "-f", f"bestvideo[height<={quality}]+bestaudio/best[height<={quality}]",
        "--merge-output-format", "mp4",
        "-o", str(output_path),
        "--no-playlist",
        "--no-warnings",
    ]

    # Add time range if specified (use adjusted values)
    if adjusted_start is not None and adjusted_end is not None:
        cmd.extend(["--download-sections", f"*{adjusted_start}-{adjusted_end}"])
    elif adjusted_start is not None:
        cmd.extend(["--download-sections", f"*{adjusted_start}-{adjusted_start + default_duration}"])

    cmd.append(youtube_url)

    # Print video info
    if Colors.enabled():
        print(f"  {Colors.CYAN}📥 {filename}{Colors.RESET}")
        print(f"     {Colors.DIM}Video ID:{Colors.RESET} {video_id}")
        if adjusted_start is not None:
            end_display = adjusted_end if adjusted_end else adjusted_start + default_duration
            print(f"     {Colors.DIM}Time:{Colors.RESET}     {adjusted_start}s - {end_display}s")
    else:
        print(f"  📥 {filename}")
        print(f"     Video ID: {video_id}")
        if adjusted_start is not None:
            end_display = adjusted_end if adjusted_end else adjusted_start + default_duration
            print(f"     Time:     {adjusted_start}s - {end_display}s")

    # Print any time adjustment warnings
    for warning in time_warnings:
        if Colors.enabled():
            print(f"     {Colors.YELLOW}⚠️  {warning}{Colors.RESET}")
        else:
            print(f"     ⚠️  {warning}")

    # Check if file already exists (by full filename with time range)
    existing = find_existing_video(output_dir, slide_id, filename)
    if existing:
        if Colors.enabled():
            print(f"     {Colors.GREEN}✓ Already exists:{Colors.RESET} {existing.name}")
        else:
            print(f"     ✓ Already exists: {existing.name}")
        return STATUS_COMPLETED, None, existing.name, None

    if dry_run:
        if Colors.enabled():
            print(f"     {Colors.DIM}[DRY RUN] Would download{Colors.RESET}")
        else:
            print(f"     [DRY RUN] Would download")
        return STATUS_PENDING, None, None, None

    # Create output directory
    (output_dir / slide_id).mkdir(parents=True, exist_ok=True)

    # Prepare metadata updates if times were adjusted
    metadata_updates = None
    if time_warnings:
        metadata_updates = {
            "time_adjusted": "; ".join(time_warnings),
        }
        # Also update the actual times used
        if adjusted_start != original_start:
            metadata_updates["actual_start"] = adjusted_start
        if adjusted_end != original_end:
            metadata_updates["actual_end"] = adjusted_end

    # Add flags for better progress output
    cmd_with_progress = cmd + ["--newline", "--progress"]

    # Run yt-dlp with streaming output for progress display
    try:
        process = subprocess.Popen(
            cmd_with_progress,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,  # Line buffered
        )

        error_lines = []
        had_progress = False
        last_progress = None

        # Stream output line by line
        for line in iter(process.stdout.readline, ''):
            line = line.rstrip()
            if not line:
                continue

            # Try to parse as progress
            progress = parse_yt_dlp_progress(line)
            if progress:
                print_progress(progress)
                had_progress = True
                last_progress = progress
            elif '[error]' in line.lower() or 'error:' in line.lower():
                error_lines.append(line)
            elif '[download]' in line and 'Destination:' in line:
                # Show destination but don't clutter
                pass

        # Wait for process to complete
        return_code = process.wait()

        # Clear progress line if we showed progress
        if had_progress:
            clear_progress_line()

        if return_code == 0:
            # Find the downloaded file
            downloaded = find_existing_video(output_dir, slide_id, filename)
            downloaded_name = downloaded.name if downloaded else f"{filename}.mp4"

            # Show success with size info
            size_info = last_progress['size'] if last_progress else ''
            if Colors.enabled():
                print(f"     {Colors.GREEN}✓ Downloaded:{Colors.RESET} {downloaded_name} {Colors.DIM}({size_info}){Colors.RESET}")
            else:
                print(f"     ✓ Downloaded: {downloaded_name} ({size_info})")

            return STATUS_COMPLETED, None, downloaded_name, metadata_updates
        else:
            # Parse error from collected error lines or use generic message
            if error_lines:
                error_msg = parse_yt_dlp_error('\n'.join(error_lines))
            else:
                error_msg = f"Exit code {return_code}"

            if Colors.enabled():
                print(f"     {Colors.RED}✗ Failed:{Colors.RESET} {error_msg}")
            else:
                print(f"     ✗ Failed: {error_msg}")
            return STATUS_ERROR, error_msg, None, metadata_updates

    except subprocess.TimeoutExpired:
        process.kill()
        clear_progress_line()
        if Colors.enabled():
            print(f"     {Colors.RED}✗ Timeout after 5 minutes{Colors.RESET}")
        else:
            print(f"     ✗ Timeout after 5 minutes")
        return STATUS_ERROR, "Timeout (5 minutes)", None, None
    except FileNotFoundError:
        if Colors.enabled():
            print(f"     {Colors.RED}✗ yt-dlp not found - is it installed?{Colors.RESET}")
        else:
            print(f"     ✗ yt-dlp not found - is it installed?")
        return STATUS_ERROR, "yt-dlp not found", None, None
    except Exception as e:
        clear_progress_line()
        if Colors.enabled():
            print(f"     {Colors.RED}✗ Error:{Colors.RESET} {e}")
        else:
            print(f"     ✗ Error: {e}")
        return STATUS_ERROR, str(e)[:100], None, None


def reset_all_status(plan: dict) -> int:
    """Remove all status/error/downloaded_file/time_adjusted fields. Returns count of reset videos."""
    count = 0
    for slide_config in plan.get("slides", {}).values():
        # Handle malformed entries where videos list is directly under slide
        videos = slide_config if isinstance(slide_config, list) else slide_config.get("videos", [])
        for video in videos:
            if "status" in video:
                del video["status"]
                count += 1
            if "error" in video:
                del video["error"]
            if "downloaded_file" in video:
                del video["downloaded_file"]
            if "time_adjusted" in video:
                del video["time_adjusted"]
            if "actual_start" in video:
                del video["actual_start"]
            if "actual_end" in video:
                del video["actual_end"]
    return count


def get_status_summary(plan: dict) -> dict:
    """Get counts of each status type."""
    summary = {STATUS_PENDING: 0, STATUS_COMPLETED: 0, STATUS_ERROR: 0}
    for slide_config in plan.get("slides", {}).values():
        # Handle malformed entries where videos list is directly under slide
        if isinstance(slide_config, list):
            videos = slide_config
        else:
            videos = slide_config.get("videos", [])
        for video in videos:
            status = video.get("status", STATUS_PENDING)
            summary[status] = summary.get(status, 0) + 1
    return summary


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Download videos for NYE slideshow",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples (from project root):
  python scripts/download_videos.py                    # Download pending videos
  python scripts/download_videos.py --dry-run          # Preview without downloading
  python scripts/download_videos.py --slide one-dance  # Download one slide only
  python scripts/download_videos.py --retry-errors     # Retry failed downloads
  python scripts/download_videos.py --reset            # Clear all status and start fresh
        """
    )
    parser.add_argument("--slide", help="Download only this slide")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be downloaded")
    parser.add_argument("--retry-errors", action="store_true", help="Retry videos with error status")
    parser.add_argument("--reset", action="store_true", help="Clear all status fields and start fresh")
    parser.add_argument("--plan", default=None, help="Path to download plan (default: youtube_download_plan.yaml in project root)")
    parser.add_argument("--output", default=None, help="Output directory (default: videos/ in project root)")
    args = parser.parse_args()

    plan_file = Path(args.plan) if args.plan else PROJECT_ROOT / "youtube_download_plan.yaml"
    output_dir = Path(args.output) if args.output else PROJECT_ROOT / "videos"

    if not plan_file.exists():
        print(f"❌ Download plan not found: {plan_file}")
        sys.exit(1)

    plan = load_download_plan(plan_file)
    defaults = plan.get("defaults", {})
    all_slides = plan.get("slides", {})

    # Handle --reset flag
    if args.reset:
        reset_count = reset_all_status(plan)
        save_download_plan(plan_file, plan)
        print(f"🔄 Reset status for {reset_count} videos")
        print(f"   Plan saved: {plan_file}")
        return

    # Show current status summary
    summary = get_status_summary(plan)

    # Professional header
    print()
    if Colors.enabled():
        print(f"{Colors.BOLD}🎬 NYE 2016 Video Downloader{Colors.RESET}")
        print(f"{Colors.DIM}{'─' * 50}{Colors.RESET}")
        print(f"   {Colors.DIM}Plan:{Colors.RESET}   {plan_file}")
        print(f"   {Colors.DIM}Output:{Colors.RESET} {output_dir}")
        status_line = f"   {Colors.DIM}Status:{Colors.RESET} "
        status_line += f"{Colors.GREEN}{summary[STATUS_COMPLETED]} completed{Colors.RESET}, "
        status_line += f"{Colors.RED}{summary[STATUS_ERROR]} errors{Colors.RESET}, "
        status_line += f"{Colors.YELLOW}{summary[STATUS_PENDING]} pending{Colors.RESET}"
        print(status_line)
        if args.dry_run:
            print(f"   {Colors.DIM}Mode:{Colors.RESET}   {Colors.MAGENTA}DRY RUN (no changes saved){Colors.RESET}")
        if args.retry_errors:
            print(f"   {Colors.DIM}Mode:{Colors.RESET}   {Colors.YELLOW}RETRY ERRORS{Colors.RESET}")
        print(f"{Colors.DIM}{'─' * 50}{Colors.RESET}")
    else:
        print("🎬 NYE 2016 Video Downloader")
        print("-" * 50)
        print(f"   Plan:   {plan_file}")
        print(f"   Output: {output_dir}")
        print(f"   Status: {summary[STATUS_COMPLETED]} completed, {summary[STATUS_ERROR]} errors, {summary[STATUS_PENDING]} pending")
        if args.dry_run:
            print(f"   Mode:   DRY RUN (no changes saved)")
        if args.retry_errors:
            print(f"   Mode:   RETRY ERRORS")
        print("-" * 50)
    print()

    # Filter to specific slide if requested
    if args.slide:
        if args.slide not in all_slides:
            print(f"❌ Slide not found: {args.slide}")
            print(f"   Available slides: {', '.join(all_slides.keys())}")
            sys.exit(1)
        slides_to_process = {args.slide: all_slides[args.slide]}
    else:
        slides_to_process = all_slides

    total_videos = 0
    successful = 0
    failed = 0
    skipped = 0
    pending = 0  # For dry run - videos that would be downloaded

    for slide_id, slide_config in slides_to_process.items():
        # Handle malformed entries where videos list is directly under slide
        videos = slide_config if isinstance(slide_config, list) else slide_config.get("videos", [])
        if Colors.enabled():
            print(f"{Colors.BOLD}📂 {slide_id}{Colors.RESET} {Colors.DIM}({len(videos)} videos){Colors.RESET}")
        else:
            print(f"📂 {slide_id} ({len(videos)} videos)")

        for video in videos:
            # Skip entries without URLs (placeholders for future videos)
            if not video.get("url"):
                continue

            total_videos += 1
            current_status = video.get("status", STATUS_PENDING)

            # Skip completed videos
            if current_status == STATUS_COMPLETED:
                filename, video_id, _ = build_filename(video, defaults)
                if Colors.enabled():
                    print(f"  {Colors.DIM}⏭ {filename}{Colors.RESET}")
                    print(f"     {Colors.DIM}Already completed{Colors.RESET}")
                else:
                    print(f"  ⏭ {filename}")
                    print(f"     Already completed")
                skipped += 1
                continue

            # Skip errors unless --retry-errors
            if current_status == STATUS_ERROR and not args.retry_errors:
                filename, video_id, _ = build_filename(video, defaults)
                error_msg = video.get('error', 'Unknown')
                if Colors.enabled():
                    print(f"  {Colors.DIM}⏭ {filename}{Colors.RESET}")
                    print(f"     {Colors.RED}Previous error:{Colors.RESET} {Colors.DIM}{error_msg}{Colors.RESET}")
                else:
                    print(f"  ⏭ {filename}")
                    print(f"     Previous error: {error_msg}")
                skipped += 1
                continue

            # Attempt download
            status, error, downloaded_file, metadata_updates = download_video(
                slide_id, video, defaults, output_dir, args.dry_run
            )

            # Update video entry (unless dry run)
            if not args.dry_run:
                video["status"] = status
                if error:
                    video["error"] = error
                elif "error" in video:
                    del video["error"]  # Clear previous error on success
                if downloaded_file:
                    video["downloaded_file"] = downloaded_file

                # Apply any metadata updates (e.g., time_adjusted info)
                if metadata_updates:
                    for key, value in metadata_updates.items():
                        video[key] = value

                # Save after each video for resilience
                save_download_plan(plan_file, plan)

            # Count results
            if status == STATUS_COMPLETED:
                successful += 1
            elif status == STATUS_ERROR:
                failed += 1
            elif status == STATUS_PENDING:
                pending += 1  # Dry run - would be downloaded

        print()

    # Final summary
    print()
    if Colors.enabled():
        print(f"{Colors.DIM}{'═' * 50}{Colors.RESET}")
        if args.dry_run:
            print(f"{Colors.BOLD}📊 Dry Run Summary{Colors.RESET}")
        else:
            print(f"{Colors.BOLD}📊 Download Summary{Colors.RESET}")
        print(f"{Colors.DIM}{'─' * 50}{Colors.RESET}")
        if args.dry_run:
            print(f"   {Colors.CYAN}⬇ Would download:{Colors.RESET} {pending}")
        else:
            print(f"   {Colors.GREEN}✓ Successful:{Colors.RESET}    {successful}")
        print(f"   {Colors.DIM}⏭ Skipped:{Colors.RESET}       {skipped}")
        if failed:
            print(f"   {Colors.RED}✗ Failed:{Colors.RESET}        {failed}")
        print(f"   {Colors.DIM}Total:{Colors.RESET}           {total_videos}")
        print(f"{Colors.DIM}{'═' * 50}{Colors.RESET}")
    else:
        print("=" * 50)
        if args.dry_run:
            print("📊 Dry Run Summary")
        else:
            print("📊 Download Summary")
        print("-" * 50)
        if args.dry_run:
            print(f"   ⬇ Would download: {pending}")
        else:
            print(f"   ✓ Successful:    {successful}")
        print(f"   ⏭ Skipped:       {skipped}")
        if failed:
            print(f"   ✗ Failed:        {failed}")
        print(f"   Total:           {total_videos}")
        print("=" * 50)

    if not args.dry_run:
        final_summary = get_status_summary(plan)
        print()
        if Colors.enabled():
            print(f"{Colors.DIM}📋 Status saved to {plan_file}:{Colors.RESET}")
            print(f"   {Colors.GREEN}Completed:{Colors.RESET} {final_summary[STATUS_COMPLETED]}")
            print(f"   {Colors.RED}Errors:{Colors.RESET}    {final_summary[STATUS_ERROR]}")
            print(f"   {Colors.YELLOW}Pending:{Colors.RESET}   {final_summary[STATUS_PENDING]}")
        else:
            print(f"📋 Status saved to {plan_file}:")
            print(f"   Completed: {final_summary[STATUS_COMPLETED]}")
            print(f"   Errors:    {final_summary[STATUS_ERROR]}")
            print(f"   Pending:   {final_summary[STATUS_PENDING]}")


if __name__ == "__main__":
    main()
