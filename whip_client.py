import aiohttp
import asyncio
from aiortc import RTCPeerConnection, RTCSessionDescription, RTCConfiguration, RTCIceServer

class WHIPClient:
    """
    Klien WebRTC HTTP Ingestion Protocol (WHIP) untuk menghubungkan stream ke Meshcast.
    """
    def __init__(self, whip_url: str, track):
        self.whip_url = whip_url
        self.track = track
        self.pc = None
        self.session_url = None
        self.session = None

    async def connect(self):
        print(f"[WHIP] Memulai koneksi WebRTC ke: {self.whip_url}")
        
        # Konfigurasi ICE Server
        config = RTCConfiguration(
            iceServers=[RTCIceServer(urls=["stun:stun.l.google.com:19302"])]
        )
        self.pc = RTCPeerConnection(configuration=config)

        # Tambahkan track raw Opus ke Peer Connection
        self.pc.addTrack(self.track)

        # Buat SDP Offer
        offer = await self.pc.createOffer()
        await self.pc.setLocalDescription(offer)

        # Gunakan asyncio.Event untuk menunggu ICE gathering selesai tanpa busy-polling
        if self.pc.iceGatheringState != "complete":
            ice_complete_event = asyncio.Event()

            @self.pc.on("icegatheringstatechange")
            def on_ice_gathering_state_change():
                if self.pc and self.pc.iceGatheringState == "complete":
                    ice_complete_event.set()

            try:
                await asyncio.wait_for(ice_complete_event.wait(), timeout=10.0)
            except asyncio.TimeoutError:
                print("[WHIP Warning] ICE gathering timeout, menggunakan candidate yang ada.")

        sdp_offer = self.pc.localDescription.sdp
        headers = {
            "Content-Type": "application/sdp"
        }

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
                await self.pc.setRemoteDescription(answer)
                print("[WHIP] Koneksi WebRTC ke Meshcast BERHASIL terhubung!")

        except Exception as e:
            await self.close()
            raise RuntimeError(f"Gagal melakukan handshake WHIP: {e}")

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

        if self.pc:
            await self.pc.close()
            self.pc = None
            print("[WHIP] Koneksi ditutup.")
