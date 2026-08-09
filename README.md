# Raw Opus Dual Streamer (MeshCast & Icecast2 via Cloudflared)

Sistem streaming audio bit-exact berlatensi ultra-rendah dengan **Dual Stream Simultan** ke server **WebRTC / WHIP Meshcast** dan **Icecast2 Self-Hosted** (ditunnel publik via **Cloudflared** ke `https://radio.samf.fun/lsnn_radio`) dari file lagu `.opus` tanpa re-encoding (Zero CPU).

## Fitur Utama
- **Dual Stream Simultan:** Memancar secara serentak ke **MeshCast WebRTC WHIP** (`cn1.meshcast.io/whip/lsnn_radio`) dan **Icecast2** (`localhost:8000/lsnn_radio` -> `https://radio.samf.fun/lsnn_radio`).
- **Auto-Service Manager:** Otomatis mendeteksi & meluncurkan servis `Icecast2` dan `Cloudflared` saat `uv run python main.py` dijalankan.
- **Zero-CPU Ogg Opus Streamer:** Membaca & menyalurkan raw Opus frame 20ms langsung ke paket RTP RFC 7587 (WebRTC) dan Ogg Opus Pages RFC 3533 (Icecast) tanpa re-encoding.
- **Bit-Exact Quality:** 100% identik dengan file master asli di disk.
- **Interaktif CLI Dashboard:** Kontrol Play, Pause, Next/Previous Track, Mute, Live Search Playlist, dan statistik live dual-stream real-time.
- **YouTube Downloader Direct to NEXT SONG:** Unduh lagu dari YouTube/YouTube Music (`[y]`) di latar belakang, otomatis di-encode ke Opus 48kHz 20ms, disimpan di folder `Music`, dan disisipkan langsung sebagai **LAGU BERIKUTNYA** tanpa memutus siaran!
- **Continuous Stream:** Menginjeksi Opus silence packet saat pause/mute agar kedua koneksi stream tetap online.

## Struktur Folder
```
Admin\Music\
├── Streaming MeshCast\   <-- Repository Aplikasi Python
│   ├── .venv\
│   ├── main.py
│   ├── service_manager.py
│   ├── icecast_client.py
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

Sistem akan otomatis memeriksa/menjalankan Icecast2 & Cloudflared, lalu menghubungkan siaran ke:
1. **MeshCast (WebRTC)**: `https://cn1.meshcast.io/whip/lsnn_radio`
2. **Icecast2 (Publik)**: `https://radio.samf.fun/lsnn_radio`

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



