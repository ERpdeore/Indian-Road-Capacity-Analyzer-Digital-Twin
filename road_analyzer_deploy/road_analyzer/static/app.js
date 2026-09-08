document.addEventListener('DOMContentLoaded', function () {
    const form = document.getElementById('analysisForm');
    const analyzeBtn = document.getElementById('analyzeBtn');
    const loadingIndicator = document.getElementById('loadingIndicator');
    const resultsPanel = document.getElementById('resultsPanel');

    form.addEventListener('submit', async function (e) {
        e.preventDefault();

        // Gather inputs
        const fileInput = document.getElementById('imageInput');
        const totalWidth = parseFloat(document.getElementById('totalWidth').value);
        const carriageway = document.getElementById('carriageway').value;
        const fringe = document.getElementById('fringe').value;

        // Basic validation
        if (!fileInput.files || fileInput.files.length === 0) {
            alert('Please upload a road image.');
            return;
        }
        if (isNaN(totalWidth) || totalWidth <= 0) {
            alert('Please enter a valid road width (greater than 0).');
            return;
        }

        // Build FormData
        const formData = new FormData();
        formData.append('file', fileInput.files[0]);
        formData.append('total_width_m', totalWidth);
        formData.append('carriageway', carriageway);
        formData.append('fringe', fringe);

        // UI loading state
        analyzeBtn.disabled = true;
        analyzeBtn.textContent = '⏳ Processing...';
        loadingIndicator.classList.remove('hidden');
        resultsPanel.classList.add('hidden');

        try {
            const response = await fetch('/analyse', {
                method: 'POST',
                body: formData
            });

            if (!response.ok) {
                const err = await response.json();
                throw new Error(err.detail || 'Server error');
            }

            const data = await response.json();
            displayResults(data);

        } catch (error) {
            alert(`Error: ${error.message}`);
            console.error(error);
        } finally {
            analyzeBtn.disabled = false;
            analyzeBtn.textContent = '🚀 Analyze Road Capacity';
            loadingIndicator.classList.add('hidden');
        }
    });

    function displayResults(data) {
        const result = data.result;
        const recommendations = data.recommendations || [];
        const disclaimer = data.disclaimer || 'This is an estimate...';

        // 1. Capacity Summary
        document.getElementById('baseDsv').textContent = result.base_dsv_pcu_hr;
        document.getElementById('reducedDsv').textContent = result.reduced_dsv_pcu_hr;
        document.getElementById('capacityLoss').textContent = result.capacity_loss_percent.toFixed(1);
        document.getElementById('blockedWidth').textContent = result.blocked_width_m.toFixed(2);
        document.getElementById('usableWidth').textContent = result.usable_width_m.toFixed(2);
        document.getElementById('widthFactor').textContent = result.width_factor.toFixed(3);

        // 2. Pothole Severities
        const potholeList = document.getElementById('potholeList');
        if (result.pothole_severities && result.pothole_severities.length > 0) {
            let html = '<ul style="list-style: none; padding: 0;">';
            result.pothole_severities.forEach((sev, idx) => {
                const emoji = sev === 'shallow' ? '🟢' : (sev === 'moderate' ? '🟡' : '🔴');
                html += `<li style="padding: 6px 0; border-bottom: 1px solid #eee;">
                            ${emoji} Pothole #${idx+1}: <strong>${sev.toUpperCase()}</strong>
                            (Classified per IRC:SP:83-2018 proxy)
                        </li>`;
            });
            html += '</ul>';
            potholeList.innerHTML = html;
        } else {
            potholeList.innerHTML = '✅ No potholes detected in this image.';
        }

        // 3. Simulation
        const sim = result.simulation.steady_state || {};
        document.getElementById('simSpeed').textContent = (sim.speed_kmh || 0).toFixed(1);
        document.getElementById('simDensity').textContent = (sim.density_pcu_km || 0).toFixed(1);
        document.getElementById('simFlow').textContent = (sim.flow_pcu_hr || 0);

        // 4. Recommendations – sort by severity
        const severityOrder = { 'Critical': 1, 'High': 2, 'Medium': 3, 'Low': 4 };
        recommendations.sort((a, b) => (severityOrder[a.severity] || 5) - (severityOrder[b.severity] || 5));

        const recList = document.getElementById('recommendationList');
        recList.innerHTML = '';
        if (recommendations.length === 0) {
            recList.innerHTML = '<li>✅ No immediate engineering actions recommended.</li>';
        } else {
            const colorMap = { 'Critical': '#c44536', 'High': '#d97a2b', 'Medium': '#f0a030', 'Low': '#3a7a5a' };
            recommendations.forEach(rec => {
                const li = document.createElement('li');
                li.style.borderLeftColor = colorMap[rec.severity] || '#0a2a44';
                li.innerHTML = `<strong>[${rec.severity}]</strong> ${rec.action}`;
                recList.appendChild(li);
            });
        }

        // 5. Disclaimer
        document.getElementById('disclaimerText').textContent = disclaimer;

        // Show results
        resultsPanel.classList.remove('hidden');
        resultsPanel.scrollIntoView({ behavior: 'smooth' });
    }
});
