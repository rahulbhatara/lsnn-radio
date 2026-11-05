import os
import glob
import shutil
import subprocess
import argparse
from typing import List, Tuple, Callable, Optional
import av
import numpy as np

def convert_audio_with_pyav(input_file: str, output_file: str):
    """
    Converts any audio file to standard 48kHz stereo 20ms Opus using pure PyAV (no external ffmpeg.exe).
    """
    in_container = None
    out_container = None
    try:
        in_container = av.open(input_file)
        if not in_container.streams.audio:
            raise ValueError(f"No audio stream found in {input_file}")

        in_stream = in_container.streams.audio[0]

        out_container = av.open(output_file, 'w', format='ogg')
        out_stream = out_container.add_stream('libopus', rate=48000)
        out_stream.layout = 'stereo'
        out_stream.bit_rate = 192000

        resampler = av.AudioResampler(
            format='s16',
            layout='stereo',
            rate=48000
        )

        # 960 samples per 20ms at 48000Hz stereo int16 (1920 int16 samples)
        CHUNK_SIZE = 960
        pcm_buffer = np.empty((0, 2), dtype=np.int16)

        for frame in in_container.decode(in_stream):
            resampled_frames = resampler.resample(frame)
            if not resampled_frames:
                continue
            for rf in resampled_frames:
                nd = rf.to_ndarray().reshape(-1, 2)
                pcm_buffer = np.vstack([pcm_buffer, nd])

                # Slice and encode in 960-sample (20ms) chunks
                while len(pcm_buffer) >= CHUNK_SIZE:
                    chunk = np.ascontiguousarray(pcm_buffer[:CHUNK_SIZE], dtype=np.int16)
                    pcm_buffer = pcm_buffer[CHUNK_SIZE:]

                    out_frame = av.AudioFrame.from_ndarray(chunk.reshape(1, -1), format='s16', layout='stereo')
                    out_frame.sample_rate = 48000

                    packets = out_stream.encode(out_frame)
                    for pkt in packets:
                        out_container.mux(pkt)

        # Flush remaining buffer if any
        if len(pcm_buffer) > 0:
            pad_len = CHUNK_SIZE - len(pcm_buffer)
            padding = np.zeros((pad_len, 2), dtype=np.int16)
            chunk = np.ascontiguousarray(np.vstack([pcm_buffer, padding]), dtype=np.int16)
            out_frame = av.AudioFrame.from_ndarray(chunk.reshape(1, -1), format='s16', layout='stereo')
            out_frame.sample_rate = 48000
            for pkt in out_stream.encode(out_frame):
                out_container.mux(pkt)

        # Flush encoder
        for pkt in out_stream.encode(None):
            out_container.mux(pkt)

    except Exception:
        if out_container:
            try:
                out_container.close()
            except Exception:
                pass
            out_container = None
        if os.path.exists(output_file):
            try:
                os.remove(output_file)
            except Exception:
                pass
        raise
    finally:
        if in_container:
            try:
                in_container.close()
            except Exception:
                pass
        if out_container:
            try:
                out_container.close()
            except Exception:
                pass

def convert_audio_to_opus(input_file: str, output_file: str):
    """
    Converts audio file to standard Opus.
    Prefers ffmpeg CLI if available in PATH for speed, otherwise falls back to pure PyAV.
    """
    ffmpeg_exe = shutil.which("ffmpeg")
    if ffmpeg_exe:
        try:
            cmd = [
                ffmpeg_exe, "-y", "-hide_banner", "-loglevel", "error",
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
            return
        except Exception:
            pass  # Fallback to PyAV

    convert_audio_with_pyav(input_file, output_file)

def scan_non_opus_files(music_dir: str) -> List[str]:
    """Finds non-opus audio files (.mp3, .wav, .flac, .m4a, .aac, .ogg) in the music directory."""
    if not os.path.exists(music_dir):
        return []
    exts = ["*.mp3", "*.wav", "*.flac", "*.m4a", "*.aac", "*.wma"]
    files = []
    for ext in exts:
        files.extend(glob.glob(os.path.join(music_dir, ext)))
    return sorted(files)

def batch_convert_files(
    file_list: List[str],
    progress_callback: Optional[Callable[[str, int, int], None]] = None
) -> Tuple[int, int]:
    """
    Converts a list of non-opus files to .opus format.
    Returns (success_count, total_count).
    """
    success = 0
    total = len(file_list)
    for idx, f in enumerate(file_list):
        base_name = os.path.splitext(f)[0]
        out_opus = f"{base_name}.opus"
        if progress_callback:
            progress_callback(os.path.basename(f), idx + 1, total)
        try:
            convert_audio_to_opus(f, out_opus)
            success += 1
        except Exception as e:
            print(f"[Convert Error] Failed {f}: {e}")
    return success, total

def main():
    parser = argparse.ArgumentParser(description="Convert music library files to standard Opus 48kHz 20ms")
    parser.add_argument("--dir", default="..", help="Music directory")
    args = parser.parse_args()

    music_dir = os.path.abspath(args.dir)
    print(f"[Convert] Checking audio files in: {music_dir}")
    files = scan_non_opus_files(music_dir)
    if not files:
        print("[Convert] No non-opus audio files found. All files are .opus ready!")
        return

    print(f"[Convert] Found {len(files)} files to convert...")
    s, t = batch_convert_files(files, lambda name, cur, tot: print(f"[{cur}/{tot}] Converting: {name}"))
    print(f"[Convert] Done! Successfully converted {s}/{t} files.")

if __name__ == "__main__":
    main()
