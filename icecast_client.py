import os
import time
import base64
import struct
import random
import asyncio
from typing import Optional, Dict, Any
from collections import deque

# --------------------------------------------------------------------------
# Ogg Opus Container Utilities (Zero-CPU Ogg Page Packaging)
# --------------------------------------------------------------------------

OGG_CRC_TABLE = []
for i in range(256):
    r = i << 24
    for _ in range(8):
        if r & 0x80000000:
            r = ((r << 1) ^ 0x04C11DB7) & 0xFFFFFFFF
        else:
            r = (r << 1) & 0xFFFFFFFF
    OGG_CRC_TABLE.append(r)

def calculate_ogg_crc(data: bytes) -> int:
    crc = 0
    for b in data:
        crc = ((crc << 8) & 0xFFFFFFFF) ^ OGG_CRC_TABLE[((crc >> 24) & 0xFF) ^ b]
    return crc

def make_ogg_page(packet_data: bytes, header_type: int, granule_pos: int, serial_no: int, seq_no: int) -> bytes:
    """
    Mengemas paket bytes menjadi Ogg Page standar RFC 3533 lengkap dengan lacing & CRC32.
    """
    rem = len(packet_data)
    lacing_vals = []
    while rem >= 255:
        lacing_vals.append(255)
        rem -= 255
    lacing_vals.append(rem)
    
    seg_table = bytes(lacing_vals)
    # Header format: magic (4s), version (B), header_type (B), granule_pos (q), serial_no (I), seq_no (I), crc (I), num_segments (B)
    header_buf = struct.pack(
        '<4sBBqIIIB',
        b'OggS',
        0,
        header_type,
        granule_pos,
        serial_no,
        seq_no,
        0,  # CRC awal 0
        len(lacing_vals)
    ) + seg_table

    full_page = header_buf + packet_data
    crc = calculate_ogg_crc(full_page)
    
    # Sisipkan nilai CRC32 pada offset 22..26
    final_header = header_buf[:22] + struct.pack('<I', crc) + header_buf[26:]
    return final_header + packet_data

# --------------------------------------------------------------------------
# Icecast Client Class
# --------------------------------------------------------------------------

