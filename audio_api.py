"""Audio playback API server using Flask."""
import logging
import os
import urllib.parse
import threading
from flask import Flask, request, jsonify
from sound_player import play_sound_async, stop_aplay

logger = logging.getLogger(__name__)

app = Flask(__name__)
current_playback_process = None
playback_lock = threading.Lock()


@app.route('/play/<path:audiofile>', methods=['POST', 'GET'])
def play_audio(audiofile):
    """
    Play an audio file using aplay.
    
    Args:
        audiofile: Path to the audio file (raw path, can include directories)
                   Can be passed as URL-encoded path or query parameter
        
    Returns:
        JSON response with status
    """
    global current_playback_process
    
    # Also check for file path in query parameter or POST body (for easier raw path handling)
    if request.is_json and 'file' in request.json:
        audiofile = request.json.get('file')
    elif request.is_json and 'path' in request.json:
        audiofile = request.json.get('path')
    elif 'file' in request.args:
        audiofile = request.args.get('file')
    elif 'path' in request.args:
        audiofile = request.args.get('path')
    
    # Decode URL-encoded path
    audiofile = urllib.parse.unquote(audiofile)
    
    # Resolve to absolute path if relative
    if not os.path.isabs(audiofile):
        # Try relative to current working directory
        audiofile = os.path.abspath(audiofile)
    
    logger.info(f"Received play request for: {audiofile}")
    
    # Check if file exists
    if not os.path.exists(audiofile):
        logger.warning(f"Audio file not found: {audiofile}")
        return jsonify({
            "status": "error",
            "message": f"Audio file not found: {audiofile}"
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
        process = play_sound_async(audiofile)
        if process:
            current_playback_process = process
            logger.info(f"Started playing audio: {audiofile} (PID: {process.pid})")
            return jsonify({
                "status": "success",
                "message": f"Playing audio: {audiofile}",
                "pid": process.pid
            })
        else:
            logger.error(f"Failed to start playback for: {audiofile}")
            return jsonify({
                "status": "error",
                "message": f"Failed to start playback for: {audiofile}"
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

