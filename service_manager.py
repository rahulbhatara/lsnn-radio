import os
import sys
import subprocess
import time
import atexit
from typing import Dict, Any

CLOUDFLARED_EXE_PATH = r"C:\Program Files (x86)\cloudflared\cloudflared.exe"
CLOUDFLARED_CONFIG_PATH = r"C:\Users\Admin\.cloudflared\config.yml"
TUNNEL_ID = "daef68c7-e378-4034-80f2-e22b87a59c50"

_cloudflared_proc = None

def is_tunnel_connected(tunnel_id_or_name: str = TUNNEL_ID) -> bool:
    exe_path = CLOUDFLARED_EXE_PATH if os.path.exists(CLOUDFLARED_EXE_PATH) else "cloudflared"
    try:
        out = subprocess.check_output(
            [exe_path, "tunnel", "info", tunnel_id_or_name],
            text=True,
            stderr=subprocess.STDOUT,
            timeout=5
        )
        return "does not have any active connection" not in out.lower() and "connector id" in out.lower()
    except Exception:
        return False

def ensure_cloudflared_running() -> bool:
    global _cloudflared_proc
    if _cloudflared_proc is not None and _cloudflared_proc.poll() is None:
        return True

    if is_tunnel_connected():
        print("[ServiceManager] Cloudflared Tunnel radio-tunnel sudah AKTIF & terhubung ke Cloudflare Edge!")
        return True

    exe_path = CLOUDFLARED_EXE_PATH if os.path.exists(CLOUDFLARED_EXE_PATH) else "cloudflared"
    if os.path.exists(CLOUDFLARED_CONFIG_PATH):
        try:
            print(f"[ServiceManager] Memulai Cloudflared Tunnel ({CLOUDFLARED_CONFIG_PATH})...")
            _cloudflared_proc = subprocess.Popen(
                [exe_path, "--config", CLOUDFLARED_CONFIG_PATH, "tunnel", "run"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            )
            for _ in range(12):
                time.sleep(0.5)
                if is_tunnel_connected():
                    print("[ServiceManager] Cloudflared Tunnel radio-tunnel BERHASIL terhubung ke Edge CDN!")
                    return True
        except Exception as e:
            print(f"[ServiceManager Error] Gagal meluncurkan Cloudflared: {e}")
    else:
        print(f"[ServiceManager Warning] Config Cloudflared tidak ditemukan di {CLOUDFLARED_CONFIG_PATH}")

    return is_tunnel_connected()

def check_and_start_all_services() -> Dict[str, Any]:
    cloudflared_ok = ensure_cloudflared_running()
    return {
        "cloudflared": cloudflared_ok
    }

def stop_all_services():
    global _cloudflared_proc
    if _cloudflared_proc:
        print("[ServiceManager] Menghentikan proses Cloudflared Tunnel yang diluncurkan...")
        try:
            _cloudflared_proc.terminate()
            _cloudflared_proc.wait(timeout=3)
        except Exception:
            try:
                _cloudflared_proc.kill()
            except Exception:
                pass
        _cloudflared_proc = None
        print("[ServiceManager] Proses Cloudflared Tunnel berhasil dihentikan!")

atexit.register(stop_all_services)
