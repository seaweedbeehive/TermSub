"""TermSub - Video Translation and Terminology Management API.

This is the main FastAPI application entry point.
"""

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from contextlib import asynccontextmanager
import json
import asyncio
from pathlib import Path
from typing import Dict, List

from app.core.config import settings
from app.db.base import Base
from app.db.session import engine
from app.api import videos, terms, export, progress
from app.core.sqlite_queue import get_queue_worker


class ConnectionManager:
    """Manages WebSocket connections for real-time progress updates.
    
    Handles multiple concurrent connections per video, allowing multiple
    clients to watch the same video's progress simultaneously.
    
    Attributes:
        active_connections: Dict mapping video_id to list of WebSocket connections
    """
    
    def __init__(self):
        self.active_connections: Dict[str, List[WebSocket]] = {}
    
    async def connect(self, websocket: WebSocket, video_id: str):
        """Accept a new WebSocket connection for a video.
        
        Args:
            websocket: The WebSocket connection object
            video_id: The video ID this connection is watching
        """
        await websocket.accept()
        
        if video_id not in self.active_connections:
            self.active_connections[video_id] = []
        
        self.active_connections[video_id].append(websocket)
        print(f"[WebSocket] Client connected for video {video_id[:8]}... "
              f"(total: {len(self.active_connections[video_id])})")
    
    def disconnect(self, websocket: WebSocket, video_id: str):
        """Remove a WebSocket connection.
        
        Args:
            websocket: The WebSocket connection to remove
            video_id: The video ID this connection was watching
        """
        if video_id in self.active_connections:
            if websocket in self.active_connections[video_id]:
                self.active_connections[video_id].remove(websocket)
            
            # Clean up empty connection lists
            if not self.active_connections[video_id]:
                del self.active_connections[video_id]
        
        print(f"[WebSocket] Client disconnected from video {video_id[:8]}...")
    
    async def broadcast_to_video(self, video_id: str, message: dict):
        """Broadcast a message to all connections watching a video.
        
        Args:
            video_id: The video ID to broadcast to
            message: Dictionary to send as JSON
            
        Returns:
            Number of clients the message was sent to
        """
        if video_id not in self.active_connections:
            return 0
        
        disconnected = []
        sent_count = 0
        
        for connection in self.active_connections[video_id]:
            try:
                await connection.send_text(json.dumps(message))
                sent_count += 1
            except Exception as e:
                # Client disconnected unexpectedly
                disconnected.append(connection)
                print(f"[WebSocket] Failed to send to client: {e}")
        
        # Clean up disconnected clients
        for conn in disconnected:
            self.disconnect(conn, video_id)
        
        return sent_count
    
    async def send_to_client(self, websocket: WebSocket, message: dict):
        """Send a message to a specific client.
        
        Args:
            websocket: The WebSocket connection
            message: Dictionary to send as JSON
        """
        try:
            await websocket.send_text(json.dumps(message))
        except Exception as e:
            print(f"[WebSocket] Failed to send to client: {e}")


# Global connection manager instance
manager = ConnectionManager()


def check_database_schema():
    """Verify database schema matches expected model.
    
    Checks for required columns in the job_queue table and raises
    an error if the schema is outdated.
    
    Raises:
        RuntimeError: If required columns are missing from job_queue table
    """
    from sqlalchemy import inspect
    
    inspector = inspect(engine)
    
    # Check if job_queue table exists
    if 'job_queue' not in inspector.get_table_names():
        print("[INIT] job_queue table does not exist yet, will be created")
        return
    
    # Check for required columns in job_queue
    columns = [col['name'] for col in inspector.get_columns('job_queue')]
    
    required_columns = ['last_heartbeat', 'timeout_at', 'locked_by']
    missing = [col for col in required_columns if col not in columns]
    
    if missing:
        error_msg = (
            f"\n{'='*70}\n"
            f"DATABASE SCHEMA OUTDATED\n"
            f"{'='*70}\n"
            f"Missing columns in job_queue table: {', '.join(missing)}\n\n"
            f"Please run the migration to update your database:\n\n"
            f"  Option 1 (Recommended): python migrations/apply_migration.py\n"
            f"  Option 2: sqlite3 termsub.db < migrations/add_job_queue_timeout_fields.sql\n"
            f"  Option 3: Delete termsub.db and restart (data will be lost)\n"
            f"{'='*70}\n"
        )
        raise RuntimeError(error_msg)
    
    print("[INIT] Database schema verified (all required columns present)")


