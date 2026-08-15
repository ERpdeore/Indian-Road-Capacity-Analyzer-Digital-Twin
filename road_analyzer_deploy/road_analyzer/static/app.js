(function () {
  "use strict";

  // ----------------------------------------------------------------
  // Element refs
  // ----------------------------------------------------------------
  const modeBtns      = document.querySelectorAll(".mode-btn");
  const dropEl        = document.getElementById("drop");
  const fileInput     = document.getElementById("file-input");
  const dropTitle     = document.getElementById("drop-title");
  const dropHint      = document.getElementById("drop-hint");
  const dropFilelist  = document.getElementById("drop-filelist");
  const videoSampleRow = document.getElementById("video-sample-row");
  const sampleEverySec = document.getElementById("sample-every-sec");

  const carriagewaySel  = document.getElementById("carriageway_key");
  const fringeSel       = document.getElementById("fringe_condition");
  const fringeDescEl    = document.getElementById("fringe-desc");
  const carriageDsvHint = document.getElementById("carriageway-dsv-hint");
  const dsvPreview      = document.getElementById("dsv-preview");
  const dsvValueEl      = document.getElementById("dsv-value");
  const regimeSel       = document.getElementById("traffic_regime");
  const regimeDescEl    = document.getElementById("regime-desc");

  const configForm    = document.getElementById("config-form");
  const runBtn        = document.getElementById("run-btn");
  const runBtnLabel   = document.getElementById("run-btn-label");
  const modelStatusEl = document.getElementById("model-status");

  const statusPanel = document.getElementById("status-panel");
  const statusText  = document.getElementById("status-text");
  const errorBox    = document.getElementById("error-box");
  const resultsRoot = document.getElementById("results-root");

  let mode = "image";
  let selectedFiles = [];
  let configData = null;   // cached /api/config-options response

  // ----------------------------------------------------------------
  // Mode switching
  // ----------------------------------------------------------------
  const MODE_COPY = {
    image: {
      title:    "Drop a road image here, or click to browse",
      hint:     "JPG / PNG · Perpendicular shot of the full carriageway works best",
      runLabel: "Run Analysis",
      accept:   "image/*",
      multiple: false,
    },
    batch: {
      title:    "Drop multiple road images here, or click to browse",
      hint:     "Select every photo taken along the same stretch - they share the road parameters",
      runLabel: "Run Batch Analysis",
      accept:   "image/*",
      multiple: true,
    },
    video: {
      title:    "Drop a road video here, or click to browse",
      hint:     "MP4 / MOV · Frames are sampled at the interval shown below",
      runLabel: "Run Video Analysis",
      accept:   "video/*",
      multiple: false,
    },
  };

  function setMode(newMode) {
    mode = newMode;
    modeBtns.forEach((b) => b.classList.toggle("active", b.dataset.mode === mode));
    const copy = MODE_COPY[mode];
    dropTitle.textContent    = copy.title;
    dropHint.textContent     = copy.hint;
    runBtnLabel.textContent  = copy.runLabel;
    fileInput.accept         = copy.accept;
    fileInput.multiple       = copy.multiple;
    videoSampleRow.style.display = mode === "video" ? "flex" : "none";
    selectedFiles = [];
    dropFilelist.textContent = "";
    fileInput.value          = "";
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
  // Hardcoded fallback config — dropdowns always work even if server
  // is sleeping (Render free tier cold start can take 60 seconds)
  // ----------------------------------------------------------------
  const FALLBACK_CONFIG = {
    carriageway_options: [
      { key: "2lane_oneway",    label: "2-Lane One-Way",
        available_fringes: ["arterial","sub_arterial","collector"],
        dsv_values: { arterial:2400, sub_arterial:1900, collector:1400 } },
      { key: "2lane_twoway",    label: "2-Lane Two-Way",
        available_fringes: ["arterial","sub_arterial","collector"],
        dsv_values: { arterial:1500, sub_arterial:1200, collector:900 } },
      { key: "3lane_oneway",    label: "3-Lane One-Way",
        available_fringes: ["arterial","sub_arterial","collector"],
        dsv_values: { arterial:3600, sub_arterial:2900, collector:2200 } },
      { key: "4lane_undivided", label: "4-Lane Undivided",
        available_fringes: ["arterial","sub_arterial","collector"],
        dsv_values: { arterial:3000, sub_arterial:2400, collector:1800 } },
      { key: "4lane_divided",   label: "4-Lane Divided",
        available_fringes: ["arterial","sub_arterial"],
        dsv_values: { arterial:3600, sub_arterial:2900 } },
      { key: "6lane_undivided", label: "6-Lane Undivided",
        available_fringes: ["arterial","sub_arterial"],
        dsv_values: { arterial:4800, sub_arterial:3800 } },
      { key: "6lane_divided",   label: "6-Lane Divided",
        available_fringes: ["arterial","sub_arterial"],
        dsv_values: { arterial:5400, sub_arterial:4300 } },
      { key: "8lane_divided",   label: "8-Lane Divided",
        available_fringes: ["arterial"],
        dsv_values: { arterial:7200 } },
    ],
    fringe_conditions: [
      { key: "arterial",     description: "No frontage access, no standing vehicles, very little cross traffic" },
      { key: "sub_arterial", description: "Frontage development, side roads, bus stops, no standing vehicles" },
      { key: "collector",    description: "Free frontage access, parked vehicles, bus stops, heavy cross traffic" },
    ],
    traffic_regimes: [
      { key: "low",  description: "Less than 15% heavy vehicles — mostly cars, autos, two-wheelers" },
      { key: "high", description: "15% or more heavy vehicles — significant freight or bus movement" },
    ],
    model_loaded: true,
  };

  function populateDropdowns(data) {
    configData = data;

    // --- Carriageway dropdown ---
    if (carriagewaySel) {
      carriagewaySel.innerHTML = (data.carriageway_options || [])
        .map((o) => `<option value="${o.key}">${o.label}</option>`)
        .join("");
    }

    // --- Fringe dropdown ---
    if (fringeSel) {
      fringeSel.innerHTML = (data.fringe_conditions || [])
        .map((f) => `<option value="${f.key}">${titleCase(f.key)}</option>`)
        .join("");
    }

    // --- Traffic regime dropdown ---
    if (regimeSel) {
      regimeSel.innerHTML = (data.traffic_regimes || [])
        .map((r) => `<option value="${r.key}">${
          r.key === "low"
            ? "Low — <15% heavy vehicles (cars, autos, two-wheelers)"
            : "High — ≥15% heavy vehicles (trucks, buses)"
        }</option>`)
        .join("");
    }

    // Wire up carriageway change — filter fringe options
    if (carriagewaySel) {
      carriagewaySel.onchange = () => {
        const opt = (data.carriageway_options || []).find((o) => o.key === carriagewaySel.value);
        if (opt && fringeSel) {
          Array.from(fringeSel.options).forEach((el) => {
            el.disabled = !(opt.available_fringes || []).includes(el.value);
          });
          if (fringeSel.options[fringeSel.selectedIndex] &&
              fringeSel.options[fringeSel.selectedIndex].disabled) {
            const first = Array.from(fringeSel.options).find((el) => !el.disabled);
            if (first) fringeSel.value = first.value;
          }
          if (fringeDescEl) {
            const fc = (data.fringe_conditions || []).find((f) => f.key === fringeSel.value);
            fringeDescEl.textContent = fc ? fc.description : "";
          }
        }
        updateDsvPreview();
      };
    }

    // Wire up fringe change
    if (fringeSel) {
      fringeSel.onchange = () => {
        if (fringeDescEl) {
          const fc = (data.fringe_conditions || []).find((f) => f.key === fringeSel.value);
          fringeDescEl.textContent = fc ? fc.description : "";
        }
        updateDsvPreview();
      };
    }

    // Wire up regime change
    if (regimeSel) {
      regimeSel.onchange = () => {
        if (regimeDescEl) {
          const r = (data.traffic_regimes || []).find((x) => x.key === regimeSel.value);
          regimeDescEl.textContent = r ? r.description : "";
        }
        updateDsvPreview();
      };
      regimeSel.onchange();
    }

    // Trigger initial updates
    if (carriagewaySel) carriagewaySel.onchange();

    // Model status
    if (!data.model_loaded) {
      modelStatusEl.textContent = "⚠ Model not found — copy best.pt into road_analyzer/models/";
      modelStatusEl.classList.add("warn");
    } else {
      modelStatusEl.textContent = "✓ Model loaded and ready.";
      modelStatusEl.classList.remove("warn");
    }
  }

  // ----------------------------------------------------------------
  // DSV preview — updates when carriageway or fringe changes
  // ----------------------------------------------------------------
  // PCU avg factors for quick vehicles/hr preview
  const AVG_PCU = { low: 1.00, high: 1.30 };

  function updateDsvPreview() {
    if (!configData) return;
    const key    = carriagewaySel.value;
    const fringe = fringeSel.value;
    const regime = regimeSel ? regimeSel.value : "low";
    const opt    = (configData.carriageway_options || []).find((o) => o.key === key);
    if (opt && opt.dsv_values && opt.dsv_values[fringe] !== undefined) {
      const dsv     = opt.dsv_values[fringe];
      const avgPcu  = AVG_PCU[regime] || 1.00;
      const vehPerHr = Math.round(dsv / avgPcu);
      dsvValueEl.textContent = dsv.toLocaleString("en-IN");
      const noteEl = document.getElementById("dsv-note");
      if (noteEl) {
        noteEl.textContent =
          `≈ ${vehPerHr.toLocaleString("en-IN")} vehicles/hr under ${regime} heavy-vehicle regime (IRC:106 Table 1)`;
      }
      dsvPreview.style.display = "";
    } else {
      dsvPreview.style.display = "none";
    }
  }

  // ----------------------------------------------------------------
  // Config options (populate selects from backend)
  // ----------------------------------------------------------------
  async function loadConfigOptions() {
    // Populate with fallback immediately — dropdowns always have values
    populateDropdowns(FALLBACK_CONFIG);
    modelStatusEl.textContent = "⟳ Connecting to server…";

    // Then fetch real data from server with retries
    let retries = 0;
    async function tryFetch() {
      try {
        const res  = await fetch("/api/config-options");
        if (!res.ok) throw new Error("Server returned " + res.status);
        const data = await res.json();
        populateDropdowns(data);
        configData = data;
        modelStatusEl.textContent = data.model_loaded
          ? "✓ Model loaded and ready."
          : "⚠ No trained model found. Copy best.pt into road_analyzer/models/.";
        if (!data.model_loaded) modelStatusEl.classList.add("warn");
      } catch (e) {
        retries++;
        if (retries < 6) {
          modelStatusEl.textContent = "⟳ Server waking up… (" + retries + "/5 attempts)";
          setTimeout(tryFetch, 4000);
        } else {
          modelStatusEl.textContent = "⚠ Could not reach server — using offline defaults.";
          modelStatusEl.classList.add("warn");
        }
      }
    }
    tryFetch();
  }

  // ----------------------------------------------------------------
  // Submit
  // ----------------------------------------------------------------
  configForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    clearResults();

    if (selectedFiles.length === 0) {
      showError(
        mode === "batch"   ? "Select at least one image first."
        : mode === "video" ? "Select a video file first."
        :                    "Select an image first."
      );
      return;
    }

    const fd = new FormData(configForm);
    // traffic_regime is now a valid field - do not delete it

    runBtn.disabled = true;

    try {
      if (mode === "image") {
        fd.append("file", selectedFiles[0]);
        showStatus("Running AI defect detection and IRC:106 capacity analysis…");
        const res = await postJSON("/api/analyze/image", fd);
        hideStatus();
        renderImageResult(res);

        // Trigger Digital Twin panel if MATLAB is running
        if (res.digital_twin_status === "running") {
          dtShowPanel();
          dtStartPolling();
        }

      } else if (mode === "batch") {
        selectedFiles.forEach((f) => fd.append("files", f));
        showStatus(`Uploading ${selectedFiles.length} images…`);
        const startRes = await postJSON("/api/analyze/batch", fd);
        showStatus(`Analysing ${startRes.num_images} images in background… please wait.`);
        const result = await pollJob(startRes.job_id);
        hideStatus();
        renderBatchResult(result);

      } else if (mode === "video") {
        fd.append("file", selectedFiles[0]);
        fd.append("sample_every_sec", sampleEverySec.value);
        showStatus("Uploading video…");
        const startRes = await postJSON("/api/analyze/video", fd);
        showStatus(
          `Sampling every ${sampleEverySec.value}s and analysing frames… this takes time for longer clips.`
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
    const res  = await fetch(url, { method: "POST", body: formData });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      throw new Error(data.detail || `Request failed (${res.status})`);
    }
    return data;
  }

  // pollJob - waits for batch/video background job to complete
  // FIX: was previously broken on second upload because JOBS dict
  // in old code shared state. Now each job gets a unique ID so
  // polling never picks up a stale result.
  async function pollJob(jobId, intervalMs = 1500, maxWaitMs = 15 * 60 * 1000) {
    const started = Date.now();
    while (Date.now() - started < maxWaitMs) {
      const res  = await fetch(`/api/jobs/${jobId}`);
      const data = await res.json();
      if (data.status === "done")  return data.result;
      if (data.status === "error") throw new Error(data.error || "Job failed.");
      await new Promise((r) => setTimeout(r, intervalMs));
    }
    throw new Error("Timed out waiting for the analysis job to finish.");
  }

  // ----------------------------------------------------------------
  // Status / error helpers
  // ----------------------------------------------------------------
  function showStatus(text) {
    statusText.textContent       = text;
    statusPanel.style.display    = "flex";
    errorBox.style.display       = "none";
  }
  function hideStatus() { statusPanel.style.display = "none"; }
  function showError(msg) {
    errorBox.textContent      = "⚠ " + msg;
    errorBox.style.display    = "block";
  }
  function clearResults() {
    resultsRoot.innerHTML      = "";
    errorBox.style.display     = "none";
    const dtPanel = document.getElementById("dt-panel");
    if (dtPanel) dtPanel.style.display = "none";
  }

  // ----------------------------------------------------------------
  // Formatting helpers
  // ----------------------------------------------------------------
  function fmt(n, decimals) {
    if (n === null || n === undefined || isNaN(n)) return "-";
    return Number(n).toLocaleString("en-IN", {
      maximumFractionDigits: decimals ?? 1,
      minimumFractionDigits: 0,
    });
  }
  function titleCase(s) {
    return String(s).replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
  }

  const DEFECT_COLORS = {
    barricade:       "#D9534F",
    pothole:         "#C97A3D",
    illegal_parking: "#D9534F",
    street_vendor:   "#D9B84A",
    cart:            "#B58A52",
    garbage:         "#7E8A6B",
    tree_on_road:    "#5C8A5C",
  };
  const FALLBACK_COLORS = ["#D9534F","#D9B84A","#C97A3D","#B58A52","#7E8A6B","#9B6B9E"];
  function colorFor(name, idx) {
    return DEFECT_COLORS[name] || FALLBACK_COLORS[idx % FALLBACK_COLORS.length];
  }

  // ----------------------------------------------------------------
  // HTML builders
  // ----------------------------------------------------------------

  function heroHTML(data) {
    const cfg = data.road_config  || {};
    const irc = data.irc_basis    || {};
    const calc = data.capacity_calculation || {};

    const regime   = data.traffic_regime || {};
    const stripParts = [
      ["Carriageway",    titleCase(cfg.carriageway_key || "")],
      ["Fringe",         titleCase(cfg.fringe_condition || "")],
      ["Total width",    cfg.total_width_m   != null ? cfg.total_width_m   + " m" : null],
      ["Lanes",          cfg.num_lanes],
      ["Shoulder",       cfg.usable_shoulder_m != null ? cfg.usable_shoulder_m + " m" : null],
      ["Traffic regime", regime.regime ? (regime.regime === "low" ? "Low (<15% heavy)" : "High (≥15% heavy)") : null],
      ["Base DSV",       irc.base_dsv_pcu_hr  != null ? irc.base_dsv_pcu_hr  + " PCU/hr" : null],
      ["Avg PCU/veh",    regime.avg_pcu_per_vehicle != null ? regime.avg_pcu_per_vehicle : null],
    ].filter((p) => p[1] !== null && p[1] !== undefined);

    return `
      <div class="hero">
        <div class="card hero-main">
          <div class="eyebrow">Analysed · <span class="image-name">${data.image || "untitled"}</span></div>
          <div class="big-number">${fmt(data.reduced_capacity_pcu_hr, 0)} <small>PCU/hr usable capacity</small></div>
          <div class="compare">
            <div class="item">
              <div class="label">Base capacity (IRC:106)</div>
              <div class="val orig">${fmt(data.original_capacity_pcu_hr, 0)} PCU/hr</div>
              ${data.original_capacity_vehicles_hr ? `<div class="val-sub">${fmt(data.original_capacity_vehicles_hr, 0)} vehicles/hr</div>` : ""}
            </div>
            <div class="item">
              <div class="label">Reduced capacity</div>
              <div class="val red">${fmt(data.reduced_capacity_pcu_hr, 0)} PCU/hr</div>
              ${data.reduced_capacity_vehicles_hr ? `<div class="val-sub">${fmt(data.reduced_capacity_vehicles_hr, 0)} vehicles/hr</div>` : ""}
            </div>
            <div class="item">
              <div class="label">Capacity lost</div>
              <div class="val loss">${fmt(data.capacity_loss_pcu_hr, 0)} PCU/hr (${fmt(data.capacity_loss_pct, 1)}%)</div>
              ${data.capacity_loss_vehicles_hr ? `<div class="val-sub">${fmt(data.capacity_loss_vehicles_hr, 0)} vehicles/hr lost</div>` : ""}
            </div>
          </div>
          ${calc.formula ? `<div class="formula-box mono">Formula: ${calc.formula}</div>` : ""}
          <div class="config-strip">${stripParts.map(([l, v]) => `<span><b>${l}:</b> ${v}</span>`).join("")}</div>
          ${data.vehicle_veto_suppressed
            ? `<div class="veto-note">Note: ${data.vehicle_veto_suppressed} vendor/cart detection(s) suppressed (overlapped a vehicle - likely auto-rickshaw misclassification).</div>`
            : ""}
        </div>
        <div class="card capacity-band-card">
          <div class="eyebrow">Overall Road Condition</div>
          ${overallBandHTML(data)}
        </div>
      </div>`;
  }

  function overallBandHTML(data) {
    const g   = data.overall_guidance || {};
    const pct = data.capacity_loss_pct || 0;
    const bandColors = {
      Minor:       { bg: "#0d2b1a", fg: "#4ade80", border: "#22c55e" },
      Moderate:    { bg: "#2d2600", fg: "#fbbf24", border: "#f59e0b" },
      Significant: { bg: "#2d2600", fg: "#fbbf24", border: "#f59e0b" },
      Severe:      { bg: "#2d0a0a", fg: "#f87171", border: "#ef4444" },
      Critical:    { bg: "#2d0a0a", fg: "#f87171", border: "#ef4444" },
    };
    const c = bandColors[g.band] || bandColors.Moderate;
    return `
      <div style="border-left:3px solid ${c.border};padding-left:14px;margin-top:8px;">
        <div style="font-family:'Oswald',sans-serif;font-size:2rem;color:${c.fg};font-weight:700;">${fmt(pct, 1)}%</div>
        <div style="display:inline-block;background:${c.bg};color:${c.fg};padding:2px 10px;border-radius:4px;font-size:11px;font-family:monospace;margin:6px 0;">${(g.band || "").toUpperCase()}</div>
        <div style="font-size:13px;color:#94a3b8;line-height:1.5;margin-top:6px;">${g.action || ""}</div>
      </div>`;
  }

  function overallGuidanceHTML(data) { return ""; }  // merged into heroHTML above

  function roadbarHTML(cfg, perDefect) {
    const totalWidth = cfg.total_width_m || 0;
    const names = Object.keys(perDefect || {});
    const segments = names
      .map((name, i) => ({ name, blocked_m: perDefect[name].blocked_m || 0, color: colorFor(name, i) }))
      .filter((s) => s.blocked_m > 0.001)
      .sort((a, b) => b.blocked_m - a.blocked_m);

    const blockedTotal = segments.reduce((s, seg) => s + seg.blocked_m, 0);
    const scale        = (blockedTotal > totalWidth && totalWidth > 0) ? totalWidth / blockedTotal : 1;
    const usableWidth  = Math.max(totalWidth - blockedTotal, 0);

    let barHTML = "";
    if (totalWidth > 0) {
      segments.forEach((seg) => {
        const pct = ((seg.blocked_m * scale) / totalWidth) * 100;
        barHTML += `<div class="seg" style="width:${pct}%;background:${seg.color}" title="${titleCase(seg.name)}: ${fmt(seg.blocked_m,2)}m">${pct > 6 ? `<span class="seg-label">${titleCase(seg.name)}</span>` : ""}</div>`;
      });
      const usablePct = (usableWidth / totalWidth) * 100;
      barHTML += `<div class="seg usable" style="width:${usablePct}%" title="Usable: ${fmt(usableWidth,2)}m">${usablePct > 10 ? `<span class="seg-label">Usable</span>` : ""}</div>`;
    }

    const legendHTML =
      segments.map((seg) => `<div class="leg"><span class="dot" style="background:${seg.color}"></span>${titleCase(seg.name)} · ${fmt(seg.blocked_m,2)} m</div>`).join("") +
      `<div class="leg"><span class="dot" style="background:var(--green)"></span>Usable width · ${fmt(usableWidth,2)} m</div>`;

    return `
      <div class="card roadbar-card">
        <div class="card-title">Carriageway Width Budget</div>
        <div class="card-sub">How each obstruction type consumes road width - overlap-aware (no double counting).</div>
        <div class="roadbar">${barHTML}</div>
        <div class="roadbar-meta"><span>Total: ${fmt(totalWidth,2)} m</span><span>Usable: ${fmt(usableWidth,2)} m</span><span>Blocked: ${fmt(Math.min(blockedTotal,totalWidth),2)} m</span></div>
        <div class="roadbar-legend">${legendHTML}</div>
      </div>`;
  }

  // ----------------------------------------------------------------
  // DEFECT ALERT BANNER
  // Shows a bold count summary + urgent alert chips at top of results
  // ----------------------------------------------------------------
  const DEFECT_ICONS = {
    pothole:         "🕳️",
    illegal_parking: "🚗",
    street_vendor:   "🛒",
    cart:            "🛺",
    garbage:         "🗑️",
    barricade:       "🚧",
    tree_on_road:    "🌳",
  };

  const DEFECT_ALERT_MESSAGES = {
    pothole: {
      URGENT:  "Potholes are SEVERE - emergency repair required within 24 hours (IRC:SP:83).",
      ROUTINE: "Potholes detected - patch with hot-mix asphalt within 7 days.",
      MONITOR: "Minor potholes noted - log and monitor at next maintenance cycle.",
    },
    illegal_parking: {
      URGENT:  "Illegal parking is critically blocking road - immediate towing required (MV Act Sec.122).",
      ROUTINE: "Illegal parking detected - deploy wardens and install No-Parking signage.",
      MONITOR: "Occasional parking noted - repaint road markings (IRC:35).",
    },
    street_vendor: {
      URGENT:  "Roadside vendors severely blocking carriageway - immediate relocation required.",
      ROUTINE: "Vendors occupying road space - coordinate relocation with Town Vending Committee.",
      MONITOR: "Vendor activity recorded - flag for Town Vending Committee review.",
    },
    cart: {
      URGENT:  "Carts blocking road - immediate removal required, designate loading bay.",
      ROUTINE: "Carts detected - restrict to designated off-peak zones.",
      MONITOR: "Cart movement noted - no immediate action needed.",
    },
    garbage: {
      URGENT:  "Garbage severely blocking road - immediate clearance under SWM Rules 2016.",
      ROUTINE: "Garbage dump detected - priority clearance within 48 hours.",
      MONITOR: "Minor garbage noted - schedule at next municipal collection.",
    },
    barricade: {
      URGENT:  "Barricade severely restricting road - coordinate immediate removal (IRC:SP:55).",
      ROUTINE: "Work zone barricade - ensure proper signage and reduce width to minimum.",
      MONITOR: "Barricade detected - verify valid permit and signage per IRC:SP:55.",
    },
    tree_on_road: {
      URGENT:  "Tree on road - immediate removal by tree authority, place diversion signage.",
      ROUTINE: "Tree encroaching on road - request pruning within 7 days.",
      MONITOR: "Tree noted - log for tree authority inspection.",
    },
  };

  function defectAlertBannerHTML(perDefect) {
    const entries = Object.entries(perDefect || {});
    if (entries.length === 0) return "";

    // Sort: URGENT first, then ROUTINE, then MONITOR
    const sevOrder = { URGENT: 0, ROUTINE: 1, MONITOR: 2, NONE: 3, INVESTIGATE: 4 };
    const sorted   = entries
      .map(([name, d]) => ({ name, ...d }))
      .filter((d) => d.severity !== "NONE")
      .sort((a, b) => (sevOrder[a.severity] ?? 9) - (sevOrder[b.severity] ?? 9));

    if (sorted.length === 0) return "";

    // Count summary row
    const countChips = sorted.map((d) => `
      <div class="alert-count-chip sev-bg-${d.severity}">
        <span class="alert-chip-icon">${DEFECT_ICONS[d.name] || "⚠️"}</span>
        <span class="alert-chip-num">${d.count}</span>
        <span class="alert-chip-name">${titleCase(d.name)}</span>
      </div>`).join("");

    // Alert messages
    const alerts = sorted.map((d) => {
      const msg = (DEFECT_ALERT_MESSAGES[d.name] || {})[d.severity]
        || d.action
        || "Defect detected - take appropriate action.";
      return `
        <div class="alert-row sev-row-${d.severity}">
          <div class="alert-row-left">
            <span class="alert-sev-dot sev-dot-${d.severity}"></span>
            <span class="alert-sev-label">${d.severity}</span>
            <span class="alert-defect-name">${DEFECT_ICONS[d.name] || ""} ${titleCase(d.name)}</span>
          </div>
          <div class="alert-row-msg">${msg}</div>
          <div class="alert-row-stats">
            <span>${d.count} detected</span>
            <span>${fmt(d.blocked_m, 2)} m blocked</span>
            <span>${fmt(d.capacity_loss_pct, 1)}% capacity lost</span>
          </div>
        </div>`;
    }).join("");

    const hasUrgent = sorted.some((d) => d.severity === "URGENT");

    return `
      <div class="alert-panel ${hasUrgent ? "has-urgent" : ""}">
        <div class="alert-panel-header">
          <div class="alert-panel-title">
            ${hasUrgent ? "🚨" : "⚠️"} Road Defect Alerts
          </div>
          <div class="alert-panel-sub">${sorted.length} defect type${sorted.length > 1 ? "s" : ""} detected - action required</div>
        </div>
        <div class="alert-count-row">${countChips}</div>
        <div class="alert-rows">${alerts}</div>
      </div>`;
  }

  function defectGridHTML(perDefect) {
    const names = Object.keys(perDefect || {});
    if (names.length === 0) {
      return `<div class="empty-state">No obstructions detected - road operating at full geometric width.</div>`;
    }
    const sorted = names
      .map((name) => ({ name, ...perDefect[name] }))
      .sort((a, b) => (b.capacity_loss_pct || 0) - (a.capacity_loss_pct || 0));

    return `<div class="defect-grid">${sorted.map((d) => {
      const sev   = d.severity || "INVESTIGATE";
      const depth = d.depth_summary;
      const depthHTML = depth ? `
        <div class="depth-summary">
          <span class="depth-sev depth-${depth.worst_severity}">${depth.worst_severity.toUpperCase()} POTHOLE</span>
          <span class="depth-detail">~${depth.avg_estimated_depth_cm} cm avg depth · penalty factor: ${depth.penalty_applied}</span>
        </div>` : "";
      return `
        <div class="defect-card sev-${sev}">
          <div class="defect-head">
            <div>
              <div class="defect-name">${titleCase(d.name)}</div>
              <div class="defect-count">${d.count} detected · ${fmt(d.blocked_m,2)} m blocked (overlap-aware)</div>
            </div>
            <div class="sev-chip sev-${sev}">${sev}</div>
          </div>
          <div class="defect-metrics">
            <div class="m"><div class="v">${fmt(d.capacity_loss_pcu,0)}</div><div class="l">PCU/hr lost</div></div>
            <div class="m"><div class="v">${fmt(d.capacity_loss_pct,1)}%</div><div class="l">of capacity</div></div>
            <div class="m"><div class="v">${fmt(d.width_factor ? (1-d.width_factor)*100 : null,1)}%</div><div class="l">width reduction</div></div>
          </div>
          ${depthHTML}
          <div class="defect-action">${d.action || "No specific action mapped - flag for manual inspection."}</div>
          <div class="defect-code">${d.code_ref || ""}</div>
        </div>`;
    }).join("")}</div>`;
  }

  // ----------------------------------------------------------------
  // MATLAB Digital Twin button
  // ----------------------------------------------------------------
  function matlabButtonHTML(data) {
    return `
      <div class="matlab-twin-bar">
        <div class="matlab-twin-info">
          <span class="matlab-twin-icon">⚡</span>
          <div>
            <div class="matlab-twin-title">Digital Twin - MATLAB Animation</div>
            <div class="matlab-twin-sub">Click to download a MATLAB script pre-loaded with your analysis results.
            Open in MATLAB R2022b+ to see animated vehicle behaviour on ideal vs defect road.</div>
          </div>
        </div>
        <button class="matlab-dl-btn" id="matlab-dl-btn">
          ↓ Download MATLAB Script
        </button>
      </div>`;
  }

  function generateMatlabScript(data) {
    const cfg  = data.road_config         || {};
    const calc = data.capacity_calculation || {};
    const irc  = data.irc_basis           || {};
    const tr   = data.traffic_regime      || {};

    const base       = data.original_capacity_pcu_hr || 1500;
    const reduced    = data.reduced_capacity_pcu_hr  || 1200;
    const lossPct    = data.capacity_loss_pct        || 0;
    const wf         = calc.width_factor             || 1;
    const pen        = calc.pothole_penalty          || 1;
    const blocked    = calc.total_blocked_m          || 0;
    const effW       = calc.effective_width_m        || cfg.total_width_m || 7;
    const totalW     = cfg.total_width_m             || 7;
    const lanes      = cfg.num_lanes                 || 2;
    const depth      = calc.worst_pothole_depth      || 'unknown';
    const fringe     = cfg.fringe_condition          || 'arterial';
    const cwKey      = cfg.carriageway_key           || '2lane_twoway';
    const regime     = tr.regime                     || 'low';
    const avgPcu     = tr.avg_pcu_per_vehicle        || 1.0;
    const baseVeh    = data.original_capacity_vehicles_hr || Math.round(base / avgPcu);
    const redVeh     = data.reduced_capacity_vehicles_hr  || Math.round(reduced / avgPcu);
    const image      = data.image                    || 'unknown';

    const defects = Object.keys(data.per_defect || {});
    const defectLabel = defects.length ? defects.join(' + ') : 'none detected';

    return `%% ================================================================
%% INDIAN ROAD CAPACITY DIGITAL TWIN - MATLAB ANIMATION SCRIPT
%% Auto-generated from dashboard analysis
%% Image analysed: ${image}
%% Generated: ${new Date().toISOString()}
%%
%% HOW TO RUN:
%%   1. Open MATLAB R2022b or later
%%   2. cd to the folder containing this file
%%   3. Type:  roadtwin
%%   4. Press Enter - animation window opens automatically
%% ================================================================

function roadtwin()

%% --- Parameters from your analysis (IRC:106-1990) ---
base_dsv         = ${base};        %% PCU/hr  - IRC:106 Table 2 DSV
reduced_cap      = ${reduced};     %% PCU/hr  - after defects
cap_loss_pct     = ${lossPct.toFixed(1)};      %% % capacity lost
total_width_m    = ${totalW};      %% metres  - measured on site
blocked_width_m  = ${blocked.toFixed(2)};    %% metres  - overlap-aware union
eff_width_m      = ${effW.toFixed(2)};       %% metres  - effective usable width
width_factor     = ${wf.toFixed(4)};    %% = eff_width / total_width
pothole_penalty  = ${pen};         %% 0.95/0.85/0.70/1.0
worst_depth      = '${depth}';    %% shallow/moderate/deep/unknown
num_lanes        = ${lanes};       %% number of lanes
carriageway_key  = '${cwKey}';    %% IRC:106 carriageway type
fringe_condition = '${fringe}';   %% arterial/sub_arterial/collector
traffic_regime   = '${regime}';   %% low/high heavy vehicle %
avg_pcu          = ${avgPcu.toFixed(3)};    %% avg PCU per vehicle (IRC:106 Table 1)
base_veh_hr      = ${baseVeh};    %% vehicles/hr (ideal)
reduced_veh_hr   = ${redVeh};     %% vehicles/hr (defect)
image_name       = '${image}';
defects_found    = '${defectLabel}';

%% --- Derived values ---
FREE_FLOW_SPEED = 50;   %% km/h
vc_ratio        = reduced_cap / base_dsv;
congested_speed = FREE_FLOW_SPEED * (1 - (1 - vc_ratio) * 0.5);

has_pothole   = ${defects.includes('pothole') ? 'true' : 'false'};
has_vendor    = ${defects.includes('street_vendor') ? 'true' : 'false'};
has_parking   = ${defects.includes('illegal_parking') ? 'true' : 'false'};
has_barricade = ${defects.includes('barricade') ? 'true' : 'false'};
has_garbage   = ${defects.includes('garbage') ? 'true' : 'false'};
has_tree      = ${defects.includes('tree_on_road') ? 'true' : 'false'};
has_cart      = ${defects.includes('cart') ? 'true' : 'false'};

%% --- Animation setup ---
ROAD_LEN    = 100;
LANE_H      = 8;
ROAD_TOP_I  = 5;
ROAD_TOP_D  = 50;
VEH_LEN     = 4;
VEH_H       = 3;
OBS_X       = 55;
N_VEH       = 12;

headway_ideal  = 3600 / max(base_dsv, 1);
headway_defect = 3600 / max(reduced_cap, 1);
spd_i_ms = FREE_FLOW_SPEED / 3.6;
spd_d_ms = congested_speed / 3.6;
spc_i    = max(spd_i_ms * headway_ideal,  6);
spc_d    = max(spd_d_ms * headway_defect, 4);

vx_i = linspace(-spc_i*(N_VEH-1), 0, N_VEH)';
vx_d = linspace(-spc_d*(N_VEH-1), 0, N_VEH)';
vs_i = FREE_FLOW_SPEED / 3.6 * 0.1;
vs_d = congested_speed / 3.6 * 0.1;

lane_y_i = arrayfun(@(l) ROAD_TOP_I + (l-0.5)*LANE_H, 1:num_lanes);
lane_y_d = arrayfun(@(l) ROAD_TOP_D + (l-0.5)*LANE_H, 1:num_lanes);

fig = figure('Name','Road Digital Twin','Color',[0.09 0.11 0.14], ...
             'Position',[80 80 1180 680],'NumberTitle','off', ...
             'MenuBar','none','ToolBar','none');
ax  = axes('Parent',fig,'Position',[0.01 0.18 0.98 0.78], ...
           'XLim',[0 ROAD_LEN],'YLim',[0 70], ...
           'Color',[0.09 0.11 0.14],'XColor',[0.09 0.11 0.14],'YColor',[0.09 0.11 0.14]);
hold(ax,'on');

%% --- Draw roads ---
C_I = [0.55 0.58 0.62]; C_D = [0.50 0.52 0.55];
C_GI= [0.11 0.62 0.46]; C_GD= [0.89 0.29 0.28];

rectangle('Position',[0 ROAD_TOP_I ROAD_LEN LANE_H*num_lanes],'FaceColor',C_I,'EdgeColor','none');
rectangle('Position',[0 ROAD_TOP_D ROAD_LEN LANE_H*num_lanes],'FaceColor',C_D,'EdgeColor','none');

for ln=1:num_lanes-1
  for x=0:8:ROAD_LEN
    line([x x+4],[ROAD_TOP_I+ln*LANE_H ROAD_TOP_I+ln*LANE_H],'Color',[1 1 1 0.3],'LineWidth',1);
    line([x x+4],[ROAD_TOP_D+ln*LANE_H ROAD_TOP_D+ln*LANE_H],'Color',[1 1 1 0.3],'LineWidth',1);
  end
end

line([0 ROAD_LEN],[ROAD_TOP_I ROAD_TOP_I],'Color',[1 1 1],'LineWidth',1.5);
line([0 ROAD_LEN],[ROAD_TOP_I+LANE_H*num_lanes ROAD_TOP_I+LANE_H*num_lanes],'Color',[1 1 1],'LineWidth',1.5);
line([0 ROAD_LEN],[ROAD_TOP_D ROAD_TOP_D],'Color',[1 1 1],'LineWidth',1.5);
line([0 ROAD_LEN],[ROAD_TOP_D+LANE_H*num_lanes ROAD_TOP_D+LANE_H*num_lanes],'Color',[1 1 1],'LineWidth',1.5);

%% --- Draw defects ---
blk_px = (blocked_width_m/total_width_m)*ROAD_LEN*0.35;
rectangle('Position',[OBS_X ROAD_TOP_D blk_px LANE_H*num_lanes], ...
          'FaceColor',[0.89 0.29 0.28 0.2],'EdgeColor',[0.89 0.29 0.28 0.5],'LineWidth',1);

if has_pothole
  theta=linspace(0,2*pi,40);
  fill(OBS_X+1.5+1.8*cos(theta), ROAD_TOP_D+LANE_H*0.4+0.9*sin(theta), ...
       [0.25 0.20 0.20],'EdgeColor',[0.6 0.2 0.2],'LineWidth',1.5);
  text(OBS_X+1.5,ROAD_TOP_D+LANE_H*0.4+2.5,sprintf('Pothole (%s)',worst_depth), ...
       'Color',[1 0.7 0.7],'FontSize',7,'HorizontalAlignment','center');
end
if has_vendor
  rectangle('Position',[OBS_X+blk_px*0.5-1.5 ROAD_TOP_D+LANE_H*0.6 3 2.5], ...
            'FaceColor',[0.95 0.68 0.10],'EdgeColor',[0.7 0.5 0],'Curvature',0.1);
  text(OBS_X+blk_px*0.5,ROAD_TOP_D+LANE_H*0.6+4,'Vendor', ...
       'Color',[0.95 0.80 0.20],'FontSize',7,'HorizontalAlignment','center');
end
if has_parking
  rectangle('Position',[OBS_X+blk_px*0.4-2 ROAD_TOP_D+LANE_H*0.8 4 2], ...
            'FaceColor',[0.89 0.29 0.28],'EdgeColor',[0.7 0.1 0.1],'Curvature',0.25);
  text(OBS_X+blk_px*0.4,ROAD_TOP_D+LANE_H*0.8-1.5,'Illegal Parking', ...
       'Color',[1 0.6 0.6],'FontSize',7,'HorizontalAlignment','center');
end

text(ROAD_LEN*0.5,ROAD_TOP_I-2.5,'IDEAL ROAD - NO DEFECTS', ...
     'Color',C_GI,'FontSize',11,'FontWeight','bold','HorizontalAlignment','center');
text(ROAD_LEN*0.5,ROAD_TOP_D-2.5,['DEFECT ROAD - ' upper(defects_found)], ...
     'Color',C_GD,'FontSize',11,'FontWeight','bold','HorizontalAlignment','center');

%% --- Stats panels ---
NL = newline;
annotation('rectangle',[0.01 0.01 0.47 0.16],'Color',C_GI,'LineWidth',1.5,'FaceColor',[0.05 0.15 0.10]);
annotation('rectangle',[0.52 0.01 0.47 0.16],'Color',C_GD,'LineWidth',1.5,'FaceColor',[0.18 0.06 0.06]);
ideal_str = ['IDEAL ROAD' NL ...
  sprintf('DSV: %d PCU/hr | %d veh/hr', round(base_dsv), round(base_veh_hr)) NL ...
  sprintf('Speed: %d km/h | Lanes: %d', round(FREE_FLOW_SPEED), num_lanes) NL ...
  sprintf('Carriageway: %s | Fringe: %s', carriageway_key, fringe_condition)];
annotation('textbox',[0.01 0.01 0.47 0.16],'String',ideal_str, ...
  'Color',[0.80 0.96 0.88],'FontSize',10,'FontName','Courier New','EdgeColor','none', ...
  'VerticalAlignment','middle','HorizontalAlignment','center');
defect_str = ['DEFECT ROAD' NL ...
  sprintf('Capacity: %d PCU/hr | %d veh/hr (-%.1f%%)', round(reduced_cap), round(reduced_veh_hr), cap_loss_pct) NL ...
  sprintf('Speed: %.1f km/h | Width factor: %.3f', congested_speed, width_factor) NL ...
  sprintf('Pothole penalty: %.2f | Blocked: %.1fm', pothole_penalty, blocked_width_m)];
annotation('textbox',[0.52 0.01 0.47 0.16],'String',defect_str, ...
  'Color',[0.98 0.78 0.78],'FontSize',10,'FontName','Courier New','EdgeColor','none', ...
  'VerticalAlignment','middle','HorizontalAlignment','center');

title_str=sprintf('Indian Road Digital Twin | %s | Loss: %.1f%% | Defects: %s', ...
  image_name, cap_loss_pct, defects_found);
annotation('textbox',[0.01 0.96 0.98 0.04],'String',title_str,'Color',[0.95 0.95 0.95], ...
  'FontSize',11,'FontWeight','bold','EdgeColor','none','HorizontalAlignment','center','FaceColor','none');

%% --- Vehicle patches ---
vp_i=gobjects(N_VEH,1); vp_d=gobjects(N_VEH,1);
for v=1:N_VEH
  ln=mod(v-1,num_lanes)+1;
  vp_i(v)=rectangle('Position',[vx_i(v) lane_y_i(ln)-VEH_H/2 VEH_LEN VEH_H], ...
    'FaceColor',C_GI,'EdgeColor',[1 1 1 0.3],'Curvature',[0.3 0.4]);
  vp_d(v)=rectangle('Position',[vx_d(v) lane_y_d(ln)-VEH_H/2 VEH_LEN VEH_H], ...
    'FaceColor',C_GD,'EdgeColor',[1 1 1 0.3],'Curvature',[0.3 0.4]);
end

%% --- Animation loop ---
fprintf('Animation running. Close figure to stop.\n');
sim_t=0;
while isvalid(fig)
  sim_t=sim_t+0.05;
  vx_i=vx_i+vs_i;
  wrap_i=vx_i>ROAD_LEN+VEH_LEN;
  if any(wrap_i)
    vx_i(wrap_i)=min(vx_i(~wrap_i))-spc_i*(1:sum(wrap_i))';
  end
  for v=1:N_VEH
    x=vx_d(v); d2o=OBS_X-x;
    if d2o>0 && d2o<spc_d*3
      spd=vs_d*(0.3+0.7*min(1,d2o/(spc_d*2)));
    elseif x>OBS_X+blk_px
      spd=vs_d*(0.3+0.7*min(1,(x-OBS_X-blk_px)/20));
    else
      spd=vs_d*0.3;
    end
    vx_d(v)=vx_d(v)+spd;
    if x>OBS_X && x<OBS_X+blk_px
      col=[0.95 0.55 0.10];
    elseif d2o>0 && d2o<spc_d*3
      a=min(1,1-d2o/(spc_d*3));
      col=C_GD*(1-a)+[0.95 0.55 0.10]*a;
    else
      col=C_GD;
    end
    ln=mod(v-1,num_lanes)+1;
    set(vp_i(v),'Position',[vx_i(v) lane_y_i(ln)-VEH_H/2 VEH_LEN VEH_H]);
    set(vp_d(v),'Position',[vx_d(v) lane_y_d(ln)-VEH_H/2 VEH_LEN VEH_H],'FaceColor',col);
  end
  wrap_d=vx_d>ROAD_LEN+VEH_LEN;
  if any(wrap_d)
    vx_d(wrap_d)=min(vx_d(~wrap_d))-spc_d*(1:sum(wrap_d))';
  end
  drawnow limitrate; pause(0.01);
end
fprintf('Done.\n');
end
`;
  }

  // ---- Canvas Road Animation ----
  let _twinAnim = null;

  function startTwinAnimation(data) {
    const canvas  = document.getElementById('twin-canvas');
    if (!canvas) return;
    const ctx     = canvas.getContext('2d');
    const W       = canvas.offsetWidth || 800;
    canvas.width  = W;
    const H       = 260;

    if (_twinAnim) cancelAnimationFrame(_twinAnim);

    const base    = data.original_capacity_pcu_hr || 1500;
    const reduced = data.reduced_capacity_pcu_hr  || 1200;
    const lossPct = data.capacity_loss_pct         || 0;
    const lanes   = (data.road_config || {}).num_lanes || 2;
    const totalW  = (data.road_config || {}).total_width_m || 7;
    const blocked = (data.capacity_calculation || {}).total_blocked_m || 0;
    const pen     = (data.capacity_calculation || {}).pothole_penalty || 1;
    const defects = Object.keys(data.per_defect || {});

    const FREE_SPD   = 50;
    const vcRatio    = reduced / base;
    const congSpd    = FREE_SPD * (1 - (1 - vcRatio) * 0.5);

    // Road layout
    const ROAD_H     = H / 2 - 10;
    const LANE_H     = ROAD_H / lanes;
    const ROAD_TOP_I = 8;
    const ROAD_TOP_D = H / 2 + 8;
    const OBS_X      = W * 0.58;
    const BLK_W      = Math.min((blocked / totalW) * W * 0.3, W * 0.25);
    const VW         = 28;
    const VH         = Math.max(8, LANE_H - 4);
    const N_VEH      = 8;

    const hiIdeal   = 3600 / Math.max(base, 1);
    const hiDefect  = 3600 / Math.max(reduced, 1);
    const spcI      = Math.max((FREE_SPD/3.6) * hiIdeal * 0.1,  VW + 8);
    const spcD      = Math.max((congSpd/3.6)  * hiDefect * 0.1, VW + 4);
    const vsI       = FREE_SPD  / 3.6 * 0.15;
    const vsD       = congSpd   / 3.6 * 0.15;

    // Vehicle positions
    let vxI = Array.from({length: N_VEH}, (_, i) => -spcI * (N_VEH - 1 - i));
    let vxD = Array.from({length: N_VEH}, (_, i) => -spcD * (N_VEH - 1 - i));

    const laneYI = (ln) => ROAD_TOP_I  + (ln + 0.5) * LANE_H;
    const laneYD = (ln) => ROAD_TOP_D  + (ln + 0.5) * LANE_H;

    const hasDefect = (name) => defects.includes(name);

    function drawRoad(yTop, color, dashed) {
      ctx.fillStyle = color;
      ctx.fillRect(0, yTop, W, ROAD_H);
      // Lane dividers
      ctx.setLineDash([14, 10]);
      ctx.strokeStyle = 'rgba(255,255,255,0.18)';
      ctx.lineWidth = 1.5;
      for (let ln = 1; ln < lanes; ln++) {
        ctx.beginPath();
        ctx.moveTo(0, yTop + ln * LANE_H);
        ctx.lineTo(W, yTop + ln * LANE_H);
        ctx.stroke();
      }
      ctx.setLineDash([]);
      // Edge lines
      ctx.strokeStyle = 'rgba(255,255,255,0.7)';
      ctx.lineWidth = 2;
      ctx.beginPath(); ctx.moveTo(0, yTop); ctx.lineTo(W, yTop); ctx.stroke();
      ctx.beginPath(); ctx.moveTo(0, yTop+ROAD_H); ctx.lineTo(W, yTop+ROAD_H); ctx.stroke();
    }

    function drawDefects(yTop) {
      // Blocked zone overlay
      ctx.fillStyle = 'rgba(220,50,50,0.18)';
      ctx.fillRect(OBS_X, yTop, BLK_W, ROAD_H);
      ctx.strokeStyle = 'rgba(220,50,50,0.6)';
      ctx.lineWidth = 1;
      ctx.strokeRect(OBS_X, yTop, BLK_W, ROAD_H);

      // Pothole
      if (hasDefect('pothole')) {
        ctx.beginPath();
        ctx.ellipse(OBS_X + BLK_W*0.3, yTop + LANE_H*0.5, 14, 8, 0, 0, Math.PI*2);
        ctx.fillStyle = '#3a1a1a';
        ctx.fill();
        ctx.strokeStyle = '#c04040';
        ctx.lineWidth = 1.5;
        ctx.stroke();
        ctx.fillStyle = '#fca5a5';
        ctx.font = '9px sans-serif';
        ctx.textAlign = 'center';
        ctx.fillText('Pothole', OBS_X + BLK_W*0.3, yTop + LANE_H*0.5 - 12);
      }
      // Vendor
      if (hasDefect('street_vendor')) {
        const vx = OBS_X + BLK_W * 0.62;
        const vy = yTop + LANE_H * (lanes > 1 ? 1.0 : 0.25);
        ctx.fillStyle = '#f59e0b';
        ctx.fillRect(vx - 12, vy - 10, 24, 16);
        ctx.fillStyle = '#fde68a';
        ctx.font = '8px sans-serif';
        ctx.textAlign = 'center';
        ctx.fillText('Vendor', vx, vy - 13);
      }
      // Illegal parking
      if (hasDefect('illegal_parking')) {
        const px = OBS_X + BLK_W * 0.5;
        const py = yTop + ROAD_H * 0.65;
        ctx.fillStyle = '#dc2626';
        ctx.beginPath();
        ctx.roundRect(px-16, py-7, 32, 14, 3);
        ctx.fill();
        ctx.fillStyle = '#fca5a5';
        ctx.font = '7px sans-serif';
        ctx.textAlign = 'center';
        ctx.fillText('Parking', px, py - 10);
      }
      // Barricade
      if (hasDefect('barricade')) {
        for (let bi = 0; bi < 3; bi++) {
          ctx.fillStyle = '#f97316';
          ctx.fillRect(OBS_X + bi*8 + 2, yTop + 2, 5, ROAD_H - 4);
        }
      }
      // Garbage
      if (hasDefect('garbage')) {
        ctx.fillStyle = '#65a30d';
        ctx.fillRect(OBS_X + BLK_W*0.7, yTop + ROAD_H*0.5, 14, 12);
        ctx.fillStyle = '#d9f99d';
        ctx.font = '7px sans-serif';
        ctx.textAlign = 'center';
        ctx.fillText('Garbage', OBS_X+BLK_W*0.77, yTop+ROAD_H*0.5-4);
      }

      // Blocked label
      ctx.fillStyle = '#fca5a5';
      ctx.font = 'bold 9px monospace';
      ctx.textAlign = 'center';
      ctx.fillText(blocked.toFixed(1)+'m blocked', OBS_X + BLK_W/2, yTop + ROAD_H + 7);
    }

    function drawVehicle(ctx, x, y, color) {
      ctx.fillStyle = color;
      ctx.beginPath();
      ctx.roundRect(x, y - VH/2, VW, VH, 3);
      ctx.fill();
      // Windshield
      ctx.fillStyle = 'rgba(150,210,255,0.5)';
      ctx.fillRect(x + VW*0.55, y - VH/2 + 2, VW*0.3, VH - 4);
    }

    function getDefectColor(x) {
      const d = OBS_X - x;
      if (x >= OBS_X && x <= OBS_X + BLK_W) return '#f97316';
      if (d > 0 && d < spcD * 3) {
        const a = Math.max(0, Math.min(1, 1 - d/(spcD*3)));
        return `rgba(${Math.round(227+28*a)},${Math.round(73-23*a)},${Math.round(72-62*a)},1)`;
      }
      return '#e34948';
    }

    function frame() {
      if (!canvas.isConnected) return;
      ctx.clearRect(0, 0, W, H);
      ctx.fillStyle = '#0f172a';
      ctx.fillRect(0, 0, W, H);

      // Roads
      drawRoad(ROAD_TOP_I, '#535a66', false);
      drawRoad(ROAD_TOP_D, '#4d5260', true);
      drawDefects(ROAD_TOP_D);

      // Ideal vehicles
      vxI = vxI.map((x, i) => {
        const nx = x + vsI;
        return nx > W + VW ? -spcI * (N_VEH - 1) + Math.min(...vxI.filter(v=>v<=W+VW)) : nx;
      });
      // wrap properly
      const maxWrapI = vxI.filter(x => x > W+VW).length;
      if (maxWrapI > 0) {
        const minX = Math.min(...vxI.filter(x => x <= W+VW));
        let wi = 0;
        vxI = vxI.map(x => x > W+VW ? minX - spcI*(++wi) : x);
      }

      vxI.forEach((x, i) => {
        const ln = i % lanes;
        drawVehicle(ctx, x, laneYI(ln), '#1baf7a');
      });

      // Defect vehicles — slow near obstacle
      vxD = vxD.map((x, i) => {
        const d = OBS_X - x;
        let spd;
        if (d > 0 && d < spcD*3)      spd = vsD * (0.25 + 0.75 * Math.min(1, d/(spcD*2)));
        else if (x >= OBS_X && x <= OBS_X+BLK_W) spd = vsD * 0.2;
        else if (x > OBS_X+BLK_W)     spd = vsD * (0.25 + 0.75 * Math.min(1, (x-OBS_X-BLK_W)/40));
        else                            spd = vsD;
        return x + spd;
      });
      const maxWrapD = vxD.filter(x => x > W+VW).length;
      if (maxWrapD > 0) {
        const minX = Math.min(...vxD.filter(x => x <= W+VW));
        let wd = 0;
        vxD = vxD.map(x => x > W+VW ? minX - spcD*(++wd) : x);
      }

      vxD.forEach((x, i) => {
        const ln = i % lanes;
        drawVehicle(ctx, x, laneYD(ln), getDefectColor(x));
      });

      // Speed labels
      ctx.fillStyle = '#1baf7a';
      ctx.font = 'bold 11px monospace';
      ctx.textAlign = 'left';
      ctx.fillText(`→ ${FREE_SPD} km/h`, 8, ROAD_TOP_I + ROAD_H/2 + 4);
      ctx.fillStyle = '#e34948';
      ctx.fillText(`→ ${congSpd.toFixed(1)} km/h`, 8, ROAD_TOP_D + ROAD_H/2 + 4);

      _twinAnim = requestAnimationFrame(frame);
    }

    // Set formula text
    const calc = data.capacity_calculation || {};
    const formulaEl = document.getElementById('twin-formula');
    if (formulaEl && calc.formula) formulaEl.textContent = 'Formula: ' + calc.formula;

    frame();
  }

  function attachMatlabButton(data) {
    const btn = document.getElementById('matlab-dl-btn');
    if (!btn) return;
    btn.addEventListener('click', () => {
      const script = generateMatlabScript(data);
      const blob   = new Blob([script], { type: 'text/plain' });
      const url    = URL.createObjectURL(blob);
      const a      = document.createElement('a');
      a.href       = url;
      a.download   = 'roadtwin.m';
      a.click();
      URL.revokeObjectURL(url);
    });
  }

  // ----------------------------------------------------------------
  // Render: single image
  // ----------------------------------------------------------------
  function renderImageResult(data) {
    resultsRoot.innerHTML =
      heroHTML(data) +
      defectAlertBannerHTML(data.per_defect) +
      matlabButtonHTML(data) +
      roadbarHTML(data.road_config || {}, data.per_defect || {}) +
      `<div class="section-title">Defects Detected - Capacity Loss &amp; Recommended Actions</div>` +
      defectGridHTML(data.per_defect);

    // Attach MATLAB download button click handler
    attachMatlabButton(data);

    // Start canvas animation after panel renders
    requestAnimationFrame(() => startTwinAnimation(data));
  }

  // ----------------------------------------------------------------
  // Render: batch
  // ----------------------------------------------------------------
  function renderBatchResult(data) {
    const perImage = (data.per_image || []).slice()
      .sort((a, b) => b.capacity_loss_pct - a.capacity_loss_pct);

    const rows = perImage.map((r, i) => `
      <tr>
        <td class="rank">${i + 1}</td>
        <td>${r.image}</td>
        <td>${fmt(r.capacity_loss_pct,1)}%</td>
        <td class="defects-list">${r.defects_found.length ? r.defects_found.map(titleCase).join(", ") : "-"}</td>
      </tr>`).join("");

    const errorsHTML = (data.errors && data.errors.length)
      ? `<div class="error-box" style="margin-top:18px;">${data.errors.length} image(s) failed: ${data.errors.map((e) => `${e.image} (${e.error})`).join("; ")}</div>`
      : "";

    resultsRoot.innerHTML = `
      <div class="card" style="margin-bottom:24px;">
        <div class="card-title">Batch Summary - ${data.num_succeeded}/${data.num_images} images analysed</div>
        <div class="batch-summary-row">
          <div class="batch-stat"><div class="l">Worst capacity loss</div><div class="v loss">${fmt(data.worst_capacity_loss_pct,1)}%</div></div>
          <div class="batch-stat"><div class="l">Average capacity loss</div><div class="v">${fmt(data.avg_capacity_loss_pct,1)}%</div></div>
          <div class="batch-stat"><div class="l">Worst image</div><div class="v" style="font-size:13px;font-family:monospace;">${data.worst_image_or_frame || "-"}</div></div>
        </div>
      </div>
      <div class="section-title">Images Ranked by Capacity Loss (Worst First)</div>
      <div class="card">
        <table class="stretch-table">
          <thead><tr><th>#</th><th>Image</th><th>Capacity Lost</th><th>Defects Found</th></tr></thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
      ${errorsHTML}`;
  }

  // ----------------------------------------------------------------
  // Render: video
  // ----------------------------------------------------------------
  function renderVideoResult(data) {
    const frames = data.frame_by_frame || [];
    const maxLoss = Math.max(1, ...frames.map((f) => f.capacity_loss_pct || 0));

    const barsHTML = frames.map((f) => {
      const h = Math.max(4, (f.capacity_loss_pct / maxLoss) * 86);
      return `<div class="tbar" style="height:${h}px;background:${lossToColor(f.capacity_loss_pct)}" title="t=${f.timestamp_sec}s · ${fmt(f.capacity_loss_pct,1)}% lost"></div>`;
    }).join("");

    const uniqueRows = (data.unique_defect_instances || [])
      .slice().sort((a, b) => b.times_seen - a.times_seen)
      .map((d) => `
        <div class="unique-defect-row">
          <span class="udr-name">${titleCase(d.cls_name)}</span>
          <span class="udr-meta">seen ${d.times_seen}× · ${fmt(d.first_seen_sec,1)}s–${fmt(d.last_seen_sec,1)}s · max ${fmt(d.max_blocked_m,2)} m blocked</span>
        </div>`).join("");

    resultsRoot.innerHTML = `
      <div class="card" style="margin-bottom:24px;">
        <div class="card-title">Video Summary - ${data.video}</div>
        <div class="batch-summary-row">
          <div class="batch-stat"><div class="l">Worst moment</div><div class="v loss">${fmt(data.worst_capacity_loss_pct,1)}%</div></div>
          <div class="batch-stat"><div class="l">Average capacity loss</div><div class="v">${fmt(data.avg_capacity_loss_pct,1)}%</div></div>
          <div class="batch-stat"><div class="l">Frames analysed</div><div class="v">${data.frames_analysed}</div></div>
          <div class="batch-stat"><div class="l">Unique defects tracked</div><div class="v">${data.unique_defect_count}</div></div>
        </div>
      </div>
      <div class="card timeline-card">
        <div class="card-title">Capacity Loss Over Time</div>
        <div class="card-sub">Each bar = one sampled frame. Height = capacity lost at that moment.</div>
        <div class="timeline-bar">${barsHTML}</div>
        <div class="timeline-meta"><span>0s</span><span>${frames.length ? frames[frames.length-1].timestamp_sec + "s" : "-"}</span></div>
      </div>
      <div class="section-title">Unique Defect Instances (Tracked - Not Double-Counted)</div>
      <div class="unique-defects-list">${uniqueRows || `<div class="empty-state">No obstructions detected.</div>`}</div>`;
  }

  function lossToColor(pct) {
    if (pct < 10) return "#22c55e";
    if (pct < 25) return "#f59e0b";
    if (pct < 50) return "#f97316";
    return "#ef4444";
  }

  // ================================================================
  // DIGITAL TWIN PANEL
  // ================================================================
  const DT = { pollTimer: null };

  function dtShowPanel() {
    const panel = document.getElementById("dt-panel");
    if (panel) {
      panel.style.display = "";
      panel.scrollIntoView({ behavior: "smooth", block: "start" });
    }
    dtSetBadge("running", "Simulink running…");
  }

  function dtStartPolling() {
    if (DT.pollTimer) clearInterval(DT.pollTimer);
    DT.pollTimer = setInterval(dtPoll, 2500);
    dtPoll();
  }

  async function dtPoll() {
    try {
      const res  = await fetch("/api/digital-twin/status");
      if (!res.ok) return;
      const data = await res.json();
      if (data.status === "done" && data.twin_data) {
        clearInterval(DT.pollTimer);
        dtSetBadge("done", "Simulation complete");
        dtRender(data.twin_data);
      } else if (data.status === "error") {
        clearInterval(DT.pollTimer);
        dtSetBadge("error", "Simulation error");
      } else {
        dtSetBadge("running", "Simulink running…");
      }
    } catch (e) { /* silent */ }
  }

  function dtRender(twin) {
    const s = twin.summary || {};
    setText("dt-ideal-cap",    Math.round(s.ideal_capacity_pcu_hr  || 0));
    setText("dt-defect-cap",   Math.round(s.defect_capacity_pcu_hr || 0));
    setText("dt-ideal-vol",    Math.round(s.ideal_volume_design_pcu  || 0));
    setText("dt-defect-vol",   Math.round(s.defect_volume_design_pcu || 0));
    setText("dt-defect-speed", (s.steady_state_speed_kmh || 0).toFixed(1));
    setText("dt-loss-pct",     (s.capacity_loss_pct || 0).toFixed(1) + "%");

    if ((s.pothole_speed_impact_pct || 0) > 0) {
      document.getElementById("dt-speed-section").style.display = "";
      setText("dt-speed-reduction", (s.speed_reduction_pct || 0).toFixed(1));
      setText("dt-congested-speed", (s.steady_state_speed_kmh || 0).toFixed(1));
    }

    dtDrawCapChart(twin);
    dtDrawSpdChart(twin);
    dtAnimateRoads(s);
    const phEl = document.getElementById("dt-pothole-marker");
    if (phEl && (s.pothole_speed_impact_pct || 0) > 0) phEl.style.display = "";
  }

  function dtDrawCapChart(twin) {
    const canvas = document.getElementById("dt-cap-chart");
    if (!canvas) return;
    dtDrawLineChart(canvas.getContext("2d"), canvas,
      twin.simulation_time_s || [],
      [
        { data: twin.ideal_capacity_pcu_hr  || [], color: "#22c55e", label: "Ideal" },
        { data: twin.defect_capacity_pcu_hr || [], color: "#ef4444", label: "Defect" },
      ]);
  }

  function dtDrawSpdChart(twin) {
    const canvas = document.getElementById("dt-spd-chart");
    if (!canvas) return;
    dtDrawLineChart(canvas.getContext("2d"), canvas,
      twin.simulation_time_s || [],
      [{ data: twin.vehicle_speed_kmh || [], color: "#f97316", label: "Speed" }]);
  }

  function dtDrawLineChart(ctx, canvas, xData, series) {
    const W = canvas.width, H = canvas.height;
    const PAD = { top: 12, right: 12, bottom: 24, left: 48 };
    const plotW = W - PAD.left - PAD.right;
    const plotH = H - PAD.top - PAD.bottom;

    ctx.fillStyle = "#1e293b";
    ctx.fillRect(0, 0, W, H);

    let yMin = Infinity, yMax = -Infinity;
    series.forEach((s) => s.data.forEach((v) => { yMin = Math.min(yMin,v); yMax = Math.max(yMax,v); }));
    if (!isFinite(yMin)) { yMin = 0; yMax = 100; }
    const yPad = (yMax - yMin) * 0.1 || 10;
    yMin -= yPad; yMax += yPad;

    const xMax   = xData[xData.length - 1] || 60;
    const xScale = (v) => PAD.left + (v / xMax) * plotW;
    const yScale = (v) => PAD.top + plotH - ((v - yMin) / (yMax - yMin)) * plotH;

    ctx.strokeStyle = "#334155"; ctx.lineWidth = 0.5;
    for (let i = 0; i <= 4; i++) {
      const y   = PAD.top + (plotH / 4) * i;
      const val = yMax - ((yMax - yMin) / 4) * i;
      ctx.beginPath(); ctx.moveTo(PAD.left, y); ctx.lineTo(PAD.left + plotW, y); ctx.stroke();
      ctx.fillStyle = "#64748b"; ctx.font = "10px JetBrains Mono, monospace";
      ctx.textAlign = "right";
      ctx.fillText(Math.round(val), PAD.left - 4, y + 4);
    }
    ctx.strokeStyle = "#475569"; ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(PAD.left, PAD.top); ctx.lineTo(PAD.left, PAD.top + plotH);
    ctx.lineTo(PAD.left + plotW, PAD.top + plotH);
    ctx.stroke();
    ctx.fillStyle = "#64748b"; ctx.font = "10px JetBrains Mono, monospace"; ctx.textAlign = "center";
    [0,15,30,45,60].forEach((sec) => ctx.fillText(sec + "s", xScale(sec), PAD.top + plotH + 16));

    series.forEach(({ data, color }) => {
      if (!data.length) return;
      ctx.strokeStyle = color; ctx.lineWidth = 2;
      ctx.beginPath();
      data.forEach((v, i) => {
        const x = xScale(xData[i] || 0), y = yScale(v);
        i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
      });
      ctx.stroke();
      ctx.fillStyle = color + "22";
      ctx.beginPath();
      data.forEach((v, i) => {
        const x = xScale(xData[i] || 0), y = yScale(v);
        i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
      });
      ctx.lineTo(xScale(xData[xData.length-1] || 0), yScale(yMin));
      ctx.lineTo(xScale(xData[0] || 0), yScale(yMin));
      ctx.closePath(); ctx.fill();
    });
  }

  function dtAnimateRoads(summary) {
    const idealCount  = Math.max(1, Math.round((summary.ideal_volume_design_pcu  || 1000) / 300));
    const defectCount = Math.max(1, Math.round((summary.defect_volume_design_pcu || 700)  / 300));
    spawnVehicles("dt-ideal-vehicles",  idealCount,  50,                           "#22c55e");
    spawnVehicles("dt-defect-vehicles", defectCount, summary.steady_state_speed_kmh || 35, "#ef4444");
  }

  function spawnVehicles(containerId, count, speedKmh, accentColor) {
    const container = document.getElementById(containerId);
    if (!container) return;
    container.innerHTML = "";
    const types   = ["car","two-w","truck","car","car","two-w"];
    const durBase = Math.max(1.5, 50 / Math.max(speedKmh, 5) * 3);
    for (let i = 0; i < Math.min(count, 6); i++) {
      const el  = document.createElement("div");
      const type = types[i % types.length];
      const dur  = durBase + Math.random() * 1.5;
      const top  = 20 + (i % 2) * 28;
      el.className = `dt-vehicle ${type}`;
      el.style.cssText = `animation-duration:${dur}s;animation-delay:${-(Math.random()*dur)}s;top:${top}px;background:${type==="truck"?"#f59e0b":type==="two-w"?"#a855f7":accentColor};`;
      container.appendChild(el);
    }
  }

  function setText(id, val) {
    const el = document.getElementById(id);
    if (el) el.textContent = val;
  }
  function dtSetBadge(cls, text) {
    const el = document.getElementById("dt-status-badge");
    if (!el) return;
    el.className = `dt-status-badge ${cls}`;
    el.textContent = text;
  }

  // ----------------------------------------------------------------
  // Init
  // ----------------------------------------------------------------
  loadConfigOptions();
})();
