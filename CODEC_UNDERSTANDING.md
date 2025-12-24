NYE Slideshow – Codec Basics (Crash Course)
===========================================

What a codec is vs. file type
- Codec: the compression method for audio/video (e.g., H.264, VP9, AV1). Determines decode support and CPU/GPU requirements.
- Container/file type: the wrapper/extension (e.g., MP4, WebM, MOV). A container can hold many codecs. Browsers care about both; MP4 is common, but MP4 can still contain an unsupported codec like AV1.

Why browsers differ
- Chromium (Chrome/Brave/Edge): good VP9/H.264 support; AV1 is supported but can be flaky or fall back to software decode depending on GPU/drivers/flags.
- Safari: H.264 is solid; VP9 support arrived late and may be hardware-limited; AV1 largely unsupported.
- Bottom line: H.264 is safest; VP9 is widely ok on Chromium and newer Safari; AV1 is the riskiest.

Why we were seeing black videos
- Many source files were encoded as AV1. On some GPUs/driver combos, AV1 decode fails silently in Chromium, showing 1–2 frames then black. Our JS previously removed the video on error and never retried, leaving slides black.

Target codecs for reliability
- Primary: H.264 (best compatibility) or VP9 (good balance; works well in Chromium and modern Safari).
- Avoid: AV1 for this event; transcode any AV1 inputs to VP9 or H.264.

Download pipeline recommendations
- In yt-dlp, prefer H.264/VP9 and avoid AV1 (explicit format selection).
- Post-download: ffprobe the file; if codec is AV1, transcode immediately to VP9/H.264 and replace the original.

Key takeaways
- Codec ≠ container; MP4 can still hide an unsupported codec.
- AV1 is great for efficiency but unreliable across all event machines/browsers; convert to VP9/H.264.
- Add error/retry logic in the player so a single bad file doesn’t blank the slide.
