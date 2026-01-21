"""Speech-to-Text client for transcription (remote endpoint, local CUDA, or Groq)."""
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
        transcription_type: str = "local",
        endpoint: str = "",
        sample_rate: int = 16000,
        timeout: int = 30,
        model: str = "medium",
        device: str = "cuda",
        groq_api_key: str = ""
    ):
        """
        Initialize STT client.
        
        Args:
            transcription_type: Type of transcription ("local", "remote", or "groq")
            endpoint: STT server endpoint URL (required if type is "remote")
            sample_rate: Audio sample rate
            timeout: Request timeout for remote endpoint
            model: Whisper model size for local transcription (tiny, base, small, medium, large)
            device: Device for local transcription (cuda or cpu)
            groq_api_key: Groq API key (required if type is "groq")
        """
        self.transcription_type = transcription_type.lower()
        self.endpoint = endpoint
        self.sample_rate = sample_rate
        self.timeout = timeout
        self.model = model
        self.device = device
        self.groq_api_key = groq_api_key
        
        # Initialize local Whisper if type is "local"
        self.whisper_model = None
        if self.transcription_type == "local":
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
        elif self.transcription_type == "groq":
            if not self.groq_api_key:
                raise ValueError("Groq API key is required when transcription_type is 'groq'")
            try:
                from groq import Groq
                self.groq_client = Groq(api_key=self.groq_api_key)
                logger.info("Groq client initialized successfully")
            except ImportError:
                logger.error("Groq SDK not installed. Install with: pip install groq")
                raise
            except Exception as e:
                logger.error(f"Failed to initialize Groq client: {e}")
                raise
        elif self.transcription_type == "remote":
            if not self.endpoint:
                raise ValueError("Endpoint is required when transcription_type is 'remote'")
        
        if self.transcription_type == "remote":
            logger.info(f"STT client initialized with remote endpoint: {endpoint}")
        elif self.transcription_type == "groq":
            logger.info("STT client initialized for Groq transcription")
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
    
    def _transcribe_groq(self, audio_bytes: bytes) -> Optional[str]:
        """
        Transcribe audio using Groq API.
        
        Args:
            audio_bytes: Raw PCM audio bytes
            
        Returns:
            Transcribed text, or None on error
        """
        if not hasattr(self, 'groq_client'):
            logger.error("Groq client not initialized")
            return None
        
        try:
            # Convert to WAV
            wav_bytes = self._audio_bytes_to_wav(audio_bytes)
            
            # Create a file-like object for Groq API
            audio_file = io.BytesIO(wav_bytes)
            audio_file.seek(0)  # Ensure we're at the start
            audio_file.name = "audio.wav"
            
            logger.info("Transcribing audio with Groq...")
            
            # Use Groq's Whisper API (OpenAI-compatible)
            # The file parameter should be a tuple: (filename, file_object, content_type)
            transcription = self.groq_client.audio.transcriptions.create(
                file=(audio_file.name, audio_file, "audio/wav"),
                model="whisper-large-v3-turbo",
                response_format="text"
            )
            
            if transcription:
                # Groq returns the text directly when response_format is "text"
                text = transcription.strip() if isinstance(transcription, str) else str(transcription).strip()
                logger.info(f"Groq transcription completed: {text[:100]}...")
                return text
            else:
                logger.warning("Groq returned empty transcription")
                return None
                
        except Exception as e:
            logger.error(f"Error in Groq transcription: {e}", exc_info=True)
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
        
        Uses the configured transcription type (local, remote, or groq).
        
        Args:
            audio_bytes: Raw PCM audio bytes (16-bit)
            
        Returns:
            Transcribed text, or None on error
        """
        if not audio_bytes or len(audio_bytes) == 0:
            logger.warning("Empty audio bytes provided")
            return None
        
        if self.transcription_type == "remote":
            return self._transcribe_remote(audio_bytes)
        elif self.transcription_type == "groq":
            return self._transcribe_groq(audio_bytes)
        else:  # local
            return self._transcribe_local(audio_bytes)

