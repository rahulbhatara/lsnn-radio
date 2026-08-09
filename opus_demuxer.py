import os
import av
from fractions import Fraction

class OpusDemuxer:
    """
    Demuxer untuk membaca paket raw Opus dari file Ogg Opus tanpa pendekodean ke PCM.
    """
    def __init__(self, file_path: str):
        self.file_path = file_path
        self.container = None
        self.audio_stream = None
        self.packet_generator = None
        self._open()

    def _open(self):
        if not os.path.exists(self.file_path):
            raise FileNotFoundError(f"File tidak ditemukan: {self.file_path}")
        
        self.container = av.open(self.file_path)
        if not self.container.streams.audio:
            raise ValueError(f"Tidak ada stream audio di file: {self.file_path}")
            
        self.audio_stream = self.container.streams.audio[0]
        self.packet_generator = self._read_packets()

    @property
    def duration_sec(self) -> float:
        if self.audio_stream and self.audio_stream.duration is not None and self.audio_stream.time_base:
            return float(self.audio_stream.duration * self.audio_stream.time_base)
        elif self.container and self.container.duration is not None:
            return float(self.container.duration / av.TIME_BASE)
        return 0.0

    def _read_packets(self):
        for packet in self.container.demux(self.audio_stream):
            if packet.pts is not None or packet.is_keyframe:
                raw_bytes = bytes(packet)
                # Skip Ogg Opus headers
                if raw_bytes.startswith(b'OpusHead') or raw_bytes.startswith(b'OpusTags'):
                    continue
                yield packet

    def get_next_packet(self):
        """
        Mengembalikan paket raw Opus berikutnya dari file.
        Jika file habis, mengembalikan None.
        """
        if self.packet_generator is None:
            return None
        try:
            return next(self.packet_generator)
        except StopIteration:
            return None
        except Exception as e:
            print(f"[Demuxer Error] File {os.path.basename(self.file_path)}: {e}")
            return None

    def close(self):
        if self.container:
            try:
                self.container.close()
            except Exception:
                pass
            self.container = None
            self.packet_generator = None
