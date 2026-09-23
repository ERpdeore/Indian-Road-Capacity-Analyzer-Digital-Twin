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
  const analysisDateEl = document.getElementById("analysis_date");

  // Default the date field to today (local time, not UTC) on load. It's
  // a normal <input type="date"> inside #config-form, so FormData(configForm)
  // already picks it up for every mode (image/batch/video) with no extra
  // wiring below — same field, same name, sent through to every endpoint.
  if (analysisDateEl && !analysisDateEl.value) {
    const now = new Date();
    const local = new Date(now.getTime() - now.getTimezoneOffset() * 60000);
    analysisDateEl.value = local.toISOString().slice(0, 10);
  }

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
      hint:     "MP4 / MOV / AVI · Frames are sampled at the interval shown below",
      runLabel: "Analyse Video",
      accept:   "video/*,video/mp4,video/quicktime,video/avi,video/x-msvideo",
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

  // ---------------------------------------------------------------
  // Camera capture -- opens the device camera, lets you snap a photo,
  // and feeds it through the exact same handleFiles() pipeline as a
  // normal drag-and-drop upload. Requires https:// (or localhost) --
  // browsers block camera access on plain http:// otherwise.
  // ---------------------------------------------------------------
  const cameraBtn        = document.getElementById("camera-btn");
  const cameraModal      = document.getElementById("camera-modal");
  const cameraVideo      = document.getElementById("camera-video");
  const cameraCanvas     = document.getElementById("camera-canvas");
  const cameraCaptureBtn = document.getElementById("camera-capture-btn");
  const cameraCancelBtn  = document.getElementById("camera-cancel-btn");
  let cameraStream = null;

  async function openCamera() {
    try {
      cameraStream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: "environment" },
        audio: false,
      });
      cameraVideo.srcObject = cameraStream;
      cameraModal.style.display = "flex";
    } catch (err) {
      alert("Could not access camera: " + err.message +
            "\nCheck your browser's camera permission for this site.");
    }
  }

  function closeCamera() {
    if (cameraStream) {
      cameraStream.getTracks().forEach((t) => t.stop());
      cameraStream = null;
    }
    cameraModal.style.display = "none";
  }

  function captureFromCamera() {
    const w = cameraVideo.videoWidth;
    const h = cameraVideo.videoHeight;
    cameraCanvas.width = w;
    cameraCanvas.height = h;
    cameraCanvas.getContext("2d").drawImage(cameraVideo, 0, 0, w, h);

    cameraCanvas.toBlob((blob) => {
      const filename = `camera_${Date.now()}.jpg`;
      const file = new File([blob], filename, { type: "image/jpeg" });

      const dt = new DataTransfer();
      dt.items.add(file);
      fileInput.files = dt.files;
      handleFiles(dt.files);

      closeCamera();
    }, "image/jpeg", 0.92);
  }

  cameraBtn.addEventListener("click", openCamera);
  cameraCaptureBtn.addEventListener("click", captureFromCamera);
  cameraCancelBtn.addEventListener("click", closeCamera);

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
        dsv_values: { arterial:2400, sub_arterial:1900, collector:1400 },
        free_flow_speeds: { arterial:50, sub_arterial:40, collector:30 } },
      { key: "2lane_twoway",    label: "2-Lane Two-Way",
        available_fringes: ["arterial","sub_arterial","collector"],
        dsv_values: { arterial:1500, sub_arterial:1200, collector:900 },
        free_flow_speeds: { arterial:50, sub_arterial:40, collector:30 } },
      { key: "3lane_oneway",    label: "3-Lane One-Way",
        available_fringes: ["arterial","sub_arterial","collector"],
        dsv_values: { arterial:3600, sub_arterial:2900, collector:2200 },
        free_flow_speeds: { arterial:65, sub_arterial:50, collector:40 } },
      { key: "4lane_undivided", label: "4-Lane Undivided",
        available_fringes: ["arterial","sub_arterial","collector"],
        dsv_values: { arterial:3000, sub_arterial:2400, collector:1800 },
        free_flow_speeds: { arterial:65, sub_arterial:50, collector:40 } },
      { key: "4lane_divided",   label: "4-Lane Divided",
        available_fringes: ["arterial","sub_arterial"],
        dsv_values: { arterial:3600, sub_arterial:2900 },
        free_flow_speeds: { arterial:80, sub_arterial:65, collector:50 } },
      { key: "6lane_undivided", label: "6-Lane Undivided",
        available_fringes: ["arterial","sub_arterial"],
        dsv_values: { arterial:4800, sub_arterial:3800 },
        free_flow_speeds: { arterial:80, sub_arterial:65, collector:50 } },
      { key: "6lane_divided",   label: "6-Lane Divided",
        available_fringes: ["arterial","sub_arterial"],
        dsv_values: { arterial:5400, sub_arterial:4300 },
        free_flow_speeds: { arterial:100, sub_arterial:80, collector:65 } },
      { key: "8lane_divided",   label: "8-Lane Divided",
        available_fringes: ["arterial"],
        dsv_values: { arterial:7200 },
        free_flow_speeds: { arterial:120, sub_arterial:100, collector:80 } },
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

  // Has the user actually touched the carriageway/fringe/regime controls?
  // Once true, a later config refresh (e.g. the real backend response
  // arriving after the hardcoded fallback) must NOT overwrite their choice.
  let userTouchedConfig = false;

  // Rebuild the fringe <select> so it only contains options that are valid
  // for the currently chosen carriageway. Rebuilding (rather than leaving
  // every option in the DOM and toggling `.disabled`) avoids the browser-
  // dependent quirks around disabled-but-selected <option> elements that
  // were causing the carriageway/frontage selection to misbehave.
  function rebuildFringeOptions(data, carriagewayKey, preferredFringe) {
    if (!fringeSel) return;
    const opt = (data.carriageway_options || []).find((o) => o.key === carriagewayKey);
    const allowed = opt ? (opt.available_fringes || []) : Object.keys(
      Object.fromEntries((data.fringe_conditions || []).map((f) => [f.key, true]))
    );
    const fringeList = (data.fringe_conditions || []).filter((f) => allowed.includes(f.key));

    fringeSel.innerHTML = fringeList
      .map((f) => `<option value="${f.key}">${titleCase(f.key)}</option>`)
      .join("");

    // Keep the user's previous fringe choice if it's still valid for the
    // newly selected carriageway type; otherwise fall back to the first
    // allowed option.
    if (preferredFringe && allowed.includes(preferredFringe)) {
      fringeSel.value = preferredFringe;
    } else if (fringeList.length) {
      fringeSel.value = fringeList[0].key;
    }

    if (fringeDescEl) {
      const fc = fringeList.find((f) => f.key === fringeSel.value);
      fringeDescEl.textContent = fc ? fc.description : "";
    }
  }

  function populateDropdowns(data) {
    // Remember what the user had selected before this (re)populate, so a
    // background config refresh never silently discards their in-progress
    // selection — this was the root cause of the recurring carriageway /
    // frontage-condition selection bug.
    const prevCarriageway = carriagewaySel ? carriagewaySel.value : null;
    const prevFringe      = fringeSel ? fringeSel.value : null;
    const prevRegime      = regimeSel ? regimeSel.value : null;

    configData = data;

    if (userTouchedConfig) {
      // The user already interacted with the form (most likely: the
      // fallback config loaded first, they picked options, and now the
      // real /api/config-options response has arrived). Only refresh the
      // underlying data model — do NOT touch the DOM selections.
      return;
    }

    // --- Carriageway dropdown ---
    if (carriagewaySel) {
      carriagewaySel.innerHTML = (data.carriageway_options || [])
        .map((o) => `<option value="${o.key}">${o.label}</option>`)
        .join("");
      const cwOptions = (data.carriageway_options || []).map((o) => o.key);
      carriagewaySel.value = (prevCarriageway && cwOptions.includes(prevCarriageway))
        ? prevCarriageway
        : (cwOptions[0] || "");
    }

    // --- Fringe dropdown (scoped to the selected carriageway) ---
    rebuildFringeOptions(data, carriagewaySel ? carriagewaySel.value : null, prevFringe);

    // --- Traffic regime dropdown ---
    if (regimeSel) {
      regimeSel.innerHTML = (data.traffic_regimes || [])
        .map((r) => `<option value="${r.key}">${
          r.key === "low"
            ? "Low — <15% heavy vehicles (cars, autos, two-wheelers)"
            : "High — ≥15% heavy vehicles (trucks, buses)"
        }</option>`)
        .join("");
      const regimeOptions = (data.traffic_regimes || []).map((r) => r.key);
      regimeSel.value = (prevRegime && regimeOptions.includes(prevRegime))
        ? prevRegime
        : (regimeOptions[0] || "");
    }

    // Wire up carriageway change — rebuild fringe options for the new type
    if (carriagewaySel) {
      carriagewaySel.onchange = () => {
        userTouchedConfig = true;
        rebuildFringeOptions(configData, carriagewaySel.value, fringeSel ? fringeSel.value : null);
        updateDsvPreview();
      };
    }

    // Wire up fringe change
    if (fringeSel) {
      fringeSel.onchange = () => {
        userTouchedConfig = true;
        if (fringeDescEl) {
          const fc = (configData.fringe_conditions || []).find((f) => f.key === fringeSel.value);
          fringeDescEl.textContent = fc ? fc.description : "";
        }
        updateDsvPreview();
      };
    }

    // Wire up regime change
    if (regimeSel) {
      regimeSel.onchange = () => {
        userTouchedConfig = true;
        if (regimeDescEl) {
          const r = (configData.traffic_regimes || []).find((x) => x.key === regimeSel.value);
          regimeDescEl.textContent = r ? r.description : "";
        }
        updateDsvPreview();
      };
      regimeSel.onchange();
    }

    // Initial DSV preview for the defaults chosen above
    updateDsvPreview();

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

  function getFreeFlowSpeed() {
    if (!configData) return 50;
    const key    = carriagewaySel ? carriagewaySel.value : "";
    const fringe = fringeSel ? fringeSel.value : "arterial";
    const opt    = (configData.carriageway_options || []).find((o) => o.key === key);
    if (opt && opt.free_flow_speeds && opt.free_flow_speeds[fringe] !== undefined) {
      return opt.free_flow_speeds[fringe];
    }
    return 50; // fallback
  }

  function updateDsvPreview() {
    if (!configData) return;
    const key    = carriagewaySel ? carriagewaySel.value : "";
    const fringe = fringeSel ? fringeSel.value : "arterial";
    const regime = regimeSel ? regimeSel.value : "low";
    const opt    = (configData.carriageway_options || []).find((o) => o.key === key);
    if (opt && opt.dsv_values && opt.dsv_values[fringe] !== undefined) {
      const dsv      = opt.dsv_values[fringe];
      const avgPcu   = AVG_PCU[regime] || 1.00;
      const vehPerHr = Math.round(dsv / avgPcu);
      const freeSpd  = getFreeFlowSpeed();
      dsvValueEl.textContent = dsv.toLocaleString("en-IN");
      const noteEl = document.getElementById("dsv-note");
      if (noteEl) {
        noteEl.textContent =
          `≈ ${vehPerHr.toLocaleString("en-IN")} vehicles/hr · Free-flow speed: ${freeSpd} km/h (IRC design speed)`;
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

  // "2026-09-23" -> "23 Sep 2026". Falls back to the raw string (or "—")
  // if it isn't a plain YYYY-MM-DD value, rather than showing "Invalid Date".
  function formatDateDisplay(isoDate) {
    if (!isoDate) return "—";
    const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(isoDate);
    if (!m) return isoDate;
    const d = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
    if (isNaN(d.getTime())) return isoDate;
    return d.toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" });
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
      ["Date",           formatDateDisplay(cfg.analysis_date)],
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
          <div class="eyebrow">Analysed ${cfg.analysis_date ? `· ${formatDateDisplay(cfg.analysis_date)} ` : ""}· <span class="image-name">${data.image || "untitled"}</span></div>
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
      const rec = d.rectification;
      const rectHTML = rec ? `
        <div class="defect-action" style="border-top:1px solid #333;margin-top:8px;padding-top:8px;">
          <strong>${rec.rectification_category}</strong> — ${rec.priority}
          <div style="font-size:0.85em;opacity:0.85;margin-top:4px;">${rec.method}</div>
          <div style="font-size:0.8em;opacity:0.7;">${rec.materials}</div>
          <div style="font-size:0.8em;opacity:0.7;">${rec.work_zone_note}</div>
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
          ${rectHTML}
          <div class="defect-action">${d.action || "No specific action mapped - flag for manual inspection."}</div>
          <div class="defect-code">${d.code_ref || ""}</div>
        </div>`;
    }).join("")}</div>`;
  }

  function xodrButtonHTML(data) {
    if (!data.roadrunner_xodr_available || !data.job_id) return "";
    return `
      <div class="action-bar">
        <div class="action-bar-info">
          <span class="action-bar-icon">🛣️</span>
          <div>
            <div class="action-bar-title">Digital Twin Bundle (.zip)</div>
            <div class="action-bar-sub">Everything for the 3D RoadRunner simulation in one download: the ideal
            road, the non-ideal (defect) road, the capacity numbers, and the MATLAB scripts + one-click launchers.
            Extract this straight into your Downloads folder, then double-click
            <code>run_ideal_digital_twin.bat</code> and <code>run_nonideal_digital_twin.bat</code> to see each
            simulation — open both to compare side by side.</div>
          </div>
        </div>
        <a class="action-dl-btn" href="/api/jobs/${encodeURIComponent(data.job_id)}/bundle.zip"
           download>
          ↓ Download Everything (.zip)
        </a>
      </div>`;
  }


  // Results from every image analysed THIS BROWSER SESSION — used only
  // to build the multi-photo corridor export below. Not sent anywhere
  // until the user explicitly clicks the corridor download button.
  const _sessionAnalyses = [];

  function corridorButtonHTML() {
    if (_sessionAnalyses.length < 2) return "";
    return `
      <div class="action-bar">
        <div class="action-bar-info">
          <span class="action-bar-icon">🛣️</span>
          <div>
            <div class="action-bar-title">Full Corridor (.xodr) — ${_sessionAnalyses.length} photos</div>
            <div class="action-bar-sub">Combines every photo you've analysed this session into one continuous
            RoadRunner road, ordered by the chainage you entered for each. Segments with no chainage entered
            fall back to a fixed spacing, in upload order.</div>
          </div>
        </div>
        <button class="action-dl-btn" id="corridor-dl-btn">
          ↓ Download Corridor (${_sessionAnalyses.length})
        </button>
      </div>
      <div class="action-bar">
        <div class="action-bar-info">
          <span class="action-bar-icon">✨</span>
          <div>
            <div class="action-bar-title">Ideal Corridor (.xodr)</div>
            <div class="action-bar-sub">Same combined road, same lengths and lanes, with every detected defect
            removed -- the "what it could look like" comparison version.</div>
          </div>
        </div>
        <button class="action-dl-btn" id="corridor-ideal-dl-btn">
          ↓ Download Ideal Corridor
        </button>
      </div>
      <div class="action-bar">
        <div class="action-bar-info">
          <span class="action-bar-icon">📊</span>
          <div>
            <div class="action-bar-title">Corridor Capacity Summary (.json)</div>
            <div class="action-bar-sub">Combines every photo's capacity numbers into one real ideal-vs-reduced
            figure for the whole stretch (weakest-segment rule) -- used to size traffic in the RoadRunner demo.</div>
          </div>
        </div>
        <button class="action-dl-btn" id="corridor-capacity-dl-btn">
          ↓ Download Capacity Summary
        </button>
      </div>`;
  }

  function _downloadCorridorVariant(endpoint, filename, btnId, busyLabel, idleLabel) {
    const btn = document.getElementById(btnId);
    if (!btn) return;
    btn.addEventListener('click', async () => {
      btn.disabled = true;
      btn.textContent = busyLabel;
      try {
        const res = await fetch(endpoint, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ results: _sessionAnalyses }),
        });
        if (!res.ok) {
          const err = await res.json().catch(() => ({}));
          throw new Error(err.detail || `Server returned ${res.status}`);
        }
        const blob = await res.blob();
        const url  = URL.createObjectURL(blob);
        const a    = document.createElement('a');
        a.href     = url;
        a.download = filename;
        a.click();
        URL.revokeObjectURL(url);
      } catch (e) {
        alert(`Could not build export: ${e.message}`);
      } finally {
        btn.disabled = false;
        btn.textContent = idleLabel;
      }
    });
  }

  function attachCorridorButton() {
    const btn = document.getElementById('corridor-dl-btn');
    if (!btn) return;
    btn.addEventListener('click', async () => {
      btn.disabled = true;
      btn.textContent = 'Building…';
      try {
        const res = await fetch('/api/export/roadrunner-corridor.xodr', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ results: _sessionAnalyses }),
        });
        if (!res.ok) {
          const err = await res.json().catch(() => ({}));
          throw new Error(err.detail || `Server returned ${res.status}`);
        }
        const blob = await res.blob();
        const url  = URL.createObjectURL(blob);
        const a    = document.createElement('a');
        a.href     = url;
        a.download = 'roadrunner_corridor.xodr';
        a.click();
        URL.revokeObjectURL(url);
      } catch (e) {
        alert(`Could not build corridor export: ${e.message}`);
      } finally {
        btn.disabled = false;
        btn.textContent = `↓ Download Corridor (${_sessionAnalyses.length})`;
      }
    });

    _downloadCorridorVariant(
      '/api/export/roadrunner-corridor-ideal.xodr',
      'roadrunner_corridor_ideal.xodr',
      'corridor-ideal-dl-btn',
      'Building…',
      '↓ Download Ideal Corridor'
    );

    _downloadCorridorVariant(
      '/api/export/roadrunner-corridor-capacity.json',
      'roadrunner_corridor_capacity.json',
      'corridor-capacity-dl-btn',
      'Building…',
      '↓ Download Capacity Summary'
    );
  }

  function departmentReportButtonHTML(data) {
    if (!data.department_report_available || !data.job_id) return "";
    return `
      <div class="action-bar">
        <div class="action-bar-info">
          <span class="action-bar-icon">📄</span>
          <div>
            <div class="action-bar-title">Department Action Report</div>
            <div class="action-bar-sub">Defects grouped by the civic department responsible for each —
            PWD, Traffic Police, or Municipal Corporation — with IRC code references, ready to send as-is.</div>
          </div>
        </div>
        <a class="action-dl-btn" href="/api/jobs/${encodeURIComponent(data.job_id)}/department-report.pdf"
           download>
          ↓ Download PDF Report
        </a>
      </div>`;
  }

  // ----------------------------------------------------------------
  // Render: single image
  // ----------------------------------------------------------------
  function renderImageResult(data) {
    resultsRoot.innerHTML =
      heroHTML(data) +
      defectAlertBannerHTML(data.per_defect) +
      xodrButtonHTML(data) +
      departmentReportButtonHTML(data) +
      corridorButtonHTML() +
      roadbarHTML(data.road_config || {}, data.per_defect || {}) +
      `<div class="section-title">Defects Detected - Capacity Loss &amp; Recommended Actions</div>` +
      defectGridHTML(data.per_defect);

    // Track this analysis for the "combine into one corridor" export —
    // session-only (in browser memory), not persisted server-side.
    _sessionAnalyses.push(data);
    attachCorridorButton();
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
        <div class="card-sub">Date of analysis: ${formatDateDisplay((data.road_config || {}).analysis_date)}</div>
        <div class="batch-summary-row">
          <div class="batch-stat"><div class="l">Worst capacity loss</div><div class="v loss">${fmt(data.worst_capacity_loss_pct,1)}%</div></div>
          <div class="batch-stat"><div class="l">Average capacity loss</div><div class="v">${fmt(data.avg_capacity_loss_pct,1)}%</div></div>
          <div class="batch-stat"><div class="l">Worst image</div><div class="v" style="font-size:13px;font-family:monospace;">${data.worst_image_or_frame || "-"}</div></div>
        </div>
      </div>
      ${departmentReportButtonHTML(data)}
      <div class="section-title">Images Ranked by Capacity Loss (Worst First)</div>
      <div class="card">
        <table class="stretch-table">
          <thead><tr><th>#</th><th>Image</th><th>Capacity Lost</th><th>Defects Found</th></tr></thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
      ${errorsHTML}`;

    // The department report / digital twin are both built from the worst
    // photo in the batch (see app.py's _run_batch_job) — trigger the same
    // twin panel + polling the single-image flow uses.
    if (data.job_id) {
      dtShowPanel();
      dtStartPolling();
    }
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
        <div class="card-sub">Date of analysis: ${formatDateDisplay((data.road_config || {}).analysis_date)}</div>
        <div class="batch-summary-row">
          <div class="batch-stat"><div class="l">Worst moment</div><div class="v loss">${fmt(data.worst_capacity_loss_pct,1)}%</div></div>
          <div class="batch-stat"><div class="l">Average capacity loss</div><div class="v">${fmt(data.avg_capacity_loss_pct,1)}%</div></div>
          <div class="batch-stat"><div class="l">Frames analysed</div><div class="v">${data.frames_analysed}</div></div>
          <div class="batch-stat"><div class="l">Unique defects tracked</div><div class="v">${data.unique_defect_count}</div></div>
        </div>
      </div>
      ${departmentReportButtonHTML(data)}
      <div class="card timeline-card">
        <div class="card-title">Capacity Loss Over Time</div>
        <div class="card-sub">Each bar = one sampled frame. Height = capacity lost at that moment.</div>
        <div class="timeline-bar">${barsHTML}</div>
        <div class="timeline-meta"><span>0s</span><span>${frames.length ? frames[frames.length-1].timestamp_sec + "s" : "-"}</span></div>
      </div>
      <div class="section-title">Unique Defect Instances (Tracked - Not Double-Counted)</div>
      <div class="unique-defects-list">${uniqueRows || `<div class="empty-state">No obstructions detected.</div>`}</div>`;

    // Same reasoning as renderBatchResult above — twin data was generated
    // from the worst sampled frame in _run_video_job.
    if (data.job_id) {
      dtShowPanel();
      dtStartPolling();
    }
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
    dtSetBadge("running", "Calculating…");
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
        dtSetBadge("running", "Calculating…");
      }
    } catch (e) { /* silent */ }
  }

  function dtRender(twin) {
    const s = twin.summary || {};
    DT.lastSummary = s;  // stash for the RoadRunner script generator (vehicle count)
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
