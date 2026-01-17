"""Speech recording module with silence detection."""
import pyaudio
import logging
import struct
import time
from typing import Optional, Callable

logger = logging.getLogger(__name__)


class VADStateMachine:
    """Voice Activity Detection state machine with hysteresis."""
    
    def __init__(
        self,
        speech_threshold: float,
        speech_start_frames: int = 3,
        silence_confirmation_frames: int = 47  # ~1.5s at 31.25 fps
    ):
        """
        Initialize VAD state machine.
        
        Args:
            speech_threshold: RMS energy threshold for speech detection
            speech_start_frames: Minimum consecutive speech frames to enter SPEECH state
            silence_confirmation_frames: Minimum consecutive silence frames to confirm silence
        """
        self.speech_threshold = speech_threshold
        self.speech_start_frames = speech_start_frames
        self.silence_confirmation_frames = silence_confirmation_frames
        
        self.state = "LISTENING"  # LISTENING, SPEECH, POSSIBLE_SILENCE, CONFIRMED_SILENCE
        self.consecutive_speech_frames = 0
        self.consecutive_silence_frames = 0
        logger.debug(f"VAD initialized: threshold={speech_threshold}, speech_start={speech_start_frames}, silence_confirm={silence_confirmation_frames}")
    
    def _calculate_rms(self, frame: bytes) -> float:
        """Calculate RMS energy of an audio frame."""
        try:
            if len(frame) == 0:
                return 0.0
            if len(frame) % 2 != 0:
                frame = frame[:-1]
            if len(frame) == 0:
                return 0.0
            samples = struct.unpack(f'<{len(frame)//2}h', frame)
            if len(samples) == 0:
                return 0.0
            rms = (sum(x * x for x in samples) / len(samples)) ** 0.5
            return rms
        except Exception as e:
            logger.error(f"Error calculating RMS: {e}")
            return 0.0
    
    def process_frame(self, frame: bytes):
        """Process a single audio frame and update state."""
        rms = self._calculate_rms(frame)
        has_speech = rms > self.speech_threshold
        
        # Log occasionally for debugging
        if self.state == "SPEECH" and self.consecutive_silence_frames % 50 == 0:
            logger.debug(f"VAD state: {self.state}, RMS: {rms:.1f}, speech: {has_speech}, silence_frames: {self.consecutive_silence_frames}")
        
        if self.state == "LISTENING":
            if has_speech:
                self.consecutive_speech_frames += 1
                if self.consecutive_speech_frames >= self.speech_start_frames:
                    self.state = "SPEECH"
                    self.consecutive_silence_frames = 0
            else:
                self.consecutive_speech_frames = 0
        
        elif self.state == "SPEECH":
            if has_speech:
                self.consecutive_speech_frames += 1
                self.consecutive_silence_frames = 0
            else:
                self.consecutive_speech_frames = 0
                self.consecutive_silence_frames += 1
                if self.consecutive_silence_frames >= self.silence_confirmation_frames:
                    self.state = "CONFIRMED_SILENCE"
                else:
                    self.state = "POSSIBLE_SILENCE"
        
        elif self.state == "POSSIBLE_SILENCE":
            if has_speech:
                self.state = "SPEECH"
                self.consecutive_speech_frames += 1
                self.consecutive_silence_frames = 0
            else:
                self.consecutive_silence_frames += 1
                if self.consecutive_silence_frames >= self.silence_confirmation_frames:
                    self.state = "CONFIRMED_SILENCE"
        
        elif self.state == "CONFIRMED_SILENCE":
            if has_speech:
                self.state = "SPEECH"
                self.consecutive_speech_frames = 1
                self.consecutive_silence_frames = 0
    
    def is_silence_confirmed(self) -> bool:
        """Check if silence has been confirmed."""
        return self.state == "CONFIRMED_SILENCE"
    
    def is_speech_active(self) -> bool:
        """Check if speech is currently active."""
        return self.state == "SPEECH"
    
    def reset(self):
        """Reset state machine to initial LISTENING state."""
        self.state = "LISTENING"
        self.consecutive_speech_frames = 0
        self.consecutive_silence_frames = 0


