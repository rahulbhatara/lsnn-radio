import asyncio
import aiohttp
from aiortc import RTCPeerConnection, RTCSessionDescription, RTCConfiguration, RTCIceServer


class WHIPClient:
    """
    Klien WebRTC HTTP Ingestion Protocol (WHIP) untuk menghubungkan stream ke Meshcast.
    Dilengkapi auto-reconnect dengan exponential backoff saat koneksi terputus.
    """
    def __init__(self, whip_url: str, track, auto_reconnect: bool = True):
        self.whip_url = whip_url
        self.track = track
        self.auto_reconnect = auto_reconnect
        self.pc: RTCPeerConnection | None = None
        self.session_url: str | None = None
        self.session: aiohttp.ClientSession | None = None
        self._monitor_task: asyncio.Task | None = None
        self._closing = False

    async def connect(self):
        await self._connect_once()
        if self.auto_reconnect:
            self._monitor_task = asyncio.create_task(self._monitor_loop())

    async def _connect_once(self):
        print(f"[WHIP] Memulai koneksi WebRTC ke: {self.whip_url}")

        # Konfigurasi ICE Server
        config = RTCConfiguration(
            iceServers=[RTCIceServer(urls=["stun:stun.l.google.com:19302"])]
        )
        pc = RTCPeerConnection(configuration=config)
        self.pc = pc

        # Tambahkan track raw Opus ke Peer Connection
        pc.addTrack(self.track)

        # Buat SDP Offer
        offer = await pc.createOffer()
        await pc.setLocalDescription(offer)

        # Gunakan asyncio.Event untuk menunggu ICE gathering selesai tanpa busy-polling
        if pc.iceGatheringState != "complete":
            ice_complete_event = asyncio.Event()

            @pc.on("icegatheringstatechange")
            def on_ice_gathering_state_change():
                if pc.iceGatheringState == "complete":
                    ice_complete_event.set()

            try:
                await asyncio.wait_for(ice_complete_event.wait(), timeout=10.0)
            except asyncio.TimeoutError:
                print("[WHIP Warning] ICE gathering timeout, menggunakan candidate yang ada.")

        sdp_offer = pc.localDescription.sdp
        headers = {
            "Content-Type": "application/sdp"
        }

        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()

        try:
            async with self.session.post(self.whip_url, data=sdp_offer, headers=headers) as resp:
                if resp.status not in (200, 201):
                    body = await resp.text()
                    raise RuntimeError(f"Server WHIP menolak koneksi (HTTP {resp.status}): {body}")

                sdp_answer = await resp.text()
                self.session_url = resp.headers.get("Location")

                # Pasang SDP Answer dari server
                answer = RTCSessionDescription(sdp=sdp_answer, type="answer")
                await pc.setRemoteDescription(answer)
                print("[WHIP] Koneksi WebRTC ke Meshcast BERHASIL terhubung!")

        except Exception as e:
            await self._close_pc()
            raise RuntimeError(f"Gagal melakukan handshake WHIP: {e}")

    async def _close_pc(self):
        if self.pc:
            try:
                await self.pc.close()
            except Exception:
                pass
            self.pc = None

    async def _reconnect(self):
        print("[WHIP] Koneksi terputus, mencoba reconnect...")
        await self._close_pc()
        # Tunggu track selesai dipakai oleh peer connection lama
        await asyncio.sleep(0.2)
        await self._connect_once()

    async def _monitor_loop(self):
        """Supervisi koneksi: reconnect otomatis dengan exponential backoff (1s..30s)."""
        backoff = 1.0
        while not self._closing:
            await asyncio.sleep(1.0)
            pc = self.pc
            if pc is None:
                continue

            state = pc.connectionState
            if state == "failed":
                try:
                    await self._reconnect()
                    backoff = 1.0
                except Exception as e:
                    print(f"[WHIP Reconnect] Gagal (coba lagi dalam {backoff:.0f}s): {e}")
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, 30.0)

    async def get_whip_stats(self) -> dict:
        if not self.pc:
            return {
                "connection_state": "closed",
                "ice_connection_state": "closed",
                "ice_gathering_state": "closed",
                "dtls_state": "closed",
                "packets_sent": 0,
                "bytes_sent": 0,
            }

        try:
            stats_report = await self.pc.getStats()
            packets_sent = 0
            bytes_sent = 0
            dtls_state = "unknown"

            for stat in stats_report.values():
                if stat.type == "outbound-rtp":
                    packets_sent = getattr(stat, "packetsSent", packets_sent)
                    bytes_sent = getattr(stat, "bytesSent", bytes_sent)
                elif stat.type == "transport":
                    dtls_state = getattr(stat, "dtlsState", dtls_state)

            return {
                "connection_state": self.pc.connectionState or "unknown",
                "ice_connection_state": self.pc.iceConnectionState or "unknown",
                "ice_gathering_state": self.pc.iceGatheringState or "unknown",
                "dtls_state": dtls_state,
                "packets_sent": packets_sent,
                "bytes_sent": bytes_sent,
            }
        except Exception:
            return {
                "connection_state": getattr(self.pc, "connectionState", "error"),
                "ice_connection_state": getattr(self.pc, "iceConnectionState", "error"),
                "ice_gathering_state": getattr(self.pc, "iceGatheringState", "error"),
                "dtls_state": "error",
                "packets_sent": 0,
                "bytes_sent": 0,
            }

    async def close(self):
        self._closing = True
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except (asyncio.CancelledError, Exception):
                pass
            self._monitor_task = None

        if self.session_url and self.session:
            try:
                # Mengirim HTTP DELETE ke session URL untuk mengakhiri sesi WHIP secara sopan
                async with self.session.delete(self.session_url) as resp:
                    pass
            except Exception:
                pass

        if self.session:
            await self.session.close()
            self.session = None

        await self._close_pc()
        print("[WHIP] Koneksi ditutup.")
