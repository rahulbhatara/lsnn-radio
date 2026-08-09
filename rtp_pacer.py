import os
import time
import asyncio
import av
from fractions import Fraction
from aiortc import MediaStreamTrack
from opus_demuxer import OpusDemuxer

# Opus Silence Frame (3 bytes) mewakili 20ms audio hening pada 48kHz
OPUS_SILENCE_FRAME = b'\xf8\xff\xfe'
SAMPLES_PER_FRAME = 960  # 20ms @ 48000 Hz
FRAME_DURATION_SEC = 0.020  # 20ms

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
        
        if self.playlist:
            self._load_demuxer()

    def _load_demuxer(self):
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
        self.current_index = (self.current_index + 1) % len(self.playlist)
        self._load_demuxer()

    def prev_track(self):
        if not self.playlist:
            return
        self.current_index = (self.current_index - 1) % len(self.playlist)
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
        return {
            "track": current_name,
            "index": self.current_index + 1 if self.playlist else 0,
            "total": len(self.playlist),
            "is_playing": self.is_playing,
            "is_muted": self.is_muted,
        }

    async def recv(self) -> av.Packet:
        # Pacing kontrol jam real-time (20ms per frame)
        now = time.monotonic()
        if self._next_pacing_time is None:
            self._next_pacing_time = now + FRAME_DURATION_SEC
        else:
            delay = self._next_pacing_time - now
            if delay > 0:
                await asyncio.sleep(delay)
            self._next_pacing_time += FRAME_DURATION_SEC

        # Naikkan timestamp PTS secara linier dan bertahap (+960 samples per 20ms)
        self._pts += SAMPLES_PER_FRAME

        # Jika dalam kondisi Pause atau Mute atau Playlist kosong
        if not self.is_playing or self.is_muted or not self.demuxer:
            p = av.Packet(OPUS_SILENCE_FRAME)
            p.pts = self._pts
            p.time_base = Fraction(1, 48000)
            return p

        # Ambil paket raw Opus dari demuxer
        packet = self.demuxer.get_next_packet()

        # Jika lagu selesai (EOF)
        if packet is None:
            if self.loop_playlist and self.playlist:
                self.next_track()
                if self.demuxer:
                    packet = self.demuxer.get_next_packet()

        # Jika masih tidak ada paket (misal error membaca file), kirim hening
        if packet is None:
            p = av.Packet(OPUS_SILENCE_FRAME)
            p.pts = self._pts
            p.time_base = Fraction(1, 48000)
            return p

        # Atur timestamp linier pada paket asli dari file
        packet.pts = self._pts
        packet.time_base = Fraction(1, 48000)
        return packet

    def stop(self):
        if self.demuxer:
            self.demuxer.close()
            self.demuxer = None
        super().stop()
