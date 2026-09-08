document.addEventListener('DOMContentLoaded', function() {
    console.log("✅ Script loaded!");

    // ---------- TAB SWITCHING ----------
    const tabBtns = document.querySelectorAll('.tab-btn');
    const tabContents = document.querySelectorAll('.tab-content');
    tabBtns.forEach(btn => {
        btn.addEventListener('click', function() {
            tabBtns.forEach(b => b.classList.remove('active'));
            tabContents.forEach(c => c.classList.remove('active'));
            this.classList.add('active');
            document.getElementById('tab-' + this.dataset.tab).classList.add('active');
        });
    });

    // ---------- FILE UPLOAD (FIXED) ----------
    const uploadArea = document.getElementById('uploadArea');
    const fileInput = document.getElementById('fileInput');
    const fileInfo = document.getElementById('fileInfo');

    if (uploadArea && fileInput) {
        // Click on the upload area triggers the hidden file input
        uploadArea.addEventListener('click', function(e) {
            e.preventDefault();
            console.log("📁 Upload area clicked!");
            fileInput.click();
        });

        // When a file is selected, show its name
        fileInput.addEventListener('change', function() {
            if (this.files && this.files.length > 0) {
                const file = this.files[0];
                console.log("📎 File selected:", file.name);
                fileInfo.textContent = '📎 ' + file.name + ' (' + (file.size / 1024 / 1024).toFixed(2) + ' MB)';
                fileInfo.classList.remove('hidden');
            } else {
                fileInfo.classList.add('hidden');
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
            if (e.dataTransfer.files.length > 0) {
                fileInput.files = e.dataTransfer.files;
                fileInput.dispatchEvent(new Event('change'));
            }
        });
    } else {
        console.error("❌ Upload elements not found!");
    }

    // ---------- DSV PREVIEW UPDATE ----------
    function updateDSVPreview() {
        const carriageway = document.getElementById('carriageway').value;
        const fringe = document.getElementById('fringe').value;
        const dsvMap = {
            '2L-U': { base: 1750, speed: 50 }, '2L-D': { base: 2000, speed: 55 },
            '4L-U': { base: 3500, speed: 65 }, '4L-D': { base: 4200, speed: 70 },
            '6L-U': { base: 5600, speed: 80 }, '6L-D': { base: 7000, speed: 85 },
            '8L-U': { base: 10500, speed: 90 }, '8L-D': { base: 12600, speed: 100 }
        };
        let dsv = dsvMap[carriageway] || { base: 2400, speed: 50 };
        if (fringe === 'low') dsv.base *= 1.0;
        else if (fringe === 'medium') dsv.base *= 0.9;
        else dsv.base *= 0.8;
        document.getElementById('baseDsvDisplay').textContent = Math.round(dsv.base).toLocaleString();
        document.getElementById('vehDisplay').textContent = Math.round(dsv.base).toLocaleString();
        document.getElementById('speedDisplay').textContent = dsv.speed;
    }

    const carriagewaySelect = document.getElementById('carriageway');
    const fringeSelect = document.getElementById('fringe');
    if (carriagewaySelect) carriagewaySelect.addEventListener('change', updateDSVPreview);
    if (fringeSelect) fringeSelect.addEventListener('change', updateDSVPreview);
    updateDSVPreview();

    // ---------- RUN ANALYSIS ----------
    const analyzeBtn = document.getElementById('analyzeBtn');
    const statusBar = document.getElementById('statusBar');

    if (analyzeBtn) {
        analyzeBtn.addEventListener('click', async function() {
            const file = fileInput.files[0];
            if (!file) {
                statusBar.textContent = '❌ Please upload an image or video first.';
                statusBar.className = 'status-bar error';
                return;
            }

            const totalWidth = parseFloat(document.getElementById('totalWidth').value);
            if (isNaN(totalWidth) || totalWidth <= 0) {
                statusBar.textContent = '❌ Please enter a valid road width.';
                statusBar.className = 'status-bar error';
                return;
            }

            const formData = new FormData();
            formData.append('file', file);
            formData.append('total_width_m', totalWidth);
            formData.append('carriageway', document.getElementById('carriageway').value);
            formData.append('fringe', document.getElementById('fringe').value);

            analyzeBtn.disabled = true;
            analyzeBtn.textContent = '⏳ Processing...';
            statusBar.textContent = '⏳ Analysing...';
            statusBar.className = 'status-bar';
            document.getElementById('resultContainer').innerHTML = '<div class="placeholder"><p>⏳ Processing your image...</p></div>';

            try {
                const response = await fetch('/analyse', { method: 'POST', body: formData });
                if (!response.ok) {
                    const err = await response.json();
                    throw new Error(err.detail || 'Server error');
                }
                const data = await response.json();
                displayResults(data);
                statusBar.textContent = '✅ Analysis complete.';
                statusBar.className = 'status-bar';
            } catch (error) {
                console.error("❌ Error:", error);
                statusBar.textContent = '❌ Error: ' + error.message;
                statusBar.className = 'status-bar error';
                document.getElementById('resultContainer').innerHTML = '<div class="placeholder"><p style="color:#a33a1a;">❌ ' + error.message + '</p></div>';
            } finally {
                analyzeBtn.disabled = false;
                analyzeBtn.textContent = '🚀 RUN ANALYSIS';
            }
        });
    } else {
        console.error("❌ Analyze button not found!");
    }

    // ---------- DISPLAY RESULTS ----------
    function displayResults(data) {
        const result = data.result;
        const container = document.getElementById('resultContainer');

        if (!result) {
            container.innerHTML = '<div class="placeholder"><p>❌ No results returned.</p></div>';
            return;
        }

        let html = `
            <div style="display:grid; grid-template-columns:1fr 1fr; gap:16px; margin-top:16px;">
                <div style="background:#f8faff; padding:16px; border-radius:10px; border:1px solid #e0e8f2;">
                    <span style="font-size:0.8rem; color:#5a6a7a; text-transform:uppercase;">Baseline DSV</span>
                    <div style="font-size:2rem; font-weight:700; color:#0a2a44;">${result.base_dsv_pcu_hr}</div>
                    <span style="font-size:0.8rem; color:#5a6a7a;">PCU/hr</span>
                </div>
                <div style="background:#f8faff; padding:16px; border-radius:10px; border:1px solid #e0e8f2;">
                    <span style="font-size:0.8rem; color:#5a6a7a; text-transform:uppercase;">Reduced DSV</span>
                    <div style="font-size:2rem; font-weight:700; color:#c44536;">${result.reduced_dsv_pcu_hr}</div>
                    <span style="font-size:0.8rem; color:#5a6a7a;">PCU/hr</span>
                </div>
                <div style="background:#f8faff; padding:16px; border-radius:10px; border:1px solid #e0e8f2;">
                    <span style="font-size:0.8rem; color:#5a6a7a; text-transform:uppercase;">Capacity Loss</span>
                    <div style="font-size:2rem; font-weight:700; color:#0a2a44;">${result.capacity_loss_percent}%</div>
                    <span style="font-size:0.8rem; color:#5a6a7a;">%</span>
                </div>
                <div style="background:#f8faff; padding:16px; border-radius:10px; border:1px solid #e0e8f2;">
                    <span style="font-size:0.8rem; color:#5a6a7a; text-transform:uppercase;">Blocked Width</span>
                    <div style="font-size:2rem; font-weight:700; color:#0a2a44;">${result.blocked_width_m}</div>
                    <span style="font-size:0.8rem; color:#5a6a7a;">metres</span>
                </div>
            </div>
            <div style="margin-top:16px; padding:16px; background:#f9fbfd; border-radius:10px; border:1px solid #e0e8f2;">
                <h4 style="margin-bottom:8px; color:#0a2a44;">🕳️ Pothole Severities</h4>
                <p>${result.pothole_severities && result.pothole_severities.length > 0 ? result.pothole_severities.map(function(s) { return 'Pothole: <strong>' + s.toUpperCase() + '</strong>'; }).join(' | ') : '✅ No potholes detected.'}</p>
            </div>
            <div style="margin-top:16px; padding:16px; background:#eef4fa; border-radius:10px; border:1px solid #dce4ed;">
                <h4 style="margin-bottom:8px; color:#0a2a44;">🚦 Traffic Simulation</h4>
                <p>Speed: <strong>${result.simulation.average_speed_kmh.toFixed(1)}</strong> km/h | Density: <strong>${result.simulation.density_pcu_km.toFixed(1)}</strong> PCU/km | Flow: <strong>${result.simulation.flow_pcu_hr}</strong> PCU/hr</p>
            </div>
        `;

        if (data.recommendations && data.recommendations.length > 0) {
            html += `<div style="margin-top:16px; padding:16px; background:#fef6f0; border-radius:10px; border-left:4px solid #a33a1a;">
                <h4 style="color:#0a2a44;">📋 Recommendations</h4>
                <ul style="list-style:none; padding:0;">`;
            data.recommendations.forEach(function(r) {
                html += `<li style="padding:4px 0;">• <strong>[${r.severity}]</strong> ${r.action}</li>`;
            });
            html += `</ul></div>`;
        }

        container.innerHTML = html;
    }
});
