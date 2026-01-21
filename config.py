"""Configuration loader for Wake Word Listener."""
import yaml
import os
from pathlib import Path
from typing import Dict, Any

# Default config
DEFAULT_CONFIG = {
    "wake_word": {
        "model_path": "hey_dex.ppn",
        "access_key": "",
        "sensitivity": 0.5
    },
    "audio": {
        "sample_rate": 16000,
        "channels": 1,
        "frame_length": 512
    },
    "recording": {
        "silence_timeout_secs": 2.0,
        "max_length_secs": 30.0,
        "vad_energy_threshold": 300
    },
    "mcp_client": {
        "enabled": True,
        "host": "127.0.0.1",
        "port": 5001,
        "endpoint_retrieve_context": "/context"
    },
    "stt": {
        "type": "local",
        "endpoint": "",
        "timeout": 30,
        "model": "medium",
        "device": "cuda",
        "groq_api_key": ""
    },
    "sounds": {
        "on_wakewordstart_sound_path": "",
        "on_wakewordend_sound_path": ""
    },
    "audio_api": {
        "enabled": True,
        "host": "127.0.0.1",
        "port": 5002
    },
    "n8n": {
        "webhook_url": ""
    },
    "logging": {
        "level": "INFO"
    }
}


def load_config(config_path: str = None) -> Dict[str, Any]:
    """
    Load configuration from YAML file or use defaults.
    
    Args:
        config_path: Path to config.yaml file. If None, uses default location.
        
    Returns:
        Configuration dictionary
    """
    if config_path is None:
        config_path = Path(__file__).parent / "config.yaml"
    
    config = DEFAULT_CONFIG.copy()
    
    if os.path.exists(config_path):
        try:
            with open(config_path, 'r') as f:
                file_config = yaml.safe_load(f)
                if file_config:
                    # Deep merge
                    def merge_dict(base, update):
                        for key, value in update.items():
                            if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                                merge_dict(base[key], value)
                            else:
                                base[key] = value
                    
                    merge_dict(config, file_config)
        except Exception as e:
            print(f"Warning: Failed to load config file {config_path}: {e}")
            print("Using default configuration")
    else:
        print(f"Config file not found at {config_path}, using defaults")
    
    # Resolve model path relative to project root or parent directory
    model_path = config["wake_word"]["model_path"]
    if not os.path.isabs(model_path):
        # Try current directory first
        if not os.path.exists(model_path):
            # Try parent directory (original location)
            parent_model_path = Path(__file__).parent.parent / model_path
            if parent_model_path.exists():
                config["wake_word"]["model_path"] = str(parent_model_path)
    
    return config

