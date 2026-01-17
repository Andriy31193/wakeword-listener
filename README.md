# Wake Word Listener

A simple, separate project responsible only for wake word detection and speech recording.

## Overview

This project listens for a wake word and, when triggered, records speech until silence is detected or a maximum recording length is reached. It is fully decoupled from audio buffering logic and can optionally query an MCP server for recent audio context.

## Features

- **Wake Word Detection**: Uses Picovoice Porcupine for wake word detection
- **Speech Recording**: Records speech after wake word detection
- **Silence Detection**: Stops recording when silence is detected (VAD with hysteresis)
- **Max Duration**: Enforces maximum recording length
- **Optional MCP Integration**: Can retrieve recent audio context from Audio Ring Buffer MCP Server
- **Clean Separation**: No ring buffer or long-term context logic

## Configuration

Edit `config.yaml` to customize:

- **Wake Word**: Model path, access key, sensitivity
- **Audio**: Sample rate, channels, frame length
- **Recording**: Silence timeout, max length, VAD threshold
- **MCP Client**: Enable/disable, host, port, endpoint
- **Logging**: Log level

## Installation

```bash
pip install -r requirements.txt
```

**Note**: You'll need the wake word model file (`.ppn`). Update `config.yaml` with the correct path to your wake word model.

## Usage

### Start the Listener

```bash
python main.py
```

The listener will start listening for wake words. Say the wake word to activate recording.

### Integration

The `_process_recorded_audio()` method in `main.py` is a placeholder where you would integrate with your downstream processing (e.g., speech recognition, chatbot). Currently, it just logs the recorded audio.

To integrate:

1. Implement speech recognition (e.g., using Whisper)
2. Send transcribed text to your AI/chatbot system
3. Optionally use context files from MCP server if AI doesn't understand the prompt

## Architecture

```
WakeWordDetector (listens for wake word)
    ↓ wake word detected
SpeechRecorder (records until silence/max length)
    ↓ audio bytes
MCPClient (optional: retrieve context)
    ↓ context files
Downstream Processing (placeholder)
```

## MCP Integration

If enabled in config, the listener can retrieve recent audio context from the Audio Ring Buffer MCP Server:

- When processing recorded audio, it automatically fetches the most recent N audio files
- These can be used to provide context if the AI doesn't understand the user's prompt
- The context files include base64-encoded audio data and metadata

## Behavior Flow

1. **Idle State**: Listener continuously checks for wake word
2. **Wake Word Detected**: Transition to recording state
3. **Recording**: Capture audio until:
   - Silence detected (VAD confirms silence after speech)
   - Maximum duration reached
4. **Processing**: Send recorded audio to downstream processing (placeholder)
5. **Optional Context Retrieval**: If enabled, fetch recent context from MCP server
6. **Return to Idle**: Continue listening for next wake word

## File Structure

- `config.yaml` - Configuration file
- `config.py` - Configuration loader
- `wake_word_detector.py` - Wake word detection (Porcupine)
- `speech_recorder.py` - Speech recording with silence detection
- `mcp_client.py` - MCP client for context retrieval (optional)
- `main.py` - Main listener entry point

## Notes

- **No Ring Buffer**: This project does not maintain any long-term audio buffer
- **Decoupled**: Fully independent from audio buffering logic
- **Optional MCP**: MCP client integration is optional and can be disabled
- **Placeholder Processing**: The `_process_recorded_audio()` method is a placeholder for your downstream processing

## Example Integration

```python
def _process_recorded_audio(self, audio_bytes: bytes):
    # Transcribe audio
    text = speech_recognizer.transcribe_audio(audio_bytes)
    
    # Get context if AI doesn't understand
    if text and "didn't understand" in text.lower():
        context_files = self.mcp_client.retrieve_recent_context(n=5)
        # Use context to enhance prompt
    
    # Send to AI/chatbot
    response = chatbot.process(text, context=context_files)
```

