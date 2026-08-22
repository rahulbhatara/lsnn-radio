import time
import queue
import threading
from typing import List, Dict, Any, Optional
import numpy as np
import sounddevice as sd
import av

OPUS_SILENCE_FRAME = b'\xf8\xff\xfe'
SAMPLES_PER_FRAME = 960  # 20ms @ 48000 Hz
SAMPLE_RATE = 48000
CHANNELS = 2

def get_windows_input_devices() -> List[Dict[str, Any]]:
    """
    Mengambil daftar perangkat audio input yang didukung di Windows (MME, WASAPI, DirectSound).
    Mengabaikan host API Windows WDM-KS yang tidak kompatibel dengan PortAudio stream callback.
    """
    try:
        devices = sd.query_devices()
        hostapis = sd.query_hostapis()
    except Exception as e:
        print(f"[AudioCapture Error] Gagal memindai perangkat audio: {e}")
        return []
    
    input_devices = []
    for idx, d in enumerate(devices):
        if d.get('max_input_channels', 0) > 0:
            hostapi_idx = d.get('hostapi', 0)
            hostapi_name = hostapis[hostapi_idx]['name'] if hostapi_idx < len(hostapis) else "Unknown"
            
            # Abaikan WDM-KS karena memicu error 'Blocking API not supported yet' dan C-crash di PortAudio
            if "WDM-KS" in hostapi_name.upper():
                continue
                
            display_name = f"{d['name']} ({hostapi_name})"
            input_devices.append({
                "id": idx,
                "name": d['name'],
                "hostapi": hostapi_name,
                "channels": d['max_input_channels'],
                "default_samplerate": d['default_samplerate'],
                "display_name": display_name
            })
    return input_devices

