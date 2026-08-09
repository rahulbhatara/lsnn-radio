import os
import sys
import glob
import random
import asyncio
import argparse
import ctypes

import qasync
from PySide6.QtWidgets import QApplication

from rtp_pacer import RawOpusTrack
from whip_client import WHIPClient
from hls_streamer import HLSStreamer
from cli_controller import CLIController
from gui_app import MainWindow
from service_manager import check_and_start_all_services, stop_all_services

DEFAULT_WHIP_URL = "https://cn1.meshcast.io/whip/lsnn_radio"
DEFAULT_PUBLIC_HLS_URL = "https://radio.samf.fun/live.m3u8"

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
        rng = random.SystemRandom()
        rng.shuffle(playlist)
    return playlist

async def main_async(args, app):
    set_win_high_precision_timer(True)
    try:
        music_dir = os.path.abspath(args.dir)
        playlist = get_opus_playlist(music_dir)

        if not playlist:
            print(f"[Main Error] Tidak ditemukan file *.opus di direktori: {music_dir}")
            sys.exit(1)

        print("[Main] Memeriksa dan mengaktifkan layanan Cloudflared...")
        check_and_start_all_services()

        print(f"[Main] Ditemukan {len(playlist)} file lagu .opus di {music_dir}")
        
        # Inisialisasi Pacer Track
        track = RawOpusTrack(playlist)

        # Inisialisasi Klien WHIP (MeshCast)
        whip_client = WHIPClient(args.url, track)

        # Inisialisasi HLS Streamer (fMP4 Opus Cloudflare CDN Engine)
        hls_streamer = HLSStreamer(
            host="127.0.0.1",
            port=args.hls_port,
            output_dir="hls_output",
            public_url=args.public_url
        )

        # Daftarkan listener paket ke HLS Streamer
        track.add_packet_listener(hls_streamer.enqueue_opus_frame)

        try:
            print("[Main] Menghubungkan Dual Stream (MeshCast & HLS CDN)...")
            await whip_client.connect()
            await hls_streamer.start()

            if args.tui or app is None:
                cli = CLIController(track, whip_client, hls_streamer, music_dir)
                await cli.run()
            else:
                window = MainWindow(track, whip_client, hls_streamer, music_dir)
                window.show()
                
                app_close_event = asyncio.Event()
                window.closed_signal.connect(app_close_event.set)
                await app_close_event.wait()

        except Exception as e:
            print(f"\n[Error Utama] {e}")
        finally:
            print("[Main] Menutup track dan koneksi Dual Stream...")
            track.stop()
            await whip_client.close()
            await hls_streamer.stop()
            stop_all_services()
            if app:
                app.quit()
            print("[Main] Selesai.")
    finally:
        set_win_high_precision_timer(False)

def main():
    parser = argparse.ArgumentParser(description="Raw Opus Dual Streamer (MeshCast WHIP & HLS Cloudflare CDN)")
    parser.add_argument("--url", default=DEFAULT_WHIP_URL, help="Target URL endpoint WHIP")
    parser.add_argument("--dir", default="..", help="Direktori lagu (.opus), default ke folder induk (..)")
    parser.add_argument("--public-url", default=DEFAULT_PUBLIC_HLS_URL, help="URL Publik HLS Cloudflare CDN")
    parser.add_argument("--hls-port", type=int, default=8000, help="Port lokal HTTP server HLS (default: 8000)")
    parser.add_argument("--tui", action="store_true", help="Jalankan dalam mode Terminal UI (TUI) tanpa GUI")
    args = parser.parse_args()

    if not args.tui:
        app = QApplication(sys.argv)
        app.setQuitOnLastWindowClosed(False)
        loop = qasync.QEventLoop(app)
        asyncio.set_event_loop(loop)
    else:
        app = None
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    try:
        with loop:
            loop.run_until_complete(main_async(args, app))
    except (RuntimeError, KeyboardInterrupt):
        pass

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nDihentikan oleh pengguna.")
        stop_all_services()
