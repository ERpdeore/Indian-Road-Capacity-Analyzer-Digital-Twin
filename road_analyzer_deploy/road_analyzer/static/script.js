// ============================================================
// Indian Road Capacity Analyzer — dashboard logic
// Talks to the real FastAPI backend: POST /analyse, POST /analyse_video,
// GET /job/{job_id}. There is no batch endpoint on the server, so the
// batch tab simply calls /analyse once per selected file.
// ============================================================

document.addEventListener('DOMContentLoaded', function () {

    // ----- Real IRC:106-1990 Table 2 DSV values (must match core.py) -----
    var IRC106_DSV = {
        '2L-U': { low: 1400, medium: 1750, high: 2100 },
        '2L-D': { low: 1600, medium: 2000, high: 2400 },
        '4L-U': { low: 2800, medium: 3500, high: 4200 },
        '4L-D': { low: 3500, medium: 4200, high: 4900 },
        '6L-U': { low: 4200, medium: 5600, high: 7000 },
        '6L-D': { low: 5600, medium: 7000, high: 8400 },
        '8L-D': { low: 8400, medium: 10500, high: 12600 }
    };

    function freeFlowSpeed(carriageway) {
        if (carriageway.indexOf('8L') === 0) return 120;
        if (carriageway.indexOf('6L') === 0) return 100;
        if (carriageway.indexOf('4L') === 0) return 80;
        return 60;
    }

    function setStatus(el, msg, isError) {
        if (!el) return;
        el.textContent = msg;
        el.className = 'status-bar' + (isError ? ' error' : '');
    }

    function fmt(n) {
        if (n === undefined || n === null || isNaN(n)) return '—';
        return Number(n).toLocaleString(undefined, { maximumFractionDigits: 1 });
    }

    // ============================================================
    // TABS
    // ============================================================
    var tabBtns = document.querySelectorAll('.tab-btn');
    var tabContents = document.querySelectorAll('.tab-content');
    tabBtns.forEach(function (btn) {
        btn.addEventListener('click', function () {
            tabBtns.forEach(function (b) { b.classList.remove('active'); });
            tabContents.forEach(function (c) { c.classList.remove('active'); });
            btn.classList.add('active');
            var target = document.getElementById('tab-' + btn.dataset.tab);
            if (target) target.classList.add('active');
        });
    });

    // ============================================================
    // GENERIC DROPZONE WIRING (click + drag/drop -> file input)
    // ============================================================
    function wireDropzone(areaId, inputId, infoId, onFiles) {
        var area = document.getElementById(areaId);
        var input = document.getElementById(inputId);
        var info = document.getElementById(infoId);
        if (!area || !input) return;

        area.addEventListener('click', function (e) {
            e.preventDefault();
            input.click();
        });

        input.addEventListener('change', function () {
            if (this.files && this.files.length > 0) {
                onFiles(this.files, info);
            } else if (info) {
                info.classList.add('hidden');
            }
        });

        area.addEventListener('dragover', function (e) {
            e.preventDefault();
            area.style.borderColor = '#b97e1f';
            area.style.background = '#141925';
        });
        area.addEventListener('dragleave', function (e) {
            e.preventDefault();
            area.style.borderColor = '';
            area.style.background = '';
        });
        area.addEventListener('drop', function (e) {
            e.preventDefault();
            area.style.borderColor = '';
            area.style.background = '';
            if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
                input.files = e.dataTransfer.files;
                input.dispatchEvent(new Event('change'));
            }
        });
    }

    function describeFiles(files) {
        if (files.length === 1) {
            var f = files[0];
            return f.name + ' (' + (f.size / 1024 / 1024).toFixed(2) + ' MB)';
        }
        var totalMb = 0;
        for (var i = 0; i < files.length; i++) totalMb += files[i].size;
        return files.length + ' files selected (' + (totalMb / 1024 / 1024).toFixed(2) + ' MB total)';
    }

    wireDropzone('uploadArea', 'fileInput', 'fileInfo', function (files, info) {
        var file = files[0];
        if (file.size > 20 * 1024 * 1024) {
            alert('File too large. Maximum size is 20MB.');
            return;
        }
        if (info) {
            info.textContent = describeFiles(files);
            info.classList.remove('hidden');
        }
    });

    wireDropzone('batchUploadArea', 'batchFileInput', 'batchFileInfo', function (files, info) {
        if (info) {
            info.textContent = describeFiles(files);
            info.classList.remove('hidden');
        }
    });

    wireDropzone('videoUploadArea', 'videoInput', 'videoInfo', function (files, info) {
        if (info) {
            info.textContent = describeFiles(files);
            info.classList.remove('hidden');
        }
    });

    // ============================================================
    // DSV PREVIEW (single image tab)
    // ============================================================
    var carriageway = document.getElementById('carriageway');
    var fringe = document.getElementById('fringe');

    function updateDSVPreview() {
        if (!carriageway || !fringe) return;
        var table = IRC106_DSV[carriageway.value] || IRC106_DSV['4L-D'];
        var dsv = table[fringe.value] !== undefined ? table[fringe.value] : table.medium;
        var speed = freeFlowSpeed(carriageway.value);

        var baseDisplay = document.getElementById('baseDsvDisplay');
        var vehDisplay = document.getElementById('vehDisplay');
        var speedDisplay = document.getElementById('speedDisplay');
        if (baseDisplay) baseDisplay.textContent = dsv.toLocaleString();
        if (vehDisplay) vehDisplay.textContent = dsv.toLocaleString();
        if (speedDisplay) speedDisplay.textContent = speed;
    }

    if (carriageway) carriageway.addEventListener('change', updateDSVPreview);
    if (fringe) fringe.addEventListener('change', updateDSVPreview);
    updateDSVPreview();

    // ============================================================
    // SEVERITY / RECOMMENDATION RENDER HELPERS
    // ============================================================
    function severityTally(severities) {
        var counts = { shallow: 0, moderate: 0, deep: 0 };
        (severities || []).forEach(function (s) {
            if (counts[s] !== undefined) counts[s]++;
        });
        return counts;
    }

    function severityBadgeHtml(label, count, colorClass) {
        if (!count) return '';
        return '<div class="defect-row"><span>' + label + '</span>' +
            '<span class="defect-badge ' + (colorClass || '') + '">' + count + '</span></div>';
    }

    function recommendationsHtml(recs) {
        if (!recs || recs.length === 0) return '';
        var rows = recs.map(function (r) {
            return '<div class="defect-row"><span>' + (r.action || '') + '</span>' +
                '<span class="defect-badge">' + (r.severity || '') + '</span></div>';
        }).join('');
        return '<div class="detail-panel"><h4>Recommended Actions</h4>' + rows + '</div>';
    }

    function metricCard(label, value, unit, extraClass) {
        return '<div class="metric-card">' +
            '<span class="metric-label">' + label + '</span>' +
            '<div class="metric-value ' + (extraClass || '') + '">' + value + '</div>' +
            '<span class="metric-unit">' + unit + '</span></div>';
    }

    // ============================================================
    // SINGLE IMAGE — RUN ANALYSIS
    // ============================================================
    var analyzeBtn = document.getElementById('analyzeBtn');
    var statusBar = document.getElementById('statusBar');
    var resultContainer = document.getElementById('resultContainer');
    var fileInput = document.getElementById('fileInput');

    async function runSingleAnalysis(file, totalWidth, carriagewayVal, fringeVal) {
        var formData = new FormData();
        formData.append('file', file);
        formData.append('total_width_m', totalWidth);
        formData.append('carriageway', carriagewayVal);
        formData.append('fringe', fringeVal);

        var response = await fetch('/analyse', { method: 'POST', body: formData });
        if (!response.ok) {
            var errText = await response.text();
            var errJson;
            try { errJson = JSON.parse(errText); } catch (e) { errJson = { detail: errText || 'Server error' }; }
            throw new Error(errJson.detail || 'Server error');
        }
        return response.json();
    }

    function displayResults(data) {
        var result = data.result;
        if (!resultContainer) return;

        if (!result) {
            resultContainer.innerHTML = '<div class="placeholder"><p>No results returned from server.</p></div>';
            return;
        }

        var baseDsv = result.base_dsv_pcu_hr || 0;
        var reducedDsv = result.reduced_dsv_pcu_hr || 0;
        var lossPercent = result.capacity_loss_percent || 0;
        var blockedWidth = result.blocked_width_m || 0;
        var severities = result.pothole_severities || [];
        var sim = result.simulation || {};
        var counts = severityTally(severities);

        var html = '<div class="metric-grid">' +
            metricCard('Baseline DSV', fmt(baseDsv), 'PCU/hr') +
            metricCard('Reduced DSV', fmt(reducedDsv), 'PCU/hr', 'warn') +
            metricCard('Capacity Loss', fmt(lossPercent) + '%', 'of baseline capacity', lossPercent > 15 ? 'warn' : 'ok') +
            metricCard('Blocked Width', fmt(blockedWidth), 'metres') +
            '</div>';

        if (severities.length > 0) {
            html += '<div class="detail-panel"><h4>Pothole Severity Breakdown</h4>' +
                severityBadgeHtml('Shallow', counts.shallow) +
                severityBadgeHtml('Moderate', counts.moderate) +
                severityBadgeHtml('Deep', counts.deep) +
                '</div>';
        }

        if (sim && Object.keys(sim).length > 0) {
            html += '<div class="detail-panel"><h4>Digital Twin Simulation</h4>';
            if (sim.average_speed_kmh !== undefined) html += '<div class="defect-row"><span>Average speed</span><span class="defect-badge">' + fmt(sim.average_speed_kmh) + ' km/h</span></div>';
            if (sim.density_pcu_km !== undefined) html += '<div class="defect-row"><span>Density</span><span class="defect-badge">' + fmt(sim.density_pcu_km) + ' PCU/km</span></div>';
            if (sim.flow_pcu_hr !== undefined) html += '<div class="defect-row"><span>Flow</span><span class="defect-badge">' + fmt(sim.flow_pcu_hr) + ' PCU/hr</span></div>';
            html += '</div>';
        }

        html += recommendationsHtml(data.recommendations);

        resultContainer.innerHTML = html;
    }

    if (analyzeBtn && statusBar && resultContainer && fileInput) {
        analyzeBtn.addEventListener('click', async function () {
            try {
                var file = fileInput.files[0];
                if (!file) {
                    setStatus(statusBar, 'Please upload an image first.', true);
                    return;
                }
                if (file.size > 20 * 1024 * 1024) {
                    setStatus(statusBar, 'File too large. Max 20MB.', true);
                    return;
                }
                var totalWidthInput = document.getElementById('totalWidth');
                var totalWidth = parseFloat(totalWidthInput ? totalWidthInput.value : NaN);
                if (isNaN(totalWidth) || totalWidth <= 0) {
                    setStatus(statusBar, 'Please enter a valid road width.', true);
                    return;
                }

                var carriagewayVal = carriageway ? carriageway.value : '4L-D';
                var fringeVal = fringe ? fringe.value : 'medium';

                analyzeBtn.disabled = true;
                analyzeBtn.textContent = 'PROCESSING…';
                setStatus(statusBar, 'Analysing road condition…', false);
                resultContainer.innerHTML = '<div class="placeholder"><p>Processing your image…</p></div>';

                var data = await runSingleAnalysis(file, totalWidth, carriagewayVal, fringeVal);
                displayResults(data);
                setStatus(statusBar, 'Analysis complete.', false);

            } catch (error) {
                setStatus(statusBar, 'Error: ' + (error.message || 'Unknown error'), true);
                resultContainer.innerHTML = '<div class="placeholder"><p style="color:#e2574c;">' + (error.message || 'Unknown error') + '</p></div>';
            } finally {
                analyzeBtn.disabled = false;
                analyzeBtn.textContent = 'RUN ANALYSIS';
            }
        });
    }

    // ============================================================
    // BATCH — no dedicated endpoint on the server, so we call
    // /analyse once per file and aggregate the results client-side.
    // ============================================================
    var batchAnalyzeBtn = document.getElementById('batchAnalyzeBtn');
    var batchStatus = document.getElementById('batchStatus');
    var batchFileInput = document.getElementById('batchFileInput');
    var batchResultContainer = document.getElementById('batchResultContainer');

    if (batchAnalyzeBtn && batchStatus) {
        batchAnalyzeBtn.addEventListener('click', async function () {
            var files = batchFileInput ? batchFileInput.files : null;
            if (!files || files.length === 0) {
                setStatus(batchStatus, 'Please select one or more images first.', true);
                return;
            }

            var totalWidthInput = document.getElementById('totalWidthBatch');
            var totalWidth = parseFloat(totalWidthInput ? totalWidthInput.value : NaN);
            if (isNaN(totalWidth) || totalWidth <= 0) {
                setStatus(batchStatus, 'Please enter a valid road width.', true);
                return;
            }
            var carriagewayVal = document.getElementById('carriagewayBatch').value;
            var fringeVal = document.getElementById('fringeBatch').value;

            batchAnalyzeBtn.disabled = true;
            var rows = [];

            for (var i = 0; i < files.length; i++) {
                setStatus(batchStatus, 'Analysing ' + (i + 1) + ' of ' + files.length + ': ' + files[i].name + '…', false);
                try {
                    var data = await runSingleAnalysis(files[i], totalWidth, carriagewayVal, fringeVal);
                    rows.push({ name: files[i].name, loss: data.result.capacity_loss_percent || 0 });
                } catch (err) {
                    rows.push({ name: files[i].name, loss: null, error: err.message });
                }
            }

            rows.sort(function (a, b) { return (b.loss || 0) - (a.loss || 0); });
            var validLosses = rows.filter(function (r) { return r.loss !== null; }).map(function (r) { return r.loss; });
            var avg = validLosses.length ? (validLosses.reduce(function (a, b) { return a + b; }, 0) / validLosses.length) : 0;
            var worst = validLosses.length ? Math.max.apply(null, validLosses) : 0;

            var html = '<div class="metric-grid">' +
                metricCard('Images Analysed', rows.length, 'files') +
                metricCard('Average Capacity Loss', fmt(avg) + '%', 'across batch') +
                metricCard('Worst Case Loss', fmt(worst) + '%', 'single image', 'warn') +
                '</div><div class="detail-panel"><h4>Ranked Results</h4>' +
                rows.map(function (r) {
                    if (r.error) {
                        return '<div class="batch-row"><span class="name">' + r.name + '</span><span style="color:#e2574c;">' + r.error + '</span></div>';
                    }
                    return '<div class="batch-row"><span class="name">' + r.name + '</span><span class="loss">' + fmt(r.loss) + '% loss</span></div>';
                }).join('') + '</div>';

            if (batchResultContainer) batchResultContainer.innerHTML = html;
            setStatus(batchStatus, 'Batch analysis complete.', false);
            batchAnalyzeBtn.disabled = false;
        });
    }

    // ============================================================
    // VIDEO — submit to /analyse_video then poll /job/{job_id}
    // ============================================================
    var videoAnalyzeBtn = document.getElementById('videoAnalyzeBtn');
    var videoStatus = document.getElementById('videoStatus');
    var videoInput = document.getElementById('videoInput');
    var videoResultContainer = document.getElementById('videoResultContainer');

    function pollJob(jobId) {
        return new Promise(function (resolve, reject) {
            var attempts = 0;
            var interval = setInterval(async function () {
                attempts++;
                try {
                    var res = await fetch('/job/' + jobId);
                    if (!res.ok) throw new Error('Job not found');
                    var job = await res.json();
                    if (job.status === 'processing') {
                        if (attempts > 60) { clearInterval(interval); reject(new Error('Timed out waiting for video analysis.')); }
                        return;
                    }
                    clearInterval(interval);
                    if (job.status === 'failed') {
                        reject(new Error(job.error || 'Video analysis failed.'));
                    } else {
                        resolve(job);
                    }
                } catch (err) {
                    clearInterval(interval);
                    reject(err);
                }
            }, 2000);
        });
    }

    function displayVideoResults(job) {
        if (!videoResultContainer) return;
        var s = job.summary || {};
        var html = '<div class="metric-grid">' +
            metricCard('Frames Analysed', job.frames_analysed || 0, 'of ' + fmt(job.total_duration_sec) + ' s clip') +
            metricCard('Average Capacity Loss', fmt(s.average_capacity_loss_percent) + '%', 'across clip') +
            metricCard('Peak Capacity Loss', fmt(s.max_capacity_loss_percent) + '%', 'worst frame', 'warn') +
            metricCard('Peak Blocked Width', fmt(s.peak_blocked_width_m), 'metres') +
            '</div>';
        html += recommendationsHtml(job.recommendations);
        videoResultContainer.innerHTML = html;
    }

    if (videoAnalyzeBtn && videoStatus) {
        videoAnalyzeBtn.addEventListener('click', async function () {
            var file = videoInput ? videoInput.files[0] : null;
            if (!file) {
                setStatus(videoStatus, 'Please upload a video first.', true);
                return;
            }
            var totalWidthInput = document.getElementById('totalWidth');
            var totalWidth = parseFloat(totalWidthInput ? totalWidthInput.value : 7.0) || 7.0;
            var carriagewayVal = carriageway ? carriageway.value : '4L-D';
            var fringeVal = fringe ? fringe.value : 'medium';

            var formData = new FormData();
            formData.append('file', file);
            formData.append('total_width_m', totalWidth);
            formData.append('carriageway', carriagewayVal);
            formData.append('fringe', fringeVal);

            videoAnalyzeBtn.disabled = true;
            videoAnalyzeBtn.textContent = 'PROCESSING…';
            setStatus(videoStatus, 'Uploading video…', false);
            if (videoResultContainer) videoResultContainer.innerHTML = '<div class="placeholder"><p>Uploading and queuing video analysis…</p></div>';

            try {
                var submitRes = await fetch('/analyse_video', { method: 'POST', body: formData });
                if (!submitRes.ok) {
                    var errText = await submitRes.text();
                    throw new Error(errText || 'Server error');
                }
                var submitData = await submitRes.json();
                setStatus(videoStatus, 'Analysing frames in the background…', false);
                if (videoResultContainer) videoResultContainer.innerHTML = '<div class="placeholder"><p>Analysing frames — this can take a little while…</p></div>';

                var job = await pollJob(submitData.job_id);
                displayVideoResults(job);
                setStatus(videoStatus, 'Video analysis complete.', false);
            } catch (err) {
                setStatus(videoStatus, 'Error: ' + (err.message || 'Unknown error'), true);
                if (videoResultContainer) videoResultContainer.innerHTML = '<div class="placeholder"><p style="color:#e2574c;">' + (err.message || 'Unknown error') + '</p></div>';
            } finally {
                videoAnalyzeBtn.disabled = false;
                videoAnalyzeBtn.textContent = 'RUN VIDEO ANALYSIS';
            }
        });
    }

});
