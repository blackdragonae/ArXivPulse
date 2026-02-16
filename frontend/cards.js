(function initCardsModule(global) {
    function createCardsModule(deps) {
        if (!deps || typeof deps.getState !== 'function' || typeof deps.setState !== 'function') {
            throw new Error('Cards module requires getState/setState dependencies.');
        }

        const fetchImpl = typeof deps.fetchImpl === 'function'
            ? deps.fetchImpl
            : (typeof global.fetch === 'function' ? global.fetch.bind(global) : null);
        if (!fetchImpl) {
            throw new Error('Cards module requires fetch implementation.');
        }

        function currentState() {
            return deps.getState() || {};
        }

        function patchState(patch) {
            deps.setState(patch || {});
        }

        function getApiBase() {
            const state = currentState();
            return String(state.apiBase || '/api');
        }

        function stringifyError(err) {
            if (!err) return 'Unknown error';
            if (err.message) return String(err.message);
            return String(err);
        }

        async function handleRate(id, status, btnElement) {
            try {
                const res = await fetchImpl(`${getApiBase()}/papers/${encodeURIComponent(id)}/rate`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ status }),
                });
                if (!res.ok) throw new Error('API Error');

                const state = currentState();
                const allPapers = Array.isArray(state.allPapers) ? state.allPapers : [];
                const visiblePapers = Array.isArray(state.currentVisiblePapers) ? state.currentVisiblePapers : [];
                const keepCardInCurrentFeed = (
                    status === 'liked' && (state.currentStatus === 'new' || state.currentStatus === 'bookmarked')
                );
                const card = btnElement && typeof btnElement.closest === 'function'
                    ? btnElement.closest('.paper-card')
                    : null;

                if (keepCardInCurrentFeed) {
                    const nextAll = allPapers.map((paper) => (paper.id === id ? { ...paper, status: 'liked' } : paper));
                    const nextVisible = visiblePapers.map((paper) => (paper.id === id ? { ...paper, status: 'liked' } : paper));
                    patchState({ allPapers: nextAll, currentVisiblePapers: nextVisible });
                    if (deps.invalidateFavoritesCache) deps.invalidateFavoritesCache();
                    if (deps.renderPaperGrid) deps.renderPaperGrid(nextVisible);
                    if (deps.refreshAllBadges) deps.refreshAllBadges({ force: true });
                    return;
                }

                const nextAll = allPapers.filter((paper) => paper.id !== id);
                const nextVisible = visiblePapers.filter((paper) => paper.id !== id);
                patchState({ allPapers: nextAll, currentVisiblePapers: nextVisible });
                if (deps.invalidateFavoritesCache) deps.invalidateFavoritesCache();

                if (state.virtualState && state.virtualState.enabled) {
                    if (deps.renderPaperGrid) deps.renderPaperGrid(nextVisible);
                    if (deps.refreshAllBadges) deps.refreshAllBadges({ force: true });
                    return;
                }

                if (card) {
                    card.style.transform = 'scale(0.95)';
                    card.style.opacity = '0';
                    setTimeout(() => {
                        card.remove();
                        const grid = deps.getPaperGrid ? deps.getPaperGrid() : null;
                        if (grid && grid.querySelectorAll('.paper-card').length === 0) {
                            grid.innerHTML = '<div style="grid-column: 1/-1; text-align: center; margin-top: 2rem; color: #94a3b8;">All caught up!</div>';
                        }
                    }, 300);
                }
                if (deps.refreshAllBadges) deps.refreshAllBadges({ force: true });
            } catch (err) {
                console.error('Rate Error:', err);
                if (deps.alertUser) {
                    deps.alertUser(`Failed to rate paper: ${stringifyError(err)}`);
                }
            }
        }

        async function toggleBookmark(id, btnElement) {
            if (!btnElement) return;
            const icon = btnElement.querySelector('i');
            const isActive = btnElement.classList.contains('active');

            if (isActive) {
                btnElement.classList.remove('active');
                if (icon) {
                    icon.classList.remove('fa-solid');
                    icon.classList.add('fa-regular');
                }
            } else {
                btnElement.classList.add('active');
                if (icon) {
                    icon.classList.remove('fa-regular');
                    icon.classList.add('fa-solid');
                }
            }

            try {
                await fetchImpl(`${getApiBase()}/papers/${encodeURIComponent(id)}/bookmark`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ active: !isActive }),
                });
            } catch (err) {
                console.error(err);
                if (deps.alertUser) deps.alertUser('Failed to bookmark.');
            }
        }

        return {
            handleRate,
            toggleBookmark,
        };
    }

    global.ArxivPulseCards = {
        create: createCardsModule,
    };
})(window);
