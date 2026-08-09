# Opus WHIP RTP Pacer (Zero-CPU Streaming)

Sistem streaming audio bit-exact berlatensi ultra-rendah ke server WebRTC / WHIP Meshcast dari file lagu `.opus` tanpa re-encoding (Zero CPU).

## Fitur Utama
- **Zero-CPU Transcoding:** Membaca dan menyalurkan raw Opus frame 20ms langsung ke paket RTP RFC 7587.
- **Bit-Exact Quality:** 100% identik dengan file master asli di disk.
- **Interaktif:** Kontrol Play, Pause, Next/Previous Track, Mute, dan Playlist via terminal CLI.
- **YouTube Downloader Direct to NEXT SONG:** Unduh lagu dari YouTube/YouTube Music (`[y]`) di latar belakang, otomatis di-encode ke Opus 48kHz 20ms, disimpan di folder `Music`, dan disisipkan langsung sebagai **LAGU BERIKUTNYA** tanpa memutus siaran WebRTC!
- **Continuous Stream:** Menginjeksi Opus silence packet saat pause/mute agar koneksi WebRTC WHIP tetap online.

## Struktur Folder
```
Admin\Music\
├── Streaming MeshCast\   <-- Repository Aplikasi Python
│   ├── .venv\
│   ├── main.py
│   ├── rtp_pacer.py
│   ├── opus_demuxer.py
│   ├── whip_client.py
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
Buka terminal di dalam folder `Admin\Music\Streaming MeshCast`, lalu jalankan:

```powershell
uv run python main.py
```

### Tombol Pintas Terminal:
- `[SPACE / p]` : Pause / Resume
- `[n / >]`     : Next Track
- `[b / <]`     : Previous Track
- `[m]`         : Mute / Unmute
- `[y]`         : Paste URL YouTube -> Otomatis unduh & jadikan **NEXT SONG**
- `[l]`         : Cetak Daftar Playlist
- `[q]`         : Keluar dari Siaran
