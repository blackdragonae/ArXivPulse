const API_BASE = '/api';

// State
let currentStatus = 'new';
let isLoading = false;
let userKeywords = [];
let currentView = 'grid';
let focusedPaperId = null;
let currentDateFilter = null;
let feedAbortController = null;
let feedPageAbortController = null;
let searchAbortController = null;

// Filtering & Sorting
let allPapers = []; // Global store for client-side filtering
let isSmartSort = false;
let followedAuthors = new Set();
let searchMode = 'local';
let favoritesSort = 'ai';
const FAVORITES_CACHE_TTL_MS = 5 * 60 * 1000;
const favoritesCache = {};

// UI State
let isStatsOpen = false;
let topicChart = null;
let trendChart = null;
let schedulerLeaderTimer = null;
let changeSummarySnapshot = null;
let changeSummarySince = null;
let activeFolderSchedule = { id: null, name: '' };
let activeFolderEditor = null;
const JOB_POLL_INTERVAL_MS = 1200;
const JOB_POLL_TIMEOUT_MS = 180000;
const LAZY_LIB_SOURCES = {
    vis: 'libs/vis-network.min.js',
    chart: 'https://cdn.jsdelivr.net/npm/chart.js',
    marked: 'https://cdn.jsdelivr.net/npm/marked/marked.min.js',
    dompurify: 'https://cdn.jsdelivr.net/npm/dompurify@3.1.7/dist/purify.min.js',
};
const lazyScriptPromises = {};
const VIRTUAL_MIN_ITEMS = 120;
const VIRTUAL_CARD_MIN_WIDTH = 600;
const VIRTUAL_GRID_GAP = 24;
const VIRTUAL_DEFAULT_ROW_HEIGHT = 460;
const VIRTUAL_OVERSCAN_ROWS = 2;
let virtualScrollRaf = null;
let virtualResizeRaf = null;
const UI_STATE_KEY = 'arxivc.uiState.v1';
const SAVED_VIEWS_KEY = 'arxivc.savedViews.v1';
const LAST_VISIT_KEY = 'arxivc.lastVisitAt.v1';
const TRAIL_KEY = 'arxivc.trail.v1';
const TRAIL_SESSION_KEY = 'arxivc.trail.session.v1';
const TRAIL_MAX_ENTRIES = 200;
const TEAM_NOTE_AUTHOR_KEY = 'arxivc.teamNoteAuthor.v1';
const INDEX_STALE_COVERAGE = 0.98;
const MENTION_HANDLE_KEY = 'arxivc.mentionHandle.v1';
const MENTION_READ_KEY_PREFIX = 'arxivc.mentions.read.v1.';
const RANK_PROFILE_KEY = 'arxivc.rankProfile.v1';
const API_CACHE_MAX_ENTRIES = 80;
const apiResponseCache = new Map();
/**
 * @typedef {Object} Paper
 * @property {string} id
 * @property {string} [title]
 * @property {string} [summary]
 * @property {string[]} [authors]
 * @property {string} [published]
 * @property {string} [pdf_url]
 * @property {string[]} [categories]
 * @property {number} [citation_count]
 * @property {number} [match_score]
 * @property {number} [novelty_score]
 * @property {boolean} [bookmarked]
 * @property {boolean} [pinned]
 */

/**
 * @typedef {Object} PapersResponse
 * @property {Paper[]} items
 * @property {number} total
 * @property {number} offset
 * @property {number} limit
 * @property {boolean} has_more
 */

/**
 * @typedef {Object} SearchResponse
 * @property {Paper[]} items
 * @property {boolean} [cached]
 * @property {number} [total]
 * @property {number} [offset]
 * @property {number} [limit]
 * @property {boolean} [has_more]
 */
const virtualState = {
    enabled: false,
    papers: [],
    columns: 1,
    rowHeight: VIRTUAL_DEFAULT_ROW_HEIGHT,
    lastStart: -1,
    lastEnd: -1,
    scrollHandler: null,
    resizeHandler: null,
};

// Audio State
let playQueue = [];
let currentTrackIndex = -1;
let isPlaying = false;
let audioObj = null;

// Selection & Review State
let isSelectionMode = false;
let selectedPaperIds = new Set();
let currentReviewMarkdown = ""; // Store for export
let currentStructuredPaperId = null;
let activeReproJobId = null;
let activeDiscoverJobId = null;
let activeCompareMatrixJobId = null;
let activeBenchmarkJobId = null;
let activeReadingPaperId = null;
let activeNotesPaperId = null;
let activeVersionPaperId = null;
let activeVersionRows = [];
let activeReadingPlanPayload = null;
let lastReadingPlanAction = null;
let activeNotesUpdatedAt = '';
let activeReadingStatus = 'queue';
let citationOverlayNetwork = null;
let relatedGraphNetwork = null;
let benchmarkTableState = { payload: null, sortKey: 'dataset', sortDir: 1 };
let lineageNetwork = null;
let digestFilterState = { cadence: 'all', unreadOnly: false };
let versionUpdatesState = { scope: 'watchlist', sinceDays: 30, includeTriaged: false };
let weeklyReviewState = { days: 7 };
let unifiedInboxState = {
    versionScope: 'watchlist',
    versionDays: 30,
    limit: 80,
    kinds: ['alert', 'version_update', 'follow_up', 'digest'],
    sort: 'recent',
    viewMode: 'all',
    focusLimit: 12,
};
let unifiedInboxSelectedItems = new Map();
let unifiedInboxVisibleItems = [];
let dayRunHistoryCache = [];
let dayRunPresetsCache = [];
let trailEntries = [];
let trailSessionId = null;
let inboxRulesCache = [];
let notesTemplatesCache = [];
let inboxRulesPreviewCache = [];
let inboxRulesAuditCache = [];
let inboxRulesDiagnosticsCache = [];
let mentionReadSet = new Set();
let mentionsCache = [];
const DEFAULT_RANK_PROFILE = { relevance: 50, novelty: 30, citations: 20 };
let rankProfile = { ...DEFAULT_RANK_PROFILE };
let rankProfileRefreshTimer = null;

// Elements

// Elements
const STOPWORDS = new Set([
    'the', 'of', 'and', 'in', 'to', 'a', 'is', 'for', 'with', 'on', 'as', 'by', 'that', 'are', 'from',
    'this', 'we', 'an', 'at', 'be', 'which', 'or', 'it', 'can', 'has', 'have', 'not', 'but', 'their',
    'measurement', 'measurements', 'study', 'results', 'data', 'model', 'analysis', 'using', 'observations'
]);

// Elements
const paperGrid = document.getElementById('paperGrid');
const loadingIndicator = document.getElementById('loading');
const fetchBtn = document.getElementById('fetchBtn');
const filterChips = document.querySelectorAll('.filter-chip[data-status]');

function showModal(modalId) {
    const modal = document.getElementById(modalId);
    if (modal) modal.classList.remove('hidden');
}

function hideModal(modalId) {
    const modal = document.getElementById(modalId);
    if (modal) modal.classList.add('hidden');
}

function closeModalById(modalId) {
    const closeHandlers = {
        chatModal: () => window.closeChatModal && window.closeChatModal(),
        structureModal: () => window.closeStructureModal && window.closeStructureModal(),
        briefModal: () => window.closeBriefModal && window.closeBriefModal(),
        digestModal: () => window.closeDigestModal && window.closeDigestModal(),
        alertsModal: () => window.closeAlertsModal && window.closeAlertsModal(),
        trailModal: () => window.closeTrailModal && window.closeTrailModal(),
        settingsModal: () => hideModal('settingsModal'),
        synthesisModal: () => window.closeSynthesisModal && window.closeSynthesisModal(),
        figureModal: () => window.closeFigureModal && window.closeFigureModal(),
        visionChatModal: () => window.closeVisionModal && window.closeVisionModal(),
        agentModal: () => window.closeAgentModal && window.closeAgentModal(),
        libChatModal: () => window.closeLibraryChatModal && window.closeLibraryChatModal(),
        discoverModal: () => window.closeDiscoverModal && window.closeDiscoverModal(),
        battleModal: () => window.closeBattleModal && window.closeBattleModal(),
        compareMatrixModal: () => window.closeCompareMatrixModal && window.closeCompareMatrixModal(),
        compareDiffModal: () => window.closeCompareDiffModal && window.closeCompareDiffModal(),
        crossPaperQaModal: () => window.closeCrossPaperQaModal && window.closeCrossPaperQaModal(),
        relatedGraphModal: () => window.closeRelatedGraphModal && window.closeRelatedGraphModal(),
        benchmarkModal: () => window.closeBenchmarkModal && window.closeBenchmarkModal(),
        citationOverlayModal: () => window.closeCitationOverlayModal && window.closeCitationOverlayModal(),
        reproModal: () => window.closeReproModal && window.closeReproModal(),
        searchAgentsModal: () => window.closeSearchAgentsModal && window.closeSearchAgentsModal(),
        schedulerOpsModal: () => window.closeSchedulerOpsModal && window.closeSchedulerOpsModal(),
        lineageModal: () => window.closeLineageModal && window.closeLineageModal(),
        conceptModal: () => window.closeConceptModal && window.closeConceptModal(),
        createFolderModal: () => window.closeCreateFolderModal && window.closeCreateFolderModal(),
        changeSummaryModal: () => window.closeChangeSummaryModal && window.closeChangeSummaryModal(),
        savedViewsModal: () => window.closeSavedViewsModal && window.closeSavedViewsModal(),
        batchTagModal: () => window.closeBatchTagModal && window.closeBatchTagModal(),
        folderScheduleModal: () => window.closeFolderScheduleModal && window.closeFolderScheduleModal(),
        readingModal: () => window.closeReadingModal && window.closeReadingModal(),
        readingPlanModal: () => window.closeReadingPlanModal && window.closeReadingPlanModal(),
        notesModal: () => window.closeNotesModal && window.closeNotesModal(),
        versionModal: () => window.closeVersionModal && window.closeVersionModal(),
        versionUpdatesModal: () => window.closeVersionUpdatesModal && window.closeVersionUpdatesModal(),
        weeklyReviewModal: () => window.closeWeeklyReviewModal && window.closeWeeklyReviewModal(),
        unifiedInboxModal: () => window.closeUnifiedInboxModal && window.closeUnifiedInboxModal(),
    };
    if (closeHandlers[modalId]) {
        closeHandlers[modalId]();
    } else {
        hideModal(modalId);
    }
}

function initializeModalUX() {
    document.querySelectorAll('.modal-overlay').forEach(modal => {
        modal.addEventListener('click', (event) => {
            if (event.target === modal) {
                closeModalById(modal.id);
            }
        });
    });

    document.addEventListener('keydown', (event) => {
        if (event.key !== 'Escape') return;

        const openModals = Array.from(document.querySelectorAll('.modal-overlay'))
            .filter(m => !m.classList.contains('hidden'));
        if (openModals.length === 0) return;

        const topModal = openModals[openModals.length - 1];
        closeModalById(topModal.id);
    });
}

function loadUIState() {
    try {
        const raw = localStorage.getItem(UI_STATE_KEY);
        if (!raw) return;
        const state = JSON.parse(raw);
        if (state && typeof state === 'object') {
            const allowedStatus = new Set(['new', 'liked', 'dismissed', 'bookmarked', 'read']);
            const allowedView = new Set(['grid', 'graph', 'galaxy', 'skim', 'threads']);
            const allowedSearch = new Set(['local', 'semantic', 'global']);
            const allowedFavSort = new Set(['ai', 'date', 'matches', 'novelty']);
            if (state.status && allowedStatus.has(state.status)) currentStatus = state.status;
            if (typeof state.dateFilter === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(state.dateFilter)) {
                currentDateFilter = state.dateFilter;
            }
            if (typeof state.smartSort === 'boolean') isSmartSort = state.smartSort;
            if (state.view && allowedView.has(state.view)) currentView = state.view;
            if (state.searchMode && allowedSearch.has(state.searchMode)) searchMode = state.searchMode;
            if (typeof state.statsOpen === 'boolean') isStatsOpen = state.statsOpen;
            if (state.favoritesSort && allowedFavSort.has(state.favoritesSort)) favoritesSort = state.favoritesSort;
        }
    } catch (e) {
        console.warn("Failed to load UI state", e);
    }
}

function saveUIState() {
    try {
        const state = {
            status: currentStatus,
            dateFilter: currentDateFilter,
            smartSort: isSmartSort,
            view: currentView,
            searchMode,
            statsOpen: isStatsOpen,
            favoritesSort,
        };
        localStorage.setItem(UI_STATE_KEY, JSON.stringify(state));
    } catch (e) {
        console.warn("Failed to save UI state", e);
    }
}

function applyUIStateToControls() {
    const smartBtn = document.getElementById('smartRankBtn');
    if (smartBtn) {
        if (isSmartSort) {
            smartBtn.style.borderColor = 'var(--primary)';
            smartBtn.style.color = 'var(--primary)';
            smartBtn.style.background = 'rgba(99, 102, 241, 0.1)';
        } else {
            smartBtn.style.borderColor = 'rgba(255,255,255,0.2)';
            smartBtn.style.color = 'var(--text-muted)';
            smartBtn.style.background = 'rgba(255,255,255,0.1)';
        }
    }

    filterChips.forEach(c => {
        if (c.dataset.status === currentStatus) c.classList.add('active');
        else c.classList.remove('active');
    });
    document.querySelectorAll('.nav-item').forEach(item => {
        if (item.getAttribute('onclick') && item.getAttribute('onclick').includes(currentStatus)) {
            item.classList.add('active');
        } else {
            item.classList.remove('active');
        }
    });

    const dateInput = document.getElementById('dateInput');
    if (dateInput) {
        if (currentDateFilter) {
            dateInput.value = currentDateFilter;
            fetchBtn.innerHTML = `<i class="fa-solid fa-calendar-day"></i> Fetch ${currentDateFilter}`;
        } else {
            dateInput.value = '';
            fetchBtn.innerHTML = '<i class="fa-solid fa-cloud-arrow-down"></i> Fetch New';
        }
    }

    setSearchMode(searchMode, { reset: false, persist: false });
    updateFavoritesSortBar();
    applySkimViewState();
    applyThreadsViewState();
}

function coerceRankValue(value, fallback) {
    const num = Number(value);
    if (!Number.isFinite(num)) return fallback;
    return Math.max(0, Math.min(100, num));
}

function normalizeRankProfile(profile) {
    if (!profile || typeof profile !== 'object') return { ...DEFAULT_RANK_PROFILE };
    let rel = coerceRankValue(profile.relevance, DEFAULT_RANK_PROFILE.relevance);
    let nov = coerceRankValue(profile.novelty, DEFAULT_RANK_PROFILE.novelty);
    let cit = coerceRankValue(profile.citations, DEFAULT_RANK_PROFILE.citations);
    let total = rel + nov + cit;
    const maxVal = Math.max(rel, nov, cit);
    if (total > 0 && total <= 3 && maxVal <= 1) {
        rel *= 100;
        nov *= 100;
        cit *= 100;
        total = rel + nov + cit;
    }
    if (total <= 0) return { ...DEFAULT_RANK_PROFILE };
    return { relevance: rel, novelty: nov, citations: cit };
}

function loadRankProfile() {
    try {
        const raw = localStorage.getItem(RANK_PROFILE_KEY);
        if (!raw) {
            rankProfile = { ...DEFAULT_RANK_PROFILE };
            return rankProfile;
        }
        const parsed = JSON.parse(raw);
        rankProfile = normalizeRankProfile(parsed);
        return rankProfile;
    } catch (e) {
        console.warn("Failed to load rank profile", e);
        rankProfile = { ...DEFAULT_RANK_PROFILE };
        return rankProfile;
    }
}

function saveRankProfile(profile) {
    rankProfile = normalizeRankProfile(profile);
    try {
        localStorage.setItem(RANK_PROFILE_KEY, JSON.stringify(rankProfile));
    } catch (e) {
        console.warn("Failed to save rank profile", e);
    }
    return rankProfile;
}

function applyRankProfileToControls(profile = rankProfile) {
    const relSlider = document.getElementById('rankRelevanceSlider');
    const novSlider = document.getElementById('rankNoveltySlider');
    const citSlider = document.getElementById('rankCitationsSlider');
    const relValue = document.getElementById('rankRelevanceValue');
    const novValue = document.getElementById('rankNoveltyValue');
    const citValue = document.getElementById('rankCitationsValue');
    if (!relSlider || !novSlider || !citSlider) return;
    relSlider.value = String(profile.relevance ?? DEFAULT_RANK_PROFILE.relevance);
    novSlider.value = String(profile.novelty ?? DEFAULT_RANK_PROFILE.novelty);
    citSlider.value = String(profile.citations ?? DEFAULT_RANK_PROFILE.citations);
    if (relValue) relValue.textContent = String(relSlider.value);
    if (novValue) novValue.textContent = String(novSlider.value);
    if (citValue) citValue.textContent = String(citSlider.value);
}

function updateRankProfileFromControls() {
    const relSlider = document.getElementById('rankRelevanceSlider');
    const novSlider = document.getElementById('rankNoveltySlider');
    const citSlider = document.getElementById('rankCitationsSlider');
    if (!relSlider || !novSlider || !citSlider) return;
    const next = {
        relevance: Number(relSlider.value),
        novelty: Number(novSlider.value),
        citations: Number(citSlider.value),
    };
    saveRankProfile(next);
    applyRankProfileToControls(rankProfile);
}

function shouldUseProfileSortForFeed() {
    if (currentStatus === 'liked') {
        return favoritesSort === 'ai';
    }
    return Boolean(isSmartSort);
}

function getRankProfileQuery() {
    if (!shouldUseProfileSortForFeed()) return '';
    const weights = normalizeRankProfile(rankProfile);
    return `&w_relevance=${encodeURIComponent(weights.relevance)}&w_novelty=${encodeURIComponent(weights.novelty)}&w_citations=${encodeURIComponent(weights.citations)}`;
}

function scheduleRankProfileRefresh() {
    if (rankProfileRefreshTimer) clearTimeout(rankProfileRefreshTimer);
    if (!shouldUseProfileSortForFeed()) return;
    if (hasActiveSearchQuery()) return;
    rankProfileRefreshTimer = setTimeout(() => {
        if (shouldUseProfileSortForFeed() && !hasActiveSearchQuery()) {
            loadPapers();
        }
    }, 280);
}

function initRankProfileControls() {
    const relSlider = document.getElementById('rankRelevanceSlider');
    const novSlider = document.getElementById('rankNoveltySlider');
    const citSlider = document.getElementById('rankCitationsSlider');
    if (!relSlider || !novSlider || !citSlider) return;
    const handler = () => {
        updateRankProfileFromControls();
        scheduleRankProfileRefresh();
    };
    [relSlider, novSlider, citSlider].forEach((slider) => {
        slider.addEventListener('input', handler);
        slider.addEventListener('change', handler);
    });
}

window.resetRankProfile = () => {
    saveRankProfile({ ...DEFAULT_RANK_PROFILE });
    applyRankProfileToControls(rankProfile);
    scheduleRankProfileRefresh();
};

function cacheApiResponse(url, payload) {
    if (!url) return;
    if (apiResponseCache.has(url)) {
        apiResponseCache.delete(url);
    }
    apiResponseCache.set(url, { payload, ts: Date.now() });
    if (apiResponseCache.size > API_CACHE_MAX_ENTRIES) {
        const firstKey = apiResponseCache.keys().next().value;
        apiResponseCache.delete(firstKey);
    }
}

function getCachedApiResponse(url) {
    const entry = apiResponseCache.get(url);
    return entry ? entry.payload : null;
}

async function fetchJsonWithCache(url, options = {}) {
    const headers = new Headers(options.headers || {});
    if (apiResponseCache.has(url)) {
        headers.set('X-Client-Cache', 'warm');
    }
    const res = await fetch(url, { ...options, headers });
    if (res.status === 304) {
        const cached = getCachedApiResponse(url);
        if (cached !== null) {
            return { data: cached, cached: true, status: 304 };
        }
        const retry = await fetch(url, { ...options, headers, cache: 'no-store' });
        const retryData = await retry.json();
        if (!retry.ok) {
            throw new Error(retryData.detail || `HTTP ${retry.status}`);
        }
        cacheApiResponse(url, retryData);
        return { data: retryData, cached: false, status: retry.status };
    }
    let data = null;
    try {
        data = await res.json();
    } catch (e) {
        data = null;
    }
    if (!res.ok) {
        throw new Error((data && data.detail) ? data.detail : `HTTP ${res.status}`);
    }
    cacheApiResponse(url, data);
    return { data, cached: false, status: res.status };
}

async function apiFetchJson(url, { method = 'GET', body = null, useCache = true, signal = undefined } = {}) {
    const opts = { method, signal };
    if (body !== null) {
        opts.headers = { 'Content-Type': 'application/json' };
        opts.body = JSON.stringify(body);
    }
    const isGet = String(method || 'GET').toUpperCase() === 'GET';
    if (isGet && useCache) {
        const { data } = await fetchJsonWithCache(url, opts);
        return data;
    }
    let res;
    try {
        res = await fetch(url, opts);
    } catch (err) {
        if (isGet) {
            // One retry for transient network failures
            res = await fetch(url, opts);
        } else {
            throw err;
        }
    }
    const data = await res.json();
    if (!res.ok) {
        throw new Error(data.detail || `HTTP ${res.status}`);
    }
    return data;
}

function applySkimViewState() {
    const skimBtn = document.getElementById('skimViewBtn');
    const enabled = currentView === 'skim';
    document.body.classList.toggle('skim-view', enabled);
    if (skimBtn) {
        if (enabled) {
            skimBtn.style.borderColor = 'var(--primary)';
            skimBtn.style.color = 'var(--primary)';
            skimBtn.style.background = 'rgba(99, 102, 241, 0.1)';
        } else {
            skimBtn.style.borderColor = 'rgba(148,163,184,0.35)';
            skimBtn.style.color = '#cbd5f5';
            skimBtn.style.background = 'transparent';
        }
    }
}

function applyThreadsViewState() {
    const threadsBtn = document.getElementById('threadsViewBtn');
    const enabled = currentView === 'threads';
    document.body.classList.toggle('threads-view', enabled);
    if (threadsBtn) {
        if (enabled) {
            threadsBtn.style.borderColor = 'var(--primary)';
            threadsBtn.style.color = 'var(--primary)';
            threadsBtn.style.background = 'rgba(99, 102, 241, 0.1)';
        } else {
            threadsBtn.style.borderColor = 'rgba(148,163,184,0.35)';
            threadsBtn.style.color = '#cbd5f5';
            threadsBtn.style.background = 'transparent';
        }
    }
}

window.toggleSkimView = () => {
    if (currentView === 'graph' || currentView === 'galaxy') {
        currentView = 'grid';
    }
    currentView = currentView === 'skim' ? 'grid' : 'skim';
    saveUIState();
    applySkimViewState();
    applyThreadsViewState();
    renderPaperGrid(currentVisiblePapers);
};

window.toggleThreadsView = () => {
    if (currentView === 'graph' || currentView === 'galaxy') {
        currentView = 'grid';
    }
    currentView = currentView === 'threads' ? 'grid' : 'threads';
    saveUIState();
    applySkimViewState();
    applyThreadsViewState();
    renderPaperGrid(currentVisiblePapers);
};

function updateFavoritesSortBar() {
    const bar = document.getElementById('favoritesSortBar');
    if (!bar) return;
    if (currentStatus === 'liked') {
        bar.classList.remove('hidden');
    } else {
        bar.classList.add('hidden');
    }
    document.querySelectorAll('.fav-sort-chip').forEach((chip) => {
        chip.classList.toggle('active', chip.dataset.sort === favoritesSort);
    });
}

function initTrail() {
    try {
        trailSessionId = localStorage.getItem(TRAIL_SESSION_KEY);
        if (!trailSessionId) {
            trailSessionId = `trail_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 6)}`;
            localStorage.setItem(TRAIL_SESSION_KEY, trailSessionId);
        }
        const raw = localStorage.getItem(TRAIL_KEY);
        if (raw) {
            const parsed = JSON.parse(raw);
            trailEntries = Array.isArray(parsed) ? parsed : [];
        }
    } catch (e) {
        trailEntries = [];
    }
}

function saveTrail() {
    try {
        localStorage.setItem(TRAIL_KEY, JSON.stringify(trailEntries.slice(-TRAIL_MAX_ENTRIES)));
    } catch (e) {
        // ignore
    }
}

function recordTrail(entry) {
    if (!entry) return;
    const now = Date.now();
    const last = trailEntries.length ? trailEntries[trailEntries.length - 1] : null;
    if (last && last.type === entry.type && last.paper_id === entry.paper_id && (now - (last.ts || 0)) < 30000) {
        return;
    }
    const payload = {
        id: `t_${now.toString(36)}_${Math.random().toString(36).slice(2, 6)}`,
        ts: now,
        ...entry,
    };
    trailEntries.push(payload);
    if (trailEntries.length > TRAIL_MAX_ENTRIES) {
        trailEntries = trailEntries.slice(-TRAIL_MAX_ENTRIES);
    }
    saveTrail();
}

function renderTrailList() {
    const list = document.getElementById('trailList');
    const meta = document.getElementById('trailMeta');
    if (!list) return;
    if (!trailEntries.length) {
        list.innerHTML = '<div style="color:var(--text-muted); text-align:center;">No trail yet.</div>';
        if (meta) meta.textContent = '';
        return;
    }
    if (meta) {
        const lastTs = trailEntries[trailEntries.length - 1]?.ts;
        meta.textContent = `Session ${trailSessionId || ''} · Last activity ${lastTs ? new Date(lastTs).toLocaleString() : ''}`;
    }
    const items = trailEntries.slice().reverse();
    list.innerHTML = items.map((item) => `
        <div class="trail-item">
            <div>
                <div style="font-weight:600;">${escapeHtml(item.label || item.type || 'Trail')}</div>
                <div style="font-size:0.8rem; color:var(--text-muted); margin-top:0.15rem;">
                    ${new Date(item.ts).toLocaleString()}
                </div>
            </div>
            <button class="btn-secondary" onclick="runTrailEntry('${item.id}')" style="padding:0.3rem 0.7rem;">
                Open
            </button>
        </div>
    `).join('');
}

window.openTrailModal = () => {
    renderTrailList();
    showModal('trailModal');
};

window.closeTrailModal = () => {
    hideModal('trailModal');
};

window.clearTrail = () => {
    trailEntries = [];
    saveTrail();
    renderTrailList();
};

window.resumeLastTrail = () => {
    if (!trailEntries.length) return;
    const entry = trailEntries[trailEntries.length - 1];
    runTrailEntry(entry.id);
};

window.runTrailEntry = (entryId) => {
    const entry = trailEntries.find((t) => t.id === entryId);
    if (!entry) return;
    if (entry.type === 'notes' && entry.paper_id) return openNotesModal(entry.paper_id);
    if (entry.type === 'reading' && entry.paper_id) return openReadingModal(entry.paper_id);
    if (entry.type === 'structure' && entry.paper_id) return openStructure(entry.paper_id);
    if (entry.type === 'versions' && entry.paper_id) return openVersionModal(entry.paper_id);
    if (entry.type === 'version_updates') return openVersionUpdatesModal();
    if (entry.type === 'figures' && entry.paper_id) return openFigures(entry.paper_id);
    if (entry.type === 'chat' && entry.paper_id) return openChat(entry.paper_id);
    if (entry.type === 'reading_plan') return openReadingPlanModal();
    if (entry.type === 'weekly_review') return openWeeklyReviewModal();
    if (entry.type === 'unified_inbox') return openUnifiedInboxModal();
    if (entry.type === 'repro' && entry.paper_id) return openReproScorecard(entry.paper_id);
    if (entry.type === 'paper' && entry.paper_id) {
        const card = document.querySelector(`.paper-card[data-paper-id="${CSS.escape(entry.paper_id)}"]`);
        setFocusedPaper(entry.paper_id, card || null);
        if (card) card.scrollIntoView({ behavior: 'smooth', block: 'center' });
        return;
    }
    if (entry.type === 'compare_diff' && entry.paper_ids) return runCompareFromTrail(entry.paper_ids, 'diff');
    if (entry.type === 'compare_matrix' && entry.paper_ids) return runCompareFromTrail(entry.paper_ids, 'matrix');
    if (entry.type === 'benchmark' && entry.paper_ids) return runCompareFromTrail(entry.paper_ids, 'benchmark');
    if (entry.type === 'synthesis' && entry.paper_ids) return runCompareFromTrail(entry.paper_ids, 'synthesis');
};

function runCompareFromTrail(paperIds, mode) {
    if (!Array.isArray(paperIds) || paperIds.length === 0) return;
    selectedPaperIds.clear();
    paperIds.forEach((id) => selectedPaperIds.add(id));
    isSelectionMode = true;
    updateSelectionUI();
    renderPaperGrid(currentVisiblePapers);
    if (mode === 'diff') return startCompareDiff();
    if (mode === 'matrix') return startCompareMatrix();
    if (mode === 'benchmark') return startBenchmarkExtract();
    if (mode === 'synthesis') return startSynthesis();
}

function computeMatchScore(paper) {
    if (!paper) return 0;
    if (paper.match_score !== undefined && paper.match_score !== null) {
        return Number(paper.match_score) || 0;
    }
    const text = `${paper.title || ''} ${paper.summary || ''}`.toLowerCase();
    let score = 0;
    (userKeywords || []).forEach((kw) => {
        const k = String(kw || '').toLowerCase().trim();
        if (k && text.includes(k)) score += 1;
    });
    return score;
}

function applyFavoritesSort(papers) {
    if (!Array.isArray(papers)) return papers;
    const sorted = papers.slice();
    if (favoritesSort === 'date') {
        sorted.sort((a, b) => String(b.published || '').localeCompare(String(a.published || '')));
    } else if (favoritesSort === 'matches') {
        sorted.forEach((p) => { p.match_score = computeMatchScore(p); });
        sorted.sort((a, b) => (b.match_score || 0) - (a.match_score || 0));
    } else if (favoritesSort === 'novelty') {
        sorted.sort((a, b) => (b.novelty_score || 0) - (a.novelty_score || 0));
    }
    return sorted;
}

function updatePaperLocal(paperId, updates) {
    if (!paperId || !updates) return;
    const apply = (list) => {
        if (!Array.isArray(list)) return;
        list.forEach((p) => {
            if (p && p.id === paperId) {
                Object.assign(p, updates);
            }
        });
    };
    apply(allPapers);
    apply(currentVisiblePapers);
}

function getPaperTitleById(paperId) {
    const paper = (allPapers || []).find(p => p.id === paperId) || (currentVisiblePapers || []).find(p => p.id === paperId);
    return paper ? paper.title : paperId;
}

function loadSavedViews() {
    try {
        const raw = localStorage.getItem(SAVED_VIEWS_KEY);
        if (!raw) return [];
        const data = JSON.parse(raw);
        return Array.isArray(data) ? data : [];
    } catch (e) {
        console.warn("Failed to load saved views", e);
        return [];
    }
}

function saveSavedViews(views) {
    try {
        localStorage.setItem(SAVED_VIEWS_KEY, JSON.stringify(views || []));
    } catch (e) {
        console.warn("Failed to save saved views", e);
    }
}

function buildSavedViewPayload(name, existing) {
    const now = new Date().toISOString();
    const searchInput = document.getElementById('searchInput');
    const query = searchInput ? searchInput.value.trim() : '';
    return {
        id: existing && existing.id ? existing.id : `view_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 6)}`,
        name: name,
        view: currentView,
        status: currentStatus || 'new',
        dateFilter: currentDateFilter || null,
        smartSort: Boolean(isSmartSort),
        favoritesSort: favoritesSort || 'ai',
        searchMode: searchMode || 'local',
        searchQuery: query,
        rankProfile: { ...rankProfile },
        created_at: existing && existing.created_at ? existing.created_at : now,
        updated_at: now,
    };
}

function renderSavedViewsBar() {
    const container = document.getElementById('savedViewsChips');
    const bar = document.getElementById('savedViewsBar');
    if (!container || !bar) return;

    const views = loadSavedViews();
    container.innerHTML = '';

    if (!views.length) {
        const empty = document.createElement('span');
        empty.style.color = 'var(--text-muted)';
        empty.style.fontSize = '0.82rem';
        empty.textContent = 'No saved views yet.';
        container.appendChild(empty);
        return;
    }

    views.forEach((view) => {
        const btn = document.createElement('button');
        btn.className = 'filter-chip';
        btn.textContent = view.name || 'View';
        btn.onclick = () => applySavedView(view.id);
        container.appendChild(btn);
    });
}

function renderSavedViewsList() {
    const list = document.getElementById('savedViewsList');
    if (!list) return;
    const views = loadSavedViews();
    if (!views.length) {
        list.innerHTML = '<div style="color:var(--text-muted);">No saved views yet.</div>';
        return;
    }
    const rows = views.map((view) => `
        <div style="border:1px solid rgba(255,255,255,0.12); border-radius:10px; padding:0.75rem; background:rgba(255,255,255,0.03); display:flex; justify-content:space-between; gap:0.8rem; align-items:center;">
            <div>
                <div style="font-weight:600;">${escapeHtml(view.name || 'View')}</div>
                <div style="font-size:0.8rem; color:var(--text-muted); margin-top:0.2rem;">
                    ${escapeHtml(view.status || 'new')} · ${escapeHtml(view.searchMode || 'local')} ${view.searchQuery ? `· ${escapeHtml(view.searchQuery)}` : ''}
                </div>
            </div>
            <div style="display:flex; gap:0.4rem;">
                <button class="btn-secondary" onclick="applySavedView('${view.id}')" style="padding:0.35rem 0.7rem;">
                    <i class="fa-solid fa-bolt"></i> Apply
                </button>
                <button class="btn-secondary" onclick="shareSavedView('${view.id}')" style="padding:0.35rem 0.7rem;">
                    <i class="fa-solid fa-share-nodes"></i> Share
                </button>
                <button class="btn-secondary" onclick="deleteSavedView('${view.id}')" style="padding:0.35rem 0.7rem; color:#f87171; border-color: rgba(248,113,113,0.35);">
                    <i class="fa-solid fa-trash"></i> Delete
                </button>
            </div>
        </div>
    `).join('');
    list.innerHTML = rows;
}

window.openSavedViewsModal = () => {
    showModal('savedViewsModal');
    renderSavedViewsList();
};

window.closeSavedViewsModal = () => {
    hideModal('savedViewsModal');
};

window.saveCurrentView = () => {
    const input = document.getElementById('savedViewNameInput');
    const name = input ? input.value.trim() : '';
    if (!name) {
        alert("Please provide a name for this view.");
        return;
    }
    const views = loadSavedViews();
    const idx = views.findIndex(v => String(v.name || '').toLowerCase() === name.toLowerCase());
    const existing = idx >= 0 ? views[idx] : null;
    const payload = buildSavedViewPayload(name, existing);
    if (idx >= 0) {
        views[idx] = payload;
    } else {
        views.unshift(payload);
    }
    saveSavedViews(views);
    if (input) input.value = '';
    renderSavedViewsBar();
    renderSavedViewsList();
};

window.applySavedView = (id) => {
    const views = loadSavedViews();
    const view = views.find(v => v.id === id);
    if (!view) return;

    currentView = view.view || 'grid';
    currentStatus = view.status || 'new';
    currentDateFilter = view.dateFilter || null;
    isSmartSort = Boolean(view.smartSort);
    favoritesSort = view.favoritesSort || 'ai';
    searchMode = view.searchMode || 'local';
    if (view.rankProfile) {
        saveRankProfile(view.rankProfile);
        applyRankProfileToControls(rankProfile);
    }

    const graphView = document.getElementById('graphView');
    if (graphView) graphView.classList.add('hidden');
    const galaxyView = document.getElementById('galaxyView');
    if (galaxyView) galaxyView.classList.add('hidden');
    const grid = document.getElementById('paperGrid');
    if (grid) grid.classList.remove('hidden');

    const searchInput = document.getElementById('searchInput');
    if (searchInput) {
        searchInput.value = view.searchQuery || '';
    }

    applyUIStateToControls();
    updateFavoritesSortBar();
    saveUIState();

    const query = searchInput ? searchInput.value.trim() : '';
    if (query) {
        handleSearch(query);
    } else {
        loadPapers();
    }

    closeSavedViewsModal();
};

window.deleteSavedView = (id) => {
    const views = loadSavedViews();
    const next = views.filter(v => v.id !== id);
    saveSavedViews(next);
    renderSavedViewsBar();
    renderSavedViewsList();
};

function formatLocalTimestamp(value) {
    if (!value) return '';
    const dt = new Date(value);
    if (!Number.isFinite(dt.getTime())) return String(value);
    return dt.toLocaleString();
}

function computeChangeSummaryTotal(counts) {
    const c = counts || {};
    return (Number(c.new_papers || 0) + Number(c.version_updates || 0) + Number(c.citation_updates || 0));
}

async function fetchChangeSummary(sinceIso) {
    const res = await fetch(`${API_BASE}/changes?since=${encodeURIComponent(sinceIso)}`);
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
    return data;
}

function updateChangeSummaryBadge(data) {
    const badge = document.getElementById('changeSummaryBadge');
    if (!badge) return;
    const total = computeChangeSummaryTotal(data ? data.counts : null);
    if (total > 0) {
        badge.style.display = 'inline-flex';
        badge.textContent = total > 99 ? '99+' : String(total);
    } else {
        badge.style.display = 'none';
        badge.textContent = '0';
    }
}

function renderChangeSummary(data) {
    const container = document.getElementById('changeSummaryContent');
    if (!container) return;

    const counts = data.counts || {};
    const sinceLabel = formatLocalTimestamp(data.since || changeSummarySince);
    const asOfLabel = formatLocalTimestamp(data.as_of);

    const newItems = Array.isArray(data.new_papers) ? data.new_papers : [];
    const versionItems = Array.isArray(data.version_updates) ? data.version_updates : [];
    const citationItems = Array.isArray(data.citation_updates) ? data.citation_updates : [];

    const renderList = (items, renderRow) => {
        if (!items.length) return '<div style="color:var(--text-muted); font-size:0.85rem;">None</div>';
        return `<ul style="margin:0.35rem 0 0 1.1rem; line-height:1.5;">${items.map(renderRow).join('')}</ul>`;
    };

    container.innerHTML = `
        <div style="display:flex; gap:0.6rem; flex-wrap:wrap; align-items:center;">
            <span class="tag">Since ${escapeHtml(sinceLabel || '')}</span>
            <span class="tag" style="background:rgba(148,163,184,0.2); color:#cbd5f5;">As of ${escapeHtml(asOfLabel || '')}</span>
        </div>
        <div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(220px, 1fr)); gap:0.8rem;">
            <div style="border:1px solid rgba(255,255,255,0.12); border-radius:10px; padding:0.75rem; background:rgba(255,255,255,0.03);">
                <div style="font-weight:600;">New papers</div>
                <div style="font-size:1.2rem; margin-top:0.25rem;">${Number(counts.new_papers || 0)}</div>
            </div>
            <div style="border:1px solid rgba(255,255,255,0.12); border-radius:10px; padding:0.75rem; background:rgba(255,255,255,0.03);">
                <div style="font-weight:600;">Version updates</div>
                <div style="font-size:1.2rem; margin-top:0.25rem;">${Number(counts.version_updates || 0)}</div>
            </div>
            <div style="border:1px solid rgba(255,255,255,0.12); border-radius:10px; padding:0.75rem; background:rgba(255,255,255,0.03);">
                <div style="font-weight:600;">Citation updates</div>
                <div style="font-size:1.2rem; margin-top:0.25rem;">${Number(counts.citation_updates || 0)}</div>
            </div>
        </div>
        <div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(260px, 1fr)); gap:0.8rem;">
            <div style="border:1px solid rgba(255,255,255,0.12); border-radius:10px; padding:0.75rem; background:rgba(255,255,255,0.03);">
                <div style="font-weight:600;">Newest papers</div>
                ${renderList(newItems, (p) => `
                    <li>
                        <span style="font-weight:600;">${escapeHtml(p.title || p.id || 'Paper')}</span>
                        <div style="font-size:0.82rem; color:var(--text-muted);">${escapeHtml((p.published || p.fetched_at || '').slice(0, 10))}</div>
                    </li>
                `)}
            </div>
            <div style="border:1px solid rgba(255,255,255,0.12); border-radius:10px; padding:0.75rem; background:rgba(255,255,255,0.03);">
                <div style="font-weight:600;">Version updates</div>
                ${renderList(versionItems, (p) => `
                    <li>
                        <span style="font-weight:600;">${escapeHtml(p.title || p.paper_id || 'Paper')}</span>
                        <div style="font-size:0.82rem; color:var(--text-muted);">${escapeHtml(p.message || '')}</div>
                    </li>
                `)}
            </div>
            <div style="border:1px solid rgba(255,255,255,0.12); border-radius:10px; padding:0.75rem; background:rgba(255,255,255,0.03);">
                <div style="font-weight:600;">Citation updates</div>
                ${renderList(citationItems, (p) => `
                    <li>
                        <span style="font-weight:600;">${escapeHtml(p.title || p.id || 'Paper')}</span>
                        <div style="font-size:0.82rem; color:var(--text-muted);">Citations: ${Number(p.citation_count || 0)}</div>
                    </li>
                `)}
            </div>
        </div>
    `;
}

async function initializeChangeSummary() {
    const nowIso = new Date().toISOString();
    const lastVisit = localStorage.getItem(LAST_VISIT_KEY);
    if (!lastVisit) {
        localStorage.setItem(LAST_VISIT_KEY, nowIso);
        return;
    }
    changeSummarySince = lastVisit;
    try {
        const data = await fetchChangeSummary(lastVisit);
        changeSummarySnapshot = data;
        updateChangeSummaryBadge(data);
    } catch (e) {
        console.warn("Failed to load change summary", e);
    } finally {
        localStorage.setItem(LAST_VISIT_KEY, nowIso);
    }
}

window.openChangeSummaryModal = async () => {
    showModal('changeSummaryModal');
    const container = document.getElementById('changeSummaryContent');
    if (container) container.innerHTML = '<div class="loader"></div>';
    try {
        if (changeSummarySnapshot) {
            renderChangeSummary(changeSummarySnapshot);
        } else if (changeSummarySince) {
            const data = await fetchChangeSummary(changeSummarySince);
            changeSummarySnapshot = data;
            renderChangeSummary(data);
        } else {
            const fallbackSince = new Date(Date.now() - 24 * 3600 * 1000).toISOString();
            const data = await fetchChangeSummary(fallbackSince);
            changeSummarySnapshot = data;
            renderChangeSummary(data);
        }
        const badge = document.getElementById('changeSummaryBadge');
        if (badge) {
            badge.style.display = 'none';
            badge.textContent = '0';
        }
    } catch (e) {
        if (container) container.innerHTML = `<div style="color:var(--danger)">Failed to load summary: ${escapeHtml(e.message)}</div>`;
    }
};

window.closeChangeSummaryModal = () => {
    hideModal('changeSummaryModal');
};

function getFavoritesCacheEntry() {
    const cacheKey = getFavoritesCacheKey();
    const entry = favoritesCache[cacheKey];
    if (!entry) return null;
    if ((Date.now() - entry.ts) > FAVORITES_CACHE_TTL_MS) {
        delete favoritesCache[cacheKey];
        return null;
    }
    return entry;
}

function setFavoritesCache(items) {
    const cacheKey = getFavoritesCacheKey();
    favoritesCache[cacheKey] = {
        items: Array.isArray(items) ? items : [],
        ts: Date.now(),
    };
}

function invalidateFavoritesCache() {
    Object.keys(favoritesCache).forEach((k) => delete favoritesCache[k]);
}

function getFavoritesCacheKey() {
    if (favoritesSort !== 'ai') return favoritesSort;
    const weights = normalizeRankProfile(rankProfile);
    return `ai:${weights.relevance}-${weights.novelty}-${weights.citations}`;
}

function isEditableTarget(el) {
    if (!el) return false;
    const tag = (el.tagName || '').toLowerCase();
    if (['input', 'textarea', 'select'].includes(tag)) return true;
    return Boolean(el.isContentEditable);
}

function setFocusedPaper(id, cardEl) {
    if (!id) return;
    focusedPaperId = id;
    document.querySelectorAll('.paper-card.focused').forEach(el => el.classList.remove('focused'));
    if (cardEl) {
        cardEl.classList.add('focused');
    } else {
        const found = document.querySelector(`.paper-card[data-paper-id="${CSS.escape(id)}"]`);
        if (found) found.classList.add('focused');
    }
    recordTrail({ type: 'paper', paper_id: id, label: `Paper: ${getPaperTitleById(id)}` });
}

function ensureFocusedPaper() {
    if (focusedPaperId) {
        const card = document.querySelector(`.paper-card[data-paper-id="${CSS.escape(focusedPaperId)}"]`);
        if (card) {
            card.classList.add('focused');
            return;
        }
    }
    const first = document.querySelector('.paper-card');
    if (first) {
        const pid = first.getAttribute('data-paper-id');
        if (pid) setFocusedPaper(pid, first);
    }
}

function getFocusedCardOrFirst() {
    if (focusedPaperId) {
        const card = document.querySelector(`.paper-card[data-paper-id="${CSS.escape(focusedPaperId)}"]`);
        if (card) return card;
    }
    const first = document.querySelector('.paper-card');
    if (first) {
        const pid = first.getAttribute('data-paper-id');
        if (pid) setFocusedPaper(pid, first);
        return first;
    }
    return null;
}

function initializeKeyboardShortcuts() {
    document.addEventListener('keydown', (event) => {
        const key = (event.key || '').toLowerCase();
        const hasModifier = event.metaKey || event.ctrlKey || event.altKey;
        if (hasModifier && key === 'k') {
            event.preventDefault();
            const input = document.getElementById('searchInput');
            if (input) input.focus();
            return;
        }
        if (isEditableTarget(document.activeElement)) return;

        const openModals = Array.from(document.querySelectorAll('.modal-overlay'))
            .filter(m => !m.classList.contains('hidden'));
        if (openModals.length > 0) return;

        if (key === '/') {
            event.preventDefault();
            const input = document.getElementById('searchInput');
            if (input) input.focus();
            return;
        }

        if (hasModifier) return;

        if (key === 'l' || key === 'd' || key === 'b') {
            const card = getFocusedCardOrFirst();
            if (!card) return;
            const pid = card.getAttribute('data-paper-id');
            if (!pid) return;
            if (key === 'l') {
                const btn = card.querySelector('.action-btn.like');
                if (btn) handleRate(pid, 'liked', btn);
            } else if (key === 'd') {
                const btn = card.querySelector('.action-btn.dismiss');
                if (btn) handleRate(pid, 'dismissed', btn);
            } else if (key === 'b') {
                const btn = card.querySelector('.action-btn.bookmark');
                if (btn) toggleBookmark(pid, btn);
            }
            return;
        }

        if (key === 'm') {
            if (typeof openBrief === 'function') openBrief();
            return;
        }
        if (key === 'i') {
            if (typeof openDigestModal === 'function') openDigestModal();
            return;
        }
        if (key === 'a') {
            if (typeof openAlertsModal === 'function') openAlertsModal();
            return;
        }
        if (key === 's') {
            if (typeof openSettings === 'function') openSettings();
            return;
        }
        if (key === 'g') {
            openGraphView();
            return;
        }
    });
}

function initializeUnifiedInboxShortcuts() {
    document.addEventListener('keydown', (event) => {
        const modal = document.getElementById('unifiedInboxModal');
        if (!modal || modal.classList.contains('hidden')) return;
        if (isEditableTarget(document.activeElement)) return;
        if (event.metaKey || event.ctrlKey || event.altKey) return;
        const key = String(event.key || '').toLowerCase();
        if (key === '1' || key === '2' || key === '3' || key === '4') {
            event.preventDefault();
            const map = {
                '1': 'unifiedInboxKindAlert',
                '2': 'unifiedInboxKindVersion',
                '3': 'unifiedInboxKindFollowup',
                '4': 'unifiedInboxKindDigest',
            };
            const id = map[key];
            const el = document.getElementById(id);
            if (el) {
                el.checked = !el.checked;
                refreshUnifiedInbox();
            }
            return;
        }
        if (key === 'a') {
            event.preventDefault();
            const allBox = document.getElementById('unifiedInboxSelectAll');
            const next = !(allBox && allBox.checked);
            if (allBox) allBox.checked = next;
            toggleUnifiedInboxSelectAll(next);
            return;
        }
        if (key === 'x') {
            event.preventDefault();
            clearUnifiedInboxSelection();
            return;
        }
        if (key === 'r') {
            event.preventDefault();
            refreshUnifiedInbox();
            return;
        }
        if (key === 'enter') {
            event.preventDefault();
            applyUnifiedInboxBulkAction();
        }
    });
}

function loadScriptOnce(key, src) {
    if (lazyScriptPromises[key]) return lazyScriptPromises[key];
    lazyScriptPromises[key] = new Promise((resolve, reject) => {
        const existing = document.querySelector(`script[data-lazy-key="${key}"]`);
        if (existing) {
            existing.addEventListener('load', () => resolve());
            existing.addEventListener('error', () => reject(new Error(`Failed to load ${src}`)));
            return;
        }

        const s = document.createElement('script');
        s.src = src;
        s.async = true;
        s.defer = true;
        s.dataset.lazyKey = key;
        s.onload = () => resolve();
        s.onerror = () => reject(new Error(`Failed to load ${src}`));
        document.head.appendChild(s);
    });
    return lazyScriptPromises[key];
}

async function ensureChartLib() {
    if (typeof Chart !== 'undefined') return;
    await loadScriptOnce('chart', LAZY_LIB_SOURCES.chart);
}

async function ensureVisLib() {
    if (typeof vis !== 'undefined') return;
    await loadScriptOnce('vis', LAZY_LIB_SOURCES.vis);
}

async function ensureMarkdownLibs() {
    const tasks = [];
    if (typeof marked === 'undefined') {
        tasks.push(loadScriptOnce('marked', LAZY_LIB_SOURCES.marked));
    }
    if (typeof DOMPurify === 'undefined') {
        tasks.push(loadScriptOnce('dompurify', LAZY_LIB_SOURCES.dompurify));
    }
    if (tasks.length > 0) {
        await Promise.all(tasks);
    }
}

function renderCountBadge(badge, count) {
    if (!badge) return;
    const value = Math.max(0, Number(count || 0));
    if (value > 0) {
        badge.style.display = 'inline-flex';
        badge.textContent = value > 99 ? '99+' : String(value);
    } else {
        badge.style.display = 'none';
        badge.textContent = '0';
    }
}

async function refreshAlertsBadge() {
    const badge = document.getElementById('alertsBadge');
    if (!badge) return;
    try {
        const res = await fetch(`${API_BASE}/alerts/count`);
        const data = await res.json();
        renderCountBadge(badge, Number(data.unseen || 0));
    } catch (e) {
        console.error("Failed to refresh alerts badge", e);
    }
}

async function refreshDigestBadge() {
    const badge = document.getElementById('digestBadge');
    if (!badge) return;
    try {
        const res = await fetch(`${API_BASE}/digest/unread-count`);
        const data = await res.json();
        renderCountBadge(badge, Number(data.unread || 0));
    } catch (e) {
        console.error("Failed to refresh digest badge", e);
    }
}

async function refreshVersionUpdatesBadge() {
    const badge = document.getElementById('versionUpdatesBadge');
    if (!badge) return;
    try {
        const scope = encodeURIComponent(versionUpdatesState.scope || 'watchlist');
        const res = await fetch(`${API_BASE}/version-updates/count?scope=${scope}`);
        const data = await res.json();
        renderCountBadge(badge, Number(data.active || 0));
    } catch (e) {
        console.error("Failed to refresh version updates badge", e);
    }
}

async function refreshUnifiedInboxBadge() {
    const badge = document.getElementById('unifiedInboxBadge');
    if (!badge) return;
    try {
        const scope = String(unifiedInboxState.versionScope || 'watchlist');
        const days = Math.max(1, Math.min(180, Number(unifiedInboxState.versionDays || 30)));
        const kinds = Array.isArray(unifiedInboxState.kinds) ? unifiedInboxState.kinds : [];
        if (!kinds.length) {
            badge.style.display = 'none';
            badge.textContent = '0';
            return;
        }
        const query = new URLSearchParams();
        query.set('version_scope', scope);
        query.set('version_days', String(days));
        if (kinds.length) query.set('kinds', kinds.join(','));
        const res = await fetch(`${API_BASE}/inbox/count?${query.toString()}`);
        const data = await res.json();
        const count = Number(data.total || 0);
        renderCountBadge(badge, count);
    } catch (e) {
        console.error("Failed to refresh unified inbox badge", e);
    }
}

let badgeRefreshInFlight = null;
let badgeLastRefreshAt = 0;
const BADGE_REFRESH_DEBOUNCE_MS = 800;

async function refreshAllBadges(options = {}) {
    const force = Boolean(options && options.force);
    if (!force && badgeRefreshInFlight) {
        return badgeRefreshInFlight;
    }
    if (!force && (Date.now() - badgeLastRefreshAt) < BADGE_REFRESH_DEBOUNCE_MS) {
        return null;
    }

    badgeRefreshInFlight = (async () => {
        try {
            const inboxScope = String(unifiedInboxState.versionScope || 'watchlist');
            const inboxDays = Math.max(1, Math.min(180, Number(unifiedInboxState.versionDays || 30)));
            const versionScope = encodeURIComponent(versionUpdatesState.scope || 'watchlist');
            const inboxQuery = new URLSearchParams();
            inboxQuery.set('version_scope', inboxScope);
            inboxQuery.set('version_days', String(inboxDays));
            inboxQuery.set('kinds', 'alert,version_update,follow_up,digest');

            const [inboxRes, versionRes] = await Promise.all([
                fetch(`${API_BASE}/inbox/count?${inboxQuery.toString()}`),
                fetch(`${API_BASE}/version-updates/count?scope=${versionScope}`),
            ]);
            const inboxData = await inboxRes.json();
            const versionData = await versionRes.json();
            if (!inboxRes.ok) throw new Error(inboxData.detail || `Inbox count failed (${inboxRes.status})`);
            if (!versionRes.ok) throw new Error(versionData.detail || `Version count failed (${versionRes.status})`);

            const counts = inboxData && typeof inboxData.counts === 'object' ? inboxData.counts : {};
            const alertsCount = Number(counts.alerts || 0);
            const digestCount = Number(counts.digests || 0);
            const followupsCount = Number(counts.follow_ups || 0);
            const selectedKinds = Array.isArray(unifiedInboxState.kinds) ? unifiedInboxState.kinds : [];
            let unifiedCount = 0;
            if (selectedKinds.length > 0) {
                const countByKind = {
                    alert: alertsCount,
                    version_update: Number(counts.version_updates || 0),
                    follow_up: followupsCount,
                    digest: digestCount,
                };
                selectedKinds.forEach((kind) => {
                    unifiedCount += Number(countByKind[kind] || 0);
                });
            }

            renderCountBadge(document.getElementById('alertsBadge'), alertsCount);
            renderCountBadge(document.getElementById('digestBadge'), digestCount);
            renderCountBadge(document.getElementById('followupsBadge'), followupsCount);
            renderCountBadge(document.getElementById('unifiedInboxBadge'), unifiedCount);
            renderCountBadge(document.getElementById('versionUpdatesBadge'), Number(versionData.active || 0));
        } catch (e) {
            console.error("Failed to refresh aggregated badges", e);
        } finally {
            badgeLastRefreshAt = Date.now();
        }
    })();

    try {
        return await badgeRefreshInFlight;
    } finally {
        badgeRefreshInFlight = null;
    }
}

function getMentionHandle() {
    return (localStorage.getItem(MENTION_HANDLE_KEY) || '').trim();
}

function mentionReadStorageKey(handle) {
    const clean = (handle || '').trim().replace(/^@+/, '');
    return `${MENTION_READ_KEY_PREFIX}${clean || 'default'}`;
}

function loadMentionReadSet(handle) {
    mentionReadSet = new Set();
    const key = mentionReadStorageKey(handle);
    try {
        const raw = localStorage.getItem(key);
        const parsed = raw ? JSON.parse(raw) : [];
        if (Array.isArray(parsed)) {
            parsed.forEach((id) => {
                if (id) mentionReadSet.add(id);
            });
        }
    } catch (e) {
        mentionReadSet = new Set();
    }
}

function saveMentionReadSet(handle) {
    const key = mentionReadStorageKey(handle);
    const items = Array.from(mentionReadSet).slice(-500);
    localStorage.setItem(key, JSON.stringify(items));
}

async function refreshMentionsBadge() {
    const badge = document.getElementById('mentionsBadge');
    if (!badge) return;
    const handle = getMentionHandle();
    if (!handle) {
        badge.style.display = 'none';
        badge.textContent = '0';
        return;
    }
    loadMentionReadSet(handle);
    try {
        const res = await fetch(`${API_BASE}/mentions?handle=${encodeURIComponent(handle)}`);
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
        const items = Array.isArray(data) ? data : [];
        const unread = items.filter((m) => m && m.id && !mentionReadSet.has(m.id));
        const count = unread.length;
        if (count > 0) {
            badge.style.display = 'inline-flex';
            badge.textContent = count > 99 ? '99+' : String(count);
        } else {
            badge.style.display = 'none';
            badge.textContent = '0';
        }
    } catch (e) {
        badge.style.display = 'none';
        badge.textContent = '0';
    }
}

async function refreshSchedulerLeaderBadge() {
    const badge = document.getElementById('schedulerLeaderBadge');
    if (!badge) return;
    try {
        const res = await fetch(`${API_BASE}/system/scheduler-leader`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();

        badge.style.display = 'inline-flex';
        const age = data.heartbeat_age_seconds;
        const ageText = Number.isFinite(age) ? `${age.toFixed(1)}s` : 'n/a';

        if (data.has_leader && data.self_is_leader) {
            badge.style.borderColor = 'rgba(34,197,94,0.45)';
            badge.style.color = '#86efac';
            badge.innerHTML = '<i class="fa-solid fa-crown"></i> Scheduler: Leader';
            badge.title = `This worker is leader (${data.self_owner_id}).`;
        } else if (data.has_leader) {
            badge.style.borderColor = 'rgba(245,158,11,0.45)';
            badge.style.color = '#fcd34d';
            badge.innerHTML = '<i class="fa-solid fa-user-group"></i> Scheduler: Follower';
            badge.title = `Leader: ${data.owner_id} | heartbeat age: ${ageText}`;
        } else {
            badge.style.borderColor = 'rgba(148,163,184,0.4)';
            badge.style.color = '#94a3b8';
            badge.innerHTML = '<i class="fa-regular fa-circle-pause"></i> Scheduler: Idle';
            badge.title = 'No active scheduler leader lock yet.';
        }
    } catch (e) {
        badge.style.display = 'inline-flex';
        badge.style.borderColor = 'rgba(239,68,68,0.45)';
        badge.style.color = '#fca5a5';
        badge.innerHTML = '<i class="fa-solid fa-triangle-exclamation"></i> Scheduler: Unknown';
        badge.title = `Failed to load scheduler status: ${e.message}`;
    }
}

async function refreshHealthBanner() {
    const banner = document.getElementById('healthBanner');
    if (!banner) return;
    let indexText = 'Index ok';
    let lastFetchText = 'Last fetch: --';
    let stale = false;

    try {
        const [runsRes, healthRes] = await Promise.all([
            fetch(`${API_BASE}/daily-fetch/runs?limit=1`),
            fetch('/health'),
        ]);

        if (runsRes.ok) {
            const runs = await runsRes.json();
            if (Array.isArray(runs) && runs.length) {
                const run = runs[0] || {};
                const status = String(run.status || '').toLowerCase();
                const date = run.date || (run.created_at || '').slice(0, 10);
                const suffix = status && status !== 'ok' ? ` (${status})` : '';
                lastFetchText = `Last fetch: ${date || '--'}${suffix}`;
            }
        }

        if (healthRes.ok) {
            const health = await healthRes.json();
            const fts = health.fts || {};
            const coverage = Number(fts.coverage || 0);
            const ok = Boolean(fts.ok) && coverage >= INDEX_STALE_COVERAGE;
            if (!ok) {
                stale = true;
                indexText = 'Index stale';
            }
        } else {
            stale = true;
            indexText = 'Index stale';
        }
    } catch (e) {
        stale = true;
        indexText = 'Index stale';
    }

    banner.textContent = `${indexText} • ${lastFetchText}`;
    banner.classList.toggle('stale', stale);
}

function formatAgeSeconds(value) {
    const seconds = Number(value);
    if (!Number.isFinite(seconds)) return 'n/a';
    if (seconds < 60) return `${seconds.toFixed(1)}s`;
    if (seconds < 3600) return `${Math.round(seconds / 60)}m`;
    return `${Math.round(seconds / 3600)}h`;
}

window.openSchedulerOpsModal = async () => {
    showModal('schedulerOpsModal');
    await loadSchedulerOps();
};

window.closeSchedulerOpsModal = () => {
    hideModal('schedulerOpsModal');
};

window.loadSchedulerOps = async () => {
    const container = document.getElementById('schedulerOpsContent');
    if (!container) return;
    container.innerHTML = '<div class="loader"></div>';
    try {
        const res = await fetch(`${API_BASE}/system/scheduler-ops`);
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);

        const leader = data.leader || {};
        const agents = data.agents || {};
        const jobs = data.jobs || {};

        const leaderTag = leader.self_is_leader
            ? '<span class="tag" style="background:rgba(34,197,94,0.2); color:#86efac;">this worker is leader</span>'
            : (leader.has_leader
                ? '<span class="tag" style="background:rgba(245,158,11,0.2); color:#fcd34d;">follower</span>'
                : '<span class="tag">idle</span>');

        const agentItems = (agents.items || []).slice(0, 20).map((a) => `
            <tr>
                <td style="padding:0.45rem; border-bottom:1px solid rgba(255,255,255,0.08);">${escapeHtml(a.name)}</td>
                <td style="padding:0.45rem; border-bottom:1px solid rgba(255,255,255,0.08);">${escapeHtml(a.cadence || 'daily')}</td>
                <td style="padding:0.45rem; border-bottom:1px solid rgba(255,255,255,0.08);">${a.overdue ? '<span style="color:#fca5a5;">due</span>' : '<span style="color:#86efac;">scheduled</span>'}</td>
                <td style="padding:0.45rem; border-bottom:1px solid rgba(255,255,255,0.08);"><code>${escapeHtml(a.next_due_at || '')}</code></td>
            </tr>
        `).join('');

        const recentJobs = (jobs.recent || []).slice(0, 12).map((j) => `
            <tr>
                <td style="padding:0.45rem; border-bottom:1px solid rgba(255,255,255,0.08);">${escapeHtml(j.type)}</td>
                <td style="padding:0.45rem; border-bottom:1px solid rgba(255,255,255,0.08);">${escapeHtml(j.status)}</td>
                <td style="padding:0.45rem; border-bottom:1px solid rgba(255,255,255,0.08);">${Number(j.attempts || 0)}/${Number(j.max_attempts || 0)}</td>
                <td style="padding:0.45rem; border-bottom:1px solid rgba(255,255,255,0.08);"><code>${escapeHtml(j.updated_at || '')}</code></td>
            </tr>
        `).join('');

        container.innerHTML = `
            <div style="display:grid; grid-template-columns:repeat(3, minmax(0,1fr)); gap:0.7rem;">
                <div style="border:1px solid rgba(255,255,255,0.12); border-radius:10px; padding:0.8rem; background:rgba(255,255,255,0.03);">
                    <div style="font-size:0.8rem; color:var(--text-muted);">Scheduler lock</div>
                    <div style="margin-top:0.25rem; font-weight:700;">${leader.has_leader ? escapeHtml(leader.owner_id || 'unknown') : 'No leader'}</div>
                    <div style="margin-top:0.35rem;">${leaderTag}</div>
                    <div style="font-size:0.82rem; color:var(--text-muted); margin-top:0.4rem;">Heartbeat age: ${formatAgeSeconds(leader.heartbeat_age_seconds)}</div>
                </div>
                <div style="border:1px solid rgba(255,255,255,0.12); border-radius:10px; padding:0.8rem; background:rgba(255,255,255,0.03);">
                    <div style="font-size:0.8rem; color:var(--text-muted);">Saved search agents</div>
                    <div style="margin-top:0.25rem; font-size:1.2rem; font-weight:700;">${Number(agents.total || 0)}</div>
                    <div style="font-size:0.82rem; color:var(--text-muted); margin-top:0.4rem;">Due now: ${Number(agents.due_now || 0)}</div>
                </div>
                <div style="border:1px solid rgba(255,255,255,0.12); border-radius:10px; padding:0.8rem; background:rgba(255,255,255,0.03);">
                    <div style="font-size:0.8rem; color:var(--text-muted);">Job queue</div>
                    <div style="margin-top:0.25rem; font-size:1.2rem; font-weight:700;">${Number(jobs.total || 0)} jobs</div>
                    <div style="font-size:0.82rem; color:var(--text-muted); margin-top:0.4rem;">Queued now: ${Number(jobs.queue_size || 0)}</div>
                </div>
            </div>
            <div style="display:grid; grid-template-columns:1fr 1fr; gap:0.8rem;">
                <div style="border:1px solid rgba(255,255,255,0.12); border-radius:10px; padding:0.6rem; background:rgba(255,255,255,0.03);">
                    <div style="font-weight:700; margin-bottom:0.45rem;">Agent Schedule</div>
                    <table style="width:100%; border-collapse:collapse; font-size:0.84rem;">
                        <thead>
                            <tr>
                                <th style="text-align:left; padding:0.45rem; color:var(--text-muted); border-bottom:1px solid rgba(255,255,255,0.12);">Name</th>
                                <th style="text-align:left; padding:0.45rem; color:var(--text-muted); border-bottom:1px solid rgba(255,255,255,0.12);">Cadence</th>
                                <th style="text-align:left; padding:0.45rem; color:var(--text-muted); border-bottom:1px solid rgba(255,255,255,0.12);">State</th>
                                <th style="text-align:left; padding:0.45rem; color:var(--text-muted); border-bottom:1px solid rgba(255,255,255,0.12);">Next due</th>
                            </tr>
                        </thead>
                        <tbody>${agentItems || '<tr><td colspan="4" style="padding:0.6rem; color:var(--text-muted);">No agents yet.</td></tr>'}</tbody>
                    </table>
                </div>
                <div style="border:1px solid rgba(255,255,255,0.12); border-radius:10px; padding:0.6rem; background:rgba(255,255,255,0.03);">
                    <div style="font-weight:700; margin-bottom:0.45rem;">Recent Jobs</div>
                    <table style="width:100%; border-collapse:collapse; font-size:0.84rem;">
                        <thead>
                            <tr>
                                <th style="text-align:left; padding:0.45rem; color:var(--text-muted); border-bottom:1px solid rgba(255,255,255,0.12);">Type</th>
                                <th style="text-align:left; padding:0.45rem; color:var(--text-muted); border-bottom:1px solid rgba(255,255,255,0.12);">Status</th>
                                <th style="text-align:left; padding:0.45rem; color:var(--text-muted); border-bottom:1px solid rgba(255,255,255,0.12);">Attempts</th>
                                <th style="text-align:left; padding:0.45rem; color:var(--text-muted); border-bottom:1px solid rgba(255,255,255,0.12);">Updated</th>
                            </tr>
                        </thead>
                        <tbody>${recentJobs || '<tr><td colspan="4" style="padding:0.6rem; color:var(--text-muted);">No jobs yet.</td></tr>'}</tbody>
                    </table>
                </div>
            </div>
        `;
    } catch (e) {
        container.innerHTML = `<div style="color:var(--danger)">Failed to load scheduler ops: ${escapeHtml(e.message)}</div>`;
    }
};

function renderAlertCards(alerts) {
    const container = document.getElementById('alertsList');
    if (!container) return;

    if (!alerts || alerts.length === 0) {
        container.innerHTML = '<div style="text-align:center; color:var(--text-muted); padding:1.5rem;">No alerts right now.</div>';
        return;
    }

    container.innerHTML = alerts.map(a => `
        <div style="border:1px solid rgba(255,255,255,0.12); border-radius:10px; padding:0.9rem; background:rgba(255,255,255,0.03);">
            <div style="display:flex; justify-content:space-between; gap:1rem; align-items:flex-start;">
                <div>
                    <div style="font-weight:600;">${a.title || a.paper_id}</div>
                    <div style="font-size:0.85rem; color:var(--text-muted); margin-top:0.2rem;">${a.message}</div>
                    <div style="font-size:0.8rem; color:var(--text-muted); margin-top:0.3rem;">
                        ${(a.authors || []).slice(0, 3).join(', ')}
                    </div>
                </div>
                <div style="display:flex; gap:0.4rem;">
                    <span class="tag" style="background:rgba(245,158,11,0.2); color:#f59e0b;">${a.alert_type}</span>
                    ${a.seen ? '<span class="tag">seen</span>' : '<span class="tag" style="background:rgba(239,68,68,0.2); color:#fca5a5;">new</span>'}
                </div>
            </div>
            ${a.alert_type === 'version' && a.paper_id ? `
                <div style="display:flex; gap:0.45rem; margin-top:0.6rem; flex-wrap:wrap;">
                    <button class="btn-secondary" onclick="openVersionModal(decodeURIComponent('${encodeURIComponent(String(a.paper_id))}'))" style="padding:0.3rem 0.65rem;">
                        <i class="fa-solid fa-code-compare"></i> Open Diff
                    </button>
                    <button class="btn-secondary" onclick="openVersionUpdatesModal()" style="padding:0.3rem 0.65rem;">
                        <i class="fa-solid fa-inbox"></i> Version Inbox
                    </button>
                </div>
            ` : ''}
        </div>
    `).join('');
}

// Init
document.addEventListener('DOMContentLoaded', () => {
    initTrail();
    initializeModalUX();
    loadUIState();
    loadRankProfile();
    applyUIStateToControls();
    applyRankProfileToControls(rankProfile);
    initRankProfileControls();
    renderSavedViewsBar();
    initializeChangeSummary();
    updateRecentSearchDatalist();
    fetchConfig();
    fetchFollowedAuthors();
    refreshAllBadges({ force: true });
    refreshMentionsBadge();
    refreshSchedulerLeaderBadge();
    refreshHealthBanner();
    loadPapers();
    if (currentView === 'graph') {
        openGraphView();
    } else if (currentView === 'galaxy') {
        toggleGalaxyView();
    }

    if (schedulerLeaderTimer) clearInterval(schedulerLeaderTimer);
    schedulerLeaderTimer = setInterval(refreshSchedulerLeaderBadge, 60000);
    setInterval(refreshHealthBanner, 300000);
    setInterval(refreshMentionsBadge, 90000);
    setInterval(() => refreshAllBadges(), 120000);
    const schedulerBadge = document.getElementById('schedulerLeaderBadge');
    if (schedulerBadge) {
        schedulerBadge.addEventListener('click', () => openSchedulerOpsModal());
    }

    fetchBtn.addEventListener('click', fetchNewPapers);

    const smartBtn = document.getElementById('smartRankBtn');
    smartBtn.addEventListener('click', () => {
        isSmartSort = !isSmartSort;
        if (isSmartSort) {
            smartBtn.style.borderColor = 'var(--primary)';
            smartBtn.style.color = 'var(--primary)';
            smartBtn.style.background = 'rgba(99, 102, 241, 0.1)';
        } else {
            smartBtn.style.borderColor = 'rgba(255,255,255,0.2)';
            smartBtn.style.color = 'var(--text-muted)';
            smartBtn.style.background = 'rgba(255,255,255,0.1)';
        }
        saveUIState();
        loadPapers();

    });

    document.getElementById('settingsBtn').addEventListener('click', openSettings);
    document.getElementById('morningBriefBtn').addEventListener('click', openBrief);

    const statsBtn = document.getElementById('toggleStatsBtn');
    statsBtn.addEventListener('click', () => {
        isStatsOpen = !isStatsOpen;
        const dash = document.getElementById('dashboard');
        if (isStatsOpen) {
            dash.classList.remove('hidden');
            statsBtn.style.color = 'var(--primary)';
            statsBtn.style.background = 'rgba(99, 102, 241, 0.1)';
            updateCharts();
        } else {
            dash.classList.add('hidden');
            statsBtn.style.color = 'var(--text-main)';
            statsBtn.style.background = 'transparent';
        }
        saveUIState();
    });
    if (isStatsOpen) {
        const dash = document.getElementById('dashboard');
        dash.classList.remove('hidden');
        statsBtn.style.color = 'var(--primary)';
        statsBtn.style.background = 'rgba(99, 102, 241, 0.1)';
        updateCharts();
    }

    filterChips.forEach(chip => {
        chip.addEventListener('click', () => {
            filterChips.forEach(c => c.classList.remove('active'));
            chip.classList.add('active');
            currentStatus = chip.dataset.status;
            saveUIState();
            updateFavoritesSortBar();
            loadPapers();
        });
    });

    document.querySelectorAll('.fav-sort-chip').forEach((chip) => {
        chip.addEventListener('click', () => {
            favoritesSort = chip.dataset.sort || 'ai';
            saveUIState();
            updateFavoritesSortBar();
            if (currentStatus === 'liked') {
                loadPapers();
            }
        });
    });

    const dateInput = document.getElementById('dateInput');
    dateInput.addEventListener('change', () => {
        if (dateInput.value) {
            fetchBtn.innerHTML = `<i class="fa-solid fa-calendar-day"></i> Fetch ${dateInput.value}`;
        } else {
            fetchBtn.innerHTML = `<i class="fa-solid fa-cloud-arrow-down"></i> Fetch New`;
        }
        currentDateFilter = dateInput.value || null;
        saveUIState();
        const dayRunDate = document.getElementById('dayRunDateInput');
        if (dayRunDate && !dayRunDate.value) {
            dayRunDate.value = dateInput.value || '';
        }
    });

    const searchInput = document.getElementById('searchInput');
    if (searchInput) {
        searchInput.addEventListener('input', (e) => {
            handleSearch(e.target.value);
        });
    }
    document.querySelectorAll('.search-chip').forEach(chip => {
        chip.addEventListener('click', () => setSearchMode(chip.dataset.mode));
    });
    // Init Audio
    audioObj = document.getElementById('globalAudio');
    audioObj.addEventListener('ended', () => {
        playNextTrack();
    });
    audioObj.addEventListener('timeupdate', updatePlayerTime);
    audioObj.addEventListener('play', () => updatePlayerState(true));
    audioObj.addEventListener('pause', () => updatePlayerState(false));

    initializeKeyboardShortcuts();
    initializeUnifiedInboxShortcuts();
    window.addEventListener('scroll', scheduleScrollUpdate, { passive: true });
    updateBackToTopVisibility();
});

const FEED_PAGE_SIZE = 80;
const FEED_RENDER_BATCH = 24;
const SEARCH_PAGE_SIZE = 60;
let feedOffset = 0;
let feedHasMore = false;
let feedLoadingMore = false;
let feedRequestToken = 0;
let feedObserver = null;
let searchOffset = 0;
let searchHasMore = false;
let searchLoadingMore = false;
let searchObserver = null;
let activeSearchQuery = '';
let activeSearchMode = 'local';
let scrollRafId = null;

function hasActiveSearchQuery() {
    const input = document.getElementById('searchInput');
    return Boolean(input && input.value && input.value.trim().length > 0);
}

function shouldUsePagedFeed() {
    if (hasActiveSearchQuery()) return false;
    if (currentStatus === 'liked') {
        return favoritesSort !== 'ai';
    }
    return ['new', 'dismissed', 'bookmarked', 'liked'].includes(currentStatus) && !isSmartSort;
}

function getFeedSentinel() {
    return document.getElementById('paperLoadSentinel');
}

function hideFeedSentinel() {
    const sentinel = getFeedSentinel();
    if (!sentinel) return;
    sentinel.classList.add('hidden');
    sentinel.textContent = '';
}

function updateFeedSentinel() {
    const sentinel = getFeedSentinel();
    if (!sentinel) return;

    if (!shouldUsePagedFeed()) {
        hideFeedSentinel();
        return;
    }
    if (allPapers.length === 0 && !feedLoadingMore) {
        hideFeedSentinel();
        return;
    }
    sentinel.classList.remove('hidden');
    if (feedLoadingMore) {
        sentinel.textContent = 'Loading more papers...';
    } else if (feedHasMore) {
        sentinel.textContent = 'Scroll to load more';
    } else {
        sentinel.textContent = 'All papers loaded';
    }
    updateBackToTopVisibility();
}

function updateSearchSentinel() {
    const sentinel = getFeedSentinel();
    if (!sentinel) return;
    if (!activeSearchQuery) {
        hideFeedSentinel();
        return;
    }
    sentinel.classList.remove('hidden');
    if (searchLoadingMore) {
        sentinel.textContent = 'Loading more results...';
    } else if (searchHasMore) {
        sentinel.textContent = 'Scroll to load more results';
    } else {
        sentinel.textContent = 'All results loaded';
    }
    updateBackToTopVisibility();
}

function disconnectFeedObserver() {
    if (!feedObserver) return;
    feedObserver.disconnect();
    feedObserver = null;
}

function disconnectSearchObserver() {
    if (!searchObserver) return;
    searchObserver.disconnect();
    searchObserver = null;
}

function setupFeedObserver() {
    const sentinel = getFeedSentinel();
    if (!sentinel || typeof IntersectionObserver === 'undefined' || !shouldUsePagedFeed()) return;
    disconnectFeedObserver();
    feedObserver = new IntersectionObserver((entries) => {
        entries.forEach((entry) => {
            if (entry.isIntersecting) {
                loadNextPaperPage();
            }
        });
    }, { root: null, rootMargin: '160px 0px' });
    feedObserver.observe(sentinel);
}

function setupSearchObserver() {
    const sentinel = getFeedSentinel();
    if (!sentinel || typeof IntersectionObserver === 'undefined' || !activeSearchQuery) return;
    disconnectSearchObserver();
    searchObserver = new IntersectionObserver((entries) => {
        entries.forEach((entry) => {
            if (entry.isIntersecting) {
                loadNextSearchPage(searchRequestToken, false);
            }
        });
    }, { root: null, rootMargin: '160px 0px' });
    searchObserver.observe(sentinel);
}

function updateBackToTopVisibility() {
    const btn = document.getElementById('backToTopBtn');
    if (!btn) return;
    const shouldShow = (window.scrollY > 500) && (shouldUsePagedFeed() || Boolean(activeSearchQuery));
    if (shouldShow) {
        btn.classList.remove('hidden');
    } else {
        btn.classList.add('hidden');
    }
}

function scheduleScrollUpdate() {
    if (scrollRafId) return;
    scrollRafId = requestAnimationFrame(() => {
        scrollRafId = null;
        updateBackToTopVisibility();
    });
}

window.scrollToTop = () => {
    window.scrollTo({ top: 0, behavior: 'smooth' });
};

async function loadNextPaperPage() {
    if (!shouldUsePagedFeed() || feedLoadingMore || !feedHasMore) return;
    const requestToken = feedRequestToken;
    feedLoadingMore = true;
    updateFeedSentinel();
    if (feedPageAbortController) {
        feedPageAbortController.abort();
    }
    feedPageAbortController = new AbortController();

    try {
        const allowSmartSort = isSmartSort && !(currentStatus === 'liked' && favoritesSort !== 'ai');
        const includeNovelty = (currentStatus === 'liked' && favoritesSort === 'novelty') || feedOffset === 0;
        let url = `${API_BASE}/papers?status=${currentStatus}&limit=${FEED_PAGE_SIZE}&offset=${feedOffset}&include_meta=true&include_novelty=${includeNovelty ? 'true' : 'false'}`;
        if (currentDateFilter) {
            url += `&date=${currentDateFilter}`;
        }
        if (allowSmartSort) {
            url += `&sort=smart`;
        } else if (currentStatus === 'liked') {
            if (favoritesSort === 'ai') {
                url += `&sort=smart`;
            } else if (favoritesSort) {
                url += `&sort=${encodeURIComponent(favoritesSort)}`;
            }
        }
        url += getRankProfileQuery();

        const { data: payload } = await fetchJsonWithCache(url, { signal: feedPageAbortController.signal });
        if (requestToken !== feedRequestToken) return;

        const pageItems = Array.isArray(payload.items) ? payload.items : [];
        const isFirstPage = feedOffset === 0;
        feedOffset += pageItems.length;
        feedHasMore = Boolean(payload.has_more);

        if (isFirstPage) {
            allPapers = pageItems;
            renderPaperGrid(allPapers);
        } else if (pageItems.length > 0) {
            allPapers = allPapers.concat(pageItems);
            renderPaperGrid(pageItems, { append: true });
        }
    } catch (err) {
        if (err && err.name === 'AbortError') {
            return;
        }
        console.error("Failed to load next page", err);
        if (requestToken === feedRequestToken) {
            alert("Failed to load more papers.");
        }
    } finally {
        if (requestToken === feedRequestToken) {
            feedLoadingMore = false;
            updateFeedSentinel();
        }
    }
}

function buildSearchUrl(query, mode, limit, offset) {
    const q = encodeURIComponent(query || '');
    const safeMode = (mode === 'semantic') ? 'semantic' : 'keyword';
    return `${API_BASE}/search?q=${q}&mode=${safeMode}&limit=${limit}&offset=${offset}&include_meta=true`;
}

async function loadNextSearchPage(token, initial) {
    if (!activeSearchQuery || searchLoadingMore || (!searchHasMore && !initial)) return;
    searchLoadingMore = true;
    updateSearchSentinel();
    if (searchAbortController) {
        searchAbortController.abort();
    }
    searchAbortController = new AbortController();
    try {
        let url;
        if (activeSearchMode === 'global') {
            url = `${API_BASE}/search/global?q=${encodeURIComponent(activeSearchQuery)}`;
        } else {
            url = buildSearchUrl(activeSearchQuery, activeSearchMode, SEARCH_PAGE_SIZE, searchOffset);
        }
        const { data: payload } = await fetchJsonWithCache(url, { signal: searchAbortController.signal });
        if (token !== searchRequestToken) return;

    if (activeSearchMode === 'global') {
        const items = Array.isArray(payload) ? payload : [];
        updateSearchCacheBadge(false);
        renderPaperGrid(items);
        searchHasMore = false;
        searchOffset = items.length;
        updateSearchSentinel();
        return;
    }

    const items = Array.isArray(payload.items) ? payload.items : [];
    if (initial) {
        updateSearchCacheBadge(Boolean(payload.cached));
    }
    if (initial) {
        renderPaperGrid(items);
    } else if (items.length > 0) {
        renderPaperGrid(items, { append: true });
        }

        searchOffset += items.length;
        searchHasMore = Boolean(payload.has_more);
        updateSearchSentinel();
    } catch (err) {
        if (err && err.name === 'AbortError') {
            return;
        }
        console.error("Search pagination failed", err);
    } finally {
        if (token === searchRequestToken) {
            searchLoadingMore = false;
            updateSearchSentinel();
        }
    }
}

// Navigation Logic
function setFilter(status) {
    currentStatus = status;
    currentView = (currentView === 'skim' || currentView === 'threads') ? currentView : 'grid';

    // Update Sidebar UI
    const navItems = document.querySelectorAll('.nav-item');
    navItems.forEach(item => {
        if (item.getAttribute('onclick') && item.getAttribute('onclick').includes(status)) {
            item.classList.add('active');
        } else {
            item.classList.remove('active');
        }
    });

    // Ensure we are in Grid View
    document.getElementById('graphView').classList.add('hidden');
    document.getElementById('paperGrid').classList.remove('hidden');
    document.getElementById('graphTabBtn').classList.remove('active');

    // Also update top filter chips if they exist (though we are moving to sidebar)
    const filterChips = document.querySelectorAll('.filter-chip');
    filterChips.forEach(c => {
        if (c.dataset.status === status) c.classList.add('active');
        else c.classList.remove('active');
    });

    updateFavoritesSortBar();
    saveUIState();
    applySkimViewState();
    applyThreadsViewState();
    loadPapers();
}

async function loadPapers() {
    currentView = currentView === 'skim' ? 'skim' : 'grid';
    saveUIState();
    feedRequestToken += 1;
    feedOffset = 0;
    feedHasMore = false;
    feedLoadingMore = false;
    disconnectFeedObserver();
    resetVirtualization();
    setLoading(true);
    paperGrid.innerHTML = '';
    if (feedAbortController) {
        feedAbortController.abort();
    }
    feedAbortController = new AbortController();

    // Adjust Grid Layout for Favorites
    if (currentStatus === 'liked') {
        paperGrid.classList.add('favorites-grid');
        // Force inline style as failsafe
        paperGrid.style.display = 'grid'; // Ensure display is grid
        paperGrid.style.setProperty('grid-template-columns', 'repeat(2, 1fr)', 'important');
        paperGrid.style.gap = '1.5rem';
        console.log("Layout: Favorites (2 columns forced)");
    } else {
        paperGrid.classList.remove('favorites-grid');
        paperGrid.style.removeProperty('grid-template-columns');
        paperGrid.style.removeProperty('border');
    }

    try {
        updateFavoritesSortBar();
        const searchInput = document.getElementById('searchInput');
        const hasSearch = searchInput && searchInput.value.trim().length > 0;
        const usePaged = shouldUsePagedFeed();
        if (currentStatus === 'liked' && !hasSearch && !usePaged) {
            const cached = getFavoritesCacheEntry();
            if (cached) {
                allPapers = cached.items;
                renderPaperGrid(allPapers);
                return;
            }
        }
        // Update header if filtering
        const dateDisplay = document.getElementById('batchDateDisplay');
        if (currentDateFilter) {
            dateDisplay.textContent = `Showing: ${currentDateFilter}`;
            // Add a "Clear" button? For now just showing is enough.
        } else if (allPapers.length > 0) {
            // Maybe show range?
        }
        if (usePaged) {
            feedHasMore = true;
            await loadNextPaperPage();
            if (feedHasMore) {
                setupFeedObserver();
            }
            updateFeedSentinel();
            return;
        }

        hideFeedSentinel();
        const allowSmartSort = isSmartSort && !(currentStatus === 'liked' && favoritesSort !== 'ai');
        let url = `${API_BASE}/papers?status=${currentStatus}&limit=100`;
        if (currentDateFilter) {
            url += `&date=${currentDateFilter}`;
        }
        if (allowSmartSort) {
            url += `&sort=smart`;
        } else if (currentStatus === 'liked') {
            if (favoritesSort === 'ai') {
                url += `&sort=smart`;
            } else {
                url += `&sort=${encodeURIComponent(favoritesSort)}`;
            }
        }
        url += getRankProfileQuery();

        const { data } = await fetchJsonWithCache(url, { signal: feedAbortController.signal });
        allPapers = data;
        if (currentStatus === 'liked') {
            setFavoritesCache(allPapers);
        }
        renderPaperGrid(allPapers);
    } catch (err) {
        if (err && err.name === 'AbortError') {
            return;
        }
        console.error("Failed to load papers", err);
        alert("Failed to load papers. check console/backend.");
    } finally {
        setLoading(false);
    }
}

async function fetchConfig() {
    try {
        const data = await apiFetchJson(`${API_BASE}/config`);
        userKeywords = data.keywords || [];
    } catch (err) {
        console.error("Failed to fetch config", err);
    }
}



async function fetchFollowedAuthors() {
    try {
        const list = await apiFetchJson(`${API_BASE}/authors/following`);
        followedAuthors = new Set(list);
    } catch (err) {
        console.error("Failed to fetch followed authors", err);
    }
}

async function fetchNewPapers() {
    fetchBtn.disabled = true;
    fetchBtn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Fetching...';

    const dateInput = document.getElementById('dateInput');
    const dateVal = dateInput ? dateInput.value : null;

    try {
        const payload = { max_results: 20 };
        if (dateVal) payload.date = dateVal;

        const data = await apiFetchJson(`${API_BASE}/fetch`, { method: 'POST', body: payload, useCache: false });
        alert(`Fetched ${data.fetched} papers from ${data.date}. ${data.new} are new.`);

        // Update date display if exists, or title
        const dateDisplay = document.getElementById('batchDateDisplay');
        if (dateDisplay) dateDisplay.textContent = `Latest Batch: ${data.date}`;

        // Reload if we are on 'new' tab
        // Update filter to match fetched date
        currentDateFilter = data.date;
        saveUIState();

        // Reload if we are on 'new' tab
        if (currentStatus === 'new') loadPapers();
        refreshAllBadges();
    } catch (err) {
        console.error("Fetch Error:", err);
        alert("Error fetching papers: " + (err.message || str(err)) + "\nCheck logs.");
    } finally {
        fetchBtn.disabled = false;
        fetchBtn.innerHTML = '<i class="fa-solid fa-cloud-arrow-down"></i> Fetch New';
    }
}





let searchDebounceCtx;
let searchRequestToken = 0;
const RECENT_SEARCH_KEY = 'arxivc.recentSearches.v1';
const RECENT_SEARCH_LIMIT = 8;
function setSearchMode(mode, { reset = true, persist = true } = {}) {
    const normalized = (mode || 'local').toLowerCase();
    searchMode = ['local', 'semantic', 'global'].includes(normalized) ? normalized : 'local';
    document.querySelectorAll('.search-chip').forEach(chip => {
        const isActive = chip.dataset.mode === searchMode;
        chip.classList.toggle('active', isActive);
    });
    updateSearchPlaceholder();
    if (reset) resetSearch();
    if (persist) saveUIState();
}

function updateSearchPlaceholder() {
    const input = document.getElementById('searchInput');
    if (searchMode === 'global') {
        input.placeholder = "Search ArXiv World (Title/Author)...";
    } else if (searchMode === 'semantic') {
        input.placeholder = "Search by Concept (Vector)...";
    } else {
        input.placeholder = "Filter library...";
    }
}

function updateSearchScopeBadge(mode, active = true) {
    const badge = document.getElementById('searchScopeBadge');
    if (!badge) return;
    if (!active || !mode) {
        badge.classList.add('hidden');
        badge.textContent = '';
        badge.removeAttribute('data-mode');
        return;
    }
    let label = 'Local';
    if (mode === 'semantic') label = 'Semantic';
    if (mode === 'global') label = 'Global';
    badge.textContent = label;
    badge.setAttribute('data-mode', mode);
    badge.classList.remove('hidden');
}

function loadRecentSearches() {
    try {
        const raw = localStorage.getItem(RECENT_SEARCH_KEY);
        if (!raw) return [];
        const data = JSON.parse(raw);
        return Array.isArray(data) ? data : [];
    } catch (_) {
        return [];
    }
}

function saveRecentSearches(items) {
    try {
        localStorage.setItem(RECENT_SEARCH_KEY, JSON.stringify(items));
    } catch (_) { }
}

function recordRecentSearch(query, mode) {
    const q = String(query || '').trim();
    if (q.length < 2) return;
    const list = loadRecentSearches();
    const key = `${mode || 'local'}::${q.toLowerCase()}`;
    const filtered = list.filter((item) => `${item.mode || 'local'}::${String(item.query || '').toLowerCase()}` !== key);
    filtered.unshift({ query: q, mode: mode || 'local', ts: Date.now() });
    const next = filtered.slice(0, RECENT_SEARCH_LIMIT);
    saveRecentSearches(next);
    updateRecentSearchDatalist(next);
}

function updateRecentSearchDatalist(items = null) {
    const listEl = document.getElementById('recentSearchesList');
    if (!listEl) return;
    const data = items || loadRecentSearches();
    listEl.innerHTML = '';
    data.forEach((item) => {
        const opt = document.createElement('option');
        opt.value = item.query;
        listEl.appendChild(opt);
    });
}

function resetSearch() {
    const query = document.getElementById('searchInput').value;
    handleSearch(query);
}

function updateSearchCacheBadge(cached) {
    const badge = document.getElementById('searchCacheBadge');
    if (!badge) return;
    if (cached) {
        badge.classList.remove('hidden');
    } else {
        badge.classList.add('hidden');
    }
}

function flashBundleCacheBadge(cached) {
    const badge = document.getElementById('bundleCacheBadge');
    if (!badge) return;
    if (!cached) {
        badge.classList.add('hidden');
        return;
    }
    badge.classList.remove('hidden');
    setTimeout(() => badge.classList.add('hidden'), 3500);
}

function resetSearchPagingState() {
    searchOffset = 0;
    searchHasMore = false;
    searchLoadingMore = false;
    activeSearchQuery = '';
    activeSearchMode = 'local';
    disconnectSearchObserver();
    updateSearchCacheBadge(false);
    updateBackToTopVisibility();
}

async function handleSearch(query) {
    const input = document.getElementById('searchInput');
    const q = (query || input.value).trim();

    if (!q) {
        clearTimeout(searchDebounceCtx);
        if (searchAbortController) {
            searchAbortController.abort();
            searchAbortController = null;
        }
        resetSearchPagingState();
        renderPaperGrid(allPapers);
        updateSearchScopeBadge(null, false);
        if (shouldUsePagedFeed()) {
            setupFeedObserver();
            updateFeedSentinel();
        } else {
            hideFeedSentinel();
        }
        return;
    }

    disconnectFeedObserver();
    disconnectSearchObserver();
    hideFeedSentinel();

    clearTimeout(searchDebounceCtx);
    if (searchAbortController) {
        searchAbortController.abort();
        searchAbortController = null;
    }
    const delay = (searchMode === 'local') ? 200 : 600;
    searchDebounceCtx = setTimeout(async () => {
        const token = ++searchRequestToken;
        try {
            updateSearchScopeBadge(searchMode, true);
            setLoading(true);
            activeSearchQuery = q;
            activeSearchMode = searchMode;
            searchOffset = 0;
            searchHasMore = false;
            searchLoadingMore = false;

            await loadNextSearchPage(token, true);
            if (token !== searchRequestToken) return;
            recordRecentSearch(q, searchMode);
            if (searchHasMore) {
                setupSearchObserver();
            }

        } catch (err) {
            console.error(err);
        } finally {
            if (token === searchRequestToken) {
                setLoading(false);
            }
        }
    }, delay);
}




// Graph View Logic
let network = null;

async function openGraphView() {
    currentView = 'graph';
    saveUIState();
    applySkimViewState();
    applyThreadsViewState();
    disconnectFeedObserver();
    hideFeedSentinel();
    resetVirtualization();

    // UI Switch
    document.getElementById('paperGrid').classList.add('hidden');
    document.getElementById('graphView').classList.remove('hidden');

    // reset sidebar active states
    document.querySelectorAll('.filter-chip, .nav-item').forEach(c => c.classList.remove('active'));
    document.getElementById('graphTabBtn').classList.add('active');

    paperGrid.innerHTML = ''; // Clear grid output to save memory? Or keep it hidden.

    const container = document.getElementById('authorGraph');
    container.innerHTML = '<div style="text-align:center; padding-top:20%; color:var(--text-muted);">Parsing connections...</div>';

    try {
        await ensureVisLib();
    } catch (e) {
        container.innerHTML = 'Library missing.';
        alert(`Error loading graph library: ${e.message}`);
        return;
    }

    try {
        const res = await fetch(`${API_BASE}/graph`);
        if (!res.ok) throw new Error("Graph API failed: " + res.status);

        const data = await res.json();

        if (data.nodes.length === 0) {
            container.innerHTML = '<div style="text-align:center; padding-top:20%;">No connections found yet. Try fetching more papers!</div>';
            return;
        }

        const options = {
            nodes: {
                shape: 'dot',
                size: 16,
                font: {
                    color: '#ffffff',
                    size: 14
                },
                borderWidth: 2,
                color: {
                    background: '#6366f1',
                    border: '#ffffff',
                    highlight: { background: '#818cf8', border: '#ffffff' }
                }
            },
            edges: {
                width: 1,
                color: { color: 'rgba(255,255,255,0.2)', highlight: '#ffffff' },
                smooth: { type: 'continuous' }
            },
            physics: {
                stabilization: {
                    enabled: true,
                    iterations: 1000,
                    updateInterval: 50,
                    fit: true
                },
                solver: 'barnesHut',
                barnesHut: {
                    gravitationalConstant: -3000,
                    centralGravity: 0.3,
                    springLength: 95,
                    springConstant: 0.04,
                    damping: 0.09,
                    avoidOverlap: 0.2
                },
                maxVelocity: 50,
                minVelocity: 0.1,
                timestep: 0.5,
                adaptiveTimestep: true
            },
            interaction: {
                hover: true,
                tooltipDelay: 200
            }
        };

        container.innerHTML = ''; // Clear loader

        try {
            network = new vis.Network(container, data, options);
            console.log("Graph initialized successfully");
        } catch (visError) {
            console.error("Vis Creation Failed:", visError);
        }

        network.on("click", function (params) {
            if (params.nodes.length) {
                const author = params.nodes[0];
                console.log("Clicked author:", author);
                // Future: Filter papers by this author?
            }
        });

    } catch (e) {
        console.error(e);
        container.innerHTML = '<div style="text-align:center; color:var(--danger); padding-top:20%;">Failed to load graph.</div>';
    }
}

function renderCardsChunked(papers, target = paperGrid) {
    let idx = 0;
    let focused = false;
    const pump = () => {
        const frag = document.createDocumentFragment();
        const stop = Math.min(idx + FEED_RENDER_BATCH, papers.length);
        for (; idx < stop; idx += 1) {
            frag.appendChild(createPaperCard(papers[idx]));
        }
        target.appendChild(frag);
        if (!focused && target === paperGrid) {
            focused = true;
            ensureFocusedPaper();
        }
        if (idx < papers.length) {
            requestAnimationFrame(pump);
        }
    };
    requestAnimationFrame(pump);
}

function getVirtualColumns() {
    const gridWidth = Math.max(320, paperGrid.clientWidth || window.innerWidth || 1200);
    return Math.max(1, Math.floor((gridWidth + VIRTUAL_GRID_GAP) / (VIRTUAL_CARD_MIN_WIDTH + VIRTUAL_GRID_GAP)));
}

function shouldVirtualizeGrid(papers) {
    if (!Array.isArray(papers)) return false;
    if (currentStatus === 'liked' && favoritesSort === 'ai') return false;
    return papers.length >= VIRTUAL_MIN_ITEMS;
}

function resetVirtualization() {
    if (virtualState.scrollHandler) {
        window.removeEventListener('scroll', virtualState.scrollHandler);
        virtualState.scrollHandler = null;
    }
    if (virtualState.resizeHandler) {
        window.removeEventListener('resize', virtualState.resizeHandler);
        virtualState.resizeHandler = null;
    }
    if (virtualScrollRaf) {
        cancelAnimationFrame(virtualScrollRaf);
        virtualScrollRaf = null;
    }
    if (virtualResizeRaf) {
        cancelAnimationFrame(virtualResizeRaf);
        virtualResizeRaf = null;
    }
    virtualState.enabled = false;
    virtualState.papers = [];
    virtualState.columns = 1;
    virtualState.rowHeight = VIRTUAL_DEFAULT_ROW_HEIGHT;
    virtualState.lastStart = -1;
    virtualState.lastEnd = -1;
}

function renderVirtualWindow(force = false) {
    if (!virtualState.enabled) return;

    const papers = virtualState.papers || [];
    if (papers.length === 0) {
        paperGrid.innerHTML = `
            <div style="grid-column: 1/-1; text-align: center; margin-top: 2rem; color: #94a3b8;">
                No matches found.
            </div>`;
        return;
    }

    virtualState.columns = getVirtualColumns();
    const rowHeight = Math.max(220, Number(virtualState.rowHeight) || VIRTUAL_DEFAULT_ROW_HEIGHT);
    const totalRows = Math.max(1, Math.ceil(papers.length / virtualState.columns));
    const gridTop = paperGrid.getBoundingClientRect().top + window.scrollY;
    const viewportTop = Math.max(0, window.scrollY - gridTop);
    const viewportBottom = viewportTop + window.innerHeight;

    let startRow = Math.floor(viewportTop / rowHeight) - VIRTUAL_OVERSCAN_ROWS;
    let endRow = Math.ceil(viewportBottom / rowHeight) + VIRTUAL_OVERSCAN_ROWS;
    startRow = Math.max(0, startRow);
    endRow = Math.min(totalRows, Math.max(startRow + 1, endRow));

    const startIdx = Math.max(0, startRow * virtualState.columns);
    const endIdx = Math.min(papers.length, endRow * virtualState.columns);
    if (!force && startIdx === virtualState.lastStart && endIdx === virtualState.lastEnd) {
        return;
    }
    virtualState.lastStart = startIdx;
    virtualState.lastEnd = endIdx;

    const topSpacerHeight = Math.max(0, startRow * rowHeight);
    const bottomSpacerHeight = Math.max(0, (totalRows - endRow) * rowHeight);

    const topSpacer = document.createElement('div');
    topSpacer.style.gridColumn = '1 / -1';
    topSpacer.style.height = `${Math.round(topSpacerHeight)}px`;

    const bottomSpacer = document.createElement('div');
    bottomSpacer.style.gridColumn = '1 / -1';
    bottomSpacer.style.height = `${Math.round(bottomSpacerHeight)}px`;

    const visibleSlice = papers.slice(startIdx, endIdx);
    paperGrid.innerHTML = '';
    paperGrid.appendChild(topSpacer);
    const visibleFrag = document.createDocumentFragment();
    visibleSlice.forEach((paper) => visibleFrag.appendChild(createPaperCard(paper)));
    paperGrid.appendChild(visibleFrag);
    paperGrid.appendChild(bottomSpacer);
    ensureFocusedPaper();

    requestAnimationFrame(() => {
        const firstCard = paperGrid.querySelector('.paper-card');
        if (!firstCard) return;
        const measured = Math.round(firstCard.getBoundingClientRect().height + VIRTUAL_GRID_GAP);
        if (Number.isFinite(measured) && measured > 200) {
            virtualState.rowHeight = Math.round((virtualState.rowHeight * 0.7) + (measured * 0.3));
        }
    });
}

function enableVirtualization(papers) {
    virtualState.enabled = true;
    virtualState.papers = papers;
    virtualState.columns = getVirtualColumns();
    virtualState.lastStart = -1;
    virtualState.lastEnd = -1;

    if (!virtualState.scrollHandler) {
        virtualState.scrollHandler = () => {
            if (virtualScrollRaf) return;
            virtualScrollRaf = requestAnimationFrame(() => {
                virtualScrollRaf = null;
                renderVirtualWindow(false);
            });
        };
        window.addEventListener('scroll', virtualState.scrollHandler, { passive: true });
    }

    if (!virtualState.resizeHandler) {
        virtualState.resizeHandler = () => {
            if (virtualResizeRaf) return;
            virtualResizeRaf = requestAnimationFrame(() => {
                virtualResizeRaf = null;
                renderVirtualWindow(true);
            });
        };
        window.addEventListener('resize', virtualState.resizeHandler);
    }

    renderVirtualWindow(true);
}

function renderThreadsView(papers) {
    paperGrid.innerHTML = '';
    if (!Array.isArray(papers) || papers.length === 0) {
        paperGrid.innerHTML = `
            <div style="grid-column: 1/-1; text-align: center; margin-top: 2rem; color: #94a3b8;">
                No matches found.
            </div>`;
        return;
    }

    const groups = new Map();
    papers.forEach((p) => {
        const concepts = Array.isArray(p.concepts) ? p.concepts : [];
        const categories = Array.isArray(p.categories) ? p.categories : [];
        const key = concepts[0] || categories[0] || 'Other';
        if (!groups.has(key)) groups.set(key, []);
        groups.get(key).push(p);
    });

    const groupEntries = Array.from(groups.entries());
    const getLatest = (items) => {
        return items.reduce((acc, p) => (p.published > acc ? p.published : acc), '');
    };
    groupEntries.sort((a, b) => {
        const aLatest = getLatest(a[1]);
        const bLatest = getLatest(b[1]);
        if (aLatest === bLatest) return b[1].length - a[1].length;
        return aLatest > bLatest ? -1 : 1;
    });

    groupEntries.forEach(([key, items]) => {
        items.sort((a, b) => (a.published > b.published ? 1 : -1));
        const section = document.createElement('div');
        section.className = 'thread-section';
        section.innerHTML = `
            <div class="thread-header">
                <span class="thread-title">${escapeHtml(key)}</span>
                <span class="thread-count">${items.length}</span>
            </div>
        `;
        const list = document.createElement('div');
        list.className = 'thread-list';
        items.forEach((p) => {
            const item = document.createElement('div');
            item.className = 'thread-item';
            const date = (p.published || '').slice(0, 10);
            const readTime = p.reading_time_minutes ? ` • ~${p.reading_time_minutes} min` : '';
            const authors = Array.isArray(p.authors) ? p.authors : (p.authors ? [p.authors] : []);
            item.innerHTML = `
                <div class="thread-date">${escapeHtml(date)}</div>
                <div class="thread-body">
                    <div class="thread-title-line">${escapeHtml(p.title || 'Untitled')}</div>
                    <div class="thread-meta">${escapeHtml(authors.slice(0, 3).join(', '))}${readTime}</div>
                </div>
                <div class="thread-actions">
                    <button class="action-btn" title="Open PDF" onclick="event.stopPropagation(); window.open('${API_BASE}/papers/${encodeURIComponent(p.id)}/pdf', '_blank')">
                        <i class="fa-regular fa-file-pdf"></i>
                    </button>
                    <button class="action-btn" title="Reading status" onclick="event.stopPropagation(); openReadingModal('${p.id}')">
                        <i class="fa-solid fa-book-open-reader"></i>
                    </button>
                </div>
            `;
            item.addEventListener('click', () => {
                focusedPaperId = p.id;
                openReadingModal(p.id);
            });
            list.appendChild(item);
        });
        section.appendChild(list);
        paperGrid.appendChild(section);
    });
}

function renderPaperGrid(papers, options = {}) {
    const append = Boolean(options.append);
    const sourcePapers = append ? currentVisiblePapers : papers;
    document.getElementById('graphView').classList.add('hidden');
    document.getElementById('paperGrid').classList.remove('hidden');
    document.getElementById('graphTabBtn').classList.remove('active');

    if (!append) {
        paperGrid.innerHTML = '';
    }

    if (currentView === 'threads') {
        resetVirtualization();
        renderThreadsView(sourcePapers);
        return;
    }

    // Auto-Cluster if we are in "liked" mode and have enough papers (AI sort only)
    if (!append && currentStatus === 'liked' && sourcePapers.length > 3 && favoritesSort === 'ai') {
        resetVirtualization();
        renderSmartStacks(sourcePapers);
        return;
    }

    if (sourcePapers.length === 0) {
        resetVirtualization();
        if (append) return;
        paperGrid.innerHTML = `
            <div style="grid-column: 1/-1; text-align: center; margin-top: 2rem; color: #94a3b8;">
                No matches found.
            </div>`;
        return;
    }

    if (shouldVirtualizeGrid(sourcePapers)) {
        enableVirtualization(sourcePapers);
        return;
    }

    resetVirtualization();
    if (append) {
        renderCardsChunked(papers);
    } else {
        renderCardsChunked(sourcePapers);
    }
    if (!append) {
        requestAnimationFrame(() => ensureFocusedPaper());
    }
}

function createPaperCard(paper) {
    const card = document.createElement('div');
    card.className = 'paper-card';
    card.dataset.paperId = paper.id;
    if (focusedPaperId && paper.id === focusedPaperId) {
        card.classList.add('focused');
    }
    const readingStatus = String(paper.reading_status || '').toLowerCase();
    const readingProgress = Number(paper.reading_progress || 0);
    const showReading = Boolean(readingStatus) || readingProgress > 0;
    const readingLabel = readingStatus ? readingStatus.charAt(0).toUpperCase() + readingStatus.slice(1) : 'Queue';
    const hasNotes = Boolean(paper.has_notes) || Boolean(paper.notes && String(paper.notes).trim().length > 0);
    const isLikedPaper = String(paper.status || '').toLowerCase() === 'liked';
    const versionChangedFields = Array.isArray(paper.version_changed_fields)
        ? paper.version_changed_fields.filter((name) => name)
        : [];
    const labels = Array.isArray(paper.labels) ? paper.labels : [];
    card.innerHTML = `
        ${paper.score > 0 ? `<div class="score-badge">Matches: ${paper.score}</div>` : ''}
        ${paper.citation_count > 0 ? `
            <div class="citation-badge" title="Citations on Semantic Scholar" style="position:absolute; top:10px; right:10px; background:var(--bg-dark); border:1px solid rgba(255,255,255,0.2); padding:2px 8px; border-radius:12px; font-size:0.8rem; display:flex; align-items:center; gap:4px;">
                ${paper.citation_count > 10 ? '🔥' : '<i class="fa-solid fa-quote-left"></i>'}
                <span>${paper.citation_count}</span>
            </div>
        ` : ''
        }
        ${paper.novelty_score !== undefined && paper.novelty_score !== null ? `
            <div title="Novelty score vs your reference library" style="position:absolute; top:40px; right:10px; background:rgba(16,185,129,0.15); border:1px solid rgba(16,185,129,0.35); color:#34d399; padding:2px 8px; border-radius:12px; font-size:0.78rem;">
                Novelty ${Math.round(Number(paper.novelty_score) * 100)}%
            </div>
        ` : ''}
        <h3 class="paper-title">${highlightText(paper.title)}</h3>
        <div class="paper-meta">
            <div class="tags" style="margin-bottom: 0.5rem;">
                ${labels.map(label => `<span class="tag label-tag">${escapeHtml(label)}</span>`).join('')}
                ${(paper.categories || []).map(cat => `<span class="tag">${cat}</span>`).join('')}
                ${paper.reading_time_minutes ? `<span class="tag readtime-tag" title="Estimated reading time">${`~${paper.reading_time_minutes} min`}</span>` : ''}
                ${Number(paper.assignment_open_count || 0) > 0 ? `<span class="tag" style="background:rgba(251,191,36,0.14); color:#fcd34d;">tasks ${Number(paper.assignment_open_count || 0)}</span>` : ''}
                ${Number(paper.assignment_unread_count || 0) > 0 ? `<span class="tag" style="background:rgba(248,113,113,0.18); color:#fca5a5;">unread ${Number(paper.assignment_unread_count || 0)}</span>` : ''}
                ${(paper.concepts || []).map(c => `<span class="tag" style="background:rgba(16, 185, 129, 0.2); color:#34d399; border:1px solid rgba(16, 185, 129, 0.3); cursor:pointer;" onclick="filterByConcept('${c}')">${c}</span>`).join('')}
            </div>
            <span>
                ${paper.authors.map(name => {
            const isFollowed = followedAuthors.has(name);
            return `<span class="author-link" onclick="toggleFollow('${name.replace(/'/g, "\\'")}')">${name}${isFollowed ? ' <i class="fa-solid fa-star author-star"></i>' : ''}</span>`;
        }).join(', ')}
            </span>
            <span style="margin: 0 0.5rem">•</span>
            <span>${paper.published.slice(0, 10)}</span>
        </div>
        <div class="paper-summary">${highlightText(paper.summary)}</div>
        ${paper.rank_explain ? `<div class="rank-explain">${escapeHtml(String(paper.rank_explain))}</div>` : ''}
        ${paper.pinned ? `<div class="pin-note">📌 ${escapeHtml(paper.pin_note || 'Pinned')}${paper.pin_expires_at ? ` · until ${escapeHtml(String(paper.pin_expires_at).slice(0, 10))}` : ''}</div>` : ''}
        ${paper.version_note ? `<div class="update-note">${escapeHtml(paper.version_note)}</div>` : ''}
        ${versionChangedFields.length ? `
            <div class="version-change-badges">
                ${versionChangedFields.map((f) => `<span class="tag version-change-tag">${escapeHtml(String(f))}</span>`).join('')}
            </div>
        ` : ''}
        ${paper.search_snippet ? `<div class="search-snippet">...${paper.search_snippet}...</div>` : ''}
        ${showReading ? `
            <div class="reading-status" data-status="${readingStatus || 'queue'}">
                <span class="tag reading-tag">${readingLabel}</span>
                <div class="reading-progress">
                    <div class="reading-progress-bar" style="width:${Math.max(0, Math.min(readingProgress, 100))}%;"></div>
                </div>
            </div>
        ` : ''}
        ${(paper.match_reasons && paper.match_reasons.length)
            ? `<details class="match-details"><summary>Why this matched</summary><ul>${paper.match_reasons.map(r => `<li>${escapeHtml(r)}</li>`).join('')}</ul></details>`
            : ''}
    <div class="card-actions">
        ${isSelectionMode ? `
            <div class="selection-checkbox-wrapper" data-selection-paper-id="${paper.id}" onclick="toggleSelection('${paper.id}', event)" style="flex-grow:1; display:flex; align-items:center; cursor:pointer;">
                <div class="custom-checkbox ${selectedPaperIds.has(paper.id) ? 'checked' : ''}" style="width:20px; height:20px; border:2px solid var(--text-muted); border-radius:4px; margin-right:8px; display:flex; align-items:center; justify-content:center; background:${selectedPaperIds.has(paper.id) ? 'var(--primary)' : 'transparent'}; border-color:${selectedPaperIds.has(paper.id) ? 'var(--primary)' : 'var(--text-muted)'}">
                    ${selectedPaperIds.has(paper.id) ? '<i class="fa-solid fa-check" style="font-size:12px;"></i>' : ''}
                </div>
                <span data-selection-label class="${selectedPaperIds.has(paper.id) ? 'text-primary' : 'text-muted'}">Select for Review</span>
            </div>
        ` : `
        <a href="${paper.pdf_url}" target="_blank" class="pdf-link">
            <i class="fa-regular fa-file-pdf"></i> PDF
        </a>
        ${(() => {
            const codeLink = extractCodeLink(paper.summary);
            return codeLink ? `
                    <a href="${codeLink}" target="_blank" class="code-link" title="View Code">
                        <i class="fa-brands fa-github"></i> Code
                    </a>
                ` : '';
        })()}
        <button class="action-btn bookmark ${paper.bookmarked ? 'active' : ''}" onclick="toggleBookmark('${paper.id}', this)" title="Read Later">
            <i class="${paper.bookmarked ? 'fa-solid' : 'fa-regular'} fa-bookmark"></i>
        </button>
        <button class="action-btn pin ${paper.pinned ? 'active' : ''}" onclick="togglePin('${paper.id}')" title="Pin highlight">
            <i class="fa-solid fa-thumbtack"></i>
        </button>
        <div class="card-action-icons">
            <button class="action-btn reading" onclick="openReadingModal('${paper.id}')" title="Reading status">
                <i class="fa-solid fa-book-open-reader"></i>
            </button>
            <button class="action-btn notes ${hasNotes ? 'active' : ''}" onclick="openNotesModal('${paper.id}')" title="Notes">
                <i class="fa-solid fa-note-sticky"></i>
            </button>
            <button class="action-btn similar" onclick="findSimilar('${paper.id}', this)" title="Find content like this">
                <i class="fa-solid fa-microscope"></i>
            </button>
            <button class="action-btn" onclick="openFigures('${paper.id}')" title="View Figures">
                <i class="fa-regular fa-image"></i>
            </button>
            <button class="action-btn" onclick="openStructure('${paper.id}')" title="Structured summary">
                <i class="fa-solid fa-list-check"></i>
            </button>
            <button class="action-btn" onclick="openLatestVersionDiff('${paper.id}')" title="Latest version diff">
                <i class="fa-solid fa-code-branch"></i>
            </button>
            <button class="action-btn discuss" onclick="checkDiscussion('${paper.id}', this)" title="Check Hacker News">
                <i class="fa-brands fa-hacker-news"></i>
            </button>
            <button class="action-btn cite" onclick="copyBibtex('${paper.id}', this)" title="Copy BibTeX">
                <i class="fa-solid fa-quote-right"></i>
            </button>
            <button class="action-btn" onclick="openReproScorecard('${paper.id}')" title="Reproducibility scorecard">
                <i class="fa-solid fa-vial-circle-check"></i>
            </button>
            <button class="action-btn dive" onclick="openRabbitHole('${paper.id}')" title="Dive into Rabbit Hole">
                <i class="fa-solid fa-bullseye"></i>
            </button>
            <button class="action-btn chat" onclick="openChat('${paper.id}')" title="Chat with AI">
                <i class="fa-solid fa-robot"></i>
            </button>
            <button class="action-btn queue" onclick="addToQueue('${paper.id}', this)" title="Add to Queue (Monologue)">
                <i class="fa-solid fa-headphones-simple"></i>
            </button>
            <button class="action-btn duo" onclick="playDuo('${paper.id}', this)" title="Play Duo Podcast (Conversation)" style="color: #f472b6;">
                 <i class="fa-solid fa-user-group"></i>
            </button>
            <button class="action-btn tag-btn" onclick="autoTagPaper('${paper.id}', this)" title="Auto-Tag Concepts">
                <i class="fa-solid fa-tags"></i>
            </button>
            <button class="action-btn export" onclick="exportPaper('${paper.id}', this)" title="Export to Obsidian">
                <i class="fa-solid fa-file-export"></i>
            </button>
            ${!isLikedPaper ? `
                    <button class="action-btn like" onclick="handleRate('${paper.id}', 'liked', this)">
                        <i class="fa-regular fa-heart"></i>
                    </button>
                ` : '<span style="color:var(--success); font-size:1.2rem;"><i class="fa-solid fa-heart"></i></span>'}

            ${currentStatus !== 'dismissed' ? `
                    <button class="action-btn dismiss" onclick="handleRate('${paper.id}', 'dismissed', this)">
                        <i class="fa-solid fa-xmark"></i>
                    </button>
                ` : '<span style="color:var(--danger); font-size:1.2rem;"><i class="fa-solid fa-trash"></i></span>'}
        </div>
        `}
    </div>
    `;
    card.addEventListener('click', () => setFocusedPaper(paper.id, card));
    return card;
}

window.handleRate = async (id, status, btnElement) => {
    try {
        const res = await fetch(`${API_BASE}/papers/${encodeURIComponent(id)}/rate`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ status })
        });

        if (!res.ok) throw new Error("API Error");

        const keepCardInCurrentFeed = (
            status === 'liked' && (currentStatus === 'new' || currentStatus === 'bookmarked')
        );
        const card = btnElement.closest('.paper-card');
        if (keepCardInCurrentFeed) {
            allPapers = allPapers.map((p) => (p.id === id ? { ...p, status: 'liked' } : p));
            currentVisiblePapers = currentVisiblePapers.map((p) => (p.id === id ? { ...p, status: 'liked' } : p));
            invalidateFavoritesCache();
            renderPaperGrid(currentVisiblePapers);
            refreshAllBadges({ force: true });
            return;
        }

        allPapers = allPapers.filter((p) => p.id !== id);
        currentVisiblePapers = currentVisiblePapers.filter((p) => p.id !== id);
        invalidateFavoritesCache();

        if (virtualState.enabled) {
            renderPaperGrid(currentVisiblePapers);
            refreshAllBadges({ force: true });
            return;
        }

        // Animate out when the target feed should no longer contain this item.
        card.style.transform = 'scale(0.95)';
        card.style.opacity = '0';
        setTimeout(() => {
            card.remove();
            // If grid is empty, show message
            if (paperGrid.querySelectorAll('.paper-card').length === 0) {
                paperGrid.innerHTML = '<div style="grid-column: 1/-1; text-align: center; margin-top: 2rem; color: #94a3b8;">All caught up!</div>';
            }
        }, 300);
        refreshAllBadges({ force: true });

    } catch (err) {
        console.error("Rate Error:", err);
        alert("Failed to rate paper: " + (err.message || str(err)));
    }
};





window.toggleFollow = async (name) => {
    const isFollowing = followedAuthors.has(name);
    const endpoint = isFollowing ? 'unfollow' : 'follow';

    // Optimistic update
    if (isFollowing) followedAuthors.delete(name);
    else followedAuthors.add(name);

    // Re-render current view to show stars
    // We don't want to lose scroll position or do weird things, so ideally just update DOM.
    // For simplicity, re-render visible grid.
    const scrollPos = window.scrollY;

    // Re-rendering everything is easiest to ensure consistency
    // But maybe we only need to update the DOM elements?
    document.querySelectorAll('.author-link').forEach(el => {
        // This is a bit tricky because textContent has the star.
        // But the click handler passes the raw name.
        if (el.textContent.includes(name)) { // loose match
            if (isFollowing) {
                // Removing star
                el.innerHTML = name;
            } else {
                // Adding star
                el.innerHTML = `${name} <i class="fa-solid fa-star author-star"></i>`;
            }
        }
    });

    // Actually render properly to be safe
    // renderPaperGrid(currentVisiblePapers?) -- hard to track.
    // Let's just update the set and let user see it on next refresh?
    // No, user expects feedback.
    // Simple approach: re-run loadPapers() or reuse rendered logic?
    // Let's rely on the DOM update above for immediate feedback, 
    // AND persist to backend.

    // Re-render grid to ensuring consistent state
    // renderPaperGrid if we have filtered list? 
    // For now, reload whole thing or just proceed with optimistic DOM patch?
    // Optimistic DOM patch on ALL instances of that author name is best.

    // Iterate all paper cards
    // This is expensive but safer than simple text matching
    const links = document.querySelectorAll('.author-link');
    links.forEach(link => {
        // Strip existing star to compare name
        const currentName = link.innerText.trim();
        if (currentName === name) {
            if (isFollowing) {
                link.innerHTML = name;
            } else {
                link.innerHTML = `${name} <i class="fa-solid fa-star author-star"></i>`;
            }
        }
    });

    try {
        await fetch(`${API_BASE}/authors/${endpoint}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name })
        });
    } catch (err) {
        console.error(err);
        // Revert check would go here
    }
};

window.findSimilar = (id, btn) => {
    disconnectFeedObserver();
    hideFeedSentinel();

    const target = allPapers.find(p => p.id === id);
    if (!target) return;

    // Tokenize target
    const targetText = ((target.title || "") + " " + (target.summary || "")).toLowerCase();
    const targetTokens = new Set(tokenize(targetText));

    // Score others
    const scored = allPapers.filter(p => p.id !== id).map(p => {
        const text = ((p.title || "") + " " + (p.summary || "")).toLowerCase();
        const tokens = tokenize(text);
        let overlap = 0;
        tokens.forEach(t => {
            if (targetTokens.has(t)) overlap++;
        });
        return { paper: p, score: overlap };
    });

    // Sort by overlap desc
    scored.sort((a, b) => b.score - a.score);

    // Take top 50 matches (filter out 0 score)
    const matches = scored.filter(s => s.score > 0).slice(0, 50).map(s => s.paper);

    // Render
    renderPaperGrid(matches);

    // Update Header
    const dateDisplay = document.getElementById('batchDateDisplay');
    dateDisplay.innerHTML = `
        <span style="color:var(--primary)">Similar to:</span> 
        <span style="font-style:italic; margin-right:1rem;">"${target.title.slice(0, 40)}..."</span>
        <button onclick="restoreView()" style="background:none; border:1px solid var(--text-muted); color:var(--text-main); border-radius:4px; cursor:pointer; padding:2px 8px;">
            <i class="fa-solid fa-arrow-left"></i> Back
        </button>
    `;

    // Animate button
    if (btn) {
        const icon = btn.querySelector('i');
        icon.classList.add('fa-spin');
        setTimeout(() => icon.classList.remove('fa-spin'), 500);
    }

    // Scroll to top
    window.scrollTo({ top: 0, behavior: 'smooth' });
};

window.checkDiscussion = async (id, btn) => {
    // Animate
    const icon = btn.querySelector('i');
    icon.classList.add('fa-spin');

    try {
        // Query HN Algolia for the arxiv ID (e.g. 2310.12345)
        // Usually papers are linked as arxiv.org/abs/ID
        const query = `arxiv.org/abs/${id}`;
        const res = await fetch(`https://hn.algolia.com/api/v1/search?query=${query}&tags=story`);
        const data = await res.json();

        if (data.hits && data.hits.length > 0) {
            // Found it! Open the first hit.
            const hit = data.hits[0];
            // Prefer the HN discussion link (objectID) over the url (which is just the paper)
            const hnUrl = `https://news.ycombinator.com/item?id=${hit.objectID}`;
            window.open(hnUrl, '_blank');
        } else {
            // Toast
            const originalTitle = btn.title;
            btn.classList.add('shake');
            setTimeout(() => btn.classList.remove('shake'), 400);

            // Simple tooltip feedback
            alert("No discussion found on Hacker News yet.");
        }
    } catch (err) {
        console.error(err);
        alert("Failed to check HN.");
    } finally {
        icon.classList.remove('fa-spin');
    }
};

// Playlist Logic

window.autoTagPaper = async (id, btn) => {
    // Animation
    const icon = btn.querySelector('i');
    icon.classList.remove('fa-tags');
    icon.classList.add('fa-spinner', 'fa-spin');

    try {
        const res = await fetch(`${API_BASE}/tag`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ paper_id: id })
        });
        if (!res.ok) throw new Error("Tagging failed");

        const data = await res.json();

        // Update local model
        const paper = allPapers.find(p => p.id === id);
        if (paper) {
            paper.concepts = data.concepts;
            // Re-render card? Or full grid.
            // Full grid is safer to ensure layout
            loadPapers();
        }

    } catch (e) {
        console.error(e);
        alert("Failed to auto-tag.");
        icon.classList.remove('fa-spinner', 'fa-spin');
        icon.classList.add('fa-tags');
    }
};

function applyConceptUpdates(conceptMap) {
    if (!conceptMap || typeof conceptMap !== 'object') return;
    const updateList = (list) => {
        if (!Array.isArray(list)) return;
        list.forEach((p) => {
            if (p && conceptMap[p.id]) {
                p.concepts = conceptMap[p.id];
            }
        });
    };
    updateList(allPapers);
    updateList(currentVisiblePapers);
}

window.openBatchTagModal = () => {
    const count = selectedPaperIds.size;
    if (!count) {
        alert("Select papers first.");
        return;
    }
    const label = document.getElementById('batchTagCount');
    if (label) label.textContent = `${count} paper${count === 1 ? '' : 's'} selected.`;
    const input = document.getElementById('batchTagInput');
    if (input) input.value = '';
    const merge = document.getElementById('batchTagMergeCheck');
    if (merge) merge.checked = true;
    showModal('batchTagModal');
};

window.closeBatchTagModal = () => {
    hideModal('batchTagModal');
};

window.runBatchTag = async () => {
    const ids = Array.from(selectedPaperIds);
    if (!ids.length) {
        alert("Select papers first.");
        return;
    }
    const input = document.getElementById('batchTagInput');
    const mergeCheck = document.getElementById('batchTagMergeCheck');
    const raw = input ? input.value.trim() : '';
    const concepts = raw ? raw.split(',').map(t => t.trim()).filter(Boolean) : null;
    const mode = (mergeCheck && mergeCheck.checked) ? 'merge' : 'replace';
    const use_ai = !concepts || concepts.length === 0;

    try {
        const res = await fetch(`${API_BASE}/tag/batch`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                paper_ids: ids,
                concepts: concepts || null,
                mode,
                use_ai,
            })
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Batch tagging failed");
        if (data.concepts) {
            applyConceptUpdates(data.concepts);
            renderPaperGrid(currentVisiblePapers);
        } else {
            loadPapers();
        }
        closeBatchTagModal();
    } catch (e) {
        console.error(e);
        alert(`Batch tagging failed: ${e.message}`);
    }
};

window.filterByConcept = (concept) => {
    document.getElementById('searchInput').value = concept;
    handleSearch(concept);
};

window.addToQueue = async (id, btn) => {
    // Original Monologue Queue
    const paper = allPapers.find(p => p.id === id);
    if (!paper) return;

    playQueue.push({ ...paper, style: 'monologue' });
    updatePlayerUI();

    // Animation
    const icon = btn.querySelector('i');
    icon.classList.add('fa-bounce');
    setTimeout(() => icon.classList.remove('fa-bounce'), 1000);

    // If nothing playing, start
    if (playQueue.length === 1 && !isPlaying) {
        playTrack(0);
    } else {
        document.getElementById('podcastPlayer').classList.remove('hidden');
    }
};

window.playDuo = async (id, btn) => {
    // Duo Conversation Queue
    const paper = allPapers.find(p => p.id === id);
    if (!paper) return;

    playQueue.push({ ...paper, style: 'conversation' });
    updatePlayerUI();

    // Animation
    const icon = btn.querySelector('i');
    icon.classList.add('fa-spin');
    setTimeout(() => icon.classList.remove('fa-spin'), 1000);

    // If nothing playing, start
    if (playQueue.length === 1 && !isPlaying) {
        playTrack(0);
    } else {
        document.getElementById('podcastPlayer').classList.remove('hidden');
    }
};

window.playNextTrack = () => {
    if (currentTrackIndex < playQueue.length - 1) {
        playTrack(currentTrackIndex + 1);
    } else {
        // End of queue
        isPlaying = false;
        updatePlayerUI();
    }
};

window.playPrevTrack = () => {
    if (currentTrackIndex > 0) {
        playTrack(currentTrackIndex - 1);
    }
};

window.playTrack = async (index) => {
    if (index < 0 || index >= playQueue.length) return;

    currentTrackIndex = index;
    const paper = playQueue[index];

    updatePlayerUI();
    document.getElementById('playPauseBtn').innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i>';

    try {
        // Generate Audio
        let text = `Next up: ${paper.title}. . ${paper.summary}`;
        const payload = {
            text: text,
            paper_data: paper,
            style: paper.style || 'monologue'
        };

        const res = await fetch(`${API_BASE}/podcast`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });

        if (!res.ok) throw new Error("Audio gen failed");

        const blob = await res.blob();
        const url = URL.createObjectURL(blob);

        audioObj.src = url;
        audioObj.play();
        isPlaying = true;

    } catch (e) {
        console.error(e);
        alert("Failed to play track: " + e.message);
        playNextTrack(); // Skip error
    }
    updatePlayerUI();
};

window.togglePlay = () => {
    if (!audioObj.src && playQueue.length > 0) {
        playTrack(0);
        return;
    }

    if (audioObj.paused) {
        audioObj.play();
    } else {
        audioObj.pause();
    }
};

function updatePlayerState(playing) {
    isPlaying = playing;
    const btn = document.getElementById('playPauseBtn');
    btn.innerHTML = playing ? '<i class="fa-solid fa-pause"></i>' : '<i class="fa-solid fa-play"></i>';
}

function updatePlayerTime() {
    const cur = audioObj.currentTime;
    const dur = audioObj.duration || 0;
    const fmt = (t) => {
        const m = Math.floor(t / 60);
        const s = Math.floor(t % 60).toString().padStart(2, '0');
        return `${m}:${s}`;
    };
    document.getElementById('playerTime').textContent = `${fmt(cur)} / ${fmt(dur)}`;
}

window.togglePlaylist = () => {
    const drawer = document.getElementById('playlistDrawer');
    drawer.classList.toggle('hidden');
    renderPlaylistItems();
};

window.closePlayer = () => {
    audioObj.pause();
    document.getElementById('podcastPlayer').classList.add('hidden');
    playQueue = [];
    currentTrackIndex = -1;
};

window.clearQueue = () => {
    playQueue = [];
    currentTrackIndex = -1;
    audioObj.pause();
    updatePlayerUI();
    renderPlaylistItems();
};

function updatePlayerUI() {
    const titleEl = document.getElementById('playerTitle');
    const statusEl = document.getElementById('playerStatus');

    if (currentTrackIndex >= 0 && currentTrackIndex < playQueue.length) {
        titleEl.textContent = playQueue[currentTrackIndex].title;
    } else {
        titleEl.textContent = "Select a paper...";
    }

    statusEl.textContent = `Queue: ${playQueue.length} items • ${currentTrackIndex + 1}/${playQueue.length}`;
    renderPlaylistItems();
}

function renderPlaylistItems() {
    const list = document.getElementById('playlistItems');
    list.innerHTML = playQueue.map((p, i) => `
        <li class="${i === currentTrackIndex ? 'active' : ''}" onclick="playTrack(${i})">
            <span class="idx">${i + 1}.</span>
            <span class="t">${p.title}</span>
            ${i === currentTrackIndex ? '<i class="fa-solid fa-volume-high"></i>' : ''}
        </li>
    `).join('');
}


// Chat Logic
let currentChatPaperId = null;

window.openChat = (id) => {
    currentChatPaperId = id;
    recordTrail({ type: 'chat', paper_id: id, label: `Chat: ${getPaperTitleById(id)}` });
    showModal('chatModal');
    document.getElementById('chatInput').focus();
    // Reset history if new paper? Or keep?
    // For now, simple clear.
    const history = document.getElementById('chatHistory');
    history.innerHTML = `
        <div class="chat-message system">
            <div class="message-content">
                Hello! I can answer questions about this paper based on its text.
            </div>
        </div>
    `;
};

window.closeChatModal = () => {
    hideModal('chatModal');
    currentChatPaperId = null;
};

window.openStructure = async (paperId, refresh = false) => {
    currentStructuredPaperId = paperId;
    recordTrail({ type: 'structure', paper_id: paperId, label: `Structure: ${getPaperTitleById(paperId)}` });
    showModal('structureModal');
    const container = document.getElementById('structureContent');
    if (container) container.innerHTML = '<div class="loader"></div>';

    try {
        const url = refresh
            ? `${API_BASE}/papers/${encodeURIComponent(paperId)}/structure/refresh`
            : `${API_BASE}/papers/${encodeURIComponent(paperId)}/structure`;
        const res = await fetch(url, refresh ? { method: 'POST' } : undefined);
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Failed to load structure");

        const s = data.structure || {};
        const modeTag = refresh ? 'refreshed' : (data.cached ? 'cached' : 'generated');
        container.innerHTML = `
            <div class="tag" style="width:max-content;">${escapeHtml(modeTag)}</div>
            <div><strong>Problem</strong><br>${escapeHtml(s.problem || 'N/A')}</div>
            <div><strong>Method</strong><br>${escapeHtml(s.method || 'N/A')}</div>
            <div><strong>Dataset / Evaluation</strong><br>${escapeHtml(s.dataset || 'N/A')}</div>
            <div><strong>Results</strong><br>${escapeHtml(s.results || 'N/A')}</div>
            <div><strong>Limitations</strong><br>${escapeHtml(s.limitations || 'N/A')}</div>
            <div style="display:flex; gap:0.5rem; margin-top:0.5rem;">
                <button class="btn-secondary" onclick="openStructure('${paperId}', true)">Regenerate</button>
            </div>
        `;
    } catch (e) {
        if (container) container.innerHTML = `<div style="color:var(--danger)">Error: ${e.message}</div>`;
    }
};

window.closeStructureModal = () => {
    hideModal('structureModal');
    currentStructuredPaperId = null;
};

function parseVersionNumber(value) {
    const num = Number(value);
    if (Number.isFinite(num) && num > 0) return Math.max(1, Math.round(num));
    return 1;
}

function pickDefaultVersionPair(rows) {
    const versions = Array.from(new Set((rows || []).map((r) => parseVersionNumber(r.arxiv_version)))).sort((a, b) => a - b);
    if (!versions.length) return { from: 1, to: 1 };
    if (versions.length === 1) return { from: versions[0], to: versions[0] };
    return { from: versions[versions.length - 2], to: versions[versions.length - 1] };
}

function renderVersionList(rows) {
    const container = document.getElementById('versionList');
    if (!container) return;
    if (!rows || rows.length === 0) {
        container.innerHTML = '<div style="color:var(--text-muted);">No versions found.</div>';
        return;
    }
    container.innerHTML = rows.map((r) => {
        const version = parseVersionNumber(r.arxiv_version);
        const title = r.title || r.id || '';
        const published = String(r.published || '').slice(0, 10);
        const citations = Number(r.citation_count || 0);
        return `
            <div class="version-item">
                <div class="version-item-top">
                    <span class="tag" style="background:rgba(14,165,233,0.16); color:#7dd3fc;">v${version}</span>
                    <span style="font-size:0.78rem; color:var(--text-muted);">${escapeHtml(published)}</span>
                </div>
                <div class="version-item-title">${escapeHtml(title)}</div>
                <div style="font-size:0.78rem; color:var(--text-muted);">
                    ${citations > 0 ? `${citations} citations` : 'No citation count yet'}
                </div>
            </div>
        `;
    }).join('');
}

function bindVersionSelectListeners() {
    const fromSel = document.getElementById('versionFromSelect');
    const toSel = document.getElementById('versionToSelect');
    if (fromSel && !fromSel.dataset.bound) {
        fromSel.addEventListener('change', () => loadVersionDiff());
        fromSel.dataset.bound = '1';
    }
    if (toSel && !toSel.dataset.bound) {
        toSel.addEventListener('change', () => loadVersionDiff());
        toSel.dataset.bound = '1';
    }
}

window.openVersionModal = async (paperId) => {
    activeVersionPaperId = paperId;
    activeVersionRows = [];
    recordTrail({ type: 'versions', paper_id: paperId, label: `Versions: ${getPaperTitleById(paperId)}` });
    showModal('versionModal');
    const titleEl = document.getElementById('versionPaperTitle');
    const metaEl = document.getElementById('versionFamilyMeta');
    const fieldsEl = document.getElementById('versionDiffFields');
    const summaryEl = document.getElementById('versionDiffSummary');
    const textEl = document.getElementById('versionDiffText');
    if (titleEl) titleEl.textContent = getPaperTitleById(paperId) || paperId;
    if (metaEl) metaEl.textContent = 'Loading versions...';
    if (fieldsEl) fieldsEl.innerHTML = '';
    if (summaryEl) summaryEl.textContent = 'Loading diff...';
    if (textEl) textEl.textContent = '';
    bindVersionSelectListeners();
    await reloadVersionData();
};

window.closeVersionModal = () => {
    hideModal('versionModal');
    activeVersionPaperId = null;
    activeVersionRows = [];
};

window.openLatestVersionDiff = async (paperId) => {
    if (!paperId) return;
    await openVersionModal(paperId);
};

window.openLatestVersionDiffFromNotes = async () => {
    if (!activeNotesPaperId) {
        alert("Open notes for a paper first.");
        return;
    }
    await openLatestVersionDiff(activeNotesPaperId);
};

window.reloadVersionData = async () => {
    if (!activeVersionPaperId) return;
    const listEl = document.getElementById('versionList');
    const metaEl = document.getElementById('versionFamilyMeta');
    const fromSel = document.getElementById('versionFromSelect');
    const toSel = document.getElementById('versionToSelect');
    if (listEl) listEl.innerHTML = '<div class="loader"></div>';
    if (metaEl) metaEl.textContent = 'Loading versions...';

    try {
        const res = await fetch(`${API_BASE}/papers/${encodeURIComponent(activeVersionPaperId)}/versions`);
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Failed to load versions");
        const rows = Array.isArray(data.versions) ? data.versions : [];
        activeVersionRows = rows;
        renderVersionList(rows);
        if (metaEl) {
            const baseId = data.arxiv_base_id || '';
            metaEl.textContent = `${rows.length} versions${baseId ? ` · ${baseId}` : ''}`;
        }

        const uniqueVersions = Array.from(new Set(rows.map((r) => parseVersionNumber(r.arxiv_version)))).sort((a, b) => a - b);
        const optionsHtml = uniqueVersions.map((v) => `<option value="${v}">v${v}</option>`).join('');
        if (fromSel) fromSel.innerHTML = optionsHtml;
        if (toSel) toSel.innerHTML = optionsHtml;

        const summaryEl = document.getElementById('versionDiffSummary');
        const fieldsEl = document.getElementById('versionDiffFields');
        const textEl = document.getElementById('versionDiffText');
        if (uniqueVersions.length < 2) {
            if (summaryEl) summaryEl.textContent = 'Need at least two versions to compute a diff.';
            if (fieldsEl) fieldsEl.innerHTML = '';
            if (textEl) textEl.textContent = '';
            return;
        }

        const pair = pickDefaultVersionPair(rows);
        if (fromSel) fromSel.value = String(pair.from);
        if (toSel) toSel.value = String(pair.to);

        await loadVersionDiff();
    } catch (e) {
        if (listEl) listEl.innerHTML = `<div style="color:var(--danger)">Failed to load versions: ${escapeHtml(e.message)}</div>`;
        const summaryEl = document.getElementById('versionDiffSummary');
        if (summaryEl) summaryEl.textContent = `Failed to load diff: ${e.message}`;
    }
};

window.swapVersionSelection = () => {
    const fromSel = document.getElementById('versionFromSelect');
    const toSel = document.getElementById('versionToSelect');
    if (!fromSel || !toSel) return;
    const from = fromSel.value;
    fromSel.value = toSel.value;
    toSel.value = from;
    loadVersionDiff();
};

window.loadVersionDiff = async () => {
    if (!activeVersionPaperId) return;
    const fromSel = document.getElementById('versionFromSelect');
    const toSel = document.getElementById('versionToSelect');
    const summaryEl = document.getElementById('versionDiffSummary');
    const fieldsEl = document.getElementById('versionDiffFields');
    const textEl = document.getElementById('versionDiffText');
    if (!fromSel || !toSel || !summaryEl || !fieldsEl || !textEl) return;
    const from = parseVersionNumber(fromSel.value);
    const to = parseVersionNumber(toSel.value);
    summaryEl.textContent = 'Loading diff...';
    fieldsEl.innerHTML = '';
    textEl.textContent = '';

    try {
        const query = new URLSearchParams({ v_from: String(from), v_to: String(to) }).toString();
        const res = await fetch(`${API_BASE}/papers/${encodeURIComponent(activeVersionPaperId)}/diff?${query}`);
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Failed to load diff");

        const changed = Array.isArray(data.changed_structure_fields) ? data.changed_structure_fields : [];
        summaryEl.innerHTML = `
            Comparing <strong>v${Number(data.from_version || from)}</strong> → <strong>v${Number(data.to_version || to)}</strong>
            ${changed.length ? ` · Changed fields: ${changed.map((x) => escapeHtml(String(x))).join(', ')}` : ' · No structured field changes detected.'}
        `;

        const structure = (data && data.structure_changes && typeof data.structure_changes === 'object')
            ? data.structure_changes
            : {};
        const fieldOrder = ['problem', 'method', 'dataset', 'results', 'limitations'];
        fieldsEl.innerHTML = fieldOrder.map((field) => {
            const meta = structure[field] || {};
            const fromText = meta.from || '';
            const toText = meta.to || '';
            const changedField = Boolean(meta.changed);
            return `
                <div class="version-field ${changedField ? 'changed' : ''}">
                    <h5>${escapeHtml(field)}</h5>
                    <p><strong>From:</strong> ${escapeHtml(fromText || 'N/A')}</p>
                    <p><strong>To:</strong> ${escapeHtml(toText || 'N/A')}</p>
                </div>
            `;
        }).join('');

        const chunks = [];
        if (data.title_diff) {
            chunks.push(`### Title\n${String(data.title_diff)}`);
        }
        if (data.summary_diff) {
            chunks.push(`### Abstract\n${String(data.summary_diff)}`);
        }
        textEl.textContent = chunks.join('\n\n') || 'No title/abstract text diff available for this version pair.';
    } catch (e) {
        summaryEl.textContent = `Failed to load diff: ${e.message}`;
        fieldsEl.innerHTML = '';
        textEl.textContent = '';
    }
};

function updateReadingTimelineUI(status, progress) {
    const steps = document.querySelectorAll('#readingTimeline .reading-step');
    steps.forEach((step) => {
        const stepKey = step.getAttribute('data-step');
        step.classList.remove('active');
        step.classList.remove('complete');
        if (status === stepKey) {
            step.classList.add('active');
        }
    });
    if (status === 'done') {
        steps.forEach((step) => step.classList.add('complete'));
    } else if (status === 'reading') {
        steps.forEach((step) => {
            const stepKey = step.getAttribute('data-step');
            if (stepKey === 'queue') step.classList.add('complete');
        });
    }
    const progressInput = document.getElementById('readingProgressInput');
    const progressLabel = document.getElementById('readingProgressLabel');
    const progressBar = document.getElementById('readingProgressBar');
    if (progressInput) progressInput.value = String(progress || 0);
    if (progressLabel) progressLabel.textContent = `${progress || 0}%`;
    if (progressBar) progressBar.style.width = `${progress || 0}%`;
}

function resetReadingExtrasUI() {
    const estimateVal = document.getElementById('readingEstimateValue');
    const estimateMeta = document.getElementById('readingEstimateMeta');
    const questionsList = document.getElementById('readingQuestionsList');
    if (estimateVal) estimateVal.textContent = 'Not estimated';
    if (estimateMeta) estimateMeta.textContent = '';
    if (questionsList) questionsList.textContent = 'No questions generated yet.';
}

function updateReadingEstimateUI(payload) {
    const estimateVal = document.getElementById('readingEstimateValue');
    const estimateMeta = document.getElementById('readingEstimateMeta');
    if (!estimateVal) return;
    if (!payload || payload.available === false) {
        estimateVal.textContent = 'Not available';
        if (estimateMeta) {
            estimateMeta.textContent = payload && payload.reason ? payload.reason : '';
        }
        return;
    }
    const minutes = Number(payload.minutes || 0);
    const pages = Number(payload.page_count || 0);
    estimateVal.textContent = minutes > 0 ? `~${minutes} min` : 'Not estimated';
    if (estimateMeta) {
        const cachedNote = payload.cached ? ' · cached' : '';
        estimateMeta.textContent = pages > 0 ? `${pages} pages${cachedNote}` : cachedNote.trim();
    }
}

window.estimateReadingTime = async (forceDownload = false) => {
    if (!activeReadingPaperId) return;
    const estimateVal = document.getElementById('readingEstimateValue');
    if (estimateVal) estimateVal.textContent = 'Estimating...';
    try {
        const params = new URLSearchParams();
        if (forceDownload) {
            params.set('download', 'true');
            params.set('refresh', 'true');
        }
        const qs = params.toString();
        const url = `${API_BASE}/papers/${encodeURIComponent(activeReadingPaperId)}/reading-time${qs ? `?${qs}` : ''}`;
        const res = await fetch(url);
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Failed to estimate reading time");
        updateReadingEstimateUI(data);
    } catch (e) {
        updateReadingEstimateUI({ available: false, reason: e.message });
    }
};

window.loadReadingQuestions = async (refresh = false) => {
    if (!activeReadingPaperId) return;
    const list = document.getElementById('readingQuestionsList');
    if (list) list.innerHTML = '<div class="loader"></div>';
    try {
        const res = await fetch(`${API_BASE}/papers/${encodeURIComponent(activeReadingPaperId)}/questions?refresh=${refresh ? 'true' : 'false'}`);
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Failed to load questions");
        const questions = Array.isArray(data.questions) ? data.questions : [];
        if (!questions.length) {
            if (list) list.textContent = 'No questions generated yet.';
            return;
        }
        if (list) {
            list.innerHTML = `<ol>${questions.map(q => `<li>${escapeHtml(q)}</li>`).join('')}</ol>`;
        }
    } catch (e) {
        if (list) list.textContent = `Failed to load questions: ${e.message}`;
    }
};

window.openReadingModal = async (paperId) => {
    activeReadingPaperId = paperId;
    activeReadingStatus = 'queue';
    recordTrail({ type: 'reading', paper_id: paperId, label: `Reading: ${getPaperTitleById(paperId)}` });
    const titleEl = document.getElementById('readingModalTitle');
    const paper = (allPapers || []).find(p => p.id === paperId) || (currentVisiblePapers || []).find(p => p.id === paperId);
    if (titleEl) titleEl.textContent = paper ? paper.title : 'Reading Status';
    showModal('readingModal');

    const progressInput = document.getElementById('readingProgressInput');
    if (progressInput) {
        progressInput.oninput = (e) => {
            const value = Number(e.target.value || 0);
            updateReadingTimelineUI(activeReadingStatus, value);
        };
    }
    resetReadingExtrasUI();
    estimateReadingTime(false);
    loadReadingQuestions(false);

    try {
        const res = await fetch(`${API_BASE}/papers/${encodeURIComponent(paperId)}/reading`);
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Failed to load reading status");
        activeReadingStatus = data.status || 'queue';
        updateReadingTimelineUI(activeReadingStatus, Number(data.progress || 0));
    } catch (e) {
        updateReadingTimelineUI('queue', 0);
    }
};

window.closeReadingModal = () => {
    hideModal('readingModal');
    activeReadingPaperId = null;
};

window.setReadingStatus = (status) => {
    activeReadingStatus = status || 'queue';
    const progressInput = document.getElementById('readingProgressInput');
    const progress = progressInput ? Number(progressInput.value || 0) : 0;
    updateReadingTimelineUI(activeReadingStatus, progress);
};

window.saveReadingStatus = async () => {
    if (!activeReadingPaperId) return;
    const progressInput = document.getElementById('readingProgressInput');
    const progress = progressInput ? Number(progressInput.value || 0) : 0;
    try {
        const res = await fetch(`${API_BASE}/papers/${encodeURIComponent(activeReadingPaperId)}/reading`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ status: activeReadingStatus, progress })
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Failed to save reading status");
        updatePaperLocal(activeReadingPaperId, {
            reading_status: data.status,
            reading_progress: data.progress,
            reading_started_at: data.started_at,
            reading_finished_at: data.finished_at,
        });
        renderPaperGrid(currentVisiblePapers);
        closeReadingModal();
    } catch (e) {
        alert(`Failed to save reading status: ${e.message}`);
    }
};

function setReadingPlanStatus(text, isError = false) {
    const statusEl = document.getElementById('readingPlanStatus');
    if (!statusEl) return;
    statusEl.style.color = isError ? 'var(--danger)' : 'var(--text-muted)';
    statusEl.textContent = text || '';
}

function renderReadingPlanProgress(payload) {
    const el = document.getElementById('readingPlanProgress');
    if (!el) return;
    if (!payload || typeof payload !== 'object') {
        el.textContent = '';
        return;
    }
    const streak = Number(payload.streak_days || 0);
    const totals = payload.totals || {};
    const done = Number(totals.done_count || 0);
    const planned = Number(totals.planned_count || 0);
    const carry = payload.carry_over || {};
    const carryCount = Number(carry.count || 0);
    const rate = Number(payload.completion_rate || 0);
    el.textContent = `Streak ${streak} day${streak === 1 ? '' : 's'} · Done ${done}/${planned} · Completion ${(rate * 100).toFixed(1)}%${carryCount > 0 ? ` · Carry-over ${carryCount}` : ''}`;
}

function clearReadingPlanUndoState() {
    lastReadingPlanAction = null;
    const bar = document.getElementById('readingPlanUndoBar');
    const text = document.getElementById('readingPlanUndoText');
    if (text) text.textContent = '';
    if (bar) bar.classList.add('hidden');
}

function setReadingPlanUndoState(action, paperId, paperTitle = '') {
    const bar = document.getElementById('readingPlanUndoBar');
    const text = document.getElementById('readingPlanUndoText');
    if (!bar || !text || !paperId) return;
    const act = String(action || '').toLowerCase();
    if (!['done', 'defer'].includes(act)) {
        clearReadingPlanUndoState();
        return;
    }
    lastReadingPlanAction = { action: act, paperId: String(paperId), paperTitle: String(paperTitle || '') };
    const label = lastReadingPlanAction.paperTitle || lastReadingPlanAction.paperId;
    text.textContent = act === 'done'
        ? `Marked done: ${label}`
        : `Deferred: ${label}`;
    bar.classList.remove('hidden');
}

function getReadingPlanOptionsFromUi() {
    const totalInput = document.getElementById('planTotalMinutes');
    const maxInput = document.getElementById('planMaxItems');
    const budgetMode = document.getElementById('planBudgetMode');
    const includeNew = document.getElementById('planIncludeNew');
    const includeLiked = document.getElementById('planIncludeLiked');
    const includeBookmarked = document.getElementById('planIncludeBookmarked');
    const mode = String(budgetMode?.value || 'balanced').toLowerCase();
    return {
        total_minutes: Math.max(10, Math.min(360, Number(totalInput?.value || 60))),
        max_items: Math.max(1, Math.min(20, Number(maxInput?.value || 6))),
        budget_mode: ['balanced', 'focus', 'sprint', 'deep'].includes(mode) ? mode : 'balanced',
        include_new: Boolean(includeNew?.checked),
        include_liked: Boolean(includeLiked?.checked),
        include_bookmarked: Boolean(includeBookmarked?.checked),
    };
}

function applyReadingPlanOptionsToUi(options) {
    if (!options || typeof options !== 'object') return;
    const totalInput = document.getElementById('planTotalMinutes');
    const maxInput = document.getElementById('planMaxItems');
    const budgetMode = document.getElementById('planBudgetMode');
    const includeNew = document.getElementById('planIncludeNew');
    const includeLiked = document.getElementById('planIncludeLiked');
    const includeBookmarked = document.getElementById('planIncludeBookmarked');
    if (totalInput && options.total_minutes != null) totalInput.value = String(Number(options.total_minutes));
    if (maxInput && options.max_items != null) maxInput.value = String(Number(options.max_items));
    if (budgetMode && options.budget_mode != null) budgetMode.value = String(options.budget_mode);
    if (includeNew && options.include_new != null) includeNew.checked = Boolean(options.include_new);
    if (includeLiked && options.include_liked != null) includeLiked.checked = Boolean(options.include_liked);
    if (includeBookmarked && options.include_bookmarked != null) includeBookmarked.checked = Boolean(options.include_bookmarked);
}

window.applyReadingPlanPreset = async (preset) => {
    const mode = String(preset || '').toLowerCase();
    const totalInput = document.getElementById('planTotalMinutes');
    const maxInput = document.getElementById('planMaxItems');
    const budgetMode = document.getElementById('planBudgetMode');
    const includeNew = document.getElementById('planIncludeNew');
    const includeLiked = document.getElementById('planIncludeLiked');
    const includeBookmarked = document.getElementById('planIncludeBookmarked');

    const presets = {
        sprint: { total: 30, max: 4, mode: 'sprint', includeNew: true, includeLiked: true, includeBookmarked: true },
        focus: { total: 60, max: 5, mode: 'focus', includeNew: true, includeLiked: true, includeBookmarked: true },
        balanced: { total: 90, max: 7, mode: 'balanced', includeNew: true, includeLiked: true, includeBookmarked: true },
        deep: { total: 120, max: 4, mode: 'deep', includeNew: false, includeLiked: true, includeBookmarked: true },
    };
    const selected = presets[mode] || presets.balanced;
    if (totalInput) totalInput.value = String(selected.total);
    if (maxInput) maxInput.value = String(selected.max);
    if (budgetMode) budgetMode.value = selected.mode;
    if (includeNew) includeNew.checked = Boolean(selected.includeNew);
    if (includeLiked) includeLiked.checked = Boolean(selected.includeLiked);
    if (includeBookmarked) includeBookmarked.checked = Boolean(selected.includeBookmarked);
    await generateReadingPlan(true);
};

function renderReadingPlan(payload) {
    const listEl = document.getElementById('readingPlanList');
    if (!listEl) return;
    const items = Array.isArray(payload?.items) ? payload.items : [];
    const budget = Number(payload?.total_minutes_budget || 0);
    const planned = Number(payload?.planned_minutes || 0);
    const count = Number(payload?.count || items.length || 0);
    const cached = Boolean(payload?.cached);
    const deferredCount = Number(payload?.deferred_count || 0);
    const budgetMode = String(payload?.options?.budget_mode || payload?.budget_mode || 'balanced');
    setReadingPlanStatus(
        `${count} item${count === 1 ? '' : 's'} · ${planned}/${budget} min planned · mode ${budgetMode}${deferredCount ? ` · deferred ${deferredCount}` : ''}${cached ? ' · cached' : ''}`
    );

    if (!items.length) {
        listEl.innerHTML = '<div style="color:var(--text-muted); text-align:center; padding:1rem 0.5rem;">No candidates matched this plan. Try increasing minutes or enabling more sources.</div>';
        return;
    }

    listEl.innerHTML = items.map((item) => {
        const pid = String(item.id || '');
        const title = item.title || pid || 'Paper';
        const published = String(item.published || '').slice(0, 10);
        const status = String(item.status || 'queue');
        const progress = Number(item.progress || 0);
        const minutesRemaining = Number(item.minutes_remaining || 0);
        const minutesTotal = Number(item.minutes_total || 0);
        const sources = Array.isArray(item.sources) ? item.sources.join(', ') : '';
        const score = Number(item.score || 0);
        return `
            <div class="reading-plan-item">
                <div class="reading-plan-title">${escapeHtml(title)}</div>
                <div class="reading-plan-meta">
                    ${escapeHtml(published)} · ${escapeHtml(status)} (${progress}%) · ${minutesRemaining} min remaining (of ${minutesTotal})
                </div>
                <div style="display:flex; gap:0.5rem; flex-wrap:wrap;">
                    ${sources ? `<span class="tag" style="background:rgba(56,189,248,0.14); color:#7dd3fc;">${escapeHtml(sources)}</span>` : ''}
                    <span class="tag" style="background:rgba(16,185,129,0.14); color:#6ee7b7;">score ${score.toFixed(2)}</span>
                </div>
                <div class="reading-plan-actions">
                    <a href="${API_BASE}/papers/${encodeURIComponent(pid)}/pdf" target="_blank" class="pdf-link"><i class="fa-regular fa-file-pdf"></i> PDF</a>
                    <button class="btn-secondary" onclick="openReadingModal(decodeURIComponent('${encodeURIComponent(pid)}'))" style="padding:0.3rem 0.7rem;">
                        <i class="fa-solid fa-book-open-reader"></i> Reading
                    </button>
                    <button class="btn-secondary" onclick="openNotesModal(decodeURIComponent('${encodeURIComponent(pid)}'))" style="padding:0.3rem 0.7rem;">
                        <i class="fa-solid fa-note-sticky"></i> Notes
                    </button>
                    <button class="btn-secondary" onclick="applyReadingPlanItemAction(decodeURIComponent('${encodeURIComponent(pid)}'),'done')" style="padding:0.3rem 0.7rem;">
                        <i class="fa-solid fa-check"></i> Done
                    </button>
                    <button class="btn-secondary" onclick="applyReadingPlanItemAction(decodeURIComponent('${encodeURIComponent(pid)}'),'defer')" style="padding:0.3rem 0.7rem;">
                        <i class="fa-solid fa-clock"></i> Defer
                    </button>
                </div>
            </div>
        `;
    }).join('');
}

function renderReadingPlanHistory(historyItems) {
    const selectEl = document.getElementById('readingPlanHistorySelect');
    if (!selectEl) return;
    const items = Array.isArray(historyItems) ? historyItems : [];
    const currentDate = activeReadingPlanPayload?.date || '';
    const options = ['<option value="">Today</option>'];
    items.forEach((item) => {
        const date = String(item.plan_date || '').trim();
        if (!date) return;
        const label = `${date} · ${Number(item.count || 0)} items · ${Number(item.planned_minutes || 0)}m`;
        options.push(`<option value="${escapeHtml(date)}"${date === currentDate ? ' selected' : ''}>${escapeHtml(label)}</option>`);
    });
    selectEl.innerHTML = options.join('');
}

window.openReadingPlanModal = async () => {
    recordTrail({ type: 'reading_plan', label: 'Reading plan' });
    showModal('readingPlanModal');
    clearReadingPlanUndoState();
    renderReadingPlanProgress(null);
    const listEl = document.getElementById('readingPlanList');
    if (listEl) listEl.innerHTML = '<div class="loader"></div>';
    await loadTodayReadingPlan(false);
    await loadReadingPlanHistory();
};

window.closeReadingPlanModal = () => {
    hideModal('readingPlanModal');
};

window.loadReadingPlanHistory = async () => {
    try {
        const res = await fetch(`${API_BASE}/reading-plan/history?limit=40`);
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Failed to load reading plan history");
        renderReadingPlanHistory(data.items || []);
    } catch (e) {
        // Keep modal usable even if history fails.
    }
};

window.loadReadingPlanProgress = async (days = 14) => {
    try {
        const span = Math.max(1, Math.min(90, Number(days || 14)));
        const res = await fetch(`${API_BASE}/reading-plan/progress?days=${span}`);
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Failed to load reading plan progress");
        renderReadingPlanProgress(data);
    } catch (e) {
        const el = document.getElementById('readingPlanProgress');
        if (el) el.textContent = `Progress unavailable: ${e.message}`;
    }
};

window.loadTodayReadingPlan = async (refresh = false) => {
    try {
        setReadingPlanStatus('Loading today\'s plan...');
        const url = `${API_BASE}/reading-plan/today${refresh ? '?refresh=true' : ''}`;
        const res = await fetch(url);
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Failed to load reading plan");
        activeReadingPlanPayload = data;
        applyReadingPlanOptionsToUi(data.options || {
            total_minutes: data.total_minutes_budget,
            max_items: data.max_items,
            budget_mode: 'balanced',
            include_new: true,
            include_liked: true,
            include_bookmarked: true,
        });
        renderReadingPlan(data);
        await loadReadingPlanHistory();
        await loadReadingPlanProgress(14);
    } catch (e) {
        setReadingPlanStatus(`Failed to load plan: ${e.message}`, true);
        const listEl = document.getElementById('readingPlanList');
        if (listEl) listEl.innerHTML = '';
    }
};

window.generateReadingPlan = async (refresh = true) => {
    try {
        setReadingPlanStatus('Generating plan...');
        const options = getReadingPlanOptionsFromUi();
        const res = await fetch(`${API_BASE}/reading-plan/generate`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                total_minutes: options.total_minutes,
                max_items: options.max_items,
                budget_mode: options.budget_mode,
                include_new: options.include_new,
                include_liked: options.include_liked,
                include_bookmarked: options.include_bookmarked,
                refresh: Boolean(refresh),
            })
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Failed to generate reading plan");
        activeReadingPlanPayload = data;
        applyReadingPlanOptionsToUi(data.options || options);
        renderReadingPlan(data);
        await loadReadingPlanHistory();
        await loadReadingPlanProgress(14);
    } catch (e) {
        setReadingPlanStatus(`Failed to generate plan: ${e.message}`, true);
    }
};

window.loadSelectedReadingPlanHistory = async () => {
    const selectEl = document.getElementById('readingPlanHistorySelect');
    if (!selectEl || !selectEl.value) {
        await loadTodayReadingPlan(false);
        return;
    }
    const date = String(selectEl.value).trim();
    if (!date) {
        await loadTodayReadingPlan(false);
        return;
    }
    try {
        setReadingPlanStatus(`Loading plan for ${date}...`);
        const res = await fetch(`${API_BASE}/reading-plan/${encodeURIComponent(date)}`);
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Failed to load historical reading plan");
        activeReadingPlanPayload = data;
        applyReadingPlanOptionsToUi(data.options || {
            total_minutes: data.total_minutes_budget,
            max_items: data.max_items,
            budget_mode: 'balanced',
            include_new: true,
            include_liked: true,
            include_bookmarked: true,
        });
        renderReadingPlan(data);
        await loadReadingPlanHistory();
        await loadReadingPlanProgress(14);
    } catch (e) {
        setReadingPlanStatus(`Failed to load history plan: ${e.message}`, true);
    }
};

window.applyReadingPlanItemAction = async (paperId, action) => {
    if (!paperId) return;
    const act = String(action || '').toLowerCase();
    if (!['done', 'defer'].includes(act)) return;
    try {
        setReadingPlanStatus(act === 'done' ? 'Marking item as done...' : 'Deferring item...');
        const res = await fetch(`${API_BASE}/reading-plan/action`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                paper_id: paperId,
                action: act,
                defer_days: act === 'defer' ? 1 : 0,
            })
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Failed to apply reading plan action");
        if (act === 'done') {
            updatePaperLocal(paperId, {
                reading_status: 'done',
                reading_progress: 100,
            });
            renderPaperGrid(currentVisiblePapers);
        }
        const paper = (allPapers || []).find((p) => p.id === paperId) || {};
        setReadingPlanUndoState(act, paperId, paper.title || '');
        if (data && data.progress) {
            renderReadingPlanProgress(data.progress);
        } else {
            await loadReadingPlanProgress(14);
        }
        await loadTodayReadingPlan(true);
        await loadReadingPlanHistory();
    } catch (e) {
        setReadingPlanStatus(`Failed to apply action: ${e.message}`, true);
    }
};

window.undoLastReadingPlanAction = async () => {
    if (!lastReadingPlanAction || !lastReadingPlanAction.paperId) return;
    const undoAction = lastReadingPlanAction.action === 'done' ? 'undo_done' : 'undefer';
    try {
        setReadingPlanStatus('Undoing last action...');
        const res = await fetch(`${API_BASE}/reading-plan/action`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                paper_id: lastReadingPlanAction.paperId,
                action: undoAction,
            })
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Failed to undo action");
        clearReadingPlanUndoState();
        if (data && data.progress) {
            renderReadingPlanProgress(data.progress);
        } else {
            await loadReadingPlanProgress(14);
        }
        await loadTodayReadingPlan(true);
        await loadReadingPlanHistory();
    } catch (e) {
        setReadingPlanStatus(`Failed to undo action: ${e.message}`, true);
    }
};

function hasWeeklyPickLabel(paper) {
    if (!paper) return false;
    const labels = Array.isArray(paper.labels) ? paper.labels : [];
    return labels.includes('Weekly Pick');
}

function updateWeeklyPickToggle(paperId) {
    const toggle = document.getElementById('weeklyPickToggle');
    if (!toggle) return;
    const paper = (allPapers || []).find(p => p.id === paperId) || (currentVisiblePapers || []).find(p => p.id === paperId);
    toggle.checked = hasWeeklyPickLabel(paper);
}

window.toggleWeeklyPick = async (active) => {
    if (!activeNotesPaperId) return;
    const statusEl = document.getElementById('weeklyPickStatus');
    if (statusEl) statusEl.textContent = 'Saving...';
    try {
        const res = await fetch(`${API_BASE}/papers/${encodeURIComponent(activeNotesPaperId)}/weekly-pick`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ active: Boolean(active) })
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Failed to update weekly pick.");
        const paper = (allPapers || []).find(p => p.id === activeNotesPaperId) || (currentVisiblePapers || []).find(p => p.id === activeNotesPaperId);
        const labels = new Set(Array.isArray(paper?.labels) ? paper.labels : []);
        if (active) {
            labels.add('Weekly Pick');
        } else {
            labels.delete('Weekly Pick');
        }
        updatePaperLocal(activeNotesPaperId, { labels: Array.from(labels) });
        renderPaperGrid(currentVisiblePapers);
        if (statusEl) statusEl.textContent = active ? 'Marked as Weekly Pick.' : 'Removed from Weekly Picks.';
    } catch (e) {
        if (statusEl) statusEl.textContent = `Failed: ${e.message}`;
        const toggle = document.getElementById('weeklyPickToggle');
        if (toggle) toggle.checked = !active;
    }
};

function formatTeamNoteBody(text) {
    if (!text) return '';
    let safe = escapeHtml(text);
    safe = safe.replace(/@([A-Za-z0-9_.-]{2,})/g, '<span class="mention">@$1</span>');
    return safe;
}

async function loadTeamNotes(paperId) {
    const list = document.getElementById('teamNotesList');
    if (!list || !paperId) return;
    list.innerHTML = '<div class="loader"></div>';
    try {
        const res = await fetch(`${API_BASE}/papers/${encodeURIComponent(paperId)}/comments?limit=50`);
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Failed to load comments.");
        if (!Array.isArray(data) || data.length === 0) {
            list.textContent = 'No comments yet.';
            return;
        }
        list.innerHTML = data.map((c) => `
            <div class="team-note-item">
                <div class="team-note-meta">
                    <span class="team-note-author">${escapeHtml(c.author || 'Anonymous')}</span>
                    <span class="team-note-date">${escapeHtml(formatIsoShort(c.created_at))}</span>
                </div>
                <div class="team-note-body">${formatTeamNoteBody(c.body || '')}</div>
            </div>
        `).join('');
    } catch (e) {
        list.innerHTML = `<div style="color:var(--danger)">Failed to load comments: ${escapeHtml(e.message)}</div>`;
    }
}

window.addTeamNote = async () => {
    if (!activeNotesPaperId) return;
    const authorInput = document.getElementById('teamNoteAuthor');
    const bodyInput = document.getElementById('teamNoteBody');
    const author = authorInput ? authorInput.value.trim() : '';
    const body = bodyInput ? bodyInput.value.trim() : '';
    if (!body) {
        alert("Please write a comment.");
        return;
    }
    if (authorInput) {
        localStorage.setItem(TEAM_NOTE_AUTHOR_KEY, author);
    }
    try {
        const res = await fetch(`${API_BASE}/papers/${encodeURIComponent(activeNotesPaperId)}/comments`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ author, body })
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Failed to post comment.");
        if (bodyInput) bodyInput.value = '';
        await loadTeamNotes(activeNotesPaperId);
    } catch (e) {
        alert(`Failed to post comment: ${e.message}`);
    }
};

function setNotesTemplateStatus(message, isError = false) {
    const statusEl = document.getElementById('notesTemplateStatus');
    if (!statusEl) return;
    statusEl.textContent = message || '';
    statusEl.style.color = isError ? 'var(--danger)' : 'var(--text-muted)';
}

function renderNotesTemplateOptions() {
    const select = document.getElementById('notesTemplateSelect');
    if (!select) return;
    const items = Array.isArray(notesTemplatesCache) ? notesTemplatesCache : [];
    const currentValue = select.value || '';
    const options = ['<option value="">Select template...</option>'];
    items.forEach((tpl) => {
        const id = String(tpl.id || '').trim();
        const name = String(tpl.name || id || 'Template').trim();
        if (!id) return;
        options.push(`<option value="${escapeHtml(id)}">${escapeHtml(name)}</option>`);
    });
    select.innerHTML = options.join('');
    if (currentValue && items.some((tpl) => String(tpl.id || '') === currentValue)) {
        select.value = currentValue;
    }
}

async function loadNotesTemplates() {
    try {
        const res = await fetch(`${API_BASE}/notes/templates`);
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Failed to load templates");
        notesTemplatesCache = Array.isArray(data.templates) ? data.templates : [];
        renderNotesTemplateOptions();
    } catch (e) {
        setNotesTemplateStatus(`Templates unavailable: ${e.message}`, true);
    }
}

window.applyNotesTemplate = (append = false) => {
    const select = document.getElementById('notesTemplateSelect');
    const input = document.getElementById('notesInput');
    if (!select || !input) return;
    const templateId = String(select.value || '').trim();
    if (!templateId) {
        alert("Choose a template first.");
        return;
    }
    const template = (notesTemplatesCache || []).find((tpl) => String(tpl.id || '') === templateId);
    if (!template) {
        alert("Selected template not found.");
        return;
    }
    const body = String(template.body || '').trim();
    if (!body) return;
    if (append && input.value.trim()) {
        input.value = `${input.value.trim()}\n\n${body}\n`;
    } else {
        input.value = `${body}\n`;
    }
    setNotesTemplateStatus(`Applied template: ${template.name || template.id}`);
};

window.saveCurrentAsTemplate = async () => {
    const input = document.getElementById('notesInput');
    if (!input) return;
    const body = String(input.value || '').trim();
    if (!body) {
        alert("Write notes content before saving as a template.");
        return;
    }
    const name = (prompt("Template name:") || '').trim();
    if (!name) return;
    const templateId = reSafeTemplateId(name);
    const existing = Array.isArray(notesTemplatesCache) ? notesTemplatesCache : [];
    const next = existing.filter((tpl) => String(tpl.id || '') !== templateId);
    next.unshift({ id: templateId, name, body });
    try {
        const res = await fetch(`${API_BASE}/notes/templates`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ templates: next })
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Failed to save template");
        notesTemplatesCache = Array.isArray(data.templates) ? data.templates : [];
        renderNotesTemplateOptions();
        const select = document.getElementById('notesTemplateSelect');
        if (select) select.value = templateId;
        setNotesTemplateStatus(`Saved template: ${name}`);
    } catch (e) {
        setNotesTemplateStatus(`Save failed: ${e.message}`, true);
    }
};

function reSafeTemplateId(name) {
    const raw = String(name || '').toLowerCase().trim();
    const slug = raw.replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '');
    return slug || `template-${Date.now()}`;
}

window.insertAutoSummaryBlock = async () => {
    if (!activeNotesPaperId) return;
    const styleInput = document.getElementById('notesAutoSummaryStyle');
    const input = document.getElementById('notesInput');
    if (!input) return;
    const style = String(styleInput?.value || 'concise').toLowerCase();
    setNotesTemplateStatus('Generating auto-summary...');
    try {
        const res = await fetch(`${API_BASE}/papers/${encodeURIComponent(activeNotesPaperId)}/notes/auto-summary`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ style })
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Failed to generate auto-summary");
        const block = String(data.block || '').trim();
        if (!block) throw new Error("No summary block returned");
        input.value = input.value.trim()
            ? `${input.value.trim()}\n\n${block}\n`
            : `${block}\n`;
        setNotesTemplateStatus(`Inserted auto-summary (${style}).`);
    } catch (e) {
        setNotesTemplateStatus(`Auto-summary failed: ${e.message}`, true);
    }
};

window.openNotesModal = async (paperId) => {
    activeNotesPaperId = paperId;
    activeNotesUpdatedAt = '';
    recordTrail({ type: 'notes', paper_id: paperId, label: `Notes: ${getPaperTitleById(paperId)}` });
    const titleEl = document.getElementById('notesModalTitle');
    const input = document.getElementById('notesInput');
    const paper = (allPapers || []).find(p => p.id === paperId) || (currentVisiblePapers || []).find(p => p.id === paperId);
    if (titleEl) titleEl.textContent = paper ? paper.title : 'Notes';
    if (input) input.value = '';
    showModal('notesModal');
    const authorInput = document.getElementById('teamNoteAuthor');
    const bodyInput = document.getElementById('teamNoteBody');
    if (authorInput && !authorInput.value) {
        authorInput.value = localStorage.getItem(TEAM_NOTE_AUTHOR_KEY) || '';
    }
    if (bodyInput) bodyInput.value = '';
    const weeklyStatus = document.getElementById('weeklyPickStatus');
    if (weeklyStatus) weeklyStatus.textContent = '';
    updateWeeklyPickToggle(paperId);
    loadTeamNotes(paperId);
    loadPaperLinks(paperId);
    loadAssignments(paperId);
    const followStatus = document.getElementById('followupStatus');
    if (followStatus) followStatus.textContent = '';
    const assignmentStatus = document.getElementById('assignmentStatusLabel');
    if (assignmentStatus) assignmentStatus.textContent = '';
    setNotesTemplateStatus('');
    const followNote = document.getElementById('followupNoteInput');
    if (followNote) followNote.value = '';
    const followDays = document.getElementById('followupDaysInput');
    if (followDays && !followDays.value) followDays.value = '7';
    const assignmentAssignee = document.getElementById('assignmentAssigneeInput');
    if (assignmentAssignee && !assignmentAssignee.value) assignmentAssignee.value = '';
    const assignmentDueDays = document.getElementById('assignmentDueDaysInput');
    if (assignmentDueDays && !assignmentDueDays.value) assignmentDueDays.value = '7';
    const assignmentNote = document.getElementById('assignmentNoteInput');
    if (assignmentNote) assignmentNote.value = '';
    await loadNotesTemplates();

    try {
        const res = await fetch(`${API_BASE}/papers/${encodeURIComponent(paperId)}/notes`);
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Failed to load notes");
        if (input) input.value = data.notes || '';
        activeNotesUpdatedAt = data.updated_at || '';
    } catch (e) {
        if (input) input.value = '';
        activeNotesUpdatedAt = '';
    }
};

window.closeNotesModal = () => {
    hideModal('notesModal');
    activeNotesPaperId = null;
    activeNotesUpdatedAt = '';
};

window.saveNotes = async () => {
    if (!activeNotesPaperId) return;
    const input = document.getElementById('notesInput');
    const notes = input ? input.value : '';
    try {
        const res = await fetch(`${API_BASE}/papers/${encodeURIComponent(activeNotesPaperId)}/notes`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ notes, last_updated_at: activeNotesUpdatedAt })
        });
        const data = await res.json();
        if (!res.ok) {
            if (res.status === 409) {
                const current = data.current || {};
                if (input) input.value = current.notes || '';
                activeNotesUpdatedAt = current.updated_at || '';
                alert("Notes were updated elsewhere. Reloaded latest version.");
                return;
            }
            throw new Error(data.detail || "Failed to save notes");
        }
        updatePaperLocal(activeNotesPaperId, {
            has_notes: Boolean(data.notes && data.notes.trim().length > 0),
            notes_updated_at: data.updated_at,
        });
        activeNotesUpdatedAt = data.updated_at || activeNotesUpdatedAt;
        renderPaperGrid(currentVisiblePapers);
        closeNotesModal();
    } catch (e) {
        alert(`Failed to save notes: ${e.message}`);
    }
};

window.setFollowUp = async () => {
    if (!activeNotesPaperId) return;
    const daysInput = document.getElementById('followupDaysInput');
    const noteInput = document.getElementById('followupNoteInput');
    const statusEl = document.getElementById('followupStatus');
    const daysVal = daysInput ? Number(daysInput.value || 0) : 0;
    const days = Number.isFinite(daysVal) && daysVal > 0 ? Math.round(daysVal) : 7;
    const note = noteInput ? noteInput.value.trim() : '';
    if (statusEl) statusEl.textContent = 'Saving...';
    try {
        const res = await fetch(`${API_BASE}/papers/${encodeURIComponent(activeNotesPaperId)}/follow-ups`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ days, note })
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Failed to set follow-up");
        if (statusEl) statusEl.textContent = `Remind set for ${String(data.remind_at || '').slice(0, 10)}.`;
        await refreshFollowupsBadge();
    } catch (e) {
        if (statusEl) statusEl.textContent = `Failed: ${e.message}`;
    }
};

async function loadAssignments(paperId) {
    const list = document.getElementById('assignmentList');
    if (!list || !paperId) return;
    list.innerHTML = '<div class="loader"></div>';
    try {
        const res = await fetch(`${API_BASE}/papers/${encodeURIComponent(paperId)}/assignments?limit=80`);
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Failed to load assignments");
        const items = Array.isArray(data.items) ? data.items : [];
        if (!items.length) {
            list.textContent = 'No assignments yet.';
            return;
        }
        list.innerHTML = items.map((a) => `
            <div class="notes-history-item">
                <div class="notes-history-meta">
                    <span>@${escapeHtml(a.assignee || 'unknown')}</span>
                    <span>${escapeHtml(formatIsoShort(a.updated_at || a.created_at || ''))}</span>
                </div>
                <div style="display:flex; gap:0.45rem; align-items:center; flex-wrap:wrap; margin-top:0.25rem;">
                    <span class="tag">${escapeHtml(a.status || 'todo')}</span>
                    ${a.unread ? '<span class="tag" style="background:rgba(248,113,113,0.2); color:#fecaca;">unread</span>' : ''}
                    ${a.due_at ? `<span class="tag" style="background:rgba(56,189,248,0.15); color:#7dd3fc;">due ${escapeHtml(String(a.due_at).slice(0, 10))}</span>` : ''}
                </div>
                ${a.note ? `<div class="notes-history-preview">${escapeHtml(a.note)}</div>` : ''}
                <div class="notes-history-actions">
                    <select onchange="updateAssignmentStatus('${escapeHtml(String(a.id || ''))}', this.value)"
                        style="padding:0.35rem 0.45rem; background:rgba(255,255,255,0.05); border:1px solid rgba(255,255,255,0.2); color:white; border-radius:4px;">
                        <option value="todo" ${a.status === 'todo' ? 'selected' : ''}>todo</option>
                        <option value="in_progress" ${a.status === 'in_progress' ? 'selected' : ''}>in_progress</option>
                        <option value="blocked" ${a.status === 'blocked' ? 'selected' : ''}>blocked</option>
                        <option value="done" ${a.status === 'done' ? 'selected' : ''}>done</option>
                    </select>
                    <button class="btn-secondary" onclick="markAssignmentViewed('${escapeHtml(String(a.id || ''))}')">
                        <i class="fa-solid fa-eye"></i> Viewed
                    </button>
                </div>
            </div>
        `).join('');
    } catch (e) {
        list.innerHTML = `<div style="color:var(--danger)">Failed to load assignments: ${escapeHtml(e.message)}</div>`;
    }
}

window.addAssignment = async () => {
    if (!activeNotesPaperId) return;
    const assigneeInput = document.getElementById('assignmentAssigneeInput');
    const dueDaysInput = document.getElementById('assignmentDueDaysInput');
    const statusInput = document.getElementById('assignmentStatusInput');
    const noteInput = document.getElementById('assignmentNoteInput');
    const statusEl = document.getElementById('assignmentStatusLabel');
    const assignee = (assigneeInput?.value || '').trim();
    const dueDays = Number(dueDaysInput?.value || 0);
    const status = String(statusInput?.value || 'todo').toLowerCase();
    const note = (noteInput?.value || '').trim();
    if (!assignee) {
        alert("Assignee is required.");
        return;
    }
    if (statusEl) statusEl.textContent = 'Saving assignment...';
    try {
        const res = await fetch(`${API_BASE}/papers/${encodeURIComponent(activeNotesPaperId)}/assignments`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                assignee,
                due_in_days: Number.isFinite(dueDays) ? Math.max(0, Math.min(365, Math.round(dueDays))) : null,
                status,
                note,
            })
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Failed to create assignment");
        if (statusEl) statusEl.textContent = 'Assignment saved.';
        if (noteInput) noteInput.value = '';
        await loadAssignments(activeNotesPaperId);
        await loadPapers();
    } catch (e) {
        if (statusEl) statusEl.textContent = `Failed: ${e.message}`;
    }
};

window.updateAssignmentStatus = async (assignmentId, status) => {
    if (!assignmentId) return;
    const statusEl = document.getElementById('assignmentStatusLabel');
    if (statusEl) statusEl.textContent = 'Updating assignment...';
    try {
        const res = await fetch(`${API_BASE}/assignments/${encodeURIComponent(assignmentId)}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ status: String(status || 'todo').toLowerCase() })
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Failed to update assignment");
        if (statusEl) statusEl.textContent = 'Assignment updated.';
        if (activeNotesPaperId) await loadAssignments(activeNotesPaperId);
        await loadPapers();
    } catch (e) {
        if (statusEl) statusEl.textContent = `Update failed: ${e.message}`;
    }
};

window.markAssignmentViewed = async (assignmentId) => {
    if (!assignmentId) return;
    try {
        const res = await fetch(`${API_BASE}/assignments/${encodeURIComponent(assignmentId)}/viewed`, { method: 'POST' });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Failed to mark assignment viewed");
        if (activeNotesPaperId) await loadAssignments(activeNotesPaperId);
        await loadPapers();
    } catch (e) {
        alert(`Failed: ${e.message}`);
    }
};

async function loadPaperLinks(paperId) {
    const list = document.getElementById('paperLinksList');
    if (!list || !paperId) return;
    list.innerHTML = '<div class="loader"></div>';
    try {
        const res = await fetch(`${API_BASE}/papers/${encodeURIComponent(paperId)}/links?limit=50`);
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Failed to load links");
        if (!Array.isArray(data) || data.length === 0) {
            list.textContent = 'No links yet.';
            return;
        }
        list.innerHTML = data.map((link) => `
            <div class="notes-history-item">
                <div class="notes-history-meta">
                    <span>${escapeHtml(link.relation || 'linked')}</span>
                    <span>${escapeHtml(formatIsoShort(link.created_at))}</span>
                </div>
                <div class="notes-history-preview">${escapeHtml(link.other_title || link.other_id || '')}</div>
                ${link.note ? `<div style="font-size:0.85rem; color:var(--text-muted); margin-top:0.3rem;">${escapeHtml(link.note)}</div>` : ''}
                <div class="notes-history-actions">
                    <button class="btn-secondary" onclick="openNotesModal(decodeURIComponent('${encodeURIComponent(link.other_id || '')}'))">Open</button>
                    <button class="btn-secondary" onclick="deletePaperLink('${escapeHtml(link.id)}')"><i class="fa-solid fa-trash"></i> Remove</button>
                </div>
            </div>
        `).join('');
    } catch (e) {
        list.innerHTML = `<div style="color:var(--danger)">Failed to load links: ${escapeHtml(e.message)}</div>`;
    }
}

window.addPaperLink = async () => {
    if (!activeNotesPaperId) return;
    const targetInput = document.getElementById('paperLinkTarget');
    const relationInput = document.getElementById('paperLinkRelation');
    const noteInput = document.getElementById('paperLinkNote');
    const target = targetInput ? targetInput.value.trim() : '';
    const relation = relationInput ? relationInput.value : '';
    const note = noteInput ? noteInput.value.trim() : '';
    if (!target) {
        alert("Provide a paper ID or URL to link.");
        return;
    }
    try {
        const res = await fetch(`${API_BASE}/papers/${encodeURIComponent(activeNotesPaperId)}/links`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ related_id: target, relation, note })
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Failed to add link");
        if (targetInput) targetInput.value = '';
        if (noteInput) noteInput.value = '';
        await loadPaperLinks(activeNotesPaperId);
    } catch (e) {
        alert(`Failed to add link: ${e.message}`);
    }
};

window.deletePaperLink = async (linkId) => {
    if (!activeNotesPaperId || !linkId) return;
    const ok = confirm("Remove this link?");
    if (!ok) return;
    try {
        const res = await fetch(`${API_BASE}/papers/${encodeURIComponent(activeNotesPaperId)}/links/${encodeURIComponent(linkId)}`, {
            method: 'DELETE'
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Failed to remove link");
        await loadPaperLinks(activeNotesPaperId);
    } catch (e) {
        alert(`Failed to remove link: ${e.message}`);
    }
};

window.openNotesHistoryModal = async () => {
    if (!activeNotesPaperId) return;
    showModal('notesHistoryModal');
    await loadNotesHistory(activeNotesPaperId);
};

window.closeNotesHistoryModal = () => {
    hideModal('notesHistoryModal');
};

async function loadNotesHistory(paperId) {
    const list = document.getElementById('notesHistoryList');
    const diffBox = document.getElementById('notesDiffBox');
    if (diffBox) diffBox.classList.add('hidden');
    if (!list) return;
    list.innerHTML = '<div class="loader"></div>';
    try {
        const res = await fetch(`${API_BASE}/papers/${encodeURIComponent(paperId)}/notes/history?limit=20`);
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
        const items = Array.isArray(data) ? data : [];
        if (!items.length) {
            list.innerHTML = '<div style="color:var(--text-muted); padding:0.6rem;">No history yet.</div>';
            return;
        }
        list.innerHTML = items.map((h) => `
            <div class="notes-history-item">
                <div class="notes-history-meta">
                    <span>${escapeHtml(formatIsoShort(h.created_at))}</span>
                    <span>${Number(h.length || 0)} chars</span>
                </div>
                <div class="notes-history-preview">${escapeHtml(h.preview || '')}</div>
                <div class="notes-history-actions">
                    <button class="btn-secondary" onclick="showNotesDiff('${escapeHtml(h.id)}')"><i class="fa-solid fa-code-compare"></i> Diff</button>
                    <button class="btn-secondary" onclick="restoreNotesHistory('${escapeHtml(h.id)}')"><i class="fa-solid fa-rotate-left"></i> Restore</button>
                </div>
            </div>
        `).join('');
    } catch (e) {
        list.innerHTML = `<div style="color:var(--danger)">Failed to load history: ${escapeHtml(e.message)}</div>`;
    }
}

window.showNotesDiff = async (historyId) => {
    if (!activeNotesPaperId || !historyId) return;
    const diffBox = document.getElementById('notesDiffBox');
    const diffContent = document.getElementById('notesDiffContent');
    if (!diffBox || !diffContent) return;
    diffBox.classList.remove('hidden');
    diffContent.textContent = 'Loading diff...';
    try {
        const res = await fetch(`${API_BASE}/papers/${encodeURIComponent(activeNotesPaperId)}/notes/diff?history_id=${encodeURIComponent(historyId)}`);
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
        diffContent.textContent = data.diff || 'No diff.';
    } catch (e) {
        diffContent.textContent = `Failed to load diff: ${e.message}`;
    }
};

window.restoreNotesHistory = async (historyId) => {
    if (!activeNotesPaperId || !historyId) return;
    try {
        const res = await fetch(`${API_BASE}/papers/${encodeURIComponent(activeNotesPaperId)}/notes/history/${encodeURIComponent(historyId)}/restore`, {
            method: 'POST'
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Failed to restore notes");
        const input = document.getElementById('notesInput');
        if (input) input.value = data.notes || '';
        activeNotesUpdatedAt = data.updated_at || activeNotesUpdatedAt;
        updatePaperLocal(activeNotesPaperId, {
            has_notes: Boolean(data.notes && data.notes.trim().length > 0),
            notes_updated_at: data.updated_at,
        });
        renderPaperGrid(currentVisiblePapers);
        closeNotesHistoryModal();
    } catch (e) {
        alert(`Failed to restore notes: ${e.message}`);
    }
};

window.exportNotesToObsidian = async () => {
    if (!activeNotesPaperId) return;
    const input = document.getElementById('notesInput');
    const notes = input ? input.value : '';
    try {
        const res = await fetch(`${API_BASE}/export`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ paper_id: activeNotesPaperId, notes })
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Export failed");
        alert(`Saved to Obsidian: ${data.path}`);
    } catch (e) {
        alert(`Export Failed: ${e.message}\nCheck Vault Path in Settings.`);
    }
};

window.handleChatInput = (e) => {
    if (e.key === 'Enter') sendChat();
};

window.sendChat = async () => {
    const input = document.getElementById('chatInput');
    const query = input.value.trim();
    if (!query || !currentChatPaperId) return;

    // Add User Message
    addChatMessage('user', query);
    input.value = '';

    // Add Loading Message
    const loadingId = addChatMessage('system', '<i class="fa-solid fa-spinner fa-spin"></i> Thinking...');

    try {
        const res = await fetch(`${API_BASE}/chat`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                paper_id: currentChatPaperId,
                query: query
            })
        });

        const data = await res.json();

        // Remove loading
        document.getElementById(loadingId).remove();

        if (data.response) {
            addChatMessage('system', formatChatResponse(data.response));
        } else {
            addChatMessage('system', "Sorry, I couldn't get a response.");
        }

    } catch (e) {
        console.error(e);
        document.getElementById(loadingId).remove();
        addChatMessage('system', "Error: " + e.message);
    }
};

function addChatMessage(role, html) {
    const history = document.getElementById('chatHistory');
    const div = document.createElement('div');
    div.className = `chat-message ${role}`;
    const id = 'msg-' + Date.now();
    div.id = id;
    div.innerHTML = `<div class="message-content">${html}</div>`;
    history.appendChild(div);
    history.scrollTop = history.scrollHeight;
    return id;
}

function formatChatResponse(text) {
    // Simple markdown-ish to HTML
    // Bold
    let html = text.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
    // Headers
    html = html.replace(/^# (.*$)/gim, '<h1>$1</h1>');
    html = html.replace(/^## (.*$)/gim, '<h2>$1</h2>');
    html = html.replace(/^### (.*$)/gim, '<h3>$1</h3>');
    // Newlines
    // html = html.replace(/\n/g, '<br>'); // pre-wrap handles this
    return html;
}

// Morning Brief Logic
window.openBrief = async () => {
    showModal('briefModal');
    const content = document.getElementById('briefContent');
    content.innerHTML = '<div class="loader"></div><div style="text-align:center">Reading 5 unread papers...<br>Generating insights with Mistral...<br>(This takes ~15-30s)</div>';

    try {
        const res = await fetch(`${API_BASE}/brief`, { method: 'POST' });
        const data = await res.json();

        await ensureMarkdownLibs();
        const cachedNote = data.cached ? '<div style="font-size:0.82rem; color:var(--text-muted); margin-bottom:0.6rem;">Loaded from cache</div>' : '';
        const html = renderMarkdownSafe(data.brief || "No brief generated.");
        content.innerHTML = cachedNote + html;

    } catch (e) {
        console.error(e);
        content.innerHTML = '<div style="color:var(--danger)">Failed to generate brief. Check server/Ollama.</div>';
    }
};

window.playBrief = async () => {
    // Get text
    const content = document.getElementById('briefContent').innerText;
    if (content.includes("Loading") || content.length < 50) return;

    const btn = document.querySelector('button[onclick="playBrief()"]');
    const icon = btn.querySelector('i');

    const originalIcon = icon.className;
    const originalText = btn.innerHTML;

    btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Buffering...';
    btn.disabled = true;

    try {
        const res = await fetch(`${API_BASE}/podcast`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ text: content })
        });

        if (res.status !== 200) throw new Error("Audio generation failed");

        const blob = await res.blob();
        const url = URL.createObjectURL(blob);
        const audio = document.getElementById('briefAudio');
        audio.src = url;
        audio.play();

        btn.innerHTML = '<i class="fa-solid fa-stop"></i> Stop';
        btn.disabled = false;
        btn.onclick = () => {
            audio.pause();
            audio.currentTime = 0;
            btn.innerHTML = originalText;
            btn.onclick = window.playBrief;
            // Fix icon class
            const i = btn.querySelector('i');
            i.className = "fa-solid fa-headphones";
        };

        audio.onended = () => {
            btn.innerHTML = originalText;
            btn.onclick = window.playBrief;
        };

    } catch (e) {
        console.error(e);
        btn.innerHTML = '<i class="fa-solid fa-triangle-exclamation"></i> Error';
        setTimeout(() => {
            btn.innerHTML = originalText;
            btn.disabled = false;
        }, 3000);
    }
};

window.closeBriefModal = () => {
    const audio = document.getElementById('briefAudio');
    audio.pause();
    hideModal('briefModal');
};

window.openDigestModal = async () => {
    showModal('digestModal');
    await loadDigestInbox();
};

window.closeDigestModal = () => {
    hideModal('digestModal');
};

window.setDigestFilter = (cadence) => {
    digestFilterState.cadence = cadence || 'all';
    loadDigestInbox();
};

window.toggleDigestUnread = () => {
    digestFilterState.unreadOnly = !digestFilterState.unreadOnly;
    loadDigestInbox();
};

window.generateDigest = async (cadence = 'daily') => {
    const list = document.getElementById('digestInboxList');
    if (list) {
        list.innerHTML = '<div class="loader"></div>';
    }
    try {
        const res = await fetch(`${API_BASE}/digest/generate`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ cadence, force: true, max_items: 10 })
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Failed to generate digest.");
        await loadDigestInbox();
        await refreshAllBadges();
    } catch (e) {
        if (list) {
            list.innerHTML = `<div style="color:var(--danger)">Failed to generate digest: ${escapeHtml(e.message)}</div>`;
        }
    }
};

function renderDigestContributors(item) {
    const c = item && item.contributors ? item.contributors : null;
    if (!c) return '';
    const parts = [];
    if (Array.isArray(c.keywords) && c.keywords.length) {
        parts.push(`Keywords: ${c.keywords.slice(0, 4).join(', ')}`);
    }
    if (Array.isArray(c.authors) && c.authors.length) {
        parts.push(`Authors: ${c.authors.slice(0, 3).join(', ')}`);
    }
    if (c.citations && Number(c.citations) > 0) {
        parts.push(`Citations: ${Number(c.citations)}`);
    }
    if (c.code) {
        parts.push('Code repo');
    }
    if (!parts.length) return '';
    return `<div style="font-size:0.78rem; color:var(--text-muted); margin-top:0.15rem;">${escapeHtml(parts.join(' • '))}</div>`;
}

window.markDigestRead = async (digestId) => {
    try {
        const res = await fetch(`${API_BASE}/digest/${encodeURIComponent(digestId)}/read`, { method: 'POST' });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Failed to mark read.");
        await loadDigestInbox();
        await refreshAllBadges();
    } catch (e) {
        alert(`Failed to mark digest read: ${e.message}`);
    }
};

let currentShareToken = null;
let currentShareUrl = '';

function openShareLinkModal(url, token) {
    currentShareToken = token || null;
    currentShareUrl = url || '';
    const input = document.getElementById('shareLinkInput');
    if (input) input.value = currentShareUrl;
    const status = document.getElementById('shareLinkStatus');
    if (status) status.textContent = '';
    showModal('shareLinkModal');
    copyShareLink();
}

window.copyShareLink = async () => {
    if (!currentShareUrl) return;
    const status = document.getElementById('shareLinkStatus');
    try {
        if (navigator.clipboard) {
            await navigator.clipboard.writeText(currentShareUrl);
            if (status) status.textContent = "Link copied to clipboard.";
        } else if (status) {
            status.textContent = "Copy the link from the field above.";
        }
    } catch (e) {
        if (status) status.textContent = "Copy the link from the field above.";
    }
};

window.revokeShareLink = async () => {
    if (!currentShareToken) {
        const status = document.getElementById('shareLinkStatus');
        if (status) status.textContent = "No active share token.";
        return;
    }
    const status = document.getElementById('shareLinkStatus');
    try {
        const res = await fetch(`${API_BASE}/share/${encodeURIComponent(currentShareToken)}`, { method: 'DELETE' });
        if (!res.ok) throw new Error("Failed to revoke link.");
        currentShareToken = null;
        if (status) status.textContent = "Share link revoked.";
    } catch (e) {
        if (status) status.textContent = `Revoke failed: ${e.message}`;
    }
};

window.closeShareLinkModal = () => {
    hideModal('shareLinkModal');
};

window.shareDigest = async (digestId) => {
    try {
        const res = await fetch(`${API_BASE}/digest/${encodeURIComponent(digestId)}/share`, { method: 'POST' });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Failed to share digest.");
        const token = data.token;
        const url = `${window.location.origin}/share/${token}`;
        openShareLinkModal(url, token);
    } catch (e) {
        alert(`Failed to share digest: ${e.message}`);
    }
};

window.loadDigestInbox = async () => {
    const list = document.getElementById('digestInboxList');
    if (!list) return;
    list.innerHTML = '<div class="loader"></div>';

    try {
        const res = await fetch(`${API_BASE}/digest/runs?limit=20`);
        const runs = await res.json();
        if (!res.ok) throw new Error(runs.detail || `HTTP ${res.status}`);

        let filtered = Array.isArray(runs) ? runs : [];
        if (digestFilterState.cadence && digestFilterState.cadence !== 'all') {
            filtered = filtered.filter((r) => r.cadence === digestFilterState.cadence);
        }
        if (digestFilterState.unreadOnly) {
            filtered = filtered.filter((r) => r.unread);
        }

        if (!Array.isArray(filtered) || filtered.length === 0) {
            list.innerHTML = '<div style="text-align:center; color:var(--text-muted); padding:1rem;">No digests yet. Generate daily or weekly digest.</div>';
            return;
        }

        list.innerHTML = filtered.map((run) => {
            const tagColor = run.cadence === 'weekly' ? '#a78bfa' : '#38bdf8';
            const items = Array.isArray(run.items) ? run.items : [];
            const sourceTag = run.source_type === 'folder'
                ? `<span class="tag" style="background:rgba(14,165,233,0.15); color:#7dd3fc; border:1px solid rgba(125,211,252,0.35);">
                        ${escapeHtml(`Collection: ${run.source_name || 'Collection'}`)}
                   </span>`
                : '';
            const topItems = items.slice(0, 10).map((item) => `
                <li style="margin-bottom:0.45rem;">
                    <a href="${API_BASE}/papers/${encodeURIComponent(item.paper_id)}/pdf" target="_blank" class="pdf-link" style="font-weight:600;">
                        ${escapeHtml(item.title || item.paper_id)}
                    </a>
                    <div style="font-size:0.84rem; color:var(--text-muted); margin-top:0.15rem;">
                        ${escapeHtml(item.reason || '')}
                    </div>
                    ${renderDigestContributors(item)}
                </li>
            `).join('');

            return `
                <div style="border:1px solid rgba(255,255,255,0.12); border-radius:10px; padding:0.9rem; background:rgba(255,255,255,0.03);">
                    <div style="display:flex; justify-content:space-between; gap:0.8rem; align-items:flex-start;">
                        <div>
                            <div style="font-weight:700;">${escapeHtml(run.title || 'Digest')}</div>
                            <div style="font-size:0.84rem; color:var(--text-muted); margin-top:0.22rem;">
                                ${escapeHtml(run.created_at || '')}
                            </div>
                        </div>
                        <div style="display:flex; gap:0.4rem; align-items:center;">
                            ${run.unread ? '<span class="tag" style="background:rgba(239,68,68,0.2); color:#fca5a5;">unread</span>' : ''}
                            <span class="tag" style="background:rgba(255,255,255,0.08); color:${tagColor}; border:1px solid ${tagColor};">
                                ${escapeHtml(run.cadence || 'daily')}
                            </span>
                            ${sourceTag}
                        </div>
                    </div>
                    <div style="font-size:0.9rem; margin-top:0.55rem; line-height:1.5;">${escapeHtml(run.summary || '')}</div>
                    <details style="margin-top:0.6rem;">
                        <summary style="cursor:pointer; color:var(--text-muted);">Top picks (${Number(run.paper_count || items.length || 0)})</summary>
                        <ol style="margin:0.65rem 0 0 1.1rem; line-height:1.45;">${topItems || '<li>No picks</li>'}</ol>
                    </details>
                    <div style="display:flex; gap:0.5rem; margin-top:0.6rem;">
                        <button class="btn-secondary" onclick="markDigestRead(${Number(run.id)})" style="padding:0.35rem 0.75rem;">
                            <i class="fa-solid fa-check"></i> Mark Read
                        </button>
                        <button class="btn-secondary" onclick="shareDigest(${Number(run.id)})" style="padding:0.35rem 0.75rem;">
                            <i class="fa-solid fa-share-nodes"></i> Share
                        </button>
                    </div>
                </div>
            `;
        }).join('');
    } catch (e) {
        list.innerHTML = `<div style="color:var(--danger)">Failed to load digest inbox: ${escapeHtml(e.message)}</div>`;
    }
};

function sinceDateFromDays(days) {
    const span = Math.max(1, Math.min(180, Number(days || 30)));
    const d = new Date();
    d.setHours(0, 0, 0, 0);
    d.setDate(d.getDate() - (span - 1));
    return d.toISOString().slice(0, 10);
}

function getVersionUpdatesFiltersFromUi() {
    const scopeEl = document.getElementById('versionUpdatesScope');
    const daysEl = document.getElementById('versionUpdatesSinceDays');
    const includeEl = document.getElementById('versionUpdatesIncludeTriaged');
    const scope = String(scopeEl?.value || versionUpdatesState.scope || 'watchlist').toLowerCase();
    const sinceDays = Math.max(1, Math.min(180, Number(daysEl?.value || versionUpdatesState.sinceDays || 30)));
    const includeTriaged = Boolean(includeEl?.checked);
    return {
        scope: ['watchlist', 'liked', 'bookmarked', 'new'].includes(scope) ? scope : 'watchlist',
        sinceDays,
        includeTriaged,
        since: sinceDateFromDays(sinceDays),
    };
}

function setVersionUpdatesStatus(text, isError = false) {
    const el = document.getElementById('versionUpdatesStatus');
    if (!el) return;
    el.style.color = isError ? 'var(--danger)' : 'var(--text-muted)';
    el.textContent = text || '';
}

function renderVersionUpdatesInbox(payload) {
    const listEl = document.getElementById('versionUpdatesList');
    if (!listEl) return;
    const items = Array.isArray(payload?.items) ? payload.items : [];
    const activeCount = Number(payload?.active_count || 0);
    const totalCount = Number(payload?.total_count || items.length || 0);
    const triagedCount = Number(payload?.triaged_count || 0);
    setVersionUpdatesStatus(`Active ${activeCount} · Triaged ${triagedCount} · Total ${totalCount}`);

    if (!items.length) {
        listEl.innerHTML = '<div style="text-align:center; color:var(--text-muted); padding:1rem;">No version updates in this filter.</div>';
        return;
    }

    listEl.innerHTML = items.map((item) => {
        const baseId = String(item.arxiv_base_id || '');
        const paperId = String(item.paper_id || '');
        const latestId = String(item.latest_id || '');
        const title = String(item.paper_title || item.latest_title || paperId || baseId || 'Paper');
        const fromV = Number(item.from_version || 0);
        const toV = Number(item.to_version || 0);
        const published = String(item.published || '').slice(0, 10);
        const changed = Array.isArray(item.changed_structure_fields) ? item.changed_structure_fields : [];
        const triageActive = Boolean(item.triage_active);
        const triageStatus = String(item.triage_status || (triageActive ? 'active' : 'triaged'));
        const triageTag = triageActive
            ? '<span class="tag" style="background:rgba(14,165,233,0.16); color:#7dd3fc;">active</span>'
            : `<span class="tag" style="background:rgba(148,163,184,0.22); color:#cbd5e1;">${escapeHtml(triageStatus)}</span>`;
        const triageMeta = item.triage_snooze_until ? ` · snoozed until ${escapeHtml(String(item.triage_snooze_until))}` : '';
        const actions = triageActive
            ? `
                <button class="btn-secondary" onclick="applyVersionUpdateAction(decodeURIComponent('${encodeURIComponent(baseId)}'),'reviewed',decodeURIComponent('${encodeURIComponent(paperId)}'))" style="padding:0.3rem 0.65rem;">
                    <i class="fa-solid fa-check"></i> Reviewed
                </button>
                <button class="btn-secondary" onclick="applyVersionUpdateAction(decodeURIComponent('${encodeURIComponent(baseId)}'),'snooze',decodeURIComponent('${encodeURIComponent(paperId)}'))" style="padding:0.3rem 0.65rem;">
                    <i class="fa-solid fa-clock"></i> Snooze
                </button>
                <button class="btn-secondary" onclick="applyVersionUpdateAction(decodeURIComponent('${encodeURIComponent(baseId)}'),'dismiss',decodeURIComponent('${encodeURIComponent(paperId)}'))" style="padding:0.3rem 0.65rem;">
                    <i class="fa-solid fa-eye-slash"></i> Dismiss
                </button>
            `
            : `
                <button class="btn-secondary" onclick="applyVersionUpdateAction(decodeURIComponent('${encodeURIComponent(baseId)}'),'clear',decodeURIComponent('${encodeURIComponent(paperId)}'))" style="padding:0.3rem 0.65rem;">
                    <i class="fa-solid fa-rotate-left"></i> Reopen
                </button>
            `;
        return `
            <div style="border:1px solid rgba(255,255,255,0.12); border-radius:10px; padding:0.9rem; background:rgba(255,255,255,0.03);">
                <div style="display:flex; justify-content:space-between; gap:0.8rem; align-items:flex-start;">
                    <div>
                        <div style="font-weight:700;">${escapeHtml(title)}</div>
                        <div style="font-size:0.84rem; color:var(--text-muted); margin-top:0.25rem;">
                            ${escapeHtml(baseId || paperId)} · v${fromV} → v${toV}${published ? ` · ${escapeHtml(published)}` : ''}
                        </div>
                        <div style="font-size:0.8rem; color:var(--text-muted); margin-top:0.25rem;">
                            ${escapeHtml(triageStatus)}${triageMeta}
                        </div>
                    </div>
                    <div style="display:flex; gap:0.4rem; align-items:center;">
                        ${triageTag}
                        <span class="tag" style="background:rgba(16,185,129,0.15); color:#6ee7b7;">${Number(item.changed_count || changed.length)} fields</span>
                    </div>
                </div>
                ${changed.length ? `<div class="version-change-badges" style="margin-top:0.45rem;">${changed.map((name) => `<span class="tag version-change-tag">${escapeHtml(String(name))}</span>`).join('')}</div>` : ''}
                <div style="display:flex; gap:0.45rem; flex-wrap:wrap; margin-top:0.6rem;">
                    <button class="btn-secondary" onclick="openVersionModal(decodeURIComponent('${encodeURIComponent(paperId || latestId)}'))" style="padding:0.3rem 0.65rem;">
                        <i class="fa-solid fa-code-compare"></i> Diff
                    </button>
                    <button class="btn-secondary" onclick="openNotesModal(decodeURIComponent('${encodeURIComponent(paperId)}'))" style="padding:0.3rem 0.65rem;">
                        <i class="fa-solid fa-note-sticky"></i> Notes
                    </button>
                    ${actions}
                </div>
            </div>
        `;
    }).join('');
}

window.openVersionUpdatesModal = async () => {
    recordTrail({ type: 'version_updates', label: 'Version updates inbox' });
    showModal('versionUpdatesModal');
    const scopeEl = document.getElementById('versionUpdatesScope');
    const daysEl = document.getElementById('versionUpdatesSinceDays');
    const includeEl = document.getElementById('versionUpdatesIncludeTriaged');
    if (scopeEl) scopeEl.value = versionUpdatesState.scope || 'watchlist';
    if (daysEl) daysEl.value = String(versionUpdatesState.sinceDays || 30);
    if (includeEl) includeEl.checked = Boolean(versionUpdatesState.includeTriaged);
    await loadVersionUpdatesInbox(true);
};

window.closeVersionUpdatesModal = () => {
    hideModal('versionUpdatesModal');
};

window.loadVersionUpdatesInbox = async (refreshBadge = true) => {
    const listEl = document.getElementById('versionUpdatesList');
    if (listEl) listEl.innerHTML = '<div class="loader"></div>';
    try {
        const filters = getVersionUpdatesFiltersFromUi();
        versionUpdatesState = {
            scope: filters.scope,
            sinceDays: filters.sinceDays,
            includeTriaged: filters.includeTriaged,
        };
        setVersionUpdatesStatus('Loading version updates...');
        const params = new URLSearchParams();
        params.set('scope', filters.scope);
        params.set('since', filters.since);
        params.set('limit', '160');
        if (filters.includeTriaged) params.set('include_triaged', 'true');
        const res = await fetch(`${API_BASE}/version-updates?${params.toString()}`);
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Failed to load version updates");
        renderVersionUpdatesInbox(data);
        if (refreshBadge) await refreshVersionUpdatesBadge();
    } catch (e) {
        setVersionUpdatesStatus(`Failed to load updates: ${e.message}`, true);
        if (listEl) listEl.innerHTML = '';
    }
};

window.applyVersionUpdateAction = async (arxivBaseId, action, paperId = '') => {
    const baseId = String(arxivBaseId || '').trim();
    const act = String(action || '').toLowerCase().trim();
    if (!baseId || !['reviewed', 'snooze', 'dismiss', 'clear'].includes(act)) return;
    try {
        setVersionUpdatesStatus('Saving action...');
        const payload = {
            action: act,
            arxiv_base_id: baseId,
            paper_id: paperId || undefined,
        };
        if (act === 'snooze') payload.snooze_days = 3;
        const res = await fetch(`${API_BASE}/version-updates/action`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Failed to update version state");
        await loadVersionUpdatesInbox(true);
        await refreshAllBadges();
    } catch (e) {
        setVersionUpdatesStatus(`Failed to save action: ${e.message}`, true);
    }
};

function renderTrendTagRow(points, valueKey, color) {
    const rows = Array.isArray(points) ? points : [];
    if (!rows.length) return '<span style="color:var(--text-muted);">No trend data.</span>';
    return rows.slice(-7).map((row) => {
        const day = String(row?.date || '').slice(5);
        const value = Number(row?.[valueKey] || 0);
        return `<span class="tag" style="background:rgba(255,255,255,0.08); border:1px solid ${color}; color:${color};">${escapeHtml(day)} ${value}</span>`;
    }).join('');
}

function renderWeeklyReview(payload) {
    const container = document.getElementById('weeklyReviewContent');
    if (!container) return;
    if (!payload || typeof payload !== 'object') {
        container.innerHTML = '<div style="color:var(--text-muted);">No weekly review data.</div>';
        return;
    }
    const reading = payload.reading || {};
    const totals = reading.totals || {};
    const versions = payload.version_updates || {};
    const picks = payload.weekly_picks || {};
    const completed = Array.isArray(payload.top_completed) ? payload.top_completed : [];
    const activeUpdates = Array.isArray(versions.items) ? versions.items : [];
    const pickItems = Array.isArray(picks.items) ? picks.items : [];
    const trends = payload.trends || {};
    const readingTrend = Array.isArray(trends.reading) ? trends.reading : [];
    const versionTrend = Array.isArray(trends.version_updates) ? trends.version_updates : [];
    const picksTrend = Array.isArray(trends.weekly_picks) ? trends.weekly_picks : [];
    container.innerHTML = `
        <div style="font-weight:700; font-size:1.05rem;">${escapeHtml(payload.title || 'Weekly Review')}</div>
        <div style="color:var(--text-muted); font-size:0.86rem;">${escapeHtml(String(payload.start_date || ''))} → ${escapeHtml(String(payload.end_date || ''))}</div>
        <div style="line-height:1.5;">${escapeHtml(payload.summary || '')}</div>
        <div style="display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:0.6rem;">
            <div style="border:1px solid rgba(255,255,255,0.12); border-radius:10px; padding:0.7rem; background:rgba(255,255,255,0.03);">
                <div style="font-size:0.8rem; color:var(--text-muted);">Streak</div>
                <div style="margin-top:0.2rem; font-weight:700;">${Number(reading.streak_days || 0)} days</div>
            </div>
            <div style="border:1px solid rgba(255,255,255,0.12); border-radius:10px; padding:0.7rem; background:rgba(255,255,255,0.03);">
                <div style="font-size:0.8rem; color:var(--text-muted);">Completed</div>
                <div style="margin-top:0.2rem; font-weight:700;">${Number(totals.done_count || 0)}</div>
            </div>
            <div style="border:1px solid rgba(255,255,255,0.12); border-radius:10px; padding:0.7rem; background:rgba(255,255,255,0.03);">
                <div style="font-size:0.8rem; color:var(--text-muted);">Done Minutes</div>
                <div style="margin-top:0.2rem; font-weight:700;">${Number(totals.done_minutes || 0)}m</div>
            </div>
            <div style="border:1px solid rgba(255,255,255,0.12); border-radius:10px; padding:0.7rem; background:rgba(255,255,255,0.03);">
                <div style="font-size:0.8rem; color:var(--text-muted);">Active Updates</div>
                <div style="margin-top:0.2rem; font-weight:700;">${Number(versions.active_count || 0)}</div>
            </div>
        </div>
        <div style="border:1px solid rgba(255,255,255,0.12); border-radius:10px; padding:0.7rem; background:rgba(255,255,255,0.03);">
            <div style="font-weight:700; margin-bottom:0.45rem;">Trends (last 7 days)</div>
            <div style="display:flex; flex-direction:column; gap:0.45rem;">
                <div style="display:flex; flex-wrap:wrap; gap:0.35rem; align-items:center;">
                    <span style="font-size:0.8rem; color:var(--text-muted); min-width:120px;">Reading done:</span>
                    ${renderTrendTagRow(readingTrend, 'done_count', '#7dd3fc')}
                </div>
                <div style="display:flex; flex-wrap:wrap; gap:0.35rem; align-items:center;">
                    <span style="font-size:0.8rem; color:var(--text-muted); min-width:120px;">Version updates:</span>
                    ${renderTrendTagRow(versionTrend, 'count', '#60a5fa')}
                </div>
                <div style="display:flex; flex-wrap:wrap; gap:0.35rem; align-items:center;">
                    <span style="font-size:0.8rem; color:var(--text-muted); min-width:120px;">Weekly picks:</span>
                    ${renderTrendTagRow(picksTrend, 'count', '#a78bfa')}
                </div>
            </div>
        </div>
        <div style="display:grid; grid-template-columns:1fr 1fr 1fr; gap:0.7rem;">
            <div style="border:1px solid rgba(255,255,255,0.12); border-radius:10px; padding:0.7rem; background:rgba(255,255,255,0.03);">
                <div style="font-weight:700;">Top Completed</div>
                <ol style="margin:0.55rem 0 0 1.1rem; line-height:1.45;">
                    ${completed.length ? completed.map((item) => `<li>${escapeHtml(String(item.title || item.paper_id || ''))} · ${Number(item.done_minutes || 0)}m</li>`).join('') : '<li>No completed items logged.</li>'}
                </ol>
            </div>
            <div style="border:1px solid rgba(255,255,255,0.12); border-radius:10px; padding:0.7rem; background:rgba(255,255,255,0.03);">
                <div style="font-weight:700;">Version Updates</div>
                <ol style="margin:0.55rem 0 0 1.1rem; line-height:1.45;">
                    ${activeUpdates.length ? activeUpdates.map((item) => `<li>${escapeHtml(String(item.paper_title || item.paper_id || ''))} · v${Number(item.from_version || 0)}→v${Number(item.to_version || 0)}</li>`).join('') : '<li>No active updates.</li>'}
                </ol>
            </div>
            <div style="border:1px solid rgba(255,255,255,0.12); border-radius:10px; padding:0.7rem; background:rgba(255,255,255,0.03);">
                <div style="font-weight:700;">Weekly Picks</div>
                <ol style="margin:0.55rem 0 0 1.1rem; line-height:1.45;">
                    ${pickItems.length ? pickItems.map((item) => `<li>${escapeHtml(String(item.title || item.paper_id || ''))}</li>`).join('') : '<li>No weekly picks.</li>'}
                </ol>
            </div>
        </div>
    `;
}

window.openWeeklyReviewModal = async () => {
    recordTrail({ type: 'weekly_review', label: 'Weekly review' });
    showModal('weeklyReviewModal');
    const container = document.getElementById('weeklyReviewContent');
    if (container) container.innerHTML = '<div class="loader"></div>';
    await loadWeeklyReview();
};

window.closeWeeklyReviewModal = () => {
    hideModal('weeklyReviewModal');
};

window.loadWeeklyReview = async () => {
    try {
        const days = Math.max(1, Math.min(30, Number(weeklyReviewState.days || 7)));
        const res = await fetch(`${API_BASE}/weekly-review?days=${days}`);
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Failed to load weekly review");
        renderWeeklyReview(data);
    } catch (e) {
        const container = document.getElementById('weeklyReviewContent');
        if (container) container.innerHTML = `<div style="color:var(--danger)">Failed to load weekly review: ${escapeHtml(e.message)}</div>`;
    }
};

window.shareWeeklyReview = async () => {
    try {
        const days = Math.max(1, Math.min(30, Number(weeklyReviewState.days || 7)));
        const res = await fetch(`${API_BASE}/weekly-review/share?days=${days}`, { method: 'POST' });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Failed to share weekly review.");
        const token = data.token;
        const url = `${window.location.origin}/share/${token}`;
        openShareLinkModal(url, token);
    } catch (e) {
        alert(`Failed to share weekly review: ${e.message}`);
    }
};

function setUnifiedInboxStatus(text, isError = false) {
    const el = document.getElementById('unifiedInboxStatus');
    if (!el) return;
    el.style.color = isError ? 'var(--danger)' : 'var(--text-muted)';
    el.textContent = text || '';
}

function encodeInboxPayload(payload) {
    try {
        return encodeURIComponent(JSON.stringify(payload || {}));
    } catch (e) {
        return encodeURIComponent('{}');
    }
}

function decodeInboxPayload(payloadJson) {
    if (!payloadJson) return {};
    try {
        return JSON.parse(payloadJson);
    } catch (e) {
        return {};
    }
}

function setUnifiedInboxControlsFromState() {
    const scopeEl = document.getElementById('unifiedInboxScope');
    const daysEl = document.getElementById('unifiedInboxDays');
    const limitEl = document.getElementById('unifiedInboxLimit');
    const sortEl = document.getElementById('unifiedInboxSort');
    const viewEl = document.getElementById('unifiedInboxViewMode');
    const focusEl = document.getElementById('unifiedInboxFocusLimit');
    if (scopeEl) scopeEl.value = unifiedInboxState.versionScope || 'watchlist';
    if (daysEl) daysEl.value = String(unifiedInboxState.versionDays || 30);
    if (limitEl) limitEl.value = String(unifiedInboxState.limit || 80);
    if (sortEl) sortEl.value = unifiedInboxState.sort || 'recent';
    if (viewEl) viewEl.value = unifiedInboxState.viewMode || 'all';
    if (focusEl) focusEl.value = String(unifiedInboxState.focusLimit || 12);
    const kinds = new Set((unifiedInboxState.kinds || []).map((k) => String(k).toLowerCase()));
    const checks = [
        ['unifiedInboxKindAlert', 'alert'],
        ['unifiedInboxKindVersion', 'version_update'],
        ['unifiedInboxKindFollowup', 'follow_up'],
        ['unifiedInboxKindDigest', 'digest'],
    ];
    checks.forEach(([id, kind]) => {
        const el = document.getElementById(id);
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
        .filter(([id]) => Boolean(document.getElementById(id)?.checked))
        .map(([, kind]) => kind);
}

function readUnifiedInboxFiltersFromUi() {
    const scopeEl = document.getElementById('unifiedInboxScope');
    const daysEl = document.getElementById('unifiedInboxDays');
    const limitEl = document.getElementById('unifiedInboxLimit');
    const sortEl = document.getElementById('unifiedInboxSort');
    const viewEl = document.getElementById('unifiedInboxViewMode');
    const focusEl = document.getElementById('unifiedInboxFocusLimit');
    const rawScope = String(scopeEl?.value || unifiedInboxState.versionScope || 'watchlist').toLowerCase();
    const versionScope = ['watchlist', 'liked', 'bookmarked', 'new'].includes(rawScope) ? rawScope : 'watchlist';
    const versionDays = Math.max(1, Math.min(180, Number(daysEl?.value || unifiedInboxState.versionDays || 30)));
    const limit = Math.max(10, Math.min(200, Number(limitEl?.value || unifiedInboxState.limit || 80)));
    const sort = String(sortEl?.value || unifiedInboxState.sort || 'recent').toLowerCase() === 'priority' ? 'priority' : 'recent';
    const viewMode = String(viewEl?.value || unifiedInboxState.viewMode || 'all').toLowerCase() === 'focus' ? 'focus' : 'all';
    const focusLimit = Math.max(1, Math.min(80, Number(focusEl?.value || unifiedInboxState.focusLimit || 12)));
    const kinds = getUnifiedInboxKindsFromUi();
    return { versionScope, versionDays, limit, kinds, sort, viewMode, focusLimit };
}

window.toggleUnifiedInboxKinds = (checked) => {
    ['unifiedInboxKindAlert', 'unifiedInboxKindVersion', 'unifiedInboxKindFollowup', 'unifiedInboxKindDigest']
        .forEach((id) => {
            const el = document.getElementById(id);
            if (el) el.checked = Boolean(checked);
        });
    refreshUnifiedInbox();
};

function buildUnifiedInboxSelectionItem(item) {
    const kind = String(item?.kind || '');
    const payload = {
        id: String(item?.id || ''),
        kind,
        alert_id: item?.alert_id != null ? Number(item.alert_id) : null,
        follow_id: item?.follow_id != null ? String(item.follow_id) : null,
        digest_id: item?.digest_id != null ? Number(item.digest_id) : null,
        paper_id: item?.paper_id != null ? String(item.paper_id) : null,
        arxiv_base_id: item?.arxiv_base_id != null ? String(item.arxiv_base_id) : null,
    };
    return payload;
}

function updateUnifiedInboxSelectionUi() {
    const count = unifiedInboxSelectedItems.size;
    const countEl = document.getElementById('unifiedInboxSelectionCount');
    if (countEl) countEl.textContent = `${count} selected`;
    const allBox = document.getElementById('unifiedInboxSelectAll');
    if (allBox) {
        const visible = (unifiedInboxVisibleItems || []).length;
        allBox.checked = visible > 0 && count > 0 && count >= visible;
        allBox.indeterminate = count > 0 && count < visible;
    }
}

window.toggleUnifiedInboxItemSelection = (payloadJson, checked) => {
    const payload = decodeInboxPayload(payloadJson);
    const key = String(payload.id || '');
    if (!key) return;
    if (checked) {
        unifiedInboxSelectedItems.set(key, payload);
    } else {
        unifiedInboxSelectedItems.delete(key);
    }
    updateUnifiedInboxSelectionUi();
};

window.clearUnifiedInboxSelection = () => {
    unifiedInboxSelectedItems.clear();
    updateUnifiedInboxSelectionUi();
    document.querySelectorAll('.unified-inbox-item-check').forEach((el) => {
        el.checked = false;
    });
};

window.toggleUnifiedInboxSelectAll = (checked) => {
    const want = Boolean(checked);
    if (!want) {
        clearUnifiedInboxSelection();
        return;
    }
    (unifiedInboxVisibleItems || []).forEach((item) => {
        const payload = buildUnifiedInboxSelectionItem(item);
        const key = String(payload.id || '');
        if (key) unifiedInboxSelectedItems.set(key, payload);
    });
    document.querySelectorAll('.unified-inbox-item-check').forEach((el) => {
        el.checked = true;
    });
    updateUnifiedInboxSelectionUi();
};

function normalizeUnifiedBulkAction(value) {
    const action = String(value || '').trim().toLowerCase();
    if (!action) return '';
    if (['seen', 'reviewed', 'dismiss', 'snooze', 'done', 'read'].includes(action)) return action;
    return '';
}

window.applyUnifiedInboxBulkAction = async () => {
    const statusEl = document.getElementById('unifiedInboxStatus');
    const selected = Array.from(unifiedInboxSelectedItems.values());
    if (!selected.length) {
        setUnifiedInboxStatus('Select at least one inbox item first.', true);
        return;
    }
    const actionEl = document.getElementById('unifiedInboxBulkAction');
    const snoozeEl = document.getElementById('unifiedInboxBulkSnoozeDays');
    const action = normalizeUnifiedBulkAction(actionEl?.value || '');
    const snoozeDays = Math.max(1, Math.min(90, Number(snoozeEl?.value || 3)));
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
        const res = await fetch(`${API_BASE}/inbox/bulk-action`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Failed to apply bulk inbox action");
        const success = Number(data.success_count || 0);
        const failure = Number(data.failure_count || 0);
        setUnifiedInboxStatus(`Bulk action finished: ${success} succeeded, ${failure} failed.`);
        clearUnifiedInboxSelection();
        await refreshUnifiedInbox();
        await refreshAllBadges({ force: true });
    } catch (e) {
        setUnifiedInboxStatus(`Bulk action failed: ${e.message}`, true);
    }
};

function renderUnifiedInbox(payload) {
    const list = document.getElementById('unifiedInboxList');
    if (!list) return;
    const counts = payload && payload.counts ? payload.counts : {};
    const total = Number(payload?.total || 0);
    const items = Array.isArray(payload?.items) ? payload.items : [];
    unifiedInboxVisibleItems = items.slice();
    const visibleIds = new Set(items.map((item) => String(item?.id || '')).filter(Boolean));
    Array.from(unifiedInboxSelectedItems.keys()).forEach((id) => {
        if (!visibleIds.has(id)) unifiedInboxSelectedItems.delete(id);
    });
    setUnifiedInboxStatus(
        `Total ${total} · Alerts ${Number(counts.alerts || 0)} · Versions ${Number(counts.version_updates || 0)} · Follow-ups ${Number(counts.follow_ups || 0)} · Digests ${Number(counts.digests || 0)}`
    );
    if (!items.length) {
        list.innerHTML = '<div style="text-align:center; color:var(--text-muted); padding:1rem;">Inbox is clear.</div>';
        updateUnifiedInboxSelectionUi();
        return;
    }

    list.innerHTML = items.map((item) => {
        const kind = String(item.kind || '');
        const title = String(item.title || item.paper_id || kind || 'Inbox item');
        const ts = String(item.remind_at || item.created_at || item.published || '');
        const priorityScore = Math.max(0, Number(item.priority_score || 0));
        const priorityReason = String(item.priority_reason || '').trim();
        const selectionPayload = buildUnifiedInboxSelectionItem(item);
        const selectionKey = String(selectionPayload.id || '');
        const selectionJson = encodeInboxPayload(selectionPayload);
        const checked = selectionKey && unifiedInboxSelectedItems.has(selectionKey) ? 'checked' : '';
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
            meta = `${escapeHtml(String(item.alert_type || 'alert'))}${ts ? ` · ${escapeHtml(ts.slice(0, 16).replace('T', ' '))}` : ''}`;
            details = item.message ? `<div style="font-size:0.88rem; color:var(--text-muted); margin-top:0.35rem;">${escapeHtml(String(item.message))}</div>` : '';
            const payloadSeen = encodeInboxPayload({ alert_id: Number(item.alert_id || 0) });
            actions = `
                ${item.paper_id ? `<button class="btn-secondary" onclick="openNotesModal(decodeURIComponent('${encodeURIComponent(String(item.paper_id || ''))}'))" style="padding:0.3rem 0.65rem;"><i class="fa-solid fa-note-sticky"></i> Notes</button>` : ''}
                ${item.alert_type === 'version' && item.paper_id ? `<button class="btn-secondary" onclick="openVersionModal(decodeURIComponent('${encodeURIComponent(String(item.paper_id || ''))}'))" style="padding:0.3rem 0.65rem;"><i class="fa-solid fa-code-compare"></i> Diff</button>` : ''}
                <button class="btn-secondary" onclick="applyUnifiedInboxAction('alert','seen',decodeURIComponent('${payloadSeen}'))" style="padding:0.3rem 0.65rem;"><i class="fa-solid fa-eye"></i> Mark Seen</button>
            `;
        } else if (kind === 'version_update') {
            meta = `v${Number(item.from_version || 0)} → v${Number(item.to_version || 0)}${ts ? ` · ${escapeHtml(ts.slice(0, 10))}` : ''}`;
            const changed = Array.isArray(item.changed_structure_fields) ? item.changed_structure_fields : [];
            details = changed.length
                ? `<div class="version-change-badges" style="margin-top:0.35rem;">${changed.slice(0, 6).map((name) => `<span class="tag version-change-tag">${escapeHtml(String(name))}</span>`).join('')}</div>`
                : '';
            const payloadReviewed = encodeInboxPayload({ arxiv_base_id: item.arxiv_base_id, paper_id: item.paper_id });
            const payloadSnooze = encodeInboxPayload({ arxiv_base_id: item.arxiv_base_id, paper_id: item.paper_id, snooze_days: 3 });
            const payloadDismiss = encodeInboxPayload({ arxiv_base_id: item.arxiv_base_id, paper_id: item.paper_id });
            actions = `
                <button class="btn-secondary" onclick="openVersionModal(decodeURIComponent('${encodeURIComponent(String(item.paper_id || item.latest_id || ''))}'))" style="padding:0.3rem 0.65rem;"><i class="fa-solid fa-code-compare"></i> Diff</button>
                <button class="btn-secondary" onclick="applyUnifiedInboxAction('version_update','reviewed',decodeURIComponent('${payloadReviewed}'))" style="padding:0.3rem 0.65rem;"><i class="fa-solid fa-check"></i> Reviewed</button>
                <button class="btn-secondary" onclick="applyUnifiedInboxAction('version_update','snooze',decodeURIComponent('${payloadSnooze}'))" style="padding:0.3rem 0.65rem;"><i class="fa-solid fa-clock"></i> Snooze</button>
                <button class="btn-secondary" onclick="applyUnifiedInboxAction('version_update','dismiss',decodeURIComponent('${payloadDismiss}'))" style="padding:0.3rem 0.65rem;"><i class="fa-solid fa-eye-slash"></i> Dismiss</button>
            `;
        } else if (kind === 'follow_up') {
            meta = `${ts ? `Due ${escapeHtml(ts.slice(0, 16).replace('T', ' '))}` : 'Due now'}`;
            details = item.note ? `<div style="font-size:0.88rem; color:var(--text-muted); margin-top:0.35rem;">${escapeHtml(String(item.note))}</div>` : '';
            const payloadDone = encodeInboxPayload({ follow_id: item.follow_id });
            const payloadSnooze = encodeInboxPayload({ follow_id: item.follow_id, snooze_days: 3 });
            actions = `
                ${item.paper_id ? `<button class="btn-secondary" onclick="openNotesModal(decodeURIComponent('${encodeURIComponent(String(item.paper_id || ''))}'))" style="padding:0.3rem 0.65rem;"><i class="fa-solid fa-note-sticky"></i> Notes</button>` : ''}
                <button class="btn-secondary" onclick="applyUnifiedInboxAction('follow_up','done',decodeURIComponent('${payloadDone}'))" style="padding:0.3rem 0.65rem;"><i class="fa-solid fa-check"></i> Done</button>
                <button class="btn-secondary" onclick="applyUnifiedInboxAction('follow_up','snooze',decodeURIComponent('${payloadSnooze}'))" style="padding:0.3rem 0.65rem;"><i class="fa-solid fa-clock"></i> Snooze</button>
            `;
        } else if (kind === 'digest') {
            meta = `${escapeHtml(String(item.cadence || 'daily'))}${ts ? ` · ${escapeHtml(ts.slice(0, 16).replace('T', ' '))}` : ''}`;
            details = item.summary ? `<div style="font-size:0.88rem; color:var(--text-muted); margin-top:0.35rem;">${escapeHtml(String(item.summary))}</div>` : '';
            const payloadRead = encodeInboxPayload({ digest_id: Number(item.digest_id || 0) });
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

window.openUnifiedInboxModal = async () => {
    recordTrail({ type: 'unified_inbox', label: 'Unified inbox' });
    showModal('unifiedInboxModal');
    setUnifiedInboxControlsFromState();
    syncDayRunControlsFromTopBar();
    setDayRunStatus('');
    await loadDayRunPresets();
    await loadDayRunHistory();
    await refreshUnifiedInbox();
};

window.closeUnifiedInboxModal = () => {
    hideModal('unifiedInboxModal');
};

window.refreshUnifiedInbox = async () => {
    const list = document.getElementById('unifiedInboxList');
    if (list) list.innerHTML = '<div class="loader"></div>';
    setUnifiedInboxStatus('Loading inbox...');
    try {
        const filters = readUnifiedInboxFiltersFromUi();
        unifiedInboxState = {
            versionScope: filters.versionScope,
            versionDays: filters.versionDays,
            limit: filters.limit,
            kinds: filters.kinds,
            sort: filters.sort,
            viewMode: filters.viewMode,
            focusLimit: filters.focusLimit,
        };
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
        if (filters.kinds?.length) {
            params.set('kinds', filters.kinds.join(','));
        }
        const res = await fetch(`${API_BASE}${endpoint}?${params.toString()}`);
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Failed to load unified inbox");
        renderUnifiedInbox(data);
        await refreshUnifiedInboxBadge();
    } catch (e) {
        setUnifiedInboxStatus(`Failed to load inbox: ${e.message}`, true);
        if (list) list.innerHTML = '';
    }
};

window.applyUnifiedInboxAction = async (kind, action, payloadJson = '{}') => {
    try {
        const extra = decodeInboxPayload(payloadJson || '{}');
        const body = { kind, action, ...(extra || {}) };
        const res = await fetch(`${API_BASE}/inbox/action`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Failed to apply inbox action");
        await refreshUnifiedInbox();
        await refreshAllBadges({ force: true });
    } catch (e) {
        setUnifiedInboxStatus(`Action failed: ${e.message}`, true);
    }
};

window.openAlertsModal = async () => {
    showModal('alertsModal');
    const container = document.getElementById('alertsList');
    if (container) container.innerHTML = '<div class="loader"></div>';

    try {
        const res = await fetch(`${API_BASE}/alerts?limit=100`);
        const data = await res.json();
        renderAlertCards(data);
    } catch (e) {
        if (container) container.innerHTML = `<div style="color:var(--danger)">Failed to load alerts: ${e.message}</div>`;
    }
};

window.closeAlertsModal = () => {
    hideModal('alertsModal');
};

window.markAllAlertsSeen = async () => {
    try {
        await fetch(`${API_BASE}/alerts/mark-seen`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ ids: null })
        });
        await refreshAllBadges();
        await openAlertsModal();
    } catch (e) {
        console.error(e);
        alert("Failed to mark alerts as seen.");
    }
};

window.openMentionsModal = async () => {
    showModal('mentionsModal');
    const input = document.getElementById('mentionHandleInput');
    const handle = getMentionHandle();
    if (input && !input.value) {
        input.value = handle ? `@${handle.replace(/^@+/, '')}` : '';
    }
    await loadMentionsInbox();
};

window.closeMentionsModal = () => {
    hideModal('mentionsModal');
};

window.saveMentionHandle = async () => {
    const input = document.getElementById('mentionHandleInput');
    const status = document.getElementById('mentionHandleStatus');
    const raw = input ? input.value.trim() : '';
    const clean = raw.replace(/^@+/, '').trim();
    if (!clean) {
        localStorage.removeItem(MENTION_HANDLE_KEY);
        if (status) status.textContent = 'Handle cleared.';
        await refreshMentionsBadge();
        return;
    }
    localStorage.setItem(MENTION_HANDLE_KEY, clean);
    loadMentionReadSet(clean);
    if (status) status.textContent = `Watching @${clean}`;
    await loadMentionsInbox();
    await refreshMentionsBadge();
};

window.markAllMentionsRead = async () => {
    const handle = getMentionHandle();
    if (!handle) return;
    mentionsCache.forEach((m) => {
        if (m && m.id) mentionReadSet.add(m.id);
    });
    saveMentionReadSet(handle);
    await refreshMentionsBadge();
    await loadMentionsInbox();
};

async function loadMentionsInbox() {
    const list = document.getElementById('mentionsList');
    const status = document.getElementById('mentionHandleStatus');
    if (!list) return;
    const handle = getMentionHandle();
    if (!handle) {
        list.innerHTML = '<div style="color:var(--text-muted); padding:0.8rem;">Set your @handle to see mentions.</div>';
        if (status) status.textContent = '';
        return;
    }
    if (status) status.textContent = `Watching @${handle}`;
    list.innerHTML = '<div class="loader"></div>';
    loadMentionReadSet(handle);
    try {
        const res = await fetch(`${API_BASE}/mentions?handle=${encodeURIComponent(handle)}&limit=50`);
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
        const items = Array.isArray(data) ? data : [];
        mentionsCache = items;
        if (!items.length) {
            list.innerHTML = '<div style="color:var(--text-muted); padding:0.8rem;">No mentions yet.</div>';
            return;
        }
        list.innerHTML = items.map((m) => {
            const unread = m && m.id && !mentionReadSet.has(m.id);
            const title = m.title || m.paper_id || 'Paper';
            return `
                <div class="mention-item">
                    <div class="mention-meta">
                        <span>@${escapeHtml(handle)} · ${escapeHtml(m.author || 'Anonymous')}</span>
                        <span>${escapeHtml(formatIsoShort(m.created_at))}</span>
                    </div>
                    <div class="mention-body">${formatTeamNoteBody(m.body || '')}</div>
                    <div style="font-size:0.8rem; color:var(--text-muted); margin-top:0.4rem;">
                        ${escapeHtml(title)}
                    </div>
                    <div style="display:flex; gap:0.5rem; margin-top:0.5rem; align-items:center;">
                        <button class="btn-secondary" onclick="openNotesModal(decodeURIComponent('${encodeURIComponent(m.paper_id || '')}'))">Open Notes</button>
                        ${unread ? '<span class="tag" style="background:rgba(239,68,68,0.2); color:#fca5a5;">new</span>' : ''}
                    </div>
                </div>
            `;
        }).join('');
    } catch (e) {
        list.innerHTML = `<div style="color:var(--danger)">Failed to load mentions: ${escapeHtml(e.message)}</div>`;
    }
}

window.openFollowupsModal = async () => {
    showModal('followupsModal');
    await refreshFollowups();
};

window.closeFollowupsModal = () => {
    hideModal('followupsModal');
};

window.refreshFollowups = async () => {
    const list = document.getElementById('followupsList');
    if (!list) return;
    list.innerHTML = '<div class="loader"></div>';
    try {
        const res = await fetch(`${API_BASE}/follow-ups?due_only=true&limit=100`);
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
        const items = Array.isArray(data) ? data : [];
        if (!items.length) {
            list.innerHTML = '<div style="color:var(--text-muted); padding:0.8rem;">No follow-ups due.</div>';
            await refreshFollowupsBadge();
            return;
        }
        list.innerHTML = items.map((f) => `
            <div class="followup-item">
                <div class="followup-meta">
                    <span>${escapeHtml(String(f.remind_at || '').slice(0, 10))}</span>
                    <span>${escapeHtml(formatIsoShort(f.created_at))}</span>
                </div>
                <div class="followup-title">${escapeHtml(f.title || f.paper_id || 'Paper')}</div>
                ${f.note ? `<div class="followup-note">${escapeHtml(f.note)}</div>` : ''}
                <div style="display:flex; gap:0.5rem; margin-top:0.5rem;">
                    <button class="btn-secondary" onclick="openNotesModal(decodeURIComponent('${encodeURIComponent(f.paper_id || '')}'))">Open Notes</button>
                    <button class="btn-secondary" onclick="markFollowupDone('${escapeHtml(f.id)}')"><i class="fa-solid fa-check"></i> Done</button>
                    <button class="btn-secondary" onclick="snoozeFollowup('${escapeHtml(f.id)}', 3)"><i class="fa-solid fa-clock"></i> Snooze 3d</button>
                </div>
            </div>
        `).join('');
        await refreshFollowupsBadge();
    } catch (e) {
        list.innerHTML = `<div style="color:var(--danger)">Failed to load follow-ups: ${escapeHtml(e.message)}</div>`;
    }
};

window.markFollowupDone = async (followId) => {
    if (!followId) return;
    try {
        const res = await fetch(`${API_BASE}/follow-ups/${encodeURIComponent(followId)}/done`, { method: 'POST' });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Failed to mark done");
        await refreshFollowups();
        await refreshAllBadges();
    } catch (e) {
        alert(`Failed to mark done: ${e.message}`);
    }
};

window.snoozeFollowup = async (followId, days = 3) => {
    if (!followId) return;
    try {
        const span = Math.max(1, Math.min(90, Number(days || 3)));
        const res = await fetch(`${API_BASE}/follow-ups/${encodeURIComponent(followId)}/snooze`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ days: span }),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Failed to snooze follow-up");
        await refreshFollowups();
        await refreshAllBadges();
    } catch (e) {
        alert(`Failed to snooze follow-up: ${e.message}`);
    }
};

async function refreshFollowupsBadge() {
    const badge = document.getElementById('followupsBadge');
    if (!badge) return;
    try {
        const res = await fetch(`${API_BASE}/follow-ups/count`);
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
        renderCountBadge(badge, Number(data.due || 0));
    } catch (e) {
        badge.style.display = 'none';
        badge.textContent = '0';
    }
}

window.openSearchAgentsModal = async () => {
    showModal('searchAgentsModal');
    const queryInput = document.getElementById('agentQueryInput');
    const searchInput = document.getElementById('searchInput');
    if (queryInput && !queryInput.value.trim() && searchInput && searchInput.value.trim()) {
        queryInput.value = searchInput.value.trim();
    }
    const summaryBox = document.getElementById('searchAgentRunSummary');
    if (summaryBox) {
        summaryBox.style.display = 'none';
        summaryBox.innerHTML = '';
    }
    updateSearchAgentFormUi();
    await loadSearchAgents();
};

window.closeSearchAgentsModal = () => {
    hideModal('searchAgentsModal');
};

function escapeHtml(value) {
    return String(value || '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function renderMarkdownSafe(markdown) {
    const source = String(markdown || '');
    const rendered = (typeof marked !== 'undefined' && typeof marked.parse === 'function')
        ? marked.parse(source)
        : escapeHtml(source).replace(/\n/g, '<br>');
    if (typeof DOMPurify !== 'undefined' && typeof DOMPurify.sanitize === 'function') {
        return DOMPurify.sanitize(rendered);
    }
    return rendered;
}

function sleep(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
}

function formatJobEta(seconds) {
    const sec = Number(seconds);
    if (!Number.isFinite(sec) || sec <= 0) return 'soon';
    if (sec < 60) return `${Math.round(sec)}s`;
    const mins = Math.round(sec / 60);
    if (mins < 60) return `${mins}m`;
    const hours = Math.round(mins / 60);
    return `${hours}h`;
}

async function submitJob(endpoint, payload = null) {
    const options = { method: 'POST' };
    if (payload !== null) {
        options.headers = { 'Content-Type': 'application/json' };
        options.body = JSON.stringify(payload);
    }
    const res = await fetch(`${API_BASE}${endpoint}`, options);
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || `Job submission failed (${res.status})`);
    if (!data.job_id) throw new Error("Server did not return job id.");
    return data.job_id;
}

async function requestJobCancel(jobId) {
    const res = await fetch(`${API_BASE}/jobs/${encodeURIComponent(jobId)}/cancel`, { method: 'POST' });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || `Failed to cancel job (${res.status})`);
    return data.job || data;
}

async function waitForJob(jobId, { onUpdate, timeoutMs = JOB_POLL_TIMEOUT_MS, intervalMs = JOB_POLL_INTERVAL_MS, endpoint = '/jobs' } = {}) {
    const started = Date.now();
    while (Date.now() - started < timeoutMs) {
        const res = await fetch(`${API_BASE}${endpoint}/${encodeURIComponent(jobId)}`);
        const job = await res.json();
        if (!res.ok) throw new Error(job.detail || `Failed to load job (${res.status})`);
        if (typeof onUpdate === 'function') onUpdate(job);
        if (job.status === 'completed') return job.result;
        if (job.status === 'canceled') throw new Error(job.error || "Job canceled.");
        if (job.status === 'error') throw new Error(job.error || "Background job failed.");
        await sleep(intervalMs);
    }
    throw new Error("Job timed out. Please try again.");
}

window.loadSearchAgents = async () => {
    const list = document.getElementById('searchAgentsList');
    if (!list) return;
    list.innerHTML = '<div class="loader"></div>';

    try {
        const res = await fetch(`${API_BASE}/search-agents`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const agents = await res.json();

        if (!agents || agents.length === 0) {
            list.innerHTML = '<div style="text-align:center; color:var(--text-muted); padding:1rem;">No saved agents yet.</div>';
            return;
        }

        list.innerHTML = agents.map((a) => `
            <div style="border:1px solid rgba(255,255,255,0.12); border-radius:10px; padding:0.8rem; background:rgba(255,255,255,0.03);">
                <div style="display:flex; justify-content:space-between; gap:0.8rem; align-items:flex-start;">
                    <div>
                        <div style="font-weight:700;">${escapeHtml(a.name)}</div>
                        <div style="font-size:0.85rem; color:var(--text-muted); margin-top:0.2rem;">
                            ${(a.query || '').trim()
                ? `<code>${escapeHtml(a.query)}</code>`
                : '<span style="opacity:0.75;">(semantic seed mode)</span>'}
                        </div>
                        ${(a.source_paper_id || '').trim()
                ? `<div style="font-size:0.77rem; color:var(--text-muted); margin-top:0.2rem;">source: <code>${escapeHtml(String(a.source_paper_id || ''))}</code></div>`
                : ''}
                        <div style="display:flex; gap:0.45rem; margin-top:0.35rem;">
                            <span class="tag">${escapeHtml(a.mode || 'global')}</span>
                            <span class="tag">${escapeHtml(a.cadence || 'daily')}</span>
                            <span class="tag">max ${Number(a.max_results || 8)}</span>
                            ${a.last_run_at ? `<span class="tag" title="${escapeHtml(a.last_run_at)}">ran</span>` : '<span class="tag">never ran</span>'}
                        </div>
                    </div>
                    <div style="display:flex; gap:0.4rem;">
                        <button class="btn-secondary" onclick="runSearchAgent(${Number(a.id)})" style="padding:0.45rem 0.7rem;">
                            <i class="fa-solid fa-play"></i> Run
                        </button>
                        <button class="action-btn" onclick="deleteSearchAgent(${Number(a.id)})" title="Delete agent" style="color:#f87171;">
                            <i class="fa-solid fa-trash"></i>
                        </button>
                    </div>
                </div>
                ${a.last_summary ? `<details style="margin-top:0.55rem;"><summary style="cursor:pointer; color:var(--text-muted);">Last digest (${Number(a.last_matches_count || 0)} matches)</summary><div style="margin-top:0.45rem; white-space:pre-wrap;">${escapeHtml(a.last_summary)}</div></details>` : ''}
            </div>
        `).join('');
    } catch (e) {
        console.error(e);
        list.innerHTML = `<div style="color:var(--danger)">Failed to load agents: ${e.message}</div>`;
    }
};

window.updateSearchAgentFormUi = () => {
    const modeEl = document.getElementById('agentModeInput');
    const queryEl = document.getElementById('agentQueryInput');
    const sourceEl = document.getElementById('agentSourcePaperInput');
    const hintEl = document.getElementById('agentFormHint');
    const mode = String(modeEl?.value || 'global').toLowerCase();
    if (queryEl) {
        queryEl.placeholder = mode === 'semantic'
            ? 'Optional semantic seed text (or leave empty and use source paper)'
            : 'e.g. ti:"diffusion" AND cat:cs.CV';
    }
    if (hintEl) {
        hintEl.textContent = mode === 'semantic'
            ? 'Semantic mode: use query text and/or a source paper from your library.'
            : 'Global/local modes require a query. Local runs over your indexed library.';
    }
    if (sourceEl) {
        sourceEl.placeholder = mode === 'semantic'
            ? 'Required if query is empty: paper ID/URL from your library'
            : 'Optional';
    }
};

window.createSearchAgent = async () => {
    const nameEl = document.getElementById('agentNameInput');
    const queryEl = document.getElementById('agentQueryInput');
    const modeEl = document.getElementById('agentModeInput');
    const sourceEl = document.getElementById('agentSourcePaperInput');
    const cadenceEl = document.getElementById('agentCadenceInput');
    const maxEl = document.getElementById('agentMaxResultsInput');

    const name = (nameEl ? nameEl.value : '').trim();
    const query = (queryEl ? queryEl.value : '').trim();
    const modeRaw = (modeEl ? modeEl.value : 'global').trim().toLowerCase();
    const mode = ['global', 'semantic', 'local'].includes(modeRaw) ? modeRaw : 'global';
    const sourcePaperId = (sourceEl ? sourceEl.value : '').trim();
    const cadence = (cadenceEl ? cadenceEl.value : 'daily').trim().toLowerCase();
    const maxResults = Number.parseInt(maxEl ? maxEl.value : '8', 10);

    if (!name) {
        alert("Please provide an agent name.");
        return;
    }
    if (mode !== 'semantic' && !query) {
        alert("Please provide a query for global/local modes.");
        return;
    }
    if (mode === 'semantic' && !query && !sourcePaperId) {
        alert("Semantic mode needs query text or a source paper ID.");
        return;
    }

    try {
        const res = await fetch(`${API_BASE}/search-agents`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                name,
                query,
                mode,
                source_paper_id: sourcePaperId || null,
                cadence: cadence === 'weekly' ? 'weekly' : 'daily',
                max_results: Number.isFinite(maxResults) ? Math.max(1, maxResults) : 8
            })
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Failed to save agent");

        if (nameEl) nameEl.value = '';
        if (queryEl) queryEl.value = '';
        if (sourceEl) sourceEl.value = '';
        await loadSearchAgents();
    } catch (e) {
        console.error(e);
        alert(`Failed to save search agent: ${e.message}`);
    }
};

window.runSearchAgent = async (agentId) => {
    const summaryBox = document.getElementById('searchAgentRunSummary');
    if (summaryBox) {
        summaryBox.style.display = 'block';
        summaryBox.innerHTML = '<div class="loader"></div>';
    }

    try {
        const res = await fetch(`${API_BASE}/search-agents/${agentId}/run`, { method: 'POST' });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Run failed");

        if (summaryBox) {
            summaryBox.style.display = 'block';
            if (data.skipped) {
                summaryBox.innerHTML = `<div style="color:var(--text-muted)">Agent is already running. Try again in a moment.</div>`;
            } else {
                const counts = `Matches: ${Number(data.matches || 0)} | New: ${Number(data.new_matches || 0)} | Repeats: ${Number(data.repeat_matches || 0)} | Alerts: ${Number(data.created_alerts || 0)}`;
                await ensureMarkdownLibs();
                summaryBox.innerHTML = `<div style="font-size:0.85rem; color:var(--text-muted); margin-bottom:0.6rem;">${counts}</div>` + renderMarkdownSafe(data.summary || "Run completed.");
            }
        }

        await loadSearchAgents();
        await refreshAlertsBadge();
    } catch (e) {
        if (summaryBox) {
            summaryBox.style.display = 'block';
            summaryBox.innerHTML = `<div style="color:var(--danger)">Run failed: ${e.message}</div>`;
        }
    }
};

window.deleteSearchAgent = async (agentId) => {
    if (!confirm("Delete this saved search agent?")) return;
    try {
        await fetch(`${API_BASE}/search-agents/${agentId}`, { method: 'DELETE' });
        await loadSearchAgents();
    } catch (e) {
        alert("Failed to delete search agent.");
    }
};

window.restoreView = () => {
    // Restore header
    const dateDisplay = document.getElementById('batchDateDisplay');
    if (currentDateFilter) {
        dateDisplay.textContent = `Showing: ${currentDateFilter}`;
    } else {
        dateDisplay.textContent = `Latest Batch: ${allPapers.length > 0 ? allPapers[0].published.slice(0, 10) : ''}`;
    }

    // Apply current search filter if any, or show all
    const searchInput = document.getElementById('searchInput');
    if (searchInput && searchInput.value) {
        filterAndRenderPapers(searchInput.value);
    } else {
        renderPaperGrid(allPapers);
    }
};

function tokenize(text) {
    return text.replace(/[^\w\s]/g, '').split(/\s+/).filter(w => w.length > 2 && !STOPWORDS.has(w));
}

function setLoading(bool) {
    isLoading = bool;
    if (bool) {
        loadingIndicator.classList.remove('hidden');
        paperGrid.classList.add('hidden');
    } else {
        loadingIndicator.classList.add('hidden');
        paperGrid.classList.remove('hidden');
    }
}

function highlightText(text) {
    if (!text) return "";
    if (!userKeywords || userKeywords.length === 0) return text;

    // Escape regex characters in keywords if necessary
    // Simple approach: case insensitive replace
    let newText = String(text);

    userKeywords.forEach(kw => {
        if (kw.length < 3) return; // Skip very short words
        const regex = new RegExp(`(${kw})`, 'gi');
        newText = newText.replace(regex, '<span class="highlight">$1</span>');
    });

    return newText;
}

async function updateCharts() {
    if (!isStatsOpen) return;
    try {
        await ensureChartLib();
    } catch (e) {
        console.error("Chart library load failed", e);
        return;
    }

    // Topic Chart (Client side data)
    // Count categories
    const counts = {};
    allPapers.forEach(p => {
        (p.categories || []).forEach(c => {
            counts[c] = (counts[c] || 0) + 1;
        });
    });

    // Sort and take top 8
    const sorted = Object.entries(counts).sort((a, b) => b[1] - a[1]).slice(0, 8);
    const labels = sorted.map(k => k[0]);
    const data = sorted.map(k => k[1]);

    const ctx1 = document.getElementById('topicChart');
    if (topicChart) topicChart.destroy();

    topicChart = new Chart(ctx1, {
        type: 'doughnut',
        data: {
            labels: labels,
            datasets: [{
                data: data,
                backgroundColor: [
                    '#6366f1', '#a855f7', '#ec4899', '#f43f5e',
                    '#f59e0b', '#10b981', '#3b82f6', '#8b5cf6'
                ],
                borderWidth: 0
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { position: 'right', labels: { color: '#94a3b8' } }
            }
        }
    });

    // Trend Chart (Server side data)
    try {
        const res = await fetch(`${API_BASE}/stats`);
        const stats = await res.json();

        const ctx2 = document.getElementById('trendChart');
        if (trendChart) trendChart.destroy();

        trendChart = new Chart(ctx2, {
            type: 'bar',
            data: {
                labels: stats.map(s => s.date.slice(5)), // MM-DD
                datasets: [{
                    label: 'Papers Fetched',
                    data: stats.map(s => s.count),
                    backgroundColor: '#3b82f6',
                    borderRadius: 4
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                scales: {
                    y: { grid: { color: 'rgba(255,255,255,0.1)' }, ticks: { color: '#94a3b8' } },
                    x: { grid: { display: false }, ticks: { color: '#94a3b8' } }
                },
                plugins: { legend: { display: false } }
            }
        });

    } catch (err) {
        console.error("Stats error", err);
    }
}

function renderSmartStacks(papers) {
    // 1. Identify common keywords (clusters)
    const tokenCounts = {};
    const paperTokens = papers.map(p => {
        const text = (p.title + " " + (p.summary || "")).toLowerCase();
        const tokens = new Set(tokenize(text));
        tokens.forEach(t => tokenCounts[t] = (tokenCounts[t] || 0) + 1);
        return { id: p.id, tokens };
    });

    // Filter for keywords that appear in at least 2 papers
    // Sort by frequency desc
    const keywords = Object.entries(tokenCounts)
        .filter(([k, count]) => count >= 2)
        .sort((a, b) => b[1] - a[1])
        .map(k => k[0]);

    // 2. Assign papers to clusters (Greedy assignment)
    const clusters = {}; // key -> [paperIds]
    const assigned = new Set();

    // Create clusters for top keywords
    keywords.forEach(kw => {
        // Find papers having this keyword that are not yet deeply assigned
        // Actually, a paper can belong to a cluster if it matches.
        // Let's sweep:
        const matches = papers.filter(p => !assigned.has(p.id) && paperTokens.find(pt => pt.id === p.id).tokens.has(kw));

        if (matches.length >= 2) {
            clusters[kw] = matches;
            matches.forEach(m => assigned.add(m.id));
        }
    });

    // 3. Render Clusters
    const container = document.createElement('div');
    container.style.gridColumn = '1/-1';

    const sortedClusters = Object.entries(clusters).sort((a, b) => b[1].length - a[1].length);

    if (sortedClusters.length === 0) {
        // No clusters found, fall back
        papers.forEach(p => {
            paperGrid.appendChild(createPaperCard(p));
        });
        return;
    }

    const isFavorites = (currentStatus === 'liked');
    const gridStyle = isFavorites ? 'display:grid; grid-template-columns: 1fr 1fr; gap:1.5rem;' : '';

    sortedClusters.forEach(([name, stackPapers]) => {
        // Capitalize
        const title = name.charAt(0).toUpperCase() + name.slice(1);

        const section = document.createElement('div');
        section.className = 'stack-section';
        section.innerHTML = `
            <div class="stack-header">
                <h3><i class="fa-solid fa-layer-group"></i> ${title}</h3>
                <span class="stack-count">${stackPapers.length} papers</span>
            </div>
            <div class="stack-grid" style="${gridStyle}"></div>
        `;

        const grid = section.querySelector('.stack-grid');
        stackPapers.forEach(p => {
            grid.appendChild(createPaperCard(p));
        });

        container.appendChild(section);
    });

    // Handle Unsorted
    const unsorted = papers.filter(p => !assigned.has(p.id));
    if (unsorted.length > 0) {
        const section = document.createElement('div');
        section.className = 'stack-section';
        section.innerHTML = `
            <div class="stack-header" style="border-left-color: var(--text-muted);">
                <h3 style="color:var(--text-muted)"><i class="fa-regular fa-folder"></i> Unsorted</h3>
                <span class="stack-count">${unsorted.length} papers</span>
            </div>
            <div class="stack-grid" style="${gridStyle}"></div>
        `;
        const grid = section.querySelector('.stack-grid');
        unsorted.forEach(p => {
            grid.appendChild(createPaperCard(p));
        });
        container.appendChild(section);
    }

    paperGrid.appendChild(container);
}

// Settings Logic
window.closeSettings = () => hideModal('settingsModal');

function formatIsoShort(value) {
    if (!value) return '';
    const text = String(value);
    return text.replace('T', ' ').slice(0, 19);
}

function formatBytes(bytes) {
    const num = Number(bytes);
    if (!Number.isFinite(num) || num <= 0) return '0 B';
    const units = ['B', 'KB', 'MB', 'GB'];
    let size = num;
    let idx = 0;
    while (size >= 1024 && idx < units.length - 1) {
        size /= 1024;
        idx += 1;
    }
    return `${size.toFixed(size >= 10 || idx === 0 ? 0 : 1)} ${units[idx]}`;
}

window.loadExportHistory = async () => {
    const list = document.getElementById('exportHistoryList');
    if (!list) return;
    list.innerHTML = '<div class="loader"></div>';

    try {
        const res = await fetch(`${API_BASE}/export/history?limit=30&kind=bundle`);
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
        if (!Array.isArray(data) || data.length === 0) {
            list.innerHTML = '<div style="color:var(--text-muted); text-align:center;">No bundle exports yet.</div>';
            return;
        }
        list.innerHTML = data.map((item) => {
            const status = item.status || 'unknown';
            const statusColor = status === 'available' ? '#34d399' : status === 'expired' ? '#f87171' : '#f59e0b';
            const meta = item.meta || {};
            const detail = [
                meta.paper_count ? `${meta.paper_count} papers` : null,
                meta.include_brief ? 'brief' : null,
                meta.include_benchmarks ? 'benchmarks' : null,
                meta.cached ? 'cached' : null,
            ].filter(Boolean).join(' · ');
            return `
                <div class="export-history-card">
                    <div style="display:flex; justify-content:space-between; gap:0.6rem; align-items:flex-start;">
                        <div>
                            <div style="font-weight:700;">${escapeHtml(item.filename || 'bundle.zip')}</div>
                            <div style="font-size:0.82rem; color:var(--text-muted); margin-top:0.2rem;">
                                ${escapeHtml(formatIsoShort(item.created_at))}${detail ? ` · ${escapeHtml(detail)}` : ''}
                            </div>
                            <div style="font-size:0.78rem; color:var(--text-muted); margin-top:0.15rem;">
                                Expires: ${escapeHtml(formatIsoShort(item.expires_at) || 'n/a')} · ${escapeHtml(formatBytes(item.size_bytes))}
                            </div>
                        </div>
                        <div style="display:flex; flex-direction:column; align-items:flex-end; gap:0.35rem;">
                            <span class="tag" style="background:rgba(255,255,255,0.08); color:${statusColor}; border:1px solid ${statusColor};">
                                ${escapeHtml(status)}
                            </span>
                            ${item.downloadable ? `
                                <button class="btn-secondary" onclick="redownloadExport('${item.id}')" style="padding:0.35rem 0.7rem;">
                                    <i class="fa-solid fa-download"></i> Re-download
                                </button>
                            ` : ''}
                        </div>
                    </div>
                </div>
            `;
        }).join('');
    } catch (e) {
        list.innerHTML = `<div style="color:var(--danger)">Failed to load export history: ${escapeHtml(e.message)}</div>`;
    }
};

window.redownloadExport = async (exportId) => {
    if (!exportId) return;
    try {
        const res = await fetch(`${API_BASE}/export/history/${encodeURIComponent(exportId)}/redownload`, {
            method: 'POST'
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Failed to re-download.");
        if (data.token) {
            window.location.href = `${API_BASE}/download/${data.token}`;
        }
        await loadExportHistory();
    } catch (e) {
        alert(`Re-download failed: ${e.message}`);
    }
};

window.downloadBackup = async () => {
    const statusEl = document.getElementById('backupStatus');
    if (statusEl) statusEl.textContent = 'Preparing backup...';
    try {
        const res = await fetch(`${API_BASE}/backup`, { method: 'POST' });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Backup failed.");
        if (data.token) {
            window.location.href = `${API_BASE}/download/${data.token}`;
        }
        if (statusEl) {
            const exp = data.expires_at ? formatIsoShort(data.expires_at) : 'n/a';
            statusEl.textContent = `Backup ready. Expires: ${exp}.`;
        }
        await loadExportHistory();
    } catch (e) {
        if (statusEl) statusEl.textContent = `Backup failed: ${e.message}`;
    }
};

window.restoreBackupFromFile = async (event) => {
    const file = event && event.target ? event.target.files[0] : null;
    const statusEl = document.getElementById('restoreStatus');
    if (!file) return;
    if (statusEl) statusEl.textContent = 'Restoring backup...';
    try {
        const form = new FormData();
        form.append('file', file);
        const res = await fetch(`${API_BASE}/restore`, {
            method: 'POST',
            body: form
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Restore failed.");
        if (statusEl) statusEl.textContent = 'Restore complete. Reload the app to refresh data.';
    } catch (e) {
        if (statusEl) statusEl.textContent = `Restore failed: ${e.message}`;
    } finally {
        event.target.value = '';
    }
};

window.exportNotesJson = async () => {
    const statusEl = document.getElementById('notesImportStatus');
    if (statusEl) statusEl.textContent = 'Preparing notes export...';
    try {
        const data = await apiFetchJson(`${API_BASE}/notes/export`);
        const payload = JSON.stringify(data, null, 2);
        const blob = new Blob([payload], { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `notes_export_${new Date().toISOString().slice(0, 10)}.json`;
        a.click();
        URL.revokeObjectURL(url);
        if (statusEl) statusEl.textContent = `Exported ${data.count || 0} notes.`;
    } catch (e) {
        if (statusEl) statusEl.textContent = `Export failed: ${e.message}`;
    }
};

window.importNotesJson = async (event) => {
    const file = event && event.target ? event.target.files[0] : null;
    const statusEl = document.getElementById('notesImportStatus');
    if (!file) return;
    if (statusEl) statusEl.textContent = 'Importing notes...';
    try {
        const text = await file.text();
        const parsed = JSON.parse(text);
        let items = [];
        if (Array.isArray(parsed)) {
            items = parsed;
        } else if (parsed && Array.isArray(parsed.items)) {
            items = parsed.items;
        } else {
            throw new Error("Invalid notes JSON format.");
        }
        const data = await apiFetchJson(`${API_BASE}/notes/import`, { method: 'POST', body: { items }, useCache: false });
        if (statusEl) {
            statusEl.textContent = `Imported ${data.imported || 0} notes, skipped ${data.skipped || 0}.`;
        }
        loadPapers();
    } catch (e) {
        if (statusEl) statusEl.textContent = `Import failed: ${e.message}`;
    } finally {
        event.target.value = '';
    }
};

function parseRuleList(value) {
    if (!value) return [];
    return String(value)
        .split(/[\n,]/)
        .map(s => s.trim())
        .filter(Boolean);
}

window.loadInboxRules = async () => {
    const list = document.getElementById('inboxRulesList');
    if (!list) return;
    list.innerHTML = '<div class="loader"></div>';
    try {
        const res = await fetch(`${API_BASE}/inbox-rules`);
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
        inboxRulesCache = Array.isArray(data) ? data : [];
        if (!inboxRulesCache.length) {
            list.innerHTML = '<div style="color:var(--text-muted); text-align:center;">No rules yet.</div>';
            return;
        }
        list.innerHTML = inboxRulesCache.map((rule) => `
            <div class="rule-card">
                <div style="display:flex; justify-content:space-between; gap:0.6rem; align-items:flex-start;">
                    <div>
                        <div style="font-weight:700;">${escapeHtml(rule.name || 'Rule')}</div>
                        <div style="font-size:0.82rem; color:var(--text-muted); margin-top:0.2rem;">
                            scope:${escapeHtml(rule.scope || 'papers')} · kind:${escapeHtml(rule.target_kind || 'any')} · action:${escapeHtml(rule.action || 'label')}
                            ${rule.label ? ` · label:${escapeHtml(rule.label)}` : ''}
                            ${rule.action === 'snooze' ? ` · ${Number(rule.snooze_days || 3)}d` : ''}
                        </div>
                        <div style="font-size:0.78rem; color:var(--text-muted); margin-top:0.2rem;">
                            ${rule.keywords?.length ? `Keywords: ${escapeHtml(rule.keywords.join(', '))}` : ''}
                            ${rule.authors?.length ? ` · Authors: ${escapeHtml(rule.authors.join(', '))}` : ''}
                            ${rule.venues?.length ? ` · Categories: ${escapeHtml(rule.venues.join(', '))}` : ''}
                        </div>
                        <div style="font-size:0.78rem; color:var(--text-muted); margin-top:0.15rem;">
                            ${Number(rule.min_novelty || 0) > 0 ? `Min novelty: ${Number(rule.min_novelty).toFixed(2)}` : ''}
                            ${(Number(rule.quiet_hours_start) >= 0 && Number(rule.quiet_hours_end) >= 0)
                ? ` · Quiet hours: ${Number(rule.quiet_hours_start)}:00-${Number(rule.quiet_hours_end)}:00`
                : ''}
                        </div>
                    </div>
                    <div style="display:flex; gap:0.4rem; align-items:center;">
                        <label style="display:flex; align-items:center; gap:0.35rem; font-size:0.85rem; color:var(--text-muted);">
                            <input type="checkbox" ${rule.enabled ? 'checked' : ''} onchange="toggleInboxRule('${rule.id}', this.checked)">
                            Enabled
                        </label>
                        <button class="btn-secondary" onclick="deleteInboxRule('${rule.id}')" style="padding:0.3rem 0.6rem; color:#f87171; border-color: rgba(248,113,113,0.35);">
                            <i class="fa-solid fa-trash"></i>
                        </button>
                    </div>
                </div>
            </div>
        `).join('');
    } catch (e) {
        list.innerHTML = `<div style="color:var(--danger)">Failed to load rules: ${escapeHtml(e.message)}</div>`;
    }
};

function getInboxRuleFormPayload() {
    const name = document.getElementById('inboxRuleName')?.value?.trim() || '';
    const action = String(document.getElementById('inboxRuleAction')?.value || 'label').toLowerCase();
    const scopeRaw = String(document.getElementById('inboxRuleScope')?.value || 'papers').toLowerCase();
    const scope = ['papers', 'inbox', 'all'].includes(scopeRaw) ? scopeRaw : 'papers';
    const targetRaw = String(document.getElementById('inboxRuleTargetKind')?.value || '').toLowerCase().trim();
    const targetKind = targetRaw || null;
    const label = document.getElementById('inboxRuleLabel')?.value?.trim() || '';
    const snoozeDays = Math.max(1, Math.min(90, Number(document.getElementById('inboxRuleSnoozeDays')?.value || 3)));
    const minNoveltyRaw = Number(document.getElementById('inboxRuleMinNovelty')?.value || 0);
    const minNovelty = Number.isFinite(minNoveltyRaw) ? Math.max(0, Math.min(1, minNoveltyRaw)) : 0;
    const quietStartRaw = Number(document.getElementById('inboxRuleQuietStart')?.value ?? -1);
    const quietEndRaw = Number(document.getElementById('inboxRuleQuietEnd')?.value ?? -1);
    const quietStart = Number.isInteger(quietStartRaw) && quietStartRaw >= 0 && quietStartRaw <= 23 ? quietStartRaw : -1;
    const quietEnd = Number.isInteger(quietEndRaw) && quietEndRaw >= 0 && quietEndRaw <= 23 ? quietEndRaw : -1;
    const keywords = parseRuleList(document.getElementById('inboxRuleKeywords')?.value);
    const authors = parseRuleList(document.getElementById('inboxRuleAuthors')?.value);
    const venues = parseRuleList(document.getElementById('inboxRuleVenues')?.value);
    const enabled = Boolean(document.getElementById('inboxRuleEnabled')?.checked);
    return {
        name,
        action,
        scope,
        target_kind: targetKind,
        label: label || null,
        snooze_days: snoozeDays,
        min_novelty: minNovelty,
        quiet_hours_start: quietStart,
        quiet_hours_end: quietEnd,
        keywords,
        authors,
        venues,
        enabled,
    };
}

function resetInboxRuleForm() {
    const name = document.getElementById('inboxRuleName');
    const action = document.getElementById('inboxRuleAction');
    const scope = document.getElementById('inboxRuleScope');
    const target = document.getElementById('inboxRuleTargetKind');
    const label = document.getElementById('inboxRuleLabel');
    const snooze = document.getElementById('inboxRuleSnoozeDays');
    const minNovelty = document.getElementById('inboxRuleMinNovelty');
    const quietStart = document.getElementById('inboxRuleQuietStart');
    const quietEnd = document.getElementById('inboxRuleQuietEnd');
    const keywords = document.getElementById('inboxRuleKeywords');
    const authors = document.getElementById('inboxRuleAuthors');
    const venues = document.getElementById('inboxRuleVenues');
    const enabled = document.getElementById('inboxRuleEnabled');
    if (name) name.value = '';
    if (action) action.value = 'label';
    if (scope) scope.value = 'papers';
    if (target) target.value = '';
    if (label) label.value = '';
    if (snooze) snooze.value = '3';
    if (minNovelty) minNovelty.value = '0';
    if (quietStart) quietStart.value = '-1';
    if (quietEnd) quietEnd.value = '-1';
    if (keywords) keywords.value = '';
    if (authors) authors.value = '';
    if (venues) venues.value = '';
    if (enabled) enabled.checked = true;
}

window.saveInboxRule = async () => {
    const payload = getInboxRuleFormPayload();
    const statusEl = document.getElementById('inboxRulesStatus');

    if (!payload.name) {
        alert("Please provide a rule name.");
        return;
    }
    if (payload.action === 'label' && !payload.label) {
        alert("Please provide a label for label rules.");
        return;
    }

    try {
        const res = await fetch(`${API_BASE}/inbox-rules`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Failed to save rule.");
        if (statusEl) statusEl.textContent = 'Rule saved.';
        resetInboxRuleForm();
        await loadInboxRules();
        await previewInboxRulesNow();
        await loadInboxRuleAudit();
        await loadInboxRuleDiagnostics();
    } catch (e) {
        if (statusEl) statusEl.textContent = `Save failed: ${e.message}`;
    }
};

window.toggleInboxRule = async (ruleId, enabled) => {
    const rule = inboxRulesCache.find(r => r.id === ruleId);
    if (!rule) return;
    try {
        await fetch(`${API_BASE}/inbox-rules/${encodeURIComponent(ruleId)}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                name: rule.name,
                action: rule.action,
                label: rule.label,
                keywords: rule.keywords || [],
                authors: rule.authors || [],
                venues: rule.venues || [],
                scope: rule.scope || 'papers',
                target_kind: rule.target_kind || null,
                snooze_days: Number(rule.snooze_days || 3),
                min_novelty: Number(rule.min_novelty || 0),
                quiet_hours_start: Number(rule.quiet_hours_start ?? -1),
                quiet_hours_end: Number(rule.quiet_hours_end ?? -1),
                enabled: Boolean(enabled)
            })
        });
        rule.enabled = Boolean(enabled);
        await previewInboxRulesNow();
        await loadInboxRuleDiagnostics();
    } catch (e) {
        alert(`Failed to update rule: ${e.message}`);
    }
};

window.deleteInboxRule = async (ruleId) => {
    if (!confirm("Delete this rule?")) return;
    try {
        const res = await fetch(`${API_BASE}/inbox-rules/${encodeURIComponent(ruleId)}`, { method: 'DELETE' });
        if (!res.ok) throw new Error("Failed to delete rule.");
        await loadInboxRules();
        await previewInboxRulesNow();
        await loadInboxRuleAudit();
        await loadInboxRuleDiagnostics();
    } catch (e) {
        alert(`Failed to delete rule: ${e.message}`);
    }
};

function flattenInboxRuleMatches(payload) {
    const sections = Array.isArray(payload?.results) ? payload.results : [];
    const out = [];
    sections.forEach((section) => {
        const scope = String(section?.scope || payload?.scope || '');
        const matches = Array.isArray(section?.matches) ? section.matches : [];
        matches.forEach((match) => {
            out.push({ ...match, scope: match.scope || scope });
        });
    });
    return out;
}

function renderInboxRulePreview(payload) {
    const list = document.getElementById('inboxRulesPreviewList');
    if (!list) return;
    if (!payload || typeof payload !== 'object') {
        list.innerHTML = '<div style="color:var(--text-muted);">No preview data.</div>';
        return;
    }
    const matches = flattenInboxRuleMatches(payload);
    const head = `
        <div style="font-size:0.82rem; color:var(--text-muted);">
            scope:${escapeHtml(String(payload.scope || 'papers'))} · matched:${Number(payload.matched || 0)} · applied:${Number(payload.applied || 0)} · audit:${Number(payload.audit_count || 0)}
        </div>
    `;
    if (!matches.length) {
        list.innerHTML = `${head}<div style="color:var(--text-muted);">No matching items.</div>`;
        return;
    }
    list.innerHTML = head + matches.slice(0, 20).map((m) => `
        <div style="border:1px solid rgba(255,255,255,0.1); border-radius:8px; padding:0.5rem; background:rgba(255,255,255,0.02);">
            <div style="font-size:0.82rem; color:var(--text-muted);">
                ${escapeHtml(String(m.scope || ''))} · ${escapeHtml(String(m.kind || m.item_kind || 'paper'))} · ${escapeHtml(String(m.action || ''))} · ${escapeHtml(String(m.result || 'matched'))}
            </div>
            <div style="font-size:0.86rem;">${escapeHtml(String(m.title || m.paper_id || m.item_ref || 'item'))}</div>
            <div style="font-size:0.78rem; color:var(--text-muted);">${escapeHtml(String(m.rule_name || m.rule_id || 'rule'))}</div>
        </div>
    `).join('');
}

function renderInboxRuleAudit(items) {
    const list = document.getElementById('inboxRulesAuditList');
    if (!list) return;
    const rows = Array.isArray(items) ? items : [];
    if (!rows.length) {
        list.innerHTML = '<div style="color:var(--text-muted);">No audit entries yet.</div>';
        return;
    }
    list.innerHTML = rows.slice(0, 60).map((row) => {
        const title = String((row.meta || {}).title || row.item_ref || 'item');
        const createdAt = formatIsoShort(row.created_at || '');
        return `
            <div style="border:1px solid rgba(255,255,255,0.1); border-radius:8px; padding:0.5rem; background:rgba(255,255,255,0.02);">
                <div style="font-size:0.8rem; color:var(--text-muted);">
                    ${escapeHtml(String(row.scope || ''))} · ${escapeHtml(String(row.item_kind || ''))} · ${escapeHtml(String(row.action || ''))} · ${escapeHtml(String(row.result || ''))}
                </div>
                <div style="font-size:0.86rem;">${escapeHtml(title)}</div>
                <div style="font-size:0.78rem; color:var(--text-muted);">${escapeHtml(String(row.rule_id || 'manual'))} · ${escapeHtml(createdAt || '')}</div>
            </div>
        `;
    }).join('');
}

function renderInboxRuleDiagnostics(payload) {
    const list = document.getElementById('inboxRulesDiagnosticsList');
    if (!list) return;
    const rows = Array.isArray(payload?.items) ? payload.items : [];
    const summary = payload?.summary || {};
    const head = `
        <div style="font-size:0.82rem; color:var(--text-muted);">
            warn:${Number(summary.warn || 0)} · info:${Number(summary.info || 0)} · error:${Number(summary.error || 0)}
        </div>
    `;
    if (!rows.length) {
        list.innerHTML = `${head}<div style="color:var(--text-muted);">No diagnostics warnings.</div>`;
        return;
    }
    list.innerHTML = head + rows.slice(0, 80).map((row) => {
        const severity = String(row?.severity || 'info').toLowerCase();
        const message = String(row?.message || '');
        const ruleName = String(row?.rule_name || row?.rule_id || 'rule');
        const type = String(row?.type || 'notice');
        const meta = row?.meta && typeof row.meta === 'object'
            ? Object.entries(row.meta).slice(0, 2).map(([k, v]) => `${k}:${Array.isArray(v) ? v.join(',') : String(v)}`).join(' · ')
            : '';
        return `
            <div class="rule-diagnostic-card" data-severity="${escapeHtml(severity)}">
                <div style="font-size:0.8rem; color:var(--text-muted);">${escapeHtml(severity)} · ${escapeHtml(type)}</div>
                <div style="font-size:0.86rem;">${escapeHtml(message)}</div>
                <div style="font-size:0.78rem; color:var(--text-muted);">${escapeHtml(ruleName)}${meta ? ` · ${escapeHtml(meta)}` : ''}</div>
            </div>
        `;
    }).join('');
}

window.loadInboxRuleDiagnostics = async () => {
    const list = document.getElementById('inboxRulesDiagnosticsList');
    if (!list) return;
    list.innerHTML = '<div class="loader"></div>';
    try {
        const data = await apiFetchJson(`${API_BASE}/inbox-rules/diagnostics?limit=200`, { useCache: false });
        inboxRulesDiagnosticsCache = data;
        renderInboxRuleDiagnostics(data);
    } catch (e) {
        list.innerHTML = `<div style="color:var(--danger)">Failed to load diagnostics: ${escapeHtml(e.message)}</div>`;
    }
};

window.previewInboxRulesNow = async () => {
    const scopeVal = String(document.getElementById('inboxRulesApplyScope')?.value || 'all').toLowerCase();
    const scope = ['papers', 'inbox', 'all'].includes(scopeVal) ? scopeVal : 'all';
    const statusEl = document.getElementById('inboxRulesStatus');
    if (statusEl) statusEl.textContent = 'Previewing rules...';
    try {
        const res = await fetch(`${API_BASE}/inbox-rules/preview`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ scope, dry_run: true, limit: 200 }),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || 'Failed to preview rules.');
        inboxRulesPreviewCache = data;
        renderInboxRulePreview(data);
        if (statusEl) statusEl.textContent = `Preview: matched ${Number(data.matched || 0)}.`;
    } catch (e) {
        renderInboxRulePreview(null);
        if (statusEl) statusEl.textContent = `Preview failed: ${e.message}`;
    }
};

window.loadInboxRuleAudit = async () => {
    const list = document.getElementById('inboxRulesAuditList');
    if (!list) return;
    const limitRaw = Number(document.getElementById('inboxRulesAuditLimit')?.value || 80);
    const limit = Math.max(10, Math.min(500, limitRaw));
    list.innerHTML = '<div class="loader"></div>';
    try {
        const data = await apiFetchJson(`${API_BASE}/inbox-rules/audit?limit=${limit}`, { useCache: false });
        inboxRulesAuditCache = Array.isArray(data.items) ? data.items : [];
        renderInboxRuleAudit(inboxRulesAuditCache);
    } catch (e) {
        list.innerHTML = `<div style="color:var(--danger)">Failed to load audit log: ${escapeHtml(e.message)}</div>`;
    }
};

window.applyInboxRulesNow = async () => {
    const statusEl = document.getElementById('inboxRulesStatus');
    const scopeVal = String(document.getElementById('inboxRulesApplyScope')?.value || 'all').toLowerCase();
    const scope = ['papers', 'inbox', 'all'].includes(scopeVal) ? scopeVal : 'all';
    if (statusEl) statusEl.textContent = 'Applying rules...';
    try {
        const res = await fetch(`${API_BASE}/inbox-rules/apply`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ scope, dry_run: false, limit: 250 }),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Failed to apply rules.");
        if (statusEl) {
            statusEl.textContent = `Applied (${scope}). matched:${data.matched || 0} labeled:${data.labeled || 0} dismissed:${data.dismissed || 0} applied:${data.applied || 0}.`;
        }
        if (currentStatus === 'new') loadPapers();
        await refreshAllBadges({ force: true });
        await previewInboxRulesNow();
        await loadInboxRuleAudit();
        await loadInboxRuleDiagnostics();
    } catch (e) {
        if (statusEl) statusEl.textContent = `Apply failed: ${e.message}`;
    }
};

window.openSettings = async () => {
    try {
        const res = await fetch(`${API_BASE}/settings`);
        if (!res.ok) {
            throw new Error("Failed to load settings");
        }
        const data = await res.json();

        const catInput = document.getElementById('settingsCategories');
        const kwInput = document.getElementById('settingsKeywords');
        const vaultInput = document.getElementById('settingsVaultPath');
        const alertCitationInput = document.getElementById('settingsAlertCitationThreshold');
        const alertMaxResultsInput = document.getElementById('settingsAlertMaxResults');
        const warmupInput = document.getElementById('settingsWarmupModels');
        const notionTokenInput = document.getElementById('settingsNotionToken');
        const notionDbInput = document.getElementById('settingsNotionDbId');

        catInput.value = (data.categories || []).join(', ');
        kwInput.value = (data.keywords || []).join('\n');
        if (vaultInput) vaultInput.value = data.vault_path || "";
        if (alertCitationInput) {
            const value = Number(data.citation_threshold);
            alertCitationInput.value = Number.isFinite(value) ? String(value) : "25";
        }
        if (alertMaxResultsInput) {
            const value = Number(data.max_results);
            alertMaxResultsInput.value = Number.isFinite(value) ? String(value) : "100";
        }
        if (warmupInput) {
            warmupInput.checked = Boolean(data.warmup_models);
        }
        if (notionTokenInput) {
            notionTokenInput.value = data.notion_token || "";
        }
        if (notionDbInput) {
            notionDbInput.value = data.notion_database_id || "";
        }

        const backupStatus = document.getElementById('backupStatus');
        const restoreStatus = document.getElementById('restoreStatus');
        const rulesStatus = document.getElementById('inboxRulesStatus');
        const previewList = document.getElementById('inboxRulesPreviewList');
        const auditList = document.getElementById('inboxRulesAuditList');
        const diagnosticsList = document.getElementById('inboxRulesDiagnosticsList');
        if (backupStatus) backupStatus.textContent = '';
        if (restoreStatus) restoreStatus.textContent = '';
        if (rulesStatus) rulesStatus.textContent = '';
        if (previewList) previewList.innerHTML = '<div style="color:var(--text-muted);">Loading preview...</div>';
        if (auditList) auditList.innerHTML = '<div style="color:var(--text-muted);">Loading audit log...</div>';
        if (diagnosticsList) diagnosticsList.innerHTML = '<div style="color:var(--text-muted);">Loading diagnostics...</div>';
        const applyScope = document.getElementById('inboxRulesApplyScope');
        if (applyScope) applyScope.value = 'all';
        resetInboxRuleForm();
        await loadExportHistory();
        await loadInboxRules();
        await previewInboxRulesNow();
        await loadInboxRuleAudit();
        await loadInboxRuleDiagnostics();

        showModal('settingsModal');
    } catch (err) {
        console.error(err);
        alert("Failed to load settings");
    }
};

window.saveSettings = async () => {
    const catInput = document.getElementById('settingsCategories');
    const kwInput = document.getElementById('settingsKeywords');
    const vaultInput = document.getElementById('settingsVaultPath');
    const alertCitationInput = document.getElementById('settingsAlertCitationThreshold');
    const alertMaxResultsInput = document.getElementById('settingsAlertMaxResults');
    const warmupInput = document.getElementById('settingsWarmupModels');
    const notionTokenInput = document.getElementById('settingsNotionToken');
    const notionDbInput = document.getElementById('settingsNotionDbId');

    const cats = catInput.value.split(',').map(s => s.trim()).filter(s => s);
    const kws = kwInput.value.split('\n').map(s => s.trim()).filter(s => s);
    const vault = vaultInput ? vaultInput.value.trim() : "";
    const citationThreshold = Number.parseInt(alertCitationInput ? alertCitationInput.value : "25", 10);
    const maxAlertResults = Number.parseInt(alertMaxResultsInput ? alertMaxResultsInput.value : "100", 10);
    const warmupModels = warmupInput ? warmupInput.checked : false;
    const notionToken = notionTokenInput ? notionTokenInput.value.trim() : '';
    const notionDbId = notionDbInput ? notionDbInput.value.trim() : '';

    if (!Number.isFinite(citationThreshold) || citationThreshold < 0) {
        alert("Citation threshold must be a number greater than or equal to 0.");
        return;
    }
    if (!Number.isFinite(maxAlertResults) || maxAlertResults < 10) {
        alert("Max alerts shown must be a number greater than or equal to 10.");
        return;
    }

    try {
        const res = await fetch(`${API_BASE}/settings`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                categories: cats,
                keywords: kws,
                vault_path: vault,
                citation_threshold: citationThreshold,
                max_results: maxAlertResults,
                warmup_models: warmupModels,
                notion_token: notionToken,
                notion_database_id: notionDbId
            })
        });

        if (!res.ok) {
            throw new Error("Failed to save");
        }

        userKeywords = kws;
        invalidateFavoritesCache();
        await refreshAlertsBadge();
        hideModal('settingsModal');
        alert("Settings saved. Fetch new papers if you want category changes to affect incoming results.");
    } catch (err) {
        console.error(err);
        alert("Failed to save settings");
    }
};

window.copyBibtex = (id, btn) => {
    const paper = allPapers.find(p => p.id === id);
    if (!paper) return;

    // Generate BibTeX
    const firstAuthor = paper.authors[0] ? paper.authors[0].split(' ').pop().toLowerCase().replace(/[^a-z]/g, '') : "unknown";
    const year = paper.published.slice(0, 4);
    const titleWord = paper.title.split(' ')[0].toLowerCase().replace(/[^a-z]/g, '');
    const citationKey = `${firstAuthor}${year}${titleWord}`;

    const bibtex = `@article{${citationKey},
    title={${paper.title}},
    author={${paper.authors.join(' and ')}},
    journal={arXiv preprint arXiv:${paper.id}},
    year={${year}}
}`;

    // Copy
    navigator.clipboard.writeText(bibtex).then(() => {
        // Feedback
        const icon = btn.querySelector('i');
        const originalClass = icon.className;

        icon.className = "fa-solid fa-check";
        btn.style.color = "var(--success)";

        setTimeout(() => {
            icon.className = originalClass;
            btn.style.color = "";
        }, 1500);
    }).catch(err => {
        alert("Failed to copy to clipboard");
    });
};

window.openReproScorecard = async (paperId) => {
    recordTrail({ type: 'repro', paper_id: paperId, label: `Repro score: ${getPaperTitleById(paperId)}` });
    showModal('reproModal');
    const container = document.getElementById('reproContent');
    container.innerHTML = `
        <div id="reproJobStatus" style="font-size:0.85rem; color:var(--text-muted); margin-bottom:0.5rem;">Queueing reproducibility analysis...</div>
        <div style="margin-bottom:0.65rem;">
            <button id="cancelReproJobBtn" class="btn-secondary" onclick="cancelReproJob()" style="padding:0.35rem 0.75rem;">
                <i class="fa-solid fa-ban"></i> Cancel
            </button>
        </div>
        <div class="loader"></div>
    `;

    try {
        const jobId = await submitJob('/jobs/reproducibility', { paper_id: paperId });
        activeReproJobId = jobId;
        const data = await waitForJob(jobId, {
            onUpdate: (job) => {
                const statusEl = document.getElementById('reproJobStatus');
                if (!statusEl) return;
                const statusLabel = job.status === 'running'
                    ? `Analyzing reproducibility (${Math.round(Number(job.progress_percent || 0))}%)`
                    : job.status === 'canceling'
                        ? 'Canceling reproducibility analysis...'
                        : `Waiting in queue (#${job.queue_position || '?'})`;
                const etaLabel = job.eta_seconds != null ? ` ETA ${formatJobEta(job.eta_seconds)}` : '';
                statusEl.textContent = `${statusLabel}${etaLabel}`;
            }
        });
        activeReproJobId = null;

        const scorePct = Math.round((Number(data.overall_score || 0) / Math.max(1, Number(data.max_score || 10))) * 100);
        const checks = (data.checks || []).map((c) => `
            <div style="border:1px solid rgba(255,255,255,0.12); border-radius:10px; padding:0.75rem; background:rgba(255,255,255,0.03);">
                <div style="display:flex; justify-content:space-between; gap:0.8rem;">
                    <strong>${c.name}</strong>
                    <span style="color:${c.score >= 2 ? '#34d399' : c.score === 1 ? '#f59e0b' : '#f87171'};">${c.score}/${c.max}</span>
                </div>
                <div style="font-size:0.86rem; color:var(--text-muted); margin-top:0.35rem;">${c.reason}</div>
            </div>
        `).join('');

        container.innerHTML = `
            <div style="display:flex; justify-content:space-between; align-items:flex-start; gap:1rem; padding:0.4rem 0.2rem;">
                <div>
                    <div style="font-size:0.82rem; color:var(--text-muted);">Overall</div>
                    <div style="font-size:1.4rem; font-weight:700;">${data.overall_score}/${data.max_score} (${scorePct}%)</div>
                    <div style="font-size:0.9rem; color:var(--text-muted);">${data.summary || ''}</div>
                </div>
                <div style="display:flex; flex-direction:column; gap:0.35rem; align-items:flex-end;">
                    <span class="tag" style="background:rgba(59,130,246,0.2); color:#93c5fd;">${data.level || 'Unknown'}</span>
                    ${data.cached ? '<span class="tag" style="font-size:0.72rem;">cached</span>' : ''}
                </div>
            </div>
            ${data.code_link ? `<a href="${data.code_link}" target="_blank" class="code-link"><i class="fa-brands fa-github"></i> Repository</a>` : ''}
            ${checks}
        `;
    } catch (e) {
        activeReproJobId = null;
        console.error(e);
        container.innerHTML = `<div style="color:var(--danger)">Failed to load reproducibility scorecard: ${e.message}</div>`;
    }
};

window.cancelReproJob = async () => {
    if (!activeReproJobId) return;
    try {
        await requestJobCancel(activeReproJobId);
        const statusEl = document.getElementById('reproJobStatus');
        if (statusEl) statusEl.textContent = 'Cancel requested. Finishing current step...';
        const btn = document.getElementById('cancelReproJobBtn');
        if (btn) btn.disabled = true;
    } catch (e) {
        alert(`Failed to cancel reproducibility job: ${e.message}`);
    }
};

window.closeReproModal = () => {
    hideModal('reproModal');
};

function extractCodeLink(text) {
    if (!text) return null;
    // Regex for github or gitlab urls
    // Simple heuristic: https://github.com/username/repo
    const regex = /https?:\/\/(www\.)?(github\.com|gitlab\.com)\/[\w\-]+\/[\w\.-]+/i;
    const match = text.match(regex);
    return match ? match[0] : null;
}

window.toggleBookmark = async (id, btnElement) => {
    // Optimistic UI update
    const icon = btnElement.querySelector('i');
    const isActive = btnElement.classList.contains('active');

    // Toggle state locally
    if (isActive) {
        btnElement.classList.remove('active');
        icon.classList.remove('fa-solid');
        icon.classList.add('fa-regular');
    } else {
        btnElement.classList.add('active');
        icon.classList.remove('fa-regular');
        icon.classList.add('fa-solid');
    }

    try {
        await fetch(`${API_BASE}/papers/${encodeURIComponent(id)}/bookmark`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ active: !isActive })
        });
    } catch (err) {
        console.error(err);
        alert("Failed to bookmark.");
        // Revert UI?
    }
};

window.togglePin = async (id) => {
    const paper = (allPapers || []).find(p => p.id === id) || (currentVisiblePapers || []).find(p => p.id === id);
    const isPinned = Boolean(paper && paper.pinned);
    if (isPinned) {
        const ok = confirm("Remove pin from this paper?");
        if (!ok) return;
        try {
            const res = await fetch(`${API_BASE}/pins/${encodeURIComponent(id)}`, { method: 'DELETE' });
            if (!res.ok) throw new Error("Failed to unpin");
            updatePaperLocal(id, { pinned: false, pin_note: '', pin_expires_at: '' });
            if (currentStatus === 'liked') {
                loadPapers();
            } else {
                renderPaperGrid(currentVisiblePapers);
            }
        } catch (e) {
            alert(`Failed to unpin: ${e.message}`);
        }
        return;
    }
    const note = prompt("Pin note (optional):", paper && paper.pin_note ? paper.pin_note : "");
    if (note === null) return;
    const expiryRaw = prompt("Pin expiry in days (blank = no expiry):", "7");
    if (expiryRaw === null) return;
    let expiresInDays = null;
    if (expiryRaw.trim() !== "") {
        const parsed = Number(expiryRaw);
        if (Number.isFinite(parsed) && parsed > 0) {
            expiresInDays = Math.round(parsed);
        }
    }
    try {
        const res = await fetch(`${API_BASE}/pins/${encodeURIComponent(id)}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ note, expires_in_days: expiresInDays })
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Failed to pin");
        updatePaperLocal(id, { pinned: true, pin_note: data.note || note, pin_expires_at: data.expires_at || '' });
        if (currentStatus === 'liked') {
            loadPapers();
        } else {
            renderPaperGrid(currentVisiblePapers);
        }
    } catch (e) {
        alert(`Failed to pin: ${e.message}`);
    }
};

window.openRabbitHole = async (id) => {
    // Reuse Graph View Container
    const graphView = document.getElementById('graphView');
    graphView.classList.remove('hidden');
    // Scroll to graph
    graphView.scrollIntoView({ behavior: 'smooth' });

    // Inject Close Button if not present
    if (!document.getElementById('closeGraphBtn')) {
        const closeBtn = document.createElement('button');
        closeBtn.id = 'closeGraphBtn';
        closeBtn.innerHTML = '<i class="fa-solid fa-times"></i> Close Graph';
        closeBtn.style.cssText = 'position:absolute; top:10px; right:10px; z-index:100; padding:5px 10px; background:rgba(255,255,255,0.1); color:white; border:none; border-radius:4px; cursor:pointer;';
        closeBtn.onclick = () => graphView.classList.add('hidden');
        graphView.appendChild(closeBtn);
    }

    const container = document.getElementById('authorGraph');
    container.innerHTML = '<div class="loader" style="position:absolute; top:50%; left:50%; transform:translate(-50%,-50%)"></div>';
    try {
        await ensureVisLib();
    } catch (e) {
        alert(`Failed to load graph library: ${e.message}`);
        graphView.classList.add('hidden');
        return;
    }

    try {
        // Fetch ego graph
        const res = await fetch(`${API_BASE}/papers/${encodeURIComponent(id)}/rabbithole`);
        const data = await res.json();

        if (data.error) {
            alert(data.error);
            container.innerHTML = `<div style="text-align:center; padding-top:20%; color: #ef4444;">${data.error}</div>`;
            return;
        }

        if (data.nodes.length === 0) {
            alert("No citations found for this paper.");
            container.innerHTML = '<div style="text-align:center; padding-top:20%;">No data found</div>';
            return;
        }

        // Visualize
        const nodes = new vis.DataSet(data.nodes.map(n => {
            let color = '#94a3b8';
            let size = 20;
            if (n.group === 'center') { color = '#f43f5e'; size = 30; } // Rose
            if (n.group === 'reference') { color = '#3b82f6'; } // Blue (Outgoing)
            if (n.group === 'citation') { color = '#10b981'; } // Emerald (Incoming)

            return {
                id: n.id,
                label: (n.label || "Paper").slice(0, 15) + "...",
                title: (n.label || "Paper") + ` (${n.year || '?'})`, // Tooltip
                color: { background: color, border: 'white' },
                size: size,
                font: { color: 'white' }
            };
        }));

        const edges = new vis.DataSet(data.edges);

        const options = {
            nodes: { shape: 'dot', font: { size: 14 } },
            edges: {
                arrows: 'to',
                color: { color: 'rgba(255,255,255,0.2)' },
                smooth: { type: 'continuous' }
            },
            physics: {
                stabilization: false,
                barnesHut: { gravitationalConstant: -2000, springLength: 200 }
            },
            interaction: { hover: true }
        };

        const network = new vis.Network(container, { nodes, edges }, options);

        // Handle Click -> Dive deeper
        network.on("click", function (params) {
            if (params.nodes.length > 0) {
                const clickedId = params.nodes[0];
                if (clickedId !== id) {
                    if (confirm("Dive into this paper?")) {
                        // Semantic Scholar IDs might be just the hash.
                        // Our backend expects ArXiv IDs usually. 
                        // But let's try passing what we got.
                        openRabbitHole(clickedId);
                    }
                }
            }
        });

    } catch (err) {
        console.error("Rabbit Hole Error:", err);
        alert("Failed to load graph.");
        graphView.classList.add('hidden');
    }
};

window.openCitationOverlay = async () => {
    const ids = Array.from(selectedPaperIds || []);
    if (ids.length < 2) {
        alert("Select at least 2 papers to view citation links.");
        return;
    }
    showModal('citationOverlayModal');
    const container = document.getElementById('citationOverlayGraph');
    const meta = document.getElementById('citationOverlayMeta');
    if (meta) meta.textContent = 'Loading citation links...';
    if (container) container.innerHTML = '<div class="loader" style="margin-top:40%;"></div>';

    try {
        await ensureVisLib();
    } catch (e) {
        if (container) container.innerHTML = `<div style="color:var(--danger); text-align:center; margin-top:40%;">Failed to load graph library.</div>`;
        return;
    }

    try {
        const res = await fetch(`${API_BASE}/citations/links`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ paper_ids: ids })
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Failed to load citation links.");

        const nodesData = Array.isArray(data.nodes) ? data.nodes : [];
        const edgesData = Array.isArray(data.edges) ? data.edges : [];
        if (meta) {
            const cachedNote = data.cached ? ' · cached' : '';
            meta.textContent = `Direct links: ${edgesData.length} · Papers: ${nodesData.length}${cachedNote}`;
        }

        if (!nodesData.length) {
            if (container) container.innerHTML = `<div style="color:var(--text-muted); text-align:center; margin-top:40%;">No nodes available.</div>`;
            return;
        }

        const nodes = new vis.DataSet(nodesData.map(n => ({
            id: n.id,
            label: (n.label || 'Paper').slice(0, 40),
            title: `${n.label || 'Paper'} ${n.year ? `(${n.year})` : ''}`,
            shape: 'dot',
            size: 18,
            color: { background: '#60a5fa', border: '#e2e8f0' },
            font: { color: 'white' }
        })));

        const edges = new vis.DataSet(edgesData.map(e => ({
            from: e.from,
            to: e.to,
            arrows: 'to',
            color: { color: 'rgba(255,255,255,0.2)' }
        })));

        if (container) container.innerHTML = '';
        citationOverlayNetwork = new vis.Network(container, { nodes, edges }, {
            nodes: { font: { size: 13 } },
            edges: { smooth: { type: 'continuous' } },
            physics: {
                stabilization: false,
                barnesHut: { gravitationalConstant: -2200, springLength: 180 }
            },
            interaction: { hover: true }
        });

        citationOverlayNetwork.on('click', (params) => {
            if (params.nodes && params.nodes.length) {
                const pid = params.nodes[0];
                if (pid) openReadingModal(pid);
            }
        });

        if (edgesData.length === 0 && container) {
            const emptyNote = document.createElement('div');
            emptyNote.style.cssText = 'position:absolute; top:20px; left:20px; color:var(--text-muted); font-size:0.85rem;';
            emptyNote.textContent = 'No direct citation links found between the selected papers.';
            container.appendChild(emptyNote);
        }
    } catch (e) {
        if (container) {
            container.innerHTML = `<div style="color:var(--danger); text-align:center; margin-top:40%;">${escapeHtml(e.message)}</div>`;
        }
    }
};

window.closeCitationOverlayModal = () => {
    hideModal('citationOverlayModal');
    if (citationOverlayNetwork && typeof citationOverlayNetwork.destroy === 'function') {
        citationOverlayNetwork.destroy();
    }
    citationOverlayNetwork = null;
};

window.openRelatedGraphModal = async () => {
    const ids = Array.from(selectedPaperIds || []);
    if (ids.length < 1) {
        alert("Select at least 1 paper.");
        return;
    }
    showModal('relatedGraphModal');
    await runRelatedGraph();
};

window.closeRelatedGraphModal = () => {
    hideModal('relatedGraphModal');
    if (relatedGraphNetwork && typeof relatedGraphNetwork.destroy === 'function') {
        relatedGraphNetwork.destroy();
    }
    relatedGraphNetwork = null;
};

window.runRelatedGraph = async () => {
    const ids = Array.from(selectedPaperIds || []);
    const container = document.getElementById('relatedGraphContainer');
    const meta = document.getElementById('relatedGraphMeta');
    const perAnchorInput = document.getElementById('relatedGraphLimitInput');
    const minScoreInput = document.getElementById('relatedGraphMinScoreInput');
    const limitPerAnchor = Math.max(1, Math.min(20, Number(perAnchorInput?.value || 8)));
    const minScore = Math.max(0.0, Math.min(1.0, Number(minScoreInput?.value || 0.68)));
    if (ids.length < 1) {
        if (meta) meta.textContent = 'Select at least 1 paper.';
        return;
    }
    if (meta) meta.textContent = 'Building related graph...';
    if (container) container.innerHTML = '<div class="loader" style="margin-top:35%;"></div>';

    try {
        await ensureVisLib();
    } catch (e) {
        if (container) container.innerHTML = `<div style="color:var(--danger); text-align:center; margin-top:35%;">Failed to load graph library.</div>`;
        return;
    }

    try {
        const res = await fetch(`${API_BASE}/related-graph`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                paper_ids: ids,
                limit_per_anchor: limitPerAnchor,
                min_score: minScore,
            }),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Failed to build related graph.");

        const nodesData = Array.isArray(data.nodes) ? data.nodes : [];
        const edgesData = Array.isArray(data.edges) ? data.edges : [];
        if (meta) {
            meta.textContent = `Anchors: ${Number(data.anchor_count || ids.length)} · Nodes: ${nodesData.length} · Edges: ${edgesData.length}`;
        }
        if (!nodesData.length) {
            if (container) container.innerHTML = `<div style="color:var(--text-muted); text-align:center; margin-top:35%;">No related graph data available.</div>`;
            return;
        }

        const nodes = new vis.DataSet(nodesData.map((n) => {
            const anchor = String(n.group || '') === 'anchor';
            return {
                id: n.id,
                label: String(n.title || n.id || '').slice(0, 38),
                title: `${n.title || n.id}${n.published ? `\n${String(n.published).slice(0, 10)}` : ''}`,
                shape: 'dot',
                size: anchor ? 24 : 16,
                color: anchor
                    ? { background: '#f59e0b', border: '#fef3c7' }
                    : { background: '#38bdf8', border: '#bae6fd' },
                font: { color: '#e2e8f0', size: 12 },
            };
        }));
        const edges = new vis.DataSet(edgesData.map((e) => {
            const score = Number(e.score || 0);
            return {
                from: e.from,
                to: e.to,
                label: Number.isFinite(score) ? score.toFixed(2) : '',
                width: 1 + Math.max(0, score * 5),
                color: { color: 'rgba(148,163,184,0.45)' },
                smooth: { type: 'dynamic' },
            };
        }));

        if (container) container.innerHTML = '';
        if (relatedGraphNetwork && typeof relatedGraphNetwork.destroy === 'function') {
            relatedGraphNetwork.destroy();
        }
        relatedGraphNetwork = new vis.Network(container, { nodes, edges }, {
            physics: {
                stabilization: false,
                barnesHut: { gravitationalConstant: -2300, springLength: 160, springConstant: 0.05 },
            },
            interaction: { hover: true },
        });
        relatedGraphNetwork.on('doubleClick', (params) => {
            if (!params.nodes || !params.nodes.length) return;
            const pid = params.nodes[0];
            if (pid) openReadingModal(pid);
        });
    } catch (e) {
        if (meta) meta.textContent = `Failed: ${e.message}`;
        if (container) container.innerHTML = `<div style="color:var(--danger); text-align:center; margin-top:35%;">${escapeHtml(e.message)}</div>`;
    }
};


window.exportPaper = async (id, btn) => {
    try {
        // Animate
        const icon = btn.querySelector('i');
        icon.classList.remove('fa-file-export');
        icon.classList.add('fa-spinner', 'fa-spin');

        const res = await fetch(`${API_BASE}/export`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ paper_id: id })
        });

        const data = await res.json();

        if (!res.ok) throw new Error(data.detail || "Export failed");

        // Success
        icon.classList.remove('fa-spinner', 'fa-spin');
        icon.classList.add('fa-check');
        setTimeout(() => {
            icon.classList.remove('fa-check');
            icon.classList.add('fa-file-export');
        }, 2000);

        // Optional: Toast?
        console.log("Exported to:", data.path);
        alert(`Saved to Obsidian: ${data.path}`);

    } catch (e) {
        console.error(e);
        alert(`Export Failed: ${e.message}\nCheck Vault Path in Settings.`);
    }
};

window.exportBibtex = async () => {
    console.log("Export BibTeX Clicked");
    const paperIds = Array.from(selectedPaperIds);
    if (paperIds.length === 0) {
        alert("Please select at least one paper.");
        return;
    }

    // Feedback
    const btn = document.querySelector('button[onclick="exportBibtex()"]');
    if (btn) {
        // Save original content if not already saved (could implement a smarter way but simple is fine)
        if (!btn.dataset.original) btn.dataset.original = btn.innerHTML;
        btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Exporting...';
        btn.disabled = true;
    }

    try {
        const res = await fetch(`${API_BASE}/export/bibtex`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ paper_ids: paperIds })
        });

        if (!res.ok) throw new Error("Server error");
        const data = await res.json();

        if (data.token) {
            // Robust download via navigation
            window.location.href = `${API_BASE}/download/${data.token}`;
        } else {
            throw new Error("No download token received");
        }

    } catch (e) {
        console.error(e);
        alert("Failed to export BibTeX: " + e.message);
    } finally {
        if (btn && btn.dataset.original) {
            btn.innerHTML = btn.dataset.original;
            btn.disabled = false;
        }
    }
};

window.exportBundle = async () => {
    const ids = Array.from(selectedPaperIds || []);
    if (!ids.length) {
        alert("Select papers first.");
        return;
    }
    try {
        const res = await fetch(`${API_BASE}/export/bundle`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                paper_ids: ids,
                include_brief: true,
                include_benchmarks: true,
            })
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Export failed.");
        flashBundleCacheBadge(Boolean(data.cached));
        window.location.href = `${API_BASE}/download/${data.token}`;
    } catch (e) {
        alert(`Failed to export bundle: ${e.message}`);
    }
};

window.exportNotion = async () => {
    const ids = Array.from(selectedPaperIds || []);
    if (!ids.length) {
        alert("Select papers first.");
        return;
    }
    const btn = document.querySelector('button[onclick="exportNotion()"]');
    if (btn) {
        if (!btn.dataset.original) btn.dataset.original = btn.innerHTML;
        btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Exporting...';
        btn.disabled = true;
    }
    try {
        const res = await fetch(`${API_BASE}/export/notion`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ paper_ids: ids })
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Notion export failed.");
        const failed = Array.isArray(data.failed) ? data.failed.length : 0;
        alert(`Notion export complete: ${data.count || 0} created${failed ? `, ${failed} failed` : ''}.`);
    } catch (e) {
        alert(`Notion export failed: ${e.message}`);
    } finally {
        if (btn && btn.dataset.original) {
            btn.innerHTML = btn.dataset.original;
            btn.disabled = false;
        }
    }
};

window.shareSelection = async () => {
    const ids = Array.from(selectedPaperIds || []);
    if (!ids.length) {
        alert("Select papers first.");
        return;
    }

    const btn = document.querySelector('button[onclick="shareSelection()"]');
    if (btn) {
        if (!btn.dataset.original) btn.dataset.original = btn.innerHTML;
        btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Sharing...';
        btn.disabled = true;
    }

    try {
        const data = await apiFetchJson(`${API_BASE}/share/selection`, { method: 'POST', body: { paper_ids: ids }, useCache: false });

        const url = `${window.location.origin}/share/${data.token}`;
        openShareLinkModal(url, data.token);
    } catch (e) {
        alert(`Failed to share selection: ${e.message}`);
    } finally {
        if (btn && btn.dataset.original) {
            btn.innerHTML = btn.dataset.original;
            btn.disabled = false;
        }
    }
};

window.shareSavedView = async (id) => {
    const views = loadSavedViews();
    const view = views.find(v => v.id === id);
    if (!view) return;
    try {
        const payload = {
            name: view.name || 'Shared View',
            status: view.status || 'new',
            date_filter: view.dateFilter || null,
            smart_sort: Boolean(view.smartSort),
            favorites_sort: view.favoritesSort || null,
            search_mode: view.searchMode || 'local',
            search_query: view.searchQuery || '',
            rank_profile: view.rankProfile || { ...rankProfile },
            limit: 80,
        };
        const data = await apiFetchJson(`${API_BASE}/share/view`, { method: 'POST', body: payload, useCache: false });
        const url = `${window.location.origin}/share/${data.token}`;
        openShareLinkModal(url, data.token);
    } catch (e) {
        alert(`Failed to share view: ${e.message}`);
    }
};

window.shareWeeklyPicks = async () => {
    const status = document.getElementById('weeklyPicksStatus');
    if (status) status.textContent = 'Generating share link...';
    try {
        const data = await apiFetchJson(`${API_BASE}/weekly-picks/share`, { method: 'POST', useCache: false });
        const url = `${window.location.origin}/share/${data.token}`;
        openShareLinkModal(url, data.token);
        if (status) status.textContent = `Shared last ${data.days || 7} days.`;
    } catch (e) {
        if (status) status.textContent = `Share failed: ${e.message}`;
    }
};

window.shareWeeklyPicksDigest = async () => {
    const status = document.getElementById('weeklyPicksStatus');
    if (status) status.textContent = 'Generating digest share link...';
    try {
        const data = await apiFetchJson(`${API_BASE}/weekly-picks/digest/share`, { method: 'POST', useCache: false });
        const url = `${window.location.origin}/share/${data.token}`;
        openShareLinkModal(url, data.token);
        if (status) status.textContent = `Digest shared (${data.days || 7} days).`;
    } catch (e) {
        if (status) status.textContent = `Digest share failed: ${e.message}`;
    }
};

function findDayRunPresetById(presetId) {
    const pid = Number(presetId || 0);
    if (!pid) return null;
    return (dayRunPresetsCache || []).find((item) => Number(item?.id || 0) === pid) || null;
}

function applyDayRunOptionsToUi(options) {
    const opts = options && typeof options === 'object' ? options : {};
    const dayRunDate = document.getElementById('dayRunDateInput');
    const dayRunForce = document.getElementById('dayRunForceCheck');
    const weekendEl = document.getElementById('dayRunWeekendPolicy');
    const rulesScopeEl = document.getElementById('dayRunRulesScope');
    const fetchEl = document.getElementById('dayRunFetchCheck');
    const rulesEl = document.getElementById('dayRunRulesCheck');
    const planEl = document.getElementById('dayRunPlanCheck');
    const inboxRefreshEl = document.getElementById('dayRunInboxRefreshCheck');
    const topDate = document.getElementById('dateInput');
    const topForce = document.getElementById('dailyFetchForceCheck');

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
    if (['watchlist', 'liked', 'bookmarked', 'new'].includes(versionScope)) {
        unifiedInboxState.versionScope = versionScope;
        const scopeEl = document.getElementById('unifiedInboxScope');
        if (scopeEl) scopeEl.value = versionScope;
    }
    if (Number.isFinite(versionDays) && versionDays > 0) {
        const bounded = Math.max(1, Math.min(180, versionDays));
        unifiedInboxState.versionDays = bounded;
        const daysEl = document.getElementById('unifiedInboxDays');
        if (daysEl) daysEl.value = String(bounded);
    }
}

function renderDayRunPresetSelect(items, selectedId = null) {
    const select = document.getElementById('dayRunPresetSelect');
    if (!select) return;
    const rows = Array.isArray(items) ? items : [];
    const preferredId = Number(selectedId || select.value || 0);
    select.innerHTML = `<option value="">No preset selected</option>` + rows.map((item) => {
        const id = Number(item?.id || 0);
        const name = String(item?.name || `Preset ${id}`);
        const used = item?.last_used_at ? ` · ${String(item.last_used_at).slice(0, 10)}` : '';
        return `<option value="${id}">${escapeHtml(name)}${escapeHtml(used)}</option>`;
    }).join('');
    if (preferredId && rows.some((item) => Number(item?.id || 0) === preferredId)) {
        select.value = String(preferredId);
    } else {
        select.value = '';
    }
}

window.selectDayRunPreset = (presetId) => {
    const id = Number(presetId || 0);
    const preset = findDayRunPresetById(id);
    const nameEl = document.getElementById('dayRunPresetName');
    const descEl = document.getElementById('dayRunPresetDescription');
    if (!preset) {
        if (nameEl) nameEl.value = '';
        if (descEl) descEl.value = '';
        return;
    }
    if (nameEl) nameEl.value = String(preset.name || '');
    if (descEl) descEl.value = String(preset.description || '');
    applyDayRunOptionsToUi(preset.options || {});
    setDayRunStatus(`Loaded preset: ${preset.name || 'Preset'}`);
};

window.loadDayRunPresets = async () => {
    const select = document.getElementById('dayRunPresetSelect');
    const currentId = Number(select?.value || 0);
    try {
        const data = await apiFetchJson(`${API_BASE}/day/presets?limit=100`, { useCache: false });
        dayRunPresetsCache = Array.isArray(data.items) ? data.items : [];
        renderDayRunPresetSelect(dayRunPresetsCache, currentId);
        if (!currentId && dayRunPresetsCache.length) {
            selectDayRunPreset(dayRunPresetsCache[0].id);
            if (select) select.value = String(dayRunPresetsCache[0].id);
        } else if (!dayRunPresetsCache.length) {
            selectDayRunPreset('');
        }
    } catch (e) {
        setDayRunStatus(`Failed to load presets: ${e.message}`, true);
    }
};

window.saveDayRunPreset = async () => {
    const nameEl = document.getElementById('dayRunPresetName');
    const descEl = document.getElementById('dayRunPresetDescription');
    const name = String(nameEl?.value || '').trim();
    if (!name) {
        setDayRunStatus('Preset name is required.', true);
        return;
    }
    try {
        const payload = {
            name,
            description: String(descEl?.value || '').trim() || null,
            options: getDayRunPayloadFromUi(),
        };
        const data = await apiFetchJson(`${API_BASE}/day/presets`, {
            method: 'POST',
            body: payload,
            useCache: false,
        });
        await loadDayRunPresets();
        const select = document.getElementById('dayRunPresetSelect');
        if (select && data?.id) {
            select.value = String(data.id);
            selectDayRunPreset(data.id);
        }
        setDayRunStatus(`Preset saved: ${name}`);
    } catch (e) {
        setDayRunStatus(`Save preset failed: ${e.message}`, true);
    }
};

window.updateDayRunPreset = async () => {
    const select = document.getElementById('dayRunPresetSelect');
    const presetId = Number(select?.value || 0);
    if (!presetId) {
        setDayRunStatus('Select a preset to update.', true);
        return;
    }
    const nameEl = document.getElementById('dayRunPresetName');
    const descEl = document.getElementById('dayRunPresetDescription');
    const name = String(nameEl?.value || '').trim();
    if (!name) {
        setDayRunStatus('Preset name is required.', true);
        return;
    }
    try {
        await apiFetchJson(`${API_BASE}/day/presets/${encodeURIComponent(String(presetId))}`, {
            method: 'PUT',
            body: {
                name,
                description: String(descEl?.value || '').trim() || null,
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
};

window.deleteDayRunPreset = async () => {
    const select = document.getElementById('dayRunPresetSelect');
    const presetId = Number(select?.value || 0);
    if (!presetId) {
        setDayRunStatus('Select a preset to delete.', true);
        return;
    }
    const preset = findDayRunPresetById(presetId);
    if (!confirm(`Delete preset "${preset?.name || presetId}"?`)) return;
    try {
        await apiFetchJson(`${API_BASE}/day/presets/${encodeURIComponent(String(presetId))}`, {
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
};

window.runSelectedDayRunPreset = async () => {
    const select = document.getElementById('dayRunPresetSelect');
    const presetId = Number(select?.value || 0);
    if (!presetId) {
        setDayRunStatus('Select a preset to run.', true);
        return;
    }
    setDayRunStatus(`Running preset #${presetId}...`);
    try {
        const data = await apiFetchJson(`${API_BASE}/day/presets/${encodeURIComponent(String(presetId))}/run`, {
            method: 'POST',
            useCache: false,
        });
        if (currentStatus === 'new') {
            if (data.date) currentDateFilter = data.date;
            await loadPapers();
        }
        await refreshAllBadges({ force: true });
        if (!document.getElementById('unifiedInboxModal')?.classList.contains('hidden')) {
            await refreshUnifiedInbox();
        }
        await Promise.all([loadDayRunHistory(), loadDayRunPresets()]);
        setDayRunStatus(data.summary || `Preset run complete (#${presetId}).`);
    } catch (e) {
        setDayRunStatus(`Preset run failed: ${e.message}`, true);
    }
};

function setDayRunStatus(text, isError = false) {
    const el = document.getElementById('dayRunStatus');
    if (!el) return;
    el.style.color = isError ? 'var(--danger)' : 'var(--text-muted)';
    el.textContent = text || '';
}

function syncDayRunControlsFromTopBar() {
    const topDate = document.getElementById('dateInput');
    const topForce = document.getElementById('dailyFetchForceCheck');
    const modalDate = document.getElementById('dayRunDateInput');
    const modalForce = document.getElementById('dayRunForceCheck');
    if (modalDate && topDate && !modalDate.value) modalDate.value = topDate.value || '';
    if (modalForce && topForce) modalForce.checked = Boolean(topForce.checked);
}

function getDayRunPayloadFromUi() {
    const topDate = document.getElementById('dateInput');
    const topForce = document.getElementById('dailyFetchForceCheck');
    const dayRunDate = document.getElementById('dayRunDateInput');
    const dayRunForce = document.getElementById('dayRunForceCheck');
    const weekendEl = document.getElementById('dayRunWeekendPolicy');
    const rulesScopeEl = document.getElementById('dayRunRulesScope');
    const fetchEl = document.getElementById('dayRunFetchCheck');
    const rulesEl = document.getElementById('dayRunRulesCheck');
    const planEl = document.getElementById('dayRunPlanCheck');
    const inboxRefreshEl = document.getElementById('dayRunInboxRefreshCheck');

    const dateVal = String(dayRunDate?.value || topDate?.value || '').trim();
    const forceVal = Boolean((dayRunForce && dayRunForce.checked) || (topForce && topForce.checked));
    const weekendPolicy = String(weekendEl?.value || 'skip').toLowerCase() === 'run' ? 'run' : 'skip';
    const rulesScope = String(rulesScopeEl?.value || 'all').toLowerCase();
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
        version_scope: unifiedInboxState.versionScope || 'watchlist',
        version_days: Math.max(1, Math.min(180, Number(unifiedInboxState.versionDays || 30))),
    };
    if (topDate) topDate.value = dateVal || '';
    if (topForce) topForce.checked = forceVal;
    return payload;
}

function renderDayRunHistory(items) {
    const list = document.getElementById('dayRunHistoryList');
    if (!list) return;
    const rows = Array.isArray(items) ? items : [];
    if (!rows.length) {
        list.innerHTML = '<div style="color:var(--text-muted);">No runs yet.</div>';
        return;
    }
    list.innerHTML = rows.map((item) => {
        const runId = Number(item.id || 0);
        const status = String(item.status || 'unknown');
        const runDate = String(item.run_date || '');
        const requestedAt = formatIsoShort(item.requested_at || '');
        const summary = String(item.summary || '').trim() || 'No summary available.';
        const options = item.options || {};
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

window.loadDayRunHistory = async () => {
    const list = document.getElementById('dayRunHistoryList');
    if (!list) return;
    list.innerHTML = '<div class="loader"></div>';
    try {
        const data = await apiFetchJson(`${API_BASE}/day/runs?limit=20`, { useCache: false });
        dayRunHistoryCache = Array.isArray(data.items) ? data.items : [];
        renderDayRunHistory(dayRunHistoryCache);
    } catch (e) {
        list.innerHTML = `<div style="color:var(--danger)">Failed to load day runs: ${escapeHtml(e.message)}</div>`;
    }
};

window.retryDayRun = async (runId) => {
    const id = Number(runId || 0);
    if (!id) return;
    setDayRunStatus(`Retrying run #${id}...`);
    try {
        const data = await apiFetchJson(`${API_BASE}/day/run/${encodeURIComponent(String(id))}/retry`, {
            method: 'POST',
            useCache: false,
        });
        setDayRunStatus(data.summary || `Retried run #${id}.`);
        await refreshAllBadges({ force: true });
        if (!document.getElementById('unifiedInboxModal')?.classList.contains('hidden')) {
            await refreshUnifiedInbox();
        }
        await loadDayRunHistory();
    } catch (e) {
        setDayRunStatus(`Retry failed: ${e.message}`, true);
    }
};

window.runDailyFetch = async () => {
    try {
        const dateInput = document.getElementById('dateInput');
        const dateVal = dateInput ? dateInput.value : null;
        const forceCheck = document.getElementById('dailyFetchForceCheck');
        const force = forceCheck ? forceCheck.checked : false;
        let res;
        let data;
        if (dateVal) {
            const forceParam = force ? '&force=true' : '';
            const url = `${API_BASE}/fetch/daily?date=${encodeURIComponent(dateVal)}${forceParam}`;
            res = await fetch(url, { method: 'POST' });
            data = await res.json();
            if (!res.ok) throw new Error(data.detail || "Daily fetch failed.");
            if (data.skipped) {
                alert(`Daily fetch skipped: ${data.reason || 'unknown'}`);
                return;
            }
        } else {
            if (force) {
                const forceUrl = `${API_BASE}/fetch/daily?force=true`;
                res = await fetch(forceUrl, { method: 'POST' });
                data = await res.json();
                if (!res.ok) throw new Error(data.detail || "Daily fetch failed.");
                if (data.skipped) {
                    alert(`Daily fetch skipped: ${data.reason || 'unknown'}`);
                    return;
                }
            } else {
                res = await fetch(`${API_BASE}/fetch`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ max_results: 20 })
                });
                data = await res.json();
                if (!res.ok) throw new Error(data.detail || "Fetch failed.");
            }
        }
        if (data.skipped) {
            alert(`Daily fetch skipped: ${data.reason || 'unknown'}`);
            return;
        }
        alert(`Daily fetch complete: ${data.fetched} papers (${data.new} new) for ${data.date}.`);
        if (currentStatus === 'new') {
            currentDateFilter = data.date;
            loadPapers();
        }
        refreshAllBadges();
    } catch (e) {
        alert(`Daily fetch failed: ${e.message}`);
    }
};

window.runMyDay = async () => {
    const btn = document.getElementById('dayRunBtn');
    const runBtn = document.querySelector('#unifiedInboxModal button[onclick="runMyDay()"]');
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
        const res = await fetch(`${API_BASE}/day/run`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Day run failed");
        if (currentStatus === 'new') {
            if (data.date) currentDateFilter = data.date;
            await loadPapers();
        }
        await refreshAllBadges({ force: true });
        if (!document.getElementById('unifiedInboxModal')?.classList.contains('hidden')) {
            await refreshUnifiedInbox();
        }
        await loadDayRunHistory();
        setDayRunStatus(data.summary || `Day run complete for ${data.date || 'today'}.`);
        alert(data.summary || `Day run complete for ${data.date || 'today'}.`);
    } catch (e) {
        setDayRunStatus(`Run failed: ${e.message}`, true);
        alert(`Run my day failed: ${e.message}`);
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
};
console.log("BibTeX Export Function Loaded");

// Selection & Synthesis Logic

function _selectionCardByPaperId(id) {
    const raw = String(id || '');
    if (!raw) return null;
    const escaped = (window.CSS && typeof window.CSS.escape === 'function')
        ? window.CSS.escape(raw)
        : raw.replace(/\\/g, '\\\\').replace(/"/g, '\\"');
    return document.querySelector(`.paper-card[data-paper-id="${escaped}"]`);
}

function _updateSelectionCardState(id) {
    const card = _selectionCardByPaperId(id);
    if (!card) return false;
    const wrapper = card.querySelector('.selection-checkbox-wrapper');
    if (!wrapper) return false;
    const selected = selectedPaperIds.has(id);
    const checkbox = wrapper.querySelector('.custom-checkbox');
    const label = wrapper.querySelector('[data-selection-label]');
    if (checkbox) {
        checkbox.classList.toggle('checked', selected);
        checkbox.style.background = selected ? 'var(--primary)' : 'transparent';
        checkbox.style.borderColor = selected ? 'var(--primary)' : 'var(--text-muted)';
        checkbox.innerHTML = selected ? '<i class="fa-solid fa-check" style="font-size:12px;"></i>' : '';
    }
    if (label) {
        label.classList.remove('text-primary', 'text-muted');
        label.classList.add(selected ? 'text-primary' : 'text-muted');
    }
    return true;
}

window.toggleSelectionMode = () => {
    isSelectionMode = !isSelectionMode;
    const btn = document.getElementById('selectionToggleBtn');

    if (isSelectionMode) {
        btn.classList.add('active');
        btn.style.background = 'var(--primary)';
        btn.innerHTML = '<i class="fa-solid fa-square-check"></i> Cancel Selection';
    } else {
        btn.classList.remove('active');
        btn.style.background = 'rgba(255,255,255,0.1)';
        btn.innerHTML = '<i class="fa-regular fa-square-check"></i> Select';
        selectedPaperIds.clear();
        updateSelectionUI();
    }

    // Re-render grid to show checkboxes/actions
    renderPaperGrid(currentVisiblePapers);
};

window.toggleSelection = (id, event = null) => {
    if (event && typeof event.stopPropagation === 'function') {
        event.stopPropagation();
    }
    if (selectedPaperIds.has(id)) {
        selectedPaperIds.delete(id);
    } else {
        selectedPaperIds.add(id);
    }
    updateSelectionUI();
    if (!_updateSelectionCardState(id)) {
        renderPaperGrid(currentVisiblePapers);
    }
};

window.updateSelectionUI = () => {
    const bar = document.getElementById('selectionBar');
    const count = document.getElementById('selectionCount');
    const batchTagBtn = document.getElementById('batchTagBtn');
    const compareDiffBtn = document.getElementById('compareDiffBtn');
    const citationOverlayBtn = document.getElementById('citationOverlayBtn');

    if (selectedPaperIds.size > 0) {
        bar.classList.remove('hidden');
        count.textContent = `${selectedPaperIds.size} Selected`;
        if (batchTagBtn) batchTagBtn.style.display = 'block';
        if (compareDiffBtn) compareDiffBtn.style.display = selectedPaperIds.size === 2 ? 'block' : 'none';
        if (citationOverlayBtn) citationOverlayBtn.style.display = selectedPaperIds.size >= 2 ? 'block' : 'none';
    } else {
        bar.classList.add('hidden');
        if (batchTagBtn) batchTagBtn.style.display = 'none';
        if (compareDiffBtn) compareDiffBtn.style.display = 'none';
        if (citationOverlayBtn) citationOverlayBtn.style.display = 'none';
    }
};

window.clearSelection = () => {
    selectedPaperIds.clear();
    updateSelectionUI();
    toggleSelectionMode(); // Also exit mode
};

window.startSynthesis = async () => {
    const papers = Array.from(selectedPaperIds);
    if (papers.length < 2) {
        alert("Please select at least 2 papers for a comparative review.");
        return;
    }

    const content = document.getElementById('synthesisContent');

    recordTrail({ type: 'synthesis', paper_ids: papers, label: `Synthesis (${papers.length})` });
    showModal('synthesisModal');
    content.innerHTML = '<div class="loader"></div><p style="text-align:center; margin-top:1rem;">Synthesizing Literature Review... (this may take a minute)</p>';

    try {
        const res = await fetch(`${API_BASE}/synthesize`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ paper_ids: papers })
        });

        const data = await res.json();

        if (!res.ok) throw new Error(data.detail || "API Error");

        currentReviewMarkdown = data.review;

        // Simple Markdown Renderer
        // For now, just replace # with H tags and newlines
        // If we had a markdown lib, proper.
        // We can reuse the one from Briefs or simple regex.
        // Let's stick to pre-wrap CSS for now, but maybe minor formatting.
        content.innerHTML = currentReviewMarkdown
            .replace(/^# (.*$)/gim, '<h1>$1</h1>')
            .replace(/^## (.*$)/gim, '<h2>$1</h2>')
            .replace(/^### (.*$)/gim, '<h3>$1</h3>')
            .replace(/\*\*(.*?)\*\*/gim, '<strong>$1</strong>')
            .replace(/\*(.*?)\*/gim, '<em>$1</em>');

    } catch (err) {
        console.error(err);
        content.innerHTML = `<div style="color:var(--danger); text-align:center;">Failed to generate review: ${err.message}</div>`;
    }
};

window.closeSynthesisModal = () => {
    hideModal('synthesisModal');
};

window.exportSynthesis = () => {
    // We can export this as a special "Paper" ID or just file download?
    // Since export_service handles "Paper" dict, we might need a hack.
    // Or we just client-side download.
    const blob = new Blob([currentReviewMarkdown], { type: 'text/markdown' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `Literature_Review_${new Date().toISOString().slice(0, 10)}.md`;
    a.click();
    URL.revokeObjectURL(url);
};

// Also we need to track visible papers for re-rendering
let currentVisiblePapers = [];
const originalRender = renderPaperGrid;
renderPaperGrid = (papers, options = {}) => {
    if (options.append) {
        currentVisiblePapers = currentVisiblePapers.concat(papers);
    } else {
        currentVisiblePapers = papers;
    }
    originalRender(papers, options);
};

// Vision Support
let currentVisionPaperId = null;
let currentVisionImage = null;

window.openFigures = async (id) => {
    currentVisionPaperId = id;
    recordTrail({ type: 'figures', paper_id: id, label: `Figures: ${getPaperTitleById(id)}` });
    const gallery = document.getElementById('figureGallery');

    showModal('figureModal');
    gallery.innerHTML = '<div class="loader"></div>';

    try {
        const res = await fetch(`${API_BASE}/papers/${encodeURIComponent(id)}/images`);
        if (!res.ok) throw new Error("Failed to fetch images");

        const images = await res.json();

        if (images.length === 0) {
            gallery.innerHTML = '<div style="grid-column:1/-1; text-align:center; padding:2rem;">No figures found (or PDF not downloaded).</div>';
            return;
        }

        gallery.innerHTML = '';
        images.forEach(img => {
            const card = document.createElement('div');
            card.className = 'figure-card';
            card.innerHTML = `
                <img src="${img.src}" loading="lazy">
                <div class="actions">
                    <button class="btn-primary" style="font-size:0.8rem; padding:0.4rem 0.8rem;" onclick="openVisionChat('${img.src}')">
                        <i class="fa-solid fa-eye"></i> Analyze
                    </button>
                </div>
            `;
            gallery.appendChild(card);
        });

    } catch (e) {
        console.error(e);
        gallery.innerHTML = `<div style="color:var(--danger)">Error: ${e.message}</div>`;
    }
};

window.closeFigureModal = () => {
    hideModal('figureModal');
};

window.openVisionChat = (imgSrc) => {
    currentVisionImage = imgSrc; // Base64
    document.getElementById('visionTargetImage').src = imgSrc;

    // Clear history
    const history = document.getElementById('visionChatHistory');
    history.innerHTML = `
        <div class="chat-message system">
            <div class="message-content">
                I see the image. What would you like to know about it?
            </div>
        </div>
    `;

    showModal('visionChatModal');
};

window.closeVisionModal = () => {
    hideModal('visionChatModal');
};

window.sendVisionMessage = async () => {
    const input = document.getElementById('visionChatInput');
    const msg = input.value.trim();
    if (!msg) return;

    // Add user message
    const history = document.getElementById('visionChatHistory');
    history.innerHTML += `
        <div class="chat-message user">
            <div class="message-content">${msg}</div>
        </div>
    `;
    input.value = '';

    // Loading state
    history.innerHTML += `
        <div class="chat-message system" id="visionLoading">
            <div class="message-content"><i class="fa-solid fa-spinner fa-spin"></i> Analyzing...</div>
        </div>
    `;
    history.scrollTop = history.scrollHeight;

    try {
        const payload = {
            paper_id: currentVisionPaperId,
            query: msg,
            image: currentVisionImage.split(',')[1] // Remove data:image/...;base64, prefix
        };

        const res = await fetch(`${API_BASE}/chat`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });

        const data = await res.json();

        // Remove loader
        document.getElementById('visionLoading').remove();

        // Add AI response
        history.innerHTML += `
            <div class="chat-message system">
                <div class="message-content">${data.response.replace(/\n/g, '<br>')}</div>
            </div>
        `;

    } catch (e) {
        if (document.getElementById('visionLoading')) document.getElementById('visionLoading').remove();
        history.innerHTML += `<div class="chat-message system"><div class="message-content" style="color:var(--danger)">Error: ${e.message}</div></div>`;
    }

    history.scrollTop = history.scrollHeight;
};

// Research Agent Logic
let agentInterval = null;
let activeAgentJobId = null;

window.openAgentModal = () => {
    showModal('agentModal');

    // Check if we have an active job
    if (activeAgentJobId) {
        // Resume view
        document.getElementById('agentInputState').classList.add('hidden');

        // Decide whether to show running or result based on last known state?
        // Simplest is to show Running and let the next poll update it (or finish it).
        // If it was already finished, pollAgent will switch to result.
        document.getElementById('agentRunningState').classList.remove('hidden');
        document.getElementById('agentResultState').classList.add('hidden'); // Reset just in case

        // Resume polling if not active
        if (!agentInterval) {
            pollAgent(activeAgentJobId); // Immediate check
            agentInterval = setInterval(() => pollAgent(activeAgentJobId), 1500);
        }
    } else {
        // New Session
        document.getElementById('agentInputState').classList.remove('hidden');
        document.getElementById('agentRunningState').classList.add('hidden');
        document.getElementById('agentResultState').classList.add('hidden');
    }
};

window.closeAgentModal = () => {
    hideModal('agentModal');
    // Stop polling to save resources, but keep the active ID so we can resume.
    if (agentInterval) {
        clearInterval(agentInterval);
        agentInterval = null;
    }
};

window.startAgentJob = async () => {
    const topic = document.getElementById('agentTopic').value.trim();
    if (!topic) return;

    // Switch to Running State
    document.getElementById('agentInputState').classList.add('hidden');
    document.getElementById('agentRunningState').classList.remove('hidden');
    document.getElementById('agentLogs').innerHTML = '<div style="color:#00ff00">> INITIALIZING SEQUENCE...</div>';

    try {
        const res = await fetch(`${API_BASE}/agent/research`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ topic: topic })
        });

        if (!res.ok) throw new Error("Failed to start agent");

        const data = await res.json();
        activeAgentJobId = data.job_id;

        // Start Polling
        agentInterval = setInterval(() => pollAgent(activeAgentJobId), 1500);

    } catch (e) {
        document.getElementById('agentLogs').innerHTML += `<div style="color:red">ERROR: ${e.message}</div>`;
    }
};

async function pollAgent(jobId) {
    try {
        const res = await fetch(`${API_BASE}/agent/${jobId}`);
        const data = await res.json();

        // Update Logs
        const logContainer = document.getElementById('agentLogs');
        // Only append new logs? Or replace? Replacing is easier for syncing.
        // But if user scrolled up?
        // Let's just replace for now.
        logContainer.innerHTML = data.logs.map(l => `<div>> ${l}</div>`).join('');
        // Auto scroll
        logContainer.scrollTop = logContainer.scrollHeight;

        if (data.status === 'completed') {
            clearInterval(agentInterval);
            agentInterval = null;
            // Keep the ID active so the user can see the result if they reopen

            // Show Result
            document.getElementById('agentRunningState').classList.add('hidden');
            document.getElementById('agentResultState').classList.remove('hidden');
            await ensureMarkdownLibs();
            document.getElementById('agentFinalReport').innerHTML = renderMarkdownSafe(data.result);

            // Clear active ID only if user explicitly resets? 
            // For now, let's keep it until they close or we add a "New Search" button.
            // Actually, if we keep it, they can't start a new one.
            // Let's add a "New Search" button in the result view?
            // For now, we'll leave it as is.
        } else if (data.status === 'error') {
            clearInterval(agentInterval);
            agentInterval = null;
            logContainer.innerHTML += `<div style="color:red">> SYSTEM FAILURE.</div>`;
        }

    } catch (e) {
        console.error("Polling error", e);
    }
}

window.resetAgentUI = () => {
    activeAgentJobId = null;
    if (agentInterval) {
        clearInterval(agentInterval);
        agentInterval = null;
    }
    document.getElementById('agentInputState').classList.remove('hidden');
    document.getElementById('agentRunningState').classList.add('hidden');
    document.getElementById('agentResultState').classList.add('hidden');
    document.getElementById('agentTopic').value = '';
    document.getElementById('agentLogs').innerHTML = '';
};

// --- Library Chat Logic ---

window.openLibraryChatModal = () => {
    showModal('libChatModal');
    document.getElementById('libChatInput').focus();
};

window.closeLibraryChatModal = () => {
    hideModal('libChatModal');
};

window.handleLibChatInput = (e) => {
    if (e.key === 'Enter') sendLibChatMessage();
};

window.sendLibChatMessage = async () => {
    const input = document.getElementById('libChatInput');
    const msg = input.value.trim();
    if (!msg) return;

    // Add User Message
    const history = document.getElementById('libChatHistory');
    history.innerHTML += `
        <div class="chat-message user">
            <div class="message-content">${msg}</div>
        </div>
    `;
    input.value = '';
    history.scrollTop = history.scrollHeight;

    // Show Loading
    const loadingId = 'lib_loading_' + Date.now();
    history.innerHTML += `
        <div id="${loadingId}" class="chat-message system">
             <div class="message-content"><i class="fas fa-spinner fa-spin"></i> Searching library...</div>
        </div>
    `;
    history.scrollTop = history.scrollHeight;

    try {
        const res = await fetch(`${API_BASE}/chat/library`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ query: msg })
        });

        const data = await res.json();
        await ensureMarkdownLibs();
        const responseText = data.response ? renderMarkdownSafe(data.response) : "Error: No response.";

        // Remove loading
        document.getElementById(loadingId).remove();

        // Add AI Message
        history.innerHTML += `
            <div class="chat-message system">
                 <div class="message-content markdown-body">${responseText}</div>
            </div>
        `;
        history.scrollTop = history.scrollHeight;

    } catch (e) {
        document.getElementById(loadingId).innerHTML = `<div class="message-content" style="color:red">Error: ${e.message}</div>`;
    }
};

// --- Discovery Logic ---

window.openDiscoverModal = () => {
    showModal('discoverModal');
};

window.closeDiscoverModal = () => {
    hideModal('discoverModal');
};

window.cancelDiscoverJob = async () => {
    if (!activeDiscoverJobId) return;
    try {
        await requestJobCancel(activeDiscoverJobId);
        const statusEl = document.getElementById('discoverStatus');
        if (statusEl) {
            statusEl.innerHTML = `<div><i class="fas fa-spinner fa-spin"></i> Cancel requested. Finishing current step...</div>`;
        }
    } catch (e) {
        alert(`Failed to cancel discovery: ${e.message}`);
    }
};

window.runDiscovery = async () => {
    if (activeDiscoverJobId) {
        alert("Discovery is already running. You can cancel it from the status panel.");
        return;
    }
    const statusEl = document.getElementById('discoverStatus');
    const resultsEl = document.getElementById('discoverResults');

    // Set Loading State
    statusEl.innerHTML = `
        <div style="display:flex; align-items:center; gap:0.6rem; flex-wrap:wrap;">
            <span><i class="fas fa-spinner fa-spin"></i> Queueing discovery workflow...</span>
            <button class="btn-secondary" onclick="cancelDiscoverJob()" style="padding:0.3rem 0.65rem;">
                <i class="fa-solid fa-ban"></i> Cancel
            </button>
        </div>
    `;
    resultsEl.innerHTML = '<div class="loader"></div>';

    try {
        const jobId = await submitJob('/jobs/discover');
        activeDiscoverJobId = jobId;
        const data = await waitForJob(jobId, {
            onUpdate: (job) => {
                const label = job.status === 'running'
                    ? `Analyzing library and querying Global ArXiv (${Math.round(Number(job.progress_percent || 0))}%)`
                    : job.status === 'canceling'
                        ? 'Canceling discovery workflow...'
                        : `Waiting in queue (#${job.queue_position || '?'})`;
                const eta = job.eta_seconds != null ? ` ETA ${formatJobEta(job.eta_seconds)}` : '';
                statusEl.innerHTML = `
                    <div style="display:flex; align-items:center; gap:0.6rem; flex-wrap:wrap;">
                        <span><i class="fas fa-spinner fa-spin"></i> ${label}${eta}</span>
                        <button class="btn-secondary" onclick="cancelDiscoverJob()" style="padding:0.3rem 0.65rem;">
                            <i class="fa-solid fa-ban"></i> Cancel
                        </button>
                    </div>
                `;
            }
        });
        activeDiscoverJobId = null;

        // Show Queries Used
        const queryTags = data.queries.map(q => `<span class="tag" style="background:rgba(255,255,255,0.1); color:white;">${q}</span>`).join(' ');
        statusEl.innerHTML = `<div>Generated Queries: ${queryTags}</div>`;

        // Render Results
        resultsEl.innerHTML = '';

        if (!data.papers || data.papers.length === 0) {
            resultsEl.innerHTML = '<div style="grid-column:1/-1; text-align:center;">No new papers found. Try adding more favorites to guide the AI.</div>';
            return;
        }

        data.papers.forEach(p => {
            const card = document.createElement('div');
            card.className = 'paper-card';
            const reasons = Array.isArray(p.recommendation_reasons) ? p.recommendation_reasons : [];
            const queryHits = Array.isArray(p.discovery_queries) ? p.discovery_queries : [];
            const authors = Array.isArray(p.authors) ? p.authors : [];
            const recommendationScore = Number(p.recommendation_score || 0);

            // Simplified Card for Discovery
            card.innerHTML = `
                <div class="score-badge" style="background: rgba(250, 204, 21, 0.2); color: #facc15;">Discovery</div>
                <div class="paper-title" onclick="openLink(decodeURIComponent('${encodeURIComponent(String(p.pdf_url || ''))}'))">${escapeHtml(String(p.title || 'Untitled'))}</div>
                <div class="paper-meta">
                    ${escapeHtml(authors.slice(0, 3).join(', '))} • ${escapeHtml(String(p.published || '').substring(0, 10))}
                </div>
                <div style="display:flex; gap:0.4rem; flex-wrap:wrap; margin:0.35rem 0 0.2rem;">
                    <span class="tag" style="background:rgba(250,204,21,0.14); color:#fde68a;">score ${recommendationScore.toFixed(2)}</span>
                    ${queryHits.slice(0, 2).map((q) => `<span class="tag" style="background:rgba(56,189,248,0.14); color:#7dd3fc;">${escapeHtml(String(q).slice(0, 30))}</span>`).join('')}
                </div>
                <div class="paper-summary" style="-webkit-line-clamp: 3;">${escapeHtml(String(p.summary || ''))}</div>
                ${reasons.length ? `<ul style="margin:0.45rem 0 0.1rem 1.1rem; color:var(--text-muted); font-size:0.84rem;">${reasons.slice(0, 3).map((r) => `<li>${escapeHtml(String(r))}</li>`).join('')}</ul>` : ''}
                <div class="card-actions">
                    <a href="${escapeHtml(String(p.pdf_url || ''))}" target="_blank" class="pdf-link"><i class="fa-regular fa-file-pdf"></i> PDF</a>
                    <button class="action-btn" onclick="fetchAndSave(decodeURIComponent('${encodeURIComponent(String(p.id || ''))}'))" title="Add to Library">
                        <i class="fa-solid fa-plus"></i> Add
                    </button>
                    <a href="https://arxiv.org/abs/${encodeURIComponent(String((p.id || '').split('v')[0] || ''))}" target="_blank" class="code-link" style="margin-left:auto;">ArXiv Page</a>
                </div>
             `;
            resultsEl.appendChild(card);
        });

    } catch (e) {
        activeDiscoverJobId = null;
        statusEl.innerText = `Error: ${e.message}`;
        resultsEl.innerHTML = `<div style="color:red; text-align:center;">Failed to run discovery.</div>`;
    }
};

window.fetchAndSave = async (paperId) => {
    // We can simulate a fetch by calling specific endpoint or just letting user know
    // The paper is already 'returned' by API but maybe not saved to 'new' feed by default
    // In server implementation, we actually saved them to DB.
    // So 'Add' might just mean "Bookmark" or "Rate Liked"?
    // For now, let's just toast and maybe bookmark it.

    // We'll bookmark it to "Reading List" contextually
    await fetch(`${API_BASE}/papers/${encodeURIComponent(paperId)}/bookmark`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ active: true })
    });

    alert("Paper added to your Reading List!");
};

// --- Battle Mode Logic ---

window.updateSelectionUI = () => {
    const count = selectedPaperIds.size;
    const bar = document.getElementById('selectionBar');
    const countEl = document.getElementById('selectionCount');
    const battleBtn = document.getElementById('battleBtn');
    const matrixBtn = document.getElementById('matrixBtn');
    const compareDiffBtn = document.getElementById('compareDiffBtn');
    const crossPaperQaBtn = document.getElementById('crossPaperQaBtn');
    const benchmarkBtn = document.getElementById('benchmarkBtn');
    const batchTagBtn = document.getElementById('batchTagBtn');
    const citationOverlayBtn = document.getElementById('citationOverlayBtn');
    const relatedGraphBtn = document.getElementById('relatedGraphBtn');

    if (count > 0) {
        bar.classList.remove('hidden');
        countEl.innerText = `${count} Selected`;
        if (batchTagBtn) batchTagBtn.style.display = 'block';

        // Show Battle button ONLY if exactly 2 papers are selected
        if (count === 2) {
            battleBtn.style.display = 'block';
        } else {
            battleBtn.style.display = 'none';
        }

        if (compareDiffBtn) {
            compareDiffBtn.style.display = count === 2 ? 'block' : 'none';
        }
        if (crossPaperQaBtn) {
            crossPaperQaBtn.style.display = count >= 2 ? 'block' : 'none';
        }

        // Matrix supports 2..6 papers
        if (count >= 2 && count <= 6) {
            matrixBtn.style.display = 'block';
        } else {
            matrixBtn.style.display = 'none';
        }

        // Benchmark extractor supports 2..8 papers.
        if (count >= 2 && count <= 8) {
            benchmarkBtn.style.display = 'block';
        } else {
            benchmarkBtn.style.display = 'none';
        }
        if (citationOverlayBtn) {
            citationOverlayBtn.style.display = count >= 2 ? 'block' : 'none';
        }
        if (relatedGraphBtn) {
            relatedGraphBtn.style.display = count >= 1 ? 'block' : 'none';
        }
    } else {
        bar.classList.add('hidden');
        battleBtn.style.display = 'none';
        matrixBtn.style.display = 'none';
        if (compareDiffBtn) compareDiffBtn.style.display = 'none';
        if (crossPaperQaBtn) crossPaperQaBtn.style.display = 'none';
        benchmarkBtn.style.display = 'none';
        if (batchTagBtn) batchTagBtn.style.display = 'none';
        if (citationOverlayBtn) citationOverlayBtn.style.display = 'none';
        if (relatedGraphBtn) relatedGraphBtn.style.display = 'none';
    }
};

// Override the existing updateSelectionUI or just rely on this one if defined later? 
// app.js functions are hoisted or assigned to window. 
// If updateSelectionUI was defined previously, we need to make sure this overwrites it or we modify the original.
// Let's modify the original if possible, but finding it is hard with replace.
// Javascript allows overwriting. If we define `window.updateSelectionUI` here, it should work IF the original was also assigned to window or if we replace the function definition.
// Wait, `toggleSelectionMode` calls `updateSelectionUI`.
// Let's modify the ORIGINAL updateSelectionUI to insert the battle logic.

window.openCrossPaperQaModal = () => {
    const count = selectedPaperIds.size;
    if (count < 2) {
        alert("Select at least 2 papers first.");
        return;
    }
    showModal('crossPaperQaModal');
    const questionInput = document.getElementById('crossPaperQaQuestionInput');
    if (questionInput && !questionInput.value.trim()) {
        questionInput.value = 'What are the main method differences and trade-offs across these papers?';
    }
    const metaEl = document.getElementById('crossPaperQaMeta');
    if (metaEl) metaEl.textContent = `${count} selected papers ready.`;
    const answerEl = document.getElementById('crossPaperQaAnswer');
    if (answerEl) answerEl.textContent = 'No answer yet.';
    const sourcesEl = document.getElementById('crossPaperQaSources');
    if (sourcesEl) sourcesEl.innerHTML = '';
};

window.closeCrossPaperQaModal = () => {
    hideModal('crossPaperQaModal');
};

window.runCrossPaperQa = async () => {
    const questionInput = document.getElementById('crossPaperQaQuestionInput');
    const topKInput = document.getElementById('crossPaperQaTopKInput');
    const metaEl = document.getElementById('crossPaperQaMeta');
    const answerEl = document.getElementById('crossPaperQaAnswer');
    const sourcesEl = document.getElementById('crossPaperQaSources');
    const question = (questionInput?.value || '').trim();
    const topKRaw = Number(topKInput?.value || 5);
    const topK = Number.isFinite(topKRaw) ? Math.max(1, Math.min(12, Math.round(topKRaw))) : 5;
    const paperIds = Array.from(selectedPaperIds);
    if (paperIds.length < 2) {
        alert("Select at least 2 papers.");
        return;
    }
    if (!question) {
        alert("Enter a question.");
        return;
    }

    if (metaEl) metaEl.textContent = `Asking across ${paperIds.length} papers...`;
    if (answerEl) answerEl.innerHTML = '<div class="loader"></div>';
    if (sourcesEl) sourcesEl.innerHTML = '';

    try {
        const res = await fetch(`${API_BASE}/cross-paper-qa`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ paper_ids: paperIds, question, top_k: topK })
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Cross-paper QA failed");
        await ensureMarkdownLibs();
        if (answerEl) {
            answerEl.innerHTML = renderMarkdownSafe(data.answer || "No answer generated.");
        }
        if (metaEl) {
            metaEl.textContent = `${Number(data.count_selected || paperIds.length)} papers · ${Number(data.count_sources || 0)} sources${data.cached ? ' · cached' : ''}`;
        }
        const sources = Array.isArray(data.sources) ? data.sources : [];
        if (sourcesEl) {
            if (!sources.length) {
                sourcesEl.innerHTML = '<div style="color:var(--text-muted);">No source snippets returned.</div>';
            } else {
                sourcesEl.innerHTML = sources.map((s) => `
                    <div style="border:1px solid rgba(255,255,255,0.12); border-radius:9px; padding:0.65rem; background:rgba(255,255,255,0.03);">
                        <div style="display:flex; justify-content:space-between; gap:0.5rem; align-items:flex-start;">
                            <div style="font-weight:600;">[${escapeHtml(String(s.tag || 'S'))}] ${escapeHtml(String(s.title || s.paper_id || 'Paper'))}</div>
                            <div style="font-size:0.78rem; color:var(--text-muted);">score ${Number(s.relevance_score || 0).toFixed(2)}</div>
                        </div>
                        <div style="font-size:0.84rem; color:var(--text-muted); margin-top:0.28rem;">
                            ${escapeHtml(String(s.published || '').slice(0, 10))} · <code>${escapeHtml(String(s.paper_id || ''))}</code>
                        </div>
                        <div style="margin-top:0.35rem;">${escapeHtml(String(s.snippet || ''))}</div>
                    </div>
                `).join('');
            }
        }
    } catch (e) {
        if (metaEl) metaEl.textContent = `Failed: ${e.message}`;
        if (answerEl) answerEl.innerHTML = `<div style="color:var(--danger)">Failed to run QA: ${escapeHtml(e.message)}</div>`;
    }
};

window.startBattle = async () => {
    const paperIds = Array.from(selectedPaperIds);
    if (paperIds.length !== 2) {
        alert("Please select exactly 2 papers for a battle.");
        return;
    }

    showModal('battleModal');
    const content = document.getElementById('battleContent');
    content.innerHTML = '<div style="text-align:center; padding:2rem;"><div class="loader"></div><h2>Refereeing Match...</h2><p>Analyzing Methodology, Claims, and Weaknesses.</p></div>';

    try {
        const res = await fetch(`${API_BASE}/compare`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ paper_ids: paperIds })
        });

        const data = await res.json();

        if (data.result) {
            await ensureMarkdownLibs();
            content.innerHTML = renderMarkdownSafe(data.result);
        } else {
            content.innerHTML = "Error: No result generated.";
        }

    } catch (e) {
        content.innerHTML = `<div style="color:red">Error: ${e.message}</div>`;
    }
};

window.startCompareMatrix = async () => {
    if (activeCompareMatrixJobId) {
        alert("A compare matrix job is already running. Cancel it first if needed.");
        return;
    }
    const paperIds = Array.from(selectedPaperIds);
    if (paperIds.length < 2) {
        alert("Please select at least 2 papers.");
        return;
    }
    if (paperIds.length > 6) {
        alert("Compare Matrix supports up to 6 papers for readability.");
        return;
    }

    recordTrail({ type: 'compare_matrix', paper_ids: paperIds, label: `Compare Matrix (${paperIds.length})` });
    showModal('compareMatrixModal');
    const content = document.getElementById('compareMatrixContent');
    content.innerHTML = `
        <div style="text-align:center; padding:2rem;">
            <div class="loader"></div>
            <p id="compareMatrixStatus">Queueing comparison matrix job...</p>
            <button class="btn-secondary" onclick="cancelCompareMatrixJob()" style="padding:0.35rem 0.8rem; margin-top:0.6rem;">
                <i class="fa-solid fa-ban"></i> Cancel
            </button>
        </div>
    `;

    try {
        const jobId = await submitJob('/jobs/compare-matrix', { paper_ids: paperIds });
        activeCompareMatrixJobId = jobId;
        const data = await waitForJob(jobId, {
            onUpdate: (job) => {
                const statusEl = document.getElementById('compareMatrixStatus');
                if (!statusEl) return;
                statusEl.textContent = job.status === 'running'
                    ? `Building comparison matrix (${Math.round(Number(job.progress_percent || 0))}%) ETA ${formatJobEta(job.eta_seconds)}`
                    : job.status === 'canceling'
                        ? 'Canceling comparison matrix...'
                        : `Waiting in queue (#${job.queue_position || '?'}) ETA ${formatJobEta(job.eta_seconds)}`;
            }
        });
        activeCompareMatrixJobId = null;
        const cacheNote = data.cached ? '<div style="font-size:0.82rem; color:var(--text-muted); margin-bottom:0.5rem;">Loaded from cache</div>' : '';
        await ensureMarkdownLibs();
        content.innerHTML = cacheNote + renderMarkdownSafe(data.result || "No matrix generated.");
    } catch (e) {
        activeCompareMatrixJobId = null;
        content.innerHTML = `<div style="color:var(--danger)">Failed to build matrix: ${e.message}</div>`;
    }
};

window.cancelCompareMatrixJob = async () => {
    if (!activeCompareMatrixJobId) return;
    try {
        await requestJobCancel(activeCompareMatrixJobId);
        const statusEl = document.getElementById('compareMatrixStatus');
        if (statusEl) statusEl.textContent = 'Cancel requested. Finishing current step...';
    } catch (e) {
        alert(`Failed to cancel matrix job: ${e.message}`);
    }
};

window.closeCompareMatrixModal = () => {
    hideModal('compareMatrixModal');
};

function formatCompareText(text) {
    const safe = escapeHtml(text || 'N/A');
    return safe.replace(/\n/g, '<br>');
}

window.startCompareDiff = async () => {
    const paperIds = Array.from(selectedPaperIds);
    if (paperIds.length !== 2) {
        alert("Please select exactly 2 papers.");
        return;
    }

    recordTrail({ type: 'compare_diff', paper_ids: paperIds, label: `Side-by-side (${paperIds.length})` });
    showModal('compareDiffModal');
    const content = document.getElementById('compareDiffContent');
    if (content) {
        content.innerHTML = `
            <div style="text-align:center; padding:2rem;">
                <div class="loader"></div>
                <p>Building side-by-side diff...</p>
            </div>
        `;
    }

    try {
        const res = await fetch(`${API_BASE}/compare/diff`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ paper_ids: paperIds })
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || 'Failed to compare papers.');

        const papers = data.papers || [];
        const diffs = data.diffs || {};
        if (papers.length !== 2) throw new Error('Unexpected compare response.');

        const [a, b] = papers;
        const fields = [
            { key: 'method', label: 'Method' },
            { key: 'dataset', label: 'Dataset / Eval' },
            { key: 'results', label: 'Results' },
        ];

        const rows = fields.map((f) => {
            const isDiff = Boolean(diffs[f.key]);
            const aText = formatCompareText((a.structure || {})[f.key]);
            const bText = formatCompareText((b.structure || {})[f.key]);
            return `
                <tr class="${isDiff ? 'diff-row' : ''}">
                    <td class="diff-label">${escapeHtml(f.label)}</td>
                    <td>${aText}</td>
                    <td>${bText}</td>
                </tr>
            `;
        }).join('');

        if (content) {
            content.innerHTML = `
                <div class="compare-diff-head">
                    <div class="compare-diff-col">
                        <div class="compare-diff-title">${escapeHtml(a.title || a.id || 'Paper A')}</div>
                        <div class="compare-diff-sub">${escapeHtml(a.id || '')}</div>
                    </div>
                    <div class="compare-diff-col">
                        <div class="compare-diff-title">${escapeHtml(b.title || b.id || 'Paper B')}</div>
                        <div class="compare-diff-sub">${escapeHtml(b.id || '')}</div>
                    </div>
                </div>
                <div class="compare-diff-note">Highlighted rows differ between papers.</div>
                <table class="compare-diff-table">
                    <thead>
                        <tr>
                            <th></th>
                            <th>Paper A</th>
                            <th>Paper B</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${rows}
                    </tbody>
                </table>
            `;
        }
    } catch (e) {
        if (content) content.innerHTML = `<div style="color:var(--danger)">Failed to compare: ${escapeHtml(e.message)}</div>`;
    }
};

window.closeCompareDiffModal = () => {
    hideModal('compareDiffModal');
};

function benchmarkNumeric(value) {
    const match = String(value || '').replace(',', '.').match(/-?[0-9]+(?:\.[0-9]+)?/);
    if (!match) return null;
    return Number(match[0]);
}

function sortBenchmarkRows(rows, sortKey, sortDir) {
    const copied = rows.slice();
    copied.sort((a, b) => {
        if (sortKey === 'dataset' || sortKey === 'metric') {
            const av = String(a[sortKey] || '').toLowerCase();
            const bv = String(b[sortKey] || '').toLowerCase();
            return av.localeCompare(bv) * sortDir;
        }
        if (sortKey.startsWith('paper:')) {
            const pid = sortKey.slice('paper:'.length);
            const avRaw = (a.values || {})[pid] || '';
            const bvRaw = (b.values || {})[pid] || '';
            const avNum = benchmarkNumeric(avRaw);
            const bvNum = benchmarkNumeric(bvRaw);
            if (avNum != null && bvNum != null) return (avNum - bvNum) * sortDir;
            return String(avRaw).localeCompare(String(bvRaw)) * sortDir;
        }
        return 0;
    });
    return copied;
}

window.sortBenchmarkBy = (sortKey) => {
    if (!benchmarkTableState.payload) return;
    if (benchmarkTableState.sortKey === sortKey) {
        benchmarkTableState.sortDir *= -1;
    } else {
        benchmarkTableState.sortKey = sortKey;
        benchmarkTableState.sortDir = 1;
    }
    renderBenchmarkTable(benchmarkTableState.payload);
};

function renderBenchmarkTable(payload) {
    const container = document.getElementById('benchmarkContent');
    if (!container) return;
    const columns = Array.isArray(payload.columns) ? payload.columns : [];
    const rows = Array.isArray(payload.rows) ? payload.rows : [];
    const sorted = sortBenchmarkRows(rows, benchmarkTableState.sortKey, benchmarkTableState.sortDir);
    const arrow = benchmarkTableState.sortDir > 0 ? ' <i class="fa-solid fa-arrow-up-wide-short"></i>' : ' <i class="fa-solid fa-arrow-down-wide-short"></i>';

    const rowHtml = sorted.map((row) => `
        <tr>
            <td style="padding:0.48rem; border-bottom:1px solid rgba(255,255,255,0.08);">${escapeHtml(row.dataset || '')}</td>
            <td style="padding:0.48rem; border-bottom:1px solid rgba(255,255,255,0.08);">${escapeHtml(row.metric || '')}</td>
            ${columns.map((c) => `<td style="padding:0.48rem; border-bottom:1px solid rgba(255,255,255,0.08);">${escapeHtml((row.values || {})[c.id] || 'n/a')}</td>`).join('')}
        </tr>
    `).join('');

    const notes = (payload.notes || []).map((n) => `<li>${escapeHtml(n)}</li>`).join('');
    container.innerHTML = `
        <div style="display:flex; justify-content:space-between; gap:0.6rem; align-items:center;">
            <div style="font-size:0.86rem; color:var(--text-muted);">
                ${payload.cached ? 'Loaded from cache' : 'Freshly extracted'} • ${Number(payload.count || columns.length)} papers
            </div>
            <button class="btn-secondary" onclick="startBenchmarkExtract()" style="padding:0.35rem 0.8rem;">
                <i class="fa-solid fa-rotate-right"></i> Re-run
            </button>
        </div>
        <div style="overflow:auto; border:1px solid rgba(255,255,255,0.12); border-radius:10px; margin-top:0.45rem;">
            <table style="width:100%; border-collapse:collapse; font-size:0.86rem;">
                <thead>
                    <tr>
                        <th style="text-align:left; padding:0.5rem; cursor:pointer; border-bottom:1px solid rgba(255,255,255,0.12);" onclick="sortBenchmarkBy('dataset')">
                            Dataset${benchmarkTableState.sortKey === 'dataset' ? arrow : ''}
                        </th>
                        <th style="text-align:left; padding:0.5rem; cursor:pointer; border-bottom:1px solid rgba(255,255,255,0.12);" onclick="sortBenchmarkBy('metric')">
                            Metric${benchmarkTableState.sortKey === 'metric' ? arrow : ''}
                        </th>
                        ${columns.map((c) => `
                            <th style="text-align:left; padding:0.5rem; cursor:pointer; border-bottom:1px solid rgba(255,255,255,0.12);" onclick="sortBenchmarkBy('paper:${c.id}')">
                                ${escapeHtml((c.title || 'Paper').slice(0, 28))}${benchmarkTableState.sortKey === `paper:${c.id}` ? arrow : ''}
                            </th>
                        `).join('')}
                    </tr>
                </thead>
                <tbody>
                    ${rowHtml || `<tr><td colspan="${2 + columns.length}" style="padding:0.65rem; color:var(--text-muted);">No benchmark rows extracted.</td></tr>`}
                </tbody>
            </table>
        </div>
        ${notes ? `<ul style="margin:0.6rem 0 0 1.1rem; color:var(--text-muted); font-size:0.85rem;">${notes}</ul>` : ''}
    `;
}

window.startBenchmarkExtract = async () => {
    if (activeBenchmarkJobId) {
        alert("Benchmark extraction is already running.");
        return;
    }
    const paperIds = Array.from(selectedPaperIds);
    if (paperIds.length < 2) {
        alert("Please select at least 2 papers.");
        return;
    }
    if (paperIds.length > 8) {
        alert("Benchmark extraction supports up to 8 papers.");
        return;
    }

    recordTrail({ type: 'benchmark', paper_ids: paperIds, label: `Benchmarks (${paperIds.length})` });
    showModal('benchmarkModal');
    const content = document.getElementById('benchmarkContent');
    content.innerHTML = `
        <div style="text-align:center; padding:2rem;">
            <div class="loader"></div>
            <p id="benchmarkStatus">Queueing benchmark extraction...</p>
            <button class="btn-secondary" onclick="cancelBenchmarkExtract()" style="padding:0.35rem 0.8rem; margin-top:0.6rem;">
                <i class="fa-solid fa-ban"></i> Cancel
            </button>
        </div>
    `;

    try {
        const jobId = await submitJob('/jobs/benchmark-extract', { paper_ids: paperIds });
        activeBenchmarkJobId = jobId;
        const data = await waitForJob(jobId, {
            onUpdate: (job) => {
                const statusEl = document.getElementById('benchmarkStatus');
                if (!statusEl) return;
                statusEl.textContent = job.status === 'running'
                    ? `Extracting benchmark evidence (${Math.round(Number(job.progress_percent || 0))}%) ETA ${formatJobEta(job.eta_seconds)}`
                    : job.status === 'canceling'
                        ? 'Canceling benchmark extraction...'
                        : `Waiting in queue (#${job.queue_position || '?'}) ETA ${formatJobEta(job.eta_seconds)}`;
            }
        });
        activeBenchmarkJobId = null;
        benchmarkTableState.payload = data;
        benchmarkTableState.sortKey = 'dataset';
        benchmarkTableState.sortDir = 1;
        renderBenchmarkTable(data);
    } catch (e) {
        activeBenchmarkJobId = null;
        content.innerHTML = `<div style="color:var(--danger)">Failed to extract benchmarks: ${escapeHtml(e.message)}</div>`;
    }
};

window.cancelBenchmarkExtract = async () => {
    if (!activeBenchmarkJobId) return;
    try {
        await requestJobCancel(activeBenchmarkJobId);
        const statusEl = document.getElementById('benchmarkStatus');
        if (statusEl) statusEl.textContent = 'Cancel requested. Finishing current step...';
    } catch (e) {
        alert(`Failed to cancel benchmark extraction: ${e.message}`);
    }
};

window.closeBenchmarkModal = () => {
    hideModal('benchmarkModal');
};

window.openLineageModal = () => {
    showModal('lineageModal');
    const input = document.getElementById('lineageTopicInput');
    const searchInput = document.getElementById('searchInput');
    if (input && !input.value.trim() && searchInput && searchInput.value.trim()) {
        input.value = searchInput.value.trim();
    }
};

window.closeLineageModal = () => {
    hideModal('lineageModal');
    if (lineageNetwork) {
        try {
            lineageNetwork.destroy();
        } catch (_) { }
        lineageNetwork = null;
    }
};

function renderLineageChains(data) {
    const container = document.getElementById('lineageChains');
    if (!container) return;
    const chains = Array.isArray(data.chains) ? data.chains : [];
    if (chains.length === 0) {
        container.innerHTML = '<div style="color:var(--text-muted);">No lineage chains found for this topic.</div>';
        return;
    }

    container.innerHTML = chains.map((chain, idx) => {
        const items = (Array.isArray(chain) ? chain : []).map((node) => `
            <li style="margin-bottom:0.45rem;">
                <div style="display:flex; justify-content:space-between; gap:0.6rem;">
                    <a href="${API_BASE}/papers/${encodeURIComponent(node.id)}/pdf" target="_blank" class="pdf-link">
                        ${escapeHtml(node.title || node.id)}
                    </a>
                    <span class="tag" style="background:rgba(255,255,255,0.08);">${escapeHtml(node.phase || '')}</span>
                </div>
                <div style="font-size:0.82rem; color:var(--text-muted); margin-top:0.15rem;">${escapeHtml(node.published || '')}</div>
            </li>
        `).join('');
        return `
            <div style="border:1px solid rgba(255,255,255,0.1); border-radius:10px; padding:0.75rem; margin-bottom:0.65rem;">
                <div style="font-weight:700; margin-bottom:0.45rem;">Chain ${idx + 1}</div>
                <ol style="margin:0 0 0 1.1rem;">${items}</ol>
            </div>
        `;
    }).join('');
}

async function renderLineageGraph(data) {
    const container = document.getElementById('lineageGraph');
    if (!container) return;
    container.innerHTML = '<div style="text-align:center; padding-top:40%; color:var(--text-muted);">Loading graph...</div>';

    if (!Array.isArray(data.nodes) || data.nodes.length === 0) {
        container.innerHTML = '<div style="text-align:center; padding-top:40%; color:var(--text-muted);">No graph data.</div>';
        return;
    }

    try {
        await ensureVisLib();
    } catch (e) {
        container.innerHTML = `<div style="text-align:center; padding-top:40%; color:var(--danger);">Failed to load graph lib: ${escapeHtml(e.message)}</div>`;
        return;
    }

    const visNodes = new vis.DataSet((data.nodes || []).map((n) => {
        return {
            id: n.id,
            label: `${String(n.title || '').slice(0, 26)}${String(n.title || '').length > 26 ? '...' : ''}`,
            title: `${n.title || n.id}\n${n.published || ''}`,
            shape: 'dot',
            size: 18,
            color: { background: '#34d399', border: '#10b981' },
            font: { color: '#e2e8f0', size: 13 }
        };
    }));
    const visEdges = new vis.DataSet((data.edges || []).map((e) => ({
        from: e.source,
        to: e.target,
        arrows: 'to',
        width: 1 + Math.max(0, Number(e.score || 0) * 6),
        color: { color: 'rgba(56,189,248,0.55)' }
    })));

    container.innerHTML = '';
    if (lineageNetwork) {
        try {
            lineageNetwork.destroy();
        } catch (_) { }
    }
    lineageNetwork = new vis.Network(container, { nodes: visNodes, edges: visEdges }, {
        interaction: { hover: true },
        physics: {
            stabilization: false,
            barnesHut: { gravitationalConstant: -2200, springLength: 170, springConstant: 0.04 }
        },
        nodes: { shape: 'dot' },
        edges: { smooth: { type: 'continuous' } }
    });
}

window.runMethodLineage = async () => {
    const topicInput = document.getElementById('lineageTopicInput');
    const statusEl = document.getElementById('lineageStatus');
    const topic = topicInput ? topicInput.value.trim() : '';
    if (!topic) {
        alert("Please enter a topic.");
        return;
    }
    if (statusEl) statusEl.textContent = 'Building lineage graph and chains...';
    const chainContainer = document.getElementById('lineageChains');
    if (chainContainer) chainContainer.innerHTML = '<div class="loader"></div>';

    try {
        const res = await fetch(`${API_BASE}/lineage?topic=${encodeURIComponent(topic)}&max_nodes=20`);
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
        renderLineageChains(data);
        await renderLineageGraph(data);
        if (statusEl) {
            statusEl.textContent = `Found ${Number((data.nodes || []).length)} papers, ${Number((data.edges || []).length)} lineage links.`;
        }
    } catch (e) {
        if (statusEl) statusEl.textContent = `Failed to build lineage: ${e.message}`;
        if (chainContainer) {
            chainContainer.innerHTML = `<div style="color:var(--danger)">Failed to build lineage: ${escapeHtml(e.message)}</div>`;
        }
    }
};

window.closeBattleModal = () => {
    hideModal('battleModal');
};

// --- Galaxy View Logic ---
let galaxyChart = null;

window.toggleGalaxyView = async () => {
    const view = document.getElementById('galaxyView');
    if (!view.classList.contains('hidden')) {
        view.classList.add('hidden');
        currentView = 'grid';
        saveUIState();
        applySkimViewState();
        applyThreadsViewState();
        return;
    }

    // Hide other views
    document.getElementById('graphView').classList.add('hidden');
    document.getElementById('dashboard').classList.add('hidden');

    view.classList.remove('hidden');
    view.scrollIntoView({ behavior: 'smooth' });
    currentView = 'galaxy';
    saveUIState();
    applySkimViewState();
    applyThreadsViewState();

    try {
        await ensureChartLib();
    } catch (e) {
        alert(`Failed to load chart library: ${e.message}`);
        view.classList.add('hidden');
        currentView = 'grid';
        saveUIState();
        applySkimViewState();
        applyThreadsViewState();
        return;
    }

    // Fetch Data
    try {
        const res = await fetch(`${API_BASE}/galaxy`);
        const data = await res.json();

        if (!data.nodes || data.nodes.length === 0) {
            alert("Not enough data for Galaxy View (need > 3 papers with embeddings).");
            view.classList.add('hidden');
            currentView = 'grid';
            saveUIState();
            return;
        }

        renderGalaxy(data.nodes);

    } catch (e) {
        console.error(e);
        alert("Failed to load Galaxy.");
    }
};

window.closeGalaxyView = () => {
    document.getElementById('galaxyView').classList.add('hidden');
    currentView = 'grid';
    saveUIState();
    applySkimViewState();
    applyThreadsViewState();
};

function renderGalaxy(nodes) {
    const ctx = document.getElementById('galaxyChart').getContext('2d');

    if (galaxyChart) {
        galaxyChart.destroy();
    }

    // Map categories to colors
    const colors = {
        'cs.CL': '#f43f5e', // Red
        'cs.LG': '#3b82f6', // Blue
        'cs.AI': '#10b981', // Green
        'cs.CV': '#facc15', // Yellow
        'quant-ph': '#a855f7' // Purple
    };

    const datasets = [];
    // Group by category for legend? Or just one dataset with custom point styles?
    // Chart.js scatter supports array of pointBackgroundColors.

    const points = nodes.map(n => ({
        x: n.x,
        y: n.y,
        r: 6, // Radius
        paperId: n.id,
        title: n.title,
        category: n.category
    }));

    const pointColors = nodes.map(n => colors[n.category] || '#94a3b8'); // Gray fallback

    galaxyChart = new Chart(ctx, {
        type: 'scatter',
        data: {
            datasets: [{
                label: 'Papers',
                data: points,
                backgroundColor: pointColors,
                borderColor: 'rgba(0,0,0,0)', // No border
                hoverBorderColor: 'white',
                hoverBorderWidth: 2,
                pointHoverRadius: 10
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: {
                x: { display: false, grid: { display: false } }, // Hide axes
                y: { display: false, grid: { display: false } }
            },
            plugins: {
                legend: { display: false },
                tooltip: {
                    callbacks: {
                        label: function (context) {
                            const p = context.raw;
                            return `${p.title.substring(0, 40)}... (${p.category})`;
                        }
                    },
                    backgroundColor: 'rgba(0,0,0,0.8)',
                    titleFont: { size: 14 },
                    bodyFont: { size: 12 },
                    padding: 10
                }
            },
            onClick: (e, elements) => {
                if (elements.length > 0) {
                    const index = elements[0].index;
                    const paperId = points[index].paperId;
                    window.open(`${API_BASE}/papers/${encodeURIComponent(paperId)}/pdf`, '_blank');
                }
            }
        }
    });
}

window.closeConceptModal = () => {
    hideModal('conceptModal');
};

let conceptNetwork = null;

window.openConceptMap = async () => {
    showModal('conceptModal');

    const container = document.getElementById('conceptNetwork');
    container.innerHTML = '<div style="color:white; text-align:center; padding-top:20%;">Loading neural connection...</div>';
    try {
        await ensureVisLib();
    } catch (e) {
        container.innerHTML = `<div style="color:var(--danger); text-align:center; padding-top:20%;">Failed to load graph library: ${escapeHtml(e.message)}</div>`;
        return;
    }

    try {
        const res = await fetch(`${API_BASE}/concepts/graph`);
        const data = await res.json();

        if (data.nodes.length === 0) {
            container.innerHTML = '<div style="color:white; text-align:center; padding-top:20%;">No concepts tagged yet. Tag some papers!</div>';
            return;
        }

        const options = {
            nodes: {
                shape: 'dot',
                font: { size: 16, color: '#e2e8f0', face: 'Outfit' },
                color: { background: '#10b981', border: '#059669', highlight: '#34d399' }
            },
            edges: {
                color: { color: 'rgba(255,255,255,0.1)', highlight: '#34d399' },
                smooth: { type: 'continuous' }
            },
            physics: {
                stabilization: false,
                barnesHut: { gravitationalConstant: -3000, springConstant: 0.04, springLength: 95 }
            },
            interaction: { hover: true }
        };

        const visData = {
            nodes: new vis.DataSet(data.nodes),
            edges: new vis.DataSet(data.edges)
        };

        conceptNetwork = new vis.Network(container, visData, options);

        conceptNetwork.on("doubleClick", function (params) {
            if (params.nodes.length > 0) {
                const tag = data.nodes.find(n => n.id === params.nodes[0]).label;
                filterByConcept(tag);
                closeConceptModal();
            }
        });

    } catch (e) {
        console.error(e);
        container.innerHTML = 'Error loading graph.';
    }
};

// --- Smart Folders Logic ---
function resetFolderModalForm() {
    const title = document.getElementById('folderModalTitle');
    const submitBtn = document.getElementById('folderSubmitBtn');
    const nameInput = document.getElementById('folderNameInput');
    const queryInput = document.getElementById('folderQueryInput');
    const descInput = document.getElementById('folderDescriptionInput');
    const goalInput = document.getElementById('folderGoalInput');
    const targetInput = document.getElementById('folderTargetCountInput');
    const statusInput = document.getElementById('folderStatusInput');
    if (title) title.textContent = 'New Smart Collection';
    if (submitBtn) submitBtn.textContent = 'Create Collection';
    if (nameInput) nameInput.value = '';
    if (queryInput) queryInput.value = '';
    if (descInput) descInput.value = '';
    if (goalInput) goalInput.value = '';
    if (targetInput) targetInput.value = '0';
    if (statusInput) statusInput.value = 'active';
}

window.openCreateFolderModal = () => {
    activeFolderEditor = null;
    resetFolderModalForm();
    showModal('createFolderModal');
};

window.openEditFolderModal = (folder) => {
    if (!folder || !folder.id) return;
    activeFolderEditor = { id: String(folder.id) };
    const title = document.getElementById('folderModalTitle');
    const submitBtn = document.getElementById('folderSubmitBtn');
    const nameInput = document.getElementById('folderNameInput');
    const queryInput = document.getElementById('folderQueryInput');
    const descInput = document.getElementById('folderDescriptionInput');
    const goalInput = document.getElementById('folderGoalInput');
    const targetInput = document.getElementById('folderTargetCountInput');
    const statusInput = document.getElementById('folderStatusInput');
    if (title) title.textContent = 'Edit Collection';
    if (submitBtn) submitBtn.textContent = 'Save Collection';
    if (nameInput) nameInput.value = String(folder.name || '');
    if (queryInput) queryInput.value = String(folder.query || '');
    if (descInput) descInput.value = String(folder.description || '');
    if (goalInput) goalInput.value = String(folder.goal || '');
    if (targetInput) targetInput.value = String(Number(folder.target_count || 0));
    if (statusInput) statusInput.value = String(folder.status || 'active');
    showModal('createFolderModal');
};

window.closeCreateFolderModal = () => {
    hideModal('createFolderModal');
    activeFolderEditor = null;
    resetFolderModalForm();
};

window.createSmartFolder = async () => {
    const name = document.getElementById('folderNameInput').value.trim();
    const query = document.getElementById('folderQueryInput').value.trim();
    const description = document.getElementById('folderDescriptionInput')?.value?.trim() || '';
    const goal = document.getElementById('folderGoalInput')?.value?.trim() || '';
    const targetCountRaw = Number(document.getElementById('folderTargetCountInput')?.value || 0);
    const statusRaw = String(document.getElementById('folderStatusInput')?.value || 'active').toLowerCase();
    const status = ['active', 'paused', 'archived'].includes(statusRaw) ? statusRaw : 'active';
    const targetCount = Number.isFinite(targetCountRaw) ? Math.max(0, Math.round(targetCountRaw)) : 0;

    if (!name || !query) {
        alert("Please enter both a name and a search query.");
        return;
    }

    const payload = {
        name,
        query,
        description,
        goal,
        target_count: targetCount,
        status,
    };

    try {
        const isEdit = Boolean(activeFolderEditor?.id);
        const endpoint = activeFolderEditor?.id
            ? `${API_BASE}/folders/${encodeURIComponent(activeFolderEditor.id)}`
            : `${API_BASE}/folders`;
        const method = isEdit ? 'PUT' : 'POST';
        const res = await fetch(endpoint, {
            method,
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Failed to save collection");

        closeCreateFolderModal();
        fetchFolders();
        alert(isEdit ? "Collection updated." : "Collection created.");
    } catch (e) {
        alert(e.message);
    }
};

function computeNextFolderDue(schedule) {
    if (!schedule) return null;
    const cadence = (schedule.cadence || 'daily').toLowerCase();
    const base = schedule.last_run_at || schedule.created_at;
    if (!base) return null;
    const baseDt = new Date(base);
    if (!Number.isFinite(baseDt.getTime())) return null;
    const days = cadence === 'weekly' ? 7 : 1;
    return new Date(baseDt.getTime() + days * 24 * 3600 * 1000);
}

async function loadFolderSchedule(folderId) {
    const meta = document.getElementById('folderScheduleMeta');
    const cadenceInput = document.getElementById('folderScheduleCadence');
    const maxItemsInput = document.getElementById('folderScheduleMaxItems');
    const enabledInput = document.getElementById('folderScheduleEnabled');
    if (!folderId) return;
    if (meta) meta.textContent = 'Loading schedule...';

    try {
        const res = await fetch(`${API_BASE}/folders/${folderId}/schedule`);
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
        const schedule = data.schedule || data || {};

        const cadence = schedule.cadence || 'daily';
        const maxItems = Number(schedule.max_items || 10);
        const enabled = schedule.enabled !== false && Number(schedule.enabled || 1) !== 0;

        if (cadenceInput) cadenceInput.value = cadence;
        if (maxItemsInput) maxItemsInput.value = String(maxItems);
        if (enabledInput) enabledInput.checked = enabled;

        const lastRun = schedule.last_run_at ? formatLocalTimestamp(schedule.last_run_at) : 'never';
        const nextDue = computeNextFolderDue(schedule);
        const nextLabel = nextDue ? formatLocalTimestamp(nextDue.toISOString()) : 'n/a';
        if (meta) meta.textContent = `Last run: ${lastRun} · Next due: ${nextLabel}`;
    } catch (e) {
        if (meta) meta.textContent = `Failed to load schedule: ${e.message}`;
    }
}

window.openFolderScheduleModal = (folderId, folderName) => {
    if (!folderId) return;
    activeFolderSchedule = { id: folderId, name: folderName || '' };
    const title = document.getElementById('folderScheduleTitle');
    if (title) title.textContent = folderName ? `Collection: ${folderName}` : 'Collection';
    showModal('folderScheduleModal');
    loadFolderSchedule(folderId);
};

window.closeFolderScheduleModal = () => {
    hideModal('folderScheduleModal');
    activeFolderSchedule = { id: null, name: '' };
};

window.saveFolderSchedule = async () => {
    if (!activeFolderSchedule.id) return;
    const cadenceInput = document.getElementById('folderScheduleCadence');
    const maxItemsInput = document.getElementById('folderScheduleMaxItems');
    const enabledInput = document.getElementById('folderScheduleEnabled');
    const cadence = cadenceInput ? cadenceInput.value : 'daily';
    const maxItems = Number(maxItemsInput ? maxItemsInput.value : 10);
    const enabled = enabledInput ? enabledInput.checked : true;

    try {
        const res = await fetch(`${API_BASE}/folders/${activeFolderSchedule.id}/schedule`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                cadence,
                max_items: maxItems,
                enabled,
            })
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Failed to save schedule");
        await loadFolderSchedule(activeFolderSchedule.id);
    } catch (e) {
        alert(`Failed to save schedule: ${e.message}`);
    }
};

window.disableFolderSchedule = async () => {
    if (!activeFolderSchedule.id) return;
    try {
        const res = await fetch(`${API_BASE}/folders/${activeFolderSchedule.id}/schedule`, { method: 'DELETE' });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Failed to disable schedule");
        await loadFolderSchedule(activeFolderSchedule.id);
    } catch (e) {
        alert(`Failed to disable schedule: ${e.message}`);
    }
};

window.runFolderDigestNow = async () => {
    if (!activeFolderSchedule.id) return;
    const cadenceInput = document.getElementById('folderScheduleCadence');
    const maxItemsInput = document.getElementById('folderScheduleMaxItems');
    const cadence = cadenceInput ? cadenceInput.value : 'daily';
    const maxItems = Number(maxItemsInput ? maxItemsInput.value : 10);

    try {
        const res = await fetch(`${API_BASE}/folders/${activeFolderSchedule.id}/digest`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ cadence, max_items: maxItems })
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Failed to run digest");
        await refreshAllBadges();
        await loadFolderSchedule(activeFolderSchedule.id);
        alert("Collection digest generated.");
    } catch (e) {
        alert(`Failed to run digest: ${e.message}`);
    }
};

window.fetchFolders = async () => {
    const container = document.getElementById('smartFoldersContainer');
    // Keep the create button
    if (!container) return; // Guard
    const createBtn = container.querySelector('button[onclick="openCreateFolderModal()"]');
    if (!createBtn) return; // Should exist if HTML is correct

    container.innerHTML = ''; // Clear existing folders

    try {
        const res = await fetch(`${API_BASE}/folders`);
        const folders = await res.json();

        folders.forEach(f => {
            const wrapper = document.createElement('div');
            wrapper.style.display = 'inline-flex';
            wrapper.style.alignItems = 'center';
            wrapper.style.gap = '0.35rem';
            wrapper.style.marginRight = '0.5rem';

            const btn = document.createElement('button');
            btn.className = 'filter-chip';
            const status = String(f.status || 'active').toLowerCase();
            const statusDot = status === 'archived' ? '•' : status === 'paused' ? '◦' : '●';
            btn.innerHTML = `<i class="fa-solid fa-folder"></i> ${f.name} <span style="opacity:0.75; font-size:0.78rem;">${statusDot}</span>`;
            btn.title = [
                f.description ? `Description: ${f.description}` : '',
                f.goal ? `Goal: ${f.goal}` : '',
                Number(f.target_count || 0) > 0 ? `Target: ${Number(f.target_count)} papers` : '',
                `Status: ${status}`,
            ].filter(Boolean).join('\n');
            btn.onclick = () => openFolder(f.id, btn);
            // Right click to delete
            btn.oncontextmenu = (e) => {
                e.preventDefault();
                if (confirm(`Delete collection "${f.name}"?`)) {
                    deleteFolder(f.id);
                }
            };

            const shareBtn = document.createElement('button');
            shareBtn.className = 'action-btn';
            shareBtn.title = 'Share read-only link';
            shareBtn.innerHTML = '<i class="fa-solid fa-share-nodes"></i>';
            shareBtn.style.padding = '0.35rem 0.55rem';
            shareBtn.style.borderRadius = '999px';
            shareBtn.onclick = (e) => {
                e.stopPropagation();
                shareFolder(f.id);
            };

            const scheduleBtn = document.createElement('button');
            scheduleBtn.className = 'action-btn';
            scheduleBtn.title = 'Schedule collection digest';
            scheduleBtn.innerHTML = '<i class="fa-solid fa-calendar-days"></i>';
            scheduleBtn.style.padding = '0.35rem 0.55rem';
            scheduleBtn.style.borderRadius = '999px';
            scheduleBtn.onclick = (e) => {
                e.stopPropagation();
                openFolderScheduleModal(f.id, f.name);
            };

            const editBtn = document.createElement('button');
            editBtn.className = 'action-btn';
            editBtn.title = 'Edit collection metadata';
            editBtn.innerHTML = '<i class="fa-solid fa-pen-to-square"></i>';
            editBtn.style.padding = '0.35rem 0.55rem';
            editBtn.style.borderRadius = '999px';
            editBtn.onclick = (e) => {
                e.stopPropagation();
                openEditFolderModal(f);
            };

            wrapper.appendChild(btn);
            wrapper.appendChild(editBtn);
            wrapper.appendChild(scheduleBtn);
            wrapper.appendChild(shareBtn);
            container.appendChild(wrapper);
        });

    } catch (e) {
        console.error("Failed to fetch folders", e);
    }

    container.appendChild(createBtn);
};

window.shareFolder = async (id) => {
    try {
        const res = await fetch(`${API_BASE}/folders/${id}/share`, { method: 'POST' });
        if (!res.ok) throw new Error("Failed to share collection.");
        const data = await res.json();
        const url = `${window.location.origin}/share/${data.token}`;
        openShareLinkModal(url, data.token);
    } catch (e) {
        alert(`Failed to share collection: ${e.message}`);
    }
};

window.deleteFolder = async (id) => {
    try {
        await fetch(`${API_BASE}/folders/${id}`, { method: 'DELETE' });
        fetchFolders();
    } catch (e) {
        alert("Failed to delete.");
    }
};

window.openFolder = async (id, btn) => {
    disconnectFeedObserver();
    hideFeedSentinel();

    console.log("Opening folder:", id);
    // UI Feedback
    const chips = document.querySelectorAll('.filter-chip');
    chips.forEach(c => c.classList.remove('active'));
    btn.classList.add('active');

    const grid = document.getElementById('paperGrid');
    grid.innerHTML = '<div class="loader"></div>';

    try {
        const url = `${API_BASE}/folders/${id}/papers`;
        console.log("Requesting:", url);

        const res = await fetch(url);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);

        const papers = await res.json();
        console.log("Papers received:", papers.length);

        // Use existing render logic
        renderPaperGrid(papers);
        currentVisiblePapers = papers; // Update state for other features

        // Update header
        const count = document.getElementById('paperCount');
        if (count) count.textContent = `${papers.length} Papers in Collection`;

    } catch (e) {
        console.error("Folder Error:", e);
        grid.innerHTML = `<div style="text-align:center; color:red">Failed to load folder: ${e.message}</div>`;
    }
};

// Survey Agent Logic
window.openSurveyModal = () => showModal('surveyModal');
window.closeSurveyModal = () => hideModal('surveyModal');

window.startSurveyJob = async () => {
    const topic = document.getElementById('surveyTopic').value;
    if (!topic) return alert("Please enter a research topic.");

    // Switch UI
    document.getElementById('surveyInputState').classList.add('hidden');
    document.getElementById('surveyRunningState').classList.remove('hidden');
    document.getElementById('surveyLogs').innerHTML = '<div class="log-entry">Initializing...</div>';

    try {
        const jobId = await submitJob('/agent/survey', { topic });
        pollSurveyJob(jobId);
    } catch (e) {
        alert("Failed to start survey: " + e.message);
        document.getElementById('surveyRunningState').classList.add('hidden');
        document.getElementById('surveyInputState').classList.remove('hidden');
    }
}

async function pollSurveyJob(jobId) {
    const logsContainer = document.getElementById('surveyLogs');
    const logsSet = new Set();

    try {
        const result = await waitForJob(jobId, {
            endpoint: '/agent',
            onUpdate: (job) => {
                const newLogs = (job.logs || []).filter(l => !logsSet.has(l));
                newLogs.forEach(l => {
                    logsSet.add(l);
                    const div = document.createElement('div');
                    div.className = 'log-entry';
                    div.textContent = l;
                    logsContainer.appendChild(div);
                });
                if (newLogs.length > 0) logsContainer.scrollTop = logsContainer.scrollHeight;
            },
            timeoutMs: 600000 // 10 mins
        });

        // Complete
        document.getElementById('surveyRunningState').classList.add('hidden');
        document.getElementById('surveyResultState').classList.remove('hidden');

        await ensureMarkdownLibs();
        document.getElementById('surveyFinalReport').innerHTML = renderMarkdownSafe(result);

    } catch (e) {
        document.getElementById('surveyRunningState').classList.add('hidden');
        document.getElementById('surveyInputState').classList.remove('hidden');
        alert("Survey Failed: " + e.message);
    }
}

window.resetSurveyUI = () => {
    document.getElementById('surveyResultState').classList.add('hidden');
    document.getElementById('surveyInputState').classList.remove('hidden');
    document.getElementById('surveyTopic').value = '';
}

window.copySurveyOutput = () => {
    const text = document.getElementById('surveyFinalReport').innerText;
    navigator.clipboard.writeText(text);
    alert("Copied to clipboard!");
}

// Initialize
// Wait for DOM
document.addEventListener('DOMContentLoaded', () => {
    fetchFolders();
});