class SpeechRecorder:
    """Records speech until silence or max duration."""
    
    def __init__(
        self,
        sample_rate: int = 16000,
        channels: int = 1,
        frame_length: int = 512,
        silence_timeout_secs: float = 2.0,
        max_length_secs: float = 30.0,
        vad_energy_threshold: float = 300
    ):
        """
        Initialize speech recorder.
        
        Args:
            sample_rate: Audio sample rate
            channels: Number of audio channels
            frame_length: Audio frame length
            silence_timeout_secs: Stop recording after silence detected
            max_length_secs: Maximum recording duration
            vad_energy_threshold: VAD energy threshold
        """
        self.sample_rate = sample_rate
        self.channels = channels
        self.frame_length = frame_length
        self.silence_timeout_secs = silence_timeout_secs
        self.max_length_secs = max_length_secs
        self.vad_energy_threshold = vad_energy_threshold
        
        self.audio = None
        self.stream = None
        self.is_recording = False
        
        # Calculate silence confirmation frames
        frames_per_second = sample_rate / frame_length
        silence_confirmation_frames = int(silence_timeout_secs * frames_per_second)
        
        self.vad = VADStateMachine(
            speech_threshold=vad_energy_threshold,
            speech_start_frames=3,
            silence_confirmation_frames=silence_confirmation_frames
        )
    
    def start_recording(self) -> bytes:
        """
        Start recording speech until silence or max duration.
        
        Returns:
            Recorded audio bytes (16-bit PCM)
        """
        if self.is_recording:
            logger.warning("Already recording")
            return b''
        
        logger.info("Starting speech recording...")
        
        try:
            self.audio = pyaudio.PyAudio()
            self.stream = self.audio.open(
                rate=self.sample_rate,
                channels=self.channels,
                format=pyaudio.paInt16,
                input=True,
                frames_per_buffer=self.frame_length
            )
            
            self.is_recording = True
            self.vad.reset()
            
            frames = []
            start_time = time.time()
            frame_duration = self.frame_length / self.sample_rate
            speech_detected = False  # Track if we've ever detected speech
            
            logger.info(f"Recording until silence ({self.silence_timeout_secs}s) or max length ({self.max_length_secs}s)...")
            logger.debug(f"VAD threshold: {self.vad_energy_threshold}, silence confirmation frames: {self.vad.silence_confirmation_frames}")
            
            while self.is_recording:
                # Check timeout
                elapsed = time.time() - start_time
                if elapsed >= self.max_length_secs:
                    logger.info(f"Reached max duration ({self.max_length_secs}s), stopping recording")
                    break
                
                # Read frame
                frame = self.stream.read(self.frame_length, exception_on_overflow=False)
                
                if len(frame) == 0:
                    time.sleep(frame_duration)
                    continue
                
                frames.append(frame)
                
                # Process through VAD
                self.vad.process_frame(frame)
                
                # Track if we've detected speech at least once (check state changes)
                if not speech_detected and (self.vad.is_speech_active() or self.vad.state in ("SPEECH", "POSSIBLE_SILENCE", "CONFIRMED_SILENCE")):
                    speech_detected = True
                    logger.info(f"Speech detected (state: {self.vad.state})")
                
                # Check for silence (only after we've had some speech)
                if speech_detected:
                    if self.vad.is_silence_confirmed():
                        # We've had speech and now silence is confirmed
                        elapsed = time.time() - start_time
                        logger.info(f"Silence confirmed (after {len(frames)} frames, {elapsed:.2f}s), stopping recording")
                        break
                    elif self.vad.state == "POSSIBLE_SILENCE":
                        # Log progress towards silence detection
                        if self.vad.consecutive_silence_frames % 20 == 0:  # Log every 20 frames
                            logger.debug(f"Silence building: {self.vad.consecutive_silence_frames}/{self.vad.silence_confirmation_frames} frames")
                
                # Small sleep to avoid CPU spinning
                time.sleep(frame_duration * 0.5)
            
            audio_bytes = b''.join(frames)
            duration = len(frames) * frame_duration
            
            logger.info(f"Recording complete: {len(frames)} frames, {duration:.2f}s, {len(audio_bytes)} bytes")
            
            return audio_bytes
            
        except Exception as e:
            logger.error(f"Error during recording: {e}")
            return b''
        finally:
            self.stop_recording()
    
    def stop_recording(self):
        """Stop recording and cleanup."""
        if not self.is_recording:
            return
        
        self.is_recording = False
        
        if self.stream:
            try:
                if self.stream.is_active():
                    self.stream.stop_stream()
                self.stream.close()
            except Exception as e:
                logger.warning(f"Error stopping stream: {e}")
            finally:
                self.stream = None
        
        if self.audio:
            try:
                self.audio.terminate()
            except Exception as e:
                logger.warning(f"Error terminating PyAudio: {e}")
            finally:
                self.audio = None
        
        logger.info("Recording stopped")
    
    def __del__(self):
        """Cleanup on deletion."""
        self.stop_recording()

