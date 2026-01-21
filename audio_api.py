"""Audio playback API server using Flask."""
import logging
import os
import urllib.parse
import threading
import tempfile
from flask import Flask, request, jsonify
from sound_player import play_sound_async, stop_aplay

logger = logging.getLogger(__name__)

app = Flask(__name__)
current_playback_process = None
playback_lock = threading.Lock()
temp_files = []  # Track temporary files for cleanup


@app.route('/play', methods=['POST'])
@app.route('/play/<path:audiofile>', methods=['POST', 'GET'])
def play_audio(audiofile=None):
    """
    Play an audio file using aplay.
    
    Supports:
    - File path in URL: /play/path/to/file.wav
    - File path in query parameter: /play?file=/path/to/file.wav
    - File path in JSON body: POST /play with {"file": "/path/to/file.wav"}
    - Binary audio data in request body: POST /play with raw binary data (n8n Binary File)
    - Multipart form data: POST /play with file upload
    
    Returns:
        JSON response with status
    """
    global current_playback_process, temp_files
    
    audiofile_path = None
    
    # Check for binary audio data in request body (n8n Binary File)
    if request.method == 'POST' and request.data and len(request.data) > 0:
        # Check if this is binary data (not JSON or form data)
        content_type = request.content_type or ''
        
        # Handle raw binary data (n8n Binary File)
        if 'application/octet-stream' in content_type or \
           'audio/' in content_type or \
           (not request.is_json and not content_type.startswith('application/json') and 
            not content_type.startswith('multipart/form-data') and 
            not content_type.startswith('application/x-www-form-urlencoded')):
            
            logger.info(f"Received binary audio data ({len(request.data)} bytes, Content-Type: {content_type})")
            
            # Determine file extension from Content-Type or use default
            file_ext = '.wav'  # Default
            if 'audio/wav' in content_type or 'audio/x-wav' in content_type:
                file_ext = '.wav'
            elif 'audio/mpeg' in content_type or 'audio/mp3' in content_type:
                file_ext = '.mp3'
            elif 'audio/ogg' in content_type:
                file_ext = '.ogg'
            elif 'audio/flac' in content_type:
                file_ext = '.flac'
            
            # Save binary data to temporary file
            try:
                temp_fd, temp_path = tempfile.mkstemp(suffix=file_ext, prefix='n8n_audio_')
                with os.fdopen(temp_fd, 'wb') as temp_file:
                    temp_file.write(request.data)
                
                audiofile_path = temp_path
                temp_files.append(temp_path)  # Track for cleanup
                logger.info(f"Saved binary audio data to temporary file: {temp_path}")
            except Exception as e:
                logger.error(f"Error saving binary audio data: {e}", exc_info=True)
                return jsonify({
                    "status": "error",
                    "message": f"Error saving binary audio data: {str(e)}"
                }), 500
    
    # Check for multipart form data (file upload)
    if not audiofile_path and request.method == 'POST' and request.files:
        if 'file' in request.files:
            uploaded_file = request.files['file']
            if uploaded_file.filename:
                logger.info(f"Received file upload: {uploaded_file.filename}")
                try:
                    temp_fd, temp_path = tempfile.mkstemp(suffix=os.path.splitext(uploaded_file.filename)[1] or '.wav', 
                                                          prefix='uploaded_audio_')
                    uploaded_file.save(temp_path)
                    os.close(temp_fd)
                    audiofile_path = temp_path
                    temp_files.append(temp_path)
                    logger.info(f"Saved uploaded file to temporary file: {temp_path}")
                except Exception as e:
                    logger.error(f"Error saving uploaded file: {e}", exc_info=True)
                    return jsonify({
                        "status": "error",
                        "message": f"Error saving uploaded file: {str(e)}"
                    }), 500
    
    # If no binary data, check for file path in various locations
    if not audiofile_path:
        # Check JSON body
        if request.is_json:
            if 'file' in request.json:
                audiofile_path = request.json.get('file')
            elif 'path' in request.json:
                audiofile_path = request.json.get('path')
        
        # Check query parameters
        if not audiofile_path:
            if 'file' in request.args:
                audiofile_path = request.args.get('file')
            elif 'path' in request.args:
                audiofile_path = request.args.get('path')
        
        # Check URL path parameter
        if not audiofile_path and audiofile:
            audiofile_path = audiofile
    
    if not audiofile_path:
        return jsonify({
            "status": "error",
            "message": "No audio file path or binary data provided"
        }), 400
    
    # Decode URL-encoded path
    audiofile_path = urllib.parse.unquote(audiofile_path)
    
    # Resolve to absolute path if relative (only for file paths, not temp files)
    if not os.path.isabs(audiofile_path) and not audiofile_path.startswith(tempfile.gettempdir()):
        audiofile_path = os.path.abspath(audiofile_path)
    
    logger.info(f"Received play request for: {audiofile_path}")
    
    # Check if file exists
    if not os.path.exists(audiofile_path):
        logger.warning(f"Audio file not found: {audiofile_path}")
        return jsonify({
            "status": "error",
            "message": f"Audio file not found: {audiofile_path}"
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
        process = play_sound_async(audiofile_path)
        if process:
            current_playback_process = process
            
            # Schedule cleanup of temporary file after playback (if it's a temp file)
            if audiofile_path in temp_files:
                def cleanup_temp_file(file_path, proc):
                    proc.wait()  # Wait for playback to finish
                    try:
                        if os.path.exists(file_path):
                            os.remove(file_path)
                            logger.debug(f"Cleaned up temporary file: {file_path}")
                            if file_path in temp_files:
                                temp_files.remove(file_path)
                    except Exception as e:
                        logger.warning(f"Error cleaning up temporary file {file_path}: {e}")
                
                # Start cleanup thread
                threading.Thread(target=cleanup_temp_file, args=(audiofile_path, process), daemon=True).start()
            
            logger.info(f"Started playing audio: {audiofile_path} (PID: {process.pid})")
            return jsonify({
                "status": "success",
                "message": f"Playing audio: {os.path.basename(audiofile_path)}",
                "pid": process.pid,
                "is_temporary": audiofile_path in temp_files
            })
        else:
            logger.error(f"Failed to start playback for: {audiofile_path}")
            # Clean up temp file if playback failed
            if audiofile_path in temp_files:
                try:
                    os.remove(audiofile_path)
                    temp_files.remove(audiofile_path)
                except:
                    pass
            return jsonify({
                "status": "error",
                "message": f"Failed to start playback for: {audiofile_path}"
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

