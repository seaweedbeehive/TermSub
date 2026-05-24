"""TermSub - Video Translation and Terminology Management API.

This is the main FastAPI application entry point.
"""

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from contextlib import asynccontextmanager
import json
import asyncio
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


HTML_INTERFACE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>TermSub - Video Translation</title>
    <script>
        // Suppress Tailwind CDN warning in development
        const originalWarn = console.warn;
        console.warn = function(...args) {
            if (args[0] && typeof args[0] === 'string' && args[0].includes('cdn.tailwindcss')) return;
            originalWarn.apply(console, args);
        };
    </script>
    <script src="https://cdn.tailwindcss.com"></script>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <style>
        body { font-family: 'Inter', system-ui, sans-serif; }
        .progress-bar { transition: width 0.3s ease; }
        .rtl-text {
            direction: rtl;
            text-align: right;
            unicode-bidi: isolate;
        }
        @keyframes pulse-dot {
            0%, 100% { opacity: 1; transform: scale(1); }
            50% { opacity: 0.5; transform: scale(1.2); }
        }
        .pulse-indicator {
            animation: pulse-dot 1.5s ease-in-out infinite;
        }

        /* Activity Log — modern dark-editor scrollbar */
        #activityLog::-webkit-scrollbar {
            width: 6px;
        }
        #activityLog::-webkit-scrollbar-track {
            background: transparent;
        }
        #activityLog::-webkit-scrollbar-thumb {
            background-color: #475569;
            border-radius: 3px;
        }
        #activityLog::-webkit-scrollbar-thumb:hover {
            background-color: #64748b;
        }
        #activityLog {
            scrollbar-width: thin;
            scrollbar-color: #475569 transparent;
        }
    </style>
