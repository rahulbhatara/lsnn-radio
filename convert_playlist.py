import os
import glob
import subprocess
import argparse

def convert_audio_to_opus(input_file: str, output_file: str):
    """
    Mengonversi file audio (mp3, wav, flac, opus) ke standar Opus 48kHz 20ms frame.
    """
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-i", input_file,
        "-c:a", "libopus",
        "-b:a", "192k",
        "-ar", "48000",
        "-ac", "2",
        "-application", "audio",
        "-frame_duration", "20",
        output_file
    ]
    subprocess.run(cmd, check=True)

def main():
    parser = argparse.ArgumentParser(description="Normalisasi file lagu ke standar Opus 48kHz 20ms")
    parser.add_argument("--dir", default="..", help="Direktori lagu")
    args = parser.parse_args()

    music_dir = os.path.abspath(args.dir)
    print(f"[Convert] Memeriksa file audio di: {music_dir}")
    
    extensions = ["*.mp3", "*.wav", "*.flac", "*.m4a"]
    files = []
    for ext in extensions:
        files.extend(glob.glob(os.path.join(music_dir, ext)))

    if not files:
        print("[Convert] Tidak ada file mp3/wav/flac yang perlu dikonversi. Semua lagu sudah berupa .opus!")
        return

    print(f"[Convert] Ditemukan {len(files)} file untuk dikonversi...")
    for f in files:
        base_name = os.path.splitext(f)[0]
        out_opus = f"{base_name}.opus"
        print(f" Mengonversi: {os.path.basename(f)} -> {os.path.basename(out_opus)}")
        try:
            convert_audio_to_opus(f, out_opus)
            print("  ✅ Selesai.")
        except Exception as e:
            print(f"  ❌ Gagal: {e}")

if __name__ == "__main__":
    main()
