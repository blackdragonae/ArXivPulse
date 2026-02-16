(function initReadingPlanModule(global) {
    function createReadingPlanModule(deps) {
        if (!deps || typeof deps.getState !== 'function' || typeof deps.setState !== 'function') {
            throw new Error('Reading plan module requires getState/setState dependencies.');
        }

        const documentRef = deps.documentRef || global.document;
        const windowRef = deps.windowRef || global;
        const fetchImpl = typeof deps.fetchImpl === 'function'
            ? deps.fetchImpl
            : (typeof global.fetch === 'function' ? global.fetch.bind(global) : null);
        if (!fetchImpl) {
            throw new Error('Reading plan module requires fetch implementation.');
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

        function showModal(modalId) {
            if (typeof deps.showModal === 'function') {
                deps.showModal(modalId);
                return;
            }
            const modal = documentRef.getElementById(modalId);
            if (modal) modal.classList.remove('hidden');
        }

        function hideModal(modalId) {
            if (typeof deps.hideModal === 'function') {
                deps.hideModal(modalId);
                return;
            }
            const modal = documentRef.getElementById(modalId);
            if (modal) modal.classList.add('hidden');
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

        function getActiveReadingPaperId() {
            return String(currentState().activeReadingPaperId || '');
        }

        function getActiveReadingStatus() {
            return String(currentState().activeReadingStatus || 'queue');
        }

        function updateReadingTimelineUI(status, progress) {
            const steps = documentRef.querySelectorAll('#readingTimeline .reading-step');
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
            const progressInput = documentRef.getElementById('readingProgressInput');
            const progressLabel = documentRef.getElementById('readingProgressLabel');
            const progressBar = documentRef.getElementById('readingProgressBar');
            if (progressInput) progressInput.value = String(progress || 0);
            if (progressLabel) progressLabel.textContent = `${progress || 0}%`;
            if (progressBar) progressBar.style.width = `${progress || 0}%`;
        }

        function resetReadingExtrasUI() {
            const estimateVal = documentRef.getElementById('readingEstimateValue');
            const estimateMeta = documentRef.getElementById('readingEstimateMeta');
            const questionsList = documentRef.getElementById('readingQuestionsList');
            if (estimateVal) estimateVal.textContent = 'Not estimated';
            if (estimateMeta) estimateMeta.textContent = '';
            if (questionsList) questionsList.textContent = 'No questions generated yet.';
        }

        function updateReadingEstimateUI(payload) {
            const estimateVal = documentRef.getElementById('readingEstimateValue');
            const estimateMeta = documentRef.getElementById('readingEstimateMeta');
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

        async function estimateReadingTime(forceDownload = false) {
            const paperId = getActiveReadingPaperId();
            if (!paperId) return;
            const estimateVal = documentRef.getElementById('readingEstimateValue');
            if (estimateVal) estimateVal.textContent = 'Estimating...';
            try {
                const params = new URLSearchParams();
                if (forceDownload) {
                    params.set('download', 'true');
                    params.set('refresh', 'true');
                }
                const qs = params.toString();
                const url = `${getApiBase()}/papers/${encodeURIComponent(paperId)}/reading-time${qs ? `?${qs}` : ''}`;
                const res = await fetchImpl(url);
                const data = await res.json();
                if (!res.ok) throw new Error(data.detail || 'Failed to estimate reading time');
                updateReadingEstimateUI(data);
            } catch (e) {
                updateReadingEstimateUI({ available: false, reason: e.message });
            }
        }

        async function loadReadingQuestions(refresh = false) {
            const paperId = getActiveReadingPaperId();
            if (!paperId) return;
            const list = documentRef.getElementById('readingQuestionsList');
            if (list) list.innerHTML = '<div class="loader"></div>';
            try {
                const res = await fetchImpl(`${getApiBase()}/papers/${encodeURIComponent(paperId)}/questions?refresh=${refresh ? 'true' : 'false'}`);
                const data = await res.json();
                if (!res.ok) throw new Error(data.detail || 'Failed to load questions');
                const questions = Array.isArray(data.questions) ? data.questions : [];
                if (!questions.length) {
                    if (list) list.textContent = 'No questions generated yet.';
                    return;
                }
                if (list) {
                    list.innerHTML = `<ol>${questions.map((q) => `<li>${escapeHtml(q)}</li>`).join('')}</ol>`;
                }
            } catch (e) {
                if (list) list.textContent = `Failed to load questions: ${e.message}`;
            }
        }

        async function openReadingModal(paperId) {
            patchState({
                activeReadingPaperId: paperId,
                activeReadingStatus: 'queue',
            });
            if (typeof deps.recordTrail === 'function') {
                const title = typeof deps.getPaperTitleById === 'function' ? deps.getPaperTitleById(paperId) : paperId;
                deps.recordTrail({ type: 'reading', paper_id: paperId, label: `Reading: ${title}` });
            }

            const titleEl = documentRef.getElementById('readingModalTitle');
            const state = currentState();
            const paper = (Array.isArray(state.allPapers) ? state.allPapers : []).find((p) => p.id === paperId)
                || (Array.isArray(state.currentVisiblePapers) ? state.currentVisiblePapers : []).find((p) => p.id === paperId);
            if (titleEl) titleEl.textContent = paper ? paper.title : 'Reading Status';
            showModal('readingModal');

            const progressInput = documentRef.getElementById('readingProgressInput');
            if (progressInput) {
                progressInput.oninput = (event) => {
                    const value = Number(event.target.value || 0);
                    updateReadingTimelineUI(getActiveReadingStatus(), value);
                };
            }
            resetReadingExtrasUI();
            estimateReadingTime(false);
            loadReadingQuestions(false);

            try {
                const res = await fetchImpl(`${getApiBase()}/papers/${encodeURIComponent(paperId)}/reading`);
                const data = await res.json();
                if (!res.ok) throw new Error(data.detail || 'Failed to load reading status');
                patchState({ activeReadingStatus: data.status || 'queue' });
                updateReadingTimelineUI(getActiveReadingStatus(), Number(data.progress || 0));
            } catch (_) {
                updateReadingTimelineUI('queue', 0);
            }
        }

        function closeReadingModal() {
            hideModal('readingModal');
            patchState({ activeReadingPaperId: null });
        }

        function setReadingStatus(status) {
            patchState({ activeReadingStatus: status || 'queue' });
            const progressInput = documentRef.getElementById('readingProgressInput');
            const progress = progressInput ? Number(progressInput.value || 0) : 0;
            updateReadingTimelineUI(getActiveReadingStatus(), progress);
        }

        async function saveReadingStatus() {
            const paperId = getActiveReadingPaperId();
            if (!paperId) return;
            const progressInput = documentRef.getElementById('readingProgressInput');
            const progress = progressInput ? Number(progressInput.value || 0) : 0;
            try {
                const res = await fetchImpl(`${getApiBase()}/papers/${encodeURIComponent(paperId)}/reading`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ status: getActiveReadingStatus(), progress }),
                });
                const data = await res.json();
                if (!res.ok) throw new Error(data.detail || 'Failed to save reading status');

                if (typeof deps.updatePaperLocal === 'function') {
                    deps.updatePaperLocal(paperId, {
                        reading_status: data.status,
                        reading_progress: data.progress,
                        reading_started_at: data.started_at,
                        reading_finished_at: data.finished_at,
                    });
                }
                if (typeof deps.renderPaperGrid === 'function') {
                    const state = currentState();
                    deps.renderPaperGrid(Array.isArray(state.currentVisiblePapers) ? state.currentVisiblePapers : []);
                }
                closeReadingModal();
            } catch (e) {
                alertUser(`Failed to save reading status: ${e.message}`);
            }
        }

        function setReadingPlanStatus(text, isError = false) {
            const statusEl = documentRef.getElementById('readingPlanStatus');
            if (!statusEl) return;
            statusEl.style.color = isError ? 'var(--danger)' : 'var(--text-muted)';
            statusEl.textContent = text || '';
        }

        function renderReadingPlanProgress(payload) {
            const el = documentRef.getElementById('readingPlanProgress');
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
            patchState({ lastReadingPlanAction: null });
            const bar = documentRef.getElementById('readingPlanUndoBar');
            const text = documentRef.getElementById('readingPlanUndoText');
            if (text) text.textContent = '';
            if (bar) bar.classList.add('hidden');
        }

        function setReadingPlanUndoState(action, paperId, paperTitle = '') {
            const bar = documentRef.getElementById('readingPlanUndoBar');
            const text = documentRef.getElementById('readingPlanUndoText');
            if (!bar || !text || !paperId) return;
            const act = String(action || '').toLowerCase();
            if (!['done', 'defer'].includes(act)) {
                clearReadingPlanUndoState();
                return;
            }
            const nextUndo = { action: act, paperId: String(paperId), paperTitle: String(paperTitle || '') };
            patchState({ lastReadingPlanAction: nextUndo });
            const label = nextUndo.paperTitle || nextUndo.paperId;
            text.textContent = act === 'done' ? `Marked done: ${label}` : `Deferred: ${label}`;
            bar.classList.remove('hidden');
        }

        function getReadingPlanOptionsFromUi() {
            const totalInput = documentRef.getElementById('planTotalMinutes');
            const maxInput = documentRef.getElementById('planMaxItems');
            const budgetMode = documentRef.getElementById('planBudgetMode');
            const includeNew = documentRef.getElementById('planIncludeNew');
            const includeLiked = documentRef.getElementById('planIncludeLiked');
            const includeBookmarked = documentRef.getElementById('planIncludeBookmarked');
            const mode = String((budgetMode && budgetMode.value) || 'balanced').toLowerCase();
            return {
                total_minutes: Math.max(10, Math.min(360, Number((totalInput && totalInput.value) || 60))),
                max_items: Math.max(1, Math.min(20, Number((maxInput && maxInput.value) || 6))),
                budget_mode: ['balanced', 'focus', 'sprint', 'deep'].includes(mode) ? mode : 'balanced',
                include_new: Boolean(includeNew && includeNew.checked),
                include_liked: Boolean(includeLiked && includeLiked.checked),
                include_bookmarked: Boolean(includeBookmarked && includeBookmarked.checked),
            };
        }

        function applyReadingPlanOptionsToUi(options) {
            if (!options || typeof options !== 'object') return;
            const totalInput = documentRef.getElementById('planTotalMinutes');
            const maxInput = documentRef.getElementById('planMaxItems');
            const budgetMode = documentRef.getElementById('planBudgetMode');
            const includeNew = documentRef.getElementById('planIncludeNew');
            const includeLiked = documentRef.getElementById('planIncludeLiked');
            const includeBookmarked = documentRef.getElementById('planIncludeBookmarked');
            if (totalInput && options.total_minutes != null) totalInput.value = String(Number(options.total_minutes));
            if (maxInput && options.max_items != null) maxInput.value = String(Number(options.max_items));
            if (budgetMode && options.budget_mode != null) budgetMode.value = String(options.budget_mode);
            if (includeNew && options.include_new != null) includeNew.checked = Boolean(options.include_new);
            if (includeLiked && options.include_liked != null) includeLiked.checked = Boolean(options.include_liked);
            if (includeBookmarked && options.include_bookmarked != null) includeBookmarked.checked = Boolean(options.include_bookmarked);
        }

        async function applyReadingPlanPreset(preset) {
            const mode = String(preset || '').toLowerCase();
            const totalInput = documentRef.getElementById('planTotalMinutes');
            const maxInput = documentRef.getElementById('planMaxItems');
            const budgetMode = documentRef.getElementById('planBudgetMode');
            const includeNew = documentRef.getElementById('planIncludeNew');
            const includeLiked = documentRef.getElementById('planIncludeLiked');
            const includeBookmarked = documentRef.getElementById('planIncludeBookmarked');

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
        }

        function renderReadingPlan(payload) {
            const listEl = documentRef.getElementById('readingPlanList');
            if (!listEl) return;
            const items = Array.isArray(payload && payload.items) ? payload.items : [];
            const budget = Number((payload && payload.total_minutes_budget) || 0);
            const planned = Number((payload && payload.planned_minutes) || 0);
            const count = Number((payload && payload.count) || items.length || 0);
            const cached = Boolean(payload && payload.cached);
            const deferredCount = Number((payload && payload.deferred_count) || 0);
            const budgetMode = String((payload && payload.options && payload.options.budget_mode)
                || (payload && payload.budget_mode)
                || 'balanced');

            setReadingPlanStatus(
                `${count} item${count === 1 ? '' : 's'} · ${planned}/${budget} min planned · mode ${budgetMode}${deferredCount ? ` · deferred ${deferredCount}` : ''}${cached ? ' · cached' : ''}`
            );

            if (!items.length) {
                listEl.innerHTML = '<div style="color:var(--text-muted); text-align:center; padding:1rem 0.5rem;">No candidates matched this plan. Try increasing minutes or enabling more sources.</div>';
                return;
            }

            listEl.innerHTML = items.map((item) => {
                const pid = String((item && item.id) || '');
                const title = (item && item.title) || pid || 'Paper';
                const published = String((item && item.published) || '').slice(0, 10);
                const status = String((item && item.status) || 'queue');
                const progress = Number((item && item.progress) || 0);
                const minutesRemaining = Number((item && item.minutes_remaining) || 0);
                const minutesTotal = Number((item && item.minutes_total) || 0);
                const sources = Array.isArray(item && item.sources) ? item.sources.join(', ') : '';
                const score = Number((item && item.score) || 0);
                const encodedPid = encodeURIComponent(pid);
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
                            <a href="${getApiBase()}/papers/${encodedPid}/pdf" target="_blank" class="pdf-link"><i class="fa-regular fa-file-pdf"></i> PDF</a>
                            <button class="btn-secondary" onclick="openReadingModal(decodeURIComponent('${encodedPid}'))" style="padding:0.3rem 0.7rem;">
                                <i class="fa-solid fa-book-open-reader"></i> Reading
                            </button>
                            <button class="btn-secondary" onclick="openNotesModal(decodeURIComponent('${encodedPid}'))" style="padding:0.3rem 0.7rem;">
                                <i class="fa-solid fa-note-sticky"></i> Notes
                            </button>
                            <button class="btn-secondary" onclick="applyReadingPlanItemAction(decodeURIComponent('${encodedPid}'),'done')" style="padding:0.3rem 0.7rem;">
                                <i class="fa-solid fa-check"></i> Done
                            </button>
                            <button class="btn-secondary" onclick="applyReadingPlanItemAction(decodeURIComponent('${encodedPid}'),'defer')" style="padding:0.3rem 0.7rem;">
                                <i class="fa-solid fa-clock"></i> Defer
                            </button>
                        </div>
                    </div>
                `;
            }).join('');
        }

        function renderReadingPlanHistory(historyItems) {
            const selectEl = documentRef.getElementById('readingPlanHistorySelect');
            if (!selectEl) return;
            const items = Array.isArray(historyItems) ? historyItems : [];
            const currentDate = (currentState().activeReadingPlanPayload || {}).date || '';
            const options = ['<option value="">Today</option>'];
            items.forEach((item) => {
                const date = String((item && item.plan_date) || '').trim();
                if (!date) return;
                const label = `${date} · ${Number((item && item.count) || 0)} items · ${Number((item && item.planned_minutes) || 0)}m`;
                options.push(`<option value="${escapeHtml(date)}"${date === currentDate ? ' selected' : ''}>${escapeHtml(label)}</option>`);
            });
            selectEl.innerHTML = options.join('');
        }

        async function openReadingPlanModal() {
            if (typeof deps.recordTrail === 'function') {
                deps.recordTrail({ type: 'reading_plan', label: 'Reading plan' });
            }
            showModal('readingPlanModal');
            clearReadingPlanUndoState();
            renderReadingPlanProgress(null);
            const listEl = documentRef.getElementById('readingPlanList');
            if (listEl) listEl.innerHTML = '<div class="loader"></div>';
            await loadTodayReadingPlan(false);
            await loadReadingPlanHistory();
        }

        function closeReadingPlanModal() {
            hideModal('readingPlanModal');
        }

        async function loadReadingPlanHistory() {
            try {
                const res = await fetchImpl(`${getApiBase()}/reading-plan/history?limit=40`);
                const data = await res.json();
                if (!res.ok) throw new Error(data.detail || 'Failed to load reading plan history');
                renderReadingPlanHistory(data.items || []);
            } catch (_) {
                // Keep modal usable even if history fails.
            }
        }

        async function loadReadingPlanProgress(days = 14) {
            try {
                const span = Math.max(1, Math.min(90, Number(days || 14)));
                const res = await fetchImpl(`${getApiBase()}/reading-plan/progress?days=${span}`);
                const data = await res.json();
                if (!res.ok) throw new Error(data.detail || 'Failed to load reading plan progress');
                renderReadingPlanProgress(data);
            } catch (e) {
                const el = documentRef.getElementById('readingPlanProgress');
                if (el) el.textContent = `Progress unavailable: ${e.message}`;
            }
        }

        async function loadTodayReadingPlan(refresh = false) {
            try {
                setReadingPlanStatus('Loading today\'s plan...');
                const url = `${getApiBase()}/reading-plan/today${refresh ? '?refresh=true' : ''}`;
                const res = await fetchImpl(url);
                const data = await res.json();
                if (!res.ok) throw new Error(data.detail || 'Failed to load reading plan');
                patchState({ activeReadingPlanPayload: data });
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
                const listEl = documentRef.getElementById('readingPlanList');
                if (listEl) listEl.innerHTML = '';
            }
        }

        async function generateReadingPlan(refresh = true) {
            try {
                setReadingPlanStatus('Generating plan...');
                const options = getReadingPlanOptionsFromUi();
                const res = await fetchImpl(`${getApiBase()}/reading-plan/generate`, {
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
                    }),
                });
                const data = await res.json();
                if (!res.ok) throw new Error(data.detail || 'Failed to generate reading plan');
                patchState({ activeReadingPlanPayload: data });
                applyReadingPlanOptionsToUi(data.options || options);
                renderReadingPlan(data);
                await loadReadingPlanHistory();
                await loadReadingPlanProgress(14);
            } catch (e) {
                setReadingPlanStatus(`Failed to generate plan: ${e.message}`, true);
            }
        }

        async function loadSelectedReadingPlanHistory() {
            const selectEl = documentRef.getElementById('readingPlanHistorySelect');
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
                const res = await fetchImpl(`${getApiBase()}/reading-plan/${encodeURIComponent(date)}`);
                const data = await res.json();
                if (!res.ok) throw new Error(data.detail || 'Failed to load historical reading plan');
                patchState({ activeReadingPlanPayload: data });
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
        }

        async function applyReadingPlanItemAction(paperId, action) {
            if (!paperId) return;
            const act = String(action || '').toLowerCase();
            if (!['done', 'defer'].includes(act)) return;
            try {
                setReadingPlanStatus(act === 'done' ? 'Marking item as done...' : 'Deferring item...');
                const res = await fetchImpl(`${getApiBase()}/reading-plan/action`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        paper_id: paperId,
                        action: act,
                        defer_days: act === 'defer' ? 1 : 0,
                    }),
                });
                const data = await res.json();
                if (!res.ok) throw new Error(data.detail || 'Failed to apply reading plan action');

                if (act === 'done' && typeof deps.updatePaperLocal === 'function') {
                    deps.updatePaperLocal(paperId, {
                        reading_status: 'done',
                        reading_progress: 100,
                    });
                    if (typeof deps.renderPaperGrid === 'function') {
                        const state = currentState();
                        deps.renderPaperGrid(Array.isArray(state.currentVisiblePapers) ? state.currentVisiblePapers : []);
                    }
                }

                const paper = (Array.isArray(currentState().allPapers) ? currentState().allPapers : []).find((p) => p.id === paperId) || {};
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
        }

        async function undoLastReadingPlanAction() {
            const undoState = currentState().lastReadingPlanAction;
            if (!undoState || !undoState.paperId) return;
            const undoAction = undoState.action === 'done' ? 'undo_done' : 'undefer';
            try {
                setReadingPlanStatus('Undoing last action...');
                const res = await fetchImpl(`${getApiBase()}/reading-plan/action`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        paper_id: undoState.paperId,
                        action: undoAction,
                    }),
                });
                const data = await res.json();
                if (!res.ok) throw new Error(data.detail || 'Failed to undo action');
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
        }

        return {
            estimateReadingTime,
            loadReadingQuestions,
            openReadingModal,
            closeReadingModal,
            setReadingStatus,
            saveReadingStatus,
            applyReadingPlanPreset,
            openReadingPlanModal,
            closeReadingPlanModal,
            loadReadingPlanHistory,
            loadReadingPlanProgress,
            loadTodayReadingPlan,
            generateReadingPlan,
            loadSelectedReadingPlanHistory,
            applyReadingPlanItemAction,
            undoLastReadingPlanAction,
        };
    }

    global.ArxivPulseReadingPlan = {
        create: createReadingPlanModule,
    };
})(window);
