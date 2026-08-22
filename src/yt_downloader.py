import os
import sys
import shutil
import asyncio
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
import yt_dlp
from .convert_playlist import convert_audio_to_opus

def sanitize_youtube_url(url: str) -> str:
    """
    Cleans YouTube URL from playlist parameters to ensure single track download.
    """
    url = url.strip()
    try:
        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        if 'v' in query:
            for param in ['list', 'index', 'start_radio', 'playnext']:
                if param in query:
                    del query[param]
            new_query = urlencode(query, doseq=True)
            return urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, new_query, parsed.fragment))
    except Exception:
        pass
    return url

def _sync_download_youtube(url: str, output_dir: str) -> str:
    clean_url = sanitize_youtube_url(url)
    out_dir = os.path.abspath(output_dir)
    os.makedirs(out_dir, exist_ok=True)

    ffmpeg_available = shutil.which("ffmpeg") is not None

    if ffmpeg_available:
        # Full ffmpeg pipeline
        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': os.path.join(out_dir, '%(title)s.%(ext)s'),
            'noplaylist': True,
            'quiet': True,
            'no_warnings': True,
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'opus',
                'preferredquality': '192',
            }],
            'postprocessor_args': [
                '-ar', '48000',
                '-ac', '2',
                '-application', 'audio',
                '-frame_duration', '20'
            ]
        }
    else:
        # No ffmpeg on system: download raw audio then transcode via internal PyAV
        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': os.path.join(out_dir, '%(title)s.%(ext)s'),
            'noplaylist': True,
            'quiet': True,
            'no_warnings': True,
        }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(clean_url, download=True)
        title = info.get('title', 'downloaded_track')
        # Clean title for filename matching
        sanitized_title = ydl.prepare_filename(info)

    if ffmpeg_available:
        # File was converted to .opus by ffmpeg postprocessor
        base = os.path.splitext(sanitized_title)[0]
        final_opus = f"{base}.opus"
        if os.path.exists(final_opus):
            return final_opus
    else:
        # Convert downloaded audio to .opus via pure PyAV
        base = os.path.splitext(sanitized_title)[0]
        final_opus = f"{base}.opus"
        # Find the actual downloaded file on disk
        downloaded_file = None
        for ext in [".m4a", ".webm", ".opus", ".mp3", ".ogg", ".aac"]:
            candidate = f"{base}{ext}"
            if os.path.exists(candidate):
                downloaded_file = candidate
                break

        if not downloaded_file:
            # Fallback scan directory for recently modified file
            candidates = [os.path.join(out_dir, f) for f in os.listdir(out_dir)]
            if candidates:
                downloaded_file = max(candidates, key=os.path.getmtime)

        if downloaded_file and downloaded_file != final_opus:
            convert_audio_to_opus(downloaded_file, final_opus)
            try:
                os.remove(downloaded_file)
            except Exception:
                pass
            return final_opus
        elif os.path.exists(final_opus):
            return final_opus

    # Final check
    if os.path.exists(sanitized_title):
        return sanitized_title
    raise FileNotFoundError(f"Downloaded audio file could not be located in {out_dir}")

async def download_youtube_opus(url: str, output_dir: str = "..") -> str:
    """
    Downloads audio from YouTube URL and encodes to standard 48kHz 20ms Opus.
    Runs asynchronously in thread pool.
    """
    return await asyncio.to_thread(_sync_download_youtube, url, output_dir)
