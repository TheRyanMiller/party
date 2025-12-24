#!/usr/bin/env python3
"""
Transcode AV1 videos to VP9 for better compatibility.
Run from project root: python3 scripts/transcode_av1_to_vp9.py
"""

import subprocess
import sys
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

VIDEOS_DIR = Path(__file__).parent.parent / "videos"

def get_codec(video_path: Path) -> str:
    """Get video codec using ffprobe."""
    result = subprocess.run(
        ['ffprobe', '-v', 'error', '-select_streams', 'v:0',
         '-show_entries', 'stream=codec_name', '-of', 'csv=p=0', str(video_path)],
        capture_output=True, text=True
    )
    return result.stdout.strip()

def transcode_to_vp9(input_path: Path) -> bool:
    """Transcode video to VP9. Returns True on success."""
    output_path = input_path.with_suffix('.vp9.mp4')

    print(f"  Transcoding: {input_path.name} -> {output_path.name}")

    # Use VP9 with good quality settings for fast encode
    result = subprocess.run([
        'ffmpeg', '-y', '-i', str(input_path),
        '-c:v', 'libvpx-vp9',
        '-crf', '30',  # Quality (lower = better, 30 is good balance)
        '-b:v', '0',   # Variable bitrate
        '-deadline', 'realtime',  # Fast encoding
        '-cpu-used', '4',  # Speed preset (0-8, higher = faster)
        '-c:a', 'libopus', '-b:a', '128k',  # Audio
        str(output_path)
    ], capture_output=True, text=True)

    if result.returncode == 0:
        # Rename: hide original with underscore, rename new to original name
        backup_path = input_path.parent / f"_av1_{input_path.name}"
        input_path.rename(backup_path)
        output_path.rename(input_path)
        print(f"  ✓ Done: {input_path.name}")
        return True
    else:
        print(f"  ✗ Failed: {input_path.name}")
        print(f"    Error: {result.stderr[:200]}")
        if output_path.exists():
            output_path.unlink()
        return False

def main():
    # Find all AV1-only slides
    av1_only_slides = []

    for slide_dir in sorted(VIDEOS_DIR.iterdir()):
        if not slide_dir.is_dir():
            continue

        av1_videos = []
        has_fallback = False

        for video in slide_dir.glob('*.mp4'):
            if video.name.startswith('_'):
                continue
            codec = get_codec(video)
            if codec == 'av1':
                av1_videos.append(video)
            elif codec in ('h264', 'vp9'):
                has_fallback = True

        if av1_videos and not has_fallback:
            av1_only_slides.append((slide_dir.name, av1_videos))

    print(f"\n{'='*60}")
    print(f"Found {len(av1_only_slides)} slides with AV1-only videos")
    print(f"{'='*60}\n")

    if not av1_only_slides:
        print("No AV1-only slides found. All slides have compatible videos!")
        return

    # Show what will be transcoded
    total_videos = sum(len(videos) for _, videos in av1_only_slides)
    print("Slides to process:")
    for slide_name, videos in av1_only_slides:
        print(f"  {slide_name}: {len(videos)} video(s)")

    print(f"\nTotal: {total_videos} videos to transcode")
    print("\nOptions:")
    print("  1. Transcode ONE video per slide (faster, ~20 videos)")
    print("  2. Transcode ALL AV1 videos (~42 videos)")
    print("  q. Quit")

    choice = input("\nChoice [1/2/q]: ").strip()

    if choice == 'q':
        print("Cancelled.")
        return

    transcode_all = (choice == '2')

    success = 0
    failed = 0

    for slide_name, videos in av1_only_slides:
        print(f"\n[{slide_name}]")
        videos_to_process = videos if transcode_all else videos[:1]

        for video in videos_to_process:
            if transcode_to_vp9(video):
                success += 1
            else:
                failed += 1

    print(f"\n{'='*60}")
    print(f"Complete! Success: {success}, Failed: {failed}")
    print(f"{'='*60}")

if __name__ == '__main__':
    main()
