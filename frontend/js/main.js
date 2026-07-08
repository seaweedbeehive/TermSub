        // State
        let currentVideoId = null;
        let videoProgressPercent = 0;  // Track progress for WebSocket updates
        let currentFileType = 'video'; // 'video' or 'text' - tracks uploaded file type
        let currentContentType = 'video'; // backend content_type value
        let loggedCompletions = new Set(); // Track completed jobs to prevent duplicate logs
        let currentJobId = null; // Track current job to ignore stale messages
        let isJobRunning = false; // Silver bullet: prevents stale completion logs
        let hasStartedProcessing = false; // Status Transition Guard: ignore COMPLETED until processing starts
        let isSavingSegment = false; // Prevents concurrent blur / replace-all race conditions
        let timelineHistory = [];    // Stack of segment snapshots for undo
        let currentTimelineSegments = []; // Last rendered segment state
        let targetPipelineMode = null; // 'transcribe' | 'terminology' | 'subtitles' | null
        const MAX_TIMELINE_HISTORY = 20;

        // ------------------------------------------------------------------
        // Authentication
        // ------------------------------------------------------------------
        const API_KEY_KEY = 'termsub_api_key';
        const EMAIL_KEY = 'termsub_email';
        let currentUser = null;
        let currentAuthTab = 'standard';
        let currentStandardMode = 'signup';
        let currentAuthSubview = 'form'; // 'form' | 'forgot' | 'reset'

        function getApiKey() {
            return localStorage.getItem(API_KEY_KEY) || '';
        }

        function setApiKey(apiKey) {
            localStorage.setItem(API_KEY_KEY, apiKey);
        }

        function clearApiKey() {
            localStorage.removeItem(API_KEY_KEY);
        }

        function getStoredEmail() {
            return localStorage.getItem(EMAIL_KEY) || '';
        }

        function setStoredEmail(email) {
            if (email) localStorage.setItem(EMAIL_KEY, email);
        }

        function clearStoredEmail() {
            localStorage.removeItem(EMAIL_KEY);
        }

        function maskEmail(email) {
            if (!email || !email.includes('@')) return 'your email';
            const [localPart, domain] = email.split('@');
            const maskedLocal = localPart.length > 1
                ? localPart[0] + '*'.repeat(localPart.length - 1)
                : '*';
            return `${maskedLocal}@${domain}`;
        }

        function setupPasswordToggles() {
            document.addEventListener('click', (event) => {
                const toggleBtn = event.target.closest('[data-toggle-password]');
                if (!toggleBtn) return;

                const inputId = toggleBtn.getAttribute('data-toggle-password');
                const input = document.getElementById(inputId);
                if (!input) return;

                const isHidden = input.type === 'password';
                input.type = isHidden ? 'text' : 'password';
                toggleBtn.textContent = isHidden ? 'Hide' : 'Show';
            });
        }

        function isStandardLoggedIn() {
            return currentUser !== null && !isByokMode();
        }

        function isByokMode() {
            return !!getApiKey();
        }

        function isAuthenticated() {
            return isStandardLoggedIn() || isByokMode();
        }

        // Patch global fetch to attach the BYOK API key to same-origin API calls.
        // Standard auth is handled automatically via the HttpOnly cookie.
        (function patchFetch() {
            const originalFetch = window.fetch;
            window.fetch = async function(input, init) {
                const url = typeof input === 'string' ? input : input.url || input.toString();
                const isSameOrigin = url.startsWith('/') || url.startsWith(window.location.origin);
                if (isSameOrigin) {
                    init = init || {};
                    const headers = new Headers(init.headers || {});
                    const apiKey = getApiKey();
                    if (apiKey && !headers.has('X-API-Key')) {
                        headers.set('X-API-Key', apiKey);
                    }
                    init.headers = headers;
                }
                return originalFetch(input, init);
            };
        })();

        // ------------------------------------------------------------------
        // Admin Dashboard
        // ------------------------------------------------------------------
        let adminData = { stats: null, users: [], subscribers: [] };

        function showAdminError(message) {
            const el = document.getElementById('adminError');
            if (!el) return;
            el.textContent = message;
            el.classList.remove('hidden');
        }

        function hideAdminError() {
            const el = document.getElementById('adminError');
            if (!el) return;
            el.classList.add('hidden');
        }

        function minutesProgressColor(minutes) {
            if (minutes < 20) return 'bg-emerald-500';
            if (minutes <= 27) return 'bg-amber-500';
            return 'bg-red-500';
        }

        function renderAdminStats() {
            const stats = adminData.stats || {};
            const totalUsersEl = document.getElementById('adminStatTotalUsers');
            const newUsersEl = document.getElementById('adminStatNewUsers');
            const newsletterEl = document.getElementById('adminStatNewsletter');
            const uploadsEl = document.getElementById('adminStatUploads');
            if (totalUsersEl) totalUsersEl.textContent = stats.total_users ?? '-';
            if (newUsersEl) newUsersEl.textContent = stats.new_users_today ?? '-';
            if (newsletterEl) newsletterEl.textContent = stats.newsletter_subscribers ?? '-';
            if (uploadsEl) uploadsEl.textContent = stats.uploads_today ?? '-';
        }

        function renderAdminUsers() {
            const tbody = document.getElementById('adminUsersTable');
            if (!tbody) return;
            if (!adminData.users.length) {
                tbody.innerHTML = `<tr><td colspan="6" class="px-4 py-8 text-center text-slate-400 dark:text-[#6B7280]">No users found.</td></tr>`;
                return;
            }
            tbody.innerHTML = adminData.users.map(user => {
                const minutes = user.minutes_used ?? 0;
                const pct = Math.min(100, Math.max(0, (minutes / 30) * 100));
                const barColor = minutesProgressColor(minutes);
                const joined = user.created_at
                    ? new Date(user.created_at).toLocaleDateString()
                    : '-';
                const adminBadge = user.is_admin
                    ? '<span class="inline-flex items-center px-2 py-0.5 rounded text-[10px] font-medium bg-purple-100 dark:bg-purple-900/30 text-purple-700 dark:text-purple-300">Admin</span>'
                    : '<span class="inline-flex items-center px-2 py-0.5 rounded text-[10px] font-medium bg-slate-100 dark:bg-[#2A2A30] text-slate-600 dark:text-[#8A8F98]">User</span>';
                const modeClass = user.api_key_mode === 'byok'
                    ? 'bg-slate-800 text-white dark:bg-[#2A2A30] dark:text-[#E2E2E8]'
                    : 'bg-blue-600 text-white dark:bg-blue-600 dark:text-white';
                return `
                    <tr class="hover:bg-slate-50 dark:hover:bg-[#121214] transition-colors">
                        <td class="px-4 py-3 text-slate-900 dark:text-[#E2E2E8] font-medium">${escapeHtml(user.email)}</td>
                        <td class="px-4 py-3 text-slate-600 dark:text-[#8A8F98]">${joined}</td>
                        <td class="px-4 py-3">
                            <span class="inline-flex items-center px-2 py-0.5 rounded text-[10px] font-medium uppercase ${modeClass}">${user.api_key_mode}</span>
                        </td>
                        <td class="px-4 py-3 w-48">
                            <div class="flex items-center gap-2">
                                <div class="flex-1 h-2 bg-slate-100 dark:bg-[#2A2A30] rounded-full overflow-hidden">
                                    <div class="h-full ${barColor} rounded-full" style="width: ${pct}%"></div>
                                </div>
                                <span class="text-xs text-slate-600 dark:text-[#8A8F98] whitespace-nowrap">${minutes.toFixed(1)}/30</span>
                            </div>
                        </td>
                        <td class="px-4 py-3">${adminBadge}</td>
                        <td class="px-4 py-3">
                            <div class="flex items-center gap-2">
                                <button data-admin-action="reset-quota" data-user-id="${user.id}" class="px-2 py-1 text-xs font-medium rounded bg-slate-100 dark:bg-[#2A2A30] hover:bg-slate-200 dark:hover:bg-[#3A3A40] text-slate-700 dark:text-[#E2E2E8] transition-colors">Reset Quota</button>
                                <button data-admin-action="toggle-mode" data-user-id="${user.id}" class="px-2 py-1 text-xs font-medium rounded bg-slate-100 dark:bg-[#2A2A30] hover:bg-slate-200 dark:hover:bg-[#3A3A40] text-slate-700 dark:text-[#E2E2E8] transition-colors">Toggle Mode</button>
                            </div>
                        </td>
                    </tr>
                `;
            }).join('');
        }

        function renderAdminSubscribers() {
            const container = document.getElementById('adminNewsletterList');
            if (!container) return;
            if (!adminData.subscribers.length) {
                container.innerHTML = '<span class="text-sm text-slate-400 dark:text-[#6B7280]">No subscribers found.</span>';
                return;
            }
            container.innerHTML = adminData.subscribers.map(sub => `
                <span class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-slate-50 dark:bg-[#121214] border border-slate-200 dark:border-[#2A2A30] text-xs text-slate-700 dark:text-[#E2E2E8]">
                    ${escapeHtml(sub.email)}
                    <span class="text-[10px] uppercase tracking-wider text-slate-400 dark:text-[#6B7280]">${sub.source}</span>
                </span>
            `).join('');
        }

        async function loadAdminDashboard() {
            hideAdminError();

            try {
                const [statsRes, usersRes, subsRes] = await Promise.all([
                    fetch('/api/admin/stats'),
                    fetch('/api/admin/users'),
                    fetch('/api/auth/newsletter-signups')
                ]);

                if (statsRes.status === 401 || statsRes.status === 403 ||
                    usersRes.status === 401 || usersRes.status === 403 ||
                    subsRes.status === 401 || subsRes.status === 403) {
                    redirectToHome('Admin access denied');
                    return;
                }

                if (!statsRes.ok || !usersRes.ok || !subsRes.ok) {
                    const detail = await statsRes.text().catch(() => 'Admin request failed');
                    throw new Error(detail || 'Admin request failed');
                }

                adminData.stats = await statsRes.json();
                adminData.users = await usersRes.json();
                adminData.subscribers = await subsRes.json();

                renderAdminStats();
                renderAdminUsers();
                renderAdminSubscribers();
            } catch (err) {
                showAdminError('Failed to load admin data: ' + err.message);
            }
        }

        async function handleAdminAction(action, userId) {
            hideAdminError();
            const endpoint = action === 'reset-quota'
                ? `/api/admin/users/${userId}/reset-quota`
                : `/api/admin/users/${userId}/toggle-mode`;
            try {
                const response = await fetch(endpoint, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' }
                });
                if (response.status === 401 || response.status === 403) {
                    redirectToHome('Admin access denied');
                    return;
                }
                if (!response.ok) {
                    const data = await response.json().catch(() => ({}));
                    throw new Error(data.detail || 'Action failed');
                }
                showToast(action === 'reset-quota' ? 'Quota reset' : 'Mode toggled', 'success');
                await loadAdminDashboard();
            } catch (err) {
                showAdminError('Action failed: ' + err.message);
            }
        }

        function redirectToHome(message) {
            const adminView = document.getElementById('adminView');
            const mainApp = document.getElementById('mainApp');
            if (adminView) adminView.classList.add('hidden');
            if (mainApp) mainApp.classList.remove('hidden');
            window.history.pushState({}, '', '/');
            showToast(message, 'error');
        }

        async function showAdminView() {
            const adminView = document.getElementById('adminView');
            const mainApp = document.getElementById('mainApp');
            const authView = document.getElementById('authView');
            const verifyView = document.getElementById('verifyView');
            if (adminView) adminView.classList.remove('hidden');
            if (mainApp) mainApp.classList.add('hidden');
            if (authView) authView.classList.add('hidden');
            if (verifyView) verifyView.classList.add('hidden');

            if (!isStandardLoggedIn()) {
                redirectToHome('Please log in as an admin');
                return;
            }

            try {
                const response = await fetch('/api/auth/me');
                if (!response.ok) {
                    redirectToHome('Admin access denied');
                    return;
                }
                const user = await response.json();
                if (!user.is_admin) {
                    redirectToHome('Admin access required');
                    return;
                }
                loadAdminDashboard();
            } catch (err) {
                redirectToHome('Could not verify admin access');
            }
        }

        function hideAdminView() {
            const adminView = document.getElementById('adminView');
            const mainApp = document.getElementById('mainApp');
            if (adminView) adminView.classList.add('hidden');
            if (mainApp) mainApp.classList.remove('hidden');
        }

        // Status config with colors
        const statusConfig = {
            uploaded: { label: 'Uploaded', color: 'bg-blue-500/20 text-blue-300', dotColor: 'bg-blue-400' },
            queued: { label: 'Queued', color: 'bg-gray-100 text-gray-700', dotColor: 'bg-gray-400' },
            extracting_audio: { label: 'Extracting Audio', color: 'bg-amber-100 text-amber-800', dotColor: 'bg-amber-500' },
            transcribing: { label: 'Transcribing', color: 'bg-orange-100 text-orange-800', dotColor: 'bg-orange-500' },
            transcribed: { label: 'Transcribed', color: 'bg-blue-100 text-blue-800', dotColor: 'bg-blue-500' },
            analyzing: { label: 'Analyzing', color: 'bg-blue-500/20 text-blue-300', dotColor: 'bg-blue-400' },
            context_ready: { label: 'Context Ready', color: 'bg-blue-500/20 text-blue-300', dotColor: 'bg-blue-400' },
            glossary_extracting: { label: 'Extracting Terms', color: 'bg-yellow-100 text-yellow-800', dotColor: 'bg-yellow-500' },
            terms_ready: { label: 'Terms Ready', color: 'bg-indigo-100 text-indigo-800', dotColor: 'bg-indigo-500' },
            translating: { label: 'Translating via OpenAI', color: 'bg-purple-100 text-purple-800', dotColor: 'bg-purple-500' },
            completed: { label: 'Completed', color: 'bg-emerald-100 text-emerald-800', dotColor: 'bg-emerald-500' },
            error: { label: 'Error', color: 'bg-rose-100 text-rose-800', dotColor: 'bg-rose-500' }
        };

        // Utility functions
        function log(message, type = 'info') {
            const logEl = document.getElementById('activityLog');
            const time = new Date().toLocaleTimeString('en-US', { hour12: false });

            if (logEl.children.length === 1 && logEl.children[0].textContent.includes('Waiting')) {
                logEl.replaceChildren();
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

            const entry = document.createElement('div');
            entry.className = 'flex items-start gap-2 text-slate-300';

            const badge = document.createElement('span');
            badge.className = `shrink-0 mt-0.5 px-1 py-0.5 rounded text-[9px] font-bold uppercase tracking-wide ${cfg.bg} ${cfg.text}`;
            badge.textContent = cfg.label;

            const text = document.createElement('span');
            text.className = 'text-[11px] leading-tight';
            text.textContent = `[${time}] ${message}`;

            entry.appendChild(badge);
            entry.appendChild(text);
            logEl.appendChild(entry);
            logEl.scrollTo({ top: logEl.scrollHeight, behavior: 'smooth' });

            // Mirror critical errors in the normal user-facing status line
            if (type === 'error') {
                updateUserFacingStatus({ status: 'error', message });
            }
        }

        function clearActivityLog() {
            const logEl = document.getElementById('activityLog');
            logEl.replaceChildren();
            loggedCompletions.clear(); // Reset completion tracking
        }

        function expandActivityLog() {
            const container = document.getElementById('activityLogContainer');
            const toggle = document.getElementById('activityLogToggle');
            if (container) container.classList.remove('activity-log-collapsed');
            if (toggle) toggle.setAttribute('aria-expanded', 'true');
        }

        function updateUserFacingStatus(data) {
            const statusBadge = document.getElementById('statusBadge');
            if (!statusBadge) return;

            const isError = data.status === 'error' || !!data.error;

            if (isError) {
                const span = document.createElement('span');
                span.id = 'statusDot';
                span.className = 'w-1.5 h-1.5 rounded-full bg-rose-400';
                statusBadge.replaceChildren();
                statusBadge.appendChild(span);
                statusBadge.appendChild(document.createTextNode('Something went wrong.'));
                const btn = document.createElement('button');
                btn.type = 'button';
                btn.dataset.openActivityLog = '';
                btn.className = 'text-blue-400 hover:text-blue-300 underline ml-1';
                btn.textContent = 'See the description in activity log.';
                statusBadge.appendChild(btn);
                statusBadge.className = 'inline-flex items-center gap-1.5 px-3 py-1.5 bg-rose-500/20 text-rose-300 text-xs font-normal rounded-full';
            } else {
                const cfg = statusConfig[data.status] || statusConfig.uploaded;
                const isProcessing = ['transcribing', 'extracting_audio', 'analyzing', 'glossary_extracting', 'translating', 'queued'].includes(data.status);
                statusBadge.className = `inline-flex items-center gap-1.5 px-3 py-1.5 ${cfg.color} text-xs font-semibold rounded-full transition-colors`;
                statusBadge.innerHTML = `<span id="statusDot" class="w-1.5 h-1.5 rounded-full ${cfg.dotColor} ${isProcessing ? 'pulse-indicator' : ''}"></span>${cfg.label}`;
            }
        }

        function escapeHtml(text) {
            if (!text) return '';
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }

        // ------------------------------------------------------------------
        // Auth UI helpers
        // ------------------------------------------------------------------
        function showAuthView(tab = 'standard', mode = 'signup') {
            currentAuthTab = tab;
            currentStandardMode = mode;
            currentAuthSubview = 'form';
            updateAuthUI();
            setAuthSubview('form');
            const authView = document.getElementById('authView');
            if (authView) authView.classList.remove('hidden');
            const verifyView = document.getElementById('verifyView');
            if (verifyView) verifyView.classList.add('hidden');
            document.body.style.overflow = 'hidden';
        }

        function showMainApp() {
            const authView = document.getElementById('authView');
            if (authView) authView.classList.add('hidden');
            const verifyView = document.getElementById('verifyView');
            if (verifyView) verifyView.classList.add('hidden');
            const mainApp = document.getElementById('mainApp');
            if (mainApp) mainApp.classList.remove('hidden');
            document.body.style.overflow = '';
        }

        function showVerifyView() {
            const authView = document.getElementById('authView');
            if (authView) authView.classList.add('hidden');
            const verifyView = document.getElementById('verifyView');
            if (verifyView) {
                const emailDisplay = document.getElementById('verifyEmailDisplay');
                if (emailDisplay) emailDisplay.textContent = maskEmail(getStoredEmail());
                verifyView.classList.remove('hidden');
            }
            const mainApp = document.getElementById('mainApp');
            if (mainApp) mainApp.classList.add('hidden');
            document.body.style.overflow = '';
        }

        function setAuthTab(tab) {
            currentAuthTab = tab;
            updateAuthUI();
        }

        function setStandardMode(mode) {
            currentStandardMode = mode;
            updateAuthUI();
        }

        function updateAuthUI() {
            const standardTab = document.getElementById('authTabStandard');
            const byokTab = document.getElementById('authTabByok');
            const standardForm = document.getElementById('standardAuthForm');
            const byokForm = document.getElementById('byokAuthForm');
            const submitBtn = document.getElementById('authSubmitBtn');
            const toggleText = document.getElementById('authModeToggleText');
            const toggleBtn = document.getElementById('authModeToggleBtn');
            const wantsUpdatesContainer = document.getElementById('wantsUpdatesContainer');
            const standardTermsContainer = document.getElementById('standardTermsContainer');
            const standardTermsCheckbox = document.getElementById('standardTermsCheckbox');
            const passwordInput = document.getElementById('authPassword');
            const authError = document.getElementById('authError');
            const byokError = document.getElementById('byokError');

            if (authError) authError.classList.add('hidden');
            if (byokError) byokError.classList.add('hidden');

            const activeTabClass = 'bg-white dark:bg-[#1A1A1E] text-slate-900 dark:text-[#E2E2E8] shadow-sm';
            const inactiveTabClass = 'text-slate-600 dark:text-[#8A8F98] hover:text-slate-900 dark:hover:text-[#E2E2E8]';
            if (standardTab) {
                standardTab.className = `flex-1 py-1.5 text-sm font-medium rounded-md transition-colors ${currentAuthTab === 'standard' ? activeTabClass : inactiveTabClass}`;
            }
            if (byokTab) {
                byokTab.className = `flex-1 py-1.5 text-sm font-medium rounded-md transition-colors ${currentAuthTab === 'byok' ? activeTabClass : inactiveTabClass}`;
            }

            if (standardForm) standardForm.classList.toggle('hidden', currentAuthTab !== 'standard');
            if (byokForm) byokForm.classList.toggle('hidden', currentAuthTab !== 'byok');

            const isLogin = currentStandardMode === 'login';
            if (submitBtn) submitBtn.textContent = isLogin ? 'Sign In' : 'Create Free Account';
            if (wantsUpdatesContainer) wantsUpdatesContainer.classList.toggle('hidden', isLogin);
            if (standardTermsContainer) standardTermsContainer.classList.toggle('hidden', isLogin);
            if (standardTermsCheckbox) standardTermsCheckbox.required = !isLogin;
            if (passwordInput) passwordInput.setAttribute('autocomplete', isLogin ? 'current-password' : 'new-password');
            if (toggleText) toggleText.textContent = isLogin ? "Don't have an account?" : 'Already have an account?';
            if (toggleBtn) toggleBtn.textContent = isLogin ? 'Create Free Account' : 'Sign in';
        }

        function setAuthSubview(subview) {
            currentAuthSubview = subview;
            const standardForm = document.getElementById('standardAuthForm');
            const forgotForm = document.getElementById('forgotPasswordForm');
            const resetForm = document.getElementById('resetPasswordForm');
            const byokForm = document.getElementById('byokAuthForm');
            const authTabs = document.getElementById('authTabStandard')?.parentElement;

            if (standardForm) standardForm.classList.toggle('hidden', subview !== 'form' || currentAuthTab !== 'standard');
            if (forgotForm) forgotForm.classList.toggle('hidden', subview !== 'forgot');
            if (resetForm) resetForm.classList.toggle('hidden', subview !== 'reset');
            if (byokForm) byokForm.classList.toggle('hidden', subview !== 'form' || currentAuthTab !== 'byok');
            if (authTabs) authTabs.classList.toggle('hidden', subview !== 'form');

            const authError = document.getElementById('authError');
            const forgotError = document.getElementById('forgotPasswordError');
            const forgotSuccess = document.getElementById('forgotPasswordSuccess');
            const resetError = document.getElementById('resetPasswordError');
            const resetSuccess = document.getElementById('resetPasswordSuccess');
            if (authError) authError.classList.add('hidden');
            if (forgotError) forgotError.classList.add('hidden');
            if (forgotSuccess) forgotSuccess.classList.add('hidden');
            if (resetError) resetError.classList.add('hidden');
            if (resetSuccess) resetSuccess.classList.add('hidden');
        }

        function showForgotPassword() {
            setAuthSubview('forgot');
        }

        function showResetPassword(token) {
            setAuthSubview('reset');
            const authView = document.getElementById('authView');
            if (authView) authView.classList.remove('hidden');
            document.body.style.overflow = 'hidden';
            const resetForm = document.getElementById('resetPasswordForm');
            if (resetForm) resetForm.dataset.token = token || '';
        }

        function updateUserDisplay() {
            const userInfo = document.getElementById('userInfo');
            const userEmailEl = document.getElementById('userEmail');
            const loginBtn = document.getElementById('loginBtn');
            const quotaWidget = document.getElementById('quotaWidgetHeader');

            if (currentUser && userInfo && userEmailEl) {
                userEmailEl.textContent = currentUser.email;
                userInfo.classList.remove('hidden');
                if (loginBtn) loginBtn.classList.add('hidden');
            } else if (isByokMode() && userInfo && userEmailEl) {
                userEmailEl.textContent = 'Using your OpenAI key';
                userInfo.classList.remove('hidden');
                if (loginBtn) loginBtn.classList.add('hidden');
            } else {
                if (userInfo) userInfo.classList.add('hidden');
                if (loginBtn) loginBtn.classList.remove('hidden');
                if (quotaWidget) quotaWidget.classList.add('hidden');
            }
        }

        function updateQuotaDisplay(quota) {
            const widget = document.getElementById('quotaWidgetHeader');
            const minutesEl = document.getElementById('quotaMinutesHeader');
            if (!widget || !minutesEl || !quota) return;
            if (quota.is_unlimited) {
                minutesEl.textContent = 'Unlimited';
                widget.classList.remove('hidden');
                return;
            }
            minutesEl.textContent = `${quota.minutes_remaining ?? 0} min remaining`;
            widget.classList.remove('hidden');
        }

        async function loadUser() {
            try {
                const response = await fetch('/api/auth/me');
                if (response.status === 401) {
                    // Not logged in — expected for guests and BYOK users.
                    currentUser = null;
                    return false;
                }
                if (response.status === 403) {
                    console.warn('Email not verified');
                    currentUser = null;
                    showVerifyView();
                    return false;
                }
                if (!response.ok) throw new Error('Session expired');
                currentUser = await response.json();
                updateUserDisplay();
                await loadQuota();
                return true;
            } catch (err) {
                console.error('Failed to load user:', err);
                clearStoredEmail();
                currentUser = null;
                return false;
            }
        }

        async function loadQuota() {
            try {
                const response = await fetch('/api/quota/');
                if (!response.ok) throw new Error('Quota unavailable');
                const quota = await response.json();
                updateQuotaDisplay(quota);
                return quota;
            } catch (err) {
                console.error('Failed to load quota:', err);
                return null;
            }
        }

        async function logout() {
            try {
                await fetch('/api/auth/logout', { method: 'POST' });
            } catch (err) {
                console.error('Logout API call failed:', err);
            }
            clearApiKey();
            clearStoredEmail();
            currentUser = null;
            updateUserDisplay();
            const widget = document.getElementById('quotaWidgetHeader');
            if (widget) widget.classList.add('hidden');
            showAuthView('standard', 'signup');
            log('Logged out', 'info');
        }

        // ------------------------------------------------------------------
        // Profile / Settings
        // ------------------------------------------------------------------
        let profileUsageSkip = 0;
        const profileUsageLimit = 10;
        let profileUsageTotal = 0;

        function toggleUserMenu(show) {
            const dropdown = document.getElementById('userMenuDropdown');
            if (!dropdown) return;
            dropdown.classList.toggle('hidden', !show);
        }

        function openProfileModal() {
            const modal = document.getElementById('profileModal');
            if (!modal) return;
            modal.classList.remove('hidden');
            modal.setAttribute('aria-hidden', 'false');
            document.body.style.overflow = 'hidden';
            loadProfile();
            loadProfileQuota();
            profileUsageSkip = 0;
            loadProfileUsage();
        }

        function closeProfileModal() {
            const modal = document.getElementById('profileModal');
            if (!modal) return;
            modal.classList.add('hidden');
            modal.setAttribute('aria-hidden', 'true');
            document.body.style.overflow = '';
        }

        function openDeleteAccountModal() {
            const modal = document.getElementById('deleteAccountModal');
            if (!modal) return;
            modal.classList.remove('hidden');
            modal.setAttribute('aria-hidden', 'false');
        }

        function closeDeleteAccountModal() {
            const modal = document.getElementById('deleteAccountModal');
            if (!modal) return;
            modal.classList.add('hidden');
            modal.setAttribute('aria-hidden', 'true');
            const form = document.getElementById('deleteAccountForm');
            if (form) form.reset();
        }

        function formatDate(iso) {
            if (!iso) return '-';
            const d = new Date(iso);
            return isNaN(d) ? iso : d.toLocaleString();
        }

        async function loadProfile() {
            try {
                const response = await fetch('/api/profile/me');
                if (response.status === 401 || response.status === 403) {
                    throw new Error('Session expired. Please log in again.');
                }
                if (!response.ok) throw new Error('Failed to load profile');
                const data = await response.json();

                const emailEl = document.getElementById('profileEmail');
                const createdAtEl = document.getElementById('profileCreatedAt');
                const totalJobsEl = document.getElementById('profileTotalJobs');
                const verificationEl = document.getElementById('profileVerificationStatus');
                const wantsUpdatesInput = document.getElementById('profileWantsUpdates');
                const modeStandardInput = document.getElementById('profileModeStandard');
                const modeByokInput = document.getElementById('profileModeByok');

                if (emailEl) emailEl.textContent = data.email || '-';
                if (createdAtEl) createdAtEl.textContent = formatDate(data.created_at);
                if (totalJobsEl) totalJobsEl.textContent = data.total_jobs_processed ?? 0;
                if (verificationEl) {
                    verificationEl.textContent = data.is_email_verified ? 'Verified' : 'Unverified';
                    verificationEl.className = `text-xs font-medium ${data.is_email_verified ? 'text-emerald-600 dark:text-emerald-400' : 'text-amber-600 dark:text-amber-400'}`;
                }
                if (wantsUpdatesInput) wantsUpdatesInput.checked = !!data.wants_updates;
                if (modeStandardInput) modeStandardInput.checked = data.api_key_mode === 'standard';
                if (modeByokInput) modeByokInput.checked = data.api_key_mode === 'byok';

                const isByok = data.api_key_mode === 'byok';
                const byokContainer = document.getElementById('profileByokKeyContainer');
                if (byokContainer) byokContainer.classList.toggle('hidden', !isByok);

                // BYOK users cannot use standard-only profile features.
                const standardOnlySections = [
                    'profileQuotaSection',
                    'profilePreferencesSection',
                    'profileApiKeyModeSection',
                    'profileEmailSection',
                    'profilePasswordSection',
                    'profileSessionsSection',
                    'profileDeleteSection'
                ];
                standardOnlySections.forEach(id => {
                    const el = document.getElementById(id);
                    if (el) el.classList.toggle('hidden', isByok);
                });
            } catch (err) {
                showToast(err.message, 'error');
            }
        }

        async function loadProfileQuota() {
            try {
                const response = await fetch('/api/quota/');
                if (!response.ok) throw new Error('Quota unavailable');
                const data = await response.json();
                const remainingEl = document.getElementById('profileQuotaRemaining');
                const detailEl = document.getElementById('profileQuotaDetail');

                if (data.is_unlimited) {
                    if (remainingEl) remainingEl.textContent = 'Unlimited';
                    if (detailEl) detailEl.textContent = 'You are using your own OpenAI API key.';
                } else {
                    if (remainingEl) remainingEl.textContent = `${data.minutes_remaining ?? 0} min`;
                    if (detailEl) detailEl.textContent = `Used ${data.minutes_used ?? 0} of ${data.trial_minutes ?? 30} trial minutes.`;
                }
            } catch (err) {
                console.error('Failed to load profile quota:', err);
            }
        }

        function renderProfileUsage(data) {
            const tbody = document.getElementById('profileUsageTable');
            const pagination = document.getElementById('profileUsagePagination');
            const prevBtn = document.getElementById('profileUsagePrev');
            const nextBtn = document.getElementById('profileUsageNext');
            const pageInfo = document.getElementById('profileUsagePageInfo');
            if (!tbody) return;

            profileUsageTotal = data.total ?? 0;

            if (!data.items || !data.items.length) {
                tbody.innerHTML = `<tr><td colspan="4" class="px-3 py-4 text-center text-slate-400 dark:text-[#6B7280]">No usage history yet.</td></tr>`;
                if (pagination) pagination.classList.add('hidden');
                return;
            }

            tbody.innerHTML = data.items.map(item => `
                <tr class="hover:bg-slate-50 dark:hover:bg-[#121214] transition-colors">
                    <td class="px-3 py-2 text-slate-700 dark:text-[#E2E2E8]">${formatDate(item.created_at)}</td>
                    <td class="px-3 py-2 text-slate-700 dark:text-[#E2E2E8] max-w-[200px] truncate" title="${escapeHtml(item.filename)}">${escapeHtml(item.filename)}</td>
                    <td class="px-3 py-2 text-slate-700 dark:text-[#E2E2E8]">${item.minutes_used ?? 0}</td>
                    <td class="px-3 py-2">
                        <span class="inline-flex items-center px-2 py-0.5 rounded text-[10px] font-medium bg-slate-100 dark:bg-[#2A2A30] text-slate-700 dark:text-[#E2E2E8]">${escapeHtml(item.status)}</span>
                    </td>
                </tr>
            `).join('');

            if (pagination) pagination.classList.remove('hidden');
            if (pageInfo) pageInfo.textContent = `${profileUsageSkip + 1}-${Math.min(profileUsageSkip + data.items.length, profileUsageTotal)} of ${profileUsageTotal}`;
            if (prevBtn) prevBtn.disabled = profileUsageSkip === 0;
            if (nextBtn) nextBtn.disabled = profileUsageSkip + data.items.length >= profileUsageTotal;
        }

        async function loadProfileUsage() {
            try {
                const response = await fetch(`/api/profile/usage?skip=${profileUsageSkip}&limit=${profileUsageLimit}`);
                if (!response.ok) throw new Error('Failed to load usage history');
                const data = await response.json();
                renderProfileUsage(data);
            } catch (err) {
                showToast(err.message, 'error');
            }
        }

        async function savePreferences(event) {
            event.preventDefault();
            const wantsUpdatesInput = document.getElementById('profileWantsUpdates');
            const body = {
                wants_updates: wantsUpdatesInput ? wantsUpdatesInput.checked : null
            };

            try {
                const response = await fetch('/api/profile/preferences', {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(body)
                });
                if (!response.ok) {
                    const data = await response.json().catch(() => ({}));
                    throw new Error(data.detail || 'Failed to save preferences');
                }
                showToast('Preferences saved.', 'success');
                loadProfile();
                if (currentUser) {
                    currentUser.wants_updates = body.wants_updates;
                }
            } catch (err) {
                showToast(err.message, 'error');
            }
        }

        async function saveApiKeyMode(event) {
            event.preventDefault();
            const standardRadio = document.getElementById('profileModeStandard');
            const byokKeyInput = document.getElementById('profileByokKeyInput');
            const mode = standardRadio && standardRadio.checked ? 'standard' : 'byok';
            const body = { mode };
            if (mode === 'byok' && byokKeyInput) {
                body.api_key = byokKeyInput.value.trim();
            }

            try {
                const response = await fetch('/api/profile/api-key-mode', {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(body)
                });
                if (!response.ok) {
                    const data = await response.json().catch(() => ({}));
                    throw new Error(data.detail || 'Failed to update API key mode');
                }
                showToast('API key mode updated.', 'success');
                loadProfile();
            } catch (err) {
                showToast(err.message, 'error');
            }
        }

        async function updateEmail(event) {
            event.preventDefault();
            const newEmailInput = document.getElementById('profileNewEmail');
            const passwordInput = document.getElementById('profileEmailPassword');
            const body = {
                new_email: newEmailInput ? newEmailInput.value.trim() : '',
                password: passwordInput ? passwordInput.value : ''
            };

            try {
                const response = await fetch('/api/profile/email', {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(body)
                });
                if (!response.ok) {
                    const data = await response.json().catch(() => ({}));
                    throw new Error(data.detail || 'Failed to update email');
                }
                showToast('Email updated. Please verify your new address.', 'success');
                document.getElementById('profileEmailForm')?.reset();
                loadProfile();
                if (currentUser && newEmailInput) currentUser.email = newEmailInput.value.trim();
                updateUserDisplay();
            } catch (err) {
                showToast(err.message, 'error');
            }
        }

        async function changePassword(event) {
            event.preventDefault();
            const currentInput = document.getElementById('profileCurrentPassword');
            const newInput = document.getElementById('profileNewPassword');
            const confirmInput = document.getElementById('profileConfirmPassword');

            if (newInput.value !== confirmInput.value) {
                showToast('New passwords do not match.', 'error');
                return;
            }

            const body = {
                current_password: currentInput.value,
                new_password: newInput.value,
                confirm_password: confirmInput.value
            };

            try {
                const response = await fetch('/api/profile/password', {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(body)
                });
                if (!response.ok) {
                    const data = await response.json().catch(() => ({}));
                    throw new Error(data.detail || 'Failed to change password');
                }
                showToast('Password changed successfully.', 'success');
                document.getElementById('profilePasswordForm')?.reset();
            } catch (err) {
                showToast(err.message, 'error');
            }
        }

        async function logoutAllSessions() {
            if (!confirm('Log out all other sessions? Your current session will remain active.')) return;
            try {
                const response = await fetch('/api/profile/sessions', { method: 'DELETE' });
                if (!response.ok) {
                    const data = await response.json().catch(() => ({}));
                    throw new Error(data.detail || 'Failed to log out sessions');
                }
                showToast('All other sessions have been logged out.', 'success');
            } catch (err) {
                showToast(err.message, 'error');
            }
        }

        async function deleteAccount(event) {
            event.preventDefault();
            const confirmInput = document.getElementById('deleteAccountConfirm');
            const passwordInput = document.getElementById('deleteAccountPassword');

            if (confirmInput.value !== 'DELETE') {
                showToast('Please type DELETE to confirm.', 'error');
                return;
            }

            const body = {
                password: passwordInput.value,
                confirmation: confirmInput.value
            };

            try {
                const response = await fetch('/api/profile/account', {
                    method: 'DELETE',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(body)
                });
                if (!response.ok) {
                    const data = await response.json().catch(() => ({}));
                    throw new Error(data.detail || 'Failed to delete account');
                }
                showToast('Your account has been deleted.', 'info');
                closeDeleteAccountModal();
                closeProfileModal();
                clearApiKey();
                clearStoredEmail();
                currentUser = null;
                updateUserDisplay();
                showAuthView('standard', 'signup');
            } catch (err) {
                showToast(err.message, 'error');
            }
        }

        async function handleStandardAuthSubmit(event) {
            event.preventDefault();
            const emailInput = document.getElementById('authEmail');
            const passwordInput = document.getElementById('authPassword');
            const wantsUpdatesInput = document.getElementById('authWantsUpdates');
            const errorEl = document.getElementById('authError');
            const submitBtn = document.getElementById('authSubmitBtn');

            const email = emailInput.value.trim();
            const password = passwordInput.value;
            const wantsUpdates = currentStandardMode === 'signup' ? wantsUpdatesInput.checked : undefined;

            if (errorEl) errorEl.classList.add('hidden');
            if (submitBtn) {
                submitBtn.disabled = true;
                submitBtn.textContent = currentStandardMode === 'login' ? 'Signing in...' : 'Creating account...';
            }

            const endpoint = currentStandardMode === 'login' ? '/api/auth/login' : '/api/auth/signup';
            const body = { email, password };
            if (currentStandardMode === 'signup') body.wants_updates = wantsUpdates;

            try {
                const response = await fetch(endpoint, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(body)
                });

                if (!response.ok) {
                    let detail = currentStandardMode === 'login' ? 'Invalid email or password.' : 'Sign up failed.';
                    try {
                        const data = await response.json();
                        if (data.detail) detail = data.detail;
                    } catch (e) { /* ignore */ }
                    throw new Error(detail);
                }

                clearApiKey();
                setStoredEmail(email);

                if (currentStandardMode === 'signup') {
                    // New accounts start unverified; show the verification screen immediately.
                    showVerifyView();
                    log('Account created — please verify your email', 'info');
                } else {
                    const loaded = await loadUser();
                    if (!loaded) {
                        if (getStoredEmail()) {
                            showVerifyView();
                        } else {
                            throw new Error('Could not load your account.');
                        }
                    } else {
                        showMainApp();
                        log(`Logged in as ${currentUser.email}`, 'success');
                    }
                }

                emailInput.value = '';
                passwordInput.value = '';
                if (wantsUpdatesInput) wantsUpdatesInput.checked = true;
            } catch (err) {
                if (errorEl) {
                    errorEl.textContent = err.message;
                    errorEl.classList.remove('hidden');
                }
            } finally {
                if (submitBtn) {
                    submitBtn.disabled = false;
                    submitBtn.textContent = currentStandardMode === 'login' ? 'Sign In' : 'Create Free Account';
                }
            }
        }

        async function handleByokSubmit(event) {
            event.preventDefault();
            const apiKeyInput = document.getElementById('byokApiKey');
            const emailInput = document.getElementById('byokEmail');
            const errorEl = document.getElementById('byokError');
            const submitBtn = document.getElementById('byokSubmitBtn');

            const apiKey = apiKeyInput.value.trim();
            const email = emailInput.value.trim();

            if (errorEl) errorEl.classList.add('hidden');
            if (submitBtn) {
                submitBtn.disabled = true;
                submitBtn.textContent = 'Validating key...';
            }

            try {
                const response = await fetch('/api/auth/byok-start', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ api_key: apiKey, email })
                });

                if (!response.ok) {
                    let detail = 'The provided API key could not be validated.';
                    try {
                        const data = await response.json();
                        if (data.detail) detail = data.detail;
                    } catch (e) { /* ignore */ }
                    throw new Error(detail);
                }

                setApiKey(apiKey);
                updateUserDisplay();
                showMainApp();
                log('Using your own OpenAI API key', 'success');
                apiKeyInput.value = '';
                emailInput.value = '';
            } catch (err) {
                if (errorEl) {
                    errorEl.textContent = err.message;
                    errorEl.classList.remove('hidden');
                }
            } finally {
                if (submitBtn) {
                    submitBtn.disabled = false;
                    submitBtn.textContent = 'Start Using TermSub';
                }
            }
        }

        async function handleForgotPasswordSubmit(event) {
            event.preventDefault();
            const emailInput = document.getElementById('forgotPasswordEmail');
            const errorEl = document.getElementById('forgotPasswordError');
            const successEl = document.getElementById('forgotPasswordSuccess');
            const submitBtn = document.getElementById('forgotPasswordSubmitBtn');

            const email = emailInput.value.trim();
            if (errorEl) errorEl.classList.add('hidden');
            if (successEl) successEl.classList.add('hidden');
            if (submitBtn) {
                submitBtn.disabled = true;
                submitBtn.textContent = 'Sending...';
            }

            try {
                const response = await fetch('/api/auth/forgot-password', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ email })
                });
                if (!response.ok) {
                    const data = await response.json().catch(() => ({}));
                    throw new Error(data.detail || 'Failed to send reset email');
                }
                if (successEl) {
                    successEl.textContent = 'Check your email for reset link';
                    successEl.classList.remove('hidden');
                }
                emailInput.value = '';
            } catch (err) {
                if (errorEl) {
                    errorEl.textContent = err.message;
                    errorEl.classList.remove('hidden');
                }
            } finally {
                if (submitBtn) {
                    submitBtn.disabled = false;
                    submitBtn.textContent = 'Send reset link';
                }
            }
        }

        async function handleResetPasswordSubmit(event) {
            event.preventDefault();
            const resetForm = document.getElementById('resetPasswordForm');
            const passwordInput = document.getElementById('resetPasswordInput');
            const confirmInput = document.getElementById('resetPasswordConfirm');
            const errorEl = document.getElementById('resetPasswordError');
            const successEl = document.getElementById('resetPasswordSuccess');
            const submitBtn = document.getElementById('resetPasswordSubmitBtn');

            const token = resetForm ? resetForm.dataset.token : '';
            const newPassword = passwordInput.value;
            const confirmPassword = confirmInput.value;

            if (errorEl) errorEl.classList.add('hidden');
            if (successEl) successEl.classList.add('hidden');

            if (newPassword !== confirmPassword) {
                if (errorEl) {
                    errorEl.textContent = 'Passwords do not match.';
                    errorEl.classList.remove('hidden');
                }
                return;
            }

            if (submitBtn) {
                submitBtn.disabled = true;
                submitBtn.textContent = 'Resetting...';
            }

            try {
                const response = await fetch('/api/auth/reset-password', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        reset_token: token,
                        new_password: newPassword,
                        confirm_password: confirmPassword
                    })
                });
                if (!response.ok) {
                    const data = await response.json().catch(() => ({}));
                    throw new Error(data.detail || 'Failed to reset password');
                }
                if (successEl) {
                    successEl.textContent = 'Password reset successfully. You can now sign in.';
                    successEl.classList.remove('hidden');
                }
                passwordInput.value = '';
                confirmInput.value = '';
                setTimeout(() => {
                    setAuthSubview('form');
                    setStandardMode('login');
                }, 2000);
            } catch (err) {
                if (errorEl) {
                    errorEl.textContent = err.message;
                    errorEl.classList.remove('hidden');
                }
            } finally {
                if (submitBtn) {
                    submitBtn.disabled = false;
                    submitBtn.textContent = 'Reset password';
                }
            }
        }

        async function resendVerificationEmail() {
            const email = getStoredEmail();
            if (!email) {
                showVerifyMessage('Please log in again to resend the verification email.', 'error');
                showAuthView('standard', 'login');
                return;
            }
            const btn = document.getElementById('resendVerifyBtn');
            if (btn) {
                btn.disabled = true;
                btn.innerHTML = '<i class="fa-solid fa-circle-notch fa-spin mr-2"></i>Sending...';
            }
            try {
                const response = await fetch('/api/auth/resend-verification', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ email })
                });
                if (!response.ok) throw new Error('Request failed');
                showVerifyMessage('Verification email sent. Please check your inbox.', 'success');
            } catch (err) {
                console.error('Failed to resend verification email:', err);
                showVerifyMessage('Could not resend email. Please try again later.', 'error');
            } finally {
                if (btn) {
                    btn.disabled = false;
                    btn.innerHTML = '<i class="fa-solid fa-paper-plane mr-2"></i>Resend Email';
                }
            }
        }

        async function recheckVerification() {
            const btn = document.getElementById('recheckVerifyBtn');
            if (btn) {
                btn.disabled = true;
                btn.innerHTML = '<i class="fa-solid fa-circle-notch fa-spin mr-2"></i>Checking...';
            }
            const loaded = await loadUser();
            if (btn) {
                btn.disabled = false;
                btn.innerHTML = '<i class="fa-solid fa-rotate-right mr-2"></i>I\'ve Verified My Email';
            }
            if (loaded) {
                showMainApp();
                log('Email verified — welcome to TermSub', 'success');
            } else {
                showVerifyMessage('Your email is not verified yet. Please click the link in the email.', 'warning');
            }
        }

        function showVerifyMessage(message, type = 'info') {
            const el = document.getElementById('verifyMessage');
            if (!el) return;
            const colors = {
                info: 'bg-blue-50 dark:bg-blue-900/20 text-blue-700 dark:text-blue-300 border-blue-200 dark:border-blue-800',
                success: 'bg-emerald-50 dark:bg-emerald-900/20 text-emerald-700 dark:text-emerald-300 border-emerald-200 dark:border-emerald-800',
                warning: 'bg-amber-50 dark:bg-amber-900/20 text-amber-700 dark:text-amber-300 border-amber-200 dark:border-amber-800',
                error: 'bg-red-50 dark:bg-red-900/20 text-red-700 dark:text-red-300 border-red-200 dark:border-red-800'
            };
            el.className = `text-xs mb-4 p-2 rounded border ${colors[type] || colors.info}`;
            el.textContent = message;
            el.classList.remove('hidden');
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

            const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
            svg.setAttribute('class', `w-4 h-4 shrink-0 ${cfg.icon}`);
            svg.setAttribute('fill', 'none');
            svg.setAttribute('stroke', 'currentColor');
            svg.setAttribute('viewBox', '0 0 24 24');
            const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
            path.setAttribute('stroke-linecap', 'round');
            path.setAttribute('stroke-linejoin', 'round');
            path.setAttribute('stroke-width', '2');
            path.setAttribute('d', 'M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z');
            svg.appendChild(path);

            const span = document.createElement('span');
            span.className = 'font-medium';
            span.textContent = message;

            el.appendChild(svg);
            el.appendChild(span);
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

            // Show/hide buttons based on status
            updateButtonVisibility(data.status);
        }

        async function renderTerms() {
            if (!currentVideoId) return;

            try {
                const response = await fetch(`/terms/video/${currentVideoId}`);
                const terms = await response.json();

                const tbody = document.getElementById('termsTable');
                const countBadge = document.getElementById('termsCount');

                if (!terms || terms.length === 0) {
                    tbody.innerHTML = '<tr><td colspan="4" class="px-3 py-8 text-center text-slate-400 dark:text-[#6B7280] text-sm">No terms extracted yet.</td></tr>';
                    if (countBadge) countBadge.classList.add('hidden');
                    return;
                }

                if (countBadge) {
                    countBadge.textContent = terms.length.toString();
                    countBadge.classList.remove('hidden');
                }

                tbody.innerHTML = terms.map(term => {
                    // Clean translation: remove bracketed type prefix (e.g., "[Key Concept] ")
                    const cleanTranslation = (term.translated_term || '').replace(/^\[.*?\]\s*/, '');
                    // Format category for display: "proper_noun" → "Proper Noun"
                    const displayCategory = (term.category || 'General')
                        .replace(/_/g, ' ')
                        .replace(/\b\w/g, c => c.toUpperCase());
                    return `
                    <tr class="hover:bg-slate-50 dark:hover:bg-[#1A1A1E] ${term.source === 'manual' ? 'bg-amber-50/50 dark:bg-amber-900/20' : ''}">
                        <td class="px-3 py-2">
                            <span class="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-semibold uppercase tracking-wide bg-slate-100 dark:bg-[#2A2A30] text-slate-600 dark:text-[#8A8F98]">
                                ${escapeHtml(displayCategory)}
                            </span>
                        </td>
                        <td class="px-3 py-2 font-medium text-slate-900 dark:text-[#E2E2E8]">${escapeHtml(term.original_term)}</td>
                        <td class="px-3 py-2 text-slate-600 dark:text-[#8A8F98] rtl-text">${escapeHtml(cleanTranslation)}</td>
                        <td class="px-3 py-2">
                            <div class="flex items-center gap-2">
                                <input type="text" value="${escapeHtml(term.standardized_term || '')}" 
                                    onchange="updateTerm('${term.id}', this.value)"
                                    class="flex-1 border-transparent bg-slate-50/50 dark:bg-[#2A2A30]/70 hover:bg-slate-100/70 dark:hover:bg-[#2A2A30] focus:bg-white dark:focus:bg-[#1A1A1E] focus:border-slate-300 dark:focus:border-[#3A3A42] focus:ring-1 focus:ring-slate-300 dark:focus:ring-[#3A3A42] text-slate-900 dark:text-[#E2E2E8] placeholder-slate-400 dark:placeholder-[#6B7280] transition-all rounded px-2 py-1 text-xs">
                            </div>
                        </td>
                    </tr>
                `}).join('');

                // Refresh remaining minutes after terms are shown (video processing has billed minutes).
                loadQuota();
            } catch (err) {
                console.error('Failed to load terms:', err);
            }
        }

        const TIMECODE_REGEX = /^(\d{2}):(\d{2}):(\d{2}),(\d{3})$/;

        // Supported languages for source/target dropdowns (ISO-639-1 codes).
        // Covers the OpenAI Audio API supported languages plus legacy app languages.
        // Kept in one flat list, sorted alphabetically by English name.
        const SUPPORTED_LANGUAGES = [
            { code: 'af', name: 'Afrikaans', nativeName: 'Afrikaans' },
            { code: 'ar', name: 'Arabic', nativeName: 'العربية' },
            { code: 'hy', name: 'Armenian', nativeName: 'Հայերեն' },
            { code: 'az', name: 'Azerbaijani', nativeName: 'Azərbaycan' },
            { code: 'bn', name: 'Bengali', nativeName: 'বাংলা' },
            { code: 'be', name: 'Belarusian', nativeName: 'Беларуская' },
            { code: 'bs', name: 'Bosnian', nativeName: 'Bosanski' },
            { code: 'bg', name: 'Bulgarian', nativeName: 'Български' },
            { code: 'ca', name: 'Catalan', nativeName: 'Català' },
            { code: 'zh', name: 'Chinese (Mandarin)', nativeName: '中文' },
            { code: 'hr', name: 'Croatian', nativeName: 'Hrvatski' },
            { code: 'cs', name: 'Czech', nativeName: 'Čeština' },
            { code: 'da', name: 'Danish', nativeName: 'Dansk' },
            { code: 'nl', name: 'Dutch', nativeName: 'Nederlands' },
            { code: 'en', name: 'English', nativeName: 'English' },
            { code: 'et', name: 'Estonian', nativeName: 'Eesti' },
            { code: 'fa', name: 'Persian (Farsi)', nativeName: 'فارسی' },
            { code: 'fi', name: 'Finnish', nativeName: 'Suomi' },
            { code: 'fr', name: 'French', nativeName: 'Français' },
            { code: 'gl', name: 'Galician', nativeName: 'Galego' },
            { code: 'de', name: 'German', nativeName: 'Deutsch' },
            { code: 'el', name: 'Greek', nativeName: 'Ελληνικά' },
            { code: 'he', name: 'Hebrew', nativeName: 'עברית' },
            { code: 'hi', name: 'Hindi', nativeName: 'हिन्दी' },
            { code: 'hu', name: 'Hungarian', nativeName: 'Magyar' },
            { code: 'is', name: 'Icelandic', nativeName: 'Íslenska' },
            { code: 'id', name: 'Indonesian', nativeName: 'Bahasa Indonesia' },
            { code: 'it', name: 'Italian', nativeName: 'Italiano' },
            { code: 'ja', name: 'Japanese', nativeName: '日本語' },
            { code: 'kn', name: 'Kannada', nativeName: 'ಕನ್ನಡ' },
            { code: 'kk', name: 'Kazakh', nativeName: 'Қазақ' },
            { code: 'ko', name: 'Korean', nativeName: '한국어' },
            { code: 'lv', name: 'Latvian', nativeName: 'Latviešu' },
            { code: 'lt', name: 'Lithuanian', nativeName: 'Lietuvių' },
            { code: 'mk', name: 'Macedonian', nativeName: 'Македонски' },
            { code: 'ms', name: 'Malay', nativeName: 'Bahasa Melayu' },
            { code: 'mr', name: 'Marathi', nativeName: 'मराठी' },
            { code: 'mi', name: 'Maori', nativeName: 'Māori' },
            { code: 'ne', name: 'Nepali', nativeName: 'नेपाली' },
            { code: 'no', name: 'Norwegian', nativeName: 'Norsk' },
            { code: 'pl', name: 'Polish', nativeName: 'Polski' },
            { code: 'pt', name: 'Portuguese', nativeName: 'Português' },
            { code: 'ro', name: 'Romanian', nativeName: 'Română' },
            { code: 'ru', name: 'Russian', nativeName: 'Русский' },
            { code: 'sr', name: 'Serbian', nativeName: 'Српски' },
            { code: 'sk', name: 'Slovak', nativeName: 'Slovenčina' },
            { code: 'sl', name: 'Slovenian', nativeName: 'Slovenščina' },
            { code: 'es', name: 'Spanish', nativeName: 'Español' },
            { code: 'sw', name: 'Swahili', nativeName: 'Kiswahili' },
            { code: 'sv', name: 'Swedish', nativeName: 'Svenska' },
            { code: 'tl', name: 'Tagalog (Filipino)', nativeName: 'Tagalog' },
            { code: 'ta', name: 'Tamil', nativeName: 'தமிழ்' },
            { code: 'te', name: 'Telugu', nativeName: 'తెలుగు' },
            { code: 'th', name: 'Thai', nativeName: 'ไทย' },
            { code: 'tr', name: 'Turkish', nativeName: 'Türkçe' },
            { code: 'uk', name: 'Ukrainian', nativeName: 'Українська' },
            { code: 'ur', name: 'Urdu', nativeName: 'اردو' },
            { code: 'vi', name: 'Vietnamese', nativeName: 'Tiếng Việt' },
            { code: 'cy', name: 'Welsh', nativeName: 'Cymraeg' },
        ];

        function formatTimecode(seconds) {
            const totalMillis = Math.max(0, Math.round(seconds * 1000));
            const ms = (totalMillis % 1000).toString().padStart(3, '0');
            const totalSeconds = Math.floor(totalMillis / 1000);
            const s = (totalSeconds % 60).toString().padStart(2, '0');
            const totalMinutes = Math.floor(totalSeconds / 60);
            const m = (totalMinutes % 60).toString().padStart(2, '0');
            const h = Math.floor(totalMinutes / 60).toString().padStart(2, '0');
            return `${h}:${m}:${s},${ms}`;
        }

        function isValidTimecode(value) {
            return typeof value === 'string' && TIMECODE_REGEX.test(value.trim());
        }

        function timecodeToSeconds(value) {
            const match = value.trim().match(TIMECODE_REGEX);
            if (!match) return NaN;
            const hours = parseInt(match[1], 10);
            const minutes = parseInt(match[2], 10);
            const seconds = parseInt(match[3], 10);
            const millis = parseInt(match[4], 10);
            return hours * 3600 + minutes * 60 + seconds + millis / 1000;
        }
        
        function renderTextPreview(segments) {
            const originalEl = document.getElementById('textPreviewOriginal');
            const translatedEl = document.getElementById('textPreviewTranslated');
            if (!originalEl || !translatedEl) return;

            // Track the latest rendered state for history snapshots
            currentTimelineSegments = JSON.parse(JSON.stringify(segments || []));
            _updateUndoButton();

            if (!segments || segments.length === 0) {
                originalEl.textContent = 'No text available yet.';
                translatedEl.textContent = 'No translation available yet.';
                return;
            }

            const ordered = [...segments].sort((a, b) => (a.sequence_number || 0) - (b.sequence_number || 0));
            const originalText = ordered.map(s => s.original_text || '').join('\n\n');
            const translatedText = ordered.map(s => s.translated_text || s.original_text || '').join('\n\n');

            originalEl.textContent = originalText;
            translatedEl.textContent = translatedText;
        }

        function renderSubtitleTimeline(segments) {
            const grid = document.getElementById('timelineCardGrid');
            if (!grid) return;

            // Track the latest rendered state for history snapshots
            currentTimelineSegments = JSON.parse(JSON.stringify(segments || []));
            _updateUndoButton();

            if (!segments || segments.length === 0) {
                grid.innerHTML = '<div class="text-slate-400 dark:text-[#6B7280] text-center py-8">No subtitles available yet.</div>';
                return;
            }
            
            const template = document.getElementById('segmentCardTemplate');
            if (!template) return;

            grid.innerHTML = '';
            segments.forEach((seg, idx) => {
                const clone = template.content.cloneNode(true);
                const card = clone.querySelector('.group');
                clone.querySelector('.seq-num').textContent = `#${seg.sequence_number || idx + 1}`;

                const startInput = card.querySelector('input[data-time-role="start"]');
                const endInput = card.querySelector('input[data-time-role="end"]');
                const textEl = card.querySelector('[data-time-role="text"]');
                const splitBtn = card.querySelector('[data-action="split"]');
                const addBtn = card.querySelector('[data-action="add"]');
                const removeBtn = card.querySelector('[data-action="remove"]');

                [startInput, endInput, textEl, splitBtn, addBtn, removeBtn].forEach(el => {
                    if (el) el.setAttribute('data-segment-id', seg.id || '');
                });
                if (addBtn) addBtn.setAttribute('data-add-below', seg.sequence_number || idx + 1);

                if (startInput) startInput.value = formatTimecode(seg.start_time);
                if (endInput) endInput.value = formatTimecode(seg.end_time);

                if (textEl) {
                    textEl.textContent = seg.translated_text != null
                        ? seg.translated_text
                        : seg.original_text || '(empty)';
                    if (seg.translated_text == null) {
                        textEl.classList.add('text-slate-400', 'dark:text-[#6B7280]', 'italic');
                    }
                    textEl.dataset.originalText = textEl.textContent;
                }

                grid.appendChild(clone);
            });

            // Attach auto-save blur listeners to editable fields
            grid.querySelectorAll('input.timecode-input, [contenteditable="true"]').forEach(el => {
                el.addEventListener('blur', async (e) => {
                    if (isSavingSegment) return;
                    const segmentId = e.target.getAttribute('data-segment-id');
                    if (!segmentId || !currentVideoId) return;

                    const isTimeInput = e.target.tagName === 'INPUT' && e.target.hasAttribute('data-time-role');
                    const timeRole = isTimeInput ? e.target.getAttribute('data-time-role') : null;
                    const card = e.target.closest('.group');
                    const payload = {};

                    // Validate the specific field that triggered blur before building payload.
                    if (isTimeInput) {
                        const raw = e.target.value.trim();
                        if (!isValidTimecode(raw)) {
                            log('Invalid timecode format. Use HH:MM:SS,mmm (e.g. 00:01:23,456).', 'warning');
                            const originalSeg = currentTimelineSegments.find(s => s.id === segmentId);
                            if (originalSeg) {
                                e.target.value = formatTimecode(originalSeg[timeRole === 'start' ? 'start_time' : 'end_time']);
                            }
                            return;
                        }
                    }

                    // Aggregate latest text and timecode values for the segment.
                    const startInput = card.querySelector('input[data-time-role="start"]');
                    const endInput = card.querySelector('input[data-time-role="end"]');
                    const textEl = card.querySelector('[contenteditable="true"]');

                    if (startInput && endInput) {
                        payload.start_time = startInput.value.trim();
                        payload.end_time = endInput.value.trim();

                        if (isValidTimecode(payload.start_time) && isValidTimecode(payload.end_time)) {
                            if (timecodeToSeconds(payload.start_time) >= timecodeToSeconds(payload.end_time)) {
                                log('Start time must be strictly before end time.', 'warning');
                                const originalSeg = currentTimelineSegments.find(s => s.id === segmentId);
                                if (originalSeg && timeRole) {
                                    e.target.value = formatTimecode(originalSeg[timeRole === 'start' ? 'start_time' : 'end_time']);
                                }
                                return;
                            }
                        }
                    }

                    if (textEl) {
                        const newText = textEl.innerText.trim();
                        if (newText === '') {
                            log('Segment text cannot be empty — change discarded.', 'warning');
                            textEl.textContent = textEl.dataset.originalText || '(empty)';
                            return;
                        }
                        payload.translated_text = newText;
                    }

                    // Skip network call if nothing changed compared to the last rendered state.
                    const originalSeg = currentTimelineSegments.find(s => s.id === segmentId);
                    if (originalSeg) {
                        const changed = (
                            (payload.translated_text !== undefined && payload.translated_text !== originalSeg.translated_text) ||
                            (payload.start_time !== undefined && payload.start_time !== formatTimecode(originalSeg.start_time)) ||
                            (payload.end_time !== undefined && payload.end_time !== formatTimecode(originalSeg.end_time))
                        );
                        if (!changed) return;
                    }

                    pushTimelineHistory();
                    isSavingSegment = true;
                    try {
                        const response = await fetch(`/videos/${currentVideoId}/segments/${segmentId}`, {
                            method: 'PATCH',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify(payload)
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
            });

            // Attach Split Card listeners
            grid.querySelectorAll('[data-action="split"]').forEach(btn => {
                btn.addEventListener('click', async (e) => {
                    e.preventDefault();
                    const segmentId = btn.getAttribute('data-segment-id');
                    if (!segmentId || !currentVideoId) return;
                    pushTimelineHistory();

                    try {
                        const response = await fetch(`/videos/${currentVideoId}/segments/${segmentId}/split`, {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' }
                        });
                        if (!response.ok) throw new Error('Server returned ' + response.status);
                        const data = await response.json();
                        log('Segment split successfully.', 'success');
                        if (data.segments) renderSubtitleTimeline(data.segments);
                    } catch (err) {
                        console.error('Split failed:', err);
                        log('Split failed: ' + err.message, 'error');
                    }
                });
            });

            // Attach Add Card Below listeners
            grid.querySelectorAll('[data-action="add"]').forEach(btn => {
                btn.addEventListener('click', async (e) => {
                    e.preventDefault();
                    const targetSeq = parseInt(btn.getAttribute('data-add-below'), 10) + 1;
                    if (!currentVideoId || isNaN(targetSeq)) return;
                    pushTimelineHistory();

                    try {
                        const response = await fetch(`/videos/${currentVideoId}/segments/add`, {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({
                                target_sequence: targetSeq,
                                start_time: 0.0,
                                end_time: 2.0,
                                text: ''
                            })
                        });
                        if (!response.ok) throw new Error('Server returned ' + response.status);
                        const data = await response.json();
                        log('New segment added.', 'success');
                        if (data.segments) renderSubtitleTimeline(data.segments);
                    } catch (err) {
                        console.error('Add segment failed:', err);
                        log('Add segment failed: ' + err.message, 'error');
                    }
                });
            });

            // Attach Remove Card listeners
            grid.querySelectorAll('[data-action="remove"]').forEach(btn => {
                btn.addEventListener('click', async (e) => {
                    e.preventDefault();
                    const segmentId = btn.getAttribute('data-segment-id');
                    if (!segmentId || !currentVideoId) return;
                    pushTimelineHistory();

                    try {
                        const response = await fetch(`/videos/${currentVideoId}/segments/${segmentId}`, {
                            method: 'DELETE'
                        });
                        if (!response.ok) throw new Error('Server returned ' + response.status);
                        const data = await response.json();
                        log('Segment removed.', 'success');
                        if (data.segments) renderSubtitleTimeline(data.segments);
                    } catch (err) {
                        console.error('Remove segment failed:', err);
                        log('Remove segment failed: ' + err.message, 'error');
                    }
                });
            });
        }

        // ------------------------------------------------------------------
        // Timeline Undo System
        // ------------------------------------------------------------------
        function pushTimelineHistory() {
            // Save a snapshot of the current timeline before a mutating operation.
            if (!currentTimelineSegments || currentTimelineSegments.length === 0) return;
            timelineHistory.push(JSON.parse(JSON.stringify(currentTimelineSegments)));
            if (timelineHistory.length > MAX_TIMELINE_HISTORY) {
                timelineHistory.shift();
            }
            _updateUndoButton();
        }

        function _updateUndoButton() {
            const btn = document.getElementById('undoTimelineBtn');
            if (!btn) return;
            const hasHistory = timelineHistory.length > 0;
            btn.disabled = !hasHistory;
            btn.classList.toggle('opacity-50', !hasHistory);
            btn.classList.toggle('cursor-not-allowed', !hasHistory);
            btn.classList.toggle('hover:bg-slate-300', hasHistory);
            btn.classList.toggle('dark:hover:bg-[#3A3A40]', hasHistory);
        }

        async function undoTimeline() {
            if (timelineHistory.length === 0 || !currentVideoId) return;
            const restoredSegments = timelineHistory.pop();

            try {
                const response = await fetch(`/videos/${currentVideoId}/segments/restore`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ segments: restoredSegments })
                });
                if (!response.ok) throw new Error('Server returned ' + response.status);
                const data = await response.json();
                log('Undo successful.', 'success');
                if (data.segments) renderSubtitleTimeline(data.segments);
            } catch (err) {
                console.error('Undo failed:', err);
                log('Undo failed: ' + err.message, 'error');
                // Push the snapshot back so the user can retry
                timelineHistory.push(restoredSegments);
                _updateUndoButton();
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

                // The backend reports "awaiting_choice" after transcription; treat it as
                // "transcribed" everywhere the UI is refreshed from polling.
                if (data.status === 'awaiting_choice') {
                    data.status = 'transcribed';
                }

                // Guard: Don't update status if we have an active job and this is stale data
                if (currentJobId && data.status === 'completed' && !loggedCompletions.has(currentJobId)) {
                    // This is likely stale data - wait for WebSocket confirmation
                    console.log('[fetchVideoStatus] Ignoring stale completion status');
                    return;
                }

                currentFileType = data.content_type === 'text' ? 'text' : 'video';
                if (window.textPipeline) window.textPipeline.setFileType(currentFileType);
                updateStatus({
                    status: data.status,
                    progress_percent: data.progress_percent || 0,
                    total_segments: data.total_segments,
                    processed_segments: data.processed_segments
                });

                updateButtonVisibility(data.status);
                if (data.segments && (data.status === 'transcribed' || data.status === 'completed')) {
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
        let fallbackPollInterval = null;
        let fallbackPollCount = 0;
        let lastPolledStatus = null;
        
        async function fetchWsToken() {
            try {
                const response = await fetch('/api/auth/ws-token', { method: 'POST' });
                if (!response.ok) return null;
                return await response.json();
            } catch (err) {
                console.error('[WebSocket] Failed to fetch WS token:', err);
                return null;
            }
        }
        
        function stopPolling() {
            if (fallbackPollInterval) {
                clearInterval(fallbackPollInterval);
                fallbackPollInterval = null;
            }
            lastPolledStatus = null;
        }
        
        async function connectWebSocket(videoId) {
            // Close existing connection and stop any polling from a previous session
            disconnectWebSocket();
            stopPolling();

            const apiKey = getApiKey();
            let protocols = null;
            let authMode = 'none';

            if (apiKey) {
                protocols = ['termsub-byok', apiKey];
                authMode = 'byok';
            } else if (currentUser) {
                // Standard users obtain a short-lived token via HTTP and send it
                // through the Sec-WebSocket-Protocol header. This is more reliable
                // than relying on cookies during the WebSocket upgrade.
                const tokenData = await fetchWsToken();
                if (tokenData && tokenData.ws_token && tokenData.subprotocol) {
                    protocols = [tokenData.subprotocol, tokenData.ws_token];
                    authMode = 'standard-ws-token';
                } else {
                    log('WebSocket auth token unavailable - falling back to status polling', 'warning');
                    fallbackToPolling(videoId);
                    return;
                }
            }

            if (authMode === 'none') {
                log('WebSocket connection skipped: not authenticated', 'warning');
                fallbackToPolling(videoId);
                return;
            }

            const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
            const wsUrl = `${wsProtocol}//${window.location.host}/ws/videos/${videoId}`;

            log('Connecting to WebSocket...');
            console.log(`[WebSocket] Connecting to ${wsUrl} (${authMode})`);

            try {
                ws = new WebSocket(wsUrl, protocols);
                
                ws.onopen = () => {
                    console.log('[WebSocket] Connected');
                    log('WebSocket connected - real-time updates enabled', 'success');
                    wsReconnectAttempts = 0;
                    
                    // Send initial ping
                    if (ws && ws.readyState === WebSocket.OPEN) {
                        ws.send(JSON.stringify({type: 'ping'}));
                    }
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
                    fallbackToPolling(videoId);
                };
                
                ws.onclose = () => {
                    console.log('[WebSocket] Connection closed');
                    ws = null;
                    
                    // Attempt to reconnect if we have a video ID and haven't exceeded attempts
                    if (currentVideoId && wsReconnectAttempts < MAX_WS_RECONNECT_ATTEMPTS) {
                        wsReconnectAttempts++;
                        log(`WebSocket disconnected. Reconnecting (${wsReconnectAttempts}/${MAX_WS_RECONNECT_ATTEMPTS})...`);
                        setTimeout(() => connectWebSocket(currentVideoId), 2000);
                    } else if (currentVideoId) {
                        log('WebSocket reconnect attempts exhausted - falling back to status polling', 'warning');
                        fallbackToPolling(currentVideoId);
                    }
                };
                
            } catch (err) {
                console.error('[WebSocket] Failed to create connection:', err);
                log('WebSocket connection failed - falling back to status polling', 'error');
                fallbackToPolling(videoId);
            }
        }
        
        function disconnectWebSocket() {
            if (ws) {
                // Prevent the close handler from trying to reconnect
                const socket = ws;
                ws = null;
                socket.onclose = null;
                socket.close();
                console.log('[WebSocket] Disconnected by client');
            }
        }
        
        function handleWebSocketMessage(data) {
            // Handle both direct status updates and job messages
            let status = data.status;

            // The backend emits "awaiting_choice" after transcription; treat it as
            // "transcribed" so the correct pipeline UI (export or auto-advance) is shown.
            if (status === 'awaiting_choice') {
                status = 'transcribed';
            }

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
                    status = 'transcribed';
                    // Safe segment count extraction with nullish coalescing
                    const segmentCount = data.result?.total_segments ?? data.total_segments ?? 0;
                    const segText = segmentCount > 0 ? `: ${segmentCount} segments` : '';
                    log(`Transcription complete${segText}`, 'success');
                    isJobRunning = false;
                    hasStartedProcessing = false;

                    // Auto-advance through the selected pipeline
                    if (targetPipelineMode === 'terminology') {
                        log('Auto-advancing to terminology analysis...');
                        updateButtonVisibility('transcribed');
                        setTimeout(() => analyzeVideo(), 0);
                    } else if (targetPipelineMode === 'subtitles') {
                        log('Auto-advancing to translation...');
                        updateButtonVisibility('transcribed');
                        setTimeout(() => skipAndTranslate(), 0);
                    } else {
                        // Transcribe-only (or no mode): show export buttons
                        updateButtonVisibility('transcribed');
                    }
                } else if (jobType === 'analyze') {
                    status = 'terms_ready';
                    const termCount = data.result?.terms_extracted ?? data.terms_count ?? 0;
                    const termText = termCount > 0 ? `: ${termCount} terms extracted` : '';
                    log(`Analysis complete${termText}`, 'success');
                    isJobRunning = false;
                    hasStartedProcessing = false;
                    renderTerms();
                    updateButtonVisibility('terms_ready');
                } else if (jobType === 'translate') {
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
                    if (data.result?.segments) {
                        renderSubtitleTimeline(data.result.segments);
                    }
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
                        // Do NOT reset isJobRunning/hasStartedProcessing here — that is the
                        // job_complete handler's responsibility. Resetting early causes the
                        // job_complete message to be treated as stale and breaks auto-advance.
                    }
                    updateButtonVisibility('transcribed');
                    break;
                    
                case 'analyzing':
                    log('Director Agent: Analyzing content...');
                    break;
                    
                case 'context_ready':
                    log(`Director Agent complete: ${data.tone} tone`, 'context');
                    break;
                    
                case 'glossary_extracting':
                    log('Glossary Agent: Extracting terms...');
                    break;
                    
                case 'terms_ready':
                    if (isJobRunning && hasStartedProcessing) {
                        log(`Glossary complete: ${data.terms_count ?? 0} terms`, 'success');
                    }
                    renderTerms();
                    updateButtonVisibility('terms_ready');
                    break;
                    
                case 'translating':
                    log('Translating via OpenAI AI...');
                    break;
                    
                case 'completed':
                    if (isJobRunning && hasStartedProcessing) {
                        log('Translation complete!', 'success');
                    }
                    renderTerms();
                    updateButtonVisibility('completed');
                    if (data.segments) {
                        renderSubtitleTimeline(data.segments);
                    }
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
            const exportPanel = document.getElementById('exportPanel');
            const exportHeader = document.getElementById('exportHeader');
            const container = document.getElementById('primaryActionContainer');
            const termsPanel = document.getElementById('termsPanel');
            const subtitleReviewPanel = document.getElementById('subtitleReviewPanel');

            if (!container) return;

            // Reset all sub-elements
            if (primaryBtn) {
                primaryBtn.classList.remove('hidden');
                primaryBtn.disabled = false;
            }
            helperText?.classList.add('hidden');
            ghostLink?.classList.add('hidden');
            exportGrid?.classList.add('hidden');
            exportPanel?.classList.add('hidden');
            textExportPanel?.classList.add('hidden');
            exportHeader?.classList.add('hidden');

            // Remove any stale post-transcribe choice container
            const oldChoices = container.querySelector('#postTranscribeChoices');
            if (oldChoices) oldChoices.remove();

            // Configure UI based on pipeline state
            switch (status) {
                case 'uploaded':
                    primaryBtn?.classList.add('hidden');
                    if (termsPanel) termsPanel.classList.add('hidden');
                    if (subtitleReviewPanel) subtitleReviewPanel.classList.add('hidden');
                    const textPreviewUploaded = document.getElementById('textPreviewPanel');
                    if (textPreviewUploaded) textPreviewUploaded.classList.add('hidden');
                    break;

                case 'transcribed':
                    if (targetPipelineMode === 'terminology' || targetPipelineMode === 'subtitles') {
                        // Auto-advancing to the next pipeline step; don't show any action
                        // button — the WebSocket-driven status updates will update the UI.
                        primaryBtn?.classList.add('hidden');
                    } else {
                        // Transcribe-only (or no mode): transcribed is the final state
                        primaryBtn.textContent = 'Download the subtitles in original language';
                        primaryBtn.className = 'w-full py-3 px-4 bg-blue-600 hover:bg-blue-700 text-white text-sm font-normal rounded-xl transition-colors tracking-wide';
                        primaryBtn.onclick = downloadTranscription;
                        exportGrid?.classList.add('hidden');
                        textExportPanel?.classList.add('hidden');
                        exportHeader?.classList.add('hidden');
                        if (termsPanel) termsPanel.classList.add('hidden');
                        if (subtitleReviewPanel) subtitleReviewPanel.classList.remove('hidden');
                        // Load original transcription into the timeline so the user can review it
                        fetch(`/videos/${currentVideoId}`)
                            .then(r => r.json())
                            .then(data => {
                                if (data.segments) renderSubtitleTimeline(data.segments);
                            })
                            .catch(err => console.error('Failed to load transcription:', err));
                    }
                    break;

                case 'terms_ready':
                    if (targetPipelineMode === 'terminology' || !targetPipelineMode) {
                        helperText?.classList.remove('hidden');
                        primaryBtn.textContent = 'Translate Subtitles';
                        primaryBtn.className = 'w-full py-3 px-4 bg-blue-600 hover:bg-blue-700 text-white text-sm font-normal rounded-xl transition-colors tracking-wide';
                        primaryBtn.onclick = translateVideo;
                        if (termsPanel) termsPanel.classList.remove('hidden');
                        if (subtitleReviewPanel) subtitleReviewPanel.classList.add('hidden');
                        renderTerms();
                    } else {
                        primaryBtn?.classList.add('hidden');
                    }
                    break;

                case 'completed':
                    primaryBtn?.classList.add('hidden');
                    if (termsPanel) termsPanel.classList.add('hidden');
                    if (subtitleReviewPanel) subtitleReviewPanel.classList.remove('hidden');
                    exportGrid?.classList.remove('hidden');
                    textExportPanel?.classList.add('hidden');
                    exportPanel?.classList.remove('hidden');
                    exportHeader?.classList.remove('hidden');
                    if (exportHeader) exportHeader.textContent = 'Download Subtitles & Translations';
                    break;

                case 'translating':
                    primaryBtn?.classList.add('hidden');
                    if (termsPanel) termsPanel.classList.add('hidden');
                    {
                        if (subtitleReviewPanel) subtitleReviewPanel.classList.remove('hidden');
                        const textPreviewPanelTranslating = document.getElementById('textPreviewPanel');
                        if (textPreviewPanelTranslating) textPreviewPanelTranslating.classList.add('hidden');
                    }
                    break;

                default:
                    primaryBtn?.classList.add('hidden');
                    if (termsPanel) termsPanel.classList.add('hidden');
                    if (subtitleReviewPanel) subtitleReviewPanel.classList.add('hidden');
                    const textPreviewPanelDefault = document.getElementById('textPreviewPanel');
                    if (textPreviewPanelDefault) textPreviewPanelDefault.classList.add('hidden');
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

        // HTTP polling fallback — used when the WebSocket can't connect or keeps
        // dropping. It must fully substitute for the WebSocket: not just show
        // status, but also drive the pipeline forward (auto-advance) and perform
        // the post-step UI transitions that normally come from job_complete messages.
        
        function fallbackToPolling(videoId) {
            // If we already have a working WebSocket, don't poll.
            if (ws && ws.readyState === WebSocket.OPEN) {
                return;
            }

            // Don't start duplicate polling loops
            if (fallbackPollInterval) return;

            log('Falling back to HTTP polling (WebSocket unavailable)', 'warning');
            console.log('[FALLBACK] Starting HTTP polling');
            
            fallbackPollCount = 0;
            lastPolledStatus = null;

            const poll = async () => {
                if (!currentVideoId || currentVideoId !== videoId) {
                    stopPolling();
                    return;
                }
                try {
                    const response = await fetch(`/videos/${videoId}`);
                    const data = await response.json();
                    // Treat the backend's "awaiting_choice" progress message as "transcribed"
                    // so the correct pipeline UI is shown even when polling.
                    if (data.status === 'awaiting_choice') {
                        data.status = 'transcribed';
                    }

                    const previousStatus = lastPolledStatus;
                    lastPolledStatus = data.status;

                    // Only update UI when the status actually changes, so live term edits
                    // aren't clobbered every 5 seconds during quiescent states.
                    if (data.status !== previousStatus) {
                        updateStatus(data);
                    }

                    fallbackPollCount++;
                    if (fallbackPollCount % 5 === 0) {
                        log(`Fallback poll #${fallbackPollCount}: status=${data.status}`);
                    }

                    // Drive the pipeline forward on transitions.
                    if (data.status === 'transcribed' && previousStatus !== 'transcribed') {
                        isJobRunning = false;
                        hasStartedProcessing = false;
                        if (targetPipelineMode === 'terminology') {
                            log('Auto-advancing to terminology analysis...');
                            updateButtonVisibility('transcribed');
                            setTimeout(() => analyzeVideo(), 0);
                        } else if (targetPipelineMode === 'subtitles') {
                            log('Auto-advancing to translation...');
                            updateButtonVisibility('transcribed');
                            setTimeout(() => skipAndTranslate(), 0);
                        } else {
                            updateButtonVisibility('transcribed');
                        }
                    } else if (data.status === 'terms_ready' && previousStatus !== 'terms_ready') {
                        isJobRunning = false;
                        hasStartedProcessing = false;
                        log('Analysis complete', 'success');
                        renderTerms();
                        updateButtonVisibility('terms_ready');
                    } else if (data.status === 'completed' && previousStatus !== 'completed') {
                        isJobRunning = false;
                        hasStartedProcessing = false;
                        log('Translation complete', 'success');
                        updateButtonVisibility('completed');
                        if (data.segments) renderSubtitleTimeline(data.segments);
                    } else if (data.status === 'error') {
                        log('Processing failed', 'error');
                    }

                    // Stop polling once we reach a terminal state.
                    const terminalStatuses = ['terms_ready', 'completed', 'error'];
                    if (targetPipelineMode === 'transcribe') {
                        terminalStatuses.push('transcribed');
                    }
                    if (terminalStatuses.includes(data.status)) {
                        stopPolling();
                    }
                } catch (err) {
                    console.error('Fallback poll error:', err);
                }
            };

            // Run immediately, then every 5 seconds.
            poll();
            fallbackPollInterval = setInterval(poll, 5000);
        }

        function updatePipelineButtonsForFileType() {
            const translateBtn = document.getElementById('translateSubtitlesBtn');
            const originalBtn = document.getElementById('originalSubtitlesBtn');
            if (!translateBtn || !originalBtn) return;

            if (currentFileType === 'text') {
                translateBtn.innerHTML = '<i class="fa-solid fa-language mr-2"></i>Translate Text';
                originalBtn.classList.add('hidden');
            } else {
                translateBtn.innerHTML = '<i class="fa-solid fa-language mr-2"></i>Translate and Get Subtitles';
                originalBtn.classList.remove('hidden');
            }
        }

        function resetApp() {
            currentVideoId = null;
            currentFileType = 'video';
            updatePipelineButtonsForFileType();
            timelineHistory = [];
            currentTimelineSegments = [];
            currentJobId = null;
            isJobRunning = false;
            hasStartedProcessing = false;
            loggedCompletions.clear();
            targetPipelineMode = null;
            
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
            if (termsPanelReset) termsPanelReset.classList.add('hidden');
            const subtitleReviewReset = document.getElementById('subtitleReviewPanel');
            if (subtitleReviewReset) subtitleReviewReset.classList.add('hidden');
            const timelineGridReset = document.getElementById('timelineCardGrid');
            if (timelineGridReset) timelineGridReset.innerHTML = '<div class="text-slate-400 dark:text-[#6B7280] text-center py-8">No subtitles available yet.</div>';
            
            // Reset step & segment counters
            const statusBadgeReset = document.getElementById('statusBadge');
            if (statusBadgeReset) {
                statusBadgeReset.className = 'inline-flex items-center gap-1.5 px-3 py-1.5 bg-blue-500/20 text-blue-300 text-xs font-normal rounded-full';
                statusBadgeReset.innerHTML = '<span id="statusDot" class="w-1.5 h-1.5 rounded-full bg-blue-400"></span>Uploaded';
            }
            
            // Clear logs and terms
            clearActivityLog();
            const termsTableReset = document.getElementById('termsTable');
            if (termsTableReset) termsTableReset.innerHTML = `
                <tr>
                    <td colspan="3" class="px-3 py-8 text-center text-slate-400 dark:text-[#6B7280] text-sm">
                        No terms extracted yet. Upload and process a video.
                    </td>
                </tr>
            `;
            
            // Disconnect WebSocket and stop polling
            disconnectWebSocket();
            stopPolling();
            
            // Clear URL param
            window.history.replaceState({}, document.title, window.location.pathname);
            
            log('New project ready. Upload a file to begin.', 'success');
        }

        // Pipeline entry point: validate inputs, set mode, upload, then auto-start processing.
        async function startPipeline(mode) {
            const fileInput = document.getElementById('fileInput');
            const targetLangSelect = document.getElementById('targetLanguage');

            if (!isAuthenticated()) {
                showAuthView('standard', 'signup');
                log('Please log in, sign up, or provide an API key to upload a file.', 'warning');
                showToast('Please log in or provide an API key to upload', 'warning');
                return;
            }

            if (!fileInput.files || !fileInput.files[0]) {
                showToast('Please select a file first', 'warning');
                return;
            }

            // Transcribe-only does not need a target language
            if (mode !== 'transcribe' && (!targetLangSelect || !targetLangSelect.value)) {
                const warningEl = document.getElementById('languageWarning');
                if (warningEl) warningEl.classList.remove('hidden');
                if (targetLangSelect) {
                    targetLangSelect.classList.add('border-red-500', 'focus:ring-red-500', 'focus:border-red-500');
                    targetLangSelect.scrollIntoView({ behavior: 'smooth', block: 'center' });
                }
                log('Upload blocked: target language is required.', 'warning');
                return;
            }

            targetPipelineMode = mode;
            log(`Starting ${mode} pipeline...`);
            await uploadFile(mode);
        }

        // Upload handler
        async function uploadFile(mode) {
            if (!isAuthenticated()) {
                showAuthView('standard', 'signup');
                log('Please log in, sign up, or provide an API key to upload a file.', 'warning');
                showToast('Please log in or provide an API key to upload', 'warning');
                return;
            }

            // Ensure the requested pipeline mode is recorded
            if (mode) targetPipelineMode = mode;

            const fileInput = document.getElementById('fileInput');
            const targetLangSelect = document.getElementById('targetLanguage');
            const sourceLangSelect = document.getElementById('sourceLanguage');
            
            if (!fileInput.files || !fileInput.files[0]) {
                return;
            }
            
            // Client-side validation: target language is required for translation pipelines only
            if (targetPipelineMode !== 'transcribe' && (!targetLangSelect || !targetLangSelect.value)) {
                const warningEl = document.getElementById('languageWarning');
                if (warningEl) warningEl.classList.remove('hidden');
                if (targetLangSelect) {
                    targetLangSelect.classList.add('border-red-500', 'focus:ring-red-500', 'focus:border-red-500');
                    targetLangSelect.scrollIntoView({ behavior: 'smooth', block: 'center' });
                }
                log('Upload blocked: target language is required.', 'warning');
                return;
            }

            const formData = new FormData();
            formData.append('file', fileInput.files[0]);
            // Transcribe-only does not need a real target language, but the backend
            // requires a non-empty value. Re-use the source language as a placeholder.
            const effectiveTargetLanguage = targetPipelineMode === 'transcribe'
                ? (sourceLangSelect.value || 'auto')
                : targetLangSelect.value;
            formData.append('target_language', effectiveTargetLanguage);
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
                if (projectLangsEl) {
                    projectLangsEl.textContent = targetPipelineMode === 'transcribe'
                        ? `${sourceLang} (transcribe only)`
                        : `${sourceLang} → ${targetLang}`;
                }
                
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

                // Auto-start transcription for every pipeline path
                processFile();

            } catch (err) {
                const errorMsg = err.message || 'Upload failed';
                log('Upload failed: ' + errorMsg, 'error');
            }
        }

        // Process file handler (handles both video transcription and text parsing)
        async function processFile() {
            if (!currentVideoId) return;

            // Target language is only required for pipelines that translate
            if (targetPipelineMode !== 'transcribe') {
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
            }

            // Collapse setup config panel once processing starts
            const setupPanel = document.getElementById('setupConfigPanel');
            if (setupPanel) setupPanel.classList.add('hidden');

            // Reset state for new job
            currentJobId = null;
            isJobRunning = true;
            hasStartedProcessing = false;

            const isTextFile = currentFileType === 'text';

            log(isTextFile ? 'Starting text parsing...' : 'Starting OpenAI Cloud transcription...');

            try {
                const response = await fetch(`/videos/${currentVideoId}/transcribe?method=whisper&provider=openai`, {
                    method: 'POST'
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
                if (data.job_id) {
                    currentJobId = data.job_id;
                }

                // Text files are parsed synchronously; there is no background job
                // and therefore no WebSocket job_complete. Advance the UI immediately.
                if (isTextFile && data.status) {
                    const normalizedStatus = data.status === 'completed' || data.status === 'awaiting_choice' ? 'transcribed' : data.status;
                    updateStatus({ status: normalizedStatus, progress_percent: 100 });
                    updateButtonVisibility(normalizedStatus);
                    // For text translations, run the full pipeline (terminology +
                    // translation) since there is no Celery event to trigger it.
                    if (targetPipelineMode !== 'transcribe') {
                        log('Auto-advancing to text translation...');
                        setTimeout(() => translateVideo(), 0);
                    } else {
                        fetch()
                            .then(r => r.json())
                            .then(data => {
                                if (data.segments) renderTextPreview(data.segments);
                            })
                            .catch(err => console.error('Failed to load text preview:', err));
                    }
                    return;
                }

                // Do not update the UI to "transcribed" here. The real completion
                // (and the next pipeline step) is driven by WebSocket job_complete
                // or the HTTP polling fallback.
                await connectWebSocket(currentVideoId);

            } catch (err) {
                log((isTextFile ? 'Parsing' : 'Transcription') + ' failed: ' + err.message, 'error');
            }
        }

        // Analyze handler (Multi-Agent Step 1)
        async function analyzeVideo() {
            if (!currentVideoId) return;
            
            // Reset state for new job
            currentJobId = null;
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
                if (data.job_id) {
                    currentJobId = data.job_id;
                }

                // The real completion and next UI state are driven by WebSocket.
            } catch (err) {
                log('Analysis failed: ' + err.message, 'error');
            }
        }

        // Translate handler (Multi-Agent Step 2)
        async function translateVideo() {
            if (!currentVideoId) return;
            
            // Reset state for new job
            currentJobId = null;
            isJobRunning = true;
            hasStartedProcessing = false;
            
            log('Starting OpenAI Translator Agent...');
            log('Using sliding window translation with glossary constraints');
            
            try {
                const response = await fetch(`/videos/${currentVideoId}/translate`, {
                    method: 'POST'
                });
                
                if (!response.ok) {
                    const err = await response.json();
                    throw new Error(err.detail || 'Translation failed');
                }
                
                const data = await response.json();
                if (data.job_id) {
                    currentJobId = data.job_id;
                }

                // The real completion and next UI state are driven by WebSocket.
            } catch (err) {
                log('Translation failed: ' + err.message, 'error');
            }
        }

        async function skipAndTranslate() {
            if (!currentVideoId) return;
            
            // Reset state for new job
            currentJobId = null;
            isJobRunning = true;
            hasStartedProcessing = false;
            
            log('Skipping terminology review and starting translation...');
            
            try {
                const response = await fetch(`/videos/${currentVideoId}/translate-direct`, {
                    method: 'POST'
                });
                
                if (!response.ok) {
                    const err = await response.json();
                    throw new Error(err.detail || 'Translation failed');
                }
                
                const data = await response.json();
                if (data.job_id) {
                    currentJobId = data.job_id;
                }

                // The real completion and next UI state are driven by WebSocket.
            } catch (err) {
                log('Translation failed: ' + err.message, 'error');
            }
        }

        // Helper: extract filename from Content-Disposition header
        function getFilenameFromHeader(response, fallback) {
            const header = response.headers.get('Content-Disposition');
            if (!header) return fallback;
            const match = header.match(/filename="?([^"]+)"?/);
            return match ? match[1] : fallback;
        }

        // Ensure any pending segment edit is saved before we trigger a download.
        async function flushPendingEdits() {
            const active = document.activeElement;
            if (
                active &&
                (active.classList.contains('timecode-input') ||
                    active.getAttribute('contenteditable') === 'true')
            ) {
                active.blur();
            }

            const start = Date.now();
            while (isSavingSegment && Date.now() - start < 3000) {
                await new Promise(resolve => setTimeout(resolve, 50));
            }
        }

        // Generic export handler
        async function exportFormat(format) {
            if (!currentVideoId) return;

            await flushPendingEdits();

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
                a.style.display = 'none';
                const fallback = `translation_${currentVideoId.substring(0, 8)}.${format}`;
                a.download = getFilenameFromHeader(response, fallback);
                document.body.appendChild(a);
                a.click();

                // Give the browser a moment to start the download before
                // cleaning up the anchor and revoking the blob URL.
                setTimeout(() => {
                    a.remove();
                    window.URL.revokeObjectURL(url);
                }, 1000);

                log(`${formatNames[format]} exported`, 'success');
                
            } catch (err) {
                log('Export failed: ' + err.message, 'error');
            }
        }

        // Download original transcription handler
        async function downloadTranscription() {
            if (!currentVideoId) return;

            await flushPendingEdits();

            try {
                const response = await fetch(`/export/${currentVideoId}/transcription`);
                
                if (!response.ok) throw new Error('Download failed');
                
                const blob = await response.blob();
                const url = window.URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.style.display = 'none';
                const fallback = `transcription_${currentVideoId.substring(0, 8)}.srt`;
                a.download = getFilenameFromHeader(response, fallback);
                document.body.appendChild(a);
                a.click();

                // Delay cleanup so the browser has time to start the download.
                setTimeout(() => {
                    a.remove();
                    window.URL.revokeObjectURL(url);
                }, 1000);

                log('Transcription downloaded', 'success');
                
            } catch (err) {
                log('Download failed: ' + err.message, 'error');
            }
        }

        // Event listeners
        document.addEventListener('DOMContentLoaded', () => {
            // Auth: wire up modal UI
            const standardAuthForm = document.getElementById('standardAuthForm');
            const byokAuthForm = document.getElementById('byokAuthForm');
            const standardTab = document.getElementById('authTabStandard');
            const byokTab = document.getElementById('authTabByok');
            const authCloseBtn = document.getElementById('authCloseBtn');
            const authModeToggleBtn = document.getElementById('authModeToggleBtn');
            const logoutBtn = document.getElementById('logoutBtn');

            if (standardTab) standardTab.addEventListener('click', () => setAuthTab('standard'));
            if (byokTab) byokTab.addEventListener('click', () => setAuthTab('byok'));
            if (standardAuthForm) standardAuthForm.addEventListener('submit', handleStandardAuthSubmit);
            if (byokAuthForm) byokAuthForm.addEventListener('submit', handleByokSubmit);
            if (authModeToggleBtn) authModeToggleBtn.addEventListener('click', () => {
                setStandardMode(currentStandardMode === 'login' ? 'signup' : 'login');
            });
            if (authCloseBtn) authCloseBtn.addEventListener('click', showMainApp);
            if (logoutBtn) logoutBtn.addEventListener('click', logout);

            // Forgot / reset password
            const authForgotPasswordBtn = document.getElementById('authForgotPasswordBtn');
            const forgotPasswordForm = document.getElementById('forgotPasswordForm');
            const forgotPasswordBackBtn = document.getElementById('forgotPasswordBackBtn');
            const resetPasswordForm = document.getElementById('resetPasswordForm');
            if (authForgotPasswordBtn) authForgotPasswordBtn.addEventListener('click', showForgotPassword);
            if (forgotPasswordForm) forgotPasswordForm.addEventListener('submit', handleForgotPasswordSubmit);
            if (forgotPasswordBackBtn) forgotPasswordBackBtn.addEventListener('click', () => setAuthSubview('form'));
            if (resetPasswordForm) resetPasswordForm.addEventListener('submit', handleResetPasswordSubmit);

            // Show / hide password toggles
            setupPasswordToggles();

            // User menu dropdown
            const userMenuBtn = document.getElementById('userMenuBtn');
            const userMenuDropdown = document.getElementById('userMenuDropdown');
            if (userMenuBtn && userMenuDropdown) {
                userMenuBtn.addEventListener('click', (e) => {
                    e.stopPropagation();
                    userMenuDropdown.classList.toggle('hidden');
                });
                document.addEventListener('click', (e) => {
                    if (!userMenuBtn.contains(e.target) && !userMenuDropdown.contains(e.target)) {
                        userMenuDropdown.classList.add('hidden');
                    }
                });
            }

            // Profile modal
            const profileBtn = document.getElementById('profileBtn');
            const profileModal = document.getElementById('profileModal');
            const profileModalClose = document.getElementById('profileModalClose');
            if (profileBtn) profileBtn.addEventListener('click', openProfileModal);
            if (profileModalClose) profileModalClose.addEventListener('click', closeProfileModal);
            if (profileModal) {
                profileModal.addEventListener('click', (e) => {
                    if (e.target === profileModal) closeProfileModal();
                });
            }

            // Profile forms
            const profilePreferencesForm = document.getElementById('profileSavePreferencesBtn');
            if (profilePreferencesForm) profilePreferencesForm.addEventListener('click', savePreferences);
            const profileSaveApiModeBtn = document.getElementById('profileSaveApiModeBtn');
            if (profileSaveApiModeBtn) profileSaveApiModeBtn.addEventListener('click', saveApiKeyMode);
            const profileEmailForm = document.getElementById('profileEmailForm');
            if (profileEmailForm) profileEmailForm.addEventListener('submit', updateEmail);
            const profilePasswordForm = document.getElementById('profilePasswordForm');
            if (profilePasswordForm) profilePasswordForm.addEventListener('submit', changePassword);
            const profileLogoutAllBtn = document.getElementById('profileLogoutAllBtn');
            if (profileLogoutAllBtn) profileLogoutAllBtn.addEventListener('click', logoutAllSessions);
            const profileDeleteAccountBtn = document.getElementById('profileDeleteAccountBtn');
            if (profileDeleteAccountBtn) profileDeleteAccountBtn.addEventListener('click', openDeleteAccountModal);

            // API mode toggle shows/hides key input
            const profileModeStandard = document.getElementById('profileModeStandard');
            const profileModeByok = document.getElementById('profileModeByok');
            const profileByokKeyContainer = document.getElementById('profileByokKeyContainer');
            function updateByokKeyVisibility() {
                if (profileByokKeyContainer) {
                    profileByokKeyContainer.classList.toggle('hidden', !(profileModeByok && profileModeByok.checked));
                }
            }
            if (profileModeStandard) profileModeStandard.addEventListener('change', updateByokKeyVisibility);
            if (profileModeByok) profileModeByok.addEventListener('change', updateByokKeyVisibility);

            // Delete account modal
            const deleteAccountModal = document.getElementById('deleteAccountModal');
            const deleteAccountCancel = document.getElementById('deleteAccountCancel');
            const deleteAccountForm = document.getElementById('deleteAccountForm');
            if (deleteAccountCancel) deleteAccountCancel.addEventListener('click', closeDeleteAccountModal);
            if (deleteAccountForm) deleteAccountForm.addEventListener('submit', deleteAccount);
            if (deleteAccountModal) {
                deleteAccountModal.addEventListener('click', (e) => {
                    if (e.target === deleteAccountModal) closeDeleteAccountModal();
                });
            }

            // Usage pagination
            const profileUsagePrev = document.getElementById('profileUsagePrev');
            const profileUsageNext = document.getElementById('profileUsageNext');
            if (profileUsagePrev) {
                profileUsagePrev.addEventListener('click', () => {
                    if (profileUsageSkip > 0) {
                        profileUsageSkip -= profileUsageLimit;
                        loadProfileUsage();
                    }
                });
            }
            if (profileUsageNext) {
                profileUsageNext.addEventListener('click', () => {
                    if (profileUsageSkip + profileUsageLimit < profileUsageTotal) {
                        profileUsageSkip += profileUsageLimit;
                        loadProfileUsage();
                    }
                });
            }

            const loginBtn = document.getElementById('loginBtn');
            if (loginBtn) loginBtn.addEventListener('click', () => {
                showAuthView('standard', 'signup');
            });

            const resendVerifyBtn = document.getElementById('resendVerifyBtn');
            const recheckVerifyBtn = document.getElementById('recheckVerifyBtn');
            if (resendVerifyBtn) resendVerifyBtn.addEventListener('click', resendVerificationEmail);
            if (recheckVerifyBtn) recheckVerifyBtn.addEventListener('click', recheckVerification);

            // Close modal when clicking the backdrop
            const authView = document.getElementById('authView');
            if (authView) {
                authView.addEventListener('click', (e) => {
                    if (e.target === authView) showMainApp();
                });
            }

            // Close modal with Escape key.
            document.addEventListener('keydown', (e) => {
                if (e.key !== 'Escape') return;
                if (deleteAccountModal && !deleteAccountModal.classList.contains('hidden')) {
                    closeDeleteAccountModal();
                    return;
                }
                if (profileModal && !profileModal.classList.contains('hidden')) {
                    closeProfileModal();
                    return;
                }
                if (authView && !authView.classList.contains('hidden')) {
                    showMainApp();
                }
            });

            // Handle email verification links clicked from the user's inbox.
            // Supports both legacy ?token= and welcome-email ?verify_token= params.
            (async () => {
                const params = new URLSearchParams(window.location.search);
                const path = window.location.pathname;

                // Password reset links use /?reset_token=...
                const resetToken = params.get('reset_token');
                if (resetToken) {
                    showResetPassword(resetToken);
                    window.history.replaceState({}, '', '/');
                    return;
                }

                const verifyToken = params.get('verify_token') || params.get('token');
                if (verifyToken) {
                    try {
                        const response = await fetch(`/api/auth/verify?token=${encodeURIComponent(verifyToken)}`);
                        if (response.ok) {
                            showToast('Email verified successfully', 'success');
                            // The backend sets the HttpOnly auth cookie; refresh the session.
                            const loaded = await loadUser();
                            if (loaded) {
                                showMainApp();
                                window.history.replaceState({}, '', '/');
                                return;
                            }
                            // Otherwise fall through to login prompt.
                            showAuthView('standard', 'login');
                        } else {
                            const data = await response.json().catch(() => ({}));
                            showToast(data.detail || 'Verification link is invalid or expired', 'error');
                            showAuthView('standard', 'login');
                        }
                    } catch (err) {
                        console.error('Verification failed:', err);
                        showToast('Verification failed. Please try logging in.', 'error');
                        showAuthView('standard', 'login');
                    }
                    // Remove token params from URL so a refresh doesn't re-verify.
                    params.delete('verify_token');
                    params.delete('token');
                    const newUrl = params.toString()
                        ? `${window.location.pathname}?${params.toString()}`
                        : window.location.pathname;
                    window.history.replaceState({}, '', newUrl);
                }
            })();

            // Determine initial view based on the HttpOnly cookie or BYOK API key.
            (async () => {
                const loaded = await loadUser();
                if (!loaded) {
                    updateUserDisplay();
                }
            })();

            // Language dropdown population with Tom Select
            const sourceLanguageSelect = document.getElementById('sourceLanguage');
            const targetLanguageSelect = document.getElementById('targetLanguage');

            function buildNativeLanguageOptions() {
                const formatOption = (lang) =>
                    `<option value="${lang.code}">${lang.name} — ${lang.nativeName}</option>`;

                return SUPPORTED_LANGUAGES.map(formatOption).join('');
            }

            function initLanguageDropdown(selectElement, firstOption, initialValue) {
                if (!selectElement) return null;

                const nativeOptions = buildNativeLanguageOptions();
                const disabledAttr = firstOption.disabled ? 'disabled' : '';
                const selectedAttr = firstOption.selected ? 'selected' : '';
                selectElement.innerHTML =
                    `<option value="${firstOption.value}" ${disabledAttr} ${selectedAttr}>${firstOption.label}</option>` +
                    nativeOptions;
                selectElement.value = initialValue;

                if (typeof TomSelect === 'undefined') {
                    // Fallback to native select if Tom Select is not loaded.
                    return selectElement;
                }

                const options = [];
                const optgroups = [];

                // First option (Auto-detect / placeholder)
                options.push({
                    code: firstOption.value,
                    display: firstOption.label,
                    name: firstOption.label,
                    nativeName: '',
                    group: 'top',
                });
                optgroups.push({ value: 'top', label: '' });

                // All languages in one alphabetical list (searchable by name or native name)
                SUPPORTED_LANGUAGES.forEach((lang) => {
                    options.push({
                        code: lang.code,
                        display: `${lang.name} — ${lang.nativeName}`,
                        name: lang.name,
                        nativeName: lang.nativeName,
                        group: 'all',
                    });
                });
                optgroups.push({ value: 'all', label: 'Languages' });

                const tom = new TomSelect(selectElement, {
                    options,
                    optgroups,
                    optgroupField: 'group',
                    valueField: 'code',
                    labelField: 'display',
                    searchField: ['name', 'nativeName'],
                    placeholder: firstOption.label,
                    allowEmptyOption: true,
                    sortField: [{ field: '$order' }],
                    render: {
                        option: (data, escape) =>
                            `<div class="py-1 px-2">${escape(data.display)}</div>`,
                        item: (data, escape) => `<div>${escape(data.display)}</div>`,
                    },
                });

                tom.setValue(initialValue);

                // Keep the underlying native select synchronized so legacy
                // code that reads selectElement.value continues to work.
                tom.on('change', (value) => {
                    selectElement.value = value || '';
                });

                return tom;
            }

            const sourceTom = initLanguageDropdown(
                sourceLanguageSelect,
                { value: 'auto', label: 'Auto-detect' },
                'auto'
            );
            const targetTom = initLanguageDropdown(
                targetLanguageSelect,
                { value: '', label: 'Select target language...', disabled: true, selected: true },
                ''
            );

            // Expose the underlying selects for code that expects them.
            window.termsubSourceLanguage = sourceLanguageSelect;
            window.termsubTargetLanguage = targetLanguageSelect;

            // --- Help panel toggle ---
            const helpBtn = document.getElementById('helpBtn');
            const helpCloseBtn = document.getElementById('helpCloseBtn');
            const howToPanel = document.getElementById('howToPanel');

            function toggleHelpPanel(show) {
                if (!howToPanel) return;
                const willShow = show === undefined ? howToPanel.classList.contains('hidden') : show;
                howToPanel.classList.toggle('hidden', !willShow);
            }

            if (helpBtn && howToPanel) {
                helpBtn.addEventListener('click', () => toggleHelpPanel());
            }
            if (helpCloseBtn && howToPanel) {
                helpCloseBtn.addEventListener('click', () => toggleHelpPanel(false));
            }
            // Close when clicking outside the panel or the help button
            document.addEventListener('click', (e) => {
                if (!howToPanel || howToPanel.classList.contains('hidden')) return;
                if (!howToPanel.contains(e.target) && e.target !== helpBtn && !helpBtn?.contains(e.target)) {
                    toggleHelpPanel(false);
                }
            });

            // --- Activity Log Collapse ---
            const activityLogToggle = document.getElementById('activityLogToggle');
            const activityLogContainer = document.getElementById('activityLogContainer');
            if (activityLogToggle && activityLogContainer) {
                activityLogToggle.addEventListener('click', () => {
                    const collapsed = activityLogContainer.classList.toggle('activity-log-collapsed');
                    activityLogToggle.setAttribute('aria-expanded', (!collapsed).toString());
                    if (!collapsed) {
                        // Expand downward: scroll the fully-open log into view so it
                        // clearly opens below the toggle instead of appearing to push
                        // earlier content upward out of sight.
                        setTimeout(() => {
                            activityLogContainer.scrollIntoView({ behavior: 'smooth', block: 'end' });
                        }, 50);
                    }
                });
            }

            // Clicking the "Open activity log" link in the status line expands the log
            const statusBadgeEl = document.getElementById('statusBadge');
            if (statusBadgeEl) {
                statusBadgeEl.addEventListener('click', (e) => {
                    if (e.target.matches('[data-open-activity-log]')) {
                        e.preventDefault();
                        expandActivityLog();
                    }
                });
            }

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
                    updatePipelineButtonsForFileType();
                }
            });
            
            // Drag & Drop handlers
            const dropZone = document.getElementById('dropZone');
            if (dropZone) {
                ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
                    dropZone.addEventListener(eventName, (e) => {
                        e.preventDefault();
                        e.stopPropagation();
                    }, false);
                });
                
                ['dragenter', 'dragover'].forEach(eventName => {
                    dropZone.addEventListener(eventName, () => {
                        dropZone.classList.add('border-blue-400', 'bg-blue-50', 'dark:bg-blue-900/20');
                    }, false);
                });
                
                ['dragleave', 'drop'].forEach(eventName => {
                    dropZone.addEventListener(eventName, () => {
                        dropZone.classList.remove('border-blue-400', 'bg-blue-50', 'dark:bg-blue-900/20');
                    }, false);
                });
                
                dropZone.addEventListener('drop', (e) => {
                    const files = e.dataTransfer.files;
                    if (files && files.length > 0) {
                        const dt = new DataTransfer();
                        dt.items.add(files[0]);
                        fileInput.files = dt.files;
                        fileInput.dispatchEvent(new Event('change'));
                    }
                }, false);
            }
            
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

            // Pipeline buttons
            document.getElementById('translateSubtitlesBtn').addEventListener('click', () => {
                if (currentFileType === 'text') {
                    // Text pipeline: parse first, then terminology/translation.
                    processFile();
                    return;
                }
                const reviewTerms = document.getElementById('reviewTerminologyCheckbox').checked;
                const mode = reviewTerms ? 'terminology' : 'subtitles';
                startPipeline(mode);
            });
            document.getElementById('originalSubtitlesBtn').addEventListener('click', () => startPipeline('transcribe'));
            document.getElementById('startNewProjectBtn').addEventListener('click', resetApp);

            // Undo button click
            const undoBtn = document.getElementById('undoTimelineBtn');
            if (undoBtn) undoBtn.addEventListener('click', undoTimeline);

            // Keyboard shortcut: Ctrl+Z / Cmd+Z for undo
            document.addEventListener('keydown', (e) => {
                if ((e.ctrlKey || e.metaKey) && e.key === 'z' && !e.shiftKey) {
                    e.preventDefault();
                    undoTimeline();
                }
            });
            
            // Global Find & Replace handler (subtitle timeline)
            document.getElementById('replaceAllBtn').addEventListener('click', async () => {
                if (!currentVideoId || isSavingSegment) return;
                pushTimelineHistory();
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

            // Text-file Find & Replace handler
            document.getElementById('replaceAllBtnText').addEventListener('click', async () => {
                if (!currentVideoId || isSavingSegment) return;
                if (currentFileType !== 'text') return;
                pushTimelineHistory();
                const findInput = document.getElementById('findInputText');
                const replaceInput = document.getElementById('replaceInputText');
                const replaceBtn = document.getElementById('replaceAllBtnText');
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
                    if (data.segments) renderTextPreview(data.segments);
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

            // Text-only export handler
            document.getElementById('exportTxtOnlyBtn').addEventListener('click', () => exportFormat('txt'));
            document.getElementById('exportSrtBtn').addEventListener('click', () => exportFormat('srt'));
            document.getElementById('exportVttBtn').addEventListener('click', () => exportFormat('vtt'));
            document.getElementById('exportTxtBtn').addEventListener('click', () => exportFormat('txt'));
            document.getElementById('exportJsonBtn').addEventListener('click', () => exportFormat('json'));

            // Admin dashboard handlers
            const adminRefreshBtn = document.getElementById('adminRefreshBtn');
            if (adminRefreshBtn) {
                adminRefreshBtn.addEventListener('click', loadAdminDashboard);
            }

            const adminHomeBtn = document.getElementById('adminHomeBtn');
            if (adminHomeBtn) {
                adminHomeBtn.addEventListener('click', () => {
                    hideAdminView();
                    history.pushState(null, '', '/');
                });
            }

            const adminUsersTable = document.getElementById('adminUsersTable');
            if (adminUsersTable) {
                adminUsersTable.addEventListener('click', (e) => {
                    const btn = e.target.closest('[data-admin-action]');
                    if (!btn) return;
                    const action = btn.getAttribute('data-admin-action');
                    const userId = btn.getAttribute('data-user-id');
                    if (action && userId) handleAdminAction(action, userId);
                });
            }

            // Route handling
            async function handleRoute() {
                const path = window.location.pathname;
                const params = new URLSearchParams(window.location.search);
                const videoId = params.get('video');

                if (path === '/admin') {
                    showAdminView();
                    return;
                }

                hideAdminView();
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
                await connectWebSocket(videoId);
                
                // Fetch current status
                fetch(`/videos/${videoId}`)
                    .then(r => r.json())
                    .then(data => {
                        // Treat "awaiting_choice" as "transcribed" on direct page loads too
                        if (data.status === 'awaiting_choice') {
                            data.status = 'transcribed';
                        }
                        updateStatus(data);
                        updateButtonVisibility(data.status);
                        if ((data.status === 'transcribed' || data.status === 'completed') && data.segments) {
                            renderSubtitleTimeline(data.segments);
                        }
                    });
                }
            }

            window.addEventListener('popstate', handleRoute);
            handleRoute();
        });
