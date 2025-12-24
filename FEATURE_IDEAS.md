NYE Party Slideshow – Playback Investigation Plan
------------------------------------------------

Context: videos sometimes show 1–2 frames then go black. Playback in Brave (Chromium-based) and quality should be preserved.

Verification steps
- Reproduce in Brave while `chrome://media-internals` is open; note decoder/profile and any pipeline errors for the failing MP4 URL.
- Drag the failing MP4 from `videos/...` into Brave directly to see if it fails outside the slideshow.
- Inspect the file with `ffprobe -v error -show_entries stream=codec_name,bit_rate,duration -of default=noprint_wrappers=1:nokey=1 <file>` to confirm codec/bitrate.
- If standalone playback is fine, open DevTools on the slideshow; check console and Network for video errors, and try `video.play()`/mute toggles to rule out policy issues.

Mitigations after evidence
- If media-internals shows AV1 decode trouble, transcode only those AV1 files to VP9 or high-bitrate H.264 (e.g., VP9 `-crf 18 -b:v 0 -row-mt 1` or H.264 `-crf 18 -preset slow`) to avoid quality loss.
- If a file is corrupt, re-download/replace it.
- If the slideshow path is at fault, add a fallback in the JS video error handler to request the next video or YouTube so a bad file doesn’t leave the slide black.
