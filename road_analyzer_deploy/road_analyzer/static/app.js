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

  // Data collection date: only PAST dates allowed — today and future are
  // blocked in the date picker itself via max = yesterday.
  if (collectionDateEl) {
    collectionDateEl.max = addDaysISO(TODAY_ISO, -1);
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
