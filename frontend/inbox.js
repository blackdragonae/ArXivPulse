(function initInboxModule(global) {
    const DEFAULT_UNIFIED_INBOX_STATE = {
        versionScope: 'watchlist',
        versionDays: 30,
        limit: 80,
        kinds: ['alert', 'version_update', 'follow_up', 'digest'],
        sort: 'recent',
        viewMode: 'all',
        focusLimit: 12,
    };

    function createInboxModule(deps) {
        if (!deps || typeof deps.getState !== 'function' || typeof deps.setState !== 'function') {
            throw new Error('Inbox module requires getState/setState dependencies.');
        }
        if (typeof deps.apiFetchJson !== 'function') {
            throw new Error('Inbox module requires apiFetchJson dependency.');
        }

        const documentRef = deps.documentRef || global.document;
        const windowRef = deps.windowRef || global;
        const fetchImpl = typeof deps.fetchImpl === 'function'
            ? deps.fetchImpl
            : (typeof global.fetch === 'function' ? global.fetch.bind(global) : null);
        if (!fetchImpl) {
            throw new Error('Inbox module requires fetch implementation.');
        }

        function currentState() {
            return deps.getState() || {};
        }

        function patchState(patch) {
            deps.setState(patch || {});
        }

        function getApiBase() {
            return String(currentState().apiBase || '/api');
        }

        function escapeHtml(value) {
            if (typeof deps.escapeHtml === 'function') {
                return deps.escapeHtml(value);
            }
            return String(value || '')
                .replace(/&/g, '&amp;')
                .replace(/</g, '&lt;')
                .replace(/>/g, '&gt;')
                .replace(/"/g, '&quot;')
                .replace(/'/g, '&#39;');
        }

        function formatIsoShort(value) {
            if (typeof deps.formatIsoShort === 'function') {
                return deps.formatIsoShort(value);
            }
            return String(value || '').slice(0, 16).replace('T', ' ');
        }

        function alertUser(message) {
            if (typeof deps.alertUser === 'function') {
                deps.alertUser(message);
                return;
            }
            if (typeof windowRef.alert === 'function') {
                windowRef.alert(message);
            }
        }

        async function refreshAllBadges(options = {}) {
            if (typeof deps.refreshAllBadges === 'function') {
                await deps.refreshAllBadges(options);
            }
        }

        async function refreshUnifiedInboxBadge() {
            if (typeof deps.refreshUnifiedInboxBadge === 'function') {
                await deps.refreshUnifiedInboxBadge();
            }
        }

        function setUnifiedInboxStatus(text, isError = false) {
            const el = documentRef.getElementById('unifiedInboxStatus');
            if (!el) return;
            el.style.color = isError ? 'var(--danger)' : 'var(--text-muted)';
            el.textContent = text || '';
        }

        function encodeInboxPayload(payload) {
            try {
                return encodeURIComponent(JSON.stringify(payload || {}));
            } catch (_) {
                return encodeURIComponent('{}');
            }
        }

        function decodeInboxPayload(payloadJson) {
            if (!payloadJson) return {};
            try {
                return JSON.parse(payloadJson);
            } catch (_) {
                return {};
            }
        }

        function getUnifiedInboxState() {
            const state = currentState();
            const raw = state.unifiedInboxState && typeof state.unifiedInboxState === 'object'
                ? state.unifiedInboxState
                : DEFAULT_UNIFIED_INBOX_STATE;
            const versionScopeRaw = String(raw.versionScope || DEFAULT_UNIFIED_INBOX_STATE.versionScope).toLowerCase();
            const sortRaw = String(raw.sort || DEFAULT_UNIFIED_INBOX_STATE.sort).toLowerCase();
            const viewRaw = String(raw.viewMode || DEFAULT_UNIFIED_INBOX_STATE.viewMode).toLowerCase();
            return {
                versionScope: ['watchlist', 'liked', 'bookmarked', 'new'].includes(versionScopeRaw)
                    ? versionScopeRaw
                    : DEFAULT_UNIFIED_INBOX_STATE.versionScope,
                versionDays: Math.max(1, Math.min(180, Number(raw.versionDays || DEFAULT_UNIFIED_INBOX_STATE.versionDays))),
                limit: Math.max(10, Math.min(200, Number(raw.limit || DEFAULT_UNIFIED_INBOX_STATE.limit))),
                kinds: Array.isArray(raw.kinds) ? raw.kinds.map((k) => String(k).toLowerCase()) : [...DEFAULT_UNIFIED_INBOX_STATE.kinds],
                sort: sortRaw === 'priority' ? 'priority' : 'recent',
                viewMode: viewRaw === 'focus' ? 'focus' : 'all',
                focusLimit: Math.max(1, Math.min(80, Number(raw.focusLimit || DEFAULT_UNIFIED_INBOX_STATE.focusLimit))),
            };
        }

        function setUnifiedInboxState(nextState) {
            const next = nextState && typeof nextState === 'object'
                ? { ...DEFAULT_UNIFIED_INBOX_STATE, ...nextState }
                : { ...DEFAULT_UNIFIED_INBOX_STATE };
            patchState({ unifiedInboxState: next });
            return next;
        }

        function getUnifiedInboxSelectedItems() {
            const state = currentState();
            if (state.unifiedInboxSelectedItems instanceof Map) {
                return state.unifiedInboxSelectedItems;
            }
            const map = new Map();
            patchState({ unifiedInboxSelectedItems: map });
            return map;
        }

        function setUnifiedInboxSelectedItems(map) {
            patchState({ unifiedInboxSelectedItems: map instanceof Map ? map : new Map() });
        }

        function getUnifiedInboxVisibleItems() {
            const items = currentState().unifiedInboxVisibleItems;
            return Array.isArray(items) ? items : [];
        }

        function setUnifiedInboxVisibleItems(items) {
            patchState({ unifiedInboxVisibleItems: Array.isArray(items) ? items : [] });
        }

        function getDayRunPresetsCache() {
            const rows = currentState().dayRunPresetsCache;
            return Array.isArray(rows) ? rows : [];
        }

        function setDayRunPresetsCache(rows) {
            patchState({ dayRunPresetsCache: Array.isArray(rows) ? rows : [] });
        }

        function getDayRunHistoryCache() {
            const rows = currentState().dayRunHistoryCache;
            return Array.isArray(rows) ? rows : [];
        }

        function setDayRunHistoryCache(rows) {
            patchState({ dayRunHistoryCache: Array.isArray(rows) ? rows : [] });
        }

        let fetchCooldownUntilMs = Number(currentState().fetchCooldownUntilMs || 0);
        let fetchCooldownLabel = String(currentState().fetchCooldownLabel || '');
        let fetchRetryActive = Boolean(currentState().fetchRetryActive);
        let fetchCooldownTimer = null;
        let fetchStatusPollTimer = null;
        let fetchStatusInFlight = false;

        function parseRetryAfterSeconds(payload, response) {
            const fromPayload = Number(payload && payload.retry_after_seconds ? payload.retry_after_seconds : 0);
            if (Number.isFinite(fromPayload) && fromPayload > 0) return fromPayload;
            const retry = payload && payload.retry && typeof payload.retry === 'object' ? payload.retry : null;
            const fromRetryPayload = Number(retry && retry.remaining_seconds ? retry.remaining_seconds : 0);
            if (Number.isFinite(fromRetryPayload) && fromRetryPayload > 0) return fromRetryPayload;
            const fromHeader = Number(response && response.headers ? response.headers.get('Retry-After') : 0);
            if (Number.isFinite(fromHeader) && fromHeader > 0) return fromHeader;
            return 0;
        }

        function parseErrorRetryAfter(err) {
            const fromErr = Number(err && err.retryAfterSeconds ? err.retryAfterSeconds : 0);
            if (Number.isFinite(fromErr) && fromErr > 0) return fromErr;
            return parseRetryAfterSeconds(err && err.payload ? err.payload : null, null);
        }

        function formatCountdownLabel(totalSeconds) {
            const sec = Math.max(0, Number(totalSeconds || 0));
            const mm = Math.floor(sec / 60);
            const ss = sec % 60;
            return `${String(mm).padStart(2, '0')}:${String(ss).padStart(2, '0')}`;
        }

        function getFetchCooldownRemainingSeconds() {
            if (!fetchCooldownUntilMs || fetchCooldownUntilMs <= 0) return 0;
            const remaining = Math.ceil((fetchCooldownUntilMs - Date.now()) / 1000);
            return Math.max(0, remaining);
        }

        function renderFetchCooldownHint() {
            const hintEl = documentRef.getElementById('fetchCooldownHint');
            const fetchBtnEl = documentRef.getElementById('fetchBtn');
            const dailyBtnEl = documentRef.getElementById('dailyFetchBtn');
            const remaining = getFetchCooldownRemainingSeconds();
            const active = remaining > 0 || fetchRetryActive;

            if (fetchBtnEl && fetchBtnEl.dataset.fetching !== '1') {
                fetchBtnEl.disabled = active;
            }
            if (dailyBtnEl && dailyBtnEl.dataset.fetching !== '1') {
                dailyBtnEl.disabled = active;
            }

            if (!hintEl) return;
            if (!active) {
                hintEl.style.display = 'none';
                hintEl.textContent = '';
                return;
            }

            if (remaining > 0) {
                const prefix = fetchCooldownLabel || (fetchRetryActive ? 'Auto-retry in' : 'Cooldown');
                hintEl.textContent = `${prefix}: ${formatCountdownLabel(remaining)}`;
            } else if (fetchRetryActive) {
                hintEl.textContent = 'Retry is running...';
            } else {
                hintEl.textContent = 'Fetch temporarily unavailable.';
            }
            hintEl.style.display = 'inline-flex';
        }

        function stopFetchCooldownTimer() {
            if (fetchCooldownTimer) {
                clearInterval(fetchCooldownTimer);
                fetchCooldownTimer = null;
            }
        }

        function startFetchCooldownTimer() {
            if (fetchCooldownTimer) return;
            fetchCooldownTimer = windowRef.setInterval(() => {
                const remaining = getFetchCooldownRemainingSeconds();
                if (remaining <= 0 && !fetchRetryActive) {
                    fetchCooldownUntilMs = 0;
                    fetchCooldownLabel = '';
                    patchState({
                        fetchCooldownUntilMs: 0,
                        fetchCooldownLabel: '',
                        fetchRetryActive: false,
                    });
                    stopFetchCooldownTimer();
                }
                renderFetchCooldownHint();
            }, 1000);
        }

        function setFetchCooldown(seconds, label = '', retryActive = false) {
            const sec = Math.max(0, Number(seconds || 0));
            fetchRetryActive = Boolean(retryActive);
            fetchCooldownLabel = String(label || '');
            fetchCooldownUntilMs = sec > 0 ? (Date.now() + sec * 1000) : 0;
            patchState({
                fetchCooldownUntilMs,
                fetchCooldownLabel,
                fetchRetryActive,
            });
            if (sec > 0 || fetchRetryActive) {
                startFetchCooldownTimer();
            } else {
                stopFetchCooldownTimer();
            }
            renderFetchCooldownHint();
        }

        function maybeApplyFetchBackoff(err, fallbackLabel = '') {
            const status = Number(err && err.status ? err.status : 0);
            let retryAfter = parseErrorRetryAfter(err);
            if (status === 409 && retryAfter <= 0) {
                retryAfter = 8;
            }
            const hasScheduledRetry = Boolean(err && err.payload && err.payload.retry_scheduled);
            if (retryAfter <= 0 && !hasScheduledRetry) return false;

            let label = fallbackLabel || 'Retry in';
            if (status === 429) label = 'Rate limit retry in';
            if (hasScheduledRetry) label = 'Auto-retry in';
            setFetchCooldown(retryAfter, label, hasScheduledRetry);
            return true;
        }

        async function fetchJsonOrThrow(url, options = {}) {
            const res = await fetchImpl(url, options);
            let data = null;
            try {
                data = await res.json();
            } catch (_) {
                data = null;
            }
            if (!res.ok) {
                const err = new Error((data && data.detail) ? data.detail : `HTTP ${res.status}`);
                err.status = res.status;
                err.retryAfterSeconds = parseRetryAfterSeconds(data, res);
                err.payload = data;
                throw err;
            }
            return data || {};
        }

        async function syncFetchStatus(options = {}) {
            const silent = options && options.silent === false ? false : true;
            if (fetchStatusInFlight) return;
            fetchStatusInFlight = true;
            try {
                const url = `${getApiBase()}/fetch/status?ts=${Date.now()}`;
                const data = await fetchJsonOrThrow(url, { method: 'GET', cache: 'no-store' });
                const pipeline = data && data.pipeline && typeof data.pipeline === 'object' ? data.pipeline : {};
                const retry = data && data.retry && typeof data.retry === 'object' ? data.retry : {};
                const cooldown = data && data.cooldown && typeof data.cooldown === 'object' ? data.cooldown : {};

                const retryStatus = String(retry.status || '').toLowerCase();
                const retryActive = retryStatus === 'scheduled' || retryStatus === 'running';
                const retryRemaining = Number(retry.remaining_seconds || 0);
                const cooldownRemaining = Number(cooldown.retry_after_seconds || 0);
                const remaining = Math.max(retryRemaining, cooldownRemaining);

                let label = '';
                if (retryStatus === 'scheduled') label = 'Auto-retry in';
                else if (retryStatus === 'running' || Boolean(pipeline.active)) label = 'Retry running';
                else if (cooldownRemaining > 0) label = 'Cooldown';

                setFetchCooldown(remaining, label, retryActive || Boolean(pipeline.active));
            } catch (e) {
                if (!silent) {
                    console.warn('Failed to sync fetch status', e);
                }
            } finally {
                fetchStatusInFlight = false;
            }
        }

        function startFetchStatusPolling() {
            if (fetchStatusPollTimer) return;
            fetchStatusPollTimer = windowRef.setInterval(() => {
                syncFetchStatus({ silent: true });
            }, 10000);
        }

        async function fetchNewPapers() {
            const button = documentRef.getElementById('fetchBtn');
            if (button) {
                button.disabled = true;
                button.dataset.fetching = '1';
                button.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Fetching...';
            }
            const dailyBtn = documentRef.getElementById('dailyFetchBtn');
            if (dailyBtn) {
                dailyBtn.disabled = true;
                dailyBtn.dataset.fetching = '1';
            }

            const dateInput = documentRef.getElementById('dateInput');
            const dateVal = dateInput ? dateInput.value : null;

            try {
                const payload = { max_results: 20 };
                if (dateVal) payload.date = dateVal;

                const data = await deps.apiFetchJson(`${getApiBase()}/fetch`, {
                    method: 'POST',
                    body: payload,
                    useCache: false,
                });
                alertUser(`Fetched ${data.fetched} papers from ${data.date}. ${data.new} are new.`);

                const dateDisplay = documentRef.getElementById('batchDateDisplay');
                if (dateDisplay) dateDisplay.textContent = `Latest Batch: ${data.date}`;

                patchState({ currentDateFilter: data.date });
                if (typeof deps.saveUIState === 'function') {
                    deps.saveUIState();
                }

                if (String(currentState().currentStatus || 'new') === 'new' && typeof deps.loadPapers === 'function') {
                    await deps.loadPapers();
                }
                await refreshAllBadges();
                await syncFetchStatus({ silent: true });
            } catch (err) {
                console.error('Fetch Error:', err);
                const status = Number(err && err.status ? err.status : 0);
                const retryAfter = parseErrorRetryAfter(err);
                const backoffApplied = maybeApplyFetchBackoff(err);
                if (status === 429) {
                    const waitLabel = retryAfter > 0 ? `${Math.ceil(retryAfter)}s` : 'a short wait';
                    alertUser(`arXiv rate limit reached. Please retry in ${waitLabel}.`);
                    await syncFetchStatus({ silent: true });
                    return;
                }
                if (status === 409) {
                    alertUser((err && err.message) ? err.message : 'Fetch already in progress. Please wait a moment and retry.');
                    await syncFetchStatus({ silent: true });
                    return;
                }
                if (backoffApplied) {
                    const waitLabel = retryAfter > 0 ? `${Math.ceil(retryAfter)}s` : 'a short wait';
                    alertUser(`Fetch failed. Auto-retry window: ${waitLabel}.`);
                    await syncFetchStatus({ silent: true });
                    return;
                }
                alertUser(`Error fetching papers: ${(err && err.message) || String(err)}\nCheck logs.`);
            } finally {
                if (button) {
                    delete button.dataset.fetching;
                    button.innerHTML = '<i class="fa-solid fa-cloud-arrow-down"></i> Fetch New';
                }
                if (dailyBtn) {
                    delete dailyBtn.dataset.fetching;
                }
                renderFetchCooldownHint();
            }
        }

        function setUnifiedInboxControlsFromState() {
            const unifiedState = getUnifiedInboxState();
            const scopeEl = documentRef.getElementById('unifiedInboxScope');
            const daysEl = documentRef.getElementById('unifiedInboxDays');
            const limitEl = documentRef.getElementById('unifiedInboxLimit');
            const sortEl = documentRef.getElementById('unifiedInboxSort');
            const viewEl = documentRef.getElementById('unifiedInboxViewMode');
            const focusEl = documentRef.getElementById('unifiedInboxFocusLimit');
            if (scopeEl) scopeEl.value = unifiedState.versionScope;
            if (daysEl) daysEl.value = String(unifiedState.versionDays);
            if (limitEl) limitEl.value = String(unifiedState.limit);
            if (sortEl) sortEl.value = unifiedState.sort;
            if (viewEl) viewEl.value = unifiedState.viewMode;
            if (focusEl) focusEl.value = String(unifiedState.focusLimit);
            const kinds = new Set(unifiedState.kinds.map((k) => String(k).toLowerCase()));
            const checks = [
                ['unifiedInboxKindAlert', 'alert'],
                ['unifiedInboxKindVersion', 'version_update'],
                ['unifiedInboxKindFollowup', 'follow_up'],
                ['unifiedInboxKindDigest', 'digest'],
            ];
            checks.forEach(([id, kind]) => {
                const el = documentRef.getElementById(id);
                if (el) el.checked = kinds.has(kind);
            });
        }

        function getUnifiedInboxKindsFromUi() {
            const checks = [
                ['unifiedInboxKindAlert', 'alert'],
                ['unifiedInboxKindVersion', 'version_update'],
                ['unifiedInboxKindFollowup', 'follow_up'],
                ['unifiedInboxKindDigest', 'digest'],
            ];
            return checks
                .filter(([id]) => Boolean(documentRef.getElementById(id) && documentRef.getElementById(id).checked))
                .map(([, kind]) => kind);
        }

        function readUnifiedInboxFiltersFromUi() {
            const unifiedState = getUnifiedInboxState();
            const scopeEl = documentRef.getElementById('unifiedInboxScope');
            const daysEl = documentRef.getElementById('unifiedInboxDays');
            const limitEl = documentRef.getElementById('unifiedInboxLimit');
            const sortEl = documentRef.getElementById('unifiedInboxSort');
            const viewEl = documentRef.getElementById('unifiedInboxViewMode');
            const focusEl = documentRef.getElementById('unifiedInboxFocusLimit');

            const rawScope = String((scopeEl && scopeEl.value) || unifiedState.versionScope || 'watchlist').toLowerCase();
            const versionScope = ['watchlist', 'liked', 'bookmarked', 'new'].includes(rawScope) ? rawScope : 'watchlist';
            const versionDays = Math.max(1, Math.min(180, Number((daysEl && daysEl.value) || unifiedState.versionDays || 30)));
            const limit = Math.max(10, Math.min(200, Number((limitEl && limitEl.value) || unifiedState.limit || 80)));
            const sort = String((sortEl && sortEl.value) || unifiedState.sort || 'recent').toLowerCase() === 'priority' ? 'priority' : 'recent';
            const viewMode = String((viewEl && viewEl.value) || unifiedState.viewMode || 'all').toLowerCase() === 'focus' ? 'focus' : 'all';
            const focusLimit = Math.max(1, Math.min(80, Number((focusEl && focusEl.value) || unifiedState.focusLimit || 12)));
            const kinds = getUnifiedInboxKindsFromUi();
            return { versionScope, versionDays, limit, kinds, sort, viewMode, focusLimit };
        }

        async function toggleUnifiedInboxKinds(checked) {
            ['unifiedInboxKindAlert', 'unifiedInboxKindVersion', 'unifiedInboxKindFollowup', 'unifiedInboxKindDigest']
                .forEach((id) => {
                    const el = documentRef.getElementById(id);
                    if (el) el.checked = Boolean(checked);
                });
            await refreshUnifiedInbox();
        }

        function buildUnifiedInboxSelectionItem(item) {
            const kind = String((item && item.kind) || '');
            return {
                id: String((item && item.id) || ''),
                kind,
                alert_id: item && item.alert_id != null ? Number(item.alert_id) : null,
                follow_id: item && item.follow_id != null ? String(item.follow_id) : null,
                digest_id: item && item.digest_id != null ? Number(item.digest_id) : null,
                paper_id: item && item.paper_id != null ? String(item.paper_id) : null,
                arxiv_base_id: item && item.arxiv_base_id != null ? String(item.arxiv_base_id) : null,
            };
        }

        function updateUnifiedInboxSelectionUi() {
            const selected = getUnifiedInboxSelectedItems();
            const count = selected.size;
            const countEl = documentRef.getElementById('unifiedInboxSelectionCount');
            if (countEl) countEl.textContent = `${count} selected`;
            const allBox = documentRef.getElementById('unifiedInboxSelectAll');
            if (allBox) {
                const visible = getUnifiedInboxVisibleItems().length;
                allBox.checked = visible > 0 && count > 0 && count >= visible;
                allBox.indeterminate = count > 0 && count < visible;
            }
        }

        function toggleUnifiedInboxItemSelection(payloadJson, checked) {
            const payload = decodeInboxPayload(payloadJson);
            const key = String(payload.id || '');
            if (!key) return;
            const selected = new Map(getUnifiedInboxSelectedItems());
            if (checked) {
                selected.set(key, payload);
            } else {
                selected.delete(key);
            }
            setUnifiedInboxSelectedItems(selected);
            updateUnifiedInboxSelectionUi();
        }

        function clearUnifiedInboxSelection() {
            setUnifiedInboxSelectedItems(new Map());
            updateUnifiedInboxSelectionUi();
            documentRef.querySelectorAll('.unified-inbox-item-check').forEach((el) => {
                el.checked = false;
            });
        }

        function toggleUnifiedInboxSelectAll(checked) {
            const want = Boolean(checked);
            if (!want) {
                clearUnifiedInboxSelection();
                return;
            }
            const selected = new Map(getUnifiedInboxSelectedItems());
            getUnifiedInboxVisibleItems().forEach((item) => {
                const payload = buildUnifiedInboxSelectionItem(item);
                const key = String(payload.id || '');
                if (key) selected.set(key, payload);
            });
            setUnifiedInboxSelectedItems(selected);
            documentRef.querySelectorAll('.unified-inbox-item-check').forEach((el) => {
                el.checked = true;
            });
            updateUnifiedInboxSelectionUi();
        }

        function normalizeUnifiedBulkAction(value) {
            const action = String(value || '').trim().toLowerCase();
            if (!action) return '';
            if (['seen', 'reviewed', 'dismiss', 'snooze', 'done', 'read'].includes(action)) return action;
            return '';
        }

        async function applyUnifiedInboxBulkAction() {
            const statusEl = documentRef.getElementById('unifiedInboxStatus');
            const selected = Array.from(getUnifiedInboxSelectedItems().values());
            if (!selected.length) {
                setUnifiedInboxStatus('Select at least one inbox item first.', true);
                return;
            }
            const actionEl = documentRef.getElementById('unifiedInboxBulkAction');
            const snoozeEl = documentRef.getElementById('unifiedInboxBulkSnoozeDays');
            const action = normalizeUnifiedBulkAction(actionEl ? actionEl.value : '');
            const snoozeDays = Math.max(1, Math.min(90, Number((snoozeEl && snoozeEl.value) || 3)));
            const items = selected.map((row) => {
                const item = { kind: row.kind };
                if (action) item.action = action;
                if (row.alert_id != null) item.alert_id = Number(row.alert_id);
                if (row.follow_id) item.follow_id = String(row.follow_id);
                if (row.digest_id != null) item.digest_id = Number(row.digest_id);
                if (row.paper_id) item.paper_id = String(row.paper_id);
                if (row.arxiv_base_id) item.arxiv_base_id = String(row.arxiv_base_id);
                if (action === 'snooze') item.snooze_days = snoozeDays;
                return item;
            });
            if (statusEl) statusEl.textContent = `Applying bulk action to ${items.length} items...`;

            try {
                const payload = {
                    action: action || null,
                    snooze_days: snoozeDays,
                    items,
                };
                const res = await fetchImpl(`${getApiBase()}/inbox/bulk-action`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload),
                });
                const data = await res.json();
                if (!res.ok) throw new Error(data.detail || 'Failed to apply bulk inbox action');
                const success = Number(data.success_count || 0);
                const failure = Number(data.failure_count || 0);
                setUnifiedInboxStatus(`Bulk action finished: ${success} succeeded, ${failure} failed.`);
                clearUnifiedInboxSelection();
                await refreshUnifiedInbox();
                await refreshAllBadges({ force: true });
            } catch (e) {
                setUnifiedInboxStatus(`Bulk action failed: ${e.message}`, true);
            }
        }

        function renderUnifiedInbox(payload) {
            const list = documentRef.getElementById('unifiedInboxList');
            if (!list) return;
            const counts = payload && payload.counts ? payload.counts : {};
            const total = Number((payload && payload.total) || 0);
            const items = Array.isArray(payload && payload.items) ? payload.items : [];
            setUnifiedInboxVisibleItems(items.slice());

            const selected = new Map(getUnifiedInboxSelectedItems());
            const visibleIds = new Set(items.map((item) => String((item && item.id) || '')).filter(Boolean));
            Array.from(selected.keys()).forEach((id) => {
                if (!visibleIds.has(id)) selected.delete(id);
            });
            setUnifiedInboxSelectedItems(selected);

            setUnifiedInboxStatus(
                `Total ${total} · Alerts ${Number(counts.alerts || 0)} · Versions ${Number(counts.version_updates || 0)} · Follow-ups ${Number(counts.follow_ups || 0)} · Digests ${Number(counts.digests || 0)}`
            );

            if (!items.length) {
                list.innerHTML = '<div style="text-align:center; color:var(--text-muted); padding:1rem;">Inbox is clear.</div>';
                updateUnifiedInboxSelectionUi();
                return;
            }

            list.innerHTML = items.map((item) => {
                const kind = String((item && item.kind) || '');
                const title = String((item && item.title) || (item && item.paper_id) || kind || 'Inbox item');
                const ts = String((item && (item.remind_at || item.created_at || item.published)) || '');
                const priorityScore = Math.max(0, Number((item && item.priority_score) || 0));
                const priorityReason = String((item && item.priority_reason) || '').trim();
                const selectionPayload = buildUnifiedInboxSelectionItem(item);
                const selectionKey = String(selectionPayload.id || '');
                const selectionJson = encodeInboxPayload(selectionPayload);
                const checked = selectionKey && selected.has(selectionKey) ? 'checked' : '';
                const priorityTag = priorityScore > 0
                    ? `<span class="unified-priority-chip" title="${escapeHtml(priorityReason || 'priority score')}">P${Math.round(priorityScore)}</span>`
                    : '';
                const kindTag = {
                    alert: '<span class="tag" style="background:rgba(245,158,11,0.2); color:#f59e0b;">alert</span>',
                    version_update: '<span class="tag" style="background:rgba(59,130,246,0.2); color:#93c5fd;">version</span>',
                    follow_up: '<span class="tag" style="background:rgba(139,92,246,0.2); color:#c4b5fd;">follow-up</span>',
                    digest: '<span class="tag" style="background:rgba(56,189,248,0.2); color:#7dd3fc;">digest</span>',
                }[kind] || `<span class="tag">${escapeHtml(kind || 'item')}</span>`;

                let meta = '';
                let details = '';
                let actions = '';

                if (kind === 'alert') {
                    meta = `${escapeHtml(String((item && item.alert_type) || 'alert'))}${ts ? ` · ${escapeHtml(ts.slice(0, 16).replace('T', ' '))}` : ''}`;
                    details = item && item.message
                        ? `<div style="font-size:0.88rem; color:var(--text-muted); margin-top:0.35rem;">${escapeHtml(String(item.message))}</div>`
                        : '';
                    const payloadSeen = encodeInboxPayload({ alert_id: Number((item && item.alert_id) || 0) });
                    actions = `
                        ${item && item.paper_id ? `<button class="btn-secondary" onclick="openNotesModal(decodeURIComponent('${encodeURIComponent(String(item.paper_id || ''))}'))" style="padding:0.3rem 0.65rem;"><i class="fa-solid fa-note-sticky"></i> Notes</button>` : ''}
                        ${item && item.alert_type === 'version' && item.paper_id ? `<button class="btn-secondary" onclick="openVersionModal(decodeURIComponent('${encodeURIComponent(String(item.paper_id || ''))}'))" style="padding:0.3rem 0.65rem;"><i class="fa-solid fa-code-compare"></i> Diff</button>` : ''}
                        <button class="btn-secondary" onclick="applyUnifiedInboxAction('alert','seen',decodeURIComponent('${payloadSeen}'))" style="padding:0.3rem 0.65rem;"><i class="fa-solid fa-eye"></i> Mark Seen</button>
                    `;
                } else if (kind === 'version_update') {
                    meta = `v${Number((item && item.from_version) || 0)} → v${Number((item && item.to_version) || 0)}${ts ? ` · ${escapeHtml(ts.slice(0, 10))}` : ''}`;
                    const changed = Array.isArray(item && item.changed_structure_fields) ? item.changed_structure_fields : [];
                    details = changed.length
                        ? `<div class="version-change-badges" style="margin-top:0.35rem;">${changed.slice(0, 6).map((name) => `<span class="tag version-change-tag">${escapeHtml(String(name))}</span>`).join('')}</div>`
                        : '';
                    const payloadReviewed = encodeInboxPayload({ arxiv_base_id: item && item.arxiv_base_id, paper_id: item && item.paper_id });
                    const payloadSnooze = encodeInboxPayload({ arxiv_base_id: item && item.arxiv_base_id, paper_id: item && item.paper_id, snooze_days: 3 });
                    const payloadDismiss = encodeInboxPayload({ arxiv_base_id: item && item.arxiv_base_id, paper_id: item && item.paper_id });
                    actions = `
                        <button class="btn-secondary" onclick="openVersionModal(decodeURIComponent('${encodeURIComponent(String((item && (item.paper_id || item.latest_id)) || ''))}'))" style="padding:0.3rem 0.65rem;"><i class="fa-solid fa-code-compare"></i> Diff</button>
                        <button class="btn-secondary" onclick="applyUnifiedInboxAction('version_update','reviewed',decodeURIComponent('${payloadReviewed}'))" style="padding:0.3rem 0.65rem;"><i class="fa-solid fa-check"></i> Reviewed</button>
                        <button class="btn-secondary" onclick="applyUnifiedInboxAction('version_update','snooze',decodeURIComponent('${payloadSnooze}'))" style="padding:0.3rem 0.65rem;"><i class="fa-solid fa-clock"></i> Snooze</button>
                        <button class="btn-secondary" onclick="applyUnifiedInboxAction('version_update','dismiss',decodeURIComponent('${payloadDismiss}'))" style="padding:0.3rem 0.65rem;"><i class="fa-solid fa-eye-slash"></i> Dismiss</button>
                    `;
                } else if (kind === 'follow_up') {
                    meta = `${ts ? `Due ${escapeHtml(ts.slice(0, 16).replace('T', ' '))}` : 'Due now'}`;
                    details = item && item.note
                        ? `<div style="font-size:0.88rem; color:var(--text-muted); margin-top:0.35rem;">${escapeHtml(String(item.note))}</div>`
                        : '';
                    const payloadDone = encodeInboxPayload({ follow_id: item && item.follow_id });
                    const payloadSnooze = encodeInboxPayload({ follow_id: item && item.follow_id, snooze_days: 3 });
                    actions = `
                        ${item && item.paper_id ? `<button class="btn-secondary" onclick="openNotesModal(decodeURIComponent('${encodeURIComponent(String(item.paper_id || ''))}'))" style="padding:0.3rem 0.65rem;"><i class="fa-solid fa-note-sticky"></i> Notes</button>` : ''}
                        <button class="btn-secondary" onclick="applyUnifiedInboxAction('follow_up','done',decodeURIComponent('${payloadDone}'))" style="padding:0.3rem 0.65rem;"><i class="fa-solid fa-check"></i> Done</button>
                        <button class="btn-secondary" onclick="applyUnifiedInboxAction('follow_up','snooze',decodeURIComponent('${payloadSnooze}'))" style="padding:0.3rem 0.65rem;"><i class="fa-solid fa-clock"></i> Snooze</button>
                    `;
                } else if (kind === 'digest') {
                    meta = `${escapeHtml(String((item && item.cadence) || 'daily'))}${ts ? ` · ${escapeHtml(ts.slice(0, 16).replace('T', ' '))}` : ''}`;
                    details = item && item.summary
                        ? `<div style="font-size:0.88rem; color:var(--text-muted); margin-top:0.35rem;">${escapeHtml(String(item.summary))}</div>`
                        : '';
                    const payloadRead = encodeInboxPayload({ digest_id: Number((item && item.digest_id) || 0) });
                    actions = `
                        <button class="btn-secondary" onclick="openDigestModal()" style="padding:0.3rem 0.65rem;"><i class="fa-solid fa-inbox"></i> Open Digests</button>
                        <button class="btn-secondary" onclick="applyUnifiedInboxAction('digest','read',decodeURIComponent('${payloadRead}'))" style="padding:0.3rem 0.65rem;"><i class="fa-solid fa-check"></i> Mark Read</button>
                    `;
                }

                const priorityDetail = priorityReason
                    ? `<div style="font-size:0.78rem; color:var(--text-muted); margin-top:0.25rem;">Priority: ${escapeHtml(priorityReason)}</div>`
                    : '';

                return `
                    <div class="unified-inbox-card">
                        <div style="display:flex; justify-content:space-between; gap:0.8rem; align-items:flex-start;">
                            <div style="flex:1;">
                                <div style="font-weight:700;">${escapeHtml(title)}</div>
                                <div style="font-size:0.83rem; color:var(--text-muted); margin-top:0.2rem;">${meta}</div>
                            </div>
                            <div style="display:flex; gap:0.4rem; align-items:center;">
                                ${priorityTag}
                                ${kindTag}
                                <label class="unified-inbox-select" style="font-size:0.8rem; color:var(--text-muted);">
                                    <input class="unified-inbox-item-check" type="checkbox" ${checked}
                                        onchange="toggleUnifiedInboxItemSelection(decodeURIComponent('${selectionJson}'), this.checked)">
                                    Select
                                </label>
                            </div>
                        </div>
                        ${priorityDetail}
                        ${details}
                        <div style="display:flex; gap:0.45rem; flex-wrap:wrap; margin-top:0.6rem;">${actions}</div>
                    </div>
                `;
            }).join('');

            updateUnifiedInboxSelectionUi();
        }

        function setDayRunStatus(text, isError = false) {
            const el = documentRef.getElementById('dayRunStatus');
            if (!el) return;
            el.style.color = isError ? 'var(--danger)' : 'var(--text-muted)';
            el.textContent = text || '';
        }

        function syncDayRunControlsFromTopBar() {
            const topDate = documentRef.getElementById('dateInput');
            const topForce = documentRef.getElementById('dailyFetchForceCheck');
            const modalDate = documentRef.getElementById('dayRunDateInput');
            const modalForce = documentRef.getElementById('dayRunForceCheck');
            if (modalDate && topDate && !modalDate.value) modalDate.value = topDate.value || '';
            if (modalForce && topForce) modalForce.checked = Boolean(topForce.checked);
        }

        function getDayRunPayloadFromUi() {
            const unifiedState = getUnifiedInboxState();
            const topDate = documentRef.getElementById('dateInput');
            const topForce = documentRef.getElementById('dailyFetchForceCheck');
            const dayRunDate = documentRef.getElementById('dayRunDateInput');
            const dayRunForce = documentRef.getElementById('dayRunForceCheck');
            const weekendEl = documentRef.getElementById('dayRunWeekendPolicy');
            const rulesScopeEl = documentRef.getElementById('dayRunRulesScope');
            const fetchEl = documentRef.getElementById('dayRunFetchCheck');
            const rulesEl = documentRef.getElementById('dayRunRulesCheck');
            const planEl = documentRef.getElementById('dayRunPlanCheck');
            const inboxRefreshEl = documentRef.getElementById('dayRunInboxRefreshCheck');

            const dateVal = String((dayRunDate && dayRunDate.value) || (topDate && topDate.value) || '').trim();
            const forceVal = Boolean((dayRunForce && dayRunForce.checked) || (topForce && topForce.checked));
            const weekendPolicy = String((weekendEl && weekendEl.value) || 'skip').toLowerCase() === 'run' ? 'run' : 'skip';
            const rulesScope = String((rulesScopeEl && rulesScopeEl.value) || 'all').toLowerCase();
            const payload = {
                date: dateVal || null,
                force: forceVal,
                weekend_policy: weekendPolicy,
                run_fetch: fetchEl ? Boolean(fetchEl.checked) : true,
                run_rules: rulesEl ? Boolean(rulesEl.checked) : true,
                run_reading_plan: planEl ? Boolean(planEl.checked) : true,
                run_inbox_refresh: inboxRefreshEl ? Boolean(inboxRefreshEl.checked) : true,
                run_inbox_rules_scope: ['papers', 'inbox', 'all'].includes(rulesScope) ? rulesScope : 'all',
                refresh_reading_plan: planEl ? Boolean(planEl.checked) : true,
                version_scope: unifiedState.versionScope || 'watchlist',
                version_days: Math.max(1, Math.min(180, Number(unifiedState.versionDays || 30))),
            };
            if (topDate) topDate.value = dateVal || '';
            if (topForce) topForce.checked = forceVal;
            return payload;
        }

        function findDayRunPresetById(presetId) {
            const pid = Number(presetId || 0);
            if (!pid) return null;
            return getDayRunPresetsCache().find((item) => Number((item && item.id) || 0) === pid) || null;
        }

        function applyDayRunOptionsToUi(options) {
            const unifiedState = getUnifiedInboxState();
            const opts = options && typeof options === 'object' ? options : {};
            const dayRunDate = documentRef.getElementById('dayRunDateInput');
            const dayRunForce = documentRef.getElementById('dayRunForceCheck');
            const weekendEl = documentRef.getElementById('dayRunWeekendPolicy');
            const rulesScopeEl = documentRef.getElementById('dayRunRulesScope');
            const fetchEl = documentRef.getElementById('dayRunFetchCheck');
            const rulesEl = documentRef.getElementById('dayRunRulesCheck');
            const planEl = documentRef.getElementById('dayRunPlanCheck');
            const inboxRefreshEl = documentRef.getElementById('dayRunInboxRefreshCheck');
            const topDate = documentRef.getElementById('dateInput');
            const topForce = documentRef.getElementById('dailyFetchForceCheck');

            const dateVal = String(opts.date || '').trim();
            if (dayRunDate && dateVal) dayRunDate.value = dateVal;
            if (dayRunForce && typeof opts.force === 'boolean') dayRunForce.checked = Boolean(opts.force);
            if (weekendEl) weekendEl.value = String(opts.weekend_policy || 'skip').toLowerCase() === 'run' ? 'run' : 'skip';
            if (rulesScopeEl) {
                const scope = String(opts.run_inbox_rules_scope || 'all').toLowerCase();
                rulesScopeEl.value = ['papers', 'inbox', 'all'].includes(scope) ? scope : 'all';
            }
            if (fetchEl && typeof opts.run_fetch === 'boolean') fetchEl.checked = Boolean(opts.run_fetch);
            if (rulesEl && typeof opts.run_rules === 'boolean') rulesEl.checked = Boolean(opts.run_rules);
            if (planEl && typeof opts.run_reading_plan === 'boolean') planEl.checked = Boolean(opts.run_reading_plan);
            if (inboxRefreshEl && typeof opts.run_inbox_refresh === 'boolean') inboxRefreshEl.checked = Boolean(opts.run_inbox_refresh);
            if (topDate && dateVal) topDate.value = dateVal;
            if (topForce && typeof opts.force === 'boolean') topForce.checked = Boolean(opts.force);

            const versionScope = String(opts.version_scope || '').toLowerCase();
            const versionDays = Number(opts.version_days || 0);
            const nextUnifiedState = { ...unifiedState };
            if (['watchlist', 'liked', 'bookmarked', 'new'].includes(versionScope)) {
                nextUnifiedState.versionScope = versionScope;
                const scopeEl = documentRef.getElementById('unifiedInboxScope');
                if (scopeEl) scopeEl.value = versionScope;
            }
            if (Number.isFinite(versionDays) && versionDays > 0) {
                const bounded = Math.max(1, Math.min(180, versionDays));
                nextUnifiedState.versionDays = bounded;
                const daysEl = documentRef.getElementById('unifiedInboxDays');
                if (daysEl) daysEl.value = String(bounded);
            }
            setUnifiedInboxState(nextUnifiedState);
        }

        function renderDayRunPresetSelect(items, selectedId = null) {
            const select = documentRef.getElementById('dayRunPresetSelect');
            if (!select) return;
            const rows = Array.isArray(items) ? items : [];
            const preferredId = Number(selectedId || select.value || 0);
            select.innerHTML = '<option value="">No preset selected</option>' + rows.map((item) => {
                const id = Number((item && item.id) || 0);
                const name = String((item && item.name) || `Preset ${id}`);
                const used = item && item.last_used_at ? ` · ${String(item.last_used_at).slice(0, 10)}` : '';
                return `<option value="${id}">${escapeHtml(name)}${escapeHtml(used)}</option>`;
            }).join('');
            if (preferredId && rows.some((item) => Number((item && item.id) || 0) === preferredId)) {
                select.value = String(preferredId);
            } else {
                select.value = '';
            }
        }

        function selectDayRunPreset(presetId) {
            const id = Number(presetId || 0);
            const preset = findDayRunPresetById(id);
            const nameEl = documentRef.getElementById('dayRunPresetName');
            const descEl = documentRef.getElementById('dayRunPresetDescription');
            if (!preset) {
                if (nameEl) nameEl.value = '';
                if (descEl) descEl.value = '';
                return;
            }
            if (nameEl) nameEl.value = String(preset.name || '');
            if (descEl) descEl.value = String(preset.description || '');
            applyDayRunOptionsToUi(preset.options || {});
            setDayRunStatus(`Loaded preset: ${preset.name || 'Preset'}`);
        }

        async function loadDayRunPresets() {
            const select = documentRef.getElementById('dayRunPresetSelect');
            const currentId = Number((select && select.value) || 0);
            try {
                const data = await deps.apiFetchJson(`${getApiBase()}/day/presets?limit=100`, { useCache: false });
                const rows = Array.isArray(data.items) ? data.items : [];
                setDayRunPresetsCache(rows);
                renderDayRunPresetSelect(rows, currentId);
                if (!currentId && rows.length) {
                    selectDayRunPreset(rows[0].id);
                    if (select) select.value = String(rows[0].id);
                } else if (!rows.length) {
                    selectDayRunPreset('');
                }
            } catch (e) {
                setDayRunStatus(`Failed to load presets: ${e.message}`, true);
            }
        }

        async function saveDayRunPreset() {
            const nameEl = documentRef.getElementById('dayRunPresetName');
            const descEl = documentRef.getElementById('dayRunPresetDescription');
            const name = String((nameEl && nameEl.value) || '').trim();
            if (!name) {
                setDayRunStatus('Preset name is required.', true);
                return;
            }
            try {
                const payload = {
                    name,
                    description: String((descEl && descEl.value) || '').trim() || null,
                    options: getDayRunPayloadFromUi(),
                };
                const data = await deps.apiFetchJson(`${getApiBase()}/day/presets`, {
                    method: 'POST',
                    body: payload,
                    useCache: false,
                });
                await loadDayRunPresets();
                const select = documentRef.getElementById('dayRunPresetSelect');
                if (select && data && data.id) {
                    select.value = String(data.id);
                    selectDayRunPreset(data.id);
                }
                setDayRunStatus(`Preset saved: ${name}`);
            } catch (e) {
                setDayRunStatus(`Save preset failed: ${e.message}`, true);
            }
        }

        async function updateDayRunPreset() {
            const select = documentRef.getElementById('dayRunPresetSelect');
            const presetId = Number((select && select.value) || 0);
            if (!presetId) {
                setDayRunStatus('Select a preset to update.', true);
                return;
            }
            const nameEl = documentRef.getElementById('dayRunPresetName');
            const descEl = documentRef.getElementById('dayRunPresetDescription');
            const name = String((nameEl && nameEl.value) || '').trim();
            if (!name) {
                setDayRunStatus('Preset name is required.', true);
                return;
            }
            try {
                await deps.apiFetchJson(`${getApiBase()}/day/presets/${encodeURIComponent(String(presetId))}`, {
                    method: 'PUT',
                    body: {
                        name,
                        description: String((descEl && descEl.value) || '').trim() || null,
                        options: getDayRunPayloadFromUi(),
                    },
                    useCache: false,
                });
                await loadDayRunPresets();
                if (select) select.value = String(presetId);
                selectDayRunPreset(presetId);
                setDayRunStatus(`Preset updated: ${name}`);
            } catch (e) {
                setDayRunStatus(`Update preset failed: ${e.message}`, true);
            }
        }

        async function deleteDayRunPreset() {
            const select = documentRef.getElementById('dayRunPresetSelect');
            const presetId = Number((select && select.value) || 0);
            if (!presetId) {
                setDayRunStatus('Select a preset to delete.', true);
                return;
            }
            const preset = findDayRunPresetById(presetId);
            const confirmImpl = typeof windowRef.confirm === 'function' ? windowRef.confirm.bind(windowRef) : () => true;
            if (!confirmImpl(`Delete preset "${(preset && preset.name) || presetId}"?`)) return;
            try {
                await deps.apiFetchJson(`${getApiBase()}/day/presets/${encodeURIComponent(String(presetId))}`, {
                    method: 'DELETE',
                    useCache: false,
                });
                await loadDayRunPresets();
                if (select) select.value = '';
                selectDayRunPreset('');
                setDayRunStatus('Preset deleted.');
            } catch (e) {
                setDayRunStatus(`Delete preset failed: ${e.message}`, true);
            }
        }

        function isUnifiedInboxModalOpen() {
            const modal = documentRef.getElementById('unifiedInboxModal');
            return Boolean(modal && !modal.classList.contains('hidden'));
        }

        async function runSelectedDayRunPreset() {
            const select = documentRef.getElementById('dayRunPresetSelect');
            const presetId = Number((select && select.value) || 0);
            if (!presetId) {
                setDayRunStatus('Select a preset to run.', true);
                return;
            }
            setDayRunStatus(`Running preset #${presetId}...`);
            try {
                const data = await deps.apiFetchJson(`${getApiBase()}/day/presets/${encodeURIComponent(String(presetId))}/run`, {
                    method: 'POST',
                    useCache: false,
                });
                if (String(currentState().currentStatus || 'new') === 'new' && typeof deps.loadPapers === 'function') {
                    if (data.date) patchState({ currentDateFilter: data.date });
                    await deps.loadPapers();
                }
                await refreshAllBadges({ force: true });
                if (isUnifiedInboxModalOpen()) {
                    await refreshUnifiedInbox();
                }
                await Promise.all([loadDayRunHistory(), loadDayRunPresets()]);
                setDayRunStatus(data.summary || `Preset run complete (#${presetId}).`);
            } catch (e) {
                setDayRunStatus(`Preset run failed: ${e.message}`, true);
            }
        }

        function renderDayRunHistory(items) {
            const list = documentRef.getElementById('dayRunHistoryList');
            if (!list) return;
            const rows = Array.isArray(items) ? items : [];
            if (!rows.length) {
                list.innerHTML = '<div style="color:var(--text-muted);">No runs yet.</div>';
                return;
            }
            list.innerHTML = rows.map((item) => {
                const runId = Number((item && item.id) || 0);
                const status = String((item && item.status) || 'unknown');
                const runDate = String((item && item.run_date) || '');
                const requestedAt = formatIsoShort(item && item.requested_at ? item.requested_at : '');
                const summary = String((item && item.summary) || '').trim() || 'No summary available.';
                const options = (item && item.options) || {};
                const optsText = `fetch:${options.run_fetch ? 'on' : 'off'} · rules:${options.run_rules ? 'on' : 'off'} · plan:${options.run_reading_plan ? 'on' : 'off'}`;
                return `
                    <div class="export-history-card">
                        <div style="display:flex; justify-content:space-between; gap:0.6rem; align-items:flex-start;">
                            <div>
                                <div style="font-weight:600;">${escapeHtml(runDate || 'n/a')} · ${escapeHtml(status)}</div>
                                <div style="font-size:0.8rem; color:var(--text-muted); margin-top:0.2rem;">${escapeHtml(requestedAt || 'n/a')} · ${escapeHtml(optsText)}</div>
                            </div>
                            <button class="btn-secondary" onclick="retryDayRun(${runId})" style="padding:0.3rem 0.7rem;">
                                <i class="fa-solid fa-rotate-right"></i> Retry
                            </button>
                        </div>
                        <div style="font-size:0.82rem; color:var(--text-muted); margin-top:0.35rem;">${escapeHtml(summary)}</div>
                    </div>
                `;
            }).join('');
        }

        async function loadDayRunHistory() {
            const list = documentRef.getElementById('dayRunHistoryList');
            if (!list) return;
            list.innerHTML = '<div class="loader"></div>';
            try {
                const data = await deps.apiFetchJson(`${getApiBase()}/day/runs?limit=20`, { useCache: false });
                const rows = Array.isArray(data.items) ? data.items : [];
                setDayRunHistoryCache(rows);
                renderDayRunHistory(rows);
            } catch (e) {
                list.innerHTML = `<div style="color:var(--danger)">Failed to load day runs: ${escapeHtml(e.message)}</div>`;
            }
        }

        async function retryDayRun(runId) {
            const id = Number(runId || 0);
            if (!id) return;
            setDayRunStatus(`Retrying run #${id}...`);
            try {
                const data = await deps.apiFetchJson(`${getApiBase()}/day/run/${encodeURIComponent(String(id))}/retry`, {
                    method: 'POST',
                    useCache: false,
                });
                setDayRunStatus(data.summary || `Retried run #${id}.`);
                await refreshAllBadges({ force: true });
                if (isUnifiedInboxModalOpen()) {
                    await refreshUnifiedInbox();
                }
                await loadDayRunHistory();
            } catch (e) {
                setDayRunStatus(`Retry failed: ${e.message}`, true);
            }
        }

        async function openUnifiedInboxModal() {
            if (typeof deps.recordTrail === 'function') {
                deps.recordTrail({ type: 'unified_inbox', label: 'Unified inbox' });
            }
            if (typeof deps.showModal === 'function') {
                deps.showModal('unifiedInboxModal');
            } else {
                const modal = documentRef.getElementById('unifiedInboxModal');
                if (modal) modal.classList.remove('hidden');
            }
            setUnifiedInboxControlsFromState();
            syncDayRunControlsFromTopBar();
            setDayRunStatus('');
            await loadDayRunPresets();
            await loadDayRunHistory();
            await refreshUnifiedInbox();
        }

        function closeUnifiedInboxModal() {
            if (typeof deps.hideModal === 'function') {
                deps.hideModal('unifiedInboxModal');
            } else {
                const modal = documentRef.getElementById('unifiedInboxModal');
                if (modal) modal.classList.add('hidden');
            }
        }

        async function refreshUnifiedInbox() {
            const list = documentRef.getElementById('unifiedInboxList');
            if (list) list.innerHTML = '<div class="loader"></div>';
            setUnifiedInboxStatus('Loading inbox...');
            try {
                const filters = readUnifiedInboxFiltersFromUi();
                setUnifiedInboxState({
                    versionScope: filters.versionScope,
                    versionDays: filters.versionDays,
                    limit: filters.limit,
                    kinds: filters.kinds,
                    sort: filters.sort,
                    viewMode: filters.viewMode,
                    focusLimit: filters.focusLimit,
                });
                if (!filters.kinds.length) {
                    renderUnifiedInbox({
                        counts: { alerts: 0, version_updates: 0, follow_ups: 0, digests: 0 },
                        total: 0,
                        items: [],
                    });
                    setUnifiedInboxStatus('Choose at least one kind to load inbox items.');
                    await refreshUnifiedInboxBadge();
                    return;
                }

                const params = new URLSearchParams();
                const endpoint = filters.viewMode === 'focus' ? '/inbox/focus' : '/inbox/unified';
                const effectiveLimit = filters.viewMode === 'focus' ? filters.focusLimit : filters.limit;
                params.set('limit', String(effectiveLimit));
                params.set('version_scope', filters.versionScope);
                params.set('version_days', String(filters.versionDays));
                if (filters.viewMode !== 'focus') {
                    params.set('sort', filters.sort || 'recent');
                }
                if (filters.kinds && filters.kinds.length) {
                    params.set('kinds', filters.kinds.join(','));
                }

                const res = await fetchImpl(`${getApiBase()}${endpoint}?${params.toString()}`);
                const data = await res.json();
                if (!res.ok) throw new Error(data.detail || 'Failed to load unified inbox');
                renderUnifiedInbox(data);
                await refreshUnifiedInboxBadge();
            } catch (e) {
                setUnifiedInboxStatus(`Failed to load inbox: ${e.message}`, true);
                if (list) list.innerHTML = '';
            }
        }

        async function applyUnifiedInboxAction(kind, action, payloadJson = '{}') {
            try {
                const extra = decodeInboxPayload(payloadJson || '{}');
                const body = { kind, action, ...(extra || {}) };
                const res = await fetchImpl(`${getApiBase()}/inbox/action`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(body),
                });
                const data = await res.json();
                if (!res.ok) throw new Error(data.detail || 'Failed to apply inbox action');
                await refreshUnifiedInbox();
                await refreshAllBadges({ force: true });
            } catch (e) {
                setUnifiedInboxStatus(`Action failed: ${e.message}`, true);
            }
        }

        async function runDailyFetch() {
            const fetchBtnEl = documentRef.getElementById('fetchBtn');
            const dailyBtnEl = documentRef.getElementById('dailyFetchBtn');
            if (dailyBtnEl) {
                dailyBtnEl.disabled = true;
                dailyBtnEl.dataset.fetching = '1';
            }
            if (fetchBtnEl) {
                fetchBtnEl.disabled = true;
                fetchBtnEl.dataset.fetching = '1';
            }
            try {
                const dateInput = documentRef.getElementById('dateInput');
                const dateVal = dateInput ? dateInput.value : null;
                const forceCheck = documentRef.getElementById('dailyFetchForceCheck');
                const force = forceCheck ? forceCheck.checked : false;
                let data;
                if (dateVal) {
                    const forceParam = force ? '&force=true' : '';
                    const url = `${getApiBase()}/fetch/daily?date=${encodeURIComponent(dateVal)}${forceParam}`;
                    data = await fetchJsonOrThrow(url, { method: 'POST' });
                    if (data.skipped) {
                        alertUser(`Daily fetch skipped: ${data.reason || 'unknown'}`);
                        await syncFetchStatus({ silent: true });
                        return;
                    }
                } else if (force) {
                    const forceUrl = `${getApiBase()}/fetch/daily?force=true`;
                    data = await fetchJsonOrThrow(forceUrl, { method: 'POST' });
                    if (data.skipped) {
                        alertUser(`Daily fetch skipped: ${data.reason || 'unknown'}`);
                        await syncFetchStatus({ silent: true });
                        return;
                    }
                } else {
                    data = await deps.apiFetchJson(`${getApiBase()}/fetch`, {
                        method: 'POST',
                        body: { max_results: 20 },
                        useCache: false,
                    });
                }

                if (data.skipped) {
                    alertUser(`Daily fetch skipped: ${data.reason || 'unknown'}`);
                    await syncFetchStatus({ silent: true });
                    return;
                }

                alertUser(`Daily fetch complete: ${data.fetched} papers (${data.new} new) for ${data.date}.`);
                if (String(currentState().currentStatus || 'new') === 'new' && typeof deps.loadPapers === 'function') {
                    patchState({ currentDateFilter: data.date });
                    await deps.loadPapers();
                }
                await refreshAllBadges();
                await syncFetchStatus({ silent: true });
            } catch (e) {
                const retryAfter = parseErrorRetryAfter(e);
                const backoffApplied = maybeApplyFetchBackoff(e);
                if (backoffApplied) {
                    const waitLabel = retryAfter > 0 ? `${Math.ceil(retryAfter)}s` : 'a short wait';
                    alertUser(`Daily fetch failed. Auto-retry window: ${waitLabel}.`);
                    await syncFetchStatus({ silent: true });
                    return;
                }
                alertUser(`Daily fetch failed: ${e.message}`);
            } finally {
                if (dailyBtnEl) {
                    delete dailyBtnEl.dataset.fetching;
                }
                if (fetchBtnEl) {
                    delete fetchBtnEl.dataset.fetching;
                }
                renderFetchCooldownHint();
            }
        }

        async function runMyDay() {
            const btn = documentRef.getElementById('dayRunBtn');
            const runBtn = documentRef.querySelector('#unifiedInboxModal button[onclick="runMyDay()"]');
            const originalHtml = btn ? btn.innerHTML : '';
            if (btn) {
                btn.disabled = true;
                btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i>';
            }
            const originalRunHtml = runBtn ? runBtn.innerHTML : '';
            if (runBtn) {
                runBtn.disabled = true;
                runBtn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i>';
            }

            try {
                const payload = getDayRunPayloadFromUi();
                setDayRunStatus('Running day workflow...');
                const res = await fetchImpl(`${getApiBase()}/day/run`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload),
                });
                const data = await res.json();
                if (!res.ok) throw new Error(data.detail || 'Day run failed');

                if (String(currentState().currentStatus || 'new') === 'new' && typeof deps.loadPapers === 'function') {
                    if (data.date) patchState({ currentDateFilter: data.date });
                    await deps.loadPapers();
                }
                await refreshAllBadges({ force: true });
                if (isUnifiedInboxModalOpen()) {
                    await refreshUnifiedInbox();
                }
                await loadDayRunHistory();
                await syncFetchStatus({ silent: true });
                setDayRunStatus(data.summary || `Day run complete for ${data.date || 'today'}.`);
                alertUser(data.summary || `Day run complete for ${data.date || 'today'}.`);
            } catch (e) {
                setDayRunStatus(`Run failed: ${e.message}`, true);
                alertUser(`Run my day failed: ${e.message}`);
                await syncFetchStatus({ silent: true });
            } finally {
                if (btn) {
                    btn.disabled = false;
                    btn.innerHTML = originalHtml || '<i class="fa-solid fa-play"></i>';
                }
                if (runBtn) {
                    runBtn.disabled = false;
                    runBtn.innerHTML = originalRunHtml || '<i class="fa-solid fa-play"></i> Run My Day';
                }
            }
        }

        renderFetchCooldownHint();
        startFetchStatusPolling();
        windowRef.setTimeout(() => {
            syncFetchStatus({ silent: true });
        }, 150);

        return {
            fetchNewPapers,
            toggleUnifiedInboxKinds,
            toggleUnifiedInboxItemSelection,
            clearUnifiedInboxSelection,
            toggleUnifiedInboxSelectAll,
            applyUnifiedInboxBulkAction,
            openUnifiedInboxModal,
            closeUnifiedInboxModal,
            refreshUnifiedInbox,
            applyUnifiedInboxAction,
            selectDayRunPreset,
            loadDayRunPresets,
            saveDayRunPreset,
            updateDayRunPreset,
            deleteDayRunPreset,
            runSelectedDayRunPreset,
            loadDayRunHistory,
            retryDayRun,
            runDailyFetch,
            runMyDay,
        };
    }

    global.ArxivPulseInbox = {
        create: createInboxModule,
    };
})(window);
