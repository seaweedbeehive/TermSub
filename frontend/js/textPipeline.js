/**
 * Text-only translation pipeline UI module.
 *
 * Handles: parse completion → term extraction → term review → translation →
 * side-by-side editing → TXT download.
 *
 * Depends on helper functions exposed by main.js:
 *   window.updateStatus, window.log, window.showToast, window.escapeHtml
 */

(function () {
    'use strict';

    let activeVideoId = null;
    let isTextMode = false;
    let hasExtractedTerms = false;
    let _lastStatus = 'uploaded';

    // ------------------------------------------------------------------
    // DOM helpers
    // ------------------------------------------------------------------
    function $(id) { return document.getElementById(id); }
    function hide(id) { const el = $(id); if (el) el.classList.add('hidden'); }
    function show(id) { const el = $(id); if (el) el.classList.remove('hidden'); }

    function setPrimaryButton(label, className, onClick) {
        const btn = $('primaryActionBtn');
        if (!btn) return;
        btn.innerHTML = label;
        btn.className = className ||
            'w-full py-3 px-4 bg-blue-600 hover:bg-blue-700 text-white text-sm font-normal rounded-xl transition-colors tracking-wide';
        btn.onclick = onClick || null;
        show('primaryActionContainer');
        btn.classList.remove('hidden');
    }

    function hidePrimaryButton() {
        const btn = $('primaryActionBtn');
        if (btn) btn.classList.add('hidden');
    }

    function setPrimaryGhost(text, onClick) {
        const ghost = $('primaryGhostLink');
        const link = $('downloadRawTranscriptionLink');
        if (!ghost || !link) return;
        if (text) {
            link.textContent = text;
            link.onclick = onClick || null;
            show('primaryGhostLink');
        } else {
            hide('primaryGhostLink');
        }
    }

    // ------------------------------------------------------------------
    // Status helpers
    // ------------------------------------------------------------------
    function _updateStatus(data) {
        if (data && data.status) _lastStatus = data.status;
        if (window.updateStatus) window.updateStatus(data);
    }

    function _log(message, type) {
        if (window.log) window.log(message, type);
        else console.log(message);
    }

    function _toast(message, type) {
        if (window.showToast) window.showToast(message, type);
        else console.log(message);
    }

    function _escape(text) {
        if (window.escapeHtml) return window.escapeHtml(text);
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    // ------------------------------------------------------------------
    // Public lifecycle
    // ------------------------------------------------------------------
    function setVideoId(videoId) {
        activeVideoId = videoId;
    }

    function setFileType(fileType) {
        isTextMode = fileType === 'text';
    }

    function isActive() {
        return isTextMode && activeVideoId;
    }

    function reset() {
        isTextMode = false;
        activeVideoId = null;
        hasExtractedTerms = false;
        hide('textPreviewPanel');
        hide('textExportPanel');
    }

    // ------------------------------------------------------------------
    // Parse completion
    // ------------------------------------------------------------------
    function onTextParsed(data) {
        if (!activeVideoId) {
            return;
        }
        const status = data.status === 'completed' || data.status === 'awaiting_choice'
            ? 'transcribed'
            : data.status;

        _updateStatus({
            status: status,
            progress_percent: 100,
            total_segments: data.total_segments,
            processed_segments: data.total_segments,
        });

        // Show original text preview.
        fetchTextSegments().then(({ segments }) => {
            if (segments) renderOriginalPreview(segments);
        });

        const reviewTerms = isSkipGlossaryChecked();
        if (reviewTerms) {
            // Auto-advance to term extraction so the user sees terms immediately.
            setPrimaryButton('<i class="fa-solid fa-list-check mr-2"></i>Extracting Terms...', null, null);
            setPrimaryGhost(null);
            startTermExtraction();
        } else {
            setPrimaryButton(
                '<i class="fa-solid fa-language mr-2"></i>Translate Text',
                null,
                startTranslation
            );
            setPrimaryGhost('or download original text', downloadOriginalText);
        }

        show('textPreviewPanel');
        hide('termsPanel');
        hide('subtitleReviewPanel');
        hide('exportPanel');
        hide('exportHeader');
    }

    function isSkipGlossaryChecked() {
        const cb = $('reviewTerminologyCheckbox');
        return cb ? cb.checked : false;
    }

    // ------------------------------------------------------------------
    // Segment / term fetching
    // ------------------------------------------------------------------
    async function fetchTextSegments() {
        const response = await fetch(`/api/text/${activeVideoId}/segments`);
        if (!response.ok) throw new Error('Failed to load text segments');
        return response.json();
    }

    async function fetchTextTerms() {
        const response = await fetch(`/api/text/${activeVideoId}/terms`);
        if (!response.ok) throw new Error('Failed to load text terms');
        return response.json();
    }

    async function refreshVideoStatus() {
        if (!activeVideoId) return;
        try {
            const response = await fetch(`/videos/${activeVideoId}`);
            if (!response.ok) throw new Error('Failed to load video status');
            const data = await response.json();
            if (data.status) updateUI(data.status);
        } catch (err) {
            console.error('[textPipeline] refreshVideoStatus failed:', err);
        }
    }

    // ------------------------------------------------------------------
    // Preview rendering
    // ------------------------------------------------------------------
    function renderOriginalPreview(segments) {
        const el = $('textPreviewOriginal');
        if (!el) return;
        const text = segments.map(s => s.original_text).join('\n\n');
        el.textContent = text || 'No text available yet.';
    }

    function renderSideBySide(segments) {
        const originalEl = $('textPreviewOriginal');
        const translatedEl = $('textPreviewTranslated');
        if (!originalEl || !translatedEl) return;

        originalEl.textContent = segments
            .map(s => s.original_text)
            .join('\n\n');

        translatedEl.textContent = segments
            .map(s => s.translated_text || s.original_text)
            .join('\n\n');

        // Debounced auto-save on edit.
        translatedEl.onblur = () => saveTranslatedText(segments, translatedEl.textContent);
    }

    async function saveTranslatedText(originalSegments, fullText) {
        const parts = fullText.split(/\n\n+/).map(s => s.trim()).filter(Boolean);
        // Match by sequence number; if counts differ, warn but still save best-effort.
        for (let i = 0; i < originalSegments.length; i++) {
            const segment = originalSegments[i];
            const newText = parts[i] || segment.translated_text || segment.original_text;
            if (newText !== segment.translated_text) {
                await updateSegment(segment.id, newText);
            }
        }
        _toast('Translation edits saved', 'success');
    }

    async function updateSegment(segmentId, value) {
        const response = await fetch(`/api/text/${activeVideoId}/segments/${segmentId}`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ translated_text: value }),
        });
        if (!response.ok) throw new Error('Failed to update segment');
    }

    // ------------------------------------------------------------------
    // Term extraction
    // ------------------------------------------------------------------
    async function startTermExtraction() {
        if (!activeVideoId) {
            return;
        }
        _log('Starting text terminology extraction...');
        try {
            const response = await fetch(`/api/text/${activeVideoId}/extract-terms`, {
                method: 'POST',
            });
            const data = await response.json();
            if (!response.ok) throw new Error(data.detail || 'Extraction failed');

            _log(`Terminology extraction queued (${data.job_id})`, 'success');
            hidePrimaryButton();
            setPrimaryGhost(null);
        } catch (err) {
            _log('Terminology extraction failed: ' + err.message, 'error');
            _toast('Terminology extraction failed', 'error');
        }
    }

    // ------------------------------------------------------------------
    // Term rendering / editing
    // ------------------------------------------------------------------
    async function renderTerms() {
        const tbody = $('termsTable');
        const countBadge = $('termsCount');
        if (!tbody) return;

        try {
            const { terms } = await fetchTextTerms();
            if (!terms || terms.length === 0) {
                tbody.innerHTML = '<tr><td colspan="4" class="px-3 py-8 text-center text-slate-400 text-sm">No terms extracted yet.</td></tr>';
                if (countBadge) countBadge.classList.add('hidden');
                return;
            }

            if (countBadge) {
                countBadge.textContent = terms.length.toString();
                countBadge.classList.remove('hidden');
            }

            tbody.innerHTML = terms.map(term => {
                const cleanTranslation = (term.translated_term || '')
                    .replace(/^\[.*?\]\s*/, '');
                const displayCategory = (term.category || 'General')
                    .replace(/_/g, ' ')
                    .replace(/\b\w/g, c => c.toUpperCase());
                return `
                    <tr class="hover:bg-slate-50 dark:hover:bg-[#1A1A1E] ${term.source === 'manual' ? 'bg-amber-50/50 dark:bg-amber-900/20' : ''}">
                        <td class="px-3 py-2">
                            <span class="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-semibold uppercase tracking-wide bg-slate-100 dark:bg-[#2A2A30] text-slate-600 dark:text-[#8A8F98]">
                                ${_escape(displayCategory)}
                            </span>
                        </td>
                        <td class="px-3 py-2 font-medium text-slate-900 dark:text-[#E2E2E8]">${_escape(term.original_term)}</td>
                        <td class="px-3 py-2 text-slate-600 dark:text-[#8A8F98] rtl-text">${_escape(cleanTranslation)}</td>
                        <td class="px-3 py-2">
                            <div class="flex items-center gap-2">
                                <input type="text" value="${_escape(term.standardized_term || '')}"
                                    onchange="textPipeline.updateTerm('${term.id}', this.value)"
                                    class="flex-1 border-transparent bg-slate-50/50 dark:bg-[#2A2A30]/70 hover:bg-slate-100/70 dark:hover:bg-[#2A2A30] focus:bg-white dark:focus:bg-[#1A1A1E] focus:border-slate-300 dark:focus:border-[#3A3A42] focus:ring-1 focus:ring-slate-300 dark:focus:ring-[#3A3A42] text-slate-900 dark:text-[#E2E2E8] placeholder-slate-400 dark:placeholder-[#6B7280] transition-all rounded px-2 py-1 text-xs">
                            </div>
                        </td>
                    </tr>
                `;
            }).join('');
        } catch (err) {
            console.error('Failed to render text terms:', err);
        }
    }

    async function updateTerm(termId, value) {
        try {
            const response = await fetch(`/api/text/terms/${termId}`, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ standardized_term: value }),
            });
            if (!response.ok) throw new Error('Term update failed');
            _log(`Updated term ${termId.substring(0, 8)}...`, 'success');
            _toast('Term updated successfully', 'success');
        } catch (err) {
            _log('Failed to update term: ' + err.message, 'error');
            _toast('Failed to update term', 'error');
        }
    }

    // ------------------------------------------------------------------
    // Translation
    // ------------------------------------------------------------------
    async function startTranslation() {
        if (!activeVideoId) {
            return;
        }
        _log('Starting text translation...');
        try {
            const response = await fetch(`/api/text/${activeVideoId}/translate`, {
                method: 'POST',
            });
            const data = await response.json();
            if (!response.ok) throw new Error(data.detail || 'Translation failed');

            _log(`Text translation queued (${data.job_id})`, 'success');
            hidePrimaryButton();
            setPrimaryGhost(null);
        } catch (err) {
            _log('Text translation failed: ' + err.message, 'error');
            _toast('Text translation failed', 'error');
        }
    }

    // ------------------------------------------------------------------
    // Status-driven UI updates
    // ------------------------------------------------------------------
    async function updateUI(status) {
        if (!isActive()) return;

        const data = await fetchTextSegments();
        const segments = data.segments || [];

        switch (status) {
            case 'transcribed':
                // Render the text preview and primary action without re-running
                // the full parse completion handler (which would recurse via
                // main.js updateStatus -> updateButtonVisibility).
                renderOriginalPreview(segments);
                const reviewTerms = isSkipGlossaryChecked();
                if (reviewTerms) {
                    setPrimaryButton('<i class="fa-solid fa-list-check mr-2"></i>Extract Terms', null, startTermExtraction);
                    setPrimaryGhost('or download original text', downloadOriginalText);
                } else {
                    setPrimaryButton(
                        '<i class="fa-solid fa-language mr-2"></i>Translate Text',
                        null,
                        startTranslation
                    );
                    setPrimaryGhost('or download original text', downloadOriginalText);
                }
                show('textPreviewPanel');
                hide('termsPanel');
                hide('subtitleReviewPanel');
                hide('exportPanel');
                hide('exportHeader');
                break;

            case 'analyzing':
            case 'context_ready':
            case 'glossary_extracting':
                hidePrimaryButton();
                hide('termsPanel');
                hide('subtitleReviewPanel');
                show('textPreviewPanel');
                renderOriginalPreview(segments);
                break;

            case 'terms_ready':
                hasExtractedTerms = true;
                hide('subtitleReviewPanel');
                hide('textPreviewPanel');
                show('termsPanel');
                await renderTerms();
                setPrimaryButton(
                    '<i class="fa-solid fa-language mr-2"></i>Translate Text',
                    null,
                    startTranslation
                );
                break;

            case 'translating':
                hidePrimaryButton();
                hide('termsPanel');
                hide('subtitleReviewPanel');
                show('textPreviewPanel');
                renderSideBySide(segments);
                break;

            case 'completed':
                hidePrimaryButton();
                hide('termsPanel');
                hide('subtitleReviewPanel');
                show('textPreviewPanel');
                renderSideBySide(segments);
                show('exportPanel');
                show('textExportPanel');
                show('exportHeader');
                const exportHeader = $('exportHeader');
                if (exportHeader) exportHeader.textContent = 'Download Translation';
                break;

            case 'error':
                hidePrimaryButton();
                break;
        }
    }

    function handleStatusUpdate(payload) {
        if (!isActive()) return;

        if (payload.type === 'job_complete') {
            const jobType = payload.job_type || '';
            if (jobType === 'text_analyze') {
                _log('Terminology extraction complete', 'success');
            } else if (jobType === 'text_translate') {
                _log('Text translation complete', 'success');
            }
            refreshVideoStatus();
            return;
        }

        if (payload.type === 'job_error') {
            _log((payload.job_type || 'Task') + ' failed: ' + (payload.error || 'Unknown error'), 'error');
            return;
        }

        // status/progress payload
        if (payload.status) {
            updateUI(payload.status);
        }
    }

    // ------------------------------------------------------------------
    // Downloads
    // ------------------------------------------------------------------
    async function downloadText() {
        if (!activeVideoId) return;
        try {
            const response = await fetch(`/api/text/${activeVideoId}/export`, {
                method: 'POST',
            });
            if (!response.ok) throw new Error('Export failed');

            const blob = await response.blob();
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            const disposition = response.headers.get('Content-Disposition');
            const match = disposition && disposition.match(/filename="([^"]+)"/);
            a.download = match ? match[1] : 'translation.txt';
            document.body.appendChild(a);
            a.click();
            a.remove();
            URL.revokeObjectURL(url);
            _toast('Translation downloaded', 'success');
        } catch (err) {
            _log('Download failed: ' + err.message, 'error');
            _toast('Download failed', 'error');
        }
    }

    async function downloadOriginalText() {
        if (!activeVideoId) return;
        // Reuse the existing export endpoint for original text.
        try {
            const response = await fetch(`/export/${activeVideoId}/transcription`, {
                method: 'GET',
            });
            if (!response.ok) throw new Error('Original text download failed');
            const blob = await response.blob();
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            const disposition = response.headers.get('Content-Disposition');
            const match = disposition && disposition.match(/filename="([^"]+)"/);
            a.download = match ? match[1] : 'original.txt';
            document.body.appendChild(a);
            a.click();
            a.remove();
            URL.revokeObjectURL(url);
        } catch (err) {
            _log('Original text download failed: ' + err.message, 'error');
        }
    }

    // Wire the TXT-only export button.
    document.addEventListener('DOMContentLoaded', () => {
        const btn = $('exportTxtOnlyBtn');
        if (btn) btn.addEventListener('click', downloadText);
    });

    // ------------------------------------------------------------------
    // Expose public API
    // ------------------------------------------------------------------
    window.textPipeline = {
        setVideoId,
        setFileType,
        isActive,
        reset,
        onTextParsed,
        startTermExtraction,
        startTranslation,
        renderTerms,
        updateTerm,
        renderSideBySide,
        updateSegment,
        downloadText,
        downloadOriginalText,
        updateUI,
        handleStatusUpdate,
    };
})();
