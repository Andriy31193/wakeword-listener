"""MCP client for retrieving audio context from ring buffer server."""
import logging
import requests
import base64
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)


class MCPClient:
    """Client for communicating with Audio Ring Buffer MCP Server."""
    
    def __init__(self, host: str = "127.0.0.1", port: int = 5001, endpoint_retrieve_context: str = "/context"):
        """
        Initialize MCP client.
        
        Args:
            host: MCP server host
            port: MCP server port
            endpoint_retrieve_context: Endpoint path for retrieving context
        """
        self.host = host
        self.port = port
        self.endpoint_retrieve_context = endpoint_retrieve_context
        self.base_url = f"http://{host}:{port}"
    
    def retrieve_recent_context(self, n: Optional[int] = None) -> Optional[List[Dict[str, Any]]]:
        """
        Retrieve recent audio context from MCP server.
        
        Args:
            n: Number of recent files to retrieve (None = all)
            
        Returns:
            List of audio file metadata with base64-encoded audio data, or None if error
        """
        try:
            url = f"{self.base_url}{self.endpoint_retrieve_context}"
            params = {"n": n} if n is not None else {}
            
            logger.info(f"Retrieving recent context from MCP server: {url}")
            response = requests.get(url, params=params, timeout=5.0)
            
            if response.status_code == 200:
                data = response.json()
                files = data.get("files", [])
                logger.info(f"Retrieved {len(files)} audio files from MCP server")
                return files
            else:
                logger.error(f"MCP server returned error: {response.status_code} - {response.text}")
                return None
                
        except requests.exceptions.RequestException as e:
            logger.error(f"Error connecting to MCP server: {e}")
            return None
        except Exception as e:
            logger.error(f"Error retrieving context: {e}")
            return None
    
    def is_server_available(self) -> bool:
        """Check if MCP server is available."""
        try:
            url = f"{self.base_url}/health"
            response = requests.get(url, timeout=2.0)
            return response.status_code == 200
        except:
            return False

