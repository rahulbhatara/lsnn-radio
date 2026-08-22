import os
import sys
import glob
import random
import asyncio
import argparse
import ctypes

import qasync
from PySide6.QtWidgets import QApplication

from src.config import AppConfig
from src.rtp_pacer import RawOpusTrack
from src.whip_client import WHIPClient
from src.hls_streamer import HLSStreamer
from src.gui import MainWindow
from src.service_manager import start_cloudflared_tunnel, stop_all_services

def set_win_high_precision_timer(enable: bool):
    """
    Lock Windows timer interrupt to 1ms accuracy to prevent 20ms pacing jitter/drift.
    """
    if sys.platform == "win32":
        try:
            if enable:
                ctypes.windll.winmm.timeBeginPeriod(1)
            else:
                ctypes.windll.winmm.timeEndPeriod(1)
        except Exception:
            pass

async def main_async(cfg: AppConfig, app: QApplication):
    set_win_high_precision_timer(True)
    whip_client = None
    hls_streamer = None
    track = None
    try:
        music_dir = os.path.abspath(cfg.music_dir)
        os.makedirs(music_dir, exist_ok=True)

        # 1. Initialize pacer engine & track (fast, no blocking disk/network)
        track = RawOpusTrack([])
        whip_client = WHIPClient(cfg.whip_url, track)
        hls_streamer = HLSStreamer(
            host="127.0.0.1",
            port=cfg.hls_port,
            output_dir="hls_output",
            public_url=cfg.public_hls_url
        )
        track.add_packet_listener(hls_streamer.enqueue_opus_frame)

        # 2. Show GUI instantly (<100ms)
        window = MainWindow(track, whip_client, hls_streamer, cfg, music_dir)
        window.show()
        window.log_event("[Main] GUI ready")

        # 3. Run background initialization without blocking GUI
        async def run_startup_sequence():
            try:
                # A. Scan playlist files in thread pool
                window.log_event(f"[Main] Scanning {music_dir}...")
                new_added, total = await asyncio.to_thread(track.refresh_playlist, music_dir)
                window._populate_all_tables()
                window._check_non_opus_files()
                if total > 0:
                    window.log_event(f"[Main] Found {total} .opus files")
                else:
                    window.log_event(f"[Main] No .opus files in {music_dir}")

                # B. Start HLS Local Server
                try:
                    await hls_streamer.start()
                    window.log_event(f"[HLS] Server active on port {hls_streamer.port}")
                except Exception as e:
                    window.log_event(f"[HLS] Start failed: {e}")

                # C. Check and start Cloudflared tunnel
                if cfg.tunnel_mode != "none":
                    window.log_event(f"[Tunnel] Starting Cloudflare {cfg.tunnel_mode.capitalize()} Tunnel...")
                    res = await asyncio.to_thread(
                        start_cloudflared_tunnel,
                        mode=cfg.tunnel_mode,
                        local_port=hls_streamer.port,
                        config_path=cfg.cloudflared_config_path,
                        tunnel_id=cfg.cloudflared_tunnel_id
                    )
                    status = res.get("status")
                    if status == "connected":
                        quick_url = res.get("url")
                        if quick_url:
                            hls_streamer.public_url = f"{quick_url}/live.m3u8"
                            window.log_event(f"[Tunnel] Cloudflared connected: {hls_streamer.public_url}")
                        else:
                            window.log_event(f"[Tunnel] Cloudflared connected: {cfg.public_hls_url}")
                    elif status == "not_installed":
                        window.log_event("[Tunnel] Cloudflared binary not found (running Local HLS only)")
                    else:
                        window.log_event(f"[Tunnel] Cloudflared status: {status}")

                # D. Connect WHIP WebRTC
                window.log_event(f"[WHIP] Connecting to {cfg.whip_url}...")
                try:
                    await whip_client.connect()
                    window.log_event("[WHIP] WebRTC connected")
                except Exception as e:
                    window.log_event(f"[WHIP] Connection failed: {e}")

            except Exception as e:
                window.log_event(f"[Startup] Error: {e}")

        # Launch background startup task in Qt event loop
        startup_task = asyncio.create_task(run_startup_sequence())

        app_close_event = asyncio.Event()
        window.closed_signal.connect(app_close_event.set)
        await app_close_event.wait()

        if not startup_task.done():
            startup_task.cancel()
            try:
                await startup_task
            except asyncio.CancelledError:
                pass

    except Exception as e:
        print(f"\n[Fatal] {e}")
    finally:
        print("[Main] Shutting down...")
        if 'startup_task' in locals() and not startup_task.done():
            startup_task.cancel()
        if track:
            track.stop()
        if whip_client:
            await whip_client.close()
        if hls_streamer:
            await hls_streamer.stop()
        stop_all_services()
        set_win_high_precision_timer(False)
        if app:
            app.quit()
        print("[Main] Done.")

def main():
    cfg = AppConfig.load()

    parser = argparse.ArgumentParser(description="MeshCast Dual Streamer")
    parser.add_argument("--url", default=None, help="WHIP endpoint URL")
    parser.add_argument("--dir", default=None, help="Music directory (.opus files)")
    parser.add_argument("--public-url", default=None, help="Public HLS CDN URL")
    parser.add_argument("--hls-port", type=int, default=None, help="Local HLS HTTP server port")
    parser.add_argument("--tunnel", choices=["quick", "custom", "none"], default=None, help="Cloudflare tunnel mode")
    args = parser.parse_args()

    # CLI args override config if explicitly supplied
    if args.url:
        cfg.whip_url = args.url
    if args.dir:
        cfg.music_dir = args.dir
    if args.public_url:
        cfg.public_hls_url = args.public_url
    if args.hls_port:
        cfg.hls_port = args.hls_port
    if args.tunnel:
        cfg.tunnel_mode = args.tunnel

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    loop = qasync.QEventLoop(app)
    asyncio.set_event_loop(loop)

    try:
        with loop:
            loop.run_until_complete(main_async(cfg, app))
    except (RuntimeError, KeyboardInterrupt):
        pass

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrupted.")
        stop_all_services()
