import os
import glob
import time
import random
import asyncio
from collections import deque
from typing import Optional, List, Dict, Any
import av
from fractions import Fraction
from aiortc import MediaStreamTrack
from .opus_demuxer import OpusDemuxer
from .audio_capture import AudioCaptureWorker, get_windows_input_devices

# Opus Silence Frame (3 bytes) mewakili 20ms audio hening pada 48kHz
OPUS_SILENCE_FRAME = b'\xf8\xff\xfe'
SAMPLES_PER_FRAME = 960  # 20ms @ 48000 Hz
FRAME_DURATION_SEC = 0.020  # 20ms
TIME_BASE_48K = Fraction(1, 48000)

def _create_silence_packet(pts: int) -> av.Packet:
    p = av.Packet(OPUS_SILENCE_FRAME)
    p.pts = pts
    p.time_base = TIME_BASE_48K
    return p

class RawOpusTrack(MediaStreamTrack):
    """
    Custom MediaStreamTrack yang mengirimkan paket Raw Opus (RFC 7587)
    secara real-time dengan pacing 20ms dan re-timestamping kontinu tanpa re-encode.
    Mendukung dua mode sumber audio:
      1. 'playlist': Priority User Queue + Fallback Auto-DJ Library Pool (Zero Re-encoding)
      2. 'mic': Live audio PCM dari Windows Audio Device yang di-encode ke 20ms Opus
    """
    kind = "audio"

    def __init__(self, playlist: list[str] = None, initial_source_mode: str = "playlist"):
        super().__init__()
        self.library: List[str] = [f for f in (playlist or []) if os.path.exists(f)]
        self.user_queue: List[str] = []
        self.shuffled_pool: List[str] = []
        self.auto_dj_enabled: bool = True
        
        self.current_track: Optional[str] = None
        self.current_source: str = "autodj"  # "queue", "autodj", "direct", "mic"
        self.demuxer: Optional[OpusDemuxer] = None
        
        self.source_mode = initial_source_mode  # "playlist" atau "mic"
        self.audio_capture = AudioCaptureWorker()
        
        self.is_playing = True
        self.is_muted = False
        
        self._pts = 0
        self._next_pacing_time = None
        
        # Telemetry & Statistics (Gunakan deque O(1) ops untuk bebas alokasi memori & GC pressure)
        self.start_time = time.monotonic()
        self.total_frames = 0
        self.audio_frames = 0
        self.silence_frames = 0
        self.total_bytes = 0
        self.track_frames_played = 0
        self._sliding_bytes = deque()  # deque of (timestamp, byte_len)
        self._pacing_drifts = deque(maxlen=50)  # deque drift in ms dengan maxlen otomatis
        self._packet_listeners = []

        if self.source_mode == "mic":
            self.audio_capture.start()
        elif self.library:
            self._refill_shuffled_pool()
            self.next_track()

    @property
    def playlist(self) -> List[str]:
        """Properti backward-compatibility untuk mengakses daftar library."""
        return self.library

    @playlist.setter
    def playlist(self, tracks: List[str]):
        self.library = [f for f in tracks if os.path.exists(f)]

    def add_packet_listener(self, callback):
        if callback not in self._packet_listeners:
            self._packet_listeners.append(callback)

    def _notify_packet_listeners(self, raw_bytes: bytes, samples: int = SAMPLES_PER_FRAME):
        for cb in self._packet_listeners:
            try:
                cb(raw_bytes, samples)
            except Exception:
                pass

    def _refill_shuffled_pool(self):
        """Mengisi ulang siklus acak library untuk Auto-DJ tanpa pengulangan lagu."""
        if not self.library:
            self.shuffled_pool = []
            return
        pool = list(self.library)
        rng = random.SystemRandom()
        rng.shuffle(pool)
        if self.current_track and len(pool) > 1 and pool[0] == self.current_track:
            pool[0], pool[-1] = pool[-1], pool[0]
        self.shuffled_pool = pool

    def refresh_playlist(self, music_dir: str) -> tuple[int, int]:
        """
        Pindai ulang direktori lagu dan perbarui library tanpa memutus lagu yang sedang diputar.
        Mengembalikan tuple (jumlah_lagu_baru, total_lagu_sekarang).
        """
        pattern = os.path.join(music_dir, "*.opus")
        files = sorted(glob.glob(pattern))
        
        existing_set = set(os.path.abspath(f) for f in self.library)
        new_files = [f for f in files if os.path.abspath(f) not in existing_set]
        
        valid_files_set = set(os.path.abspath(f) for f in files)
        self.library = [f for f in self.library if os.path.abspath(f) in valid_files_set]
        
        if new_files:
            self.library.extend(new_files)
            if not self.shuffled_pool and self.auto_dj_enabled:
                self._refill_shuffled_pool()

        # Bersihkan queue dari file yang sudah tidak ada di disk
        self.user_queue = [f for f in self.user_queue if os.path.abspath(f) in valid_files_set]

        # Jika belum ada lagu yang diputar dan mode playlist aktif, mulai putar
        if not self.demuxer and self.library and self.source_mode == "playlist":
            self.next_track()
            
        return len(new_files), len(self.library)

    def _load_demuxer(self, track_path: str):
        self.track_frames_played = 0
        if self.demuxer:
            self.demuxer.close()
            self.demuxer = None
            
        if track_path and os.path.exists(track_path):
            try:
                self.demuxer = OpusDemuxer(track_path)
            except Exception as e:
                print(f"[Pacer Error] Gagal memuat {os.path.basename(track_path)}: {e}")
                self.demuxer = None

    def set_source_mode(self, mode: str) -> str:
        """
        Mengganti mode input streaming:
        - 'playlist': Priority Queue & Auto-DJ Library Pool (Zero Re-encoding)
        - 'mic': Live audio PCM dari Windows Audio Device & di-encode ke 20ms Opus
        """
        if mode not in ("playlist", "mic"):
            return self.source_mode

        if self.source_mode == mode:
            return self.source_mode

        self.source_mode = mode
        if self.source_mode == "mic":
            self.audio_capture.start(device_id=self.audio_capture.device_id)
            print("[RawOpusTrack] Berpindah ke Mode: LIVE MICROPHONE (PCM -> 20ms Opus)")
        else:
            self.audio_capture.stop()
            if not self.demuxer and (self.user_queue or self.library):
                self.next_track()
            print("[RawOpusTrack] Berpindah ke Mode: NATIVE OPUS MUSIC LIBRARY")

        return self.source_mode

    def set_audio_device(self, device_id: Optional[int]) -> bool:
        """Mengganti perangkat input audio Windows."""
        if self.source_mode == "mic":
            return self.audio_capture.start(device_id=device_id)
        else:
            self.audio_capture.device_id = device_id
            return True

    def get_available_audio_devices(self) -> list:
        return get_windows_input_devices()

    def get_audio_capture_stats(self) -> dict:
        return self.audio_capture.get_stats()

    def toggle_play(self):
        self.is_playing = not self.is_playing
        return self.is_playing

    def toggle_mute(self):
        self.is_muted = not self.is_muted
        return self.is_muted

    def toggle_auto_dj(self, enable: Optional[bool] = None) -> bool:
        """Mengaktifkan atau menonaktifkan mode Auto-DJ (Fallback acak saat Queue kosong)."""
        if enable is not None:
            self.auto_dj_enabled = enable
        else:
            self.auto_dj_enabled = not self.auto_dj_enabled
            
        if self.auto_dj_enabled and not self.demuxer and self.library and self.source_mode == "playlist":
            self.next_track()
        return self.auto_dj_enabled

    def next_track(self):
        """
        Memutar lagu berikutnya dengan logika prioritas:
        1. User Queue (Prioritas Pertama)
        2. Auto-DJ Shuffled Pool (Jika Queue kosong dan Auto-DJ On)
        3. Hening/Pause (Jika antrian habis dan Auto-DJ Off)
        """
        next_path = None
        if self.user_queue:
            next_path = self.user_queue.pop(0)
            self.current_source = "queue"
        elif self.auto_dj_enabled and self.library:
            if not self.shuffled_pool:
                self._refill_shuffled_pool()
            if self.shuffled_pool:
                next_path = self.shuffled_pool.pop(0)
                self.current_source = "autodj"
        else:
            self.current_source = "none"

        if next_path and os.path.exists(next_path):
            self.current_track = next_path
            self._load_demuxer(next_path)
        else:
            self.current_track = None
            if self.demuxer:
                self.demuxer.close()
                self.demuxer = None

    def prev_track(self):
        """Memutar ulang lagu yang sedang aktif dari awal."""
        if self.current_track and os.path.exists(self.current_track):
            self._load_demuxer(self.current_track)

    def play_track_direct(self, track_path: str):
        """Langsung memutar lagu dari library tanpa mengubah antrian queue."""
        if not os.path.exists(track_path):
            return
        self.current_track = track_path
        self.current_source = "direct"
        self._load_demuxer(track_path)

    def play_track_at_index(self, index: int):
        """Backward-compatibility: memutar lagu berdasarkan indeks di library."""
        if 0 <= index < len(self.library):
            self.play_track_direct(self.library[index])

    def add_to_queue_top(self, track_path: str) -> int:
        """Menyisipkan lagu ke urutan teratas antrian (Play Next). Mengembalikan indeks (0)."""
        if not os.path.exists(track_path):
            return -1
        self.user_queue.insert(0, track_path)
        return 0

    def add_to_queue_bottom(self, track_path: str) -> int:
        """Menambahkan lagu ke urutan terbawah antrian (Add to Queue). Mengembalikan indeks posisi baru."""
        if not os.path.exists(track_path):
            return -1
        self.user_queue.append(track_path)
        return len(self.user_queue) - 1

    def queue_track_next(self, index: int) -> int:
        """Backward-compatibility: memindahkan lagu library pada index ke atas antrian."""
        if 0 <= index < len(self.library):
            return self.add_to_queue_top(self.library[index])
        return -1

    def remove_from_queue(self, index: int) -> bool:
        """Menghapus item pada indeks tertentu di antrian User Queue."""
        if 0 <= index < len(self.user_queue):
            self.user_queue.pop(index)
            return True
        return False

    def remove_track_at_index(self, index: int) -> bool:
        """Backward-compatibility: menghapus item antrian."""
        return self.remove_from_queue(index)

    def move_queue_item(self, from_idx: int, to_idx: int) -> bool:
        """Menggeser urutan lagu di dalam antrian."""
        if 0 <= from_idx < len(self.user_queue) and 0 <= to_idx < len(self.user_queue):
            item = self.user_queue.pop(from_idx)
            self.user_queue.insert(to_idx, item)
            return True
        return False

    def clear_queue(self):
        """Mengosongkan seluruh antrian User Queue."""
        self.user_queue.clear()

    def shuffle_queue(self):
        """Mengacak urutan lagu di dalam antrian User Queue."""
        if len(self.user_queue) > 1:
            rng = random.SystemRandom()
            rng.shuffle(self.user_queue)

    def insert_next_track(self, file_path: str) -> int:
        """Menambahkan file download baru ke urutan teratas antrian (Play Next)."""
        if not os.path.exists(file_path):
            return -1
        if file_path not in self.library:
            self.library.append(file_path)
        self.add_to_queue_top(file_path)
        return 1

    def get_status(self) -> dict:
        current_name = (
            os.path.basename(self.current_track)
            if self.current_track and os.path.exists(self.current_track)
            else "Tidak ada lagu aktif"
        )
        duration_sec = self.demuxer.duration_sec if self.demuxer else 0.0
        elapsed_sec = self.track_frames_played * FRAME_DURATION_SEC
        mic_stats = self.audio_capture.get_stats()

        return {
            "source_mode": self.source_mode,
            "track": current_name,
            "current_track_path": self.current_track,
            "current_source": self.current_source,
            "queue_count": len(self.user_queue),
            "library_count": len(self.library),
            "auto_dj_enabled": self.auto_dj_enabled,
            "is_playing": self.is_playing,
            "is_muted": self.is_muted,
            "track_elapsed_sec": elapsed_sec,
            "track_duration_sec": duration_sec,
            "mic_is_running": mic_stats["is_running"],
            "mic_level_db": mic_stats["level_db"],
            "mic_level_linear": mic_stats["level_linear"],
            "mic_device_id": mic_stats["device_id"],
        }

    def get_pacer_stats(self) -> dict:
        now = time.monotonic()
        uptime = max(0.001, now - self.start_time)
        
        # Sliding window bitrate (3 detik terakhir)
        recent_bytes = sum(b for t, b in self._sliding_bytes)
        recent_frames = len(self._sliding_bytes)
        window_dur = (self._sliding_bytes[-1][0] - self._sliding_bytes[0][0]) if len(self._sliding_bytes) > 1 else 3.0
        window_dur = max(0.1, window_dur)
        
        instant_bitrate_kbps = (recent_bytes * 8 / window_dur) / 1000.0 if recent_frames > 1 else 0.0
        instant_pps = recent_frames / window_dur if recent_frames > 1 else 0.0
        
        avg_bitrate_kbps = (self.total_bytes * 8 / uptime) / 1000.0
        avg_pps = self.total_frames / uptime
        
        instant_drift = self._pacing_drifts[-1] if self._pacing_drifts else 0.0
        avg_drift = sum(self._pacing_drifts) / len(self._pacing_drifts) if self._pacing_drifts else 0.0
        max_drift = max(self._pacing_drifts) if self._pacing_drifts else 0.0

        return {
            "uptime_sec": uptime,
            "total_frames": self.total_frames,
            "audio_frames": self.audio_frames,
            "silence_frames": self.silence_frames,
            "total_bytes": self.total_bytes,
            "instant_bitrate_kbps": instant_bitrate_kbps,
            "avg_bitrate_kbps": avg_bitrate_kbps,
            "instant_pps": instant_pps,
            "avg_pps": avg_pps,
            "instant_drift_ms": instant_drift,
            "avg_drift_ms": avg_drift,
            "max_drift_ms": max_drift,
        }

    def _record_packet_stats(self, packet: av.Packet, is_silence: bool = False):
        pkt_len = packet.size if hasattr(packet, 'size') and packet.size is not None else len(packet)

        self.total_frames += 1
        if is_silence:
            self.silence_frames += 1
        else:
            self.audio_frames += 1

        self.total_bytes += pkt_len

        now_ts = time.monotonic()
        self._sliding_bytes.append((now_ts, pkt_len))
        if len(self._sliding_bytes) > 200:
            cutoff = now_ts - 3.0
            while self._sliding_bytes and self._sliding_bytes[0][0] < cutoff:
                self._sliding_bytes.popleft()

    async def recv(self) -> av.Packet:
        # Pacing kontrol jam real-time (20ms per frame)
        now = time.monotonic()
        # Resync jam pacing jika tertinggal jauh (system sleep / event-loop stall)
        # agar tidak mengirim burst puluhan frame sekaligus saat bangun.
        if self._next_pacing_time is None or (self._next_pacing_time - now) < -0.5:
            self._next_pacing_time = now + FRAME_DURATION_SEC
        else:
            delay = self._next_pacing_time - now
            if delay > 0:
                await asyncio.sleep(delay)

            # Hitung pacing drift dalam ms (maxlen=50 otomatis membuang data lama O(1))
            actual_wake = time.monotonic()
            drift_ms = abs(actual_wake - self._next_pacing_time) * 1000.0
            self._pacing_drifts.append(drift_ms)

            self._next_pacing_time += FRAME_DURATION_SEC

        # Naikkan timestamp PTS secara linier dan bertahap (+960 samples per 20ms)
        self._pts += SAMPLES_PER_FRAME

        # Jika dalam kondisi Pause
        if not self.is_playing:
            p = _create_silence_packet(self._pts)
            self._record_packet_stats(p, is_silence=True)
            self._notify_packet_listeners(OPUS_SILENCE_FRAME, SAMPLES_PER_FRAME)
            return p

        # ── Mode 1: Live Audio Device (Microphone) ──────────────────
        if self.source_mode == "mic":
            # Jika MUTE aktif: suntikkan frame hening
            if self.is_muted:
                p = _create_silence_packet(self._pts)
                self._record_packet_stats(p, is_silence=True)
                self._notify_packet_listeners(OPUS_SILENCE_FRAME, SAMPLES_PER_FRAME)
                return p

            raw_bytes = self.audio_capture.get_next_opus_packet()
            if raw_bytes is None:
                # Buffer underrun / belum ada sampel audio dari mic -> kirim hening
                p = _create_silence_packet(self._pts)
                self._record_packet_stats(p, is_silence=True)
                self._notify_packet_listeners(OPUS_SILENCE_FRAME, SAMPLES_PER_FRAME)
                return p

            packet = av.Packet(raw_bytes)
            packet.pts = self._pts
            packet.time_base = TIME_BASE_48K
            self._record_packet_stats(packet, is_silence=False)
            self._notify_packet_listeners(raw_bytes, SAMPLES_PER_FRAME)
            return packet

        # ── Mode 2: Native Opus Music Library Demuxer (Queue & Auto-DJ) ───────────────
        if not self.demuxer:
            if self.user_queue or (self.auto_dj_enabled and self.library):
                self.next_track()

            if not self.demuxer:
                p = _create_silence_packet(self._pts)
                self._record_packet_stats(p, is_silence=True)
                self._notify_packet_listeners(OPUS_SILENCE_FRAME, SAMPLES_PER_FRAME)
                return p

        # Ambil paket raw Opus dari demuxer (lagu tetap berjalan di background)
        packet = self.demuxer.get_next_packet()

        # Jika lagu selesai (EOF)
        if packet is None:
            self.next_track()
            if self.demuxer:
                packet = self.demuxer.get_next_packet()

        # Jika masih tidak ada paket (misal antrian habis & Auto-DJ off), kirim hening
        if packet is None:
            p = _create_silence_packet(self._pts)
            self._record_packet_stats(p, is_silence=True)
            self._notify_packet_listeners(OPUS_SILENCE_FRAME, SAMPLES_PER_FRAME)
            return p

        # Lagu sedang dibaca: naikkan counter frame lagu yang diputar
        self.track_frames_played += 1

        # Jika MUTE aktif: ganti paket suara lagu dengan hening (posisi lagu tetap maju)
        if self.is_muted:
            p = _create_silence_packet(self._pts)
            self._record_packet_stats(p, is_silence=True)
            self._notify_packet_listeners(OPUS_SILENCE_FRAME, SAMPLES_PER_FRAME)
            return p

        # Atur timestamp linier pada paket asli dari file
        packet.pts = self._pts
        packet.time_base = TIME_BASE_48K
        self._record_packet_stats(packet, is_silence=False)
        self._notify_packet_listeners(bytes(packet), SAMPLES_PER_FRAME)
        return packet

    def stop(self):
        if self.audio_capture:
            self.audio_capture.stop()
        if self.demuxer:
            self.demuxer.close()
            self.demuxer = None
        super().stop()
