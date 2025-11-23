"""
WebSocket Manager for real-time job progress updates.

This module provides WebSocket connection management and progress broadcasting
for extraction jobs, allowing clients to receive real-time updates.
"""

import asyncio
import logging
from datetime import datetime
from typing import Dict, List

from fastapi import WebSocket

from backend.postparse.api.services.job_manager import Job

logger = logging.getLogger(__name__)


class WebSocketManager:
    """
    Manager for WebSocket connections and progress broadcasting.
    
    This class handles multiple WebSocket connections per job, broadcasting
    progress updates to all connected clients for a given job_id.
    
    Example:
        >>> manager = WebSocketManager()
        >>> await manager.connect(job_id, websocket)
        >>> await manager.broadcast_progress(job_id, {"progress": 50})
        >>> await manager.disconnect(job_id, websocket)
    """
    
    def __init__(self):
        """Initialize WebSocketManager with empty connection store."""
        self._active_connections: Dict[str, List[WebSocket]] = {}
        self._lock = asyncio.Lock()
        logger.info("WebSocketManager initialized")
    
    async def connect(self, job_id: str, websocket: WebSocket) -> None:
        """
        Accept and register a new WebSocket connection for a job.
        
        Args:
            job_id: UUID string of the job to monitor
            websocket: FastAPI WebSocket instance
        
        Example:
            >>> await manager.connect(
            ...     "550e8400-e29b-41d4-a716-446655440000",
            ...     websocket
            ... )
        """
        await websocket.accept()
        
        async with self._lock:
            if job_id not in self._active_connections:
                self._active_connections[job_id] = []
            self._active_connections[job_id].append(websocket)
        
        connection_count = len(self._active_connections[job_id])
        logger.info(
            f"WebSocket connected for job {job_id} "
            f"(total connections: {connection_count})"
        )
    
    async def disconnect(self, job_id: str, websocket: WebSocket) -> None:
        """
        Remove and close a WebSocket connection.
        
        Args:
            job_id: UUID string of the job
            websocket: FastAPI WebSocket instance to disconnect
        
        Example:
            >>> await manager.disconnect(job_id, websocket)
        """
        async with self._lock:
            if job_id in self._active_connections:
                if websocket in self._active_connections[job_id]:
                    self._active_connections[job_id].remove(websocket)
                
                # Clean up empty job connection lists
                if not self._active_connections[job_id]:
                    del self._active_connections[job_id]
        
        try:
            await websocket.close()
        except Exception as e:
            logger.warning(f"Error closing WebSocket: {e}")
        
        logger.info(f"WebSocket disconnected for job {job_id}")
    
    async def broadcast_progress(self, job_id: str, progress_data: dict) -> None:
        """
        Broadcast progress update to all clients connected to a job.
        
        Args:
            job_id: UUID string of the job
            progress_data: Dictionary with progress information
        
        Progress data format:
            {
                "job_id": "uuid",
                "status": "running",
                "progress": 65,
                "messages_processed": 65,
                "errors": [],
                "timestamp": "2025-11-19T10:30:00Z"
            }
        
        Example:
            >>> await manager.broadcast_progress(job_id, {
            ...     "job_id": job_id,
            ...     "status": "running",
            ...     "progress": 75,
            ...     "messages_processed": 150,
            ...     "errors": [],
            ...     "timestamp": datetime.now().isoformat()
            ... })
        """
        async with self._lock:
            if job_id not in self._active_connections:
                return
            
            # Add timestamp if not present
            if "timestamp" not in progress_data:
                progress_data["timestamp"] = datetime.now().isoformat()
            
            # Get list of connections to broadcast to
            connections = self._active_connections[job_id].copy()
        
        # Broadcast outside of lock to avoid blocking
        disconnected = []
        for websocket in connections:
            try:
                await websocket.send_json(progress_data)
            except Exception as e:
                logger.warning(
                    f"Failed to send to WebSocket for job {job_id}: {e}"
                )
                disconnected.append(websocket)
        
        # Remove disconnected clients
        if disconnected:
            async with self._lock:
                if job_id in self._active_connections:
                    for ws in disconnected:
                        if ws in self._active_connections[job_id]:
                            self._active_connections[job_id].remove(ws)
                    
                    # Clean up empty lists
                    if not self._active_connections[job_id]:
                        del self._active_connections[job_id]
    
    async def send_job_update(self, job_id: str, job: Job) -> None:
        """
        Convert Job object to dict and broadcast to all clients.
        
        Args:
            job_id: UUID string of the job
            job: Job object with current status
        
        Example:
            >>> job = manager.get_job(job_id)
            >>> await ws_manager.send_job_update(job_id, job)
        """
        progress_data = {
            "job_id": job.job_id,
            "status": job.status.value,
            "progress": job.progress,
            "messages_processed": job.messages_processed,
            "errors": job.errors,
            "timestamp": datetime.now().isoformat(),
        }
        
        await self.broadcast_progress(job_id, progress_data)
    
    def get_connection_count(self, job_id: str) -> int:
        """
        Get the number of active connections for a job.
        
        Args:
            job_id: UUID string of the job
        
        Returns:
            Number of active WebSocket connections
        
        Example:
            >>> count = manager.get_connection_count(job_id)
            >>> print(f"Active connections: {count}")
        """
        return len(self._active_connections.get(job_id, []))
