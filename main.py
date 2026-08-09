import os
import sys
import glob
import random
import asyncio
import argparse

from rtp_pacer import RawOpusTrack
from whip_client import WHIPClient
from icecast_client import IcecastClient
from cli_controller import CLIController
from service_manager import check_and_start_all_services, stop_all_services

import ctypes

DEFAULT_WHIP_URL = "https://cn1.meshcast.io/whip/lsnn_radio"
DEFAULT_ICECAST_MOUNT = "/lsnn_radio"
DEFAULT_PUBLIC_ICECAST_URL = "https://radio.samf.fun/lsnn_radio"

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
        parser = argparse.ArgumentParser(description="Raw Opus Dual Streamer (MeshCast WHIP & Icecast2)")
        parser.add_argument("--url", default=DEFAULT_WHIP_URL, help="Target URL endpoint WHIP")
        parser.add_argument("--dir", default="..", help="Direktori lagu (.opus), default ke folder induk (..)")
        parser.add_argument("--icecast-mount", default=DEFAULT_ICECAST_MOUNT, help="Mount point Icecast (default: /lsnn_radio)")
        parser.add_argument("--icecast-pass", default="hackme", help="Password source Icecast (default: hackme)")
        parser.add_argument("--public-url", default=DEFAULT_PUBLIC_ICECAST_URL, help="URL Publik Icecast Tunnel")
        args = parser.parse_args()

        music_dir = os.path.abspath(args.dir)
        playlist = get_opus_playlist(music_dir)

        if not playlist:
            print(f"[Main Error] Tidak ditemukan file *.opus di direktori: {music_dir}")
            sys.exit(1)

        print("[Main] Memeriksa dan mengaktifkan layanan Icecast2 & Cloudflared...")
        check_and_start_all_services()

        print(f"[Main] Ditemukan {len(playlist)} file lagu .opus di {music_dir}")
        
        # Inisialisasi Pacer Track
        track = RawOpusTrack(playlist)

        # Inisialisasi Klien WHIP (MeshCast)
        whip_client = WHIPClient(args.url, track)

        # Inisialisasi Klien Icecast2 (Self-Hosted via Cloudflared)
        icecast_client = IcecastClient(
            host="127.0.0.1",
            port=8000,
            mount=args.icecast_mount,
            password=args.icecast_pass,
            public_url=args.public_url
        )

        # Daftarkan listener paket ke Icecast
        track.add_packet_listener(icecast_client.enqueue_opus_frame)

        try:
            # Koneksi ke Meshcast WHIP & Icecast2 secara simultan
            print("[Main] Menghubungkan Dual Stream (MeshCast & Icecast2)...")
            await whip_client.connect()
            await icecast_client.connect()
            
            # Jalankan Pengontrol CLI Interaktif Dual Stream
            cli = CLIController(track, whip_client, icecast_client, music_dir)
            await cli.run()

        except Exception as e:
            print(f"\n[Error Utama] {e}")
        finally:
            print("[Main] Menutup track dan koneksi Dual Stream...")
            track.stop()
            await whip_client.close()
            await icecast_client.close()
            stop_all_services()
            print("[Main] Selesai.")
    finally:
        set_win_high_precision_timer(False)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nDihentikan oleh pengguna.")
        stop_all_services()


