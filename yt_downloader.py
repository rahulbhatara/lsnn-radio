import os
import sys
import asyncio
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

def sanitize_youtube_url(url: str) -> str:
    """
    Membersihkan URL YouTube dari parameter playlist (list=..., index=...)
    agar hanya mengunduh single video utama.
    """
    url = url.strip()
    try:
        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        # Jika ada parameter video ID ('v'), hapus parameter playlist
        if 'v' in query:
            for param in ['list', 'index', 'start_radio', 'playnext']:
                if param in query:
                    del query[param]
            new_query = urlencode(query, doseq=True)
            return urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, new_query, parsed.fragment))
    except Exception:
        pass
    return url

async def download_youtube_opus(url: str, output_dir: str = "..") -> str:
    """
    Mengunduh audio dari URL YouTube / YouTube Music menggunakan yt-dlp,
    meng-encode ke format standar Opus 48kHz 20ms, dan menyimpannya di output_dir.
    Mengembalikan path file .opus yang berhasil diunduh.
    """
    clean_url = sanitize_youtube_url(url)
    out_dir = os.path.abspath(output_dir)
    out_template = os.path.join(out_dir, "%(title)s.%(ext)s")

    cmd = [
        "yt-dlp",
        "--no-playlist",
        "--print", "after_move:filepath",
        "-x",
        "--audio-format", "opus",
        "--postprocessor-args", "ffmpeg:-c:a libopus -b:a 192k -ar 48000 -ac 2 -application audio -frame_duration 20",
        "-o", out_template,
        clean_url
    ]

    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )

    stdout, stderr = await process.communicate()

    if process.returncode != 0:
        err_msg = stderr.decode('utf-8', errors='ignore').strip()
        raise RuntimeError(f"Gagal mengunduh lagu YouTube: {err_msg}")

    output_path = stdout.decode('utf-8', errors='ignore').strip()
    
    # Ambil baris terakhir jika ada beberapa output line
    if "\n" in output_path:
        output_path = output_path.splitlines()[-1].strip()

    if not os.path.exists(output_path):
        raise FileNotFoundError(f"File hasil unduhan tidak ditemukan di path: {output_path}")

    return output_path
