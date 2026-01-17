"""Wake word detection using Picovoice Porcupine."""
import pvporcupine
import pyaudio
import logging
import struct
from pathlib import Path
from typing import Optional, Callable

logger = logging.getLogger(__name__)


class WakeWordDetector:
    """Detects wake words using Picovoice Porcupine."""
    
    def __init__(
        self,
        model_path: str,
        access_key: str,
        sample_rate: int = 16000,
        frame_length: int = 512,
        wake_word_callback: Optional[Callable] = None
    ):
        """
        Initialize the wake word detector.
        
        Args:
            model_path: Path to wake word model file (.ppn)
            access_key: Picovoice access key
            sample_rate: Audio sample rate
            frame_length: Audio frame length
            wake_word_callback: Optional callback function called when wake word is detected.
                               Receives the keyword index as argument.
        """
        self.model_path = model_path
        self.access_key = access_key
        self.sample_rate = sample_rate
        self.frame_length = frame_length
        self.wake_word_callback = wake_word_callback
        
        self.porcupine = None
        self.audio_stream = None
        self.audio = None
        self.is_listening = False
        
        # Build full path to model
        model_path_full = Path(model_path)
        if not model_path_full.is_absolute():
            # Try relative to current directory
            if not model_path_full.exists():
                # Try parent directory
                model_path_full = Path(__file__).parent.parent / model_path
        
        try:
            self.porcupine = pvporcupine.create(
                access_key=access_key,
                keyword_paths=[str(model_path_full)]
            )
            logger.info(f"Initialized Porcupine with wake word: {model_path_full}")
        except Exception as e:
            logger.error(f"Failed to initialize Porcupine: {e}")
            raise
    
    def start_listening(self):
        """Start listening for wake words."""
        if self.is_listening:
            logger.warning("Already listening for wake words")
            return
        
        try:
            self.audio = pyaudio.PyAudio()
            self.audio_stream = self.audio.open(
                rate=self.sample_rate,
                channels=1,
                format=pyaudio.paInt16,
                input=True,
                frames_per_buffer=self.frame_length
            )
            self.is_listening = True
            logger.info("Started listening for wake words")
        except Exception as e:
            logger.error(f"Failed to start audio stream: {e}")
            raise
    
    def process_frame(self) -> Optional[int]:
        """
        Process a single audio frame and check for wake word.
        
        Returns:
            Keyword index if wake word detected, None otherwise.
        """
        if not self.is_listening or not self.audio_stream:
            return None
        
        try:
            # Read audio data
            pcm_bytes = self.audio_stream.read(self.frame_length, exception_on_overflow=False)
            
            # Convert bytes to 16-bit signed integers
            pcm = list(struct.unpack(f'<{self.porcupine.frame_length}h', pcm_bytes))
            
            keyword_index = self.porcupine.process(pcm)
            
            if keyword_index >= 0:
                logger.info(f"Wake word detected! Keyword index: {keyword_index}")
                if self.wake_word_callback:
                    self.wake_word_callback(keyword_index)
                return keyword_index
            
            return None
        except Exception as e:
            logger.error(f"Error processing audio frame: {e}")
            return None
    
    def stop_listening(self):
        """Stop listening for wake words."""
        if not self.is_listening:
            return
        
        self.is_listening = False
        
        if self.audio_stream:
            self.audio_stream.stop_stream()
            self.audio_stream.close()
            self.audio_stream = None
        
        if self.audio:
            self.audio.terminate()
            self.audio = None
        
        logger.info("Stopped listening for wake words")
    
    def __del__(self):
        """Cleanup on deletion."""
        self.stop_listening()
        if self.porcupine:
            self.porcupine.delete()

