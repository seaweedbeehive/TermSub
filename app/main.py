"""TermSub - Video Translation and Terminology Management API.

This is the main FastAPI application entry point.
"""

import asyncio
import hashlib
import json
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from app.api import admin, auth, export, profile, progress, quota, terms, videos
from app.core.analytics import log_page_view
from app.core.auth import RequestIdentity, decode_access_token
from app.core.config import settings
from app.core.quota import QuotaManager
from app.db.base import Base
from app.db.session import SessionLocal, engine
from app.models.user import User


class ConnectionManager:
    """Manages WebSocket connections for real-time progress updates.

    Handles multiple concurrent connections per video, allowing multiple
    clients to watch the same video's progress simultaneously.

    Attributes:
        active_connections: Dict mapping video_id to list of WebSocket connections
    """

    def __init__(self) -> None:
        self.active_connections: dict[str, list[WebSocket]] = {}

    async def connect(
        self,
        websocket: WebSocket,
        video_id: str,
        subprotocol: str | None = None,
    ) -> None:
        """Accept a new WebSocket connection for a video.

        Args:
            websocket: The WebSocket connection object
            video_id: The video ID this connection is watching
            subprotocol: The negotiated subprotocol to return to the client.
        """
        await websocket.accept(subprotocol=subprotocol)

        if video_id not in self.active_connections:
            self.active_connections[video_id] = []

        self.active_connections[video_id].append(websocket)
        print(
            f"[WebSocket] Client connected for video {video_id[:8]}... "
            f"(total: {len(self.active_connections[video_id])})"
        )

    def disconnect(self, websocket: WebSocket, video_id: str) -> None:
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

    async def broadcast_to_video(self, video_id: str, message: dict[str, Any]) -> int:
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

    async def send_to_client(
        self, websocket: WebSocket, message: dict[str, Any]
    ) -> None:
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


class AnalyticsMiddleware(BaseHTTPMiddleware):
    """Log incoming requests to the PageView analytics table.

    Skips static assets and dispatches the DB write to a background thread
    so the response is not blocked.
    """

    SKIP_PREFIXES = ("/static", "/assets", "/favicon")

    @staticmethod
    def _extract_user_id(authorization: str | None) -> str | None:
        if not authorization or not authorization.lower().startswith("bearer "):
            return None
        token = authorization[7:].strip()
        try:
            payload = decode_access_token(token)
            return payload.get("sub")
        except Exception:
            return None

    @staticmethod
    def _hash_ip(ip: str | None) -> str | None:
        if not ip:
            return None
        return hashlib.sha256(ip.encode("utf-8")).hexdigest()[:16]

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        path = request.url.path
        if path.startswith(self.SKIP_PREFIXES):
            return await call_next(request)

        authorization = request.headers.get("authorization")
        user_id = self._extract_user_id(authorization)
        ip_hash = self._hash_ip(request.client.host if request.client else None)
        user_agent = request.headers.get("user-agent")
        session_id = request.headers.get("x-session-id")

        response = await call_next(request)

        # Fire-and-forget the DB write so analytics never blocks the response.
        threading.Thread(
            target=log_page_view,
            args=(user_id, path, session_id, ip_hash, user_agent),
            daemon=True,
        ).start()

        return response


def check_database_schema() -> None:
    """Verify database schema matches expected model.

    Checks for required columns in the job_queue table and raises
    an error if the schema is outdated.

    Raises:
        RuntimeError: If required columns are missing from job_queue table
    """
    from sqlalchemy import inspect

    inspector = inspect(engine)

    # Check if job_queue table exists
    if "job_queue" not in inspector.get_table_names():
        print("[INIT] job_queue table does not exist yet, will be created")
        return

    # Check for required columns in job_queue
    columns = [col["name"] for col in inspector.get_columns("job_queue")]

    required_columns = ["last_heartbeat", "timeout_at", "locked_by"]
    missing = [col for col in required_columns if col not in columns]

    if missing:
        error_msg = (
            f"\n{'=' * 70}\n"
            f"DATABASE SCHEMA OUTDATED\n"
            f"{'=' * 70}\n"
            f"Missing columns in job_queue table: {', '.join(missing)}\n\n"
            f"Please run the migration to update your database:\n\n"
            f"  Option 1 (Recommended): python migrations/apply_migration.py\n"
            f"  Option 2: Drop and recreate the database (data will be lost)\n"
            f"{'=' * 70}\n"
        )
        raise RuntimeError(error_msg)

    # Check for Celery migration column
    if "celery_task_id" not in columns:
        print("[INIT] WARNING: job_queue is missing 'celery_task_id' column.")
        print("[INIT] Run: python migrations/add_celery_task_id_column.py")
        raise RuntimeError(
            "Database schema outdated: missing 'celery_task_id' in job_queue.\n"
            "Run: python migrations/add_celery_task_id_column.py"
        )

    print("[INIT] Database schema verified (all required columns present)")


