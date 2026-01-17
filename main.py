"""Main entry point for Wake Word Listener."""
import logging
import time
import threading
from config import load_config
from wake_word_detector import WakeWordDetector
from speech_recorder import SpeechRecorder
from mcp_client import MCPClient
from n8n_client import N8NClient
from stt_client import STTClient

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class WakeWordListener:
    """Main wake word listener class."""
    
    def __init__(self, config: dict):
        """
        Initialize wake word listener.
        
        Args:
            config: Configuration dictionary
        """
        self.config = config
        self.is_running = False
        self.is_processing = False
        self.interrupt_flag = threading.Event()
        self._processing_lock = threading.Lock()
        
        # Initialize wake word detector
        wake_config = config["wake_word"]
        audio_config = config["audio"]
        
        self.wake_word_detector = WakeWordDetector(
            model_path=wake_config["model_path"],
            access_key=wake_config["access_key"],
            sample_rate=audio_config["sample_rate"],
            frame_length=audio_config["frame_length"],
            wake_word_callback=self._on_wake_word
        )
        
        # Initialize speech recorder
        recording_config = config["recording"]
        
        self.speech_recorder = SpeechRecorder(
            sample_rate=audio_config["sample_rate"],
            channels=audio_config["channels"],
            frame_length=audio_config["frame_length"],
            silence_timeout_secs=recording_config["silence_timeout_secs"],
            max_length_secs=recording_config["max_length_secs"],
            vad_energy_threshold=recording_config["vad_energy_threshold"]
        )
        
        # Initialize MCP client (optional)
        self.mcp_client = None
        mcp_config = config.get("mcp_client", {})
        if mcp_config.get("enabled", False):
            self.mcp_client = MCPClient(
                host=mcp_config["host"],
                port=mcp_config["port"],
                endpoint_retrieve_context=mcp_config["endpoint_retrieve_context"]
            )
            
            # Check if server is available
            if self.mcp_client.is_server_available():
                logger.info("MCP server is available for context retrieval")
            else:
                logger.warning("MCP server is not available (context retrieval disabled)")
        
        # Initialize STT client
        stt_config = config.get("stt", {})
        self.stt_client = STTClient(
            endpoint=stt_config.get("endpoint", ""),
            sample_rate=audio_config["sample_rate"],
            timeout=stt_config.get("timeout", 30),
            model=stt_config.get("model", "medium"),
            device=stt_config.get("device", "cuda")
        )
        
        # Initialize n8n client
        n8n_config = config.get("n8n", {})
        webhook_url = n8n_config.get("webhook_url", "")
        if webhook_url:
            self.n8n_client = N8NClient(
                webhook_url=webhook_url,
                sample_rate=audio_config["sample_rate"]
            )
            logger.info("N8N client initialized")
        else:
            self.n8n_client = None
            logger.warning("N8N webhook URL not configured (audio will not be sent to n8n)")
        
        logger.info("Wake Word Listener initialized")
    
    def _on_wake_word(self, keyword_index: int):
        """Callback when wake word is detected."""
        logger.info(f"Wake word detected! Keyword index: {keyword_index}")
        
        # Check if already processing - set interrupt flag
        with self._processing_lock:
            if self.is_processing:
                logger.info("Interrupting current processing for new wake word")
                self.interrupt_flag.set()
                # Stop current recording if active
                if self.speech_recorder.is_recording:
                    self.speech_recorder.stop_recording()
            
            # Mark as processing and clear interrupt flag
            self.is_processing = True
            self.interrupt_flag.clear()
        
        # Process wake word in background thread (non-blocking)
        threading.Thread(target=self._handle_wake_word, daemon=True).start()
    
    def _handle_wake_word(self):
        """Handle wake word detection: record speech and send to n8n."""
        try:
            # Check for interrupt before recording
            if self.interrupt_flag.is_set():
                logger.info("Wake word handler interrupted before recording")
                return
            
            # Record speech
            logger.info("Recording user speech...")
            audio_bytes = self.speech_recorder.start_recording()
            
            # Check for interrupt after recording
            if self.interrupt_flag.is_set():
                logger.info("Wake word handler interrupted after recording")
                return
            
            if not audio_bytes or len(audio_bytes) == 0:
                logger.warning("No audio recorded")
                return
            
            # Process recorded audio
            self._process_recorded_audio(audio_bytes)
            
        except Exception as e:
            logger.error(f"Error handling wake word: {e}", exc_info=True)
        finally:
            # Clear processing state
            with self._processing_lock:
                self.is_processing = False
    
    def _process_recorded_audio(self, audio_bytes: bytes):
        """
        Process recorded audio and send to n8n webhook.
        
        Args:
            audio_bytes: Recorded audio bytes (16-bit PCM)
        """
        logger.info(f"Processing recorded audio: {len(audio_bytes)} bytes")
        
        if not self.n8n_client:
            logger.warning("N8N client not initialized, cannot send audio")
            return
        
        # Check for interrupt before transcription
        if self.interrupt_flag.is_set():
            logger.info("Audio processing interrupted before transcription")
            return
        
        # Transcribe audio using STT (remote endpoint or local CUDA)
        transcribed_text = None
        try:
            logger.info("Transcribing audio...")
            transcribed_text = self.stt_client.transcribe(audio_bytes)
            
            if transcribed_text:
                logger.info(f"Transcription: {transcribed_text[:100]}...")
            else:
                logger.warning("Transcription returned no text")
        except Exception as e:
            logger.error(f"Error during transcription: {e}", exc_info=True)
        
        # Check for interrupt after transcription
        if self.interrupt_flag.is_set():
            logger.info("Audio processing interrupted after transcription")
            return
        
        # Optionally retrieve context from MCP server if available
        context_files = None
        if self.mcp_client and self.mcp_client.is_server_available():
            logger.info("Retrieving recent context from MCP server...")
            context_files = self.mcp_client.retrieve_recent_context(n=5)
            
            if context_files:
                logger.info(f"Retrieved {len(context_files)} context files from MCP server")
            else:
                logger.info("No context files retrieved from MCP server")
        
        # Check for interrupt before sending
        if self.interrupt_flag.is_set():
            logger.info("Audio processing interrupted before sending to n8n")
            return
        
        # Only send if we have transcribed text
        if not transcribed_text:
            logger.warning("No transcribed text available, cannot send to n8n")
            return
        
        # Send transcribed text to n8n webhook (no audio data, only text)
        try:
            response = self.n8n_client.send_text(
                text=transcribed_text,
                context_files=context_files
            )
            
            # Check for interrupt after sending
            if self.interrupt_flag.is_set():
                logger.info("Audio processing interrupted after sending to n8n")
                return
            
            if response:
                logger.info(f"Successfully sent text to n8n: {response}")
            else:
                logger.error("Failed to send text to n8n (no response)")
        except Exception as e:
            logger.error(f"Error sending text to n8n: {e}", exc_info=True)
    
    def start(self):
        """Start listening for wake words."""
        if self.is_running:
            logger.warning("Wake word listener is already running")
            return
        
        logger.info("Starting wake word listener...")
        
        try:
            self.wake_word_detector.start_listening()
            self.is_running = True
            
            logger.info("Wake word listener started. Say the wake word to activate.")
            
            # Main loop: process wake word frames
            try:
                while self.is_running:
                    self.wake_word_detector.process_frame()
                    time.sleep(0.01)  # Small sleep to avoid CPU spinning
                    
            except KeyboardInterrupt:
                logger.info("Received interrupt signal")
            finally:
                self.stop()
                
        except Exception as e:
            logger.error(f"Error starting wake word listener: {e}")
            self.stop()
            raise
    
    def stop(self):
        """Stop listening for wake words."""
        if not self.is_running:
            return
        
        logger.info("Stopping wake word listener...")
        
        self.is_running = False
        self.interrupt_flag.set()  # Signal interrupt to stop any processing
        
        if self.wake_word_detector:
            try:
                self.wake_word_detector.stop_listening()
            except Exception as e:
                logger.warning(f"Error stopping wake word detector: {e}")
        
        if self.speech_recorder:
            try:
                self.speech_recorder.stop_recording()
            except Exception as e:
                logger.warning(f"Error stopping speech recorder: {e}")
        
        logger.info("Wake word listener stopped")


def main():
    """Main function."""
    # Load configuration
    config = load_config()
    
    # Set logging level from config
    log_level = config.get("logging", {}).get("level", "INFO")
    logging.getLogger().setLevel(getattr(logging, log_level.upper()))
    
    logger.info("Starting Wake Word Listener...")
    logger.info(f"Configuration: {config}")
    
    # Create and start listener
    listener = WakeWordListener(config)
    
    try:
        listener.start()
    except KeyboardInterrupt:
        logger.info("Shutting down...")


if __name__ == "__main__":
    main()

