import sys
import os
import asyncio
import msvcrt
from yt_downloader import download_youtube_opus

class CLIController:
    """
    Pengontrol terminal interaktif tanpa perlu menekan Enter (msvcrt di Windows),
    dilengkapi fitur pengunduhan YouTube di latar belakang.
    """
    def __init__(self, track, whip_client, music_dir=".."):
        self.track = track
        self.whip_client = whip_client
        self.music_dir = music_dir
        self.is_running = True
        self.status_message = ""
        self.download_in_progress = False

    def print_menu(self):
        os.system('cls' if os.name == 'nt' else 'clear')
        status = self.track.get_status()
        
        state_str = "▶ PLAYING" if status["is_playing"] else "⏸ PAUSED"
        mute_str = " 🔇 MUTED" if status["is_muted"] else ""
        
        print("==========================================================")
        print("      🎵 RAW OPUS WHIP STREAMER & PACER (ZERO-CPU) 🎵     ")
        print("==========================================================")
        print(f" Status Siaran : {state_str}{mute_str}")
        print(f" Lagu Aktif    : [{status['index']}/{status['total']}] {status['track']}")
        if self.status_message:
            print(f" Info          : {self.status_message}")
        print("----------------------------------------------------------")
        print(" [SPACE / p] : Pause / Resume")
        print(" [n / >]     : Lagu Berikutnya (Next)")
        print(" [b / <]     : Lagu Sebelumnya (Previous)")
        print(" [m]         : Mute / Unmute")
        print(" [y]         : Unduh YouTube -> Masukkan ke NEXT SONG")
        print(" [l]         : Cetak Daftar Playlist")
        print(" [q]         : Keluar dari Siaran")
        print("==========================================================")

    def print_playlist(self):
        print("\n--- 🎶 DAFTAR PLAYLIST 🎶 ---")
        for idx, path in enumerate(self.track.playlist, 1):
            mark = "👉" if idx == self.track.current_index + 1 else "  "
            print(f"{mark} {idx}. {os.path.basename(path)}")
        print("----------------------------\n")

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
            self.print_menu()
            return

        self.status_message = f"⏳ Mengunduh lagu dari YouTube di latar belakang..."
        self.download_in_progress = True
        self.print_menu()

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
            self.print_menu()

    async def run(self):
        self.print_menu()
        while self.is_running:
            if msvcrt.kbhit():
                key = msvcrt.getch()
                try:
                    ch = key.decode('utf-8', errors='ignore').lower()
                except Exception:
                    ch = ''

                if ch in (' ', 'p'):
                    self.track.toggle_play()
                    self.print_menu()
                elif ch in ('n', '>'):
                    self.track.next_track()
                    self.print_menu()
                elif ch in ('b', '<'):
                    self.track.prev_track()
                    self.print_menu()
                elif ch == 'm':
                    self.track.toggle_mute()
                    self.print_menu()
                elif ch == 'y':
                    await self._handle_youtube_input()
                elif ch == 'l':
                    self.print_playlist()
                elif ch == 'q':
                    print("\n[CLI] Menghentikan siaran...")
                    self.is_running = False
                    break

            await asyncio.sleep(0.05)
