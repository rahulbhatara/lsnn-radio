import sys
import os
import time
import asyncio
import msvcrt
from yt_downloader import download_youtube_opus

def format_duration(seconds: float) -> str:
    total_sec = int(seconds)
    hours = total_sec // 3600
    minutes = (total_sec % 3600) // 60
    sec = total_sec % 60
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{sec:02d}"
    return f"{minutes:02d}:{sec:02d}"

def format_bytes(num_bytes: int) -> str:
    if num_bytes < 1024:
        return f"{num_bytes} B"
    elif num_bytes < 1024 * 1024:
        return f"{num_bytes / 1024:.2f} KB"
    else:
        return f"{num_bytes / (1024 * 1024):.2f} MB"

def format_progress(elapsed_sec: float, duration_sec: float, bar_width: int = 15) -> str:
    elapsed_str = format_duration(elapsed_sec)
    if duration_sec <= 0:
        return f"{elapsed_str} / 00:00"
    
    dur_str = format_duration(duration_sec)
    ratio = min(1.0, max(0.0, elapsed_sec / duration_sec))
    filled = int(ratio * bar_width)
    if filled > 0:
        bar = "=" * (filled - 1) + ">" + "." * (bar_width - filled)
    else:
        bar = "." * bar_width
    pct = int(ratio * 100)
    return f"{elapsed_str} / {dur_str} [{bar}] {pct}%"

