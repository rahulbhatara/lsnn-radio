# Raw Opus Dual Streamer (MeshCast & HLS Cloudflare CDN)

Sistem streaming audio bit-exact berlatensi ultra-rendah dengan **Dual Stream Simultan** ke server **WebRTC / WHIP Meshcast** dan **HLS Streamer (fMP4 Opus)** yang ditunnel publik via **Cloudflared** ke Cloudflare Edge CDN (`https://radio.samf.fun/live.m3u8`) dari file lagu `.opus` tanpa re-encoding (Zero CPU).

## Fitur Utama
- **Dual Stream Simultan:** Memancar secara serentak ke **MeshCast WebRTC WHIP** (`cn1.meshcast.io/whip/lsnn_radio`) dan **HLS Cloudflare CDN** (`https://radio.samf.fun/live.m3u8`).
- **Cloudflare Edge CDN Caching:** Segmen audio fMP4 (`.m4s`) di-cache 100% di Edge Cloudflare. PC Anda hanya mengirimkan data 1x (~128 kbps) meskipun ada ribuan/jutaan pendengar bersamaan!
- **Auto-Service Manager:** Otomatis mendeteksi & meluncurkan `Cloudflared` tunnel saat `uv run python main.py` dijalankan.
- **Zero-CPU HLS & RTP Segmenter:** Membaca & menyalurkan raw Opus frame 20ms langsung ke paket RTP RFC 7587 (WebRTC) dan HLS fMP4 RFC 8216 (Cloudflare CDN) tanpa re-encoding.
- **Bit-Exact Quality:** 100% identik dengan file master asli di disk.
- **Interaktif CLI Dashboard:** Kontrol Play, Pause, Next/Previous Track, Mute, Live Search Playlist (`[f]`), Rescan Disk (`[u]`), dan statistik live dual-stream real-time.
- **YouTube Downloader Direct to NEXT SONG:** Unduh lagu dari YouTube/YouTube Music (`[y]`) di latar belakang, otomatis di-encode ke Opus 48kHz 20ms, disimpan di folder `Music`, dan disisipkan langsung sebagai **LAGU BERIKUTNYA** tanpa memutus siaran!
- **Continuous Stream:** Menginjeksi Opus silence packet saat pause/mute agar kedua koneksi stream tetap online.

## Struktur Folder
```
Admin\Music\
├── Streaming MeshCast\   <-- Repository Aplikasi Python
│   ├── .venv\
│   ├── main.py
│   ├── service_manager.py
│   ├── hls_streamer.py
│   ├── whip_client.py
│   ├── rtp_pacer.py
│   ├── opus_demuxer.py
│   ├── cli_controller.py
│   ├── yt_downloader.py
│   ├── convert_playlist.py
│   └── pyproject.toml
├── Car's Outside.opus
├── Die With A Smile.opus
├── Here's Your Perfect.opus
├── When I Was Your Man.opus
├── bergema sampai selamanya.opus
└── penjaga hati.opus
```

## Cara Menjalankan
Cukup buka terminal di folder `Admin\Music\Streaming MeshCast`, lalu jalankan:

```powershell
uv run python main.py
```

Sistem akan otomatis memeriksa/menjalankan Cloudflared Tunnel dan menghubungkan siaran ke:
1. **MeshCast (WebRTC)**: `https://cn1.meshcast.io/whip/lsnn_radio`
2. **HLS Cloudflare CDN (Publik)**: `https://radio.samf.fun/live.m3u8`

### Tombol Pintas Terminal:
- `[SPACE / p]` : Pause / Resume
- `[n / >]`     : Next Track
- `[b / <]`     : Previous Track
- `[m]`         : Mute / Unmute
- `[s]`         : Toggle Detailed Dual Stream Stats
- `[y]`         : Paste URL YouTube -> Otomatis unduh & jadikan **NEXT SONG**
- `[u]`         : Rescan / Reload Playlist Folder (Update lagu baru dari disk)
- `[l]`         : Switch ke Mode Playlist Lagu & Live Search (`[f]`)
- `[q]`         : Keluar dari Siaran




