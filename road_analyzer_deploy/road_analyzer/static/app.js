(function () {
  "use strict";

  // ----------------------------------------------------------------
  // Element refs
  // ----------------------------------------------------------------
  const modeBtns = document.querySelectorAll(".mode-btn");
  const dropEl = document.getElementById("drop");
  const fileInput = document.getElementById("file-input");
  const dropTitle = document.getElementById("drop-title");
  const dropHint = document.getElementById("drop-hint");
  const dropFilelist = document.getElementById("drop-filelist");
  const videoSampleRow = document.getElementById("video-sample-row");
  const sampleEverySec = document.getElementById("sample-every-sec");

  const carriagewaySel = document.getElementById("carriageway_key");
  const fringeSel = document.getElementById("fringe_condition");
  const trafficSel = document.getElementById("heavy_traffic_regime");
  const fringeDescEl = document.getElementById("fringe-desc");
  const trafficDescEl = document.getElementById("traffic-desc");

  const configForm = document.getElementById("config-form");
  const runBtn = document.getElementById("run-btn");
  const runBtnLabel = document.getElementById("run-btn-label");
  const modelStatusEl = document.getElementById("model-status");

  const statusPanel = document.getElementById("status-panel");
  const statusText = document.getElementById("status-text");
  const errorBox = document.getElementById("error-box");
  const resultsRoot = document.getElementById("results-root");

  let mode = "image"; // image | batch | video
  let selectedFiles = []; // File[]

  // ----------------------------------------------------------------
  // Mode switching
  // ----------------------------------------------------------------
  const MODE_COPY = {
    image: {
      title: "Drop a road image here, or click to browse",
      hint: "JPG / PNG &middot; near-perpendicular shot of the carriageway works best",
      runLabel: "Run analysis",
      accept: "image/*",
      multiple: false,
    },
    batch: {
      title: "Drop multiple road images here, or click to browse",
      hint: "Select every photo taken along the same stretch &mdash; they'll share the road parameters on the right",
      runLabel: "Run batch analysis",
      accept: "image/*",
      multiple: true,
    },
    video: {
      title: "Drop a road video here, or click to browse",
      hint: "MP4 / MOV &middot; frames are sampled at the interval below, not every frame",
      runLabel: "Run video analysis",
      accept: "video/*",
      multiple: false,
    },
  };

  function setMode(newMode) {
    mode = newMode;
    modeBtns.forEach((b) => b.classList.toggle("active", b.dataset.mode === mode));
    const copy = MODE_COPY[mode];
    dropTitle.textContent = copy.title.replace("&middot;", "·").replace("&mdash;", "—");
    dropHint.innerHTML = copy.hint;
    runBtnLabel.textContent = copy.runLabel;
    fileInput.accept = copy.accept;
    fileInput.multiple = copy.multiple;
    videoSampleRow.style.display = mode === "video" ? "flex" : "none";
    selectedFiles = [];
    dropFilelist.textContent = "";
    fileInput.value = "";
    clearResults();
  }

  modeBtns.forEach((btn) =>
    btn.addEventListener("click", () => setMode(btn.dataset.mode))
  );

  // ----------------------------------------------------------------
  // File picking / drag-drop
  // ----------------------------------------------------------------
  fileInput.addEventListener("change", (e) => handleFiles(e.target.files));

  dropEl.addEventListener("dragover", (e) => {
    e.preventDefault();
    dropEl.classList.add("drag");
  });
  dropEl.addEventListener("dragleave", () => dropEl.classList.remove("drag"));
  dropEl.addEventListener("drop", (e) => {
    e.preventDefault();
    dropEl.classList.remove("drag");
    handleFiles(e.dataTransfer.files);
  });

  function handleFiles(fileList) {
    const files = Array.from(fileList || []);
    if (files.length === 0) return;
    selectedFiles = mode === "batch" ? files : [files[0]];
    dropFilelist.innerHTML = selectedFiles
      .map((f) => `&#10003; ${f.name}`)
      .join("<br>");
  }

  // ----------------------------------------------------------------
  // Config options (populate selects from the backend, so the
  // frontend can never drift out of sync with the IRC tables in
  // core.py)
  // ----------------------------------------------------------------
  async function loadConfigOptions() {
    try {
      const res = await fetch("/api/config-options");
      const data = await res.json();

      carriagewaySel.innerHTML = data.carriageway_keys
        .map((k) => `<option value="${k}">${titleCase(k)}</option>`)
        .join("");

      fringeSel.innerHTML = data.fringe_conditions
        .map((f) => `<option value="${f.key}">${titleCase(f.key)}</option>`)
        .join("");
      fringeSel.addEventListener("change", () => {
        const f = data.fringe_conditions.find((x) => x.key === fringeSel.value);
        fringeDescEl.textContent = f ? f.description : "";
      });
      fringeSel.dispatchEvent(new Event("change"));

      trafficSel.innerHTML = data.heavy_traffic_regimes
        .map((t) => `<option value="${t.key}">${titleCase(t.key)}</option>`)
        .join("");
      trafficSel.addEventListener("change", () => {
        const t = data.heavy_traffic_regimes.find((x) => x.key === trafficSel.value);
        trafficDescEl.textContent = t ? t.description : "";
      });
      trafficSel.value = "high";
      trafficSel.dispatchEvent(new Event("change"));

      if (!data.model_loaded) {
        modelStatusEl.textContent =
          `No trained model found at ${data.model_path} — train in the notebook ` +
          `and copy best.pt into road_analyzer/models/, or set ROAD_MODEL_PATH.`;
        modelStatusEl.classList.add("warn");
      } else {
        modelStatusEl.textContent = `Model loaded from ${data.model_path}`;
      }
    } catch (e) {
      modelStatusEl.textContent = "Could not reach the backend at /api/config-options.";
      modelStatusEl.classList.add("warn");
    }
  }

  // ----------------------------------------------------------------
  // Submit
  // ----------------------------------------------------------------
  configForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    clearResults();

    if (selectedFiles.length === 0) {
      showError(
        mode === "batch"
          ? "Select at least one image first."
          : mode === "video"
          ? "Select a video file first."
          : "Select an image first."
      );
      return;
    }

    const fd = new FormData(configForm);
    runBtn.disabled = true;

    try {
      if (mode === "image") {
        fd.append("file", selectedFiles[0]);
        showStatus("Running detection and IRC capacity analysis…");
        const res = await postJSON("/api/analyze/image", fd);
        hideStatus();
        renderImageResult(res);
      } else if (mode === "batch") {
        selectedFiles.forEach((f) => fd.append("files", f));
        showStatus(`Uploading ${selectedFiles.length} images…`);
        const startRes = await postJSON("/api/analyze/batch", fd);
        showStatus(`Analysing ${startRes.num_images} images… this can take a little while.`);
        const result = await pollJob(startRes.job_id);
        hideStatus();
        renderBatchResult(result);
      } else if (mode === "video") {
        fd.append("file", selectedFiles[0]);
        fd.append("sample_every_sec", sampleEverySec.value);
        showStatus("Uploading video…");
        const startRes = await postJSON("/api/analyze/video", fd);
        showStatus(
          `Sampling frames every ${sampleEverySec.value}s and analysing… this can take a while for longer clips.`
        );
        const result = await pollJob(startRes.job_id);
        hideStatus();
        renderVideoResult(result);
      }
    } catch (err) {
      hideStatus();
      showError(err.message || String(err));
    } finally {
      runBtn.disabled = false;
    }
  });

  async function postJSON(url, formData) {
    const res = await fetch(url, { method: "POST", body: formData });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      throw new Error(data.detail || `Request failed (${res.status})`);
    }
    return data;
  }

  async function pollJob(jobId, intervalMs = 1200, maxWaitMs = 10 * 60 * 1000) {
    const started = Date.now();
    while (Date.now() - started < maxWaitMs) {
      const res = await fetch(`/api/jobs/${jobId}`);
      const data = await res.json();
      if (data.status === "done") return data.result;
      if (data.status === "error") throw new Error(data.error || "Job failed.");
      await new Promise((r) => setTimeout(r, intervalMs));
    }
    throw new Error("Timed out waiting for the job to finish.");
  }

  // ----------------------------------------------------------------
  // Status / error helpers
  // ----------------------------------------------------------------
  function showStatus(text) {
    statusText.textContent = text;
    statusPanel.style.display = "flex";
    errorBox.style.display = "none";
  }
  function hideStatus() {
    statusPanel.style.display = "none";
  }
  function showError(msg) {
    errorBox.textContent = msg;
    errorBox.style.display = "block";
  }
  function clearResults() {
    resultsRoot.innerHTML = "";
    errorBox.style.display = "none";
  }

  // ----------------------------------------------------------------
  // Shared formatting helpers
  // ----------------------------------------------------------------
  function fmt(n, decimals) {
    if (n === null || n === undefined || isNaN(n)) return "—";
    return Number(n).toLocaleString("en-IN", {
      maximumFractionDigits: decimals ?? 1,
      minimumFractionDigits: 0,
    });
  }
  function titleCase(s) {
    return String(s).replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
  }
  function losColor(letter) {
    if (letter === "A" || letter === "B") return { bg: "var(--green-dim)", fg: "#8FCBA3" };
    if (letter === "C" || letter === "D") return { bg: "#3D3517", fg: "var(--yellow)" };
    return { bg: "var(--red-dim)", fg: "#FF8B86" };
  }

  const DEFECT_COLORS = {
    barricade: "#D9534F",
    pothole: "#C97A3D",
    illegal_parking: "#D9534F",
    street_vendor: "#D9B84A",
    cart: "#B58A52",
    garbage: "#7E8A6B",
  };
  const FALLBACK_COLORS = ["#D9534F", "#D9B84A", "#C97A3D", "#B58A52", "#7E8A6B", "#9B6B9E"];
  function colorFor(name, idx) {
    return DEFECT_COLORS[name] || FALLBACK_COLORS[idx % FALLBACK_COLORS.length];
  }

  function defectGridHTML(perDefect) {
    const names = Object.keys(perDefect || {});
    if (names.length === 0) {
      return `<div class="empty-state">No obstructions detected — road operating at full geometric width.</div>`;
    }
    const sorted = names
      .map((name) => ({ name, ...perDefect[name] }))
      .sort((a, b) => (b.capacity_loss_pct || 0) - (a.capacity_loss_pct || 0));

    return `<div class="defect-grid">${sorted
      .map((d) => {
        const sev = d.severity || "INVESTIGATE";
        return `
          <div class="defect-card sev-${sev}">
            <div class="defect-head">
              <div>
                <div class="defect-name">${titleCase(d.name)}</div>
                <div class="defect-count">${d.count} detected &middot; ${fmt(d.blocked_m, 2)} m blocked</div>
              </div>
              <div class="sev-chip sev-${sev}">${sev}</div>
            </div>
            <div class="defect-metrics">
              <div class="m"><div class="v">${fmt(d.capacity_loss_pcu, 0)}</div><div class="l">PCU/hr lost</div></div>
              <div class="m"><div class="v">${fmt(d.capacity_loss_pct, 1)}%</div><div class="l">of capacity</div></div>
            </div>
            <div class="defect-action">${d.action || "No specific action mapped — flag for manual inspection."}</div>
            <div class="defect-code">${d.code_ref || ""}</div>
          </div>`;
      })
      .join("")}</div>`;
  }

  function roadbarHTML(cfg, perDefect) {
    const totalWidth = cfg.total_width_m || 0;
    const names = Object.keys(perDefect || {});
    let blockedTotal = 0;
    const segments = names
      .map((name, i) => {
        const d = perDefect[name];
        blockedTotal += d.blocked_m || 0;
        return { name, blocked_m: d.blocked_m || 0, color: colorFor(name, i) };
      })
      .filter((s) => s.blocked_m > 0.001)
      .sort((a, b) => b.blocked_m - a.blocked_m);
    const usableWidth = Math.max(totalWidth - blockedTotal, 0);

    let barHTML = "";
    if (totalWidth > 0) {
      segments.forEach((seg) => {
        const pct = (seg.blocked_m / totalWidth) * 100;
        barHTML += `<div class="seg" style="width:${pct}%;background:${seg.color}" title="${titleCase(
          seg.name
        )}: ${fmt(seg.blocked_m, 2)} m blocked">${
          pct > 6 ? `<span class="seg-label">${titleCase(seg.name)}</span>` : ""
        }</div>`;
      });
      const usablePct = (usableWidth / totalWidth) * 100;
      barHTML += `<div class="seg usable" style="width:${usablePct}%" title="Usable width: ${fmt(
        usableWidth,
        2
      )} m">${usablePct > 10 ? `<span class="seg-label">Usable</span>` : ""}</div>`;
    }

    const legendHTML =
      segments
        .map(
          (seg) =>
            `<div class="leg"><span class="dot" style="background:${seg.color}"></span>${titleCase(
              seg.name
            )} &middot; ${fmt(seg.blocked_m, 2)} m</div>`
        )
        .join("") +
      `<div class="leg"><span class="dot" style="background:var(--green)"></span>Usable width</div>`;

    return `
      <div class="card roadbar-card">
        <div class="card-title">Carriageway width budget</div>
        <div class="card-sub">How much of the road's physical width each obstruction type consumes, to scale.</div>
        <div class="roadbar">${barHTML}</div>
        <div class="roadbar-meta">
          <span>Total width: ${fmt(totalWidth, 2)} m</span>
          <span>Usable: ${fmt(usableWidth, 2)} m</span>
        </div>
        <div class="roadbar-legend">${legendHTML}</div>
      </div>`;
  }

  function heroHTML(data) {
    const cfg = data.road_config || {};
    const irc = data.irc_basis || {};
    const letter = data.level_of_service || "—";
    const c = losColor(letter);

    const stripParts = [
      ["Carriageway", cfg.carriageway_key],
      ["Fringe condition", cfg.fringe_condition],
      ["Width", cfg.total_width_m != null ? cfg.total_width_m + " m" : null],
      ["Lanes", cfg.num_lanes],
      ["Shoulder", cfg.usable_shoulder_m != null ? cfg.usable_shoulder_m + " m" : null],
      [
        "Design Service Volume",
        irc.design_service_volume_pcu_hr != null
          ? irc.design_service_volume_pcu_hr + " PCU/hr"
          : null,
      ],
    ].filter((p) => p[1] !== null && p[1] !== undefined);

    return `
      <div class="hero">
        <div class="card hero-main">
          <div class="eyebrow">Analysed image &middot; <span class="image-name">${
            data.image || "untitled"
          }</span></div>
          <div class="big-number">${fmt(data.reduced_capacity_pcu_hr, 0)} <small>PCU/hr usable capacity</small></div>
          <div class="compare">
            <div class="item"><div class="label">Original capacity</div><div class="val orig">${fmt(
              data.original_capacity_pcu_hr,
              0
            )} PCU/hr</div></div>
            <div class="item"><div class="label">Reduced capacity</div><div class="val red">${fmt(
              data.reduced_capacity_pcu_hr,
              0
            )} PCU/hr</div></div>
            <div class="item"><div class="label">Capacity lost</div><div class="val loss">${fmt(
              data.capacity_loss_pcu_hr,
              0
            )} PCU/hr (${fmt(data.capacity_loss_pct, 1)}%)</div></div>
          </div>
          <div class="config-strip">${stripParts
            .map(([label, val]) => `<span><b>${label}:</b> ${val}</span>`)
            .join("")}</div>
          ${
            data.vehicle_veto_suppressed
              ? `<div style="margin-top:12px;font-size:12px;color:var(--text-faint);">Note: ${data.vehicle_veto_suppressed} vendor/cart detection(s) were suppressed because they overlapped a vehicle box (likely an auto-rickshaw misclassification).</div>`
              : ""
          }
        </div>
        <div class="card los-card">
          <div>
            <div class="eyebrow">Level of Service (IRC)</div>
            <div class="los-badge-row">
              <div class="los-letter" style="background:${c.bg};color:${c.fg}">${letter}</div>
              <div>
                <div class="los-desc-title">${data.level_of_service_desc || "—"}</div>
                <div class="los-desc-sub">Based on % capacity lost to obstructions</div>
              </div>
            </div>
          </div>
          <div class="los-action">${data.los_action || "—"}</div>
        </div>
      </div>`;
  }

  // ----------------------------------------------------------------
  // Render: single image
  // ----------------------------------------------------------------
  function renderImageResult(data) {
    resultsRoot.innerHTML =
      heroHTML(data) +
      roadbarHTML(data.road_config || {}, data.per_defect || {}) +
      `<div class="section-title">Capacity loss &amp; recommended action by obstruction</div>` +
      defectGridHTML(data.per_defect);
  }

  // ----------------------------------------------------------------
  // Render: batch
  // ----------------------------------------------------------------
  function renderBatchResult(data) {
    const perImage = (data.per_image || []).slice().sort((a, b) => b.capacity_loss_pct - a.capacity_loss_pct);

    const rows = perImage
      .map((r, i) => {
        const c = losColor(r.level_of_service);
        return `
        <tr>
          <td class="rank">${i + 1}</td>
          <td>${r.image}</td>
          <td><span class="los-chip" style="background:${c.bg};color:${c.fg}">${r.level_of_service}</span></td>
          <td>${fmt(r.capacity_loss_pct, 1)}%</td>
          <td class="defects-list">${
            r.defects_found.length ? r.defects_found.map(titleCase).join(", ") : "—"
          }</td>
        </tr>`;
      })
      .join("");

    const errorsHTML =
      data.errors && data.errors.length
        ? `<div class="error-box" style="margin-top:18px;">${data.errors.length} image(s) failed to analyse: ${data.errors
            .map((e) => `${e.image} (${e.error})`)
            .join("; ")}</div>`
        : "";

    resultsRoot.innerHTML = `
      <div class="card" style="margin-bottom:24px;">
        <div class="card-title" style="font-weight:600;margin-bottom:14px;">Batch summary — ${data.num_succeeded}/${data.num_images} images analysed</div>
        <div class="batch-summary-row">
          <div class="batch-stat"><div class="l">Worst stretch</div><div class="v loss">${fmt(
            data.worst_capacity_loss_pct,
            1
          )}%</div></div>
          <div class="batch-stat"><div class="l">Average capacity loss</div><div class="v">${fmt(
            data.avg_capacity_loss_pct,
            1
          )}%</div></div>
          <div class="batch-stat"><div class="l">Worst image</div><div class="v" style="font-size:14px;font-family:'JetBrains Mono',monospace;">${
            data.worst_image_or_frame || "—"
          }</div></div>
        </div>
      </div>
      <div class="section-title">Images ranked by capacity loss (worst first)</div>
      <div class="card">
        <table class="stretch-table">
          <thead><tr><th>#</th><th>Image</th><th>LOS</th><th>Capacity lost</th><th>Defects found</th></tr></thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
      ${errorsHTML}
    `;
  }

  // ----------------------------------------------------------------
  // Render: video
  // ----------------------------------------------------------------
  function renderVideoResult(data) {
    const frames = data.frame_by_frame || [];
    const maxLoss = Math.max(1, ...frames.map((f) => f.capacity_loss_pct || 0));

    const barsHTML = frames
      .map((f) => {
        const h = Math.max(4, (f.capacity_loss_pct / maxLoss) * 86);
        return `<div class="tbar" data-sev="${f.level_of_service}" style="height:${h}px" title="t=${f.timestamp_sec}s &middot; ${fmt(
          f.capacity_loss_pct,
          1
        )}% lost &middot; LOS ${f.level_of_service}"></div>`;
      })
      .join("");

    const uniqueRows = (data.unique_defect_instances || [])
      .slice()
      .sort((a, b) => b.times_seen - a.times_seen)
      .map(
        (d) => `
        <div class="unique-defect-row">
          <span class="udr-name">${titleCase(d.cls_name)}</span>
          <span class="udr-meta">seen ${d.times_seen}&times; &middot; ${fmt(
          d.first_seen_sec,
          1
        )}s&ndash;${fmt(d.last_seen_sec, 1)}s &middot; max ${fmt(d.max_blocked_m, 2)} m blocked</span>
        </div>`
      )
      .join("");

    resultsRoot.innerHTML = `
      <div class="card" style="margin-bottom:24px;">
        <div class="card-title" style="font-weight:600;margin-bottom:14px;">Video summary — ${data.video}</div>
        <div class="batch-summary-row">
          <div class="batch-stat"><div class="l">Worst moment</div><div class="v loss">${fmt(
            data.worst_capacity_loss_pct,
            1
          )}%</div></div>
          <div class="batch-stat"><div class="l">Average capacity loss</div><div class="v">${fmt(
            data.avg_capacity_loss_pct,
            1
          )}%</div></div>
          <div class="batch-stat"><div class="l">Frames analysed</div><div class="v">${
            data.frames_analysed
          } <span style="font-size:13px;color:var(--text-faint);">/ ${data.total_frames_in_video} total, sampled every ${
            data.sampled_every_sec
          }s</span></div></div>
          <div class="batch-stat"><div class="l">Unique defects tracked</div><div class="v">${
            data.unique_defect_count
          }</div></div>
        </div>
      </div>

      <div class="card timeline-card">
        <div class="card-title" style="font-weight:600;margin-bottom:4px;">Capacity loss over time</div>
        <div class="card-sub" style="color:var(--text-faint);font-size:12.5px;margin-bottom:16px;">Each bar is one sampled frame &mdash; height and colour show how much capacity was lost at that moment.</div>
        <div class="timeline-bar">${barsHTML}</div>
        <div class="timeline-meta"><span>0s</span><span>${
          frames.length ? frames[frames.length - 1].timestamp_sec + "s" : "—"
        }</span></div>
      </div>

      <div class="section-title">Unique defect instances across the clip (tracked, not double-counted)</div>
      <div class="unique-defects-list">${
        uniqueRows || `<div class="empty-state">No obstructions detected across the sampled frames.</div>`
      }</div>
    `;
  }

  // ----------------------------------------------------------------
  // Init
  // ----------------------------------------------------------------
  loadConfigOptions();
})();
