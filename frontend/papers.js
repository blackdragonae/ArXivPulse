(function initPapersModule(global) {
    function createPapersModule(deps) {
        if (!deps || typeof deps.getState !== 'function' || typeof deps.setState !== 'function') {
            throw new Error('Papers module requires getState/setState dependencies.');
        }

        const documentRef = deps.documentRef || global.document;
        const windowRef = deps.windowRef || global;

        function currentState() {
            return deps.getState() || {};
        }

        function patchState(patch) {
            deps.setState(patch || {});
        }

        function shouldUsePagedFeed() {
            if (deps.hasActiveSearchQuery && deps.hasActiveSearchQuery()) return false;
            const state = currentState();
            if (state.currentStatus === 'liked') {
                return state.favoritesSort !== 'ai';
            }
            return ['new', 'dismissed', 'bookmarked', 'liked'].includes(state.currentStatus) && !state.isSmartSort;
        }

        function updateFavoritesSortBar() {
            const state = currentState();
            const bar = documentRef.getElementById('favoritesSortBar');
            if (!bar) return;
            if (state.currentStatus === 'liked') {
                bar.classList.remove('hidden');
            } else {
                bar.classList.add('hidden');
            }
            documentRef.querySelectorAll('.fav-sort-chip').forEach((chip) => {
                chip.classList.toggle('active', chip.dataset.sort === state.favoritesSort);
            });
        }

        function computeMatchScore(paper) {
            if (!paper) return 0;
            if (paper.match_score !== undefined && paper.match_score !== null) {
                return Number(paper.match_score) || 0;
            }
            const text = `${paper.title || ''} ${paper.summary || ''}`.toLowerCase();
            let score = 0;
            const keywords = Array.isArray(currentState().userKeywords) ? currentState().userKeywords : [];
            keywords.forEach((kw) => {
                const token = String(kw || '').toLowerCase().trim();
                if (token && text.includes(token)) score += 1;
            });
            return score;
        }

        function applyFavoritesSort(papers) {
            if (!Array.isArray(papers)) return papers;
            const state = currentState();
            const sorted = papers.slice();
            if (state.favoritesSort === 'date') {
                sorted.sort((a, b) => String(b.published || '').localeCompare(String(a.published || '')));
            } else if (state.favoritesSort === 'matches') {
                sorted.forEach((paper) => {
                    paper.match_score = computeMatchScore(paper);
                });
                sorted.sort((a, b) => (b.match_score || 0) - (a.match_score || 0));
            } else if (state.favoritesSort === 'novelty') {
                sorted.sort((a, b) => (b.novelty_score || 0) - (a.novelty_score || 0));
            }
            return sorted;
        }

        async function loadNextPaperPage() {
            const state = currentState();
            if (!shouldUsePagedFeed() || state.feedLoadingMore || !state.feedHasMore) return;
            const requestToken = state.feedRequestToken;

            patchState({ feedLoadingMore: true });
            if (deps.updateFeedSentinel) deps.updateFeedSentinel();

            if (state.feedPageAbortController) state.feedPageAbortController.abort();
            const pageAbortController = new windowRef.AbortController();
            patchState({ feedPageAbortController: pageAbortController });

            try {
                const runtime = currentState();
                const allowSmartSort = runtime.isSmartSort && !(runtime.currentStatus === 'liked' && runtime.favoritesSort !== 'ai');
                const includeNovelty = (runtime.currentStatus === 'liked' && runtime.favoritesSort === 'novelty') || runtime.feedOffset === 0;
                let url = `${runtime.apiBase}/papers?status=${runtime.currentStatus}&limit=${runtime.feedPageSize}&offset=${runtime.feedOffset}&include_meta=true&include_novelty=${includeNovelty ? 'true' : 'false'}`;
                if (runtime.currentDateFilter) {
                    url += `&date=${runtime.currentDateFilter}`;
                }
                if (allowSmartSort) {
                    url += '&sort=smart';
                } else if (runtime.currentStatus === 'liked') {
                    if (runtime.favoritesSort === 'ai') {
                        url += '&sort=smart';
                    } else if (runtime.favoritesSort) {
                        url += `&sort=${encodeURIComponent(runtime.favoritesSort)}`;
                    }
                }
                if (deps.getRankProfileQuery) {
                    url += deps.getRankProfileQuery();
                }

                const payloadWrapper = await deps.fetchJsonWithCache(url, { signal: pageAbortController.signal });
                if (requestToken !== currentState().feedRequestToken) return;
                const payload = payloadWrapper && Object.prototype.hasOwnProperty.call(payloadWrapper, 'data')
                    ? payloadWrapper.data
                    : payloadWrapper;

                const pageItems = Array.isArray(payload?.items) ? payload.items : [];
                const now = currentState();
                const isFirstPage = now.feedOffset === 0;
                const nextOffset = Number(now.feedOffset || 0) + pageItems.length;
                const nextAllPapers = isFirstPage ? pageItems : (Array.isArray(now.allPapers) ? now.allPapers.concat(pageItems) : pageItems);
                patchState({
                    allPapers: nextAllPapers,
                    feedOffset: nextOffset,
                    feedHasMore: Boolean(payload?.has_more),
                });

                if (isFirstPage) {
                    deps.renderPaperGrid(nextAllPapers);
                } else if (pageItems.length > 0) {
                    deps.renderPaperGrid(pageItems, { append: true });
                }
            } catch (err) {
                if (err && err.name === 'AbortError') return;
                console.error('Failed to load next page', err);
                if (requestToken === currentState().feedRequestToken && deps.alertUser) {
                    deps.alertUser('Failed to load more papers.');
                }
            } finally {
                if (requestToken === currentState().feedRequestToken) {
                    patchState({ feedLoadingMore: false });
                    if (deps.updateFeedSentinel) deps.updateFeedSentinel();
                }
            }
        }

        function setFilter(status) {
            const state = currentState();
            patchState({
                currentStatus: status,
                currentView: (state.currentView === 'skim' || state.currentView === 'threads') ? state.currentView : 'grid',
            });

            const navItems = documentRef.querySelectorAll('.nav-item');
            navItems.forEach((item) => {
                if (item.getAttribute('onclick') && item.getAttribute('onclick').includes(status)) {
                    item.classList.add('active');
                } else {
                    item.classList.remove('active');
                }
            });

            const graphView = documentRef.getElementById('graphView');
            if (graphView) graphView.classList.add('hidden');
            const grid = documentRef.getElementById('paperGrid');
            if (grid) grid.classList.remove('hidden');
            const graphTabBtn = documentRef.getElementById('graphTabBtn');
            if (graphTabBtn) graphTabBtn.classList.remove('active');

            documentRef.querySelectorAll('.filter-chip').forEach((chip) => {
                if (chip.dataset.status === status) chip.classList.add('active');
                else chip.classList.remove('active');
            });

            updateFavoritesSortBar();
            if (deps.saveUIState) deps.saveUIState();
            if (deps.applySkimViewState) deps.applySkimViewState();
            if (deps.applyThreadsViewState) deps.applyThreadsViewState();
            return loadPapers();
        }

        async function loadPapers() {
            const state = currentState();
            patchState({ currentView: state.currentView === 'skim' ? 'skim' : 'grid' });
            if (deps.saveUIState) deps.saveUIState();

            const nextToken = Number(state.feedRequestToken || 0) + 1;
            patchState({
                feedRequestToken: nextToken,
                feedOffset: 0,
                feedHasMore: false,
                feedLoadingMore: false,
            });

            if (deps.disconnectFeedObserver) deps.disconnectFeedObserver();
            if (deps.resetVirtualization) deps.resetVirtualization();
            if (deps.setLoading) deps.setLoading(true);

            const grid = deps.getPaperGrid ? deps.getPaperGrid() : null;
            if (grid) grid.innerHTML = '';

            if (state.feedAbortController) state.feedAbortController.abort();
            const feedAbortController = new windowRef.AbortController();
            patchState({ feedAbortController });

            const runtime = currentState();
            if (grid) {
                if (runtime.currentStatus === 'liked') {
                    grid.classList.add('favorites-grid');
                    grid.style.display = 'grid';
                    grid.style.setProperty('grid-template-columns', 'repeat(2, 1fr)', 'important');
                    grid.style.gap = '1.5rem';
                } else {
                    grid.classList.remove('favorites-grid');
                    grid.style.removeProperty('grid-template-columns');
                    grid.style.removeProperty('border');
                }
            }

            try {
                updateFavoritesSortBar();
                const searchInput = documentRef.getElementById('searchInput');
                const hasSearch = Boolean(searchInput && searchInput.value && searchInput.value.trim().length > 0);
                const usePaged = shouldUsePagedFeed();
                const stateNow = currentState();
                if (stateNow.currentStatus === 'liked' && !hasSearch && !usePaged && deps.getFavoritesCacheEntry) {
                    const cached = deps.getFavoritesCacheEntry();
                    if (cached && Array.isArray(cached.items)) {
                        patchState({ allPapers: cached.items });
                        deps.renderPaperGrid(cached.items);
                        return;
                    }
                }

                const dateDisplay = documentRef.getElementById('batchDateDisplay');
                if (dateDisplay && stateNow.currentDateFilter) {
                    dateDisplay.textContent = `Showing: ${stateNow.currentDateFilter}`;
                }

                if (usePaged) {
                    patchState({ feedHasMore: true });
                    await loadNextPaperPage();
                    const afterFirstPage = currentState();
                    if (afterFirstPage.feedHasMore && deps.setupFeedObserver) {
                        deps.setupFeedObserver();
                    }
                    if (deps.updateFeedSentinel) deps.updateFeedSentinel();
                    return;
                }

                if (deps.hideFeedSentinel) deps.hideFeedSentinel();
                const requestState = currentState();
                const allowSmartSort = requestState.isSmartSort && !(requestState.currentStatus === 'liked' && requestState.favoritesSort !== 'ai');
                let url = `${requestState.apiBase}/papers?status=${requestState.currentStatus}&limit=100`;
                if (requestState.currentDateFilter) {
                    url += `&date=${requestState.currentDateFilter}`;
                }
                if (allowSmartSort) {
                    url += '&sort=smart';
                } else if (requestState.currentStatus === 'liked') {
                    if (requestState.favoritesSort === 'ai') {
                        url += '&sort=smart';
                    } else {
                        url += `&sort=${encodeURIComponent(requestState.favoritesSort)}`;
                    }
                }
                if (deps.getRankProfileQuery) {
                    url += deps.getRankProfileQuery();
                }

                const response = await deps.fetchJsonWithCache(url, { signal: feedAbortController.signal });
                const payload = response && Object.prototype.hasOwnProperty.call(response, 'data')
                    ? response.data
                    : response;
                const papers = Array.isArray(payload?.items) ? payload.items : (Array.isArray(payload) ? payload : []);
                patchState({ allPapers: papers });
                if (requestState.currentStatus === 'liked' && deps.setFavoritesCache) {
                    deps.setFavoritesCache(papers);
                }
                deps.renderPaperGrid(papers);
            } catch (err) {
                if (err && err.name === 'AbortError') return;
                console.error('Failed to load papers', err);
                if (deps.alertUser) deps.alertUser('Failed to load papers. check console/backend.');
            } finally {
                if (deps.setLoading) deps.setLoading(false);
            }
        }

        return {
            shouldUsePagedFeed,
            updateFavoritesSortBar,
            computeMatchScore,
            applyFavoritesSort,
            setFilter,
            loadPapers,
            loadNextPaperPage,
        };
    }

    global.ArxivPulsePapers = {
        create: createPapersModule,
    };
})(window);