class AudioCaptureWorker:
    """
    Worker penangkap audio PCM real-time dari Windows Audio Device (Microphone/Stereo Mix)
    dan meng-encode-nya ke paket Raw Opus 20ms (48kHz stereo 192kbps) tanpa delay.
    Thread-safe menggunakan RLock dan terlindungi dari race condition saat stop/start.
    """
    def __init__(self, device_id: Optional[int] = None, bitrate: int = 192000):
        self.device_id = device_id
        self.bitrate = bitrate
        self.queue = queue.Queue(maxsize=150)  # ~3 detik buffer audio
        
        self.stream: Optional[sd.InputStream] = None
        self.codec: Optional[av.CodecContext] = None
        self.is_running = False
        self._lock = threading.RLock()  # Reentrant Lock untuk mencegah deadlock saat stop() dipanggil di dalam start()
        
        # Audio level telemetry (RMS / Peak)
        self.current_level_db = -60.0
        self.current_level_linear = 0.0
        self.frames_captured = 0
        self.frames_encoded = 0

    def _init_codec(self) -> bool:
        try:
            codec = av.CodecContext.create('libopus', 'w')
            codec.sample_rate = SAMPLE_RATE
            codec.layout = 'stereo'
            codec.format = 's16'
            codec.bit_rate = self.bitrate
            codec.open()
            self.codec = codec
            return True
        except Exception as e:
            print(f"[AudioCapture Error] Gagal inisialisasi PyAV libopus encoder: {e}")
            self.codec = None
            return False

    def _audio_callback(self, indata: np.ndarray, frames: int, time_info, status):
        """
        Callback PortAudio real-time yang dipanggil per blok 960 sampel (20ms).
        Berjalan pada background C-thread milik PortAudio.
        """
        if not self.is_running:
            return

        codec_ref = self.codec
        if codec_ref is None:
            return

        # Hitung level sinyal audio (RMS & Peak untuk VU Meter GUI)
        try:
            float_data = indata.astype(np.float32) / 32768.0
            peak = float(np.max(np.abs(float_data)))
            self.current_level_linear = peak
            if peak > 1e-5:
                self.current_level_db = max(-60.0, 20.0 * np.log10(peak))
            else:
                self.current_level_db = -60.0
        except Exception:
            pass

        self.frames_captured += 1

        # Pastikan data berformat stereo (2 channels) int16 dan C-contiguous
        try:
            if indata.shape[1] == 1:
                stereo_data = np.repeat(indata, 2, axis=1)
            else:
                stereo_data = indata[:, :2]
            
            stereo_contiguous = np.ascontiguousarray(stereo_data, dtype=np.int16)

            # Encode PCM -> Raw Opus Frame 20ms
            frame = av.AudioFrame.from_ndarray(stereo_contiguous.reshape(1, -1), format='s16', layout='stereo')
            frame.sample_rate = SAMPLE_RATE
            packets = codec_ref.encode(frame)
            for pkt in packets:
                raw_bytes = bytes(pkt)
                self.frames_encoded += 1
                try:
                    self.queue.put_nowait(raw_bytes)
                except queue.Full:
                    # Jika queue penuh (underrun/lag), drop frame paling tua
                    try:
                        self.queue.get_nowait()
                        self.queue.put_nowait(raw_bytes)
                    except Exception:
                        pass
        except Exception:
            pass

    def start(self, device_id: Optional[int] = None) -> bool:
        with self._lock:
            if self.is_running:
                self.stop()

            if device_id is not None:
                self.device_id = device_id

            if not self._init_codec():
                return False

            # Tentukan channel yang didukung perangkat
            input_channels = 2
            if self.device_id is not None:
                try:
                    dev_info = sd.query_devices(self.device_id)
                    max_in = dev_info.get('max_input_channels', 2)
                    input_channels = 1 if max_in == 1 else 2
                except Exception:
                    input_channels = 2

            try:
                # Buka InputStream PortAudio dengan blocksize 960 (20ms @ 48kHz)
                self.stream = sd.InputStream(
                    samplerate=SAMPLE_RATE,
                    channels=input_channels,
                    dtype='int16',
                    blocksize=SAMPLES_PER_FRAME,
                    device=self.device_id,
                    callback=self._audio_callback
                )
                self.stream.start()
                self.is_running = True
                print(f"[AudioCapture] Live Audio Input aktif (Device ID: {self.device_id}, Ch: {input_channels})")
                return True
            except Exception as e:
                print(f"[AudioCapture Error] Gagal membuka audio device {self.device_id}: {e}")
                self.is_running = False
                if self.stream is not None:
                    try:
                        self.stream.close()
                    except Exception:
                        pass
                    self.stream = None
                self.codec = None
                return False

    def stop(self):
        with self._lock:
            self.is_running = False
            
            # Hentikan dan tutup stream PortAudio terlebih dahulu agar callback berhenti total
            if self.stream is not None:
                try:
                    self.stream.stop()
                except Exception:
                    pass
                try:
                    self.stream.close()
                except Exception:
                    pass
                self.stream = None

            # Setelah stream C PortAudio selesai, aman untuk menghapus codec
            self.codec = None
            
            # Bersihkan sisa queue buffer
            while not self.queue.empty():
                try:
                    self.queue.get_nowait()
                except Exception:
                    break
                    
            self.current_level_db = -60.0
            self.current_level_linear = 0.0
            print("[AudioCapture] Live Audio Input dihentikan.")

    def get_next_opus_packet(self) -> Optional[bytes]:
        """
        Mengambil paket raw Opus 20ms berikutnya dari antrian capture.
        Mengembalikan None jika antrian kosong.
        """
        try:
            return self.queue.get_nowait()
        except queue.Empty:
            return None

    def get_stats(self) -> Dict[str, Any]:
        return {
            "is_running": self.is_running,
            "device_id": self.device_id,
            "level_db": self.current_level_db,
            "level_linear": self.current_level_linear,
            "queue_size": self.queue.qsize(),
            "frames_captured": self.frames_captured,
            "frames_encoded": self.frames_encoded,
        }

