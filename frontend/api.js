(function initApiModule(global) {
    const DEFAULT_MAX_CACHE_ENTRIES = 80;

    function parseRetryAfter(response, payload) {
        const retryAfterRaw = response?.headers?.get('Retry-After');
        const retryAfter = Number.parseInt(retryAfterRaw || '', 10);
        if (Number.isFinite(retryAfter) && retryAfter > 0) return retryAfter;
        if (payload && Number.isFinite(Number(payload.retry_after_seconds))) {
            return Number(payload.retry_after_seconds);
        }
        return null;
    }

    function createApiClient(options = {}) {
        const baseUrl = String(options.baseUrl || '/api');
        const maxCacheEntries = Math.max(1, Number(options.maxCacheEntries || DEFAULT_MAX_CACHE_ENTRIES));
        const fetchImpl = typeof options.fetchImpl === 'function'
            ? options.fetchImpl
            : (typeof global.fetch === 'function' ? global.fetch.bind(global) : null);
        if (!fetchImpl) {
            throw new Error('fetch is not available in this environment.');
        }

        const apiResponseCache = new Map();

        function cacheApiResponse(url, payload) {
            if (!url) return;
            if (apiResponseCache.has(url)) apiResponseCache.delete(url);
            apiResponseCache.set(url, { payload, ts: Date.now() });
            if (apiResponseCache.size > maxCacheEntries) {
                const firstKey = apiResponseCache.keys().next().value;
                apiResponseCache.delete(firstKey);
            }
        }

        function getCachedApiResponse(url) {
            const entry = apiResponseCache.get(url);
            return entry ? entry.payload : null;
        }

        async function fetchJsonWithCache(url, options = {}) {
            const headers = new global.Headers(options.headers || {});
            if (apiResponseCache.has(url)) headers.set('X-Client-Cache', 'warm');

            const res = await fetchImpl(url, { ...options, headers });
            if (res.status === 304) {
                const cached = getCachedApiResponse(url);
                if (cached !== null) {
                    return { data: cached, cached: true, status: 304 };
                }
                const retry = await fetchImpl(url, { ...options, headers, cache: 'no-store' });
                const retryData = await retry.json();
                if (!retry.ok) {
                    const err = new Error(retryData.detail || `HTTP ${retry.status}`);
                    err.status = retry.status;
                    const retryAfter = parseRetryAfter(retry, retryData);
                    if (retryAfter) err.retryAfterSeconds = retryAfter;
                    err.payload = retryData;
                    throw err;
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
                const err = new Error((data && data.detail) ? data.detail : `HTTP ${res.status}`);
                err.status = res.status;
                const retryAfter = parseRetryAfter(res, data);
                if (retryAfter) err.retryAfterSeconds = retryAfter;
                err.payload = data;
                throw err;
            }
            cacheApiResponse(url, data);
            return { data, cached: false, status: res.status };
        }

        async function fetchJson(url, { method = 'GET', body = null, useCache = true, signal = undefined } = {}) {
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
                res = await fetchImpl(url, opts);
            } catch (err) {
                if (isGet) {
                    // One retry for transient network failures.
                    res = await fetchImpl(url, opts);
                } else {
                    throw err;
                }
            }
            let data = null;
            try {
                data = await res.json();
            } catch (e) {
                data = null;
            }
            if (!res.ok) {
                const err = new Error((data && data.detail) ? data.detail : `HTTP ${res.status}`);
                err.status = res.status;
                const retryAfter = parseRetryAfter(res, data);
                if (retryAfter) err.retryAfterSeconds = retryAfter;
                err.payload = data;
                throw err;
            }
            return data;
        }

        return {
            baseUrl,
            cacheApiResponse,
            getCachedApiResponse,
            fetchJsonWithCache,
            fetchJson,
            clearCache: () => apiResponseCache.clear(),
        };
    }

    function getOrCreateApiClient(options = {}) {
        if (global.__ARXIVC_API__ && typeof global.__ARXIVC_API__.fetchJson === 'function') {
            return global.__ARXIVC_API__;
        }
        const client = createApiClient(options);
        global.__ARXIVC_API__ = client;
        return client;
    }

    global.ArxivPulseApi = {
        createApiClient,
        getOrCreateApiClient,
    };
})(window);
