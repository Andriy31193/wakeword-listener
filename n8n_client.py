"""n8n webhook client for sending audio to n8n."""
import logging
import requests
import base64
import wave
import io
import time
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)


class N8NClient:
    """Client for sending audio to n8n webhook in n8n-playable format."""
    
    def __init__(self, webhook_url: str, sample_rate: int = 16000):
        """
        Initialize n8n client.
        
        Args:
            webhook_url: n8n webhook URL
            sample_rate: Audio sample rate for WAV encoding
        """
        self.webhook_url = webhook_url
        self.sample_rate = sample_rate
        logger.info(f"Initialized N8NClient with webhook: {webhook_url}")
    
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
    
    def _wav_to_data_url(self, wav_bytes: bytes) -> str:
        """
        Convert WAV bytes to data URL format for n8n playback.
        
        Args:
            wav_bytes: WAV-formatted audio bytes
            
        Returns:
            Data URL string (data:audio/wav;base64,...)
        """
        audio_b64 = base64.b64encode(wav_bytes).decode('utf-8')
        return f"data:audio/wav;base64,{audio_b64}"
    
    def send_text(
        self,
        text: str,
        context: Optional[str] = None,
        context_files: Optional[List[Dict[str, Any]]] = None,
        timeout: int = 30
    ) -> Optional[Dict[str, Any]]:
        """
        Send transcribed text to n8n webhook (no audio data).
        
        Args:
            text: Transcribed text (required)
            context: Optional context text (from transcriptions)
            context_files: Optional list of context files from MCP server (metadata only, no audio)
            timeout: Request timeout in seconds
            
        Returns:
            Response JSON dict, or None on error
        """
        if not text:
            logger.error("Text is required for n8n request")
            return None
        
        try:
            # Prepare payload with only text (no audio data)
            payload = {
                "userPrompt": text,  # Main user prompt
                "timestamp": time.time()
            }
            
            # Add context if provided
            if context:
                payload["context"] = context
            
            # Add context files metadata if provided (without audio data URLs)
            if context_files:
                # Include context file metadata only (no audio data)
                context_metadata = []
                for ctx_file in context_files:
                    context_metadata.append({
                        "filename": ctx_file.get("filename", "unknown.wav"),
                        "timestamp": ctx_file.get("timestamp"),
                        "duration": ctx_file.get("duration"),
                        "size": ctx_file.get("size")
                        # Note: audio_data_url removed - only metadata
                    })
                
                if context_metadata:
                    payload["context_files"] = context_metadata
                    payload["context_count"] = len(context_metadata)
                    logger.info(f"Included {len(context_metadata)} context file metadata entries in payload")
            
            # For backward compatibility, also include "query" field
            if context:
                payload["query"] = f"{context} {text}".strip()
            else:
                payload["query"] = text
            
            logger.info(f"Sending text to n8n: text='{text[:100]}...', context={bool(context)}, context_files={len(context_files) if context_files else 0}")
            
            # Send HTTP request
            response = requests.post(
                self.webhook_url,
                json=payload,
                timeout=timeout
            )
            
            response.raise_for_status()
            result = response.json()
            
            logger.info(f"Received response from n8n: {type(result)}")
            return result
            
        except requests.exceptions.RequestException as e:
            logger.error(f"HTTP error sending text to n8n: {e}")
            return None
        except Exception as e:
            logger.error(f"Error sending text to n8n: {e}")
            return None
    
    def send_audio(
        self,
        audio_bytes: bytes,
        text: Optional[str] = None,
        context: Optional[str] = None,
        context_files: Optional[List[Dict[str, Any]]] = None,
        timeout: int = 30
    ) -> Optional[Dict[str, Any]]:
        """
        Send transcribed text to n8n webhook (no audio data).
        
        This method now only sends text - audio_bytes parameter is ignored.
        Use send_text() directly if you don't have audio bytes.
        
        Args:
            audio_bytes: Audio bytes (ignored, kept for backward compatibility)
            text: Transcribed text (required)
            context: Optional context text
            context_files: Optional context files metadata
            timeout: Request timeout in seconds
            
        Returns:
            Response JSON dict, or None on error
        """
        if not text:
            logger.warning("No text provided, cannot send to n8n")
            return None
        
        # Delegate to send_text (ignore audio_bytes)
        return self.send_text(
            text=text,
            context=context,
            context_files=context_files,
            timeout=timeout
        )

