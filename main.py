import os
import sys
import glob
import random
import asyncio
import argparse
from rtp_pacer import RawOpusTrack
from whip_client import WHIPClient
from cli_controller import CLIController

import ctypes

DEFAULT_WHIP_URL = "https://cn1.meshcast.io/whip/lsnn_radio"

def set_win_high_precision_timer(enable: bool):
    """
    Mengunci timer interrupt Windows ke akurasi 1ms untuk mencegah jitter/drift pacing 20ms.
    """
    if sys.platform == "win32":
        try:
            if enable:
                ctypes.windll.winmm.timeBeginPeriod(1)
            else:
                ctypes.windll.winmm.timeEndPeriod(1)
        except Exception:
            pass

def get_opus_playlist(music_dir: str, shuffle: bool = True) -> list[str]:
    pattern = os.path.join(music_dir, "*.opus")
    playlist = sorted(glob.glob(pattern))
    if shuffle and playlist:
        # Gunakan SystemRandom untuk entropi tinggi dari sistem operasi (1x shuffle sudah acak sempurna)
        rng = random.SystemRandom()
        rng.shuffle(playlist)
    return playlist

async def main():
    set_win_high_precision_timer(True)
    try:
        parser = argparse.ArgumentParser(description="Raw Opus WHIP Streamer & Pacer (Zero-CPU)")
        parser.add_argument("--url", default=DEFAULT_WHIP_URL, help="Target URL endpoint WHIP")
        parser.add_argument("--dir", default="..", help="Direktori lagu (.opus), default ke folder induk (..)")
        args = parser.parse_args()

        music_dir = os.path.abspath(args.dir)
        playlist = get_opus_playlist(music_dir)

        if not playlist:
            print(f"[Main Error] Tidak ditemukan file *.opus di direktori: {music_dir}")
            sys.exit(1)

        print(f"[Main] Ditemukan {len(playlist)} file lagu .opus di {music_dir}")
        
        # Inisialisasi Pacer Track
        track = RawOpusTrack(playlist)

        # Inisialisasi Klien WHIP
        whip_client = WHIPClient(args.url, track)

        try:
            # Koneksi ke Meshcast WHIP
            await whip_client.connect()
            
            # Jalankan Pengontrol CLI Interaktif
            cli = CLIController(track, whip_client, music_dir)
            await cli.run()

        except Exception as e:
            print(f"\n[Error Utama] {e}")
        finally:
            print("[Main] Menutup track dan koneksi WHIP...")
            track.stop()
            await whip_client.close()
            print("[Main] Selesai.")
    finally:
        set_win_high_precision_timer(False)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nDihentikan oleh pengguna.")
