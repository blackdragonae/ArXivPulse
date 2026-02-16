(function initStateModule(global) {
    const API_BASE = '/api';
    const DEFAULT_RANK_PROFILE = { relevance: 50, novelty: 30, citations: 20 };

    function cloneRankProfile(input) {
        const source = input && typeof input === 'object' ? input : {};
        return {
            relevance: Number(source.relevance ?? DEFAULT_RANK_PROFILE.relevance),
            novelty: Number(source.novelty ?? DEFAULT_RANK_PROFILE.novelty),
            citations: Number(source.citations ?? DEFAULT_RANK_PROFILE.citations),
        };
    }

    function createInitialState(overrides = {}) {
        const source = overrides && typeof overrides === 'object' ? overrides : {};
        return {
            apiBase: String(source.apiBase || API_BASE),
            currentStatus: String(source.currentStatus || 'new'),
            isLoading: Boolean(source.isLoading),
            currentView: String(source.currentView || 'grid'),
            currentDateFilter: source.currentDateFilter || null,
            isSmartSort: Boolean(source.isSmartSort),
            searchMode: String(source.searchMode || 'local'),
            favoritesSort: String(source.favoritesSort || 'ai'),
            userKeywords: Array.isArray(source.userKeywords) ? [...source.userKeywords] : [],
            favoritesCacheTtlMs: Number(source.favoritesCacheTtlMs || (5 * 60 * 1000)),
            apiCacheMaxEntries: Number(source.apiCacheMaxEntries || 80),
            defaultRankProfile: cloneRankProfile(source.defaultRankProfile),
        };
    }

    function getSharedState(overrides = {}) {
        if (global.__ARXIVC_STATE__ && typeof global.__ARXIVC_STATE__ === 'object') {
            return global.__ARXIVC_STATE__;
        }
        const state = createInitialState(overrides);
        global.__ARXIVC_STATE__ = state;
        return state;
    }

    global.ArxivPulseState = {
        API_BASE,
        DEFAULT_RANK_PROFILE,
        createInitialState,
        getSharedState,
    };
})(window);
