#!/usr/bin/env python3
"""
NYE Party Project Setup Script

Initializes the project structure for a fresh clone:
1. Creates video directories for each slide in slideshow.yaml
2. Generates youtube_download_plan.yaml template with placeholder entries

Usage (from project root):
    python scripts/setup.py              # Full setup (dirs + download plan)
    python scripts/setup.py --dirs-only  # Only create directories
    python scripts/setup.py --dry-run    # Preview what would be created
"""

import argparse
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    print("Error: PyYAML is required. Install with: pip install pyyaml")
    sys.exit(1)


# Paths - scripts/ is one level below project root
PROJECT_ROOT = Path(__file__).parent.parent
SLIDESHOW_FILE = PROJECT_ROOT / "slideshow.yaml"
DOWNLOAD_PLAN_FILE = PROJECT_ROOT / "youtube_download_plan.yaml"
VIDEOS_DIR = PROJECT_ROOT / "videos"


def load_slideshow():
    """Load and parse slideshow.yaml"""
    if not SLIDESHOW_FILE.exists():
        print(f"Error: {SLIDESHOW_FILE} not found")
        sys.exit(1)

    with open(SLIDESHOW_FILE) as f:
        return yaml.safe_load(f)


def needs_video(slide: dict) -> bool:
    """
    Determine if a slide needs a video directory.

    Returns False for:
    - Slides with featuredImage (meme slides with static images)
    - Slides with video: false (explicitly disabled)
    - Slides with only background image and no video field
    """
    # Explicitly disabled
    if slide.get('video') is False:
        return False

    # Has featured image (meme-style slide) and no video config
    if 'featuredImage' in slide and 'video' not in slide:
        return False

    # Has background image but no video field (static image slide)
    bg = slide.get('background', {})
    if bg.get('type') == 'image' and 'video' not in slide:
        return False

    return True


def get_slides_needing_videos(slideshow: dict) -> list[str]:
    """Extract slide IDs that need video directories"""
    slides = slideshow.get('slides', [])
    return [s['id'] for s in slides if needs_video(s)]


def create_video_directories(slide_ids: list[str], dry_run: bool = False) -> int:
    """Create video directories for each slide ID"""
    created = 0

    for slide_id in slide_ids:
        video_dir = VIDEOS_DIR / slide_id
        if not video_dir.exists():
            if dry_run:
                print(f"  Would create: videos/{slide_id}/")
            else:
                video_dir.mkdir(parents=True, exist_ok=True)
                print(f"  Created: videos/{slide_id}/")
            created += 1
        else:
            print(f"  Exists: videos/{slide_id}/")

    return created


def load_existing_download_plan() -> dict:
    """Load existing download plan if it exists"""
    if DOWNLOAD_PLAN_FILE.exists():
        with open(DOWNLOAD_PLAN_FILE) as f:
            return yaml.safe_load(f) or {}
    return {}


def generate_download_plan(slide_ids: list[str], dry_run: bool = False) -> int:
    """Generate or update youtube_download_plan.yaml"""
    existing = load_existing_download_plan()

    # Preserve existing structure
    plan = {
        'defaults': existing.get('defaults', {
            'quality': 720,
            'format': 'mp4',
            'duration': 60
        }),
        'slides': existing.get('slides', {})
    }

    added = 0
    for slide_id in slide_ids:
        if slide_id not in plan['slides']:
            plan['slides'][slide_id] = {
                'videos': [
                    {
                        'url': '# TODO: Add YouTube URL',
                        'start': 0
                    }
                ]
            }
            added += 1
            if dry_run:
                print(f"  Would add entry: {slide_id}")
            else:
                print(f"  Added entry: {slide_id}")
        else:
            print(f"  Exists: {slide_id}")

    if not dry_run and added > 0:
        with open(DOWNLOAD_PLAN_FILE, 'w') as f:
            yaml.dump(plan, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
        print(f"\nUpdated {DOWNLOAD_PLAN_FILE}")

    return added


def main():
    parser = argparse.ArgumentParser(
        description="Initialize NYE Party project structure",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python setup.py              # Full setup
    python setup.py --dirs-only  # Only create video directories
    python setup.py --dry-run    # Preview changes without making them
        """
    )
    parser.add_argument(
        '--dirs-only',
        action='store_true',
        help='Only create video directories, skip download plan'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Preview what would be created without making changes'
    )
    args = parser.parse_args()

    print("=" * 50)
    print("NYE Party Project Setup")
    print("=" * 50)

    if args.dry_run:
        print("\n[DRY RUN - No changes will be made]\n")

    # Load slideshow config
    print("\nLoading slideshow.yaml...")
    slideshow = load_slideshow()

    # Get slides that need videos
    slide_ids = get_slides_needing_videos(slideshow)
    total_slides = len(slideshow.get('slides', []))

    print(f"Found {total_slides} total slides, {len(slide_ids)} need video directories")

    # Create video directories
    print(f"\n{'[Video Directories]':=^50}")
    dirs_created = create_video_directories(slide_ids, args.dry_run)
    print(f"\n{dirs_created} directories {'would be ' if args.dry_run else ''}created")

    # Generate download plan
    if not args.dirs_only:
        print(f"\n{'[Download Plan]':=^50}")
        entries_added = generate_download_plan(slide_ids, args.dry_run)
        print(f"\n{entries_added} entries {'would be ' if args.dry_run else ''}added")

    # Summary
    print(f"\n{'[Summary]':=^50}")
    if args.dry_run:
        print("Dry run complete. Run without --dry-run to apply changes.")
    else:
        print("Setup complete!")
        print("\nNext steps:")
        print("  1. Edit youtube_download_plan.yaml and add YouTube URLs")
        print("  2. Run: python scripts/download_videos.py")
        print("  3. Run: uvicorn backend.server:app --reload --port 8000")


if __name__ == "__main__":
    main()
