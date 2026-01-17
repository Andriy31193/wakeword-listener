"""Speech-to-Text client for transcription (remote endpoint or local CUDA)."""
import logging
import requests
import base64
import wave
import io
from typing import Optional

logger = logging.getLogger(__name__)


class STTClient:
    """Client for speech-to-text transcription (remote or local CUDA)."""
    
    def __init__(
        self,
        endpoint: str = "",
        sample_rate: int = 16000,
        timeout: int = 30,
        model: str = "medium",
        device: str = "cuda"
    ):
        """
        Initialize STT client.
        
        Args:
            endpoint: STT server endpoint URL. If empty, uses local Whisper with CUDA.
            sample_rate: Audio sample rate
            timeout: Request timeout for remote endpoint
            model: Whisper model size for local transcription (tiny, base, small, medium, large)
            device: Device for local transcription (cuda or cpu)
        """
        self.endpoint = endpoint
        self.sample_rate = sample_rate
        self.timeout = timeout
        self.model = model
        self.device = device
        
        # Initialize local Whisper if no endpoint
        self.whisper_model = None
        if not self.endpoint:
            try:
                import whisper
                logger.info(f"Loading Whisper model '{model}' for local transcription (device: {device})...")
                self.whisper_model = whisper.load_model(model, device=device)
                logger.info(f"Whisper model loaded successfully on {device}")
            except ImportError:
                logger.error("Whisper not installed. Install with: pip install openai-whisper")
                raise
            except Exception as e:
                logger.error(f"Failed to load Whisper model: {e}")
                raise
        
        if self.endpoint:
            logger.info(f"STT client initialized with remote endpoint: {endpoint}")
        else:
            logger.info(f"STT client initialized for local transcription (model: {model}, device: {device})")
    
    def _audio_bytes_to_wav(self, audio_bytes: bytes, channels: int = 1) -> bytes:
        """
        Convert raw PCM audio bytes to WAV format.
        
        Args:
            audio_bytes: Raw PCM audio bytes (16-bit)
            channels: Number of audio channels
            
        Returns:
            WAV-formatted bytes
        """
        wav_buffer = io.BytesIO()
        with wave.open(wav_buffer, 'wb') as wav_file:
            wav_file.setnchannels(channels)
            wav_file.setsampwidth(2)  # 16-bit = 2 bytes
            wav_file.setframerate(self.sample_rate)
            wav_file.writeframes(audio_bytes)
        
        wav_buffer.seek(0)
        return wav_buffer.read()
    
    def _transcribe_remote(self, audio_bytes: bytes) -> Optional[str]:
        """
        Transcribe audio using remote STT endpoint.
        
        Args:
            audio_bytes: Raw PCM audio bytes
            
        Returns:
            Transcribed text, or None on error
        """
        try:
            # Convert to WAV
            wav_bytes = self._audio_bytes_to_wav(audio_bytes)
            
            # Encode as base64
            audio_b64 = base64.b64encode(wav_bytes).decode('utf-8')
            
            # Prepare payload
            payload = {
                "audio_base64": audio_b64,
                "format": "wav",
                "sample_rate": self.sample_rate
            }
            
            logger.info(f"Sending audio to STT endpoint: {self.endpoint}")
            response = requests.post(
                self.endpoint,
                json=payload,
                timeout=self.timeout
            )
            
            response.raise_for_status()
            result = response.json()
            
            # Extract text from response (support various response formats)
            text = (
                result.get("text") or
                result.get("transcription") or
                result.get("result") or
                result.get("output")
            )
            
            if text:
                logger.info(f"STT transcription received: {text[:100]}...")
                return text.strip()
            else:
                logger.warning(f"STT endpoint returned no text: {result}")
                return None
                
        except requests.exceptions.RequestException as e:
            logger.error(f"Error calling STT endpoint: {e}")
            return None
        except Exception as e:
            logger.error(f"Error in remote transcription: {e}")
            return None
    
    def _transcribe_local(self, audio_bytes: bytes) -> Optional[str]:
        """
        Transcribe audio using local Whisper with CUDA.
        
        Args:
            audio_bytes: Raw PCM audio bytes
            
        Returns:
            Transcribed text, or None on error
        """
        if not self.whisper_model:
            logger.error("Whisper model not loaded")
            return None
        
        try:
            import numpy as np
            
            # Convert bytes to numpy array (16-bit signed integers)
            # Whisper expects float32 in range [-1, 1]
            audio_array = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0
            
            logger.info(f"Transcribing audio locally with Whisper (model: {self.model}, device: {self.device})...")
            
            # Transcribe directly from numpy array
            max_samples = 30 * self.sample_rate  # 30 seconds max per chunk
            if len(audio_array) > max_samples:
                logger.debug(f"Audio too large ({len(audio_array)} samples), splitting into chunks")
                # Split and transcribe in chunks
                texts = []
                for i in range(0, len(audio_array), max_samples):
                    chunk = audio_array[i:i + max_samples]
                    result = self.whisper_model.transcribe(
                        chunk,
                        language=None,  # Auto-detect language
                        verbose=False
                    )
                    chunk_text = result["text"].strip()
                    if chunk_text:
                        texts.append(chunk_text)
                text = " ".join(texts) if texts else None
            else:
                result = self.whisper_model.transcribe(
                    audio_array,
                    language=None,  # Auto-detect language
                    verbose=False
                )
                text = result["text"].strip()
            
            if text:
                logger.info(f"Local transcription completed: {text[:100]}...")
                return text
            else:
                logger.warning("Whisper returned empty transcription")
                return None
                
        except ImportError:
            logger.error("NumPy not installed. Install with: pip install numpy")
            return None
        except Exception as e:
            logger.error(f"Error in local transcription: {e}", exc_info=True)
            return None
    
    def transcribe(self, audio_bytes: bytes) -> Optional[str]:
        """
        Transcribe audio bytes to text.
        
        Uses remote endpoint if configured, otherwise uses local Whisper with CUDA.
        
        Args:
            audio_bytes: Raw PCM audio bytes (16-bit)
            
        Returns:
            Transcribed text, or None on error
        """
        if not audio_bytes or len(audio_bytes) == 0:
            logger.warning("Empty audio bytes provided")
            return None
        
        if self.endpoint:
            return self._transcribe_remote(audio_bytes)
        else:
            return self._transcribe_local(audio_bytes)

