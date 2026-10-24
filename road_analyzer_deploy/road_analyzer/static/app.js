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

  const roadTypeSel   = document.getElementById("road_type");
  const roadTypeHint  = document.getElementById("road-type-hint");
  const classSel      = document.getElementById("functional_class");
  const speedInput    = document.getElementById("operating_speed_kmh");
  const widthInput    = document.getElementById("total_width_m");
  const widthHint     = document.getElementById("width-hint");
  const dsvPreview    = document.getElementById("dsv-preview");
  const dsvValueEl    = document.getElementById("dsv-value");
  const FACTOR_FIELDS = ["on_street_parking", "bus_stop", "access_points"];

  const configForm    = document.getElementById("config-form");
  const runBtn        = document.getElementById("run-btn");
  const runBtnLabel   = document.getElementById("run-btn-label");
  const modelStatusEl = document.getElementById("model-status");
  const analysisDateEl   = document.getElementById("analysis_date");
  const collectionDateEl = document.getElementById("data_collection_date"); // NEW

  // Local-time "today" as YYYY-MM-DD (avoids UTC off-by-one near midnight)
  function todayLocalISO() {
    const now = new Date();
    const local = new Date(now.getTime() - now.getTimezoneOffset() * 60000);
    return local.toISOString().slice(0, 10);
  }
  function addDaysISO(iso, days) {
    const d = new Date(iso + "T00:00:00");
    d.setDate(d.getDate() + days);
    return d.toISOString().slice(0, 10);
  }

  const TODAY_ISO = todayLocalISO();

  // Data collection date: today or earlier allowed — only future dates
  // are blocked in the date picker itself via max = today. Defaults to
  // today too, same as analysis date below, so the user only has to
  // change it if the photo/video was actually taken on an earlier day.
  if (collectionDateEl) {
    if (!collectionDateEl.value) collectionDateEl.value = TODAY_ISO;
    collectionDateEl.max = TODAY_ISO;
  }

  // Visible, on-page proof of what "today" resolved to -- so this can be
  // checked just by looking at the page, no dev tools required.
  const collectionHintEl = document.getElementById("collection-date-hint");
  if (collectionHintEl) {
    const todayDisplay = formatDateDisplay(TODAY_ISO);
    collectionHintEl.textContent =
      `Date the photo/video was actually taken on site — today (${todayDisplay}) or earlier`;
  }

  // Analysis date: a normal <input type="date"> inside #config-form, so
  // FormData(configForm) already picks it up for every mode (image/batch/
  // video) with no extra wiring below — same field, same name, sent
  // through to every endpoint. Defaults to today, can't be in the future.
  if (analysisDateEl) {
    if (!analysisDateEl.value) analysisDateEl.value = TODAY_ISO;
    analysisDateEl.max = TODAY_ISO;
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
  // Offline fallback (Render free tier can take ~60 s to wake). Must match
  // road_analyzer/indo_hcm.py — the server copy replaces it when it loads.
  // ----------------------------------------------------------------
  const FALLBACK_CONFIG = {
    road_types: [   // Indo-HCM Table 5.4
      { key: "undivided_2lane", label: "Two-lane undivided (both directions)", lanes: 2, divided: false, basis: "both directions", ref_width_m: 7.5,  base_capacity_pcu_h: 2400 },
      { key: "divided_4lane",   label: "Four-lane divided — one direction (2 lanes)",  lanes: 2, divided: true, basis: "one direction", ref_width_m: 7.5,  base_capacity_pcu_h: 2700 },
      { key: "divided_6lane",   label: "Six-lane divided — one direction (3 lanes)",   lanes: 3, divided: true, basis: "one direction", ref_width_m: 11.0, base_capacity_pcu_h: 4200 },
      { key: "divided_8lane",   label: "Eight-lane divided — one direction (4 lanes)", lanes: 4, divided: true, basis: "one direction", ref_width_m: 14.5, base_capacity_pcu_h: 6800,
        note: "Table 5.4 value applies where signal spacing is 1-3 km (Section 5.4.4.2)." },
      { key: "divided_10lane",  label: "Ten-lane divided — one direction (5 lanes)",   lanes: 5, divided: true, basis: "one direction", ref_width_m: 18.0, base_capacity_pcu_h: 10000,
        note: "Table 5.4 value applies where signal spacing is 1-3 km (Section 5.4.4.2)." },
    ],
    functional_classes: [
      { key: "arterial",     label: "Arterial",     operating_speed_kmh: 50 },
      { key: "sub_arterial", label: "Sub-arterial", operating_speed_kmh: 40 },
      { key: "collector",    label: "Collector",    operating_speed_kmh: 30 },
    ],
    speed_model: { a: 20.11, b: 210.8, range_kmh: [40, 80] },
    on_street_parking: [   // Tables 5.9 / 5.10
      { key: "none", label: "No on-street parking", factor: 1.0 },
      { key: "len_lt25", label: "Long-term, < 25% of segment length (T5.9)", factor: 0.70 },
      { key: "len_25_50", label: "Long-term, 25 – 50% of length (T5.9)", factor: 0.65 },
      { key: "len_gt50", label: "Long-term, > 50% of length (T5.9)", factor: 0.40 },
      { key: "man_le500", label: "Short-term, ≤ 500 manoeuvres/km/h (T5.10)", factor: 0.65 },
      { key: "man_gt500", label: "Short-term, > 500 manoeuvres/km/h (T5.10)", factor: 0.40 },
    ],
    bus_stop: [
      { key: "none", label: "No bus stop on segment", factor: 1.0 },
      { key: "kerbside_low", label: "Kerbside stop, ≤ 30 buses/h", factor: 0.80 },
      { key: "kerbside_high", label: "Kerbside stop, > 30 buses/h", factor: 0.60 },
      { key: "bay_low", label: "Bus bay, ≤ 30 buses/h", factor: 0.90 },
      { key: "bay_high", label: "Bus bay, > 30 buses/h", factor: 0.80 },
    ],
    access_points: [
      { key: "none", label: "No access points", factor: 1.0 },
      { key: "lt200", label: "< 200 veh/h entering/leaving", factor: 0.90 },
      { key: "200_500", label: "200 – 500 veh/h", factor: 0.80 },
      { key: "gt500", label: "> 500 veh/h", factor: 0.70 },
    ],
    dsv_vc_ratio: 0.70,
    model_loaded: true,
  };

  let userTouchedConfig = false;

  function fillSelect(sel, items, render) {
    if (!sel) return;
    const prev = sel.value;
    sel.innerHTML = items.map((o) => `<option value="${o.key}">${render(o)}</option>`).join("");
    if (prev && items.some((o) => o.key === prev)) sel.value = prev;
  }

  function populateDropdowns(data) {
    configData = data;
    if (userTouchedConfig) return;   // never overwrite a selection in progress
    fillSelect(roadTypeSel, data.road_types || [], (o) => o.label);
    if (roadTypeSel && !roadTypeSel.dataset.init) {
      roadTypeSel.value = "divided_4lane";
      roadTypeSel.dataset.init = "1";
    }
    fillSelect(classSel, data.functional_classes || [],
      (o) => `${o.label} (default ${o.operating_speed_kmh} km/h)`);
    FACTOR_FIELDS.forEach((f) =>
      fillSelect(document.getElementById(f), data[f] || [], (o) => `${o.label} — ${o.factor.toFixed(2)}`));

    [roadTypeSel, classSel, speedInput, widthInput, ...FACTOR_FIELDS.map((f) => document.getElementById(f))]
      .forEach((el) => {
        if (!el) return;
        el.oninput = el.onchange = () => { userTouchedConfig = true; updateDsvPreview(); };
      });
    updateDsvPreview();

    if (!data.model_loaded) {
      modelStatusEl.textContent = "⚠ Model not found — copy best.pt into road_analyzer/models/";
      modelStatusEl.classList.add("warn");
    } else {
      modelStatusEl.textContent = "✓ Model loaded and ready.";
      modelStatusEl.classList.remove("warn");
    }
  }

  // Mirrors indo_hcm.base_capacity() so the user sees C0 before uploading.
  function updateDsvPreview() {
    if (!configData || !roadTypeSel) return;
    const rt = (configData.road_types || []).find((o) => o.key === roadTypeSel.value);
    if (!rt) { dsvPreview.style.display = "none"; return; }
    const sm = configData.speed_model || { a: 20.11, b: 210.8, range_kmh: [40, 80] };
    const v = parseFloat(speedInput && speedInput.value);
    let c0 = rt.base_capacity_pcu_h, how = "Indo-HCM Table 5.4";
    if (rt.divided && v > 0) {
      const lane = sm.a * v + sm.b;
      c0 = Math.round(lane * rt.lanes);
      how = `Indo-HCM Eq. 5.4: ${sm.a} × ${v} + ${sm.b} = ${Math.round(lane)} PCU/h/lane × ${rt.lanes}`;
      if (v < sm.range_kmh[0] || v > sm.range_kmh[1]) how += " (outside 40–80 km/h validity — extrapolated)";
    }
    dsvValueEl.textContent = Math.round(c0).toLocaleString("en-IN");
    document.getElementById("dsv-unit").textContent = `PCU/h, ${rt.basis}`;
    const dsv = Math.round(c0 * (configData.dsv_vc_ratio || 0.7));
    document.getElementById("dsv-note").textContent =
      `${how} · LOS-C service volume ${dsv.toLocaleString("en-IN")} PCU/h · before obstructions and side-friction factors`;
    if (roadTypeHint) {
      roadTypeHint.textContent = `${rt.lanes} lanes, ${rt.basis}; reference width ${rt.ref_width_m} m` +
        (rt.note ? ` · ${rt.note}` : "");
    }
    const w = parseFloat(widthInput && widthInput.value);
    if (widthHint && w > 0) {
      const perLane = w / rt.lanes;
      const ok = perLane >= 2.75 && perLane <= 4.25;
      widthHint.textContent = `${perLane.toFixed(2)} m per lane` +
        (ok ? " — consistent with Indo-HCM 3.5 m lanes" : " — check road type or width (Indo-HCM: 3.5 m lanes + 0.25 m shyness)");
      widthHint.classList.toggle("warn", !ok);
    }
    dsvPreview.style.display = "";
  }

  async function loadConfigOptions() {
    populateDropdowns(FALLBACK_CONFIG);
    modelStatusEl.textContent = "⟳ Connecting to server…";
    let retries = 0;
    async function tryFetch() {
      try {
        const res = await fetch("/api/config-options");
        if (!res.ok) throw new Error("Server returned " + res.status);
        populateDropdowns(await res.json());
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

    // ---- Date validation (NEW) ----
    // Collection date: today or earlier — future not allowed.
    if (collectionDateEl && collectionDateEl.value > TODAY_ISO) {
      showError("Data collection date cannot be in the future.");
      return;
    }
    // Analysis date: cannot be in the future.
    if (analysisDateEl && analysisDateEl.value > TODAY_ISO) {
      showError("Data analysis date cannot be in the future.");
      return;
    }
    // Analysis date cannot be earlier than the collection date.
    if (collectionDateEl && analysisDateEl &&
        collectionDateEl.value && analysisDateEl.value &&
        analysisDateEl.value < collectionDateEl.value) {
      showError("Data analysis date cannot be before the data collection date.");
      return;
    }

    if (selectedFiles.length === 0) {
      showError(
        mode === "batch"   ? "Select at least one image first."
        : mode === "video" ? "Select a video file first."
        :                    "Select an image first."
      );
      return;
    }

    const fd = new FormData(configForm);

    runBtn.disabled = true;

    try {
      if (mode === "image") {
        fd.append("file", selectedFiles[0]);
        showStatus("Running AI defect detection and Indo-HCM capacity analysis…");
        const res = await postJSON("/api/analyze/image", fd);
        hideStatus();
        renderImageResult(res);
        dtShow(res.digital_twin);

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
  };
  const FALLBACK_COLORS = ["#D9534F","#D9B84A","#C97A3D","#B58A52","#7E8A6B","#9B6B9E"];
  function colorFor(name, idx) {
    return DEFECT_COLORS[name] || FALLBACK_COLORS[idx % FALLBACK_COLORS.length];
  }

  // ----------------------------------------------------------------
  // HTML builders
  // ----------------------------------------------------------------

  function heroHTML(data) {
    const cfg   = data.road_config || {};
    const basis = data.capacity_basis || {};
    const calc  = data.capacity_calculation || {};
    const iv    = data.indicative_vehicles || {};
    const los   = data.level_of_service;

    const stripParts = [
      ["Collected",       formatDateDisplay(cfg.data_collection_date)],
      ["Analysed",        formatDateDisplay(cfg.analysis_date)],
      ["Road type",       basis.road_type_label],
      ["Basis",           basis.direction_basis],
      ["Class",           basis.functional_class ? titleCase(basis.functional_class) : null],
      ["Width",           cfg.total_width_m != null ? cfg.total_width_m + " m" : null],
      ["Lanes",           cfg.num_lanes],
      ["Operating speed", basis.operating_speed_kmh != null
                            ? `${basis.operating_speed_kmh} km/h (${basis.operating_speed_source})` : null],
    ].filter((p) => p[1] !== null && p[1] !== undefined && p[1] !== "");

    const factors = calc.factors || {};
    const factorChips = Object.entries(factors)
      .map(([k, v]) => `<span class="${v < 1 ? "factor-active" : ""}"><b>${k.replace("F_", "F<sub>")}</sub></b> ${fmt(v, 3)}</span>`)
      .join("");

    const warnings = (basis.warnings || []).concat((data.digital_twin || {}).warnings || []);
    const losHTML = los
      ? `<div class="item"><div class="label">LOS at ${fmt(los.observed_volume_pcu_h, 0)} PCU/h</div>
           <div class="val">${los.los_ideal} → <span class="red">${los.los_reduced}</span></div>
           <div class="val-sub">V/C ${fmt(los.vc_ideal, 2)} → ${fmt(los.vc_reduced, 2)}</div></div>`
      : `<div class="item"><div class="label">Level of service</div>
           <div class="val-sub">Enter an observed volume to get V/C and LOS</div></div>`;

    return `
      <div class="hero">
        <div class="card hero-main">
          <div class="eyebrow">${basis.standard || "Indo-HCM 2017"} · <span class="image-name">${data.image || "untitled"}</span></div>
          <div class="big-number">${fmt(data.reduced_capacity_pcu_h, 0)} <small>PCU/h capacity now (${basis.direction_basis || ""})</small></div>
          <div class="compare">
            <div class="item">
              <div class="label">Base capacity C0</div>
              <div class="val orig">${fmt(data.base_capacity_pcu_h, 0)} PCU/h</div>
              <div class="val-sub">≈ ${fmt(iv.base_capacity_veh_h, 0)} veh/h (assumed mix)</div>
            </div>
            <div class="item">
              <div class="label">Reduced capacity C</div>
              <div class="val red">${fmt(data.reduced_capacity_pcu_h, 0)} PCU/h</div>
              <div class="val-sub">≈ ${fmt(iv.reduced_capacity_veh_h, 0)} veh/h (assumed mix)</div>
            </div>
            <div class="item">
              <div class="label">Capacity lost</div>
              <div class="val loss">${fmt(data.capacity_loss_pcu_h, 0)} PCU/h (${fmt(data.capacity_loss_pct, 1)}%)</div>
              <div class="val-sub">LOS-C service volume ${fmt(data.dsv_los_c_ideal_pcu_h, 0)} → ${fmt(data.dsv_los_c_reduced_pcu_h, 0)}</div>
            </div>
            ${losHTML}
          </div>
          ${calc.formula ? `<div class="formula-box mono">${calc.formula}</div>` : ""}
          <div class="config-strip">${factorChips}</div>
          <div class="config-strip">${stripParts.map(([l, v]) => `<span><b>${l}:</b> ${v}</span>`).join("")}</div>
          ${warnings.map((w) => `<div class="veto-note">⚠ ${w}</div>`).join("")}
          ${data.vehicle_veto_suppressed
            ? `<div class="veto-note">${data.vehicle_veto_suppressed} vendor/cart detection(s) suppressed because they overlapped a vehicle box (likely auto-rickshaws).</div>`
            : ""}
        </div>
        <div class="card capacity-band-card">
          <div class="eyebrow">Overall capacity loss</div>
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

  function roadbarHTML(data) {
    const cfg  = data.road_config || {};
    const calc = data.capacity_calculation || {};
    const perDefect = data.per_defect || {};
    const totalWidth = cfg.total_width_m || 0;
    const segments = Object.keys(perDefect)
      .filter((n) => n !== "pothole")
      .map((name, i) => ({ name, blocked_m: perDefect[name].blocked_m || 0, color: colorFor(name, i),
                           mech: perDefect[name].mechanism }))
      .filter((s) => s.blocked_m > 0.001)
      .sort((a, b) => b.blocked_m - a.blocked_m);
    const blockedTotal = segments.reduce((s, seg) => s + seg.blocked_m, 0);
    const scale  = (blockedTotal > totalWidth && totalWidth > 0) ? totalWidth / blockedTotal : 1;
    const usable = calc.effective_width_m != null ? calc.effective_width_m : Math.max(totalWidth - blockedTotal, 0);

    let barHTML = "";
    if (totalWidth > 0) {
      segments.forEach((seg) => {
        const pct = ((seg.blocked_m * scale) / totalWidth) * 100;
        barHTML += `<div class="seg" style="width:${pct}%;background:${seg.color}" title="${titleCase(seg.name)}: ${fmt(seg.blocked_m,2)} m">${pct > 6 ? `<span class="seg-label">${titleCase(seg.name)}</span>` : ""}</div>`;
      });
      const restPct = Math.max(0, 100 - segments.reduce((s, seg) => s + (seg.blocked_m * scale / totalWidth) * 100, 0));
      barHTML += `<div class="seg usable" style="width:${restPct}%">${restPct > 10 ? `<span class="seg-label">Open</span>` : ""}</div>`;
    }
    const legendHTML =
      segments.map((seg) => `<div class="leg"><span class="dot" style="background:${seg.color}"></span>${titleCase(seg.name)} · ${fmt(seg.blocked_m,2)} m · ${seg.mech}</div>`).join("") +
      `<div class="leg"><span class="dot" style="background:var(--green)"></span>Usable for F<sub>W</sub> (after 0.25 m shy distance) · ${fmt(usable,2)} m</div>`;

    return `
      <div class="card roadbar-card">
        <div class="card-title">Carriageway Width</div>
        <div class="card-sub">Physical occupation across the carriageway. Parked vehicles are shown but act through the Indo-HCM parking factor, not the width factor; potholes act through speed.</div>
        <div class="roadbar">${barHTML}</div>
        <div class="roadbar-meta"><span>Total: ${fmt(totalWidth,2)} m</span><span>Width-class obstructions: ${fmt(calc.obstruction_width_m,2)} m</span><span>Usable: ${fmt(usable,2)} m</span></div>
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
  };

  const DEFECT_ALERT_MESSAGES = {
    pothole: {
      URGENT:  "Medium/large potholes — rectify straightaway (IRC:82-2015 cl. 5.3); verify depth on site.",
      ROUTINE: "Small potholes — fill with premix at the next maintenance round (IRC:82 cl. 7.5.3.5).",
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
      URGENT:  "Garbage severely blocking road - immediate clearance (SWM Rules 2016).",
      ROUTINE: "Garbage dump detected - request priority clearance from the SWM department.",
      MONITOR: "Minor garbage noted - schedule at next municipal collection.",
    },
    barricade: {
      URGENT:  "Barricade severely restricting road - coordinate immediate removal (IRC:SP:55).",
      ROUTINE: "Work zone barricade - ensure proper signage and reduce width to minimum.",
      MONITOR: "Barricade detected - verify valid permit and signage per IRC:SP:55.",
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
            <span>${d.blocked_m ? fmt(d.blocked_m, 2) + " m wide" : d.mechanism}</span>
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
      const size = d.size_summary;
      const depthHTML = size ? `
        <div class="depth-summary">
          <span class="depth-sev depth-${size.worst_size_class}">${size.worst_size_class.toUpperCase()} POTHOLE</span>
          <span class="depth-detail">small ${size.counts.small} · medium ${size.counts.medium} · large ${size.counts.large}
            · assumed speed drop ${fmt(size.assumed_speed_reduction_pct,0)}% · ${size.classification}</span>
        </div>` : "";
      const rec = d.rectification;
      const rectHTML = rec ? `
        <div class="defect-action" style="border-top:1px solid #333;margin-top:8px;padding-top:8px;">
          <strong>${rec.rectification_category}</strong> — ${rec.priority}
          ${rec.escalation_note ? `<div style="font-size:0.8em;opacity:0.8;margin-top:4px;">${rec.escalation_note}</div>` : ""}
          <div style="font-size:0.85em;opacity:0.85;margin-top:4px;">${rec.method}</div>
          <div style="font-size:0.8em;opacity:0.7;">${rec.materials}</div>
          <div style="font-size:0.8em;opacity:0.7;">${rec.work_zone_note}</div>
        </div>` : "";
      return `
        <div class="defect-card sev-${sev}">
          <div class="defect-head">
            <div>
              <div class="defect-name">${titleCase(d.name)}</div>
              <div class="defect-count">${d.count} detected · ${d.mechanism}${d.blocked_m ? ` · ${fmt(d.blocked_m,2)} m` : ""}</div>
            </div>
            <div class="sev-chip sev-${sev}">${sev}</div>
          </div>
          <div class="defect-metrics">
            <div class="m"><div class="v">${fmt(d.capacity_loss_pcu,0)}</div><div class="l">PCU/hr lost</div></div>
            <div class="m"><div class="v">${fmt(d.capacity_loss_pct,1)}%</div><div class="l">of C0 if alone</div></div>
            <div class="m"><div class="v">${fmt(d.factor,3)}</div><div class="l">factor alone</div></div>
          </div>
          ${depthHTML}
          ${rectHTML}
          <div class="defect-action">${d.action || "No specific action mapped - flag for manual inspection."}</div>
          <div class="defect-code">${d.code_ref || ""}</div>
          <div class="defect-code">Severity basis: ${d.severity_basis || "-"}</div>
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
            PWD, Traffic Police, or Municipal Corporation — with IRC code references, verify on site before dispatch.</div>
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
      roadbarHTML(data) +
      `<div class="section-title">Defects Detected — each factor shown as if it were the only obstruction (factors combine by multiplication)</div>` +
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
        <td>${fmt(r.reduced_capacity_pcu_h,0)}</td>
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
          <div class="batch-stat"><div class="l">Bottleneck capacity</div><div class="v">${fmt(data.bottleneck_capacity_pcu_h,0)} PCU/h</div></div>
          <div class="batch-stat"><div class="l">Median loss</div><div class="v">${fmt(data.median_capacity_loss_pct,1)}%</div></div>
          <div class="batch-stat"><div class="l">Worst image</div><div class="v" style="font-size:13px;font-family:monospace;">${data.worst_image_or_frame || "-"}</div></div>
        </div>
      </div>
      ${departmentReportButtonHTML(data)}
      <div class="section-title">Images Ranked by Capacity Loss (Worst First)</div>
      <div class="card">
        <table class="stretch-table">
          <thead><tr><th>#</th><th>Image</th><th>Capacity now (PCU/h)</th><th>Capacity Lost</th><th>Defects Found</th></tr></thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
      ${errorsHTML}`;

    // The department report / digital twin are both built from the worst
    // photo in the batch (see app.py's _run_batch_job) — trigger the same
    // twin panel + polling the single-image flow uses.
    dtShow(data.digital_twin);
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
          <span class="udr-meta">seen ${d.times_seen}× · ${fmt(d.first_seen_sec,1)}s–${fmt(d.last_seen_sec,1)}s · max ${fmt(d.max_width_m,2)} m wide</span>
        </div>`).join("");

    resultsRoot.innerHTML = `
      <div class="card" style="margin-bottom:24px;">
        <div class="card-title">Video Summary - ${data.video}</div>
        <div class="card-sub">Date of analysis: ${formatDateDisplay((data.road_config || {}).analysis_date)}</div>
        <div class="batch-summary-row">
          <div class="batch-stat"><div class="l">Worst moment</div><div class="v loss">${fmt(data.worst_capacity_loss_pct,1)}%</div></div>
          <div class="batch-stat"><div class="l">Bottleneck capacity</div><div class="v">${fmt(data.bottleneck_capacity_pcu_h,0)} PCU/h</div></div>
          <div class="batch-stat"><div class="l">Median loss</div><div class="v">${fmt(data.median_capacity_loss_pct,1)}%</div></div>
          <div class="batch-stat"><div class="l">Frames analysed</div><div class="v">${data.frames_analysed}</div></div>
          <div class="batch-stat"><div class="l">Unique defects tracked</div><div class="v">${data.unique_defect_count}</div></div>
        </div>
      </div>
      ${departmentReportButtonHTML(data)}
      <div class="card timeline-card">
        <div class="card-title">Capacity Loss Over Time</div>
        <div class="card-sub">Each bar = one sampled frame. Fixed camera: change over time. Moving camera: change along the road.</div>
        <div class="timeline-bar">${barsHTML}</div>
        <div class="timeline-meta"><span>0s</span><span>${frames.length ? frames[frames.length-1].timestamp_sec + "s" : "-"}</span></div>
      </div>
      <div class="section-title">Unique Defect Instances (Tracked - Not Double-Counted)</div>
      <div class="unique-defects-list">${uniqueRows || `<div class="empty-state">No obstructions detected.</div>`}</div>`;

    // Same reasoning as renderBatchResult above — twin data was generated
    // from the worst sampled frame in _run_video_job.
    dtShow(data.digital_twin);
  }

  function lossToColor(pct) {
    if (pct < 10) return "#22c55e";
    if (pct < 25) return "#f59e0b";
    if (pct < 50) return "#f97316";
    return "#ef4444";
  }

  // ================================================================
  // DIGITAL TWIN PANEL — twin data arrives with the analysis response
  // ================================================================
  function dtShow(twin) {
    const panel = document.getElementById("dt-panel");
    if (!panel || !twin) return;
    panel.style.display = "";
    const I = twin.ideal || {}, D = twin.defect || {};
    setText("dt-demand-line",
      `Demand ${fmt(twin.demand_pcu_h, 0)} PCU/h — ${twin.demand_source} · horizon ${twin.horizon_min} min`);
    setText("dt-ideal-cap",   fmt(I.capacity_pcu_h, 0));
    setText("dt-defect-cap",  fmt(D.capacity_pcu_h, 0));
    setText("dt-ideal-vc",    fmt(I.vc_ratio, 2));
    setText("dt-defect-vc",   fmt(D.vc_ratio, 2));
    setText("dt-ideal-speed", fmt(I.section_speed_kmh, 1));
    setText("dt-ideal-queue", fmt(I.queue_length_after_horizon_m, 0));
    setText("dt-defect-queue", fmt(D.queue_length_after_horizon_m, 0));
    if (D.queue_growth_pcu_h > 0) {
      setText("dt-defect-speed", `${fmt(D.section_speed_kmh, 1)} / ${fmt(D.upstream_speed_kmh, 1)}`);
      setText("dt-defect-speed-label", "At bottleneck / in the queue");
    } else {
      setText("dt-defect-speed", fmt(D.section_speed_kmh, 1));
      setText("dt-defect-speed-label", "Stream speed at demand");
    }
    setText("dt-loss-pct", fmt(twin.capacity_loss_pct, 1) + "%");

    const notes = [];
    if (D.queue_growth_pcu_h > 0) {
      notes.push(`Demand exceeds the reduced capacity: the queue grows by ${fmt(D.queue_growth_pcu_h,0)} PCU/h and its tail moves upstream at ${fmt(Math.abs(D.shockwave_kmh),1)} km/h; mean added delay ${fmt(D.mean_queue_delay_min,1)} min per vehicle over the horizon.`);
    } else {
      notes.push("Demand is below the reduced capacity: no queue forms; the obstruction only lowers stream speed.");
    }
    (twin.warnings || []).forEach((w) => notes.push("⚠ " + w));
    notes.push("Assumptions: " + (twin.assumptions || []).join(" · "));
    document.getElementById("dt-notes").innerHTML = notes.map((n) => `<div>${n}</div>`).join("");
    document.getElementById("dt-notes").style.display = "";

    drawXY(document.getElementById("dt-cap-chart"), [
      { x: twin.time_min, y: twin.queue_length_m.ideal,  color: "#22c55e", label: "Ideal" },
      { x: twin.time_min, y: twin.queue_length_m.defect, color: "#ef4444", label: "Current" },
    ], "min", "m");
    drawXY(document.getElementById("dt-spd-chart"), [
      { x: twin.speed_flow.ideal.flow_pcu_h,  y: twin.speed_flow.ideal.speed_kmh,  color: "#22c55e", label: "Ideal" },
      { x: twin.speed_flow.defect.flow_pcu_h, y: twin.speed_flow.defect.speed_kmh, color: "#ef4444", label: "Current" },
    ], "PCU/h", "km/h", twin.demand_pcu_h);
  }

  function drawXY(canvas, series, xUnit, yUnit, markX) {
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    const W = canvas.width, H = canvas.height;
    const P = { top: 14, right: 14, bottom: 28, left: 52 };
    const pw = W - P.left - P.right, ph = H - P.top - P.bottom;
    ctx.fillStyle = "#1e293b"; ctx.fillRect(0, 0, W, H);
    const xs = series.flatMap((s) => s.x), ys = series.flatMap((s) => s.y);
    const xMax = Math.max(1, ...xs, markX || 0), yMax = Math.max(1, ...ys) * 1.1;
    const X = (v) => P.left + (v / xMax) * pw, Y = (v) => P.top + ph - (v / yMax) * ph;
    ctx.font = "10px JetBrains Mono, monospace"; ctx.fillStyle = "#64748b";
    ctx.strokeStyle = "#334155"; ctx.lineWidth = 0.5;
    for (let i = 0; i <= 4; i++) {
      const yv = (yMax / 4) * i, y = Y(yv);
      ctx.beginPath(); ctx.moveTo(P.left, y); ctx.lineTo(P.left + pw, y); ctx.stroke();
      ctx.textAlign = "right"; ctx.fillText(Math.round(yv), P.left - 4, y + 3);
      const xv = (xMax / 4) * i;
      ctx.textAlign = "center"; ctx.fillText(Math.round(xv), X(xv), P.top + ph + 14);
    }
    ctx.textAlign = "right"; ctx.fillText(xUnit, P.left + pw, P.top + ph + 26);
    ctx.textAlign = "left";  ctx.fillText(yUnit, 4, P.top + 8);
    if (markX) {
      ctx.strokeStyle = "#94a3b8"; ctx.setLineDash([4, 3]);
      ctx.beginPath(); ctx.moveTo(X(markX), P.top); ctx.lineTo(X(markX), P.top + ph); ctx.stroke();
      ctx.setLineDash([]); ctx.fillText("demand", X(markX) + 3, P.top + 10);
    }
    series.forEach((s, si) => {
      ctx.strokeStyle = s.color; ctx.lineWidth = 2; ctx.beginPath();
      s.x.forEach((xv, i) => (i ? ctx.lineTo(X(xv), Y(s.y[i])) : ctx.moveTo(X(xv), Y(s.y[i]))));
      ctx.stroke();
      ctx.fillStyle = s.color; ctx.fillText(s.label, P.left + 8 + si * 70, P.top + 10);
    });
  }

  function setText(id, val) {
    const el = document.getElementById(id);
    if (el) el.textContent = val;
  }

  // ----------------------------------------------------------------
  // Init
  // ----------------------------------------------------------------
  loadConfigOptions();
})();
