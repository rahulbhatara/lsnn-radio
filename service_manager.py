import os
import sys
import socket
import subprocess
import time
from typing import Dict, Any

ICECAST_EXE_PATH = r"C:\Program Files\Icecast\bin\icecast.exe"
ICECAST_CONFIG_PATH = r"C:\Program Files\Icecast\icecast.xml"
ICECAST_DIR = r"C:\Program Files\Icecast"

CLOUDFLARED_EXE_PATH = r"C:\Program Files (x86)\cloudflared\cloudflared.exe"
CLOUDFLARED_CONFIG_PATH = r"C:\Users\Admin\.cloudflared\config.yml"

def is_port_open(host: str, port: int, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (socket.timeout, ConnectionRefusedError, OSError):
        return False

def is_process_running(process_name: str) -> bool:
    try:
        output = subprocess.check_output(
            ["tasklist", "/FI", f"IMAGENAME eq {process_name}"],
            text=True,
            stderr=subprocess.DEVNULL
        )
        return process_name.lower() in output.lower()
    except Exception:
        return False

def ensure_icecast_running(host: str = "127.0.0.1", port: int = 8000) -> bool:
    if is_port_open(host, port):
        return True
    
    if os.path.exists(ICECAST_EXE_PATH) and os.path.exists(ICECAST_CONFIG_PATH):
        try:
            print(f"[ServiceManager] Memulai Icecast2 ({ICECAST_EXE_PATH})...")
            subprocess.Popen(
                [ICECAST_EXE_PATH, "-c", ICECAST_CONFIG_PATH],
                cwd=ICECAST_DIR,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            )
            # Tunggu port terbuka
            for _ in range(10):
                time.sleep(0.5)
                if is_port_open(host, port):
                    print("[ServiceManager] Icecast2 berhasil diaktifkan!")
                    return True
        except Exception as e:
            print(f"[ServiceManager Error] Gagal meluncurkan Icecast2: {e}")
    else:
        print(f"[ServiceManager Warning] File executable Icecast tidak ditemukan di {ICECAST_EXE_PATH}")
    
    return is_port_open(host, port)

def ensure_cloudflared_running() -> bool:
    if is_process_running("cloudflared.exe"):
        return True

    exe_path = CLOUDFLARED_EXE_PATH if os.path.exists(CLOUDFLARED_EXE_PATH) else "cloudflared"
    if os.path.exists(CLOUDFLARED_CONFIG_PATH):
        try:
            print(f"[ServiceManager] Memulai Cloudflared Tunnel ({CLOUDFLARED_CONFIG_PATH})...")
            subprocess.Popen(
                [exe_path, "--config", CLOUDFLARED_CONFIG_PATH, "tunnel", "run"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            )
            for _ in range(10):
                time.sleep(0.5)
                if is_process_running("cloudflared.exe"):
                    print("[ServiceManager] Cloudflared Tunnel berhasil diaktifkan!")
                    return True
        except Exception as e:
            print(f"[ServiceManager Error] Gagal meluncurkan Cloudflared: {e}")
    else:
        print(f"[ServiceManager Warning] Config Cloudflared tidak ditemukan di {CLOUDFLARED_CONFIG_PATH}")

    return is_process_running("cloudflared.exe")

def check_and_start_all_services() -> Dict[str, Any]:
    icecast_ok = ensure_icecast_running()
    cloudflared_ok = ensure_cloudflared_running()
    return {
        "icecast": icecast_ok,
        "cloudflared": cloudflared_ok
    }

def stop_all_services():
    print("[ServiceManager] Menghentikan semua layanan (Icecast2 & Cloudflared)...")
    if is_process_running("icecast.exe"):
        try:
            subprocess.run(["taskkill", "/F", "/T", "/IM", "icecast.exe"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass
    if is_process_running("cloudflared.exe"):
        try:
            subprocess.run(["taskkill", "/F", "/T", "/IM", "cloudflared.exe"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass
    print("[ServiceManager] Semua layanan berhasil dihentikan sepenuhnya!")

import atexit
atexit.register(stop_all_services)

