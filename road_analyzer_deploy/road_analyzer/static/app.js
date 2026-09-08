document.addEventListener('DOMContentLoaded', function () {
    const form = document.getElementById('analysisForm');
    const fileInput = document.getElementById('fileInput');
    const analyzeBtn = document.getElementById('analyzeBtn');
    const loadingIndicator = document.getElementById('loadingIndicator');
    const resultsPanel = document.getElementById('resultsPanel');
    const statusMessage = document.getElementById('statusMessage');
    const progressFill = document.getElementById('progressFill');

    form.addEventListener('submit', async function (e) {
        e.preventDefault();

        const file = fileInput.files[0];
        if (!file) {
            alert('Please upload a file.');
            return;
        }

        const totalWidth = parseFloat(document.getElementById('totalWidth').value);
        if (isNaN(totalWidth) || totalWidth <= 0) {
            alert('Please enter a valid road width.');
            return;
        }

        const carriageway = document.getElementById('carriageway').value;
        const fringe = document.getElementById('fringe').value;

        const formData = new FormData();
        formData.append('file', file);
        formData.append('total_width_m', totalWidth);
        formData.append('carriageway', carriageway);
        formData.append('fringe', fringe);

        // Determine if it's a video based on MIME type
        const isVideo = file.type.startsWith('video/');

        // UI Loading State
        analyzeBtn.disabled = true;
        analyzeBtn.textContent = '⏳ Submitting...';
        loadingIndicator.classList.remove('hidden');
        resultsPanel.classList.add('hidden');
        progressFill.style.width = '0%';
        statusMessage.textContent = isVideo ? 'Video uploaded. Server is processing...' : 'Processing image...';

        try {
            const endpoint = isVideo ? '/analyse_video' : '/analyse';
            const response = await fetch(endpoint, { method: 'POST', body: formData });

            if (!response.ok) {
                const err = await response.json();
                throw new Error(err.detail || 'Server error');
            }

            const data = await response.json();

            if (isVideo) {
                // --- VIDEO: Polling Logic ---
                const jobId = data.job_id;
                statusMessage.textContent = 'Video processing started. Polling for results...';
                progressFill.style.width = '10%';

                let done = false;
                let attempts = 0;
                const maxAttempts = 60; // 2 minutes max

                while (!done && attempts < maxAttempts) {
                    attempts++;
                    await new Promise(resolve => setTimeout(resolve, 2000)); // Wait 2 seconds

                    const pollRes = await fetch(`/job/${jobId}`);
                    const pollData = await pollRes.json();

                    if (pollData.status === 'completed') {
                        displayVideoResults(pollData);
                        done = true;
                        progressFill.style.width = '100%';
                    } else if (pollData.status === 'failed') {
                        throw new Error(pollData.error || 'Video processing failed.');
                    } else {
                        // Still processing
                        const progress = Math.min(20 + attempts * 1.5, 90);
                        progressFill.style.width = progress + '%';
                        statusMessage.textContent = `Processing frame ${attempts}...`;
                    }
                }

                if (!done) {
                    throw new Error('Video processing timed out after 2 minutes.');
                }

            } else {
                // --- IMAGE: Instant Results ---
                displayImageResults(data);
                progressFill.style.width = '100%';
            }

        } catch (error) {
            alert(`Error: ${error.message}`);
            console.error(error);
            loadingIndicator.classList.add('hidden');
        } finally {
            analyzeBtn.disabled = false;
            analyzeBtn.textContent = '🚀 Analyze';
            loadingIndicator.classList.add('hidden');
        }
    });

    // --- DISPLAY FUNCTIONS ---

    function displayImageResults(data) {
        const result = data.result;
        const container = document.getElementById('dynamicResultContainer');
        container.innerHTML = `
            <div class="result-grid">
                <div class="result-item"><span class="label">Baseline DSV</span><span class="value">${result.base_dsv_pcu_hr}</span><span class="unit">PCU/hr</span></div>
                <div class="result-item"><span class="label">Reduced DSV</span><span class="value highlight">${result.reduced_dsv_pcu_hr}</span><span class="unit">PCU/hr</span></div>
                <div class="result-item"><span class="label">Capacity Loss</span><span class="value">${result.capacity_loss_percent}%</span><span class="unit">%</span></div>
                <div class="result-item"><span class="label">Blocked Width</span><span class="value">${result.blocked_width_m}</span><span class="unit">m</span></div>
                <div class="result-item"><span class="label">Usable Width</span><span class="value">${result.usable_width_m}</span><span class="unit">m</span></div>
                <div class="result-item"><span class="label">Width Factor</span><span class="value">${result.width_factor}</span><span class="unit">-</span></div>
            </div>
            <div id="potholeSection"><h3>🕳️ Potholes</h3><div id="potholeList">${result.pothole_severities.length > 0 ? result.pothole_severities.map((s,i) => `Pothole ${i+1}: ${s.toUpperCase()}`).join(', ') : 'None detected'}</div></div>
            <div id="simulationSection"><h3>🚦 Traffic Sim</h3><p>Speed: ${result.simulation.average_speed_kmh.toFixed(1)} km/h</p></div>
        `;
        document.getElementById('resultsPanel').classList.remove('hidden');
        resultsPanel.scrollIntoView({ behavior: 'smooth' });
    }

    function displayVideoResults(data) {
        const summary = data.summary;
        const timeline = data.timeline || [];
        const container = document.getElementById('dynamicResultContainer');
        
        // Build a simple timeline display
        let timelineHtml = '<ul style="max-height:200px;overflow-y:auto;font-size:0.9rem;background:#f8f9fa;padding:10px;border-radius:6px;">';
        timeline.slice(0, 20).forEach((frame, idx) => {
            timelineHtml += `<li>t=${frame.timestamp_sec}s: Loss ${frame.capacity_loss_percent}%, Blocked ${frame.blocked_width_m}m</li>`;
        });
        if (timeline.length > 20) timelineHtml += `<li>... and ${timeline.length - 20} more frames</li>`;
        timelineHtml += '</ul>';

        container.innerHTML = `
            <div class="result-grid">
                <div class="result-item"><span class="label">Avg. Loss</span><span class="value">${summary.average_capacity_loss_percent}%</span><span class="unit">over ${data.frames_analysed} frames</span></div>
                <div class="result-item"><span class="label">Peak Loss</span><span class="value highlight">${summary.max_capacity_loss_percent}%</span><span class="unit">at worst frame</span></div>
                <div class="result-item"><span class="label">Min Loss</span><span class="value">${summary.min_capacity_loss_percent}%</span><span class="unit">best moment</span></div>
                <div class="result-item"><span class="label">Peak Blocked</span><span class="value">${summary.peak_blocked_width_m}</span><span class="unit">metres</span></div>
                <div class="result-item"><span class="label">Peak Reduced DSV</span><span class="value">${summary.peak_reduced_dsv_pcu_hr}</span><span class="unit">PCU/hr</span></div>
                <div class="result-item"><span class="label">Duration</span><span class="value">${data.total_duration_sec}</span><span class="unit">seconds</span></div>
            </div>
            <h3>⏱️ Dynamic Timeline (1 sample/sec)</h3>
            ${timelineHtml}
            <h3>📋 Recommendations</h3>
            <ul>${data.recommendations.map(r => `<li>[${r.severity}] ${r.action}</li>`).join('')}</ul>
        `;
        document.getElementById('disclaimerText').textContent = data.disclaimer;
        document.getElementById('resultsPanel').classList.remove('hidden');
        resultsPanel.scrollIntoView({ behavior: 'smooth' });
    }
});
