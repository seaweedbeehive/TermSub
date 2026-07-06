/**
 * Job session persistence layer.
 *
 * Stores only lightweight job configuration and the job id. All heavy state
 * (segments, terms, results) is fetched fresh from the backend on restore.
 */

(function () {
    const STORAGE_KEY = 'termsub_current_job';

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
            const session = {
                jobId: payload.jobId,
                config: payload.config || {},
                savedAt: now(),
            };
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
        return saveSession({ jobId, config });
    }

    function markDownloaded() {
        const session = loadSession();
        if (!session) return;
        session.config = { ...(session.config || {}), downloaded: true };
        session.savedAt = now();
        localStorage.setItem(STORAGE_KEY, JSON.stringify(session));
    }

    // Expose a minimal API on window so the rest of the vanilla JS app can use
    // it without a module loader.
    window.jobSession = {
        STORAGE_KEY,
        loadSession,
        saveSession,
        saveConfig,
        markDownloaded,
        clearSession,
    };
})();