</head>
<body class="bg-slate-50 min-h-screen">
    <div class="max-w-6xl mx-auto p-6">
        <!-- App Header -->
        <div class="bg-white rounded-xl shadow-sm p-6 mb-6">
            <div class="flex items-center gap-3">
                <div class="w-10 h-10 bg-blue-600 rounded-lg flex items-center justify-center">
                    <i class="fa-solid fa-closed-captioning text-white"></i>
                </div>
                <div>
                    <h1 class="text-xl font-bold text-slate-900">TermSub</h1>
                    <p class="text-sm text-slate-500">Video Translation & Terminology Management</p>
                </div>
            </div>
        </div>

        <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
            <!-- Left Panel - Upload & Controls -->
            <div class="lg:col-span-1 flex flex-col gap-4 max-h-[calc(100vh-3rem)]">
                <!-- Upload Card -->
                <div id="uploadCard" class="bg-white rounded-xl shadow-sm p-6 shrink-0">
                    <div id="uploadForm" class="space-y-4">
                        <div>
                            <input type="file" id="fileInput" accept="video/*,audio/*,.txt" class="hidden">
                            <label for="fileInput" id="dropZone"
                                class="flex flex-col items-center justify-center w-full h-32 border-2 border-dashed border-slate-300 rounded-lg bg-slate-50 hover:bg-slate-100 cursor-pointer transition-colors">
                                <i class="fa-solid fa-cloud-arrow-up text-2xl text-slate-400 mb-2"></i>
                                <p class="text-sm text-slate-600 font-medium" id="fileLabel">Click to select file</p>
                                <p class="text-xs text-slate-400 mt-1">MP4, MOV, AVI, MP3, TXT</p>
                            </label>
                        </div>

                        <div id="setupConfigPanel" class="space-y-4">
                        <div>
                            <label class="block text-xs font-medium text-slate-700 mb-1">Source Language</label>
                            <select id="sourceLanguage" class="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500">
                                <option value="auto">Auto-detect</option>
                                <option value="en">English</option>
                                <option value="fa">Persian (Farsi)</option>
                                <option value="ar">Arabic</option>
                                <option value="de">German</option>
                                <option value="fr">French</option>
                                <option value="es">Spanish</option>
                                <option value="it">Italian</option>
                                <option value="ja">Japanese</option>
                                <option value="zh">Chinese</option>
                            </select>

                        </div>

                        <div>
                            <label class="block text-xs font-medium text-slate-700 mb-1">Target Language</label>
                            <select id="targetLanguage" class="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500">
                                <option value="" disabled selected>Select target language...</option>
                                <option value="en">English</option>
                                <option value="es">Spanish</option>
                                <option value="fr">French</option>
                                <option value="de">German</option>
                                <option value="ar">Arabic</option>
                                <option value="it">Italian</option>
                                <option value="ja">Japanese</option>
                                <option value="zh">Chinese</option>
                                <option value="fa">Persian (Farsi)</option>
                            </select>
                            <div id="languageWarning" class="hidden text-xs font-semibold text-red-500 bg-red-50 border border-red-200 rounded p-2 mt-2">⚠️ Please select a Target Language before proceeding!</div>
                        </div>

                        <!-- Engine Selection -->
                        <div>
                            <label class="block text-xs font-medium text-slate-700 mb-2">Transcription Engine</label>
                            <div class="grid grid-cols-1 gap-3" id="engineSelector">
                                <!-- Local Engine Card -->
                                <div class="engine-card cursor-pointer border-2 border-slate-200 rounded-lg p-3 hover:border-slate-300 transition-colors" data-engine="local">
                                    <div class="flex items-start gap-3">
                                        <div class="mt-0.5">
                                            <div class="w-4 h-4 rounded-full border-2 border-slate-300 flex items-center justify-center engine-radio">
                                                <div class="w-2 h-2 rounded-full bg-blue-600 hidden"></div>
                                            </div>
                                        </div>
                                        <div class="flex-1">
                                            <div class="flex items-center justify-between">
                                                <h3 class="text-sm font-semibold text-slate-900">Local Engine</h3>
                                                <span class="text-[10px] bg-slate-100 text-slate-600 px-2 py-0.5 rounded-full font-medium">Fast-Whisper</span>
                                            </div>
                                            <p class="text-xs text-slate-500 mt-1">100% Free & Offline. High local system hardware strain.</p>
                                        </div>
                                    </div>
                                </div>
                                <!-- Cloud Engine Card -->
                                <div class="engine-card cursor-pointer border-2 border-blue-500 rounded-lg p-3 bg-blue-50 transition-colors" data-engine="gemini">
                                    <div class="flex items-start gap-3">
                                        <div class="mt-0.5">
                                            <div class="w-4 h-4 rounded-full border-2 border-blue-500 flex items-center justify-center engine-radio">
                                                <div class="w-2 h-2 rounded-full bg-blue-600"></div>
                                            </div>
                                        </div>
                                        <div class="flex-1">
                                            <div class="flex items-center justify-between">
                                                <h3 class="text-sm font-semibold text-slate-900">Cloud Engine</h3>
                                                <span class="text-[10px] bg-blue-100 text-blue-700 px-2 py-0.5 rounded-full font-medium">Gemini AI + WhisperX Sync</span>
                                            </div>
                                            <p class="text-xs text-slate-500 mt-1">Maximum linguistic accuracy & slang processing. Low hardware strain. Requires API key.</p>
                                        </div>
                                    </div>
                                </div>
                            </div>
                            <!-- Hidden input retains the selected value for downstream JS -->
                            <input type="hidden" id="transcriptionEngine" value="gemini">
                        </div>

                        <!-- Engine Comparison -->
                        <div class="bg-slate-50 rounded-lg p-3 border border-slate-200">
                            <p class="text-[10px] font-semibold text-slate-700 uppercase tracking-wider mb-2">Quick Comparison</p>
                            <div class="grid grid-cols-2 gap-2 text-xs">
                                <div>
                                    <p class="font-medium text-slate-900">Local (Fast-Whisper)</p>
                                    <ul class="text-slate-500 text-[10px] mt-1 space-y-0.5 list-disc list-inside">
                                        <li>Free forever</li>
                                        <li>Privacy guaranteed</li>
                                        <li>Heavy CPU/GPU load</li>
                                        <li>Basic slang support</li>
                                    </ul>
                                </div>
                                <div>
                                    <p class="font-medium text-slate-900">Cloud (Gemini + WhisperX)</p>
                                    <ul class="text-slate-500 text-[10px] mt-1 space-y-0.5 list-disc list-inside">
                                        <li>Requires API key</li>
                                        <li>Minimal local load</li>
                                        <li>Best for slang/idioms</li>
                                        <li>Word-level timestamp sync</li>
                                    </ul>
                                </div>
                            </div>
                        </div>

                        <!-- Gemini API Key Vault -->
                        <div>
                            <label class="block text-xs font-medium text-slate-700 mb-1" for="geminiApiKey">Gemini API Key</label>
                            <input type="password" id="geminiApiKey" class="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500" placeholder="Paste your Gemini API key here">
                            <p class="text-[10px] text-slate-500 mt-1">
                                <a href="https://aistudio.google.com/" target="_blank" rel="noopener noreferrer" class="text-blue-600 hover:text-blue-700 underline">Get a free API key at Google AI Studio</a>
                            </p>
                        </div>

                        </div>

                        <button id="uploadBtn" class="w-full py-2.5 px-4 bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium rounded-lg transition-colors">
                            <i class="fa-solid fa-upload mr-2"></i>Start
                        </button>
                    </div>

                    <!-- Post-upload compact state -->
                    <div id="uploadCompleteCard" class="hidden space-y-3">
                        <div class="flex items-center gap-3 p-3 bg-slate-50 rounded-lg border border-slate-200">
                            <i class="fa-solid fa-file-check text-emerald-500"></i>
                            <span id="uploadedFilename" class="text-sm font-medium text-slate-700 truncate">filename.mp4</span>
                        </div>
                        <button id="startNewProjectBtn" class="w-full py-2 px-3 text-xs font-medium text-slate-600 bg-white border border-slate-300 rounded-lg hover:bg-slate-50 transition-colors">
                            <i class="fa-solid fa-rotate-right mr-1"></i>Start New Project
                        </button>
                    </div>
                </div>

                <!-- Project Metadata & Status Card (Unified) -->
                <div id="statusCard" class="bg-white rounded-xl shadow-sm overflow-hidden hidden shrink-0">
                    <!-- Project Header -->
                    <div class="bg-slate-50 px-6 py-4 border-b border-slate-200">
                        <h2 id="projectTitle" class="text-sm font-semibold text-slate-900 truncate">Untitled Project</h2>
                        <div class="flex items-center gap-2 mt-1 text-xs text-slate-500">
                            <span id="projectType"><i class="fa-solid fa-video mr-1"></i>Video</span>
                            <span>•</span>
                            <span id="projectLangs">EN → FA</span>
                            <span>•</span>
                            <span id="projectId" class="font-mono">-</span>
                        </div>
                    </div>
                    
                    <!-- Status Section -->
                    <div class="p-6">
                        <!-- Status Badge with Color -->
                        <div class="flex items-center justify-between mb-4">
                            <span class="text-xs font-medium text-slate-500 uppercase tracking-wider">Status</span>
                            <span id="statusBadge" class="inline-flex items-center gap-1.5 px-3 py-1.5 bg-slate-100 text-slate-700 text-xs font-semibold rounded-full">
                                <span id="statusDot" class="w-1.5 h-1.5 rounded-full bg-slate-400"></span>
                                Uploaded
                            </span>
                        </div>
                        
                        <!-- Current Step & Segment Counters (no progress bar) -->
                        <div class="mb-4">
                            <div class="flex items-end justify-between mb-2">
                                <span id="currentStep" class="text-sm text-slate-600">Ready to process</span>
                            </div>
                            <div class="flex justify-between text-xs text-slate-500">
                                <span id="segmentCount">0 segments</span>
                                <span id="processedCount">0 processed</span>
                            </div>
                        </div>
                        
                        <!-- Step Detail -->
                        <div id="stepDetail" class="text-xs text-slate-500 bg-slate-50 rounded-lg px-3 py-2 hidden"></div>
                        
                        <!-- Director's Context Brief -->
                        <div id="contextBriefContainer" class="hidden mt-3 pt-3 border-t border-slate-100">
                            <p class="text-[10px] font-semibold text-slate-400 uppercase tracking-wider mb-1">Director's Context Brief</p>
                            <p id="contextBriefText" class="text-xs text-slate-600 italic bg-slate-50 p-2 rounded border border-slate-100 leading-relaxed"></p>
                        </div>
                    </div>
                </div>

                <!-- Primary Action Container -->
                <div id="primaryActionContainer" class="bg-white rounded-xl shadow-sm p-4 hidden shrink-0">
                    <p id="primaryHelperText" class="text-xs text-amber-700 mb-2 hidden">💡 Review and edit your Extracted Terms before translating.</p>
                    
                    <button id="primaryActionBtn" class="w-full py-3 px-4 text-white text-sm font-semibold rounded-lg transition-colors shadow-sm">
                        Action
                    </button>
                    
                    <div id="primaryGhostLink" class="mt-2 text-center hidden">
                        <button id="downloadRawTranscriptionLink" class="text-xs text-slate-500 hover:text-slate-700 underline">or download raw transcription</button>
                    </div>
                    
                    <p id="exportHeader" class="hidden text-[10px] font-semibold text-slate-400 uppercase tracking-wider mb-2">Download Subtitles & Translations</p>
                    <div id="primaryExportGrid" class="hidden grid grid-cols-2 gap-2">
                        <button id="exportSrtBtn" class="py-2 px-3 bg-slate-700 hover:bg-slate-800 text-white text-xs font-medium rounded-lg transition-colors">
                            <i class="fa-solid fa-closed-captioning mr-1"></i>SRT
                        </button>
                        <button id="exportVttBtn" class="py-2 px-3 bg-slate-700 hover:bg-slate-800 text-white text-xs font-medium rounded-lg transition-colors">
                            <i class="fa-brands fa-html5 mr-1"></i>VTT
                        </button>
                        <button id="exportTxtBtn" class="py-2 px-3 bg-slate-600 hover:bg-slate-700 text-white text-xs font-medium rounded-lg transition-colors">
                            <i class="fa-solid fa-file-text mr-1"></i>TXT
                        </button>
                        <button id="exportJsonBtn" class="py-2 px-3 bg-slate-600 hover:bg-slate-700 text-white text-xs font-medium rounded-lg transition-colors">
                            <i class="fa-solid fa-code mr-1"></i>JSON
                        </button>
                    </div>
                </div>
            </div>

            <!-- Right Panel - Terms & Activity -->
            <div class="lg:col-span-2 space-y-6">
                <!-- Terms Table -->
                <div id="termsPanel" class="bg-white rounded-xl shadow-sm p-6">
                    <h2 class="text-sm font-semibold text-slate-900 mb-4">Extracted Terms</h2>
                    <div class="overflow-x-auto">
                        <table class="w-full text-sm">
                            <thead class="sticky top-0 bg-white z-10 shadow-sm text-slate-600">
                                <tr>
                                    <th class="px-3 py-2 text-left text-xs font-medium">Type</th>
                                    <th class="px-3 py-2 text-left text-xs font-medium">Original</th>
                                    <th class="px-3 py-2 text-left text-xs font-medium">Translation</th>
                                    <th class="px-3 py-2 text-center text-xs font-medium">Freq</th>
                                    <th class="px-3 py-2 text-left text-xs font-medium">Standard</th>
                                </tr>
                            </thead>
                            <tbody id="termsTable" class="divide-y divide-slate-100">
                                <tr>
                                    <td colspan="5" class="px-3 py-8 text-center text-slate-400 text-sm">
                                        No terms extracted yet. Upload and process a video.
                                    </td>
                                </tr>
                            </tbody>
                        </table>
                    </div>
                </div>

                <!-- Subtitle Review Timeline -->
                <div id="subtitleReviewPanel" class="hidden h-full flex flex-col bg-white rounded-xl shadow-sm p-6">
                    <h2 class="text-sm font-semibold text-slate-900 mb-4">Translated Subtitle Timeline</h2>
                    
                    <!-- Global Find & Replace Bar -->
                    <div class="flex items-center gap-2 mb-3">
                        <input type="text" id="findInput" placeholder="Find text..." class="flex-1 text-xs border border-slate-200 bg-slate-50 rounded px-2 py-1 focus:bg-white focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none transition-all">
                        <input type="text" id="replaceInput" placeholder="Replace with..." class="flex-1 text-xs border border-slate-200 bg-slate-50 rounded px-2 py-1 focus:bg-white focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none transition-all">
                        <button id="replaceAllBtn" class="px-3 py-1 bg-slate-700 hover:bg-slate-800 text-white text-xs font-medium rounded transition-colors">Replace All</button>
                    </div>
                    
                    <div id="timelineCardGrid" class="flex-1 overflow-y-auto space-y-2 pr-1 font-mono text-xs">
                        <div class="text-slate-400 text-center py-8">No subtitles available yet.</div>
                    </div>
                </div>

                <!-- Activity Log -->
                <div class="bg-slate-900 rounded-xl shadow-sm p-4">
                    <h2 class="text-sm font-semibold text-slate-200 mb-3">Activity Log</h2>
                    <div id="activityLog" class="h-48 overflow-y-auto font-mono text-xs space-y-1">
                        <div class="text-slate-500">Waiting for file upload...</div>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <!-- Toast Container -->
    <div id="toastContainer" class="fixed bottom-5 right-5 z-[9999] flex flex-col gap-2 pointer-events-none"></div>

    <script>
        // State
        let currentVideoId = null;
        let videoProgressPercent = 0;  // Track progress for WebSocket updates
        let currentFileType = 'video'; // 'video' or 'text' - tracks uploaded file type
        let loggedCompletions = new Set(); // Track completed jobs to prevent duplicate logs
        let currentJobId = null; // Track current job to ignore stale messages
        let isJobRunning = false; // Silver bullet: prevents stale completion logs
        let hasStartedProcessing = false; // Status Transition Guard: ignore COMPLETED until processing starts
        let isSavingSegment = false; // Prevents concurrent blur / replace-all race conditions

        // Status config with colors
        const statusConfig = {
            uploaded: { label: 'Uploaded', color: 'bg-slate-100 text-slate-700', dotColor: 'bg-slate-400' },
            queued: { label: 'Queued', color: 'bg-gray-100 text-gray-700', dotColor: 'bg-gray-400' },
            extracting_audio: { label: 'Extracting Audio', color: 'bg-amber-100 text-amber-800', dotColor: 'bg-amber-500' },
            transcribing: { label: 'Transcribing', color: 'bg-orange-100 text-orange-800', dotColor: 'bg-orange-500' },
            transcribed: { label: 'Transcribed', color: 'bg-blue-100 text-blue-800', dotColor: 'bg-blue-500' },
            analyzing: { label: 'Analyzing', color: 'bg-cyan-100 text-cyan-800', dotColor: 'bg-cyan-500' },
            context_ready: { label: 'Context Ready', color: 'bg-sky-100 text-sky-800', dotColor: 'bg-sky-500' },
            glossary_extracting: { label: 'Extracting Terms', color: 'bg-yellow-100 text-yellow-800', dotColor: 'bg-yellow-500' },
            terms_ready: { label: 'Terms Ready', color: 'bg-indigo-100 text-indigo-800', dotColor: 'bg-indigo-500' },
            translating: { label: 'Translating via Gemini', color: 'bg-purple-100 text-purple-800', dotColor: 'bg-purple-500' },
            completed: { label: 'Completed', color: 'bg-emerald-100 text-emerald-800', dotColor: 'bg-emerald-500' },
            error: { label: 'Error', color: 'bg-rose-100 text-rose-800', dotColor: 'bg-rose-500' }
        };

        // Utility functions
        function log(message, type = 'info') {
            const logEl = document.getElementById('activityLog');
            const time = new Date().toLocaleTimeString('en-US', { hour12: false });
            
            if (logEl.children.length === 1 && logEl.children[0].textContent.includes('Waiting')) {
                logEl.innerHTML = '';
            }
            
            // Prevent duplicate completion messages
            const lastEntry = logEl.lastElementChild;
            if (lastEntry && lastEntry.textContent.includes(message)) {
                return; // Skip duplicate message
            }
            
            // Badge map
            const badgeMap = {
                info:    { label: 'INFO',    bg: 'bg-slate-700',    text: 'text-slate-200' },
                success: { label: 'SUCCESS', bg: 'bg-emerald-600',  text: 'text-white' },
                error:   { label: 'ERROR',   bg: 'bg-red-600',      text: 'text-white' },
                warning: { label: 'WARN',    bg: 'bg-amber-500',    text: 'text-white' },
                align:   { label: 'ALIGN',   bg: 'bg-cyan-600',     text: 'text-white' },
                context: { label: 'CONTEXT', bg: 'bg-indigo-600',   text: 'text-white' }
            };
            const cfg = badgeMap[type] || badgeMap.info;
            
            const html = `<div class="flex items-start gap-2 text-slate-300">
                <span class="shrink-0 mt-0.5 px-1 py-0.5 rounded text-[9px] font-bold uppercase tracking-wide ${cfg.bg} ${cfg.text}">${cfg.label}</span>
                <span class="text-[11px] leading-tight">[${time}] ${message}</span>
            </div>`;
            
            logEl.insertAdjacentHTML('beforeend', html);
            logEl.scrollTo({ top: logEl.scrollHeight, behavior: 'smooth' });
        }
        
        function clearActivityLog() {
            const logEl = document.getElementById('activityLog');
            logEl.innerHTML = '';
            loggedCompletions.clear(); // Reset completion tracking
        }

        function escapeHtml(text) {
            if (!text) return '';
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }

        function showToast(message, type = 'info') {
            console.log("🔔 [Toast Triggered]:", message, type);
            const container = document.getElementById('toastContainer');
            if (!container) return;

            const colorMap = {
                info:    { bg: 'bg-blue-600',   icon: 'text-white' },
                success: { bg: 'bg-emerald-600', icon: 'text-white' },
                error:   { bg: 'bg-red-600',     icon: 'text-white' },
                warning: { bg: 'bg-amber-500',   icon: 'text-white' }
            };
            const cfg = colorMap[type] || colorMap.info;

            const el = document.createElement('div');
            el.className = `pointer-events-auto ${cfg.bg} text-white shadow-xl px-4 py-2 rounded-lg font-sans text-sm flex items-center gap-2 transition-all duration-300 transform translate-x-full`;
            el.innerHTML = `
                <svg class="w-4 h-4 shrink-0 ${cfg.icon}" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>
                <span class="font-medium">${message}</span>
            `;
            container.appendChild(el);

            // Slide in
            requestAnimationFrame(() => el.classList.remove('translate-x-full'));

            // Auto-dismiss after 2.5 seconds
            setTimeout(() => {
                el.classList.add('translate-x-full', 'opacity-0');
                setTimeout(() => el.remove(), 300);
            }, 2500);
        }

        function updateStatus(data) {
            const cfg = statusConfig[data.status] || statusConfig.uploaded;
            const isProcessing = ['transcribing', 'extracting_audio', 'analyzing', 'glossary_extracting', 'translating', 'queued'].includes(data.status);
            
            // Update Status Badge in Card
            const statusBadge = document.getElementById('statusBadge');
            statusBadge.className = `inline-flex items-center gap-1.5 px-3 py-1.5 ${cfg.color} text-xs font-semibold rounded-full transition-colors`;
            statusBadge.innerHTML = `<span id="statusDot" class="w-1.5 h-1.5 rounded-full ${cfg.dotColor} ${isProcessing ? 'pulse-indicator' : ''}"></span>${cfg.label}`;
            
            // Update step & segment counters
            const currentStepEl = document.getElementById('currentStep');
            if (currentStepEl) currentStepEl.textContent = data.current_step || 'Ready';
            const segmentCountEl = document.getElementById('segmentCount');
            if (segmentCountEl) segmentCountEl.textContent = `${data.total_segments ?? 0} segments`;
            const processedCountEl = document.getElementById('processedCount');
            if (processedCountEl) processedCountEl.textContent = `${data.processed_segments || 0} processed`;
            
            // Update Step Detail
            const stepDetail = document.getElementById('stepDetail');
            if (data.step_detail || (isProcessing && data.current_step)) {
                stepDetail.textContent = data.step_detail || data.current_step;
                stepDetail.classList.remove('hidden');
            } else {
                stepDetail.classList.add('hidden');
            }

            // Show/hide buttons based on status
            updateButtonVisibility(data.status);
        }

        async function renderTerms() {
            if (!currentVideoId) return;
            
            try {
                const response = await fetch(`/terms/video/${currentVideoId}`);
                const terms = await response.json();
                
                const tbody = document.getElementById('termsTable');
                
                if (!terms || terms.length === 0) {
                    tbody.innerHTML = '<tr><td colspan="5" class="px-3 py-8 text-center text-slate-400 text-sm">No terms extracted yet.</td></tr>';
                    return;
                }

                tbody.innerHTML = terms.map(term => {
                    // Clean translation: remove bracketed type prefix (e.g., "[Key Concept] ")
                    const cleanTranslation = (term.translated_term || '').replace(/^\\[.*?\\]\\s*/, '');
                    return `
                    <tr class="hover:bg-slate-50 ${term.source === 'manual' ? 'bg-amber-50/50' : ''}">
                        <td class="px-3 py-2">
                            <div class="flex flex-wrap gap-1">
                                <span class="inline-flex px-2 py-0.5 rounded text-[10px] font-medium ${term.source === 'manual' ? 'bg-amber-100 text-amber-700' : 'bg-blue-100 text-blue-700'}">${escapeHtml(term.category || 'Term')}</span>
                                ${term.source === 'manual' ? '<span class="inline-flex px-2 py-0.5 rounded text-[10px] font-medium bg-amber-200 text-amber-800">Manual</span>' : ''}
                            </div>
                        </td>
                        <td class="px-3 py-2 font-medium text-slate-900">${escapeHtml(term.original_term)}</td>
                        <td class="px-3 py-2 text-slate-600 rtl-text">${escapeHtml(cleanTranslation)}</td>
                        <td class="px-3 py-2 text-center">
                            <span class="inline-flex items-center justify-center min-w-[1.5rem] px-1.5 py-0.5 bg-slate-100 rounded-full text-xs font-medium text-slate-700">${term.frequency || 1}</span>
                        </td>
                        <td class="px-3 py-2">
                            <div class="flex items-center gap-2">
                                <input type="text" value="${escapeHtml(term.standardized_term || '')}" 
                                    onchange="updateTerm('${term.id}', this.value)"
                                    class="flex-1 border-transparent bg-slate-50/50 hover:bg-slate-100/70 focus:bg-white focus:border-slate-300 focus:ring-1 focus:ring-slate-300 transition-all rounded px-2 py-1 text-xs">
                            </div>
                        </td>
                    </tr>
                `}).join('');
            } catch (err) {
                console.error('Failed to load terms:', err);
            }
        }

        function formatTimecode(seconds) {
            const m = Math.floor(seconds / 60).toString().padStart(2, '0');
            const s = Math.floor(seconds % 60).toString().padStart(2, '0');
            const ms = Math.floor((seconds % 1) * 1000).toString().padStart(3, '0');
            return `${m}:${s}.${ms}`;
        }
        
        function renderSubtitleTimeline(segments) {
            const grid = document.getElementById('timelineCardGrid');
            if (!grid) return;
            
            if (!segments || segments.length === 0) {
                grid.innerHTML = '<div class="text-slate-400 text-center py-8">No subtitles available yet.</div>';
                return;
            }
            
            grid.innerHTML = segments.map((seg, idx) => `
                <div class="bg-slate-50 rounded-lg p-3 border border-slate-100 hover:border-slate-200 transition-colors">
                    <div class="flex items-center gap-2 mb-1.5 text-slate-400">
                        <span class="text-[10px] font-bold bg-slate-200 text-slate-600 px-1.5 py-0.5 rounded">#${seg.sequence_number || idx + 1}</span>
                        <span class="text-[11px] font-mono">⏱ [${formatTimecode(seg.start_time)} → ${formatTimecode(seg.end_time)}]</span>
                    </div>
                    <div contenteditable="true" data-segment-id="${seg.id || ''}"
                        class="text-slate-800 leading-relaxed outline-none focus:bg-white focus:ring-2 focus:ring-blue-100 focus:border-blue-400 rounded p-1 transition-all ${seg.translated_text ? '' : 'text-slate-400 italic'}"
                    >${escapeHtml(seg.translated_text || seg.original_text || '(empty)')}</div>
                </div>
            `).join('');
            
            // Attach auto-save blur listeners to editable fields
            grid.querySelectorAll('[data-segment-id]').forEach(el => {
                el.addEventListener('blur', async (e) => {
                    if (isSavingSegment) return;
                    const segmentId = e.target.getAttribute('data-segment-id');
                    const newText = e.target.innerText.trim();
                    if (!segmentId || !currentVideoId) return;
                    
                    // Guard against accidental empty strings
                    if (newText === '') {
                        log('Segment text cannot be empty — change discarded.', 'warning');
                        e.target.textContent = e.target.dataset.originalText || '(empty)';
                        return;
                    }
                    
                    isSavingSegment = true;
                    try {
                        const response = await fetch(`/videos/${currentVideoId}/segments/${segmentId}`, {
                            method: 'PATCH',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ translated_text: newText })
                        });
                        if (!response.ok) throw new Error('Server returned ' + response.status);
                        log('Segment updated and saved.', 'info');
                        showToast('Segment saved successfully', 'success');
                    } catch (err) {
                        console.error('Auto-save failed:', err);
                        log('Auto-save failed: ' + err.message, 'error');
                    } finally {
                        isSavingSegment = false;
                    }
                });
                // Store original text for rollback on empty blur
                el.dataset.originalText = el.textContent;
            });
        }
        
        async function updateTerm(termId, value) {
            try {
                await fetch(`/terms/${termId}`, {
                    method: 'PATCH',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ standardized_term: value })
                });
                log(`Updated term ${termId.substring(0, 8)}...`, 'success');
            } catch (err) {
                log('Failed to update term: ' + err.message, 'error');
            }
        }

        async function fetchVideoStatus() {
            // Fetch current video status from server
            if (!currentVideoId) return;
            
            try {
                const response = await fetch(`/videos/${currentVideoId}`);
                const data = await response.json();
                
                // Guard: Don't update status if we have an active job and this is stale data
                if (currentJobId && data.status === 'completed' && !loggedCompletions.has(currentJobId)) {
                    // This is likely stale data - wait for WebSocket confirmation
                    console.log('[fetchVideoStatus] Ignoring stale completion status');
                    return;
                }
                
                updateStatus({
                    status: data.status,
                    progress_percent: data.progress_percent || 0,
                    total_segments: data.total_segments,
                    processed_segments: data.processed_segments
                });
                
                updateButtonVisibility(data.status);
                updateContextBrief(data);
                if (data.status === 'completed' && data.segments) {
                    renderSubtitleTimeline(data.segments);
                }
            } catch (err) {
                console.error('Failed to fetch video status:', err);
            }
        }

        // ============================================================================
        // WebSocket Connection Management (REPLACES OLD POLLING)
        // ============================================================================
        
        let ws = null;
        let wsReconnectAttempts = 0;
        const MAX_WS_RECONNECT_ATTEMPTS = 3;
        
        function connectWebSocket(videoId) {
            // Close existing connection if any
            if (ws) {
                ws.close();
                ws = null;
            }
            
            const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
            const wsUrl = `${wsProtocol}//${window.location.host}/ws/videos/${videoId}`;
            
            log('Connecting to WebSocket...');
            console.log(`[WebSocket] Connecting to ${wsUrl}`);
            
            try {
                ws = new WebSocket(wsUrl);
                
                ws.onopen = () => {
                    console.log('[WebSocket] Connected');
                    log('WebSocket connected - real-time updates enabled', 'success');
                    wsReconnectAttempts = 0;
                    
                    // Send initial ping
                    ws.send(JSON.stringify({type: 'ping'}));
                };
                
                ws.onmessage = (event) => {
                    try {
                        const data = JSON.parse(event.data);
                        console.log('[WebSocket] Message received:', data);
                        
                        // Handle different message types
                        if (data.type === 'pong' || data.type === 'keepalive') {
                            return; // Ignore keepalive messages
                        }
                        
                        if (data.type === 'connected') {
                            log(`Connected to video stream: ${data.video_id?.substring(0, 8)}...`);
                            return;
                        }
                        
                        // Update UI based on status
                        handleWebSocketMessage(data);
                        
                    } catch (err) {
                        console.error('[WebSocket] Failed to parse message:', err);
                    }
                };
                
                ws.onerror = (err) => {
                    console.error('[WebSocket] Error:', err);
                    log('WebSocket error - falling back to status polling', 'error');
                };
                
                ws.onclose = () => {
                    console.log('[WebSocket] Connection closed');
                    ws = null;
                    
                    // Attempt to reconnect if we have a video ID and haven't exceeded attempts
                    if (currentVideoId && wsReconnectAttempts < MAX_WS_RECONNECT_ATTEMPTS) {
                        wsReconnectAttempts++;
                        log(`WebSocket disconnected. Reconnecting (${wsReconnectAttempts}/${MAX_WS_RECONNECT_ATTEMPTS})...`);
                        setTimeout(() => connectWebSocket(currentVideoId), 2000);
                    }
                };
                
            } catch (err) {
                console.error('[WebSocket] Failed to create connection:', err);
                log('WebSocket connection failed', 'error');
            }
        }
        
        function disconnectWebSocket() {
            if (ws) {
                ws.close();
                ws = null;
                console.log('[WebSocket] Disconnected by client');
            }
        }
        
        function handleWebSocketMessage(data) {
            // Handle both direct status updates and job messages
            let status = data.status;
            
            // Handle job_complete messages
            if (data.type === 'job_complete') {
                const jobType = data.job_type || 'task';
                const jobId = data.job_id || `${jobType}-${Date.now()}`;
                
                // Guard: Skip if we've already logged this completion
                if (loggedCompletions.has(jobId)) {
                    console.log('[WebSocket] Ignoring duplicate job_complete for:', jobId);
                    return;
                }
                
                // Guard: Skip if this is a stale message for a previous job
                if (currentJobId && data.job_id && data.job_id !== currentJobId) {
                    console.log('[WebSocket] Ignoring stale job_complete for old job:', jobId);
                    return;
                }
                
                console.log('[WebSocket] Job complete:', jobType);
                loggedCompletions.add(jobId);
                
                // Map job types to status and log appropriate completion message
                if (jobType === 'transcribe') {
                    if (!isJobRunning || !hasStartedProcessing) {
                        console.log('[WebSocket] Ignoring stale transcribe complete');
                        return;
                    }
                    status = 'transcribed';
                    // Safe segment count extraction with nullish coalescing
                    const segmentCount = data.result?.total_segments ?? data.total_segments ?? 0;
                    const segText = segmentCount > 0 ? `: ${segmentCount} segments` : '';
                    log(`Transcription complete${segText}`, 'success');
                    isJobRunning = false;
                    hasStartedProcessing = false;
                    updateButtonVisibility('transcribed');
                } else if (jobType === 'analyze') {
                    if (!isJobRunning || !hasStartedProcessing) {
                        console.log('[WebSocket] Ignoring stale analyze complete');
                        return;
                    }
                    status = 'terms_ready';
                    const termCount = data.result?.terms_extracted ?? data.terms_count ?? 0;
                    const termText = termCount > 0 ? `: ${termCount} terms extracted` : '';
                    log(`Analysis complete${termText}`, 'success');
                    isJobRunning = false;
                    hasStartedProcessing = false;
                    renderTerms();
                    updateButtonVisibility('terms_ready');
                } else if (jobType === 'translate') {
                    if (!isJobRunning || !hasStartedProcessing) {
                        console.log('[WebSocket] Ignoring stale translate complete');
                        return;
                    }
                    status = 'completed';
                    const translatedCount = data.result?.translated_segments ?? data.translated_count ?? 0;
                    const totalCount = data.result?.total_segments ?? data.total_segments ?? 0;
                    const countText = (translatedCount > 0 || totalCount > 0) 
                        ? `: ${translatedCount}/${totalCount} segments` 
                        : '';
                    log(`Translation complete${countText}`, 'success');
                    isJobRunning = false;
                    hasStartedProcessing = false;
                    updateButtonVisibility('completed');
                    if (data.result?.segments) renderSubtitleTimeline(data.result.segments);
                } else {
                    log(`${jobType} complete`, 'success');
                }
                
                // Refresh status from server (without triggering duplicate logs)
                fetchVideoStatus();
                return; // Don't process further - we handled it
            }
            
            // Handle job_error messages
            if (data.type === 'job_error') {
                const jobType = data.job_type || 'task';
                const errorMsg = data.error || 'Unknown error';
                console.log('[WebSocket] Job error:', data);
                log(`${jobType} failed: ${errorMsg}`, 'error');
                return;
            }
            
            // Handle job_started messages
            if (data.type === 'job_started') {
                const jobType = data.job_type || 'task';
                console.log('[WebSocket] Job started:', jobType);
                hasStartedProcessing = true;
                // Log appropriate started message
                if (jobType === 'transcribe') {
                    log('Transcription started...');
                } else if (jobType === 'analyze') {
                    log('Analysis started...');
                } else if (jobType === 'translate') {
                    log('Translation started...');
                } else {
                    log(`${jobType} started...`);
                }
                return;
            }
            
            // Update status display for regular status messages
            updateStatus({
                status: status,
                progress_percent: data.progress || videoProgressPercent || 0,
                total_segments: data.total_segments,
                processed_segments: data.processed_segments,
                current_step: data.message || status
            });
            
            // Log the update (only if meaningful message exists)
            const logMessage = data.message || data.step_detail;
            if (logMessage && logMessage !== status && logMessage !== 'undefined') {
                // Badge duration & completion metrics as SUCCESS
                const isMetric = /(?:duration|elapsed|complete in|segments?|total)\\s*[:\\-]?\\s*\\d/i.test(logMessage);
                log(logMessage, isMetric ? 'success' : 'info');
            }
            
            // Status Transition Guard: only mark after we see a processing state
            if (['queued', 'extracting_audio', 'transcribing', 'analyzing', 'glossary_extracting', 'translating'].includes(status)) {
                hasStartedProcessing = true;
            }
            
            // Handle specific statuses
            switch (status) {
                case 'queued':
                    log('Job queued - waiting for available worker...');
                    break;
                    
                case 'transcribing':
                    log('Transcribing audio...');
                    break;
                    
                case 'transcribed':
                    if (isJobRunning && hasStartedProcessing) {
                        log('Transcription complete!', 'success');
                        isJobRunning = false;
                        hasStartedProcessing = false;
                    }
                    updateButtonVisibility('transcribed');
                    break;
                    
                case 'analyzing':
                    log('Director Agent: Analyzing content...');
                    break;
                    
                case 'context_ready':
                    log(`Director Agent complete: ${data.tone} tone`, 'context');
                    // Fetch full Pass 1 context_analysis for the narrative brief
                    fetch(`/videos/${currentVideoId}`)
                        .then(r => r.json())
                        .then(videoData => updateContextBrief(videoData));
                    break;
                    
                case 'glossary_extracting':
                    log('Glossary Agent: Extracting terms...');
                    break;
                    
                case 'terms_ready':
                    if (isJobRunning && hasStartedProcessing) {
                        log(`Glossary complete: ${data.terms_count ?? 0} terms`, 'success');
                        isJobRunning = false;
                        hasStartedProcessing = false;
                    }
                    renderTerms();
                    updateButtonVisibility('terms_ready');
                    break;
                    
                case 'translating':
                    log('Translating via Gemini AI...');
                    break;
                    
                case 'completed':
                    if (isJobRunning && hasStartedProcessing) {
                        log('Translation complete!', 'success');
                        isJobRunning = false;
                        hasStartedProcessing = false;
                    }
                    renderTerms();
                    updateButtonVisibility('completed');
                    if (data.segments) renderSubtitleTimeline(data.segments);
                    break;
                    
                case 'error':
                    log(`Error: ${data.message || data.error}`, 'error');
                    break;
            }
            
            // Handle job retry messages
            if (data.type === 'job_retry') {
                log(`Retrying: ${data.job_type} (${data.retry_count}/${data.max_retries})`);
            }
        }
        
        function updateButtonVisibility(status) {
            const primaryBtn = document.getElementById('primaryActionBtn');
            const helperText = document.getElementById('primaryHelperText');
            const ghostLink = document.getElementById('primaryGhostLink');
            const exportGrid = document.getElementById('primaryExportGrid');
            const exportHeader = document.getElementById('exportHeader');
            const container = document.getElementById('primaryActionContainer');
            
            if (!container) return;
            
            // Reset all sub-elements
            primaryBtn?.classList.remove('hidden');
            helperText?.classList.add('hidden');
            ghostLink?.classList.add('hidden');
            exportGrid?.classList.add('hidden');
            exportHeader?.classList.add('hidden');
            
            // Configure primary action based on pipeline state
            switch (status) {
                case 'uploaded':
                    primaryBtn.textContent = currentFileType === 'text' ? '1. Parse Text' : '1. Transcribe Audio';
                    primaryBtn.className = 'w-full py-3 px-4 bg-emerald-600 hover:bg-emerald-700 text-white text-sm font-semibold rounded-lg transition-colors shadow-sm';
                    primaryBtn.onclick = processFile;
                    break;
                    
                case 'transcribed':
                    primaryBtn.textContent = '2. Extract Terminology';
                    primaryBtn.className = 'w-full py-3 px-4 bg-blue-600 hover:bg-blue-700 text-white text-sm font-semibold rounded-lg transition-colors shadow-sm';
                    primaryBtn.onclick = analyzeVideo;
                    ghostLink?.classList.remove('hidden');
                    break;
                    
                case 'terms_ready':
                    helperText?.classList.remove('hidden');
                    primaryBtn.textContent = '3. Translate Subtitles';
                    primaryBtn.className = 'w-full py-3 px-4 bg-purple-600 hover:bg-purple-700 text-white text-sm font-semibold rounded-lg transition-colors shadow-sm';
                    primaryBtn.onclick = translateVideo;
                    break;
                    
                case 'completed':
                    primaryBtn?.classList.add('hidden');
                    exportGrid?.classList.remove('hidden');
                    exportHeader?.classList.remove('hidden');
                    document.getElementById('termsPanel').classList.add('hidden');
                    document.getElementById('subtitleReviewPanel').classList.remove('hidden');
                    break;
                    
                default:
                    primaryBtn?.classList.add('hidden');
                    document.getElementById('termsPanel').classList.remove('hidden');
                    document.getElementById('subtitleReviewPanel').classList.add('hidden');
            }
        }
        
        function updateContextBrief(data) {
            const container = document.getElementById('contextBriefContainer');
            const textEl = document.getElementById('contextBriefText');
            if (!container || !textEl) return;
            
            let brief = '';
            
            // Prefer explicit main_topic if available
            if (data.main_topic) {
                brief = data.main_topic;
            }
            // Try parsing context_analysis JSON (from polling)
            else if (data.context_analysis) {
                try {
                    const ca = typeof data.context_analysis === 'string' ? JSON.parse(data.context_analysis) : data.context_analysis;
                    if (ca.main_topic) brief = ca.main_topic;
                    else if (ca.translation_notes) brief = ca.translation_notes;
                } catch (e) { /* ignore parse errors */ }
            }
            // Fallback to style-guide metadata from WebSocket
            else if (data.domain || data.tone) {
                const parts = [];
                if (data.domain) parts.push(data.domain);
                if (data.tone) parts.push(`${data.tone} tone`);
                if (data.formality_level) parts.push(`formality ${data.formality_level}/5`);
                brief = parts.join(' • ');
            }
            
            if (brief) {
                textEl.textContent = brief;
                container.classList.remove('hidden');
            }
        }
        
        // Legacy polling fallback (only used if WebSocket fails)
        let fallbackPollInterval = null;
        let fallbackPollCount = 0;
        
        function fallbackToPolling(videoId) {
            log('Falling back to HTTP polling (WebSocket unavailable)', 'warning');
            console.log('[FALLBACK] Starting HTTP polling');
            
            if (fallbackPollInterval) {
                clearInterval(fallbackPollInterval);
            }
            
            fallbackPollCount = 0;
            fallbackPollInterval = setInterval(async () => {
                try {
                    const response = await fetch(`/videos/${videoId}`);
                    const data = await response.json();
                    updateStatus(data);
                    updateContextBrief(data);
                    fallbackPollCount++;
                    
                    if (fallbackPollCount % 5 === 0) {
                        log(`Fallback poll #${fallbackPollCount}: status=${data.status}`);
                    }
                    
                    if (['terms_ready', 'completed', 'error'].includes(data.status)) {
                        clearInterval(fallbackPollInterval);
                        fallbackPollInterval = null;
                        if (data.status === 'terms_ready' || data.status === 'completed') {
                            renderTerms();
                        }
                        if (data.status === 'completed' && data.segments) {
                            renderSubtitleTimeline(data.segments);
                        }
                    }
                } catch (err) {
                    console.error('Fallback poll error:', err);
                }
            }, 5000);
        }

        function resetApp() {
            currentVideoId = null;
            currentFileType = 'video';
            currentJobId = null;
            isJobRunning = false;
            hasStartedProcessing = false;
            loggedCompletions.clear();
            
            // Reset upload form
            const fileInputEl = document.getElementById('fileInput');
            if (fileInputEl) fileInputEl.value = '';
            const fileLabelEl = document.getElementById('fileLabel');
            if (fileLabelEl) fileLabelEl.textContent = 'Click to select file';
            const dropZoneEl = document.getElementById('dropZone');
            if (dropZoneEl) dropZoneEl.classList.remove('border-blue-400', 'bg-blue-50');
            const uploadFormReset = document.getElementById('uploadForm');
            if (uploadFormReset) uploadFormReset.classList.remove('hidden');
            const uploadCompleteCardReset = document.getElementById('uploadCompleteCard');
            if (uploadCompleteCardReset) uploadCompleteCardReset.classList.add('hidden');
            const setupConfigPanelReset = document.getElementById('setupConfigPanel');
            if (setupConfigPanelReset) setupConfigPanelReset.classList.remove('hidden');
            
            // Hide status and action containers
            const statusCardReset = document.getElementById('statusCard');
            if (statusCardReset) statusCardReset.classList.add('hidden');
            const primaryActionReset = document.getElementById('primaryActionContainer');
            if (primaryActionReset) primaryActionReset.classList.add('hidden');
            const termsPanelReset = document.getElementById('termsPanel');
            if (termsPanelReset) termsPanelReset.classList.remove('hidden');
            const subtitleReviewReset = document.getElementById('subtitleReviewPanel');
            if (subtitleReviewReset) subtitleReviewReset.classList.add('hidden');
            const timelineGridReset = document.getElementById('timelineCardGrid');
            if (timelineGridReset) timelineGridReset.innerHTML = '<div class="text-slate-400 text-center py-8">No subtitles available yet.</div>';
            
            // Reset step & segment counters
            const segCountReset = document.getElementById('segmentCount');
            if (segCountReset) segCountReset.textContent = '0 segments';
            const procCountReset = document.getElementById('processedCount');
            if (procCountReset) procCountReset.textContent = '0 processed';
            const stepReset = document.getElementById('currentStep');
            if (stepReset) stepReset.textContent = 'Ready to process';
            
            // Clear logs and terms
            clearActivityLog();
            const termsTableReset = document.getElementById('termsTable');
            if (termsTableReset) termsTableReset.innerHTML = `
                <tr>
                    <td colspan="5" class="px-3 py-8 text-center text-slate-400 text-sm">
                        No terms extracted yet. Upload and process a video.
                    </td>
                </tr>
            `;
            
            // Disconnect WebSocket
            disconnectWebSocket();
            
            // Clear URL param
            window.history.replaceState({}, document.title, window.location.pathname);
            
            log('New project ready. Upload a file to begin.', 'success');
        }

        // Upload handler
        async function uploadFile() {
            const fileInput = document.getElementById('fileInput');
            const targetLangSelect = document.getElementById('targetLanguage');
            const sourceLangSelect = document.getElementById('sourceLanguage');
            
            if (!fileInput.files || !fileInput.files[0]) {
                return;
            }

            const formData = new FormData();
            formData.append('file', fileInput.files[0]);
            formData.append('target_language', targetLangSelect.value);
            formData.append('source_language', sourceLangSelect.value);

            log('Uploading file...');
            
            try {
                const response = await fetch('/videos/upload', {
                    method: 'POST',
                    body: formData
                });
                
                if (!response.ok) {
                    // Try to get detailed error message from response
                    let errorDetail = 'Upload failed';
                    try {
                        const errorData = await response.json();
                        errorDetail = errorData.detail || `HTTP ${response.status}: ${response.statusText}`;
                    } catch (e) {
                        errorDetail = `HTTP ${response.status}: ${response.statusText}`;
                    }
                    throw new Error(errorDetail);
                }
                
                const data = await response.json();
                currentVideoId = data.id;
                currentFileType = data.content_type || 'video';
                
                // Set Project Metadata
                const projectTitleEl = document.getElementById('projectTitle');
                if (projectTitleEl) projectTitleEl.textContent = data.filename || 'Untitled Project';
                
                const projectTypeEl = document.getElementById('projectType');
                if (projectTypeEl) projectTypeEl.innerHTML = 
                    `<i class="fa-solid ${currentFileType === 'text' ? 'fa-file-lines' : 'fa-video'} mr-1"></i>${currentFileType === 'text' ? 'Text File' : 'Video'}`;
                
                const sourceLangSel = document.getElementById('sourceLanguage');
                const sourceLang = sourceLangSel && sourceLangSel.value === 'auto' ? 'Auto' : 
                    (sourceLangSel ? sourceLangSel.value.toUpperCase() : 'Auto');
                const targetLangSel = document.getElementById('targetLanguage');
                const targetLang = targetLangSel ? targetLangSel.value.toUpperCase() : '';
                const projectLangsEl = document.getElementById('projectLangs');
                if (projectLangsEl) projectLangsEl.textContent = `${sourceLang} → ${targetLang}`;
                
                const projectIdEl = document.getElementById('projectId');
                if (projectIdEl) projectIdEl.textContent = currentVideoId.substring(0, 8);
                
                const statusCardEl = document.getElementById('statusCard');
                if (statusCardEl) statusCardEl.classList.remove('hidden');
                const primaryActionEl = document.getElementById('primaryActionContainer');
                if (primaryActionEl) primaryActionEl.classList.remove('hidden');
                
                // Swap upload form for compact filename card
                const uploadFormEl = document.getElementById('uploadForm');
                if (uploadFormEl) uploadFormEl.classList.add('hidden');
                const uploadCompleteCardEl = document.getElementById('uploadCompleteCard');
                if (uploadCompleteCardEl) uploadCompleteCardEl.classList.remove('hidden');
                const uploadedFilenameEl = document.getElementById('uploadedFilename');
                if (uploadedFilenameEl) uploadedFilenameEl.textContent = data.filename || 'Untitled Project';
                
                log('Upload complete: ' + data.filename, 'success');
                
                updateStatus({ status: 'uploaded', progress_percent: 0 });
                
            } catch (err) {
                const errorMsg = err.message || 'Upload failed';
                log('Upload failed: ' + errorMsg, 'error');
            }
        }

        // Process file handler (handles both video transcription and text parsing)
        async function processFile() {
            if (!currentVideoId) return;
            
            // Validate target language is selected
            const targetLangSelect = document.getElementById('targetLanguage');
            if (!targetLangSelect || !targetLangSelect.value) {
                const warningEl = document.getElementById('languageWarning');
                if (warningEl) warningEl.classList.remove('hidden');
                if (targetLangSelect) {
                    targetLangSelect.classList.add('border-red-500', 'focus:ring-red-500', 'focus:border-red-500');
                    targetLangSelect.scrollIntoView({ behavior: 'smooth', block: 'center' });
                }
                return;
            }
            
            // Collapse setup config panel once processing starts
            const setupPanel = document.getElementById('setupConfigPanel');
            if (setupPanel) setupPanel.classList.add('hidden');
            
            // Reset state for new job
            currentJobId = `transcribe-${currentVideoId}-${Date.now()}`;
            isJobRunning = true;
            hasStartedProcessing = false;
            
            const isTextFile = currentFileType === 'text';
            const actionName = isTextFile ? 'parsing text' : 'transcription';
            
            const engine = document.getElementById('transcriptionEngine').value;
            const engineLabel = engine === 'gemini' ? 'Gemini Cloud' : 'Local Whisper';
            log(isTextFile ? 'Starting text parsing...' : `Starting ${engineLabel} transcription...`);
            
            try {
                const engine = document.getElementById('transcriptionEngine').value;
                const requestHeaders = {};
                
                // Forward Gemini API key when using Cloud Engine
                if (engine === 'gemini') {
                    const apiKey = localStorage.getItem('termsub_gemini_api_key') || document.getElementById('geminiApiKey').value || '';
                    if (apiKey.trim()) {
                        requestHeaders['X-Gemini-API-Key'] = apiKey.trim();
                    }
                }
                
                const response = await fetch(`/videos/${currentVideoId}/transcribe?method=whisper&provider=${engine}`, {
                    method: 'POST',
                    headers: requestHeaders
                });
                
                if (!response.ok) {
                    let errorMessage = isTextFile ? 'Text parsing failed' : 'Transcription failed';
                    try {
                        const errorData = await response.json();
                        errorMessage = errorData.detail || errorMessage;
                    } catch (e) {
                        // response wasn't JSON — keep default
                    }
                    throw new Error(errorMessage);
                }
                
                const data = await response.json();
                
                // Update UI silently — completion will be logged via WebSocket
                updateStatus({ status: 'transcribed', total_segments: data.total_segments ?? 0 });
                const segCountUpload = document.getElementById('segmentCount');
                if (segCountUpload) segCountUpload.textContent = data.total_segments ?? 0;
                
                // Show analyze button
                updateButtonVisibility('transcribed');
                
                // Connect WebSocket for future updates
                connectWebSocket(currentVideoId);
                
            } catch (err) {
                log((isTextFile ? 'Parsing' : 'Transcription') + ' failed: ' + err.message, 'error');
            }
        }

        // Analyze handler (Multi-Agent Step 1)
        async function analyzeVideo() {
            if (!currentVideoId) return;
            
            // Reset state for new job
            currentJobId = `analyze-${currentVideoId}-${Date.now()}`;
            isJobRunning = true;
            hasStartedProcessing = false;
            
            log('Starting Multi-Agent Analysis (Director + Glossary)...');
            log('Director Agent: Analyzing context and style...');
            
            try {
                const response = await fetch(`/videos/${currentVideoId}/analyze`, {
                    method: 'POST'
                });
                
                if (!response.ok) {
                    const err = await response.json();
                    throw new Error(err.detail || 'Analysis failed');
                }
                
                const data = await response.json();
                
                // Update UI silently — completion will be logged via WebSocket
                updateStatus({ status: 'terms_ready' });
                updateButtonVisibility('terms_ready');
                
                // Render terms
                await renderTerms();
                
            } catch (err) {
                log('Analysis failed: ' + err.message, 'error');
            }
        }

        // Translate handler (Multi-Agent Step 2)
        async function translateVideo() {
            if (!currentVideoId) return;
            
            // Reset state for new job
            currentJobId = `translate-${currentVideoId}-${Date.now()}`;
            isJobRunning = true;
            hasStartedProcessing = false;
            
            log('Starting Gemini Translator Agent...');
            log('Using sliding window translation with glossary constraints');
            
            try {
                const response = await fetch(`/videos/${currentVideoId}/translate`, {
                    method: 'POST'
                });
                
                if (!response.ok) {
                    const err = await response.json();
                    throw new Error(err.detail || 'Translation failed');
                }
                
                
                // Update UI silently — completion will be logged via WebSocket
                updateStatus({ status: 'completed' });
                updateButtonVisibility('completed');
                
            } catch (err) {
                log('Translation failed: ' + err.message, 'error');
            }
        }

        // Generic export handler
        async function exportFormat(format) {
            if (!currentVideoId) return;
            
            const formatNames = {
                'srt': 'SRT',
                'vtt': 'WebVTT',
                'txt': 'Text',
                'json': 'JSON'
            };
            
            try {
                const response = await fetch(`/export/${currentVideoId}/${format}`);
                
                if (!response.ok) throw new Error('Export failed');
                
                const blob = await response.blob();
                const url = window.URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = `translation_${currentVideoId.substring(0, 8)}.${format}`;
                document.body.appendChild(a);
                a.click();
                a.remove();
                window.URL.revokeObjectURL(url);
                
                log(`${formatNames[format]} exported`, 'success');
                
            } catch (err) {
                log('Export failed: ' + err.message, 'error');
            }
        }

        // Download original transcription handler
        async function downloadTranscription() {
            if (!currentVideoId) return;
            
            try {
                const response = await fetch(`/export/${currentVideoId}/transcription`);
                
                if (!response.ok) throw new Error('Download failed');
                
                const blob = await response.blob();
                const url = window.URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = `transcription_${currentVideoId.substring(0, 8)}.srt`;
                document.body.appendChild(a);
                a.click();
                a.remove();
                window.URL.revokeObjectURL(url);
                
                log('Transcription downloaded', 'success');
                
            } catch (err) {
                log('Download failed: ' + err.message, 'error');
            }
        }

        // Event listeners
        document.addEventListener('DOMContentLoaded', () => {
            // --- Engine Selection Cards ---
            const engineCards = document.querySelectorAll('.engine-card');
            const engineInput = document.getElementById('transcriptionEngine');

            function updateEngineSelection(selectedEngine) {
                engineCards.forEach(card => {
                    const isSelected = card.dataset.engine === selectedEngine;
                    const radioRing = card.querySelector('.engine-radio');
                    const radioDot = radioRing.querySelector('div');
                    if (isSelected) {
                        card.classList.add('border-blue-500', 'bg-blue-50');
                        card.classList.remove('border-slate-200', 'hover:border-slate-300');
                        radioRing.classList.add('border-blue-500');
                        radioRing.classList.remove('border-slate-300');
                        radioDot.classList.remove('hidden');
                    } else {
                        card.classList.remove('border-blue-500', 'bg-blue-50');
                        card.classList.add('border-slate-200', 'hover:border-slate-300');
                        radioRing.classList.remove('border-blue-500');
                        radioRing.classList.add('border-slate-300');
                        radioDot.classList.add('hidden');
                    }
                });
                engineInput.value = selectedEngine;
            }

            engineCards.forEach(card => {
                card.addEventListener('click', () => {
                    updateEngineSelection(card.dataset.engine);
                });
            });

            // --- Gemini API Key Vault (localStorage) ---
            const apiKeyInput = document.getElementById('geminiApiKey');
            const savedKey = localStorage.getItem('termsub_gemini_api_key');
            if (savedKey) {
                apiKeyInput.value = savedKey;
            }
            apiKeyInput.addEventListener('input', () => {
                localStorage.setItem('termsub_gemini_api_key', apiKeyInput.value);
            });

            // File input
            const fileInput = document.getElementById('fileInput');
            const fileLabel = document.getElementById('fileLabel');
            
            fileInput.addEventListener('change', () => {
                if (fileInput.files && fileInput.files[0]) {
                    const file = fileInput.files[0];
                    fileLabel.textContent = file.name;
                    document.getElementById('dropZone').classList.add('border-blue-400', 'bg-blue-50');
                    
                    // Detect file type for downstream pipeline text
                    const isTextFile = file.name.toLowerCase().endsWith('.txt');
                    currentFileType = isTextFile ? 'text' : 'video';
                }
            });
            
            // Target language change: clear validation warning
            const targetLangSelect = document.getElementById('targetLanguage');
            if (targetLangSelect) {
                targetLangSelect.addEventListener('change', () => {
                    if (targetLangSelect.value) {
                        const warningEl = document.getElementById('languageWarning');
                        if (warningEl) warningEl.classList.add('hidden');
                        targetLangSelect.classList.remove('border-red-500', 'focus:ring-red-500', 'focus:border-red-500');
                    }
                });
            }

            // Buttons
            document.getElementById('uploadBtn').addEventListener('click', uploadFile);
            document.getElementById('startNewProjectBtn').addEventListener('click', resetApp);
            
            // Global Find & Replace handler
            document.getElementById('replaceAllBtn').addEventListener('click', async () => {
                if (!currentVideoId || isSavingSegment) return;
                const findInput = document.getElementById('findInput');
                const replaceInput = document.getElementById('replaceInput');
                const replaceBtn = document.getElementById('replaceAllBtn');
                const findText = findInput ? findInput.value.trim() : '';
                if (!findText) return;
                
                isSavingSegment = true;
                if (replaceBtn) {
                    replaceBtn.textContent = 'Replacing...';
                    replaceBtn.classList.add('opacity-50', 'cursor-not-allowed');
                }
                
                try {
                    const response = await fetch(`/videos/${currentVideoId}/replace`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ find_text: findText, replace_text: replaceInput ? replaceInput.value : '' })
                    });
                    if (!response.ok) throw new Error('Replace failed');
                    const data = await response.json();
                    if (data.segments) renderSubtitleTimeline(data.segments);
                    if (findInput) findInput.value = '';
                    if (replaceInput) replaceInput.value = '';
                    log('Global replace applied successfully.', 'success');
                    showToast('Batch replacement complete!', 'success');
                } catch (err) {
                    log('Replace failed: ' + err.message, 'error');
                } finally {
                    isSavingSegment = false;
                    if (replaceBtn) {
                        replaceBtn.textContent = 'Replace All';
                        replaceBtn.classList.remove('opacity-50', 'cursor-not-allowed');
                    }
                }
            });
            document.getElementById('downloadRawTranscriptionLink').addEventListener('click', downloadTranscription);
            document.getElementById('exportSrtBtn').addEventListener('click', () => exportFormat('srt'));
            document.getElementById('exportVttBtn').addEventListener('click', () => exportFormat('vtt'));
            document.getElementById('exportTxtBtn').addEventListener('click', () => exportFormat('txt'));
            document.getElementById('exportJsonBtn').addEventListener('click', () => exportFormat('json'));   

            // Check for video ID in URL
            const videoId = new URLSearchParams(window.location.search).get('video');
            if (videoId) {
                currentVideoId = videoId;
                const videoIdShortEl = document.getElementById('videoIdShort');
                if (videoIdShortEl) videoIdShortEl.textContent = videoId.substring(0, 8);
                const statusCardEl2 = document.getElementById('statusCard');
                if (statusCardEl2) statusCardEl2.classList.remove('hidden');
                const primaryActionEl2 = document.getElementById('primaryActionContainer');
                if (primaryActionEl2) primaryActionEl2.classList.remove('hidden');
                
                // Hide upload form, show compact card for loaded project
                const uploadFormEl2 = document.getElementById('uploadForm');
                if (uploadFormEl2) uploadFormEl2.classList.add('hidden');
                const uploadCompleteCardEl2 = document.getElementById('uploadCompleteCard');
                if (uploadCompleteCardEl2) uploadCompleteCardEl2.classList.remove('hidden');
                const uploadedFilenameEl2 = document.getElementById('uploadedFilename');
                if (uploadedFilenameEl2) uploadedFilenameEl2.textContent = 'Loaded project';
                
                // Connect WebSocket for real-time updates
                connectWebSocket(videoId);
                
                // Fetch current status
                fetch(`/videos/${videoId}`)
                    .then(r => r.json())
                    .then(data => {
                        updateStatus(data);
                        updateButtonVisibility(data.status);
                        updateContextBrief(data);
                        if (data.total_segments) {
                            const segCountLoad = document.getElementById('segmentCount');
                            if (segCountLoad) segCountLoad.textContent = data.total_segments;
                        }
                        if (data.status === 'completed' && data.segments) {
                            renderSubtitleTimeline(data.segments);
                        }
                    });
            }
        });
    </script>
</body>
</html>"""


@app.get("/", response_class=HTMLResponse)
def root():
    """Root endpoint - serve the demo HTML interface."""
    return HTML_INTERFACE


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
