import os
import json
from dataclasses import dataclass, asdict, field
from typing import Optional

CONFIG_FILE = "config.json"

@dataclass
class AppConfig:
    music_dir: str = ".."
    whip_url: str = "https://cn1.meshcast.io/whip/lsnn_radio"
    hls_port: int = 8000
    public_hls_url: str = "https://radio.samf.fun/live.m3u8"
    tunnel_mode: str = "quick"  # "quick", "custom", "none"
    cloudflared_config_path: str = ""
    cloudflared_tunnel_id: str = ""

    @classmethod
    def get_default_config_path(cls) -> str:
        # Check standard user home directory ~/.cloudflared/config.yml
        home_config = os.path.expanduser("~/.cloudflared/config.yml")
        if os.path.exists(home_config):
            return home_config
        return ""

    @classmethod
    def load(cls, file_path: str = CONFIG_FILE) -> "AppConfig":
        if os.path.exists(file_path):
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
            except Exception as e:
                print(f"[Config] Error loading {file_path}: {e}")
        
        cfg = cls()
        # If user has a default config.yml in ~/.cloudflared, prefill it
        default_yml = cls.get_default_config_path()
        if default_yml:
            cfg.cloudflared_config_path = default_yml
            cfg.tunnel_mode = "custom"
        return cfg

    def save(self, file_path: str = CONFIG_FILE) -> bool:
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(asdict(self), f, indent=2)
            return True
        except Exception as e:
            print(f"[Config Error] Failed to save {file_path}: {e}")
            return False
