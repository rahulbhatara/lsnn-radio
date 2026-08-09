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

        # Tunggu ICE gathering selesai agar SDP offer lengkap
        while self.pc.iceGatheringState != "complete":
            await asyncio.sleep(0.1)

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
                print("[WHIP] Koneksi WebRTC ke Meshcast BERHASIL terhubung! 🚀")

        except Exception as e:
            await self.close()
            raise RuntimeError(f"Gagal melakukan handshake WHIP: {e}")

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
