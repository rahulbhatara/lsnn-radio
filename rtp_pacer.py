import os
import glob
import time
import random
import asyncio
from collections import deque
import av
from fractions import Fraction
from aiortc import MediaStreamTrack
from opus_demuxer import OpusDemuxer

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
    """
    kind = "audio"

    def __init__(self, playlist: list[str]):
        super().__init__()
        self.playlist = [f for f in playlist if os.path.exists(f)]
        self.current_index = 0
        self.demuxer = None
        
        self.is_playing = True
        self.is_muted = False
        self.loop_playlist = True
        
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

        if self.playlist:
            # Lakukan pengacakan tingkat tinggi saat awal inisialisasi track
            self.reshuffle_playlist_loop(avoid_repeat_track=None)
            self._load_demuxer()

    def add_packet_listener(self, callback):
        if callback not in self._packet_listeners:
            self._packet_listeners.append(callback)

    def _notify_packet_listeners(self, raw_bytes: bytes, samples: int = SAMPLES_PER_FRAME):
        for cb in self._packet_listeners:
            try:
                cb(raw_bytes, samples)
            except Exception:
                pass

    def reshuffle_playlist_loop(self, avoid_repeat_track: str = None):
        """
        Mengacak seluruh playlist untuk siklus baru, memastikan lagu pertama tidak mengulang lagu terakhir.
        """
        if not self.playlist:
            return

        rng = random.SystemRandom()
        rng.shuffle(self.playlist)

        if avoid_repeat_track and len(self.playlist) > 1 and self.playlist[0] == avoid_repeat_track:
            swap_idx = rng.randint(1, len(self.playlist) - 1)
            self.playlist[0], self.playlist[swap_idx] = self.playlist[swap_idx], self.playlist[0]

        self.current_index = 0

    def reshuffle_remaining(self):
        """
        Mengacak ulang sisa lagu di playlist tanpa menghentikan atau mengubah lagu yang sedang diputar.
        """
        if not self.playlist or len(self.playlist) <= 1:
            return

        current_track = self.playlist[self.current_index] if 0 <= self.current_index < len(self.playlist) else None
        
        rng = random.SystemRandom()
        other_tracks = [t for i, t in enumerate(self.playlist) if i != self.current_index]
        rng.shuffle(other_tracks)

        new_playlist = other_tracks[:self.current_index] + ([current_track] if current_track else []) + other_tracks[self.current_index:]
        self.playlist = new_playlist
        if current_track and current_track in self.playlist:
            self.current_index = self.playlist.index(current_track)

    def refresh_playlist(self, music_dir: str) -> tuple[int, int]:
        """
        Pindai ulang direktori lagu dan perbarui playlist tanpa memutus lagu yang sedang diputar.
        Mengembalikan tuple (jumlah_lagu_baru, total_lagu_sekarang).
        """
        pattern = os.path.join(music_dir, "*.opus")
        files = sorted(glob.glob(pattern))
        
        current_track = self.playlist[self.current_index] if (self.playlist and 0 <= self.current_index < len(self.playlist)) else None
        
        existing_set = set(os.path.abspath(f) for f in self.playlist)
        new_files = [f for f in files if os.path.abspath(f) not in existing_set]
        
        valid_files_set = set(os.path.abspath(f) for f in files)
        updated_playlist = [f for f in self.playlist if os.path.abspath(f) in valid_files_set]
        
        if new_files:
            updated_playlist.extend(new_files)

        self.playlist = updated_playlist

        if current_track and current_track in self.playlist:
            self.current_index = self.playlist.index(current_track)
        elif self.playlist:
            self.current_index = min(self.current_index, len(self.playlist) - 1)
            self._load_demuxer()
            
        return len(new_files), len(self.playlist)

    def _load_demuxer(self):

        self.track_frames_played = 0
        if self.demuxer:
            self.demuxer.close()
            self.demuxer = None
            
        if self.playlist and 0 <= self.current_index < len(self.playlist):
            path = self.playlist[self.current_index]
            try:
                self.demuxer = OpusDemuxer(path)
            except Exception as e:
                print(f"[Pacer Error] Gagal memuat {os.path.basename(path)}: {e}")
                self.demuxer = None

    def toggle_play(self):
        self.is_playing = not self.is_playing
        return self.is_playing

    def toggle_mute(self):
        self.is_muted = not self.is_muted
        return self.is_muted

    def next_track(self):
        if not self.playlist:
            return
        
        last_track = self.playlist[self.current_index] if 0 <= self.current_index < len(self.playlist) else None

        if self.current_index + 1 >= len(self.playlist):
            if self.loop_playlist:
                self.reshuffle_playlist_loop(avoid_repeat_track=last_track)
            else:
                self.current_index = 0
        else:
            self.current_index += 1

        self._load_demuxer()

    def prev_track(self):
        if not self.playlist:
            return
        self.current_index = (self.current_index - 1) % len(self.playlist)
        self._load_demuxer()

    def play_track_at_index(self, index: int):
        if not self.playlist:
            return
        if 0 <= index < len(self.playlist):
            self.current_index = index
            self._load_demuxer()

    def insert_next_track(self, file_path: str) -> int:
        if not os.path.exists(file_path):
            return -1
        # Jika file sudah ada di playlist, hapus duplikat lama jika perlu atau biarkan
        insert_pos = self.current_index + 1
        if insert_pos > len(self.playlist):
            insert_pos = len(self.playlist)
        self.playlist.insert(insert_pos, file_path)
        return insert_pos

    def get_status(self) -> dict:
        current_name = (
            os.path.basename(self.playlist[self.current_index])
            if self.playlist and 0 <= self.current_index < len(self.playlist)
            else "Tidak ada lagu"
        )
        duration_sec = self.demuxer.duration_sec if self.demuxer else 0.0
        elapsed_sec = self.track_frames_played * FRAME_DURATION_SEC
        return {
            "track": current_name,
            "index": self.current_index + 1 if self.playlist else 0,
            "total": len(self.playlist),
            "is_playing": self.is_playing,
            "is_muted": self.is_muted,
            "track_elapsed_sec": elapsed_sec,
            "track_duration_sec": duration_sec,
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
        if self._next_pacing_time is None:
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

        # Jika dalam kondisi Pause atau Playlist kosong
        if not self.is_playing or not self.demuxer:
            p = _create_silence_packet(self._pts)
            self._record_packet_stats(p, is_silence=True)
            self._notify_packet_listeners(OPUS_SILENCE_FRAME, SAMPLES_PER_FRAME)
            return p

        # Ambil paket raw Opus dari demuxer (lagu tetap berjalan di background)
        packet = self.demuxer.get_next_packet()

        # Jika lagu selesai (EOF)
        if packet is None:
            if self.loop_playlist and self.playlist:
                self.next_track()
                if self.demuxer:
                    packet = self.demuxer.get_next_packet()

        # Jika masih tidak ada paket (misal error membaca file), kirim hening
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
        if self.demuxer:
            self.demuxer.close()
            self.demuxer = None
        super().stop()
