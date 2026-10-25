/* =====================================================================
   Road Capacity Analyzer — dashboard
   All engineering numbers come from the server (road_analyzer/*.py).
   This file only draws them and sends what-if requests to /api/whatif.
   ===================================================================== */
(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const SVG = "http://www.w3.org/2000/svg";

  // ------------------------------------------------------------------ refs
  const form          = $("config-form");
  const fileInput     = $("file-input");
  const dropEl        = $("drop");
  const runBtn        = $("run-btn");
  const runLabel      = $("run-btn-label");
  const modelStatusEl = $("model-status");
  const roadTypeSel   = $("road_type");
  const widthInput    = $("total_width_m");
  const speedInput    = $("operating_speed_kmh");
  const volumeInput   = $("observed_volume_pcu_h");
  const collectionDate = $("data_collection_date");
  const analysisDate   = $("analysis_date");
  const xsection      = $("xsection");
  const photoImg      = $("photo");
  const photoBoxes    = $("photo-boxes");
  const slider        = $("demand-slider");

  const LABEL = {
    street_vendor: "Street vendor", cart: "Handcart", garbage: "Garbage",
    barricade: "Barricade", pothole: "Pothole", illegal_parking: "Parked vehicle",
  };
  const WIDTH_CLASSES = ["street_vendor", "cart", "garbage", "barricade", "pothole"];
  const SHY_M = 0.25;               // Indo-HCM 5.1.2 kerb shyness, used for drawing only
  const MODE_COPY = {
    image: { title: "Choose a road photo", hint: "or drop it here", run: "Analyse photo", accept: "image/*", multiple: false },
    batch: { title: "Choose photos along one road", hint: "they share the road details on the left", run: "Analyse photos", accept: "image/*", multiple: true },
    video: { title: "Choose a road video", hint: "MP4, MOV or AVI", run: "Analyse video",
             accept: "video/*,video/mp4,video/quicktime,video/avi,video/x-msvideo", multiple: false },
  };

  // ------------------------------------------------------------------ state
  let mode = "image";
  let selectedFiles = [];
  let config = null;
  const sessionResults = [];        // single-photo results, for the corridor export
  const S = {                       // what is on screen
    result: null,                   // full single-section result from the server
    photoUrl: null,
    obstacles: [],                  // [{defect_type, left_m, right_m, bbox_px, on}]
    off: { on_street_parking: false, bus_stop: false, access_points: false, iri: false },
    view: null,                     // latest /api/whatif response (or derived from result)
    demand: null,
    whatifTimer: null, whatifSeq: 0,
  };

  // ------------------------------------------------------------------ helpers
  const fmt = (n, d = 0) => (n === null || n === undefined || Number.isNaN(+n)) ? "–"
    : Number(n).toLocaleString("en-IN", { maximumFractionDigits: d, minimumFractionDigits: d });
  const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const metres = (m) => m >= 1000 ? `${fmt(m / 1000, 1)} km` : `${fmt(m)} m`;
  function el(tag, attrs = {}, parent) {
    const n = document.createElementNS(SVG, tag);
    for (const [k, v] of Object.entries(attrs)) if (v !== undefined && v !== null) n.setAttribute(k, v);
    if (parent) parent.appendChild(n);
    return n;
  }
  const cssVar = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  const colorOf = (t) => cssVar(`--c-${t}`) || "#666";
  const reducedMotion = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  function todayISO() {
    const d = new Date();
    return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
  }
  const TODAY = todayISO();
  for (const inp of [collectionDate, analysisDate]) { inp.value = inp.value || TODAY; inp.max = TODAY; }
  function prettyDate(iso) {
    const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso || "");
    if (!m) return iso || "–";
    return new Date(+m[1], +m[2] - 1, +m[3]).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
  }

  // ------------------------------------------------------------------ config
  const FALLBACK_CONFIG = {   // must match road_analyzer/indo_hcm.py
    road_types: [
      { key: "undivided_2lane", label: "Two-lane undivided", lanes: 2, divided: false, basis: "both directions", paved_width_m: 7.0, capacity_pcu_h: 2400, dsv_pcu_h: 1680 },
      { key: "divided_4lane", label: "Four-lane divided", lanes: 2, divided: true, basis: "one direction", paved_width_m: 7.0, capacity_pcu_h: 2700, dsv_pcu_h: 1890 },
      { key: "divided_6lane", label: "Six-lane divided", lanes: 3, divided: true, basis: "one direction", paved_width_m: 10.5, capacity_pcu_h: 4200, dsv_pcu_h: 2940 },
      { key: "divided_8lane", label: "Eight-lane divided", lanes: 4, divided: true, basis: "one direction", paved_width_m: 14.0, capacity_pcu_h: 6800, dsv_pcu_h: 4760,
        condition: "Derived from sections with 1-3 km signal spacing; applies to similar site conditions (Section 5.4.4.2)." },
      { key: "divided_10lane", label: "Ten-lane divided", lanes: 5, divided: true, basis: "one direction", paved_width_m: 17.5, capacity_pcu_h: 10000, dsv_pcu_h: 7000,
        condition: "Derived from sections with 1-3 km signal spacing; applies to similar site conditions (Section 5.4.4.2)." },
    ],
    speed_model: { a: 20.11, b: 210.8, range_kmh: [40, 80] },
    on_street_parking: [
      { key: "none", label: "No on-street parking", factor: 1.0 },
      { key: "len_lt25", label: "Long-term parking, < 25% of segment length", factor: 0.70 },
      { key: "len_25_50", label: "Long-term parking, 25–50% of segment length", factor: 0.65 },
      { key: "len_gt50", label: "Long-term parking, > 50% of segment length", factor: 0.40 },
      { key: "man_le500", label: "Short-term parking, ≤ 500 manoeuvres/km/h", factor: 0.65 },
      { key: "man_gt500", label: "Short-term parking, > 500 manoeuvres/km/h", factor: 0.40 },
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
      { key: "lt200", label: "Access traffic < 200 veh/h (entry + exit)", factor: 0.90 },
      { key: "200_500", label: "Access traffic 200–500 veh/h", factor: 0.80 },
      { key: "gt500", label: "Access traffic > 500 veh/h", factor: 0.70 },
    ],
    width_methods: [
      { key: "proportional", label: "In proportion to usable width" },
      { key: "table_slope", label: "Capacity per metre from Indo-HCM Table 5.4" },
    ],
    dsv_vc_ratio: 0.70,
    los_tables: {
      undivided: [{ letter: "A", vc_max: 0.35 }, { letter: "B", vc_max: 0.55 }, { letter: "C", vc_max: 0.70 }, { letter: "D", vc_max: 0.85 }, { letter: "E", vc_max: 1.00 }],
      divided:   [{ letter: "A", vc_max: 0.15 }, { letter: "B", vc_max: 0.45 }, { letter: "C", vc_max: 0.75 }, { letter: "D", vc_max: 0.85 }, { letter: "E", vc_max: 1.00 }],
    },
    model_loaded: true,
  };
  const WIDTH_METHOD_LABEL = { proportional: "In proportion to usable width", table_slope: "Capacity per metre from Indo-HCM Table 5.4" };

  let userTouched = false;
  function fillSelect(sel, items, render) {
    const prev = sel.value;
    sel.innerHTML = items.map((o) => `<option value="${esc(o.key)}">${esc(render(o))}</option>`).join("");
    if (prev && items.some((o) => o.key === prev)) sel.value = prev;
  }
  function applyConfig(data) {
    config = data;
    if (!userTouched) {
      fillSelect(roadTypeSel, data.road_types, (o) => `${o.label}${o.divided ? ", one direction" : ""}`);
      if (!roadTypeSel.dataset.init) { roadTypeSel.value = "divided_4lane"; roadTypeSel.dataset.init = "1"; }
      for (const f of ["on_street_parking", "bus_stop", "access_points"])
        fillSelect($(f), data[f], (o) => o.factor < 1 ? `${o.label}  (× ${o.factor.toFixed(2)})` : o.label);
      fillSelect($("width_method"), data.width_methods, (o) => WIDTH_METHOD_LABEL[o.key] || o.label);
    }
    modelStatusEl.textContent = data.model_loaded ? "Detection model ready." : "The detection model file is missing on the server (models/best.pt).";
    modelStatusEl.classList.toggle("warn", !data.model_loaded);
    updatePreview();
  }
  async function loadConfig() {
    applyConfig(FALLBACK_CONFIG);
    modelStatusEl.textContent = "Connecting to the server…";
    for (let i = 1; i <= 6; i++) {
      try {
        const r = await fetch("/api/config-options");
        if (!r.ok) throw new Error(r.status);
        applyConfig(await r.json());
        return;
      } catch (e) {
        modelStatusEl.textContent = `The server is starting up (try ${i} of 6). The free host sleeps when idle.`;
        await new Promise((res) => setTimeout(res, 4000));
      }
    }
    modelStatusEl.textContent = "Could not reach the server. Showing offline values.";
    modelStatusEl.classList.add("warn");
  }
  const roadType = () => (config.road_types || []).find((o) => o.key === roadTypeSel.value);

  // ------------------------------------------------------------------ live preview (before analysis)
  function updatePreview() {
    if (!config) return;
    const rt = roadType();
    if (!rt) return;
    const w = parseFloat(widthInput.value);

    speedInput.disabled = !rt.divided;
    if (!rt.divided) speedInput.value = "";
    $("speed-hint").textContent = rt.divided
      ? "At least 100 cars with a gap of more than 8 s, on a clear stretch. Gives a capacity specific to this road."
      : "Not used for two-lane undivided roads: Indo-HCM's speed model covers divided roads only.";

    $("road-type-hint").textContent =
      `${rt.lanes} lanes, ${rt.basis}. Indo-HCM width ${rt.paved_width_m} m.` + (rt.condition ? ` ${rt.condition}` : "");

    const hint = $("width-hint");
    if (w > 0) {
      let ok = true, msg;
      if (rt.divided) {
        ok = Math.abs(w - rt.paved_width_m) <= 0.5;
        msg = ok ? "Matches this road type." : `Indo-HCM expects ${rt.paved_width_m - 0.5}–${rt.paved_width_m + 0.5} m for this road type. Check the road type.`;
      } else {
        ok = w >= 6 && w <= 11;
        msg = !ok ? "Indo-HCM expects 6–11 m for a two-lane undivided road." : (w < 7 ? "Indo-HCM studied widths above 7 m only." : "Matches this road type.");
      }
      hint.textContent = msg;
      hint.classList.toggle("warn", !ok);
    }

    if (S.result) return;     // results on screen: the form no longer drives the drawing
    const v = parseFloat(speedInput.value);
    let c0 = rt.capacity_pcu_h, how = "Indo-HCM Table 5.4";
    if (rt.divided && v > 0) {
      const lane = config.speed_model.a * v + config.speed_model.b;
      c0 = lane * rt.lanes;
      how = `Speed model, ${fmt(lane)} PCU/h per lane`;
    }
    const preview = {
      width: w > 0 ? w : rt.paved_width_m, lanes: rt.lanes, divided: rt.divided,
      c0, c0How: how, basis: rt.basis,
    };
    drawRoad(preview, [], { preview: true });
    renderChainPreview(preview);
  }

  // ------------------------------------------------------------------ mode + files
  function setMode(m) {
    mode = m;
    const c = MODE_COPY[m];
    $("drop-title").textContent = c.title;
    $("drop-hint").textContent = c.hint;
    runLabel.textContent = c.run;
    fileInput.accept = c.accept;
    fileInput.multiple = c.multiple;
    $("video-sample-row").hidden = m !== "video";
    $("camera-btn").hidden = m === "video";
    selectedFiles = [];
    fileInput.value = "";
    $("drop-filelist").textContent = "";
  }
  document.querySelectorAll('#mode-switch input[name="mode"]').forEach((r) =>
    r.addEventListener("change", () => setMode(r.value)));

  function handleFiles(list) {
    const files = Array.from(list || []);
    if (!files.length) return;
    selectedFiles = mode === "batch" ? files : [files[0]];
    $("drop-filelist").textContent = selectedFiles.length > 1
      ? `${selectedFiles.length} photos selected` : selectedFiles[0].name;
    if (mode === "image" && selectedFiles[0].type.startsWith("image/")) showPhoto(selectedFiles[0]);
  }
  fileInput.addEventListener("change", (e) => handleFiles(e.target.files));
  dropEl.addEventListener("dragover", (e) => { e.preventDefault(); dropEl.classList.add("drag"); });
  dropEl.addEventListener("dragleave", () => dropEl.classList.remove("drag"));
  dropEl.addEventListener("drop", (e) => { e.preventDefault(); dropEl.classList.remove("drag"); handleFiles(e.dataTransfer.files); });

  function showPhoto(file) {
    if (S.photoUrl) URL.revokeObjectURL(S.photoUrl);
    if (!file) { S.photoUrl = null; photoImg.hidden = true; $("photo-empty").hidden = false; photoBoxes.innerHTML = ""; return; }
    S.photoUrl = URL.createObjectURL(file);
    photoImg.src = S.photoUrl;
    photoImg.alt = `Road photo ${file.name}`;
    photoImg.hidden = false;
    $("photo-empty").hidden = true;
    photoBoxes.innerHTML = "";
  }

  // camera
  let camStream = null;
  $("camera-btn").addEventListener("click", async () => {
    try {
      camStream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment" }, audio: false });
      $("camera-video").srcObject = camStream;
      $("camera-modal").hidden = false;
      $("camera-capture-btn").focus();
    } catch (err) {
      showError(`The camera could not be opened (${err.message}). Allow camera access for this site, or choose a photo file.`);
    }
  });
  function closeCamera() {
    if (camStream) camStream.getTracks().forEach((t) => t.stop());
    camStream = null;
    $("camera-modal").hidden = true;
  }
  $("camera-cancel-btn").addEventListener("click", closeCamera);
  $("camera-capture-btn").addEventListener("click", () => {
    const v = $("camera-video"), c = $("camera-canvas");
    c.width = v.videoWidth; c.height = v.videoHeight;
    c.getContext("2d").drawImage(v, 0, 0);
    c.toBlob((blob) => {
      const file = new File([blob], `camera_${Date.now()}.jpg`, { type: "image/jpeg" });
      const dt = new DataTransfer(); dt.items.add(file);
      fileInput.files = dt.files;
      handleFiles(dt.files);
      closeCamera();
    }, "image/jpeg", 0.92);
  });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !$("camera-modal").hidden) closeCamera(); });

  form.addEventListener("input", (e) => {
    if (["road_type", "total_width_m", "operating_speed_kmh", "on_street_parking", "bus_stop", "access_points", "width_method"].includes(e.target.id)) userTouched = true;
    updatePreview();
  });

  // ------------------------------------------------------------------ status
  function showStatus(t) { $("status-text").textContent = t; $("status-panel").hidden = false; $("error-box").hidden = true; }
  function hideStatus() { $("status-panel").hidden = true; }
  function showError(t) { $("error-box").textContent = t; $("error-box").hidden = false; }

  // ------------------------------------------------------------------ submit
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    $("error-box").hidden = true;
    if (collectionDate.value > TODAY) return showError("The photo date cannot be in the future.");
    if (analysisDate.value > TODAY) return showError("The analysis date cannot be in the future.");
    if (analysisDate.value < collectionDate.value) return showError("The analysis date cannot be before the photo date.");
    if (!selectedFiles.length) {
      return showError(mode === "batch" ? "Choose at least one photo first." : mode === "video" ? "Choose a video first." : "Choose a photo first.");
    }
    const fd = new FormData(form);
    fd.delete("mode");
    runBtn.disabled = true;
    try {
      if (mode === "image") {
        fd.append("file", selectedFiles[0]);
        showStatus("Finding obstructions and working out the capacity…");
        const res = await postForm("/api/analyze/image", fd);
        hideStatus();
        sessionResults.push(res);
        showSingle(res, { photo: selectedFiles[0] });
      } else if (mode === "batch") {
        selectedFiles.forEach((f) => fd.append("files", f));
        showStatus(`Uploading ${selectedFiles.length} photos…`);
        const start = await postForm("/api/analyze/batch", fd);
        showStatus(`Analysing ${start.num_images} photos. This takes a while on the free server.`);
        const res = await pollJob(start.job_id);
        hideStatus();
        showMulti(res);
      } else {
        fd.append("file", selectedFiles[0]);
        fd.append("sample_every_sec", $("sample-every-sec").value);
        showStatus("Uploading the video…");
        const start = await postForm("/api/analyze/video", fd);
        showStatus(`Analysing one frame every ${$("sample-every-sec").value} s. Long videos take several minutes.`);
        const res = await pollJob(start.job_id);
        hideStatus();
        showMulti(res);
      }
    } catch (err) {
      hideStatus();
      showError(err.message || String(err));
    } finally {
      runBtn.disabled = false;
    }
  });

  async function postForm(url, fd) {
    const r = await fetch(url, { method: "POST", body: fd });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(typeof data.detail === "string" ? data.detail : `The server returned ${r.status}.`);
    return data;
  }
  async function pollJob(id) {
    const t0 = Date.now();
    while (Date.now() - t0 < 15 * 60 * 1000) {
      const r = await fetch(`/api/jobs/${encodeURIComponent(id)}`);
      const d = await r.json();
      if (d.status === "done") return d.result;
      if (d.status === "error") throw new Error(d.error || "The analysis failed.");
      await new Promise((res) => setTimeout(res, 1500));
    }
    throw new Error("The analysis took longer than 15 minutes. Try a shorter video or fewer photos.");
  }

  // ------------------------------------------------------------------ show one section
  function showSingle(res, { photo = null, drop = true } = {}) {
    S.result = res;
    S.obstacles = (res.roadrunner_obstacles || []).map((o) => ({ ...o, on: true }));
    S.off = { on_street_parking: false, bus_stop: false, access_points: false, iri: false };
    S.view = viewFromResult(res);
    const lv = res.level_of_service;
    S.demand = lv && lv.observed_volume_pcu_h ? lv.observed_volume_pcu_h : (res.digital_twin ? res.digital_twin.demand_pcu_h : Math.round(res.base_capacity_pcu_h * 0.7));
    if (photo) showPhoto(photo); else showPhoto(null);
    renderAll({ drop });
    $("demand").hidden = false;
    $("defects").hidden = false;
    renderDownloads(res);
    renderWarnings(res);
    if (!res.level_of_service) requestWhatIf(0);   // fills LOS for the assumed design volume
    if (photo) $("road-figure").scrollIntoView({ behavior: reducedMotion() ? "auto" : "smooth", block: "start" });
  }

  function viewFromResult(res) {
    const calc = res.capacity_calculation || {};
    return {
      base_capacity_pcu_h: res.base_capacity_pcu_h,
      indo_hcm_capacity_pcu_h: res.indo_hcm_capacity_pcu_h,
      reduced_capacity_pcu_h: res.reduced_capacity_pcu_h,
      capacity_loss_pct: res.capacity_loss_pct,
      indo_hcm_factors: calc.indo_hcm_factors || {},
      extension_factors: calc.extension_factors || {},
      parking_class_used: calc.parking_class_used,
      width: { usable_width_m: calc.effective_width_m, clear_effective_width_m: (calc.total_width_m || 0) - 2 * SHY_M },
      level_of_service: res.level_of_service,
      overall_guidance: res.overall_guidance,
      digital_twin: res.digital_twin,
    };
  }

  function sectionGeometry() {
    const res = S.result, cfg = res.road_config || {}, basis = res.capacity_basis || {};
    return { width: +cfg.total_width_m, lanes: +cfg.num_lanes || 2, divided: !!basis.divided, basis: basis.direction_basis };
  }

  function renderAll({ drop = false } = {}) {
    drawRoad(sectionGeometry(), S.obstacles, { drop });
    drawPhotoBoxes();
    renderChain();
    renderDemand();
    renderDefectTable();
  }

  // ------------------------------------------------------------------ the road drawing
  // Plan view of a short slice of carriageway. The horizontal axis is across
  // the road and is the SAME scale as the photo above (photo width = road width).
  function drawRoad(geo, obstacles, { drop = false, preview = false } = {}) {
    const W = 1000, top = 22, sliceH = 132, dimY = top + sliceH + 30, useY = dimY + 34;
    const H = useY + 26;
    const k = W / geo.width;                 // svg units per metre
    xsection.setAttribute("viewBox", `0 0 ${W} ${H}`);
    xsection.innerHTML = '<title id="xsection-title">Plan of the carriageway</title>';
    const defs = el("defs", {}, xsection);
    const hatch = el("pattern", { id: "hatch", width: 6, height: 6, patternUnits: "userSpaceOnUse", patternTransform: "rotate(45)" }, defs);
    el("rect", { width: 6, height: 6, fill: "rgba(242,194,48,.18)" }, hatch);
    el("line", { x1: 0, y1: 0, x2: 0, y2: 6, stroke: "rgba(242,194,48,.75)", "stroke-width": 1.4 }, hatch);
    const barr = el("pattern", { id: "barricade-stripes", width: 16, height: 16, patternUnits: "userSpaceOnUse", patternTransform: "rotate(45)" }, defs);
    el("rect", { width: 16, height: 16, fill: "#fff" }, barr);
    el("rect", { width: 8, height: 16, fill: colorOf("barricade") }, barr);
    const dots = el("pattern", { id: "garbage-dots", width: 8, height: 8, patternUnits: "userSpaceOnUse" }, defs);
    el("rect", { width: 8, height: 8, fill: colorOf("garbage") }, dots);
    el("circle", { cx: 4, cy: 4, r: 1.4, fill: "rgba(255,255,255,.45)" }, dots);

    // asphalt + kerbs (black-and-yellow stripes outside the carriageway)
    el("rect", { x: 0, y: top, width: W, height: sliceH, fill: cssVar("--asphalt") }, xsection);
    for (const x0 of [-12, W]) {
      for (let y = top, i = 0; y < top + sliceH; y += 11, i++)
        el("rect", { x: x0, y, width: 12, height: Math.min(11, top + sliceH - y), fill: i % 2 ? cssVar("--ink") : cssVar("--kerb") }, xsection);
    }
    // lane lines
    for (let i = 1; i < geo.lanes; i++) {
      const x = (W / geo.lanes) * i;
      el("line", { x1: x, y1: top + 6, x2: x, y2: top + sliceH - 6, stroke: "#F4F6F6", "stroke-width": 3, "stroke-dasharray": "18 14" }, xsection);
    }
    if (geo.divided) {
      el("text", { x: 8, y: top - 7, "font-size": 13, fill: cssVar("--ink-2") }, xsection).textContent = "Median side";
      const t = el("text", { x: W - 8, y: top - 7, "font-size": 13, fill: cssVar("--ink-2"), "text-anchor": "end" }, xsection);
      t.textContent = "Footpath side";
    }

    // shy bands: 0.25 m at each kerb and around every obstruction still on the road
    const active = obstacles.filter((o) => o.on && WIDTH_CLASSES.includes(o.defect_type));
    const shy = [[0, SHY_M], [geo.width - SHY_M, geo.width]];
    for (const o of active) {
      shy.push([Math.max(0, o.left_m - SHY_M), o.left_m], [o.right_m, Math.min(geo.width, o.right_m + SHY_M)]);
    }
    for (const [a, b] of shy) if (b > a) el("rect", { x: a * k, y: top, width: (b - a) * k, height: sliceH, fill: "url(#hatch)" }, xsection);

    // obstructions
    obstacles.forEach((o, i) => {
      const x = o.left_m * k, w = Math.max((o.right_m - o.left_m) * k, 4);
      const isParking = o.defect_type === "illegal_parking";
      const g = el("g", {
        class: `obstacle${o.on ? "" : " off"}${drop ? " drop-in" : ""}`,
        tabindex: preview ? null : 0, role: "button",
        "aria-pressed": String(o.on),
        "aria-label": `${LABEL[o.defect_type] || o.defect_type}, ${fmt(o.left_m, 1)} to ${fmt(o.right_m, 1)} m from the left. ${o.on ? "On the road. Press to remove." : "Removed. Press to put back."}`,
        style: drop ? `animation-delay:${i * 90}ms` : null,
      }, xsection);
      const y = top + 16 + (i % 3) * 8, h = sliceH - 32 - (i % 3) * 16;
      let fill = colorOf(o.defect_type);
      if (o.defect_type === "barricade") fill = "url(#barricade-stripes)";
      if (o.defect_type === "garbage") fill = "url(#garbage-dots)";
      const rx = o.defect_type === "pothole" ? Math.min(w, h) / 2 : 3;
      el("rect", { class: "obstacle-body", x, y, width: w, height: h, rx, fill }, g);
      el("rect", { class: "obstacle-outline", x, y, width: w, height: h, rx, fill: "none",
                   stroke: isParking ? "#fff" : "rgba(255,255,255,.7)", "stroke-width": 1.5,
                   "stroke-dasharray": isParking ? "6 4" : null }, g);
      if (w > 70) {
        const t = el("text", { x: x + w / 2, y: y + h / 2 + 5, "text-anchor": "middle", "font-size": 15, fill: "#fff", "font-weight": 600, "pointer-events": "none" }, g);
        t.textContent = LABEL[o.defect_type] || o.defect_type;
      }
      if (S.photoUrl && !preview) {
        for (const xx of [x, x + w])
          el("line", { x1: xx, y1: 0, x2: xx, y2: y, stroke: "rgba(34,41,46,.45)", "stroke-dasharray": "3 4" }, xsection);
      }
      if (!preview) {
        const toggle = () => toggleObstacle(i);
        g.addEventListener("click", toggle);
        g.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggle(); } });
      }
    });

    // dimension line: whole carriageway
    dimension(0, W, dimY, `${fmt(geo.width, 1)} m carriageway`, cssVar("--ink"));
    // usable segments: complement of shy bands + active obstructions
    const blocked = shy.concat(active.map((o) => [o.left_m, o.right_m])).sort((a, b) => a[0] - b[0]);
    const segs = []; let cur = 0;
    for (const [a, b] of blocked) { if (a > cur + 1e-6) segs.push([cur, a]); cur = Math.max(cur, b); }
    if (cur < geo.width - 1e-6) segs.push([cur, geo.width]);
    const sign = cssVar("--sign");
    for (const [a, b] of segs) {
      el("rect", { class: "usable-seg", x: a * k, y: useY - 3, width: (b - a) * k, height: 6, fill: sign }, xsection);
    }
    const usable = S.view && S.view.width && S.view.width.usable_width_m != null && !preview
      ? S.view.width.usable_width_m : segs.reduce((s, [a, b]) => s + b - a, 0);
    const lab = el("text", { x: W / 2, y: useY + 22, "text-anchor": "middle", "font-size": 15, fill: sign, "font-weight": 600 }, xsection);
    lab.textContent = `${fmt(usable, 2)} m usable by moving traffic`;

    function dimension(x1, x2, y, text, color) {
      el("line", { x1, y1: y, x2, y2: y, stroke: color, "stroke-width": 1.2 }, xsection);
      for (const x of [x1, x2]) el("line", { x1: x, y1: y - 7, x2: x, y2: y + 7, stroke: color, "stroke-width": 1.2 }, xsection);
      const t = el("text", { x: (x1 + x2) / 2, y: y - 6, "text-anchor": "middle", "font-size": 15, fill: color }, xsection);
      t.textContent = text;
    }

    const cap = $("xsection-caption");
    if (preview) {
      cap.textContent = `The clear road. The hatched strips are the 0.25 m drivers keep from each kerb (Indo-HCM 5.1.2). Blue is the width left for moving traffic.`;
    } else {
      const n = obstacles.length;
      cap.textContent = n
        ? `${n} obstruction${n > 1 ? "s" : ""} found. Click one to take it off the road and see the capacity without it. Parked vehicles (dashed) count through the Indo-HCM parking factor, not width.`
        : "No obstructions were found in this photo.";
    }
  }

  function drawPhotoBoxes() {
    photoBoxes.innerHTML = "";
    if (!S.photoUrl || !S.result) return;
    const sz = S.result.image_size_px || {};
    if (!sz.width) return;
    photoBoxes.setAttribute("viewBox", `0 0 ${sz.width} ${sz.height}`);
    photoBoxes.setAttribute("preserveAspectRatio", "none");
    const sw = Math.max(2, sz.width / 400);
    S.obstacles.forEach((o) => {
      if (!o.bbox_px) return;
      const [x1, y1, x2, y2] = o.bbox_px;
      el("rect", { x: x1, y: y1, width: x2 - x1, height: y2 - y1, fill: "none",
                   stroke: o.on ? colorOf(o.defect_type) : "rgba(255,255,255,.5)", "stroke-width": sw * 1.5,
                   "stroke-dasharray": o.on ? null : `${sw * 4} ${sw * 3}` }, photoBoxes);
      for (const x of [x1, x2])
        el("line", { x1: x, y1: y2, x2: x, y2: sz.height, stroke: "rgba(255,255,255,.55)", "stroke-width": sw * 0.6, "stroke-dasharray": `${sw * 2} ${sw * 3}` }, photoBoxes);
    });
  }

  // ------------------------------------------------------------------ capacity chain
  function chainValue(v, label, cls = "") {
    return `<li><div class="chain-value ${cls}"><strong>${fmt(v)}</strong><small>${label}</small></div></li>`;
  }
  function chainFactor(key, value, label, on, togglable, ext = false) {
    return `<li><button type="button" class="chain-factor" data-factor="${key}" aria-pressed="${on}" ${togglable ? "" : "disabled"}
      title="${togglable ? (on ? "Switch this off to see the road without it" : "Switch back on") : ""}">
      <b class="${ext ? "ext" : ""}">× ${fmt(value, 3)}</b><small>${label}</small></button></li>`;
  }

  function renderChainPreview(p) {
    $("chain").innerHTML = chainValue(p.c0, `PCU/h, ${p.basis}.<br>${p.c0How}`, "is-final");
    $("chain-note").textContent = "This is the capacity of the clear road. Analyse a photo to find what is reducing it.";
    $("whatif-reset").hidden = true;
  }

  function renderChain() {
    const v = S.view, res = S.result;
    const hf = v.indo_hcm_factors || {}, ef = v.extension_factors || {};
    const basis = res.capacity_basis || {};
    const parkTable = (config.on_street_parking || []).find((o) => o.key === v.parking_class_used);
    const parts = [];
    parts.push(chainValue(v.base_capacity_pcu_h, `PCU/h, clear road<br>${esc(basis.base_capacity_method || "")}`));

    const cfg = res.road_config || {};
    const hcmItems = [
      ["F_OP", "on_street_parking", "Parked vehicles", hf.F_OP, cfg.on_street_parking !== "none" || S.obstacles.some((o) => o.defect_type === "illegal_parking")],
      ["F_BS", "bus_stop", "Bus stop", hf.F_BS, cfg.bus_stop && cfg.bus_stop !== "none"],
      ["F_AC", "access_points", "Side roads", hf.F_AC, cfg.access_points && cfg.access_points !== "none"],
    ];
    let anyHcm = false;
    for (const [fk, offKey, label, val, present] of hcmItems) {
      if (!present) continue;
      anyHcm = true;
      const on = !S.off[offKey];
      const extra = fk === "F_OP" && parkTable && on ? `<br>${esc(parkTable.label.split(",")[0])}` : "";
      parts.push(chainFactor(offKey, on ? val : 1, `${label}${extra}`, on, true));
    }
    if (anyHcm) parts.push(chainValue(v.indo_hcm_capacity_pcu_h, "PCU/h, Indo-HCM", "is-hcm"));

    const widthObs = S.obstacles.filter((o) => WIDTH_CLASSES.includes(o.defect_type));
    if (widthObs.length) {
      const on = widthObs.some((o) => o.on);
      parts.push(chainFactor("width", ef.F_W, "Lost width<br>project extension", on, true, true));
    }
    const rough = (res.capacity_calculation || {}).roughness || {};
    if (rough.applied) parts.push(chainFactor("iri", ef.F_R, "Roughness<br>project extension", !S.off.iri, true, true));
    parts.push(chainValue(v.reduced_capacity_pcu_h, "PCU/h now", "is-final"));
    $("chain").innerHTML = parts.join("");
    $("chain").querySelectorAll(".chain-factor:not([disabled])").forEach((b) =>
      b.addEventListener("click", () => toggleFactor(b.dataset.factor)));

    const lost = v.base_capacity_pcu_h - v.reduced_capacity_pcu_h;
    const g = v.overall_guidance || {};
    const flag = isWhatIf() ? '<span class="whatif-flag">What-if</span>' : "";
    $("chain-note").innerHTML =
      `The road has lost <b>${fmt(lost)} PCU/h, ${fmt(v.capacity_loss_pct, 1)}%</b> of its capacity. ${esc(g.action || "")}${flag}`;
    $("whatif-reset").hidden = !isWhatIf();
  }

  // ------------------------------------------------------------------ what-if
  function isWhatIf() {
    return S.obstacles.some((o) => !o.on) || Object.values(S.off).some(Boolean) || demandDiffers();
  }
  function demandDiffers() {
    const lv = S.result && S.result.level_of_service;
    const orig = lv && lv.observed_volume_pcu_h ? lv.observed_volume_pcu_h : (S.result && S.result.digital_twin ? S.result.digital_twin.demand_pcu_h : null);
    return orig != null && Math.abs(S.demand - orig) > 0.5;
  }
  function toggleObstacle(i) {
    const o = S.obstacles[i];
    o.on = !o.on;
    if (o.defect_type === "illegal_parking") {
      const anyOn = S.obstacles.some((x) => x.defect_type === "illegal_parking" && x.on);
      if (!anyOn && (S.result.road_config || {}).on_street_parking !== "none") S.off.on_street_parking = true;
      if (anyOn) S.off.on_street_parking = false;
    }
    drawRoad(sectionGeometry(), S.obstacles);
    drawPhotoBoxes();
    renderDefectTable();
    requestWhatIf();
  }
  function toggleFactor(key) {
    if (key === "width") {
      const widthObs = S.obstacles.filter((o) => WIDTH_CLASSES.includes(o.defect_type));
      const turnOn = !widthObs.some((o) => o.on);
      widthObs.forEach((o) => { o.on = turnOn; });
    } else if (key === "iri") {
      S.off.iri = !S.off.iri;
    } else {
      S.off[key] = !S.off[key];
      if (key === "on_street_parking")
        S.obstacles.forEach((o) => { if (o.defect_type === "illegal_parking") o.on = !S.off.on_street_parking; });
    }
    drawRoad(sectionGeometry(), S.obstacles);
    drawPhotoBoxes();
    renderDefectTable();
    requestWhatIf();
  }
  function requestWhatIf(delay = 120) {
    clearTimeout(S.whatifTimer);
    S.whatifTimer = setTimeout(sendWhatIf, delay);
  }
  async function sendWhatIf() {
    const seq = ++S.whatifSeq;
    const cfg = { ...(S.result.road_config || {}) };
    for (const k of ["on_street_parking", "bus_stop", "access_points"]) if (S.off[k]) cfg[k] = "none";
    if (S.off.iri) cfg.iri_m_per_km = null;
    const body = {
      road_config: cfg,
      obstacles: S.obstacles.filter((o) => o.on).map(({ defect_type, left_m, right_m }) => ({ defect_type, left_m, right_m })),
      demand_pcu_h: S.demand,
    };
    try {
      const r = await fetch("/api/whatif", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      const data = await r.json();
      if (!r.ok) throw new Error(data.detail || r.status);
      if (seq !== S.whatifSeq) return;          // a newer request is on its way
      S.view = data;
      drawRoad(sectionGeometry(), S.obstacles);
      drawPhotoBoxes();
      renderChain();
      renderDemand();
    } catch (err) {
      showError(`Could not recalculate: ${err.message}. The server may be asleep; try again in a minute.`);
    }
  }

  // ------------------------------------------------------------------ demand, LOS, twin
  function renderDemand() {
    const v = S.view, twin = v.digital_twin;
    const c0 = v.base_capacity_pcu_h;
    const lv = S.result.level_of_service;
    const surveyed = lv && lv.observed_volume_pcu_h;
    const max = Math.ceil(Math.max(c0 * 1.3, (S.demand || 0) * 1.15) / 100) * 100;
    slider.max = max;
    slider.value = S.demand;
    $("demand-out").textContent = fmt(S.demand);

    const marks = [
      [v.reduced_capacity_pcu_h, "Capacity now"],
      [c0, "Clear-road capacity"],
    ];
    if (surveyed) marks.push([surveyed, "Surveyed"]);
    marks.sort((a, b) => a[0] - b[0]);
    $("demand-marks").innerHTML = marks.map(([val, t], i) =>
      `<span style="left:${(val / max) * 100}%;top:${i % 2 ? 14 : 0}px">${t} ${fmt(val)}</span>`).join("");
    $("demand-marks").style.height = "48px";

    // LOS rows
    const divided = !!(S.result.capacity_basis || {}).divided;
    const table = (config.los_tables || FALLBACK_CONFIG.los_tables)[divided ? "divided" : "undivided"];
    const L = v.level_of_service;
    const rows = [["Clear road", "", L && L.vc_base, L && L.los_base]];
    if (Math.abs(v.indo_hcm_capacity_pcu_h - c0) > 0.5) rows.push(["With side friction", "Indo-HCM", L && L.vc_hcm, L && L.los_hcm]);
    rows.push(["As found", "with obstructions", L && L.vc_ext, L && L.los_ext]);
    const VC_MAX = 1.5;
    const bands = [];
    let lo = 0;
    for (const b of table) { bands.push([b.letter, lo, b.vc_max]); lo = b.vc_max; }
    bands.push(["F", lo, VC_MAX]);
    const scale = bands.map(([l, a, b]) =>
      `<span class="los-band" style="width:${((b - a) / VC_MAX) * 100}%;background:var(--los-${l})">${l}</span>`).join("");
    $("los").innerHTML = rows.map(([label, sub, vc, letter]) => {
      const pos = vc == null ? 100 : Math.min(vc, VC_MAX) / VC_MAX * 100;
      return `<div class="los-row">
        <div class="los-row-label">${label}${sub ? `<small>${sub}</small>` : ""}</div>
        <div class="los-scale" aria-hidden="true">${scale}<span class="los-pin" style="left:${pos}%"></span></div>
        <div class="los-letter" style="color:var(--los-${letter || "F"})">${letter || "–"}<small>V/C ${vc == null ? "–" : fmt(vc, 2)}</small></div>
      </div>`;
    }).join("") + `<p class="hint">Level of service from Indo-HCM Table ${divided ? "5.7" : "5.6"}, by traffic ÷ capacity.</p>`;

    // twin figures for the road as found
    if (!twin) { $("twin-figures").innerHTML = ""; return; }
    const d = twin.defect, i = twin.ideal;
    const figs = [];
    if (d.queue_growth_pcu_h > 0) {
      figs.push([metres(d.queue_length_after_horizon_m), "queue behind the section after one hour"]);
      figs.push([d.mean_queue_delay_min == null ? "No exit" : `${fmt(d.mean_queue_delay_min, 1)} min`, "extra delay per vehicle, average"]);
      figs.push([`${fmt(d.upstream_speed_kmh, 1)} km/h`, "speed inside the queue"]);
      figs.push([`${fmt(d.section_speed_kmh, 1)} km/h`, "speed past the obstruction"]);
    } else {
      figs.push(["No queue", "traffic is below the capacity now"]);
      figs.push([`${fmt(d.section_speed_kmh, 1)} km/h`, "speed past the obstruction"]);
      figs.push([`${fmt(i.section_speed_kmh, 1)} km/h`, "speed on the clear road"]);
    }
    $("twin-figures").innerHTML = figs.map(([a, b]) => `<div class="twin-figure"><strong>${a}</strong><span>${b}</span></div>`).join("");
    drawSpeedChart(twin);
    drawQueueChart(twin);
    $("twin-assumptions").innerHTML = `<summary>How the traffic model works</summary><ul>${
      (twin.assumptions || []).concat(twin.warnings || []).map((a) => `<li>${esc(a)}</li>`).join("")}</ul>`;
  }

  slider.addEventListener("input", () => {
    S.demand = +slider.value;
    $("demand-out").textContent = fmt(S.demand);
    requestWhatIf(90);
  });

  function axes(svg, xMax, yMax, xLabel, yLabel, xTicks, yTicks) {
    const P = { l: 46, r: 14, t: 14, b: 38 }, Wd = 480 - P.l - P.r, Hd = 260 - P.t - P.b;
    const X = (x) => P.l + (x / xMax) * Wd, Y = (y) => P.t + Hd - (y / yMax) * Hd;
    svg.querySelectorAll(":not(title)").forEach((n) => n.remove());
    for (const t of yTicks) {
      el("line", { x1: P.l, y1: Y(t), x2: P.l + Wd, y2: Y(t), stroke: cssVar("--rule") }, svg);
      el("text", { x: P.l - 6, y: Y(t) + 4, "text-anchor": "end" }, svg).textContent = fmt(t);
    }
    for (const t of xTicks) el("text", { x: X(t), y: P.t + Hd + 16, "text-anchor": "middle" }, svg).textContent = fmt(t);
    el("line", { x1: P.l, y1: P.t + Hd, x2: P.l + Wd, y2: P.t + Hd, stroke: cssVar("--ink") }, svg);
    el("text", { x: P.l + Wd, y: 256, "text-anchor": "end" }, svg).textContent = xLabel;
    el("text", { x: 4, y: 11 }, svg).textContent = yLabel;
    return { X, Y };
  }
  const niceTicks = (max, n = 4) => {
    const raw = max / n, mag = Math.pow(10, Math.floor(Math.log10(raw)));
    const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw);
    const out = []; for (let t = 0; t <= max + 1e-9; t += step) out.push(+t.toFixed(6)); return out;
  };

  function legend(svg, x, anchor) {
    const items = [["Clear road", cssVar("--ink-2"), "6 4"], ["As found", cssVar("--sign"), null]];
    items.forEach(([label, color, dash], i) => {
      const y = 28 + i * 18, lx = anchor === "end" ? x - 26 : x;
      el("line", { x1: lx, y1: y - 4, x2: lx + 22, y2: y - 4, stroke: color, "stroke-width": 2.5, "stroke-dasharray": dash }, svg);
      const t = el("text", { x: anchor === "end" ? lx - 6 : lx + 28, y, "text-anchor": anchor }, svg);
      t.textContent = label;
    });
  }

  function drawSpeedChart(twin) {
    const svg = $("chart-speed");
    const sf = twin.speed_flow;
    const xMax = Math.max(sf.ideal.flow_pcu_h.at(-1), twin.demand_pcu_h) * 1.08;
    const yMax = Math.max(...sf.ideal.speed_kmh) * 1.12;
    const { X, Y } = axes(svg, xMax, yMax, "traffic, PCU/h", "speed, km/h", niceTicks(xMax), niceTicks(yMax));
    const line = (q, v, color, dash) => {
      const d = q.map((x, j) => `${j ? "L" : "M"}${X(x).toFixed(1)},${Y(v[j]).toFixed(1)}`).join("");
      el("path", { d, fill: "none", stroke: color, "stroke-width": 2.5, "stroke-dasharray": dash }, svg);
    };
    line(sf.ideal.flow_pcu_h, sf.ideal.speed_kmh, cssVar("--ink-2"), "6 4");
    line(sf.defect.flow_pcu_h, sf.defect.speed_kmh, cssVar("--sign"));
    el("line", { x1: X(twin.demand_pcu_h), y1: 14, x2: X(twin.demand_pcu_h), y2: 222, stroke: cssVar("--kerb"), "stroke-width": 2 }, svg);
    for (const [st, color] of [[twin.ideal, cssVar("--ink-2")], [twin.defect, cssVar("--sign")]]) {
      const q = st.queue_growth_pcu_h > 0 ? st.capacity_pcu_h : twin.arrival_pcu_h ?? twin.demand_pcu_h;
      el("circle", { cx: X(q), cy: Y(st.section_speed_kmh), r: 5, fill: color, stroke: "#fff", "stroke-width": 1.5 }, svg);
    }
    legend(svg, 462, "end");
  }

  function drawQueueChart(twin) {
    const svg = $("chart-queue");
    const tm = twin.time_min, qd = twin.queue_length_m.defect, qi = twin.queue_length_m.ideal;
    const yMax = Math.max(100, ...qd, ...qi) * 1.1;
    const { X, Y } = axes(svg, 60, yMax, "minutes", "queue, m", [0, 15, 30, 45, 60], niceTicks(yMax));
    const path = (vals, color, dash) => el("path", {
      d: tm.map((x, j) => `${j ? "L" : "M"}${X(x).toFixed(1)},${Y(vals[j]).toFixed(1)}`).join(""),
      fill: "none", stroke: color, "stroke-width": 2.5, "stroke-dasharray": dash }, svg);
    path(qi, cssVar("--ink-2"), "6 4");
    path(qd, cssVar("--sign"));
    legend(svg, 60, "start");
    if (Math.max(...qd) === 0) el("text", { x: 240, y: 120, "text-anchor": "middle" }, svg).textContent = "No queue at this traffic level";
  }

  // ------------------------------------------------------------------ defects table
  function renderDefectTable() {
    const pd = S.result.per_defect || {};
    const names = Object.keys(pd).sort((a, b) => (pd[b].capacity_loss_pct || 0) - (pd[a].capacity_loss_pct || 0));
    if (!names.length) {
      $("defect-table").innerHTML = "<tbody><tr><td>No obstructions were found. The road is working at its full Indo-HCM capacity for the side friction entered.</td></tr></tbody>";
      return;
    }
    const rows = names.map((n) => {
      const d = pd[n];
      const obs = S.obstacles.filter((o) => o.defect_type === n);
      const on = obs.some((o) => o.on);
      const spans = (d.detections || []).map((x) => `${fmt(x.left_m, 1)}–${fmt(x.right_m, 1)}`).join(", ");
      const mech = n === "illegal_parking" ? "Indo-HCM parking factor" : n === "pothole" || WIDTH_CLASSES.includes(n) ? "Lost width" : "–";
      const det = [];
      det.push(`<p><b>Action.</b> ${esc(d.action)}</p>`);
      det.push(`<p><b>Reference.</b> ${esc(d.code_ref)}. Priority from ${esc(d.severity_basis)}.</p>`);
      if (d.size_summary) {
        const c = d.size_summary.counts || {};
        det.push(`<p><b>Size.</b> ${c.small || 0} small, ${c.medium || 0} medium, ${c.large || 0} large. ${esc(d.size_summary.classification)}.</p>`);
      }
      if (d.rectification) {
        const r = d.rectification;
        det.push(`<p><b>${esc(r.rectification_category)}.</b> ${esc(r.method)}</p><p>${esc(r.materials)} ${esc(r.work_zone_note)}</p>`);
        if (r.escalation_note) det.push(`<p>${esc(r.escalation_note)}</p>`);
      }
      return `<tr class="${on ? "" : "off"}">
          <td><label class="switch"><input type="checkbox" data-class="${n}" ${on ? "checked" : ""}> on road</label></td>
          <td class="defect-name"><span class="swatch" style="background:${colorOf(n)}"></span>${esc(LABEL[n] || n)}${d.count > 1 ? ` × ${d.count}` : ""}</td>
          <td class="num">${spans} m</td>
          <td>${mech}</td>
          <td class="num">${fmt(d.capacity_loss_pct, 1)}%</td>
          <td class="priority ${d.severity}">${d.severity ? d.severity.charAt(0) + d.severity.slice(1).toLowerCase() : "–"}</td>
          <td><button type="button" class="row-toggle" aria-expanded="false" data-row="${n}">Details</button></td>
        </tr>
        <tr class="detail-row" id="detail-${n}" hidden><td colspan="7">${det.join("")}</td></tr>`;
    }).join("");
    $("defect-table").innerHTML = `<thead><tr><th>Include</th><th>Obstruction</th><th>From the left kerb</th><th>Acts through</th><th>Loss alone</th><th>Priority</th><th></th></tr></thead><tbody>${rows}</tbody>`;
    $("defect-table").querySelectorAll("input[data-class]").forEach((cb) => cb.addEventListener("change", () => {
      const cls = cb.dataset.class;
      S.obstacles.forEach((o) => { if (o.defect_type === cls) o.on = cb.checked; });
      if (cls === "illegal_parking" && (S.result.road_config || {}).on_street_parking !== "none") S.off.on_street_parking = !cb.checked;
      drawRoad(sectionGeometry(), S.obstacles);
      drawPhotoBoxes();
      renderDefectTable();
      requestWhatIf();
    }));
    $("defect-table").querySelectorAll(".row-toggle").forEach((b) => b.addEventListener("click", () => {
      const row = $(`detail-${b.dataset.row}`);
      row.hidden = !row.hidden;
      b.setAttribute("aria-expanded", String(!row.hidden));
      b.textContent = row.hidden ? "Details" : "Hide";
    }));
  }

  // ------------------------------------------------------------------ downloads
  function renderDownloads(res) {
    const id = encodeURIComponent(res.job_id || "");
    const items = [];
    if (res.department_report_available) items.push([`/api/jobs/${id}/department-report.pdf`, "Department report", "PDF for PWD, traffic police and municipal desks"]);
    if (res.roadrunner_xodr_available) items.push([`/api/jobs/${id}/bundle.zip`, "Digital twin bundle", "ZIP with road files and MATLAB scripts"]);
    if (res.defects_excel_available) items.push([`/api/jobs/${id}/defects.xlsx`, "Obstruction log", "Excel, one row per detection"]);
    if (res.roadrunner_xodr_available) items.push([`/api/jobs/${id}/roadrunner.xodr`, "Road file", "OpenDRIVE for RoadRunner"]);
    let html = items.map(([href, t, s]) => `<a class="download" href="${href}" download><b>${t}</b><small>${s}</small></a>`).join("");
    if (sessionResults.length >= 2) {
      html += [
        ["corridor-xodr", "Corridor road file", `${sessionResults.length} photos joined by distance`],
        ["corridor-ideal", "Corridor, no obstructions", "the same corridor, cleared"],
        ["corridor-capacity", "Corridor capacity", "weakest section governs"],
      ].map(([k, t, s]) => `<button type="button" class="download" data-corridor="${k}"><b>${t}</b><small>${s}</small></button>`).join("");
    }
    $("download-row").innerHTML = html;
    $("downloads").hidden = !html;
    $("download-row").querySelectorAll("[data-corridor]").forEach((b) => b.addEventListener("click", () => corridorDownload(b)));
  }
  async function corridorDownload(btn) {
    const map = {
      "corridor-xodr": ["/api/export/roadrunner-corridor.xodr", "roadrunner_corridor.xodr"],
      "corridor-ideal": ["/api/export/roadrunner-corridor-ideal.xodr", "roadrunner_corridor_ideal.xodr"],
      "corridor-capacity": ["/api/export/roadrunner-corridor-capacity.json", "roadrunner_corridor_capacity.json"],
    };
    const [url, name] = map[btn.dataset.corridor];
    btn.disabled = true;
    try {
      const r = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ results: sessionResults }) });
      if (!r.ok) { const e = await r.json().catch(() => ({})); throw new Error(e.detail || r.status); }
      const blob = await r.blob(), a = document.createElement("a");
      a.href = URL.createObjectURL(blob); a.download = name; a.click();
      setTimeout(() => URL.revokeObjectURL(a.href), 1000);
    } catch (e) { showError(`Could not build the corridor file: ${e.message}`); }
    finally { btn.disabled = false; }
  }

  function renderWarnings(res) {
    const basis = res.capacity_basis || {};
    const list = [...(basis.warnings || [])];
    if (res.vehicle_veto_suppressed) list.push(`${res.vehicle_veto_suppressed} vendor or cart box(es) ignored because they overlapped a vehicle (usually an auto-rickshaw).`);
    if (res.indicative_vehicles) list.push(`Vehicles per hour: about ${fmt(res.indicative_vehicles.base_capacity_veh_h)} on the clear road and ${fmt(res.indicative_vehicles.reduced_capacity_veh_h)} now. ${res.indicative_vehicles.note}`);
    list.push(`Operating speed ${fmt(basis.operating_speed_kmh, 1)} km/h: ${basis.operating_speed_source}.`);
    const w = $("warnings");
    w.innerHTML = `<summary>Notes on this result (${list.length})</summary><ul>${list.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>`;
    w.open = (basis.warnings || []).length > 0;
    w.hidden = false;
  }

  // ------------------------------------------------------------------ several photos / video
  function showMulti(sum) {
    const isVideo = sum.mode === "video";
    const b = sum.bottleneck_result;
    let photo = null;
    if (!isVideo && b) photo = selectedFiles.find((f) => f.name === b.image) || null;
    if (b) showSingle({ ...b, digital_twin: sum.digital_twin, job_id: sum.job_id }, { photo, drop: true });
    else { S.result = null; showPhoto(null); updatePreview(); }
    renderDownloads({ ...(b || {}), job_id: sum.job_id, department_report_available: sum.department_report_available,
                      roadrunner_xodr_available: false, defects_excel_available: false });

    const m = $("multi");
    const figs = isVideo
      ? [[sum.frames_analysed, "frames analysed"], [fmt(sum.bottleneck_capacity_pcu_h), "PCU/h at the worst moment"],
         [`${fmt(sum.worst_capacity_loss_pct, 1)}%`, "largest capacity loss"], [sum.unique_defect_count, "obstructions tracked"]]
      : [[`${sum.num_succeeded} of ${sum.num_images}`, "photos analysed"], [fmt(sum.bottleneck_capacity_pcu_h), "PCU/h at the bottleneck"],
         [`${fmt(sum.worst_capacity_loss_pct, 1)}%`, "largest capacity loss"], [`${fmt(sum.median_capacity_loss_pct, 1)}%`, "median loss"]];
    let html = `<div class="section-head"><h2>${isVideo ? esc(sum.video) : "Photos along the road"}</h2>
      <p class="section-sub">${isVideo
        ? `The drawing above shows the frame at ${fmt((b || {}).timestamp_sec, 1)} s, where capacity was lowest. With a fixed camera the bars are changes over time; with a moving camera they are changes along the road.`
        : `A road carries no more than its narrowest point allows, so the drawing above shows the bottleneck photo, ${esc((b || {}).image || "")}.`}</p></div>
      <div class="multi-figures">${figs.map(([a, t]) => `<div><strong>${a}</strong><span>${t}</span></div>`).join("")}</div>`;

    if (isVideo) {
      const fr = sum.frame_by_frame || [];
      const W = 900, H = 140, maxT = fr.length ? fr[fr.length - 1].timestamp_sec || 1 : 1;
      const bars = fr.map((f) => {
        const x = 40 + (f.timestamp_sec / maxT) * (W - 60), h = (f.capacity_loss_pct / 100) * (H - 40);
        return `<rect x="${x.toFixed(1)}" y="${(H - 24 - h).toFixed(1)}" width="${Math.max(2, (W - 60) / Math.max(fr.length, 1) - 1).toFixed(1)}" height="${h.toFixed(1)}" fill="var(--sign)"><title>${fmt(f.timestamp_sec, 1)} s, ${fmt(f.capacity_loss_pct, 1)}% lost</title></rect>`;
      }).join("");
      html += `<svg class="timeline" viewBox="0 0 ${W} ${H}" role="img" aria-label="Capacity loss in each analysed frame">
        <line x1="40" y1="${H - 24}" x2="${W - 20}" y2="${H - 24}" stroke="var(--ink)"/>${bars}
        <text x="40" y="${H - 6}">0 s</text><text x="${W - 20}" y="${H - 6}" text-anchor="end">${fmt(maxT, 1)} s</text>
        <text x="4" y="14">capacity lost, % (bar height)</text></svg>`;
      const u = (sum.unique_defect_instances || []).slice().sort((a, c) => c.times_seen - a.times_seen);
      html += `<table><thead><tr><th>Obstruction</th><th>Seen in frames</th><th>First seen</th><th>Last seen</th><th>Widest</th></tr></thead><tbody>${
        u.map((d) => `<tr><td>${esc(LABEL[d.cls_name] || d.cls_name)}</td><td class="num">${d.times_seen}</td><td class="num">${fmt(d.first_seen_sec, 1)} s</td><td class="num">${fmt(d.last_seen_sec, 1)} s</td><td class="num">${fmt(d.max_width_m, 2)} m</td></tr>`).join("")
        || '<tr><td colspan="5">No obstructions were tracked.</td></tr>'}</tbody></table>`;
    } else {
      const rows = (sum.per_image || []).slice().sort((a, c) => a.reduced_capacity_pcu_h - c.reduced_capacity_pcu_h);
      html += `<table><thead><tr><th>Photo</th><th>Capacity now, PCU/h</th><th>Lost</th><th>Found</th></tr></thead><tbody>${
        rows.map((r) => `<tr class="${b && r.image === b.image ? "is-bottleneck" : ""}"><td>${esc(r.image)}</td><td class="num">${fmt(r.reduced_capacity_pcu_h)}</td><td class="num">${fmt(r.capacity_loss_pct, 1)}%</td><td>${
          r.defects_found.length ? r.defects_found.map((n) => esc(LABEL[n] || n)).join(", ") : "nothing"}</td></tr>`).join("")}</tbody></table>`;
      if ((sum.errors || []).length)
        html += `<p class="error" style="margin-top:14px">${sum.errors.length} photo(s) could not be read: ${sum.errors.map((e) => esc(`${e.image} (${e.error})`)).join("; ")}</p>`;
    }
    m.innerHTML = html;
    m.hidden = false;
  }

  // back to the surveyed road (keeps the photo on screen)
  $("whatif-reset").addEventListener("click", () => {
    S.obstacles.forEach((o) => { o.on = true; });
    S.off = { on_street_parking: false, bus_stop: false, access_points: false, iri: false };
    const lv = S.result.level_of_service;
    S.demand = lv && lv.observed_volume_pcu_h ? lv.observed_volume_pcu_h : (S.result.digital_twin ? S.result.digital_twin.demand_pcu_h : S.demand);
    S.view = viewFromResult(S.result);
    renderAll();
  });

  // ------------------------------------------------------------------ init
  setMode("image");
  loadConfig();
})();
