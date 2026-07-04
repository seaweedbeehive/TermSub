/**
 * Job session persistence layer.
 *
 * Saves the current job state to localStorage so users can refresh or navigate
 * back without losing their place. Large result payloads (transcription/
 * translation) are only cached when small; otherwise only the jobId is kept and
 * the data is re-fetched from the backend on restore.
 */

(function () {
    const STORAGE_KEY = 'termsub_current_job';
    const MAX_STORAGE_BYTES = 4 * 1024 * 1024; // 4 MB safety margin under 5 MB

    function getByteSize(str) {
        try {
            return new Blob([str]).size;
        } catch {
            return str.length * 2;
        }
    }

    function now() {
        return new Date().toISOString();
    }

    function loadSession() {
        try {
            const raw = localStorage.getItem(STORAGE_KEY);
            if (!raw) return null;
            return JSON.parse(raw);
        } catch (err) {
            console.error('[jobSession] Failed to load session:', err);
            return null;
        }
    }

    function saveSession(payload) {
        try {
            const existing = loadSession() || {};
            const session = {
                ...existing,
                ...payload,
                config: {
                    ...(existing.config || {}),
                    ...(payload.config || {}),
                },
                savedAt: now(),
            };

            // Avoid duplicating large segment arrays in localStorage. If the
            // serialized session exceeds the safety limit, strip result bodies
            // and keep only jobId/config so restoration can re-fetch from API.
            const candidate = JSON.stringify(session);
            if (getByteSize(candidate) > MAX_STORAGE_BYTES) {
                console.warn('[jobSession] Session too large; stripping results, will re-fetch.');
                delete session.transcriptionResult;
                delete session.translationResult;
                delete session.srtContent;
            }

            localStorage.setItem(STORAGE_KEY, JSON.stringify(session));
            return session;
        } catch (err) {
            console.error('[jobSession] Failed to save session:', err);
            return null;
        }
    }

    function clearSession() {
        try {
            localStorage.removeItem(STORAGE_KEY);
        } catch (err) {
            console.error('[jobSession] Failed to clear session:', err);
        }
    }

    function saveConfig(jobId, config) {
        return saveSession({
            jobId,
            currentStep: 1,
            config,
        });
    }

    function saveTranscription(jobId, transcriptionResult) {
        return saveSession({
            jobId,
            currentStep: 2,
            transcriptionResult,
        });
    }

    function saveTranslation(jobId, translationResult) {
        return saveSession({
            jobId,
            currentStep: 3,
            translationResult,
        });
    }

    function markDownloaded() {
        clearSession();
    }

    // Expose a minimal API on window so the rest of the vanilla JS app can use
    // it without a module loader.
    window.jobSession = {
        STORAGE_KEY,
        loadSession,
        saveSession,
        saveConfig,
        saveTranscription,
        saveTranslation,
        markDownloaded,
        clearSession,
    };
})();