class IcecastClient:
    """
    Klien pengunggah HTTP source untuk Icecast2 server yang mengalirkan Ogg Opus bitstream.
    """
    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 8000,
        mount: str = "/lsnn_radio",
        password: str = "hackme",
        public_url: str = "https://radio.samf.fun/lsnn_radio"
    ):
        self.host = host
        self.port = port
        self.mount = mount if mount.startswith("/") else f"/{mount}"
        self.password = password
        self.public_url = public_url

        self.reader: Optional[asyncio.StreamReader] = None
        self.writer: Optional[asyncio.StreamWriter] = None
        self.is_connected = False
        
        self.serial_no = random.randint(1, 0x7FFFFFFF)
        self.seq_no = 0
        self.pts_samples = 0

        # Queue untuk menerima audio packet dari Pacer
        self.packet_queue = asyncio.Queue(maxsize=200)
        self.streaming_task: Optional[asyncio.Task] = None

        # Statistics & Telemetry
        self.start_time = time.monotonic()
        self.total_bytes_sent = 0
        self.total_packets_sent = 0
        self._sliding_bytes = deque()  # (timestamp, byte_count)

    def _create_auth_header(self) -> str:
        auth_str = f"source:{self.password}"
        b64_auth = base64.b64encode(auth_str.encode('utf-8')).decode('ascii')
        return f"Basic {b64_auth}"

    def _get_headers_pages(self) -> list[bytes]:
        """
        Menghasilkan 2 Ogg header page wajib untuk Opus (OpusHead dan OpusTags).
        """
        self.seq_no = 0
        # Header 1: OpusHead (19 bytes)
        # Pre-skip 312, 48000Hz, 2 channels
        opus_head = b'OpusHead\x01\x02\x38\x01\x80\xbb\x00\x00\x00\x00\x00'
        page0 = make_ogg_page(
            packet_data=opus_head,
            header_type=0x02,  # BOS (Beginning of Stream)
            granule_pos=0,
            serial_no=self.serial_no,
            seq_no=self.seq_no
        )
        self.seq_no += 1

        # Header 2: OpusTags (vendor string)
        vendor = b'MeshCast DualStream'
        opus_tags = b'OpusTags' + struct.pack('<I', len(vendor)) + vendor + struct.pack('<I', 0)
        page1 = make_ogg_page(
            packet_data=opus_tags,
            header_type=0x00,
            granule_pos=0,
            serial_no=self.serial_no,
            seq_no=self.seq_no
        )
        self.seq_no += 1
        return [page0, page1]

    async def connect(self) -> bool:
        print(f"[Icecast] Menghubungkan ke http://{self.host}:{self.port}{self.mount} ...")
        try:
            self.reader, self.writer = await asyncio.open_connection(self.host, self.port)
            
            headers = (
                f"SOURCE {self.mount} HTTP/1.0\r\n"
                f"Authorization: {self._create_auth_header()}\r\n"
                f"Content-Type: audio/ogg\r\n"
                f"User-Agent: MeshCast-IcecastStreamer/1.0\r\n"
                f"Ice-Name: Samf Radio Dual Stream\r\n"
                f"Ice-Description: Bit-Exact Raw Opus Stream\r\n"
                f"Ice-Public: 1\r\n"
                f"\r\n"
            )
            self.writer.write(headers.encode('utf-8'))
            await self.writer.drain()

            # Baca respon HTTP server
            response_line = await asyncio.wait_for(self.reader.readline(), timeout=5.0)
            resp_str = response_line.decode('utf-8', errors='ignore')
            
            if "200" not in resp_str:
                print(f"[Icecast Error] Server menolak koneksi: {resp_str.strip()}")
                await self.close()
                return False

            # Kirimkan OpusHead & OpusTags Ogg Pages pertama
            header_pages = self._get_headers_pages()
            for page in header_pages:
                await self._send_chunk(page)

            self.is_connected = True
            self.start_time = time.monotonic()
            
            # Meluncurkan background loop penyalur paket
            self.streaming_task = asyncio.create_task(self._streaming_loop())
            print(f"[Icecast] Terhubung ke Icecast2! Stream publik: {self.public_url}")
            return True

        except Exception as e:
            print(f"[Icecast Error] Gagal terhubung ke Icecast2: {e}")
            await self.close()
            return False

    async def _send_chunk(self, data: bytes):
        if not self.writer:
            return
        
        self.writer.write(data)
        await self.writer.drain()

        # Update telemetry
        pkt_len = len(data)
        self.total_bytes_sent += pkt_len
        self.total_packets_sent += 1
        
        now = time.monotonic()
        self._sliding_bytes.append((now, pkt_len))
        cutoff = now - 3.0
        while self._sliding_bytes and self._sliding_bytes[0][0] < cutoff:
            self._sliding_bytes.popleft()

    def enqueue_opus_frame(self, raw_opus_bytes: bytes, samples: int = 960):
        """
        Callback non-blocking dari RawOpusTrack untuk memasukkan paket 20ms.
        """
        if not self.is_connected:
            return
        
        try:
            self.packet_queue.put_nowait((raw_opus_bytes, samples))
        except asyncio.QueueFull:
            # Membuang paket tercecer paling lama jika queue penuh untuk mencegah memory growth
            try:
                self.packet_queue.get_nowait()
                self.packet_queue.put_nowait((raw_opus_bytes, samples))
            except Exception:
                pass

    async def _streaming_loop(self):
        while self.is_connected:
            try:
                raw_opus_bytes, samples = await self.packet_queue.get()
                self.pts_samples += samples
                
                # Kemas raw opus frame ke Ogg Page
                ogg_page = make_ogg_page(
                    packet_data=raw_opus_bytes,
                    header_type=0x00,
                    granule_pos=self.pts_samples,
                    serial_no=self.serial_no,
                    seq_no=self.seq_no
                )
                self.seq_no += 1
                
                await self._send_chunk(ogg_page)
                self.packet_queue.task_done()
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"[Icecast Loop Error] {e}")
                self.is_connected = False
                break

    def get_icecast_stats(self) -> Dict[str, Any]:
        now = time.monotonic()
        uptime = max(0.1, now - self.start_time)
        
        recent_bytes = sum(b for t, b in self._sliding_bytes)
        window_dur = (self._sliding_bytes[-1][0] - self._sliding_bytes[0][0]) if len(self._sliding_bytes) > 1 else 3.0
        window_dur = max(0.1, window_dur)
        
        inst_bitrate = (recent_bytes * 8 / window_dur) / 1000.0 if len(self._sliding_bytes) > 1 else 0.0
        avg_bitrate = (self.total_bytes_sent * 8 / uptime) / 1000.0

        return {
            "is_connected": self.is_connected,
            "host": self.host,
            "port": self.port,
            "mount": self.mount,
            "public_url": self.public_url,
            "uptime_sec": uptime,
            "total_bytes": self.total_bytes_sent,
            "total_packets": self.total_packets_sent,
            "instant_bitrate_kbps": inst_bitrate,
            "avg_bitrate_kbps": avg_bitrate
        }

    async def close(self):
        self.is_connected = False
        if self.streaming_task:
            self.streaming_task.cancel()
            self.streaming_task = None
            
        if self.writer:
            try:
                # Kirim penutup chunk HTTP (0\r\n\r\n)
                self.writer.write(b"0\r\n\r\n")
                await self.writer.drain()
                self.writer.close()
                await self.writer.wait_closed()
            except Exception:
                pass
            self.writer = None
            self.reader = None
        print("[Icecast] Koneksi ke Icecast ditutup.")
