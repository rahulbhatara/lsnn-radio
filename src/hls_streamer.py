import os
import re
import time
import html
import shutil
import asyncio
import fractions
from typing import Dict, Any, Optional
from collections import deque
import av
from aiohttp import web

# Whitelist nama file segmen yang valid: init.mp4 / xxx.m4s / xxx.mp4.
# Mencegah path traversal & arbitrary file read via HTTP.
_SAFE_SEGMENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-]*\.(?:m4s|mp4)$")

class HLSStreamer:
    """
    Zero-CPU HLS Streamer (fMP4 Opus) dengan HTTP Server internal & CORS/Cache Rules.
    Menghasilkan playlist HLS statis & segmen .m4s yang 100% kompatibel di-cache Cloudflare Edge CDN.
    """
    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 8000,
        output_dir: str = "hls_output",
        public_url: str = "https://radio.samf.fun/live.m3u8",
        icecast_server=None
    ):
        self.host = host
        self.port = port
        self.output_dir = os.path.abspath(output_dir)
        self.public_url = public_url
        # Relay AAC/Icecast-native opsional; route "/live" di-mount di app yang sama
        # agar tetap terjangkau oleh Cloudflare tunnel (tunnel menunjuk ke port ini).
        self.icecast_server = icecast_server
        
        self.m3u8_file = os.path.join(self.output_dir, "live.m3u8")
        self.container: Optional[av.container.OutputContainer] = None
        self.audio_stream = None
        self._pts = 0

        self.packet_queue: Optional[asyncio.Queue] = None
        self.mux_task: Optional[asyncio.Task] = None
        self.runner: Optional[web.AppRunner] = None
        self.site: Optional[web.TCPSite] = None
        self.is_running = False

        # Statistics & Telemetry
        self.start_time = time.monotonic()
        self.segments_created = 0
        self.total_bytes_served = 0
        self.http_requests_count = 0
        self._sliding_bytes = deque(maxlen=1000)  # (timestamp, byte_len)
        self._m3u8_cache: Optional[str] = None
        self._m3u8_mtime: float = 0.0
        self.init_filename: Optional[str] = None

    def _prepare_output_dir(self):
        if os.path.exists(self.output_dir):
            try:
                shutil.rmtree(self.output_dir)
            except Exception:
                pass
        os.makedirs(self.output_dir, exist_ok=True)

    def _init_pyav_hls(self):
        self._prepare_output_dir()
        
        # Inisialisasi PyAV HLS Muxer (2-second fMP4 segments with auto-cleanup)
        # Gunakan epoch timestamp sebagai start_number & init filename agar URL segmen unik tiap sesi,
        # mencegah Cloudflare CDN / Browser menyajikan cache segmen lama dari sesi sebelumnya.
        session_id = int(time.time())
        self.init_filename = f"init_{session_id}.mp4"
        self.container = av.open(
            self.m3u8_file,
            mode="w",
            format="hls",
            options={
                "hls_time": "2",
                "hls_list_size": "5",
                "hls_segment_type": "fmp4",
                "hls_flags": "delete_segments+omit_endlist",
                "start_number": str(session_id),
                "hls_fmp4_init_filename": self.init_filename,
            }
        )
        self.audio_stream = self.container.add_stream("opus", rate=48000)
        self._pts = 0

    async def start(self) -> bool:
        print(f"[HLS] Starting HLS Segmenter Engine & HTTP Server (base port: {self.port})...")
        try:
            self._init_pyav_hls()
            self.packet_queue = asyncio.Queue(maxsize=300)
            
            # Setup aiohttp web server
            # Catatan: route statis (/live) HARUS didaftarkan sebelum /{filename}
            # karena aiohttp mencocokkan route berurutan.
            app = web.Application()

            async def _handle_options(request: web.Request) -> web.Response:
                return web.Response(
                    status=204,
                    headers={
                        "Access-Control-Allow-Origin": "*",
                        "Access-Control-Allow-Methods": "GET, OPTIONS",
                        "Access-Control-Allow-Headers": "*",
                        "Access-Control-Max-Age": "86400",
                    },
                )

            app.router.add_route("OPTIONS", "/{tail:.*}", _handle_options)
            if self.icecast_server is not None:
                app.router.add_get("/live", self.icecast_server.handle_request)
            app.router.add_get("/live.m3u8", self._handle_m3u8)
            app.router.add_get("/{filename}", self._handle_segment)
            app.router.add_get("/", self._handle_index)

            self.runner = web.AppRunner(app)
            await self.runner.setup()

            # Attempt to bind to requested port, with auto-scan fallback if occupied
            bound = False
            for test_port in range(self.port, self.port + 30):
                try:
                    site = web.TCPSite(self.runner, self.host, test_port)
                    await site.start()
                    self.site = site
                    self.port = test_port
                    bound = True
                    break
                except OSError:
                    continue

            if not bound:
                raise OSError(f"Could not bind HLS HTTP Server to any port in range {self.port}-{self.port + 30}")

            self.is_running = True
            self.start_time = time.monotonic()
            self.mux_task = asyncio.create_task(self._mux_loop())

            print(f"[HLS] Server active on http://{self.host}:{self.port} (Public URL: {self.public_url})")
            return True
        except Exception as e:
            print(f"[HLS Error] Failed to launch HLS Server: {e}")
            await self.stop()
            return False

    def enqueue_opus_frame(self, raw_opus_bytes: bytes, samples: int = 960):
        if not self.is_running or self.packet_queue is None:
            return
        try:
            self.packet_queue.put_nowait((raw_opus_bytes, samples))
        except asyncio.QueueFull:
            try:
                self.packet_queue.get_nowait()
                self.packet_queue.put_nowait((raw_opus_bytes, samples))
            except Exception:
                pass

    async def _mux_loop(self):
        while self.is_running:
            try:
                raw_opus_bytes, samples = await self.packet_queue.get()
                
                if self.container and self.audio_stream:
                    pkt = av.Packet(raw_opus_bytes)
                    pkt.pts = self._pts
                    pkt.time_base = fractions.Fraction(1, 48000)
                    pkt.stream = self.audio_stream
                    
                    self.container.mux(pkt)
                    self._pts += samples
                    
                self.packet_queue.task_done()
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"[HLS Mux Error] {e}")
                await asyncio.sleep(0.05)

    async def _handle_m3u8(self, request: web.Request) -> web.Response:
        self.http_requests_count += 1
        for _ in range(30):
            if os.path.exists(self.m3u8_file):
                break
            await asyncio.sleep(0.1)

        if not os.path.exists(self.m3u8_file):
            return web.Response(
                status=503,
                text="Playlist initializing, please retry in 2 seconds.",
                headers={"Retry-After": "2", "Access-Control-Allow-Origin": "*"}
            )
        
        try:
            try:
                current_mtime = os.path.getmtime(self.m3u8_file)
                if self._m3u8_cache is None or current_mtime > self._m3u8_mtime:
                    with open(self.m3u8_file, "r", encoding="utf-8") as f:
                        self._m3u8_cache = f.read()
                    self._m3u8_mtime = current_mtime
            except OSError:
                if self._m3u8_cache is None:
                    return web.Response(
                        status=503,
                        text="Playlist belum siap.",
                        headers={"Retry-After": "1", "Access-Control-Allow-Origin": "*"},
                    )

            if self._m3u8_cache is None:
                return web.Response(
                    status=503,
                    text="Playlist belum siap.",
                    headers={"Retry-After": "1", "Access-Control-Allow-Origin": "*"},
                )

            content = self._m3u8_cache
            self.total_bytes_served += len(content)
            now = time.monotonic()
            self._sliding_bytes.append((now, len(content)))
            
            return web.Response(
                text=content,
                content_type="application/x-mpegURL",
                headers={
                    "Cache-Control": "no-cache, no-store, must-revalidate",
                    "Access-Control-Allow-Origin": "*",
                    "Access-Control-Allow-Headers": "*"
                }
            )
        except Exception:
            return web.Response(status=500, text="Gagal membaca playlist.")

    async def _handle_segment(self, request: web.Request) -> web.Response:
        self.http_requests_count += 1
        filename = request.match_info.get("filename", "")

        # Security: tolak nama file di luar whitelist (blokir "../", backslash, ekstensi lain)
        if not _SAFE_SEGMENT_RE.match(filename):
            return web.Response(status=404, text="File segmen tidak ditemukan.")

        file_path = os.path.join(self.output_dir, filename)

        # Fallback: Jika init.mp4 dibuat oleh PyAV/FFmpeg di root working directory
        if not os.path.isfile(file_path):
            if filename == getattr(self, "init_filename", None):
                root_fallback = os.path.abspath(filename)
                if os.path.isfile(root_fallback):
                    file_path = root_fallback

        if not os.path.isfile(file_path):
            return web.Response(status=404, text="File segmen tidak ditemukan.")

        try:
            file_size = os.path.getsize(file_path)
            self.total_bytes_served += file_size
            now = time.monotonic()
            self._sliding_bytes.append((now, file_size))

            content_type = "audio/mp4" if filename.endswith((".m4s", ".mp4")) else "video/mp4"
            
            return web.FileResponse(
                path=file_path,
                headers={
                    "Content-Type": content_type,
                    "Cache-Control": "public, max-age=60, immutable",
                    "Access-Control-Allow-Origin": "*",
                    "Access-Control-Allow-Headers": "*"
                }
            )
        except Exception:
            return web.Response(status=500, text="Gagal membaca segmen.")

    async def _handle_index(self, request: web.Request) -> web.Response:
        safe_url = html.escape(self.public_url)
        html_page = (
            "<!DOCTYPE html><html><head><title>MeshCast HLS Radio</title></head>"
            "<body style='font-family:sans-serif; background:#121212; color:#fff; text-align:center; padding:50px;'>"
            "<h1>📡 Radio HLS Stream Active</h1>"
            f"<p>Stream URL: <a style='color:#00e676;' href='{safe_url}'>{safe_url}</a></p>"
            "</body></html>"
        )
        return web.Response(text=html_page, content_type="text/html", headers={"Access-Control-Allow-Origin": "*"})

    def get_hls_stats(self) -> Dict[str, Any]:
        now = time.monotonic()
        uptime = max(0.1, now - self.start_time)

        cutoff = now - 3.0
        while self._sliding_bytes and self._sliding_bytes[0][0] < cutoff:
            self._sliding_bytes.popleft()

        recent_bytes = sum(b for t, b in self._sliding_bytes)
        window_dur = (self._sliding_bytes[-1][0] - self._sliding_bytes[0][0]) if len(self._sliding_bytes) > 1 else 3.0
        window_dur = max(0.1, window_dur)

        inst_bitrate = (recent_bytes * 8 / window_dur) / 1000.0 if len(self._sliding_bytes) > 1 else 0.0
        avg_bitrate = (self.total_bytes_served * 8 / uptime) / 1000.0

        return {
            "is_running": self.is_running,
            "host": self.host,
            "port": self.port,
            "public_url": self.public_url,
            "uptime_sec": uptime,
            "total_bytes": self.total_bytes_served,
            "http_requests": self.http_requests_count,
            "instant_bitrate_kbps": inst_bitrate,
            "avg_bitrate_kbps": avg_bitrate
        }

    async def stop(self):
        self.is_running = False
        if self.mux_task:
            self.mux_task.cancel()
            self.mux_task = None

        if self.container:
            try:
                self.container.close()
            except Exception:
                pass
            self.container = None

        if self.runner:
            await self.runner.cleanup()
            self.runner = None
            self.site = None

        if hasattr(self, "init_filename") and self.init_filename and os.path.exists(self.init_filename):
            try:
                os.remove(self.init_filename)
            except Exception:
                pass

        if os.path.exists(self.output_dir):
            try:
                shutil.rmtree(self.output_dir)
            except Exception:
                pass

        print("[HLS] HLS Server & Segmenter dihentikan.")
