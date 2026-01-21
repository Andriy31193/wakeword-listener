"""Audio playback API server using Flask."""
import logging
import os
import urllib.parse
import threading
import tempfile
import base64
from flask import Flask, request, jsonify
from sound_player import play_sound_async, stop_aplay

logger = logging.getLogger(__name__)

app = Flask(__name__)
current_playback_process = None
playback_lock = threading.Lock()
temp_files = []  # Track temporary files for cleanup
temp_files_lock = threading.Lock()


def _save_audio_data_to_temp_file(audio_data: bytes, file_extension: str = "wav") -> str:
    """
    Save raw audio data to a temporary file.
    
    Args:
        audio_data: Raw audio bytes
        file_extension: File extension for the temp file (default: wav)
        
    Returns:
        Path to the temporary file
    """
    # Create temporary file
    temp_fd, temp_path = tempfile.mkstemp(suffix=f".{file_extension}", prefix="audio_playback_")
    try:
        with os.fdopen(temp_fd, 'wb') as temp_file:
            temp_file.write(audio_data)
        
        # Track temp file for cleanup
        with temp_files_lock:
            temp_files.append(temp_path)
        
        logger.debug(f"Saved audio data to temporary file: {temp_path}")
        return temp_path
    except Exception as e:
        logger.error(f"Error saving audio data to temp file: {e}")
        try:
            os.close(temp_fd)
            if os.path.exists(temp_path):
                os.unlink(temp_path)
        except:
            pass
        raise


@app.route('/play', methods=['POST'])
@app.route('/play/<path:audiofile>', methods=['POST', 'GET'])
def play_audio(audiofile=None):
    """
    Play an audio file using aplay.
    
    Supports multiple input methods:
    1. File path in URL: /play/path/to/file.wav
    2. File path in query parameter: /play?file=/path/to/file.wav
    3. File path in JSON body: POST /play with {"file": "/path/to/file.wav"}
    4. Raw audio data in request body: POST /play with binary audio data
    5. Base64 encoded audio in JSON: POST /play with {"audio_base64": "...", "format": "wav"}
    6. Multipart form data: POST /play with file field
    
    Returns:
        JSON response with status
    """
    global current_playback_process
    
    audio_path = None
    is_temp_file = False
    
    try:
        # Method 1: Check for raw audio data in request body (binary)
        if request.content_type and 'audio' in request.content_type:
            logger.info("Received raw audio data in request body")
            audio_data = request.data
            if audio_data:
                # Try to determine format from content-type
                file_ext = "wav"  # default
                if 'mp3' in request.content_type:
                    file_ext = "mp3"
                elif 'ogg' in request.content_type:
                    file_ext = "ogg"
                elif 'flac' in request.content_type:
                    file_ext = "flac"
                
                audio_path = _save_audio_data_to_temp_file(audio_data, file_ext)
                is_temp_file = True
        
        # Method 2: Check for multipart form data with file
        elif request.files and 'file' in request.files:
            logger.info("Received audio file in multipart form data")
            file_obj = request.files['file']
            if file_obj:
                audio_data = file_obj.read()
                # Get extension from filename or content type
                filename = file_obj.filename or "audio.wav"
                file_ext = os.path.splitext(filename)[1][1:] or "wav"  # Remove leading dot
                audio_path = _save_audio_data_to_temp_file(audio_data, file_ext)
                is_temp_file = True
        
        # Method 3: Check for base64 encoded audio in JSON
        elif request.is_json:
            json_data = request.json
            if 'audio_base64' in json_data or 'audio' in json_data:
                logger.info("Received base64 encoded audio in JSON")
                audio_b64 = json_data.get('audio_base64') or json_data.get('audio')
                if audio_b64:
                    try:
                        audio_data = base64.b64decode(audio_b64)
                        file_ext = json_data.get('format', 'wav')
                        if file_ext and not file_ext.startswith('.'):
                            file_ext = file_ext.lstrip('.')
                        audio_path = _save_audio_data_to_temp_file(audio_data, file_ext)
                        is_temp_file = True
                    except Exception as e:
                        logger.error(f"Error decoding base64 audio: {e}")
                        return jsonify({
                            "status": "error",
                            "message": f"Invalid base64 audio data: {e}"
                        }), 400
            
            # Method 4: Check for file path in JSON
            elif 'file' in json_data:
                audio_path = json_data.get('file')
            elif 'path' in json_data:
                audio_path = json_data.get('path')
        
        # Method 5: Check for file path in query parameter
        elif 'file' in request.args:
            audio_path = request.args.get('file')
        elif 'path' in request.args:
            audio_path = request.args.get('path')
        
        # Method 6: Use path from URL parameter (if provided)
        elif audiofile:
            audio_path = audiofile
        
        # If no audio source found
        if not audio_path:
            return jsonify({
                "status": "error",
                "message": "No audio file or data provided. Send audio data in request body, multipart form, base64 JSON, or provide file path."
            }), 400
        
        # Decode URL-encoded path (if it's a path, not temp file)
        if not is_temp_file:
            audio_path = urllib.parse.unquote(audio_path)
            
            # Resolve to absolute path if relative
            if not os.path.isabs(audio_path):
                audio_path = os.path.abspath(audio_path)
        
        logger.info(f"Received play request for: {audio_path} (temp: {is_temp_file})")
        
        # Check if file exists (for non-temp files)
        if not is_temp_file and not os.path.exists(audio_path):
            logger.warning(f"Audio file not found: {audio_path}")
            return jsonify({
                "status": "error",
                "message": f"Audio file not found: {audio_path}"
            }), 404
        
        # Stop any currently playing audio
        with playback_lock:
            if current_playback_process:
                try:
                    current_playback_process.terminate()
                    current_playback_process.wait(timeout=1)
                except:
                    pass
                stop_aplay()
                current_playback_process = None
            
            # Start playing new audio
            process = play_sound_async(audio_path)
            if process:
                current_playback_process = process
                logger.info(f"Started playing audio: {audio_path} (PID: {process.pid})")
                
                # Schedule cleanup of temp file after playback (non-blocking)
                if is_temp_file:
                    def cleanup_temp_file():
                        process.wait()  # Wait for playback to finish
                        try:
                            if os.path.exists(audio_path):
                                os.unlink(audio_path)
                                with temp_files_lock:
                                    if audio_path in temp_files:
                                        temp_files.remove(audio_path)
                                logger.debug(f"Cleaned up temporary file: {audio_path}")
                        except Exception as e:
                            logger.warning(f"Error cleaning up temp file {audio_path}: {e}")
                    
                    threading.Thread(target=cleanup_temp_file, daemon=True).start()
                
                return jsonify({
                    "status": "success",
                    "message": f"Playing audio: {audio_path}",
                    "pid": process.pid,
                    "temp_file": is_temp_file
                })
            else:
                logger.error(f"Failed to start playback for: {audio_path}")
                # Clean up temp file if playback failed
                if is_temp_file and os.path.exists(audio_path):
                    try:
                        os.unlink(audio_path)
                        with temp_files_lock:
                            if audio_path in temp_files:
                                temp_files.remove(audio_path)
                    except:
                        pass
                return jsonify({
                    "status": "error",
                    "message": f"Failed to start playback for: {audio_path}"
                }), 500
    
    except Exception as e:
        logger.error(f"Error in play_audio: {e}", exc_info=True)
        # Clean up temp file on error
        if is_temp_file and audio_path and os.path.exists(audio_path):
            try:
                os.unlink(audio_path)
                with temp_files_lock:
                    if audio_path in temp_files:
                        temp_files.remove(audio_path)
            except:
                pass
        return jsonify({
            "status": "error",
            "message": f"Error processing audio: {str(e)}"
        }), 500