def create_tables() -> None:
    """Create all database tables."""
    Base.metadata.create_all(bind=engine)
    print("[INIT] Database tables created/verified")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan handler."""
    # Startup
    print("=" * 60)
    print("[INIT] Starting TermSub API...")

    # Check schema before creating tables (for existing databases)
    check_database_schema()

    create_tables()

    # Start Redis Pub/Sub listener for WebSocket broadcasts from Celery workers
    from app.core.redis_pubsub import start_redis_listener

    listener_task = asyncio.create_task(start_redis_listener(manager))
    print("[INIT] Redis Pub/Sub listener started")

    print("[INIT] API ready at http://0.0.0.0:8000")
    print("=" * 60)
    yield
    # Shutdown
    print("[INIT] Shutting down...")
    listener_task.cancel()
    with suppress(asyncio.CancelledError):
        await listener_task
    print("[INIT] Redis Pub/Sub listener stopped")


app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    lifespan=lifespan,
)

# CORS middleware
# Restrict to the configured frontend origin and do not allow credentials.
# TermSub currently uses JWT/API-key auth in headers, not cookies, so
# allow_credentials stays False to prevent cross-origin credential attacks.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.FRONTEND_BASE_URL],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Analytics middleware — logs page views in the background
app.add_middleware(AnalyticsMiddleware)

# Include routers
app.include_router(auth.router, prefix="/api")
app.include_router(quota.router, prefix="/api")
app.include_router(admin.router, prefix="/api")
app.include_router(profile.router, prefix="/api")
app.include_router(videos.router)
app.include_router(terms.router)
app.include_router(export.router)
app.include_router(progress.router)

# Set up WebSocket manager for progress updates
videos.set_websocket_manager(manager)
progress.set_websocket_manager(manager)


# Resolve absolute path to frontend directory relative to this file
_FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
_STATIC_DIR = _FRONTEND_DIR

app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")


@app.get("/")
async def root() -> FileResponse:
    """Root endpoint - serve the landing page."""
    return FileResponse(str(_FRONTEND_DIR / "landing.html"))


@app.get("/app")
@app.get("/app/{path:path}")
async def app_page(path: str | None = None) -> FileResponse:
    """App frontend route - serve index.html for /app deep links."""
    return FileResponse(str(_FRONTEND_DIR / "index.html"))


@app.get("/admin")
@app.get("/admin/{path:path}")
async def admin_page(path: str | None = None) -> FileResponse:
    """Admin dashboard frontend route - serve admin.html for /admin deep links."""
    return FileResponse(str(_FRONTEND_DIR / "admin.html"))


@app.get("/favicon.ico")
async def favicon() -> Response:
    """Return a 1x1 transparent pixel to stop 404 errors."""
    # 1x1 transparent GIF
    return Response(
        content=b"GIF89a\x01\x00\x01\x00\x00\x00\x00!\xf9\x04\x00\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;",
        media_type="image/gif",
    )


@app.get("/health")
def health_check() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "healthy"}


@app.get("/api/version")
def get_version() -> dict[str, str]:
    """Return the current application version."""
    return {"version": settings.VERSION}


def _extract_ws_identity(
    websocket: WebSocket,
) -> tuple[str | None, RequestIdentity | None]:
    """Resolve a WebSocket identity from the Sec-WebSocket-Protocol header.

    Standard users send ``["termsub-auth", <jwt>]``.
    BYOK users send ``["termsub-byok", <openai-api-key>]``.
    This avoids putting credentials in the URL query string where they can leak
    into proxy logs.

    Returns:
        Tuple of (negotiated_subprotocol, RequestIdentity | None).
    """
    subprotocols = websocket.scope.get("subprotocols", [])
    if len(subprotocols) >= 2:
        protocol = subprotocols[0]
        credential = subprotocols[1]

        if protocol == "termsub-auth":
            try:
                payload = decode_access_token(credential)
                user_id = payload.get("sub")
                if not user_id:
                    return None, None

                db = SessionLocal()
                try:
                    user = db.query(User).filter(User.id == user_id).first()
                    if not user or not user.is_active or not user.is_email_verified:
                        return None, None
                    return protocol, RequestIdentity(
                        user_id=user_id, is_byok=False, user=user
                    )
                finally:
                    db.close()
            except Exception:
                return None, None

        if protocol == "termsub-byok":
            api_key = credential.strip()
            if api_key:
                return protocol, RequestIdentity(
                    user_id=QuotaManager.byok_user_id(api_key),
                    is_byok=True,
                    api_key=api_key,
                )

    return None, None


@app.websocket("/ws/videos/{video_id}")
async def websocket_endpoint(
    websocket: WebSocket,
    video_id: str,
) -> None:
    """WebSocket endpoint for real-time video progress updates.

    Supports both standard JWT users (``["termsub-auth", token]``) and BYOK
    users (``["termsub-byok", api_key]``) via the WebSocket subprotocol.

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
    subprotocol, identity = _extract_ws_identity(websocket)
    if not identity:
        await websocket.close(code=1008, reason="Missing or invalid credentials")
        return

    await manager.connect(websocket, video_id, subprotocol=subprotocol)

    try:
        # Send initial connection confirmation
        await manager.send_to_client(
            websocket,
            {
                "type": "connected",
                "video_id": video_id,
                "message": "Connected to progress updates",
            },
        )

        # Keep connection alive and handle client messages
        while True:
            try:
                # Wait for client messages (optional - clients can send ping/keepalive)
                data = await websocket.receive_text()
                message = json.loads(data)

                # Handle client messages (e.g., ping)
                if message.get("type") == "ping":
                    await manager.send_to_client(websocket, {"type": "pong"})

            except TimeoutError:
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
