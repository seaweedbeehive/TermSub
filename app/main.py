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
            <div class="lg:col-span-1 space-y-6">
                <!-- Upload Card -->
                <div class="bg-white rounded-xl shadow-sm p-6">
                    <h2 class="text-sm font-semibold text-slate-900 mb-4">Upload File</h2>
                    
                    <div class="space-y-4">
                        <div>
                            <input type="file" id="fileInput" accept="video/*,audio/*,.txt" class="hidden">
                            <label for="fileInput" id="dropZone"
                                class="flex flex-col items-center justify-center w-full h-32 border-2 border-dashed border-slate-300 rounded-lg bg-slate-50 hover:bg-slate-100 cursor-pointer transition-colors">
                                <i class="fa-solid fa-cloud-arrow-up text-2xl text-slate-400 mb-2"></i>
                                <p class="text-sm text-slate-600 font-medium" id="fileLabel">Click to select file</p>
                                <p class="text-xs text-slate-400 mt-1">MP4, MOV, AVI, MP3, TXT</p>
                            </label>
                        </div>

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
                                <option value="fa">Persian (Farsi)</option>
                                <option value="es">Spanish</option>
                                <option value="fr">French</option>
                                <option value="de">German</option>
                                <option value="en">English</option>
                                <option value="ar">Arabic</option>
                                <option value="it">Italian</option>
                                <option value="ja">Japanese</option>
                                <option value="zh">Chinese</option>
                            </select>
                        </div>

                        <div>
                            <label class="block text-xs font-medium text-slate-700 mb-1">Transcription Engine</label>
                            <select id="transcriptionEngine" class="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500">
                                <option value="gemini" selected>Cloud (Gemini Flash)</option>
                                <option value="local">Local (Privacy First)</option>
                            </select>
                            <p class="text-[10px] text-slate-500 mt-1">Cloud uses Google's AI for maximum accuracy.</p>
                        </div>

                        <button id="uploadBtn" class="w-full py-2.5 px-4 bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium rounded-lg transition-colors">
                            <i class="fa-solid fa-upload mr-2"></i>Upload File
                        </button>
                    </div>
                </div>

                <!-- Project Metadata & Status Card (Unified) -->
                <div id="statusCard" class="bg-white rounded-xl shadow-sm overflow-hidden hidden">
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
                        
                        <!-- Progress with Large Percentage -->
                        <div class="mb-4">
                            <div class="flex items-end justify-between mb-2">
                                <span id="currentStep" class="text-sm text-slate-600">Ready to process</span>
                                <span id="progressPercentLarge" class="text-2xl font-bold text-slate-900">0%</span>
                            </div>
                            <div class="w-full bg-slate-200 rounded-full h-3">
                                <div id="progressBar" class="progress-bar bg-blue-600 h-3 rounded-full" style="width: 0%"></div>
                            </div>
                            <div class="flex justify-between mt-1.5 text-xs text-slate-500">
                                <span id="segmentCount">0 segments</span>
                                <span id="processedCount">0 processed</span>
                            </div>
                        </div>
                        
                        <!-- Step Detail -->
                        <div id="stepDetail" class="text-xs text-slate-500 bg-slate-50 rounded-lg px-3 py-2 hidden"></div>
                    </div>

                    <!-- Action Buttons -->
                    <div class="px-6 pb-6 space-y-2">
                        <button id="transcribeBtn" class="w-full py-2.5 px-4 bg-emerald-600 hover:bg-emerald-700 text-white text-sm font-medium rounded-lg transition-colors hidden">
                            <i class="fa-solid fa-waveform mr-2"></i><span id="transcribeBtnText">Transcribe</span>
                        </button>
                        <button id="downloadTranscriptionBtn" class="w-full py-2.5 px-4 bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium rounded-lg transition-colors hidden">
                            <i class="fa-solid fa-download mr-2"></i>Download Transcription
                        </button>
                        <button id="analyzeBtn" class="w-full py-2.5 px-4 bg-amber-600 hover:bg-amber-700 text-white text-sm font-medium rounded-lg transition-colors hidden">
                            <i class="fa-solid fa-brain mr-2"></i>Analyze Content
                        </button>
                        <button id="translateBtn" class="w-full py-2.5 px-4 bg-purple-600 hover:bg-purple-700 text-white text-sm font-medium rounded-lg transition-colors hidden">
                            <i class="fa-solid fa-language mr-2"></i>Translate
                        </button>
                        <div id="exportSection" class="hidden space-y-2 pt-2 border-t border-slate-200">
                            <p class="text-xs font-medium text-slate-700">Export Translation</p>
                            <div class="grid grid-cols-2 gap-2">
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
                </div>
            </div>

            <!-- Right Panel - Terms & Activity -->
            <div class="lg:col-span-2 space-y-6">
                <!-- Terms Table -->
                <div class="bg-white rounded-xl shadow-sm p-6">
                    <h2 class="text-sm font-semibold text-slate-900 mb-4">Extracted Terms</h2>
                    <div class="overflow-x-auto">
                        <table class="w-full text-sm">
                            <thead class="bg-slate-50 text-slate-600">
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
                    
                    <!-- Custom Terms (Find & Replace) -->
                    <div id="customTermsSection" class="mt-6 pt-6 border-t border-slate-200">
                        <h3 class="text-sm font-semibold text-slate-900 mb-3">Custom Terms (Find & Replace)</h3>
                        <p class="text-xs text-slate-500 mb-3">Add custom translations that will override auto-detected terms.</p>
                        <div class="flex gap-2 mb-3">
                            <input type="text" id="customOriginal" placeholder="Find (original)" 
                                class="flex-1 px-3 py-2 border border-slate-300 rounded-lg text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500">
                            <input type="text" id="customTranslated" placeholder="Replace with (translation)" 
                                class="flex-1 px-3 py-2 border border-slate-300 rounded-lg text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500">
                            <button onclick="addCustomTerm()" class="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium rounded-lg transition-colors">
                                <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4 inline mr-1" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4" />
                                </svg>
                                Add
                            </button>
                        </div>
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

    <!-- Toast Notification -->
    <div id="toast" class="fixed bottom-4 right-4 bg-slate-800 text-white px-4 py-3 rounded-lg shadow-lg transform translate-y-20 opacity-0 transition-all duration-300 z-50">
        <div class="flex items-center gap-2">
            <i id="toastIcon" class="fa-solid fa-check-circle text-emerald-400"></i>
            <span id="toastMessage">Message</span>
        </div>
    </div>

    <script>
        // State
        let currentVideoId = null;
        let videoProgressPercent = 0;  // Track progress for WebSocket updates
        let currentFileType = 'video'; // 'video' or 'text' - tracks uploaded file type
        let loggedCompletions = new Set(); // Track completed jobs to prevent duplicate logs
        let currentJobId = null; // Track current job to ignore stale messages
        let isJobRunning = false; // Silver bullet: prevents stale completion logs
        let hasStartedProcessing = false; // Status Transition Guard: ignore COMPLETED until processing starts

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
            translating: { label: 'Translating', color: 'bg-purple-100 text-purple-800', dotColor: 'bg-purple-500' },
            completed: { label: 'Completed', color: 'bg-emerald-100 text-emerald-800', dotColor: 'bg-emerald-500' },
            error: { label: 'Error', color: 'bg-rose-100 text-rose-800', dotColor: 'bg-rose-500' }
        };

        // Utility functions
        function showToast(message, type = 'success') {
            const toast = document.getElementById('toast');
            const toastIcon = document.getElementById('toastIcon');
            const toastMessage = document.getElementById('toastMessage');
            
            toastMessage.textContent = message;
            toastIcon.className = type === 'success' ? 'fa-solid fa-check-circle text-emerald-400' : 
                                  type === 'error' ? 'fa-solid fa-exclamation-circle text-red-400' :
                                  'fa-solid fa-info-circle text-blue-400';
            
            toast.classList.remove('translate-y-20', 'opacity-0');
            setTimeout(() => toast.classList.add('translate-y-20', 'opacity-0'), 3000);
        }

        function log(message, type = 'info') {
            const logEl = document.getElementById('activityLog');
            const time = new Date().toLocaleTimeString('en-US', { hour12: false });
            const color = type === 'error' ? 'text-red-400' : type === 'success' ? 'text-emerald-400' : 'text-slate-300';
            
            if (logEl.children.length === 1 && logEl.children[0].textContent.includes('Waiting')) {
                logEl.innerHTML = '';
            }
            
            // Prevent duplicate completion messages
            const lastEntry = logEl.lastElementChild;
            if (lastEntry && lastEntry.textContent.includes(message)) {
                return; // Skip duplicate message
            }
            
            logEl.innerHTML += `<div class="${color}">[${time}] ${message}</div>`;
            logEl.scrollTop = logEl.scrollHeight;
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

        function updateStatus(data) {
            const cfg = statusConfig[data.status] || statusConfig.uploaded;
            const progress = data.progress_percent || 0;
            const isProcessing = ['transcribing', 'extracting_audio', 'analyzing', 'glossary_extracting', 'translating', 'queued'].includes(data.status);
            
            // Update Status Badge in Card
            const statusBadge = document.getElementById('statusBadge');
            statusBadge.className = `inline-flex items-center gap-1.5 px-3 py-1.5 ${cfg.color} text-xs font-semibold rounded-full transition-colors`;
            statusBadge.innerHTML = `<span id="statusDot" class="w-1.5 h-1.5 rounded-full ${cfg.dotColor} ${isProcessing ? 'pulse-indicator' : ''}"></span>${cfg.label}`;
            
            // Update Progress Section
            document.getElementById('currentStep').textContent = data.current_step || 'Ready';
            document.getElementById('progressPercentLarge').textContent = `${progress}%`;
            document.getElementById('progressBar').style.width = `${progress}%`;
            document.getElementById('segmentCount').textContent = `${data.total_segments ?? 0} segments`;
            document.getElementById('processedCount').textContent = `${data.processed_segments || 0} processed`;
            
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
                    const cleanTranslation = (term.translated_term || '').replace(/^\[.*?\]\s*/, '');
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
                                    class="flex-1 px-2 py-1 border border-slate-300 rounded text-xs focus:ring-2 focus:ring-blue-500 focus:border-blue-500">
                                ${term.source === 'manual' ? `
                                    <button onclick="deleteCustomTerm('${term.id}')" 
                                        class="text-rose-500 hover:text-rose-700 p-1" title="Remove custom term">
                                        <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                                        </svg>
                                    </button>
                                ` : ''}
                            </div>
                        </td>
                    </tr>
                `}).join('');
            } catch (err) {
                console.error('Failed to load terms:', err);
            }
        }

        async function updateTerm(termId, value) {
            try {
                await fetch(`/terms/${termId}`, {
                    method: 'PATCH',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ standardized_term: value })
                });
                log(`Updated term ${termId.substring(0, 8)}...`, 'success');
                showToast('Term updated');
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
            } catch (err) {
                console.error('Failed to fetch video status:', err);
            }
        }

        // ============================================================================
        // Custom Terms (Find & Replace)
        // ============================================================================

        async function addCustomTerm() {
            if (!currentVideoId) {
                showToast('Please upload a file first');
                return;
            }

            const originalInput = document.getElementById('customOriginal');
            const translatedInput = document.getElementById('customTranslated');
            const original = originalInput.value.trim();
            const translated = translatedInput.value.trim();

            if (!original || !translated) {
                showToast('Please enter both original and translated terms');
                return;
            }

            try {
                const response = await fetch(`/terms/video/${currentVideoId}/custom`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ original_term: original, translated_term: translated })
                });

                if (response.ok) {
                    log(`Added custom term: "${original}" → "${translated}"`, 'success');
                    showToast('Custom term added');
                    originalInput.value = '';
                    translatedInput.value = '';
                    renderTerms(); // Refresh the terms table
                } else {
                    const err = await response.json();
                    throw new Error(err.detail || 'Failed to add term');
                }
            } catch (err) {
                log('Failed to add custom term: ' + err.message, 'error');
                showToast('Error: ' + err.message);
            }
        }

        async function deleteCustomTerm(termId) {
            if (!confirm('Are you sure you want to remove this custom term?')) return;

            try {
                const response = await fetch(`/terms/video/${currentVideoId}/custom/${termId}`, {
                    method: 'DELETE'
                });

                if (response.ok) {
                    log('Custom term removed', 'success');
                    showToast('Custom term removed');
                    renderTerms(); // Refresh the terms table
                } else {
                    const err = await response.json();
                    throw new Error(err.detail || 'Failed to remove term');
                }
            } catch (err) {
                log('Failed to remove custom term: ' + err.message, 'error');
                showToast('Error: ' + err.message);
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
                    showToast('Transcription complete!');
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
                    showToast('Analysis complete!');
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
                    showToast('Translation complete!');
                    updateButtonVisibility('completed');
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
                showToast(`Failed: ${errorMsg}`, 'error');
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
                log(logMessage);
            }
            
            // Status Transition Guard: only mark after we see a processing state
            if (['queued', 'extracting_audio', 'transcribing', 'analyzing', 'glossary_extracting', 'translating'].includes(status)) {
                hasStartedProcessing = true;
            }
            
            // Handle specific statuses
            switch (status) {
                case 'queued':
                    log('Job queued - waiting for available worker...');
                    showToast('Job queued, waiting to start...');
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
                    showToast('Transcription complete!');
                    updateButtonVisibility('transcribed');
                    break;
                    
                case 'analyzing':
                    log('Director Agent: Analyzing content...');
                    break;
                    
                case 'context_ready':
                    log(`Director Agent complete: ${data.tone} tone`, 'success');
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
                    showToast('Terms ready!');
                    updateButtonVisibility('terms_ready');
                    break;
                    
                case 'translating':
                    log('Translating...');
                    break;
                    
                case 'completed':
                    if (isJobRunning && hasStartedProcessing) {
                        log('Translation complete!', 'success');
                        isJobRunning = false;
                        hasStartedProcessing = false;
                    }
                    renderTerms();
                    showToast('Translation finished!');
                    updateButtonVisibility('completed');
                    break;
                    
                case 'error':
                    log(`Error: ${data.message || data.error}`, 'error');
                    showToast(data.message || 'Error occurred', 'error');
                    break;
            }
            
            // Handle job retry messages
            if (data.type === 'job_retry') {
                log(`Retrying: ${data.job_type} (${data.retry_count}/${data.max_retries})`);
                showToast(`Retrying... (${data.retry_count}/${data.max_retries})`);
            }
        }
        
        function updateButtonVisibility(status) {
            const transcribeBtn = document.getElementById('transcribeBtn');
            const downloadTranscriptionBtn = document.getElementById('downloadTranscriptionBtn');
            const analyzeBtn = document.getElementById('analyzeBtn');
            const translateBtn = document.getElementById('translateBtn');
            const exportSection = document.getElementById('exportSection');
            
            // Hide all first
            transcribeBtn?.classList.add('hidden');
            downloadTranscriptionBtn?.classList.add('hidden');
            analyzeBtn?.classList.add('hidden');
            translateBtn?.classList.add('hidden');
            exportSection?.classList.add('hidden');
            
            // Show based on status
            switch (status) {
                case 'uploaded':
                    transcribeBtn?.classList.remove('hidden');
                    break;
                case 'transcribed':
                    downloadTranscriptionBtn?.classList.remove('hidden');
                    analyzeBtn?.classList.remove('hidden');
                    break;
                case 'terms_ready':
                    translateBtn?.classList.remove('hidden');
                    break;
                case 'completed':
                    exportSection?.classList.remove('hidden');
                    break;
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
                    }
                } catch (err) {
                    console.error('Fallback poll error:', err);
                }
            }, 5000);
        }

        // Upload handler
        async function uploadFile() {
            const fileInput = document.getElementById('fileInput');
            const targetLangSelect = document.getElementById('targetLanguage');
            const sourceLangSelect = document.getElementById('sourceLanguage');
            
            if (!fileInput.files || !fileInput.files[0]) {
                showToast('Please select a file', 'error');
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
                document.getElementById('projectTitle').textContent = data.filename || 'Untitled Project';
                document.getElementById('projectType').innerHTML = 
                    `<i class="fa-solid ${currentFileType === 'text' ? 'fa-file-lines' : 'fa-video'} mr-1"></i>${currentFileType === 'text' ? 'Text File' : 'Video'}`;
                
                const sourceLang = document.getElementById('sourceLanguage').value === 'auto' ? 'Auto' : 
                    document.getElementById('sourceLanguage').value.toUpperCase();
                const targetLang = document.getElementById('targetLanguage').value.toUpperCase();
                document.getElementById('projectLangs').textContent = `${sourceLang} → ${targetLang}`;
                document.getElementById('projectId').textContent = currentVideoId.substring(0, 8);
                
                document.getElementById('statusCard').classList.remove('hidden');
                
                log('Upload complete: ' + data.filename, 'success');
                showToast('File uploaded successfully');
                
                updateStatus({ status: 'uploaded', progress_percent: 0 });
                
            } catch (err) {
                const errorMsg = err.message || 'Upload failed';
                log('Upload failed: ' + errorMsg, 'error');
                showToast('Upload failed: ' + errorMsg, 'error');
            }
        }

        // Process file handler (handles both video transcription and text parsing)
        async function processFile() {
            if (!currentVideoId) return;
            
            // Clear log and reset state for new job
            clearActivityLog();
            currentJobId = `transcribe-${currentVideoId}-${Date.now()}`;
            isJobRunning = true;
            hasStartedProcessing = false;
            
            const isTextFile = currentFileType === 'text';
            const actionName = isTextFile ? 'parsing text' : 'transcription';
            
            log(isTextFile ? 'Starting text parsing...' : 'Starting Whisper transcription...');
            
            try {
                const engine = document.getElementById('transcriptionEngine').value;
            const response = await fetch(`/videos/${currentVideoId}/transcribe?method=whisper&provider=${engine}`, {
                    method: 'POST'
                });
                
                if (!response.ok) throw new Error(isTextFile ? 'Text parsing failed' : 'Transcription failed');
                
                const data = await response.json();
                showToast(isTextFile ? 'Text parsed!' : 'Transcription complete!');
                
                // Update UI silently — completion will be logged via WebSocket
                updateStatus({ status: 'transcribed', total_segments: data.total_segments ?? 0 });
                document.getElementById('segmentCount').textContent = data.total_segments ?? 0;
                
                // Show analyze button
                updateButtonVisibility('transcribed');
                
                // Connect WebSocket for future updates
                connectWebSocket(currentVideoId);
                
            } catch (err) {
                log((isTextFile ? 'Parsing' : 'Transcription') + ' failed: ' + err.message, 'error');
                showToast(isTextFile ? 'Text parsing failed' : 'Transcription failed', 'error');
            }
        }

        // Analyze handler (Multi-Agent Step 1)
        async function analyzeVideo() {
            if (!currentVideoId) return;
            
            // Clear log and reset state for new job
            clearActivityLog();
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
                showToast(`${data.terms_extracted} terms ready for review!`);
                
                // Update UI silently — completion will be logged via WebSocket
                updateStatus({ status: 'terms_ready' });
                updateButtonVisibility('terms_ready');
                
                // Render terms
                await renderTerms();
                
            } catch (err) {
                log('Analysis failed: ' + err.message, 'error');
                showToast('Analysis failed', 'error');
            }
        }

        // Translate handler (Multi-Agent Step 2)
        async function translateVideo() {
            if (!currentVideoId) return;
            
            // Clear log and reset state for new job
            clearActivityLog();
            currentJobId = `translate-${currentVideoId}-${Date.now()}`;
            isJobRunning = true;
            hasStartedProcessing = false;
            
            log('Starting Translator Agent...');
            log('Using sliding window translation with glossary constraints');
            
            try {
                const response = await fetch(`/videos/${currentVideoId}/translate`, {
                    method: 'POST'
                });
                
                if (!response.ok) {
                    const err = await response.json();
                    throw new Error(err.detail || 'Translation failed');
                }
                
                showToast('Translation finished!');
                
                // Update UI silently — completion will be logged via WebSocket
                updateStatus({ status: 'completed' });
                updateButtonVisibility('completed');
                
            } catch (err) {
                log('Translation failed: ' + err.message, 'error');
                showToast('Translation failed', 'error');
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
                showToast(`${formatNames[format]} downloaded`);
                
            } catch (err) {
                log('Export failed: ' + err.message, 'error');
                showToast('Export failed', 'error');
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
                showToast('Transcription downloaded');
                
            } catch (err) {
                log('Download failed: ' + err.message, 'error');
                showToast('Download failed', 'error');
            }
        }

        // Event listeners
        document.addEventListener('DOMContentLoaded', () => {
            // File input
            const fileInput = document.getElementById('fileInput');
            const fileLabel = document.getElementById('fileLabel');
            
            fileInput.addEventListener('change', () => {
                if (fileInput.files && fileInput.files[0]) {
                    const file = fileInput.files[0];
                    fileLabel.textContent = file.name;
                    document.getElementById('dropZone').classList.add('border-blue-400', 'bg-blue-50');
                    
                    // Detect file type and update button text
                    const isTextFile = file.name.toLowerCase().endsWith('.txt');
                    currentFileType = isTextFile ? 'text' : 'video';
                    
                    const transcribeBtnText = document.getElementById('transcribeBtnText');
                    if (transcribeBtnText) {
                        transcribeBtnText.textContent = isTextFile ? 'Parse Text' : 'Transcribe';
                    }
                }
            });

            // Buttons
            document.getElementById('uploadBtn').addEventListener('click', uploadFile);
            document.getElementById('transcribeBtn').addEventListener('click', processFile);
            document.getElementById('downloadTranscriptionBtn').addEventListener('click', downloadTranscription);
            document.getElementById('analyzeBtn').addEventListener('click', analyzeVideo);
            document.getElementById('translateBtn').addEventListener('click', translateVideo);
            document.getElementById('exportSrtBtn').addEventListener('click', () => exportFormat('srt'));
            document.getElementById('exportVttBtn').addEventListener('click', () => exportFormat('vtt'));
            document.getElementById('exportTxtBtn').addEventListener('click', () => exportFormat('txt'));
            document.getElementById('exportJsonBtn').addEventListener('click', () => exportFormat('json'));   

            // Check for video ID in URL
            const videoId = new URLSearchParams(window.location.search).get('video');
            if (videoId) {
                currentVideoId = videoId;
                document.getElementById('videoIdShort').textContent = videoId.substring(0, 8);
                document.getElementById('statusCard').classList.remove('hidden');
                
                // Connect WebSocket for real-time updates
                connectWebSocket(videoId);
                
                // Fetch current status
                fetch(`/videos/${videoId}`)
                    .then(r => r.json())
                    .then(data => {
                        updateStatus(data);
                        updateButtonVisibility(data.status);
                        if (data.total_segments) {
                            document.getElementById('segmentCount').textContent = data.total_segments;
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
