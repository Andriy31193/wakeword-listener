"""Sound player utility using aplay."""
import logging
import subprocess
import os
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def play_sound(sound_path: str) -> bool:
    """
    Play a sound file using aplay.
    
    Args:
        sound_path: Path to the sound file to play
        
    Returns:
        True if successful, False otherwise
    """
    if not sound_path or not sound_path.strip():
        return False
    
    sound_path = sound_path.strip()
    
    # Check if file exists
    if not os.path.exists(sound_path):
        logger.warning(f"Sound file not found: {sound_path}")
        return False
    
    try:
        # Use aplay to play the sound file
        # aplay is non-blocking by default, but we can make it blocking if needed
        result = subprocess.run(
            ["aplay", sound_path],
            capture_output=True,
            text=True,
            timeout=30  # Max 30 seconds for a sound file
        )
        
        if result.returncode == 0:
            logger.debug(f"Successfully played sound: {sound_path}")
            return True
        else:
            logger.error(f"Failed to play sound: {sound_path}, error: {result.stderr}")
            return False
            
    except FileNotFoundError:
        logger.error("aplay command not found. Make sure ALSA utilities are installed.")
        return False
    except subprocess.TimeoutExpired:
        logger.warning(f"Sound playback timed out: {sound_path}")
        return False
    except Exception as e:
        logger.error(f"Error playing sound {sound_path}: {e}", exc_info=True)
        return False


def play_sound_async(sound_path: str) -> Optional[subprocess.Popen]:
    """
    Play a sound file asynchronously using aplay.
    
    Args:
        sound_path: Path to the sound file to play
        
    Returns:
        subprocess.Popen object if successful, None otherwise
    """
    if not sound_path or not sound_path.strip():
        return None
    
    sound_path = sound_path.strip()
    
    # Check if file exists
    if not os.path.exists(sound_path):
        logger.warning(f"Sound file not found: {sound_path}")
        return None
    
    try:
        # Use aplay to play the sound file asynchronously
        process = subprocess.Popen(
            ["aplay", sound_path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        logger.debug(f"Started playing sound asynchronously: {sound_path} (PID: {process.pid})")
        return process
        
    except FileNotFoundError:
        logger.error("aplay command not found. Make sure ALSA utilities are installed.")
        return None
    except Exception as e:
        logger.error(f"Error starting sound playback {sound_path}: {e}", exc_info=True)
        return None


def stop_aplay() -> bool:
    """
    Stop any currently playing aplay processes.
    
    Returns:
        True if successful, False otherwise
    """
    try:
        # Find and kill all aplay processes
        result = subprocess.run(
            ["pkill", "-f", "aplay"],
            capture_output=True,
            text=True
        )
        
        if result.returncode == 0 or result.returncode == 1:  # 1 means no processes found
            logger.debug("Stopped aplay processes")
            return True
        else:
            logger.warning(f"Failed to stop aplay processes: {result.stderr}")
            return False
            
    except FileNotFoundError:
        logger.error("pkill command not found")
        return False
    except Exception as e:
        logger.error(f"Error stopping aplay: {e}", exc_info=True)
        return False

