        // --- State ---
        let rawRunsData = [];
        let currentFilteredRuns = [];
        let savedConfig = { filter1: '', filter2: '' };
        let xAxisMode = 'steps'; // 'steps' or 'time'
        let isLogScale = false;
        let currentSmoothing = 0;

        const scanProgress = new ProgressOverlayController({
            overlayId: 'plot-scan-progress-overlay',
            titleId: 'plot-scan-title',
            percentId: 'plot-scan-percent',
            fillId: 'plot-scan-fill',
            statusId: 'plot-scan-status',
            countId: 'plot-scan-count',
            cancelBtnId: 'btn-cancel-plot-scan'
        });

        // Auto-shutdown heartbeat + client-leave is handled by shared.js
        // (initAutoShutdown runs on load).

        // --- Smoothing Math ---
        function exponentialSmoothing(yVals, alpha) {
            if (alpha <= 0 || yVals.length <= 1) return yVals;
            const smoothed = [];
            let last = yVals[0];
            smoothed.push(last);
            const weight = 1 - alpha;
            for (let i = 1; i < yVals.length; i++) {
                const val = yVals[i];
                if (val !== null && val !== undefined) {
                    last = last * alpha + val * weight;
                    smoothed.push(last);
                } else {
                    smoothed.push(val);
                }
            }
            return smoothed;
        }

        // --- Run Name Parsing & Helpers ---
        function countCapitals(s) {
            if (!s) return 0;
            let count = 0;
            for (let i = 0; i < s.length; i++) {
                const ch = s[i];
                if (ch >= 'A' && ch <= 'Z') count++;
            }
            return count;
        }

        function pickCanonicalCasing(words) {
            if (!words || words.length === 0) return '';
            let best = words[0];
            let maxCaps = countCapitals(best);
            for (let i = 1; i < words.length; i++) {
                const caps = countCapitals(words[i]);
                if (caps > maxCaps) {
                    maxCaps = caps;
                    best = words[i];
                }
            }
            return best;
        }

        function parseRunName(name) {
            if (!name) return { part1: '', part2: null };
            const parts = name.split('_');
            const part1 = parts[0] || '';
            const part2 = parts.length > 1 ? parts[1] : null;
            return { part1, part2 };
        }

        function getUniquePart1(runs) {
            const groups = new Map();
            runs.forEach(r => {
                const { part1 } = parseRunName(r.name);
                if (part1) {
                    const key = part1.toLowerCase();
                    if (!groups.has(key)) groups.set(key, []);
                    groups.get(key).push(part1);
                }
            });
            const canonical = [];
            groups.forEach(variants => {
                canonical.push(pickCanonicalCasing(variants));
            });
            return canonical.sort((a, b) => a.localeCompare(b, undefined, { sensitivity: 'base', numeric: true }));
        }

        function getUniquePart2ForPart1(runs, targetPart1) {
            const targetLower = (targetPart1 || '').toLowerCase();
            const groups = new Map();
            runs.forEach(r => {
                const { part1, part2 } = parseRunName(r.name);
                if (part1 && part1.toLowerCase() === targetLower && part2 !== null && part2 !== undefined && part2 !== '') {
                    const key = part2.toLowerCase();
                    if (!groups.has(key)) groups.set(key, []);
                    groups.get(key).push(part2);
                }
            });
            const canonical = [];
            groups.forEach(variants => {
                canonical.push(pickCanonicalCasing(variants));
            });
            canonical.sort((a, b) => a.localeCompare(b, undefined, { sensitivity: 'base', numeric: true }));
            return ['(all)', ...canonical];
        }

        // --- Config Sync ---
        async function loadServerConfig() {
            try {
                const res = await fetch('/api/config');
                const json = await res.json();
                if (json.status === 'success' && json.data) {
                    savedConfig = json.data;
                }
            } catch (e) {
                console.error('Failed to load config:', e);
            }
        }

        async function saveServerConfig(filter1, filter2) {
            savedConfig = { filter1, filter2 };
            try {
                await fetch('/api/config', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ filter1, filter2 })
                });
            } catch (e) {
                console.error('Failed to save config:', e);
            }
        }

        // --- Combo Box Management ---
        function populateComboBoxes(initialLoad = false) {
            const combo1 = document.getElementById('combo-filter1');
            const combo2 = document.getElementById('combo-filter2');
            
            const part1List = getUniquePart1(rawRunsData);
            
            let selected1 = combo1.value;
            if (initialLoad) {
                const matched1 = savedConfig.filter1 ? part1List.find(x => x.toLowerCase() === savedConfig.filter1.toLowerCase()) : null;
                if (matched1) {
                    selected1 = matched1;
                } else {
                    selected1 = part1List.length > 0 ? part1List[0] : '';
                }
            } else {
                const matched1 = part1List.find(x => x.toLowerCase() === selected1.toLowerCase());
                selected1 = matched1 || (part1List.length > 0 ? part1List[0] : '');
            }

            combo1.innerHTML = '';
            part1List.forEach(item => {
                const opt = document.createElement('option');
                opt.value = item;
                opt.textContent = item;
                combo1.appendChild(opt);
            });
            combo1.value = selected1;

            const part2List = getUniquePart2ForPart1(rawRunsData, selected1);
            let selected2 = combo2.value;
            if (initialLoad) {
                const matched2 = savedConfig.filter2 ? part2List.find(x => x.toLowerCase() === savedConfig.filter2.toLowerCase()) : null;
                if (matched2) {
                    selected2 = matched2;
                } else {
                    selected2 = '(all)';
                }
            } else {
                const matched2 = part2List.find(x => x.toLowerCase() === selected2.toLowerCase());
                selected2 = matched2 || '(all)';
            }

            combo2.innerHTML = '';
            part2List.forEach(item => {
                const opt = document.createElement('option');
                opt.value = item;
                opt.textContent = item;
                combo2.appendChild(opt);
            });
            combo2.value = selected2;

            if (initialLoad && combo1.value && (combo1.value !== savedConfig.filter1 || combo2.value !== savedConfig.filter2)) {
                saveServerConfig(combo1.value, combo2.value);
            }
        }

        function onFilter1Change() {
            const combo1 = document.getElementById('combo-filter1');
            const combo2 = document.getElementById('combo-filter2');
            const prevVal2 = combo2.value;
            const selected1 = combo1.value;

            const part2List = getUniquePart2ForPart1(rawRunsData, selected1);
            combo2.innerHTML = '';
            part2List.forEach(item => {
                const opt = document.createElement('option');
                opt.value = item;
                opt.textContent = item;
                combo2.appendChild(opt);
            });

            const matched2 = part2List.find(x => x.toLowerCase() === prevVal2.toLowerCase());
            if (matched2) {
                combo2.value = matched2;
            } else {
                combo2.value = '(all)';
            }

            saveServerConfig(combo1.value, combo2.value);
            updateFilteredDataAndPlot();
        }

        function onFilter2Change() {
            const combo1 = document.getElementById('combo-filter1');
            const combo2 = document.getElementById('combo-filter2');
            saveServerConfig(combo1.value, combo2.value);
            updateFilteredDataAndPlot();
        }

        function getFilteredRuns() {
            const combo1 = document.getElementById('combo-filter1');
            const combo2 = document.getElementById('combo-filter2');
            const val1 = combo1 ? combo1.value : '';
            const val2 = combo2 ? combo2.value : '';

            if (!val1) return [];
            const val1Lower = val1.toLowerCase();
            const val2Lower = val2 ? val2.toLowerCase() : '';

            return rawRunsData.filter(run => {
                const { part1, part2 } = parseRunName(run.name);
                if (!part1 || part1.toLowerCase() !== val1Lower) return false;
                if (val2 && val2Lower !== '(all)') {
                    if (!part2 || part2.toLowerCase() !== val2Lower) return false;
                }
                return true;
            });
        }

        function updateFilteredDataAndPlot() {
            currentFilteredRuns = getFilteredRuns();

            const combo1 = document.getElementById('combo-filter1');
            const combo2 = document.getElementById('combo-filter2');
            const val1 = combo1 ? combo1.value : '';
            const val2 = combo2 ? combo2.value : '';

            const hiddenCount = currentFilteredRuns.filter(r => !r.default_visible).length;
            const filterLabel = val1 ? (val2 && val2 !== '(all)' ? `${val1} / ${val2}` : val1) : 'No runs';
            document.getElementById('runs-badge').innerText = `${currentFilteredRuns.length} Runs (${filterLabel})`;

            const hiddenBadge = document.getElementById('hidden-badge');
            if (hiddenCount > 0) {
                hiddenBadge.innerText = `${hiddenCount} Hidden (> 1.0)`;
                hiddenBadge.style.display = 'inline-block';
            } else {
                hiddenBadge.style.display = 'none';
            }

            document.getElementById('search-input').value = '';
            renderPlot();
        }

        // --- Build Plotly Traces from State ---
        function buildPlotlyTraces() {
            return currentFilteredRuns.map(run => {
                const xVals = (xAxisMode === 'time') ? run.relative_hours : run.steps;
                const smoothedY = exponentialSmoothing(run.values, currentSmoothing);

                // Build customdata for rich hover tooltip
                const customdata = run.steps.map((st, i) => {
                    const hrs = run.relative_hours[i] || 0;
                    const totalMins = Math.round(hrs * 60);
                    const h = Math.floor(totalMins / 60);
                    const m = totalMins % 60;
                    const timeStr = `${hrs.toFixed(2)} hrs (${h}h ${m}m)`;
                    return {
                        run_date: run.run_date || 'Unknown',
                        step: st,
                        time_str: timeStr,
                        raw_y: run.values[i]
                    };
                });

                let hovertemplate;
                if (xAxisMode === 'time') {
                    hovertemplate =
                        `<b>%{fullData.name}</b><br>` +
                        `Date: %{customdata.run_date}<br>` +
                        `Elapsed: %{x:.2f} hrs (%{customdata.time_str})<br>` +
                        `Step: %{customdata.step}<br>` +
                        `val/loss: %{y:.6f}<extra></extra>`;
                } else {
                    hovertemplate =
                        `<b>%{fullData.name}</b><br>` +
                        `Date: %{customdata.run_date}<br>` +
                        `Step: %{x}<br>` +
                        `Elapsed: %{customdata.time_str}<br>` +
                        `val/loss: %{y:.6f}<extra></extra>`;
                }

                return {
                    name: run.name,
                    x: xVals,
                    y: smoothedY,
                    type: 'scatter',
                    mode: 'lines',
                    line: { width: 1.8 },
                    visible: run.default_visible ? true : 'legendonly',
                    customdata: customdata,
                    hovertemplate: hovertemplate
                };
            });
        }

        function getLayout() {
            const xTitle = (xAxisMode === 'time') ? 'Relative Time (Hours elapsed from start)' : 'Step';
            return {
                paper_bgcolor: '#121214',
                plot_bgcolor: '#181822',
                margin: { l: 65, r: 40, t: 25, b: 60 },
                hovermode: 'closest',
                xaxis: {
                    title: { text: xTitle, font: { color: '#9ca3af', size: 13 } },
                    tickfont: { color: '#9ca3af' },
                    gridcolor: '#262638',
                    zerolinecolor: '#373750',
                    linecolor: '#2d2d3d'
                },
                yaxis: {
                    title: { text: 'Validation Loss (val/loss)', font: { color: '#9ca3af', size: 13 } },
                    tickfont: { color: '#9ca3af' },
                    gridcolor: '#262638',
                    zerolinecolor: '#373750',
                    linecolor: '#2d2d3d',
                    type: isLogScale ? 'log' : 'linear',
                    autorange: true
                },
                legend: {
                    orientation: 'v',
                    x: 1.01,
                    y: 1,
                    xanchor: 'left',
                    yanchor: 'top',
                    font: { color: '#d1d5db', size: 11 },
                    bgcolor: 'rgba(26, 26, 36, 0.85)',
                    bordercolor: '#2f2f3f',
                    borderwidth: 1,
                    itemclick: 'toggle',
                    itemdoubleclick: 'toggleothers'
                },
                modebar: {
                    bgcolor: 'transparent',
                    color: '#9ca3af',
                    activecolor: '#4dabf7'
                }
            };
        }

        function renderPlot() {
            const plotDiv = document.getElementById('plot-container');
            const traces = buildPlotlyTraces();
            const config = {
                responsive: true,
                displaylogo: false,
                modeBarButtonsToRemove: ['lasso2d', 'select2d']
            };
            Plotly.newPlot(plotDiv, traces, getLayout(), config);
        }

        // --- Controls Handlers ---
        function setXAxisMode(mode) {
            if (xAxisMode === mode) return;
            xAxisMode = mode;

            document.getElementById('btn-xaxis-steps').className = (mode === 'steps') ? 'btn-ui btn-toggle-active' : 'btn-ui';
            document.getElementById('btn-xaxis-time').className = (mode === 'time') ? 'btn-ui btn-toggle-active' : 'btn-ui';

            // Preserve current visibility state across traces
            const plotDiv = document.getElementById('plot-container');
            let currentVisibilities = [];
            if (plotDiv && plotDiv.data) {
                currentVisibilities = plotDiv.data.map(t => t.visible);
            }

            const updatedTraces = buildPlotlyTraces();
            if (currentVisibilities.length === updatedTraces.length) {
                updatedTraces.forEach((t, i) => {
                    t.visible = currentVisibilities[i];
                });
            }

            Plotly.react(plotDiv, updatedTraces, getLayout());
        }

        function updateSmoothing(val) {
            currentSmoothing = parseFloat(val);
            document.getElementById('smoothing-val').innerText = currentSmoothing.toFixed(2);
            
            const plotDiv = document.getElementById('plot-container');
            if (!plotDiv || !plotDiv.data) return;

            const yUpdates = currentFilteredRuns.map(run => exponentialSmoothing(run.values, currentSmoothing));
            Plotly.restyle('plot-container', { y: yUpdates });
        }

        function toggleYScale() {
            isLogScale = !isLogScale;
            document.getElementById('btn-scale').innerText = isLogScale ? 'Y: Log' : 'Y: Linear';
            Plotly.relayout('plot-container', { 'yaxis.type': isLogScale ? 'log' : 'linear' });
        }

        function showAllTraces() {
            Plotly.restyle('plot-container', { visible: true });
        }

        function hideAllTraces() {
            Plotly.restyle('plot-container', { visible: 'legendonly' });
        }

        function resetDefaultVisibility() {
            const vis = currentFilteredRuns.map(r => r.default_visible ? true : 'legendonly');
            Plotly.restyle('plot-container', { visible: vis });
        }

        function filterSeries(keyword) {
            keyword = keyword.toLowerCase().trim();
            const visible = [];
            for (let i = 0; i < currentFilteredRuns.length; i++) {
                const name = currentFilteredRuns[i].name.toLowerCase();
                const runDate = (currentFilteredRuns[i].run_date || '').toLowerCase();
                if (!keyword || name.includes(keyword) || runDate.includes(keyword)) {
                    visible.push(true);
                } else {
                    visible.push('legendonly');
                }
            }
            Plotly.restyle('plot-container', { visible: visible });
        }

        // --- Fetch Data ---
        async function fetchData(isRefresh = false) {
            scanProgress.show({
                title: 'Scanning Validation Loss Logs',
                initialStatus: isRefresh ? 'Rescanning database logs...' : 'Scanning SQLite logs...',
                countText: 'Processing',
                onCancel: async () => {
                    try {
                        await fetch('/api/scan_cancel', { method: 'POST' });
                    } catch (e) {}
                    scanProgress.hideImmediate();
                }
            });

            try {
                await loadServerConfig();
                const initRes = await fetch('/api/data?async=1' + (isRefresh ? '&refresh=1' : ''), { method: 'POST' })
                    .then(x => x.json()).catch(() => null);
                
                if (initRes && initRes.status === 'success' && initRes.data?.started) {
                    scanProgress.startPolling('/api/scan_progress', {
                        intervalMs: 250,
                        onComplete: async () => {
                            scanProgress.hide(300);
                            const res = await fetch('/api/data');
                            const json = await res.json();
                            if (json.status === 'success') {
                                rawRunsData = json.data.runs || [];
                                populateComboBoxes(true);
                                updateFilteredDataAndPlot();
                            }
                        },
                        onError: () => scanProgress.hideImmediate()
                    });
                } else {
                    const res = await fetch('/api/data' + (isRefresh ? '?refresh=1' : ''));
                    const json = await res.json();
                    scanProgress.hide(200);
                    if (json.status === 'success') {
                        rawRunsData = json.data.runs || [];
                        populateComboBoxes(true);
                        updateFilteredDataAndPlot();
                    } else {
                        alert('Error loading runs: ' + json.message);
                    }
                }
            } catch (err) {
                console.error(err);
                scanProgress.hideImmediate();
                alert('Network or server error loading training data.');
            }
        }

        window.addEventListener('DOMContentLoaded', () => {
            fetchData();
        });