def create_tables():
    """Create all database tables."""
    Base.metadata.create_all(bind=engine)
    print("[INIT] Database tables created/verified")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    # Startup
    print("=" * 60)
    print("[INIT] Starting TermSub API...")
    
    # Check schema before creating tables (for existing databases)
    check_database_schema()
    
    create_tables()
    
    # Start background queue worker
    worker = get_queue_worker()
    worker.start()
    print("[INIT] Background queue worker started")
    
    print(f"[INIT] API ready at http://0.0.0.0:8000")
    print("=" * 60)
    yield
    # Shutdown
    print("[INIT] Shutting down...")
    worker = get_queue_worker()
    worker.stop()
    print("[INIT] Background queue worker stopped")


app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    lifespan=lifespan,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(videos.router)
app.include_router(terms.router)
app.include_router(export.router)
app.include_router(progress.router)

# Set up WebSocket manager for progress updates
from app.api import videos as videos_module
from app.api import progress as progress_module
videos_module.set_websocket_manager(manager)
progress_module.set_websocket_manager(manager)




# Resolve absolute path to frontend directory relative to this file
_FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
_STATIC_DIR = _FRONTEND_DIR

app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")


@app.get("/")
async def root():
    """Root endpoint - serve the frontend HTML interface."""
    return FileResponse(str(_FRONTEND_DIR / "index.html"))


@app.get("/favicon.ico")
async def favicon():
    """Return a 1x1 transparent pixel to stop 404 errors."""
    # 1x1 transparent GIF
    return Response(
        content=b'GIF89a\x01\x00\x01\x00\x00\x00\x00!\xf9\x04\x00\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;',
        media_type="image/gif"
    )


@app.get("/health")
def health_check():
    """Health check endpoint."""
    return {"status": "healthy"}


@app.websocket("/ws/videos/{video_id}")
async def websocket_endpoint(websocket: WebSocket, video_id: str):
    """WebSocket endpoint for real-time video progress updates.
    
    Connect to this endpoint to receive real-time updates during:
    - Transcription
    - Context analysis (Director Agent)
    - Glossary extraction (Glossary Agent)
    - Translation (Translator Agent)
    
    Messages sent:
    - {"status": "connected", "video_id": "..."}
    - {"status": "analyzing", "message": "Analyzing context..."}
    - {"status": "terms_ready", "terms_count": 15, "message": "Found 15 terms"}
    - {"status": "translating", "progress": 45, "current_batch": 9, "total_batches": 20}
    - {"status": "completed", "message": "Translation finished"}
    - {"status": "error", "message": "Error description"}
    
    Args:
        websocket: The WebSocket connection
        video_id: The video ID to watch
    """
    await manager.connect(websocket, video_id)
    
    try:
        # Send initial connection confirmation
        await manager.send_to_client(websocket, {
            "type": "connected",
            "video_id": video_id,
            "message": "Connected to progress updates"
        })
        
        # Keep connection alive and handle client messages
        while True:
            try:
                # Wait for client messages (optional - clients can send ping/keepalive)
                data = await websocket.receive_text()
                message = json.loads(data)
                
                # Handle client messages (e.g., ping)
                if message.get("type") == "ping":
                    await manager.send_to_client(websocket, {"type": "pong"})
                    
            except asyncio.TimeoutError:
                # Send keepalive ping
                try:
                    await websocket.send_text(json.dumps({"type": "keepalive"}))
                except Exception:
                    break
            except json.JSONDecodeError:
                # Ignore invalid JSON
                pass
                
    except WebSocketDisconnect:
        print(f"[WebSocket] Client disconnected from video {video_id[:8]}...")
    except Exception as e:
        print(f"[WebSocket] Error: {e}")
    finally:
        manager.disconnect(websocket, video_id)
