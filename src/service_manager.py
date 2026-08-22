import os
import sys
import shutil
import subprocess
import time
import re
import threading
import atexit
from typing import Dict, Any, Optional

_cloudflared_proc: Optional[subprocess.Popen] = None
_quick_tunnel_url: Optional[str] = None
_tunnel_status: str = "stopped"  # "running", "connected", "stopped", "failed"

def find_cloudflared_executable() -> Optional[str]:
    """Finds the cloudflared executable dynamically across PATH and standard installation folders."""
    which_path = shutil.which("cloudflared")
    if which_path and os.path.exists(which_path):
        return which_path

    candidates = [
        os.path.expandvars(r"%ProgramFiles%\cloudflared\cloudflared.exe"),
        os.path.expandvars(r"%ProgramFiles(x86)%\cloudflared\cloudflared.exe"),
        os.path.abspath("./cloudflared.exe"),
        os.path.abspath("./bin/cloudflared.exe"),
        "/usr/local/bin/cloudflared",
        "/usr/bin/cloudflared",
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    return None

def is_cloudflared_installed() -> bool:
    return find_cloudflared_executable() is not None

def is_named_tunnel_connected(exe_path: str, tunnel_id_or_name: str) -> bool:
    if not tunnel_id_or_name:
        return False
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

def _monitor_quick_tunnel_output(proc: subprocess.Popen):
    global _quick_tunnel_url, _tunnel_status
    url_pattern = re.compile(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com")
    try:
        while proc.poll() is None:
            line = proc.stderr.readline()
            if not line:
                break
            line_str = line.decode("utf-8", errors="ignore")
            if _quick_tunnel_url is None:
                match = url_pattern.search(line_str)
                if match:
                    _quick_tunnel_url = match.group(0)
                    _tunnel_status = "connected"
                    print(f"[ServiceManager] Quick Tunnel connected: {_quick_tunnel_url}")
    except Exception as e:
        print(f"[ServiceManager Error] Quick tunnel monitor: {e}")

def start_cloudflared_tunnel(
    mode: str = "quick",
    local_port: int = 8000,
    config_path: str = "",
    tunnel_id: str = ""
) -> Dict[str, Any]:
    global _cloudflared_proc, _quick_tunnel_url, _tunnel_status

    if mode == "none":
        _tunnel_status = "disabled"
        return {"status": "disabled", "url": None}

    exe = find_cloudflared_executable()
    if not exe:
        _tunnel_status = "not_installed"
        print("[ServiceManager Warning] cloudflared is not installed on this system.")
        return {"status": "not_installed", "url": None}

    # Stop any previous process
    stop_all_services()

    try:
        if mode == "quick":
            import tempfile
            local_target = f"http://127.0.0.1:{local_port}"
            print(f"[ServiceManager] Starting Cloudflare Quick Tunnel -> {local_target} ...")

            # Create an isolated config to prevent cloudflared from reading ~/.cloudflared/config.yml
            temp_cfg = os.path.join(tempfile.gettempdir(), "cf_quick_isolated.yml")
            with open(temp_cfg, "w", encoding="utf-8") as f:
                f.write(f"url: {local_target}\n")

            cmd = [exe, "--config", temp_cfg, "tunnel", "--url", local_target]
            _cloudflared_proc = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            )
            _tunnel_status = "starting"
            _quick_tunnel_url = None

            # Spawn reader thread to capture trycloudflare.com URL and drain stderr
            t = threading.Thread(target=_monitor_quick_tunnel_output, args=(_cloudflared_proc,), daemon=True)
            t.start()

            # Wait up to 12 seconds for URL
            for _ in range(24):
                if _quick_tunnel_url:
                    break
                time.sleep(0.5)

            return {
                "status": "connected" if _quick_tunnel_url else "starting",
                "url": _quick_tunnel_url
            }

        elif mode == "custom":
            expanded_config = os.path.expanduser(config_path) if config_path else ""
            if not expanded_config or not os.path.exists(expanded_config):
                _tunnel_status = "config_missing"
                print(f"[ServiceManager Warning] Custom config not found at: {config_path}")
                return {"status": "config_missing", "url": None}

            cmd = [exe, "--config", expanded_config, "tunnel", "run"]
            if tunnel_id:
                cmd.append(tunnel_id)

            print(f"[ServiceManager] Starting Custom Cloudflared Tunnel ({expanded_config})...")
            _cloudflared_proc = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            )
            _tunnel_status = "starting"

            for _ in range(10):
                time.sleep(0.5)
                if tunnel_id and is_named_tunnel_connected(exe, tunnel_id):
                    _tunnel_status = "connected"
                    print("[ServiceManager] Custom Tunnel connected to Cloudflare Edge!")
                    return {"status": "connected", "url": None}

            _tunnel_status = "running"
            return {"status": "running", "url": None}

    except Exception as e:
        _tunnel_status = "failed"
        print(f"[ServiceManager Error] Failed to start cloudflared: {e}")
        return {"status": "failed", "error": str(e)}

    return {"status": _tunnel_status, "url": _quick_tunnel_url}

def get_tunnel_status() -> Dict[str, Any]:
    return {
        "status": _tunnel_status,
        "quick_url": _quick_tunnel_url,
        "is_running": _cloudflared_proc is not None and _cloudflared_proc.poll() is None
    }

def stop_all_services():
    global _cloudflared_proc, _tunnel_status, _quick_tunnel_url
    if _cloudflared_proc:
        try:
            _cloudflared_proc.terminate()
            _cloudflared_proc.wait(timeout=2)
        except Exception:
            try:
                _cloudflared_proc.kill()
            except Exception:
                pass
        _cloudflared_proc = None
    _tunnel_status = "stopped"
    _quick_tunnel_url = None

atexit.register(stop_all_services)
