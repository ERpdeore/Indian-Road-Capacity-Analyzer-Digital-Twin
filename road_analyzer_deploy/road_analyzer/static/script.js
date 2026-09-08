// ============================================================
// COMPLETE SCRIPT.JS WITH NULL CHECKS
// ============================================================

document.addEventListener('DOMContentLoaded', function() {
    console.log("✅ Script loaded!");

    // ----- GET ALL ELEMENTS (with null checks) -----
    var uploadArea = document.getElementById('uploadArea');
    var fileInput = document.getElementById('fileInput');
    var fileInfo = document.getElementById('fileInfo');
    var carriageway = document.getElementById('carriageway');
    var fringe = document.getElementById('fringe');
    var analyzeBtn = document.getElementById('analyzeBtn');
    var statusBar = document.getElementById('statusBar');
    var resultContainer = document.getElementById('resultContainer');

    // ----- LOG ELEMENTS FOR DEBUGGING -----
    console.log("uploadArea:", uploadArea);
    console.log("fileInput:", fileInput);
    console.log("carriageway:", carriageway);
    console.log("fringe:", fringe);
    console.log("analyzeBtn:", analyzeBtn);

    // ----- TAB SWITCHING (with null check) -----
    var tabBtns = document.querySelectorAll('.tab-btn');
    var tabContents = document.querySelectorAll('.tab-content');

    if (tabBtns.length > 0 && tabContents.length > 0) {
        tabBtns.forEach(function(btn) {
            btn.addEventListener('click', function() {
                tabBtns.forEach(function(b) { b.classList.remove('active'); });
                tabContents.forEach(function(c) { c.classList.remove('active'); });
                this.classList.add('active');
                var targetTab = document.getElementById('tab-' + this.dataset.tab);
                if (targetTab) {
                    targetTab.classList.add('active');
                }
            });
        });
    } else {
        console.warn('⚠️ Tabs not found. Skipping tab setup.');
    }

    // ----- FILE UPLOAD (only if elements exist) -----
    if (uploadArea && fileInput && fileInfo) {
        // Click on upload area opens file picker
        uploadArea.addEventListener('click', function(e) {
            e.preventDefault();
            console.log("📁 Upload area clicked!");
            fileInput.click();
        });

        // When file is selected, show its name
        fileInput.addEventListener('change', function() {
            console.log("📎 File input changed!");
            try {
                if (this.files && this.files.length > 0) {
                    var file = this.files[0];
                    if (file.size > 20 * 1024 * 1024) {
                        alert('❌ File too large. Maximum size is 20MB.');
                        this.value = '';
                        fileInfo.classList.add('hidden');
                        return;
                    }
                    fileInfo.textContent = '📎 ' + file.name + ' (' + (file.size / 1024 / 1024).toFixed(2) + ' MB)';
                    fileInfo.classList.remove('hidden');
                    console.log("✅ File selected:", file.name);
                } else {
                    fileInfo.classList.add('hidden');
                }
            } catch (err) {
                console.error('❌ Error handling file selection:', err);
            }
        });

        // Drag and drop support
        uploadArea.addEventListener('dragover', function(e) {
            e.preventDefault();
            this.style.borderColor = '#0a2a44';
            this.style.background = '#f0f7ff';
        });

        uploadArea.addEventListener('dragleave', function(e) {
            e.preventDefault();
            this.style.borderColor = '#cbd5e1';
            this.style.background = 'transparent';
        });

        uploadArea.addEventListener('drop', function(e) {
            e.preventDefault();
            this.style.borderColor = '#cbd5e1';
            this.style.background = 'transparent';
            try {
                if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
                    var file = e.dataTransfer.files[0];
                    if (file.size > 20 * 1024 * 1024) {
                        alert('❌ File too large. Maximum size is 20MB.');
                        return;
                    }
                    fileInput.files = e.dataTransfer.files;
                    var event = new Event('change');
                    fileInput.dispatchEvent(event);
                    console.log("✅ File dropped:", file.name);
                }
            } catch (err) {
                console.error('❌ Error handling drop:', err);
            }
        });

        console.log("✅ Upload events attached successfully!");
    } else {
        console.error('❌ Upload elements not found!');
    }

    // ----- DSV PREVIEW UPDATE (with null checks) -----
    function updateDSVPreview() {
        try {
            // Only run if elements exist
            if (!carriageway || !fringe) {
                console.warn('⚠️ Carriageway or fringe elements missing. Skipping DSV update.');
                return;
            }

            var carriagewayVal = carriageway.value;
            var fringeVal = fringe.value;

            var dsvMap = {
                '2L-U': { base: 1750, speed: 50 }, '2L-D': { base: 2000, speed: 55 },
                '4L-U': { base: 3500, speed: 65 }, '4L-D': { base: 4200, speed: 70 },
                '6L-U': { base: 5600, speed: 80 }, '6L-D': { base: 7000, speed: 85 },
                '8L-U': { base: 10500, speed: 90 }, '8L-D': { base: 12600, speed: 100 }
            };

            var dsv = dsvMap[carriagewayVal] || { base: 2400, speed: 50 };
            if (fringeVal === 'low') dsv.base *= 1.0;
            else if (fringeVal === 'medium') dsv.base *= 0.9;
            else dsv.base *= 0.8;

            var baseDisplay = document.getElementById('baseDsvDisplay');
            var vehDisplay = document.getElementById('vehDisplay');
            var speedDisplay = document.getElementById('speedDisplay');

            if (baseDisplay) baseDisplay.textContent = Math.round(dsv.base).toLocaleString();
            if (vehDisplay) vehDisplay.textContent = Math.round(dsv.base).toLocaleString();
            if (speedDisplay) speedDisplay.textContent = dsv.speed;

        } catch (err) {
            console.error('❌ Error updating DSV preview:', err);
        }
    }

    // Only attach listeners if elements exist
    if (carriageway) carriageway.addEventListener('change', updateDSVPreview);
    if (fringe) fringe.addEventListener('change', updateDSVPreview);
    updateDSVPreview();

    // ----- RUN ANALYSIS (only if button exists) -----
    if (analyzeBtn && statusBar && resultContainer && fileInput) {
        analyzeBtn.addEventListener('click', async function() {
            console.log("🚀 RUN ANALYSIS clicked!");

            try {
                var file = fileInput.files[0];
                if (!file) {
                    statusBar.textContent = '❌ Please upload an image first.';
                    statusBar.className = 'status-bar error';
                    return;
                }

                if (file.size > 20 * 1024 * 1024) {
                    statusBar.textContent = '❌ File too large. Max 20MB.';
                    statusBar.className = 'status-bar error';
                    return;
                }

                var totalWidthInput = document.getElementById('totalWidth');
                if (!totalWidthInput) {
                    statusBar.textContent = '❌ Road width input not found.';
                    statusBar.className = 'status-bar error';
                    return;
                }

                var totalWidth = parseFloat(totalWidthInput.value);
                if (isNaN(totalWidth) || totalWidth <= 0) {
                    statusBar.textContent = '❌ Please enter a valid road width.';
                    statusBar.className = 'status-bar error';
                    return;
                }

                var carriagewayVal = carriageway ? carriageway.value : '4L-D';
                var fringeVal = fringe ? fringe.value : 'medium';

                var formData = new FormData();
                formData.append('file', file);
                formData.append('total_width_m', totalWidth);
                formData.append('carriageway', carriagewayVal);
                formData.append('fringe', fringeVal);

                analyzeBtn.disabled = true;
                analyzeBtn.textContent = '⏳ Processing...';
                statusBar.textContent = '⏳ Analysing road condition...';
                statusBar.className = 'status-bar';
                resultContainer.innerHTML = '<div class="placeholder"><p>⏳ Processing your image...</p></div>';

                var response = await fetch('/analyse', { method: 'POST', body: formData });

                if (!response.ok) {
                    var errorText = await response.text();
                    var errorJson;
                    try {
                        errorJson = JSON.parse(errorText);
                    } catch (e) {
                        errorJson = { detail: errorText || 'Server error' };
                    }
                    throw new Error(errorJson.detail || 'Server error');
                }

                var data = await response.json();
                console.log("✅ Analysis complete:", data);
                displayResults(data);
                statusBar.textContent = '✅ Analysis complete.';
                statusBar.className = 'status-bar';

            } catch (error) {
                console.error("❌ Error in analysis:", error);
                statusBar.textContent = '❌ Error: ' + (error.message || 'Unknown error');
                statusBar.className = 'status-bar error';
                resultContainer.innerHTML = '<div class="placeholder"><p style="color:#a33a1a;">❌ ' + (error.message || 'Unknown error') + '</p></div>';
            } finally {
                analyzeBtn.disabled = false;
                analyzeBtn.textContent = '🚀 RUN ANALYSIS';
            }
        });
    } else {
        console.error('❌ Critical elements missing for RUN ANALYSIS!');
    }

    // ----- VIDEO ANALYSIS -----
    var videoUploadArea = document.getElementById('videoUploadArea');
    var videoInput = document.getElementById('videoInput');
    var videoInfo = document.getElementById('videoInfo');
    var videoAnalyzeBtn = document.getElementById('videoAnalyzeBtn');
    var videoStatus = document.getElementById('videoStatus');

    if (videoUploadArea && videoInput) {
        videoUploadArea.addEventListener('click', function(e) {
            e.preventDefault();
            videoInput.click();
        });

        videoInput.addEventListener('change', function() {
            try {
                if (this.files && this.files.length > 0) {
                    var file = this.files[0];
                    if (videoInfo) {
                        videoInfo.textContent = '🎬 ' + file.name + ' (' + (file.size / 1024 / 1024).toFixed(2) + ' MB)';
                        videoInfo.classList.remove('hidden');
                    }
                }
            } catch (err) {
                console.error('❌ Video upload error:', err);
            }
        });
    }

    if (videoAnalyzeBtn && videoStatus) {
        videoAnalyzeBtn.addEventListener('click', function() {
            try {
                var file = videoInput ? videoInput.files[0] : null;
                if (!file) {
                    videoStatus.textContent = '❌ Please upload a video first.';
                    videoStatus.className = 'status-bar error';
                    return;
                }
                videoStatus.textContent = '🎥 Video analysis coming soon!';
                videoStatus.className = 'status-bar';
            } catch (err) {
                console.error('❌ Video analysis error:', err);
            }
        });
    }

    // ----- BATCH ANALYSIS -----
    var batchAnalyzeBtn = document.getElementById('batchAnalyzeBtn');
    var batchStatus = document.getElementById('batchStatus');

    if (batchAnalyzeBtn && batchStatus) {
        batchAnalyzeBtn.addEventListener('click', function() {
            try {
                batchStatus.textContent = '📁 Batch processing coming soon!';
                batchStatus.className = 'status-bar';
            } catch (err) {
                console.error('❌ Batch analysis error:', err);
            }
        });
    }

    // ----- DISPLAY RESULTS -----
    function displayResults(data) {
        try {
            var result = data.result;
            var container = document.getElementById('resultContainer');

            if (!container) {
                console.error('❌ resultContainer not found!');
                return;
            }

            if (!result) {
                container.innerHTML = '<div class="placeholder"><p>❌ No results returned from server.</p></div>';
                return;
            }

            var baseDsv = result.base_dsv_pcu_hr || 0;
            var reducedDsv = result.reduced_dsv_pcu_hr || 0;
            var lossPercent = result.capacity_loss_percent || 0;
            var blockedWidth = result.blocked_width_m || 0;
            var severities = result.pothole_severities || [];
            var sim = result.simulation || {};

            var html = `
                <div style="display:grid; grid-template-columns:1fr 1fr; gap:16px; margin-top:16px;">
                    <div style="background:#f8faff; padding:16px; border-radius:10px; border:1px solid #e0e8f2;">
                        <span style="font-size:0.8rem; color:#5a6a7a; text-transform:uppercase;">Baseline DSV</span>
                        <div style="font-size:2rem; font-weight:700; color:#0a2a44;">${baseDsv}</div>
                        <span style="font-size:0.8rem; color:#5a6a7a;">PCU/hr</span>
                    </div>
                    <div style="background:#f8faff; padding:16px; border-radius:10px; border:1px solid #e0e8f2;">
                        <span style="font-size:0.8rem; color:#5a6a7a; text-transform:uppercase;">Reduced DSV</span>
                        <div style="font-size:2rem; font-weight:700; color:#c44536;">${reducedDsv}</div>
                        <span style="font-size:0.8rem; color:#5a6a7a;">PCU/hr</span>
                    </div>
                    <div style="background:#f8faff; padding:16px; border-radius:10px; border:1px solid #e0e8f2;">
                        <span style="font-size:0.8rem; color:#5a6a7a; text-transform:uppercase;">Capacity Loss</span>
                        <div style="font-size:2rem; font-weight:700; color:#0a2a44;">${lossPercent}%</div>
                        <span style="font-size:0.8rem; color:#5a6a7a;">%</span>
                    </div>
                    <div style="background:#f8faff; padding:16px; border-radius:10px; border:1px solid #e0e8f2;">
                        <span style="font-size:0.8rem; color:#5a6a7a; text-transform:uppercase;">Blocked Width</span>
                        <div style="font-size:2rem; font-weight:700; color:#0a2a44;">${blockedWidth}</div>
                        <span style="font-size:0.8rem; color:#5a6a7a;">metres</span>
                    </div>
                </div>
                <div style="margin-top:16px; padding:16px; background:#f9fbfd; border-radius:10px; border:1px solid #e0e8f2;">
                    <h4 style="margin-bottom:8px; color:#0a2a44;">🕳️ Poth
