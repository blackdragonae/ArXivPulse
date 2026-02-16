(function initMain(global) {
    const stateModule = global.ArxivPulseState;
    const apiModule = global.ArxivPulseApi;
    if (!stateModule || !apiModule) {
        console.error('ArXiv Pulse bootstrap failed: missing state/api modules.');
        return;
    }

    const sharedState = stateModule.getSharedState();
    const apiBase = String(sharedState.apiBase || stateModule.API_BASE || '/api');
    const apiClient = apiModule.getOrCreateApiClient({
        baseUrl: apiBase,
        maxCacheEntries: Number(sharedState.apiCacheMaxEntries || 80),
    });

    global.API_BASE = apiBase;
    global.__ARXIVC_STATE__ = sharedState;
    global.__ARXIVC_API__ = apiClient;
    global.__ARXIVC_RUNTIME__ = {
        state: sharedState,
        api: apiClient,
        initializedAt: new Date().toISOString(),
    };
})(window);
