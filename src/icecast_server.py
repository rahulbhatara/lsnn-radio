import time
import asyncio
from collections import deque
from typing import Any, Deque, Dict, List, Optional

import av
from aiohttp import web


def make_adts_header(payload_length: int) -> bytes:
    """
    Bangun header ADTS 7-byte untuk satu frame AAC-LC mentah (raw AAC).
    Konfigurasi tetap: MPEG-4, AAC-LC (profile=1), 48 kHz (sf_index=3),
    stereo (channel_configuration=2), tanpa CRC, buffer fullness 0x7FF.
    """
    frame_length = payload_length + 7
    b0 = 0xFF                                              # syncword hi
    b1 = 0xF1                                              # syncword lo + MPEG-4 + layer 0 + protection_absent
    b2 = (0x01 << 6) | (0x03 << 2) | (0 << 1) | ((0x02 >> 2) & 0x01)
    b3 = ((0x02 & 0x03) << 6) | ((frame_length >> 11) & 0x03)
    b4 = (frame_length >> 3) & 0xFF
    b5 = ((frame_length & 0x07) << 5) | 0x1F               # fullness 0x7FF (11 bit all-one)
    b6 = 0x3F
    return bytes((b0, b1, b2, b3, b4, b5, b6))


class NativeIcecastServer:
    """
    Relay audio bergaya Icecast-native (tanpa binary icecast eksternal).

    Menerima paket raw Opus 20ms dari pacer (via packet listener), melakukan
    transcode on-the-fly: Opus -> PCM -> AAC-LC, membungkusnya dengan header
    ADTS, lalu melayani mount point HTTP stream kontinu "/live" (Content-Type:
    audio/aac) yang kompatibel dengan VLC / browser / player radio tradisional.

    Secara default server ini MATI (enabled=False). Saat mati, listener packet
    langsung di-skip sehingga tidak ada biaya CPU sama sekali.

    Satu pipeline transcode dibagi ke semua pendengar (fan-out via asyncio.Queue
    per klien), jadi jumlah listener tidak menambah beban encode.
    """

    def __init__(
        self,
        sample_rate: int = 48000,
        channels: int = 2,
        bitrate: int = 128000,
        max_buffer_sec: float = 8.0,
        max_listeners: int = 100,
        client_queue_max: int = 400,
    ):
        self.sample_rate = sample_rate
        self.channels = channels
        self.bitrate = bitrate
        self.max_listeners = max_listeners
        self._client_queue_max = client_queue_max
        self._max_buffer_bytes = max(65536, int(bitrate / 8 * max_buffer_sec))

        self.enabled = False

        # Pipeline transcode (di-init saat enable())
        self._decoder: Optional[av.CodecContext] = None   # libopus decoder
        self._encoder: Optional[av.CodecContext] = None   # AAC-LC encoder
        self._resampler = None                            # s16 -> fltp untuk encoder AAC

        # Fan-out buffer & klien
        self._clients: List[Dict[str, Any]] = []
        self._buffer: Deque[bytes] = deque()              # chunk ADTS siap kirim
        self._buffer_bytes = 0

        # Statistik
        self.start_time = time.monotonic()
        self.packets_produced = 0
        self.total_bytes = 0
        self.listeners_served = 0
        self.transcode_errors = 0
        self._last_error_log = 0.0
        self._sliding = deque(maxlen=200)                 # (timestamp, size) utk bitrate instan

    # ── Lifecycle ───────────────────────────────────────────────────
    def enable(self) -> bool:
        """Aktifkan relay: init decoder Opus + encoder AAC. Idempotent."""
        if self.enabled:
            return True
        try:
            dec = av.CodecContext.create("libopus", "r")
            try:
                dec.sample_rate = self.sample_rate
                dec.layout = "stereo" if self.channels == 2 else "mono"
            except Exception:
                pass  # default libopus decode sudah 48kHz stereo

            enc = av.CodecContext.create("aac", "w")
            enc.sample_rate = self.sample_rate
            enc.layout = "stereo" if self.channels == 2 else "mono"
            enc.format = "fltp"
            enc.bit_rate = self.bitrate
            enc.open()

            resampler = av.AudioResampler(
                format="fltp",
                layout="stereo" if self.channels == 2 else "mono",
                rate=self.sample_rate,
            )

            self._decoder = dec
            self._encoder = enc
            self._resampler = resampler
            self.enabled = True
            self.start_time = time.monotonic()
            self.transcode_errors = 0
            print(f"[Icecast] Native AAC/Icecast relay ENABLED ({self.bitrate // 1000} kbps AAC-LC @ /live)")
            return True
        except Exception as e:
            print(f"[Icecast Error] Gagal init transcoder AAC: {e}")
            self._decoder = None
            self._encoder = None
            self._resampler = None
            self.enabled = False
            return False

    def disable(self):
        """Matikan relay dan bebaskan codec. Klien aktif akan terputus <=1 detik."""
        if not self.enabled and self._encoder is None:
            return
        self.enabled = False
        self._decoder = None
        self._encoder = None
        self._resampler = None
        self._buffer.clear()
        self._buffer_bytes = 0
        print("[Icecast] Native AAC/Icecast relay DISABLED.")

    # ── Input dari pacer (packet listener) ──────────────────────────
    def enqueue_opus_frame(self, raw_opus_bytes: bytes, samples: int = 960):
        """Dipanggil pacer tiap frame Opus 20ms. No-op murah saat disabled."""
        if not self.enabled or self._decoder is None or self._encoder is None:
            return
        try:
            pkt = av.Packet(bytes(raw_opus_bytes))
            for frame in self._decoder.decode(pkt):
                for rf in self._resampler.resample(frame):
                    for out_pkt in self._encoder.encode(rf):
                        self._emit(bytes(out_pkt))
        except Exception as e:
            self.transcode_errors += 1
            now = time.monotonic()
            if now - self._last_error_log > 10.0:
                self._last_error_log = now
                print(f"[Icecast Error] Transcode gagal (total {self.transcode_errors}): {e}")

    def _emit(self, aac_payload: bytes):
        """Bungkus ADTS, simpan ke ring buffer, dan fan-out ke semua klien."""
        chunk = make_adts_header(len(aac_payload)) + aac_payload
        self._buffer.append(chunk)
        self._buffer_bytes += len(chunk)
        self.packets_produced += 1
        self.total_bytes += len(chunk)
        now = time.monotonic()
        self._sliding.append((now, len(chunk)))

        while self._buffer_bytes > self._max_buffer_bytes and len(self._buffer) > 1:
            self._buffer_bytes -= len(self._buffer.popleft())

        for c in self._clients:
            if c["dead"]:
                continue
            try:
                c["q"].put_nowait(chunk)
            except asyncio.QueueFull:
                c["dead"] = True  # klien lambat -> tendang agar tidak menumpuk

    def _recent_chunks(self, count: int) -> List[bytes]:
        if count <= 0 or not self._buffer:
            return []
        return list(self._buffer)[-count:]

    # ── HTTP handler mount "/live" ──────────────────────────────────
    async def handle_request(self, request: web.Request) -> web.StreamResponse:
        if not self.enabled:
            return web.Response(
                status=503,
                text="AAC/Icecast stream is currently disabled by the broadcaster.",
                headers={"Retry-After": "60", "Access-Control-Allow-Origin": "*"},
            )
        if len(self._clients) >= self.max_listeners:
            return web.Response(status=503, text="Too many listeners connected.", headers={"Retry-After": "10"})

        resp = web.StreamResponse(status=200)
        resp.content_type = "audio/aac"
        resp.headers.update({
            "Cache-Control": "no-cache, no-store, no-transform, must-revalidate",
            "Pragma": "no-cache",
            "Accept-Ranges": "none",
            "Access-Control-Allow-Origin": "*",
            # Cegah buffering di reverse-proxy mana pun dalam rantai (nginx/cloudflared)
            "X-Accel-Buffering": "no",
            "icy-br": str(self.bitrate // 1000),
            "icy-name": "MeshCast Live",
            "icy-description": "Native Icecast-compatible AAC relay (Opus transcoded)",
            "icy-genre": "various",
        })
        await resp.prepare(request)

        q: asyncio.Queue = asyncio.Queue(maxsize=self._client_queue_max)
        client = {"q": q, "dead": False}
        self._clients.append(client)
        self.listeners_served += 1

        try:
            # Prime buffer dengan tail terakhir supaya playback mulai instan
            for data in self._recent_chunks(5):
                try:
                    q.put_nowait(data)
                except asyncio.QueueFull:
                    break

            while True:
                try:
                    first = await asyncio.wait_for(q.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    # Timeout bukan error: kesempatan cek flag mati/kick
                    if client["dead"] or not self.enabled:
                        break
                    continue

                # Coalesce frame 20ms menjadi blok besar (~<=64KB): lebih ramah
                # proksi/tunnel dan mengurangi syscall per-frame.
                parts = [first]
                total = len(first)
                while total < 65536:
                    try:
                        nxt = q.get_nowait()
                    except asyncio.QueueEmpty:
                        break
                    parts.append(nxt)
                    total += len(nxt)
                await resp.write(b"".join(parts))
        except (ConnectionResetError, ConnectionError):
            pass
        except Exception:
            pass
        finally:
            try:
                self._clients.remove(client)
            except ValueError:
                pass
            try:
                await resp.write_eof()
            except Exception:
                pass

        return resp

    # ── Statistik ───────────────────────────────────────────────────
    def get_stats(self) -> Dict[str, Any]:
        now = time.monotonic()
        cutoff = now - 3.0
        recent = [(t, s) for t, s in self._sliding if t >= cutoff]
        if len(recent) > 1:
            dur = max(0.1, recent[-1][0] - recent[0][0])
            inst_kbps = (sum(s for _, s in recent) * 8 / dur) / 1000.0
        else:
            inst_kbps = 0.0

        return {
            "enabled": self.enabled,
            "listeners": sum(1 for c in self._clients if not c["dead"]),
            "listeners_total": self.listeners_served,
            "packets": self.packets_produced,
            "total_bytes": self.total_bytes,
            "instant_bitrate_kbps": round(inst_kbps, 1),
            "target_bitrate_kbps": self.bitrate // 1000,
            "transcode_errors": self.transcode_errors,
            "uptime_sec": now - self.start_time,
        }
