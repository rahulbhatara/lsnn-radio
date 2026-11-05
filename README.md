# LSNN Radio — MeshCast Multi-Streamer

A lightweight, easy-to-use desktop app for broadcasting live radio. Stream your local music library and microphone simultaneously across **WebRTC (MeshCast)**, **HLS**, and **Icecast**—with built-in **Cloudflare Tunnel** support so you can go live without complex network setup.

## Key Features

- **Multi-Platform Streaming:** Broadcast simultaneously to WebRTC (ultra-low latency), HLS, and Icecast (`/live`) from a single app.
- **CPU-Friendly Playback:** Plays `.opus` audio directly without re-encoding, keeping CPU usage near zero while automatically converting other formats (`.mp3`, `.wav`, `.flac`, `.m4a`) in the background.
- **Smart Auto-DJ & Queue:** Manage a priority song queue or let Auto-DJ shuffle your music library seamlessly without repeating tracks back-to-back.
- **Built-in YouTube Downloader:** Paste any YouTube link to automatically download, convert, and add the audio to your queue.
- **Instant Public Links:** Go live to the internet in one click using Cloudflare Quick Tunnels (no account or port-forwarding needed) or connect your own custom domain.
- **Modern Dark Interface:** Clean desktop UI featuring a searchable music library, drag-and-drop queue, live microphone volume meter, and real-time listener stats.

## Requirements

- **OS:** Windows 10/11 or Linux
- **Python:** 3.12 or newer
- **Package Manager:** [uv](https://github.com/astral-sh/uv) (recommended) or `pip`
- **Optional Tools:** `ffmpeg` (for faster audio conversion) and `cloudflared` (for public streaming links)

## Quick Start

1. **Clone the repository:**
   ```bash
   git clone https://github.com/rahulbhatara/lsnn-radio.git
   cd lsnn-radio
   ```

2. **Install dependencies:**
   ```bash
   uv sync
   ```

3. **Run the app:**
   ```bash
   uv run python main.py
   ```

## Configuration

You don't need to edit code or configuration files manually. Click the **Settings** button inside the app to set up:

- Your local **Music Folder** location.
- **Streaming URLs & Ports** (MeshCast WHIP endpoint, local HLS/Icecast port).
- **Cloudflare Tunnel Mode** (*Quick* for an instant temporary link, *Custom* for your own domain, or *None* for local network only).

*(Advanced users can also edit `config.json` directly using `config.example.json` as a reference).*

## License

MIT License