class CLIController:
    """
    Pengontrol terminal interaktif tanpa perlu menekan Enter (msvcrt di Windows),
    dilengkapi fitur visualisasi statistik dual-stream real-time, mode switch playlist, & pengunduhan YouTube di latar belakang.
    """
    def __init__(self, track, whip_client, icecast_client=None, music_dir=".."):
        self.track = track
        self.whip_client = whip_client
        self.icecast_client = icecast_client
        self.music_dir = music_dir
        self.is_running = True
        self.status_message = ""
        self.download_in_progress = False
        self.show_detailed_stats = False
        self.show_playlist_mode = False
        self.selected_index = 0
        self.search_query = ""
        self.search_mode_active = False
        self._cached_whip_stats = None
        self._last_whip_stats_time = 0.0

    def _get_filtered_playlist(self) -> list[tuple[int, str]]:
        if not self.search_query:
            return [(i, p) for i, p in enumerate(self.track.playlist)]
        query = self.search_query.lower().strip()
        return [(i, p) for i, p in enumerate(self.track.playlist) if query in os.path.basename(p).lower()]

    async def print_menu(self):
        # Gunakan ANSI escape sequence untuk refresh terminal tanpa me-spawn sub-proses (Zero CPU Waste)
        sys.stdout.write("\033[H\033[2J")
        sys.stdout.flush()

        status = self.track.get_status()
        pacer_stats = self.track.get_pacer_stats()
        
        now = time.monotonic()
        if self.show_detailed_stats or (now - self._last_whip_stats_time > 2.0) or not self._cached_whip_stats:
            self._cached_whip_stats = await self.whip_client.get_whip_stats()
            self._last_whip_stats_time = now
        whip_stats = self._cached_whip_stats

        ice_stats = self.icecast_client.get_icecast_stats() if self.icecast_client else None
        
        state_str = "▶ PLAYING" if status["is_playing"] else "⏸ PAUSED"
        mute_str = " 🔇 MUTED" if status["is_muted"] else ""
        
        uptime_str = format_duration(pacer_stats["uptime_sec"])
        bytes_str = format_bytes(pacer_stats["total_bytes"])
        inst_bitrate = pacer_stats["instant_bitrate_kbps"]
        avg_bitrate = pacer_stats["avg_bitrate_kbps"]
        conn_state = whip_stats["connection_state"]
        dtls_state = whip_stats["dtls_state"]
        
        elapsed_sec = status.get("track_elapsed_sec", 0.0)
        duration_sec = status.get("track_duration_sec", 0.0)
        progress_str = format_progress(elapsed_sec, duration_sec)

        if self.show_playlist_mode:
            # Mode Tampilan Playlist Lagu (Live Search & Scroll)
            print("==========================================================")
            print("      🎶 DAFTAR PLAYLIST LAGU STREAMING 🎶                ")
            print("==========================================================")
            print(f" Status Siaran : {state_str}{mute_str}")
            print(f" Lagu Aktif    : [{status['index']}/{status['total']}] {status['track']}")
            print(f" Posisi Lagu   : {progress_str}")
            if self.status_message:
                print(f" Info          : {self.status_message}")
            print("----------------------------------------------------------")
            
            filtered = self._get_filtered_playlist()
            total_filtered = len(filtered)

            if self.search_mode_active:
                print(f" 🔍 Cari Lagu (FOKUS KETIK) : [ {self.search_query}█ ] ({total_filtered} lagu cocok)")
            else:
                query_disp = f"\"{self.search_query}\"" if self.search_query else "Kosong"
                print(f" 🔍 Cari Lagu (Tekan [f] utk Cari): [{query_disp}] ({total_filtered} lagu)")
            print("----------------------------------------------------------")
            
            if not filtered:
                print(f" ⚠️ Tidak ada lagu yang cocok dengan pencarian '{self.search_query}'.")
            else:
                if self.selected_index >= total_filtered:
                    self.selected_index = max(0, total_filtered - 1)

                # Windowing Viewport Seragam (4 lagu sebelum & 4 lagu sesudah kursor) untuk SEMUA mode
                window_size = 4
                start_idx = max(0, self.selected_index - window_size)
                end_idx = min(total_filtered, self.selected_index + window_size + 1)
                
                display_items = [(f_idx, item) for f_idx, item in enumerate(filtered) if start_idx <= f_idx < end_idx]
                show_above_notice = (start_idx > 0)
                show_below_notice = (end_idx < total_filtered)
                above_count = start_idx
                below_count = total_filtered - end_idx

                if show_above_notice:
                    print(f"   ... ({above_count} lagu di atas)")

                for f_idx, (orig_idx, path) in display_items:
                    is_current = (orig_idx == self.track.current_index)
                    is_selected = (f_idx == self.selected_index)
                    
                    name = os.path.basename(path)
                    num = orig_idx + 1

                    if is_current and is_selected:
                        prefix = "▶ 👉"
                        suffix = " (Sedang Diputar & Disorot)"
                    elif is_selected:
                        prefix = "  👉"
                        suffix = " (Disorot)"
                    elif is_current:
                        prefix = "  🔊"
                        suffix = " (Sedang Diputar)"
                    else:
                        prefix = "    "
                        suffix = ""

                    print(f" {prefix} {num:2d}. {name}{suffix}")

                if show_below_notice:
                    print(f"   ... ({below_count} lagu di bawah)")

            print("----------------------------------------------------------")
            if self.search_mode_active:
                print(" [Ketik Teks] : Memfilter playlist secara real-time")
                print(" [BACKSPACE]  : Hapus karakter pencarian")
                print(" [↑ / ↓]      : Geser / Pilih Lagu Terfilter")
                print(" [ENTER]      : Memutar Lagu Terpilih")
                print(" [ESC]        : Keluar dari Mode Ketik Cari")
            else:
                print(" [↑ / ↓]     : Geser / Pilih Lagu (Scroll)")
                print(" [ENTER]     : Memutar Lagu Terpilih")
                print(" [f / /]     : Fokus / Aktifkan Search Bar")
                print(" [l / ESC]   : Kembali ke Dashboard Utama")
                print(" [r]         : Acak Ulang Playlist (Reshuffle)")
                print(" [u]         : Rescan / Refresh Playlist Folder")
                print(" [n / >]     : Lagu Berikutnya (Next)")
                print(" [b / <]     : Lagu Sebelumnya (Previous)")
                print(" [SPACE / p] : Pause / Resume")
                print(" [m]         : Mute / Unmute")
                print(" [y]         : Unduh YouTube -> Masukkan ke NEXT SONG")
                print(" [q]         : Keluar dari Siaran")
            print("==========================================================")
        else:
            # Mode Utama (Dashboard Stats & Controls)
            print("==========================================================")
            print("  📡 RAW OPUS DUAL STREAMER (MESHCAST & ICECAST2) 📡       ")
            print("==========================================================")
            print(f" Status Siaran : {state_str}{mute_str}")
            print(f" Lagu Aktif    : [{status['index']}/{status['total']}] {status['track']}")
            print(f" Posisi Lagu   : {progress_str}")
            if self.status_message:
                print(f" Info          : {self.status_message}")
            
            # Streaming Targets Status
            ice_status_str = "CONNECTED 🟢" if (ice_stats and ice_stats["is_connected"]) else "OFFLINE 🔴"
            ice_url = ice_stats["public_url"] if ice_stats else "N/A"
            ice_bytes = format_bytes(ice_stats["total_bytes"]) if ice_stats else "0 B"
            ice_bitrate = ice_stats["instant_bitrate_kbps"] if ice_stats else 0.0

            if not self.show_detailed_stats:
                # Mode Ringkas (Compact Stats)
                print("------------------ 📻 DUAL STREAM TARGETS ----------------")
                print(f" 🚀 Stream #1 (MeshCast WebRTC) : State={conn_state} ({inst_bitrate:.1f} kbps)")
                print(f" 🌐 Stream #2 (Icecast Tunnel) : {ice_status_str} ({ice_bitrate:.1f} kbps)")
                print(f"    🔗 Public Icecast Stream   : {ice_url}")
                print("----------------------------------------------------------")
                print(f" ⏱️  Uptime   : {uptime_str:<12} 📦 Total Audio : {bytes_str}")
            else:
                # Mode Detail (Detailed Dashboard)
                print("------------------ 📊 LIVE DASHBOARD DUAL STREAM ---------")
                print(f" ⏱️  Durasi Streaming : {uptime_str}")
                print(f" 🚀 Stream #1 (MeshCast) : State={conn_state} | ICE={whip_stats['ice_connection_state']} | DTLS={dtls_state}")
                print(f"    - Bitrate          : {inst_bitrate:.1f} kbps (Avg: {avg_bitrate:.1f} kbps) | Sent: {bytes_str}")
                print(f" 🌐 Stream #2 (Icecast)  : State={ice_status_str} | Local=http://localhost:8000/lsnn_radio")
                print(f"    - URL Publik       : {ice_url}")
                print(f"    - Bitrate          : {ice_bitrate:.1f} kbps (Avg: {ice_stats['avg_bitrate_kbps'] if ice_stats else 0:.1f} kbps) | Sent: {ice_bytes}")
                print(f" 📦 Paket Audio Pacer  : Total={pacer_stats['total_frames']:,} | Audio={pacer_stats['audio_frames']:,} | Silence={pacer_stats['silence_frames']:,}")
                print(f" ⚡ Rate & Drift       : {pacer_stats['instant_pps']:.1f} pps | Drift Realtime={pacer_stats['instant_drift_ms']:.2f} ms | Avg={pacer_stats['avg_drift_ms']:.2f} ms")

            print("----------------------------------------------------------")
            print(" [SPACE / p] : Pause / Resume")
            print(" [n / >]     : Lagu Berikutnya (Next)")
            print(" [b / <]     : Lagu Sebelumnya (Previous)")
            print(" [m]         : Mute / Unmute")
            print(f" [s]         : Toggle Dashboard Detailed Stats [{'ON' if self.show_detailed_stats else 'OFF'}]")
            print(" [y]         : Unduh YouTube -> Masukkan ke NEXT SONG")
            print(" [l]         : Switch ke Mode Playlist Lagu")
            print(" [q]         : Keluar dari Siaran")
            print("==========================================================")

    async def _handle_youtube_input(self):
        print("\n----------------------------------------------------------")
        print("Masukkan URL YouTube / YouTube Music (lalu tekan Enter):")
        print("----------------------------------------------------------")
        
        # Ambil input URL secara asinkron tanpa memblokir event loop
        loop = asyncio.get_running_loop()
        url = await loop.run_in_executor(None, sys.stdin.readline)
        url = url.strip()

        if not url:
            self.status_message = "⚠️ URL YouTube kosong. Batal mengunduh."
            await self.print_menu()
            return

        self.status_message = f"⏳ Mengunduh lagu dari YouTube di latar belakang..."
        self.download_in_progress = True
        await self.print_menu()

        # Jalankan unduhan di background task
        asyncio.create_task(self._download_task(url))

    async def _download_task(self, url: str):
        try:
            output_path = await download_youtube_opus(url, output_dir=self.music_dir)
            file_name = os.path.basename(output_path)
            
            # Sisipkan lagu ke posisi NEXT SONG (current_index + 1)
            pos = self.track.insert_next_track(output_path)
            
            self.status_message = f"✅ Berhasil! '{file_name}' ditambahkan di nomor #{pos} (NEXT SONG)."
        except Exception as e:
            self.status_message = f"❌ Gagal mengunduh YouTube: {e}"
        finally:
            self.download_in_progress = False
            await self.print_menu()

    async def run(self):
        await self.print_menu()
        last_refresh = time.monotonic()

        while self.is_running:
            key_pressed = False
            if msvcrt.kbhit():
                key = msvcrt.getch()
                
                if key in (b'\x00', b'\xe0'):
                    if msvcrt.kbhit():
                        arrow_key = msvcrt.getch()
                        if self.show_playlist_mode:
                            filtered = self._get_filtered_playlist()
                            if arrow_key == b'H':  # Panah Atas
                                if filtered:
                                    self.selected_index = (self.selected_index - 1) % len(filtered)
                                key_pressed = True
                            elif arrow_key == b'P':  # Panah Bawah
                                if filtered:
                                    self.selected_index = (self.selected_index + 1) % len(filtered)
                                key_pressed = True
                elif key in (b'\r', b'\n'):  # Tombol Enter
                    if self.show_playlist_mode:
                        filtered = self._get_filtered_playlist()
                        if filtered and 0 <= self.selected_index < len(filtered):
                            orig_idx, path = filtered[self.selected_index]
                            self.track.play_track_at_index(orig_idx)
                            song_name = os.path.basename(path)
                            self.status_message = f"▶ Memutar lagu terpilih: {song_name}"
                            key_pressed = True
                elif key == b'\x08':  # Backspace Key
                    if self.show_playlist_mode and self.search_mode_active:
                        if self.search_query:
                            self.search_query = self.search_query[:-1]
                            self.selected_index = 0
                            key_pressed = True
                elif key == b'\x1b':  # ESC Key
                    if self.show_playlist_mode:
                        if self.search_mode_active:
                            self.search_mode_active = False
                            self.search_query = ""
                            self.selected_index = self.track.current_index
                            self.status_message = "ℹ️ Keluar dari mode pencarian."
                        else:
                            self.show_playlist_mode = False
                        key_pressed = True
                else:
                    if self.show_playlist_mode and self.search_mode_active:
                        try:
                            char_str = key.decode('utf-8', errors='ignore')
                            if char_str and char_str.isprintable():
                                self.search_query += char_str
                                self.selected_index = 0
                                key_pressed = True
                        except Exception:
                            pass
                    else:
                        try:
                            ch = key.decode('utf-8', errors='ignore').lower()
                        except Exception:
                            ch = ''

                        if ch in (' ', 'p'):
                            self.track.toggle_play()
                            key_pressed = True
                        elif ch in ('n', '>'):
                            self.track.next_track()
                            self.selected_index = self.track.current_index
                            key_pressed = True
                        elif ch in ('b', '<'):
                            self.track.prev_track()
                            self.selected_index = self.track.current_index
                            key_pressed = True
                        elif ch == 'm':
                            self.track.toggle_mute()
                            key_pressed = True
                        elif ch == 's':
                            self.show_detailed_stats = not self.show_detailed_stats
                            key_pressed = True
                        elif ch in ('l', '\x1b'):  # 'l' atau ESC
                            self.show_playlist_mode = not self.show_playlist_mode
                            if self.show_playlist_mode:
                                self.selected_index = self.track.current_index
                                self.search_mode_active = False
                            key_pressed = True
                        elif ch in ('f', '/'):
                            if self.show_playlist_mode:
                                self.search_mode_active = True
                                self.status_message = "🔍 Mode Pencarian AKTIF (Ketik kata kunci... Tekan ESC untuk keluar)."
                                key_pressed = True
                        elif ch == 'r':
                            if self.show_playlist_mode:
                                self.track.reshuffle_remaining()
                                self.status_message = "🔀 Sisa playlist berhasil diacak ulang!"
                                key_pressed = True
                        elif ch == 'u':
                            new_added, total_count = self.track.refresh_playlist(self.music_dir)
                            if new_added > 0:
                                self.status_message = f"🔄 Playlist diperbarui! ({new_added} lagu baru ditemukan, Total: {total_count} lagu)"
                            else:
                                self.status_message = f"🔄 Playlist di-rescan (Total: {total_count} lagu)"
                            key_pressed = True
                        elif ch == 'y':
                            await self._handle_youtube_input()
                            key_pressed = True
                        elif ch == 'q':
                            print("\n[CLI] Menghentikan siaran...")
                            self.is_running = False
                            break

            now = time.monotonic()
            if (key_pressed or (now - last_refresh >= 0.5)) and not self.download_in_progress:
                await self.print_menu()
                last_refresh = now

            await asyncio.sleep(0.05)