@app.route('/stop', methods=['POST', 'GET'])
def stop_audio():
    """
    Stop any currently playing audio.
    
    Returns:
        JSON response with status
    """
    global current_playback_process
    
    logger.info("Received stop request")
    
    with playback_lock:
        stopped = False
        
        # Stop the current playback process if exists
        if current_playback_process:
            try:
                current_playback_process.terminate()
                current_playback_process.wait(timeout=1)
                stopped = True
            except Exception as e:
                logger.warning(f"Error stopping playback process: {e}")
            current_playback_process = None
        
        # Also stop any aplay processes
        if stop_aplay():
            stopped = True
        
        if stopped:
            logger.info("Stopped audio playback")
            return jsonify({
                "status": "success",
                "message": "Audio playback stopped"
            })
        else:
            logger.info("No audio playback to stop")
            return jsonify({
                "status": "success",
                "message": "No audio playback was active"
            })


@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint."""
    return jsonify({
        "status": "healthy",
        "service": "audio-playback-api"
    })


def cleanup_old_temp_files(max_age_seconds: int = 300):
    """
    Clean up temporary files older than max_age_seconds.
    
    Args:
        max_age_seconds: Maximum age of temp files in seconds (default: 5 minutes)
    """
    import time
    current_time = time.time()
    
    with temp_files_lock:
        files_to_remove = []
        for temp_path in temp_files[:]:  # Copy list to avoid modification during iteration
            try:
                if os.path.exists(temp_path):
                    file_age = current_time - os.path.getmtime(temp_path)
                    if file_age > max_age_seconds:
                        os.unlink(temp_path)
                        files_to_remove.append(temp_path)
                        logger.debug(f"Cleaned up old temp file: {temp_path} (age: {file_age:.1f}s)")
                else:
                    # File doesn't exist, remove from tracking
                    files_to_remove.append(temp_path)
            except Exception as e:
                logger.warning(f"Error cleaning up temp file {temp_path}: {e}")
                files_to_remove.append(temp_path)
        
        # Remove cleaned files from tracking
        for temp_path in files_to_remove:
            if temp_path in temp_files:
                temp_files.remove(temp_path)


def run_api_server(host='127.0.0.1', port=5002, debug=False):
    """
    Run the audio playback API server.
    
    Args:
        host: Host to bind to
        port: Port to bind to
        debug: Enable Flask debug mode
    """
    logger.info(f"Starting audio playback API server on {host}:{port}")
    app.run(host=host, port=port, debug=debug, threaded=True, use_reloader=False)


if __name__ == '__main__':
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    run_api_server()

