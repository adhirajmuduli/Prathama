(function () {
  "use strict";

  const EMPTY_STYLE = {
    version: 8,
    sources: {},
    layers: [{id: "background", type: "background", paint: {"background-color": "#dfe9e4"}}]
  };
  const PIPELINE_DESCRIPTIONS = {
    scientific_idw: "IDW preserves exact station values, uses projected regional distances, masks the boundary, and linearly interpolates adjacent spatial surfaces.",
    scientific_kde: "KDE applies a Gaussian kernel-weighted mean using the selected kilometre bandwidth, masks the boundary, and linearly interpolates adjacent spatial surfaces."
  };
  const state = {
    dataset: null,
    surfaces: null,
    currentTimestamp: null,
    currentView: "stations",
    boundaryPath: "/static/data/export.geojson",
    boundary: null,
    mapAvailable: false,
    mapReason: "Map capability has not been checked.",
    mapRenderer: "Unavailable",
    videoUrl: null,
    configuration: null
  };
  const element = id => document.getElementById(id);
  let map = null;
  let statusQueue = [];

  function status(message, type = "", duration = 5000) {
    const node = element("status-container");
    const entry = { message, type, timestamp: Date.now() };
    statusQueue.push(entry);

    // Show current message
    node.textContent = message;
    node.className = `status-container ${type}`.trim();
    node.setAttribute("role", type === "error" ? "alert" : "status");

    // Auto-clear after duration (unless it's an error or warning)
    if (type === "success" || type === "") {
      setTimeout(() => {
        statusQueue = statusQueue.filter(e => e.timestamp !== entry.timestamp);
        if (statusQueue.length === 0) {
          node.textContent = "";
          node.className = "status-container";
        } else {
          const latest = statusQueue[statusQueue.length - 1];
          node.textContent = latest.message;
          node.className = `status-container ${latest.type}`.trim();
        }
      }, duration);
    }
  }

  function busy(active) {
    element("loading-overlay").hidden = !active;
  }

  async function responseJson(response) {
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.error || `Request failed (${response.status}).`);
    return payload;
  }

  function detectMapCapability() {
    if (!window.maplibregl) {
      return {available: false, renderer: "MapLibre unavailable", reason: "The local MapLibre asset did not load."};
    }
    const canvas = document.createElement("canvas");
    const context = canvas.getContext("webgl2", {failIfMajorPerformanceCaveat: true});
    if (!context) {
      return {
        available: false,
        renderer: "No hardware WebGL2 context",
        reason: "The interactive map is disabled because hardware WebGL2 is unavailable. IDW/KDE generation and image display remain available on the server CPU."
      };
    }
    const debug = context.getExtension("WEBGL_debug_renderer_info");
    const renderer = debug ? context.getParameter(debug.UNMASKED_RENDERER_WEBGL) : "Hardware WebGL2 renderer (identity protected)";
    context.getExtension("WEBGL_lose_context")?.loseContext();
    return {available: true, renderer, reason: "Hardware WebGL2 is available for the map canvas. IDW/KDE calculations still run on the server CPU."};
  }

  function applyMapCapability(capability) {
    state.mapAvailable = capability.available;
    state.mapReason = capability.reason;
    state.mapRenderer = capability.renderer;
    element("gpu-status").textContent = capability.available ? "WebGL2 available" : "WebGL2 unavailable";
    element("gpu-status").className = capability.available ? "capability-ok" : "capability-off";
    element("gpu-renderer").textContent = capability.renderer;
    element("gpu-pipelines").textContent = capability.available ? "Enabled" : "Disabled";
    element("gpu-pipelines").className = capability.available ? "capability-ok" : "capability-off";
    element("gpu-reason").textContent = capability.reason;
    element("view-markers-btn").disabled = !capability.available;
  }

  function datasetParameter() {
    return element("parameter-select").value;
  }

  function filteredObservations() {
    if (!state.dataset) return [];
    return state.dataset.data.filter(row => row.parameter === datasetParameter());
  }

  function setDataset(payload) {
    state.dataset = payload;
    state.surfaces = null;
    const parameters = [...new Set(payload.data.map(row => row.parameter))].sort();
    element("parameter-select").innerHTML = parameters.length === 0 
      ? '<option disabled selected>No parameters found in dataset.</option>'
      : parameters.map(value => `<option>${escapeHtml(value)}</option>`).join("");
    populateTimestamps();
    drawStations();
    status(`${payload.total_records.toLocaleString()} validated observations loaded.`, "success");
  }

  function escapeHtml(value) {
    const span = document.createElement("span");
    span.textContent = String(value);
    return span.innerHTML;
  }

  function populateTimestamps() {
    const timestamps = [...new Set(filteredObservations().map(row => row.timestamp))].sort();
    if (timestamps.length === 0) {
      element("timestamp-select").innerHTML = '<option disabled selected>No timestamps available. Select a parameter above.</option>';
    } else {
      element("timestamp-select").innerHTML = timestamps.map(value => `<option value="${escapeHtml(value)}">${escapeHtml(value)}</option>`).join("");
    }
    state.currentTimestamp = timestamps[0] || null;
  }

  function currentRows() {
    return filteredObservations().filter(row => row.timestamp === state.currentTimestamp);
  }

  function stationGeoJson(rows) {
    return {
      type: "FeatureCollection",
      features: rows.map(row => ({
        type: "Feature",
        geometry: {type: "Point", coordinates: [Number(row.longitude), Number(row.latitude)]},
        properties: {value: Number(row.value), parameter: row.parameter}
      }))
    };
  }

  function drawStations() {
    if (!map || !state.dataset || !state.currentTimestamp) return;
    const data = stationGeoJson(currentRows());
    const source = map.getSource("stations");
    if (source) source.setData(data);
    else {
      map.addSource("stations", {type: "geojson", data});
      map.addLayer({
        id: "station-points",
        type: "circle",
        source: "stations",
        paint: {
          "circle-radius": 6,
          "circle-color": "#087f5b",
          "circle-stroke-color": "#ffffff",
          "circle-stroke-width": 1.5
        }
      });
      // Add tooltip on hover
      const popup = new maplibregl.Popup({closeButton: false, closeOnClick: false});
      map.on("mouseenter", "station-points", e => {
        map.getCanvas().style.cursor = "pointer";
        if (!e.features || e.features.length === 0) return;
        const feature = e.features[0];
        const props = feature.properties || {};
        popup.setLngLat(e.lngLat)
          .setHTML(`<div style="font-size:12px"><strong>${escapeHtml(props.parameter || "Parameter")}</strong><br>Value: ${Number(props.value).toPrecision(4)}<br>Time: ${escapeHtml(state.currentTimestamp)}</div>`)
          .addTo(map);
      });
      map.on("mouseleave", "station-points", () => {
        map.getCanvas().style.cursor = "";
        popup.remove();
      });
      // Add click interaction for potential cross-highlight (extensible for future data-entry grid link)
      map.on("click", "station-points", e => {
        if (!e.features || e.features.length === 0) return;
        const feature = e.features[0];
        const coords = feature.geometry.coordinates;
        status(`Station at (${Number(coords[0]).toFixed(4)}, ${Number(coords[1]).toFixed(4)}) selected.`, "success");
      });
    }
    setLayerVisibility();
  }

  function setLayerVisibility() {
    if (!map) return;
    if (map.getLayer("station-points")) {
      map.setLayoutProperty("station-points", "visibility", state.currentView === "stations" ? "visible" : "none");
    }
    if (map.getLayer("scientific-surface")) {
      map.setLayoutProperty("scientific-surface", "visibility", state.currentView === "heatmap" ? "visible" : "none");
    }
  }

  function coordinates(geometry, output = []) {
    if (!geometry) return output;
    const visit = value => {
      if (Array.isArray(value) && value.length >= 2 && Number.isFinite(value[0]) && Number.isFinite(value[1])) output.push(value);
      else if (Array.isArray(value)) value.forEach(visit);
    };
    visit(geometry.coordinates);
    return output;
  }

  async function loadBoundary(path) {
    const response = await fetch(path);
    if (!response.ok) throw new Error("Boundary could not be loaded.");
    state.boundary = await response.json();
    if (!map) return;
    const source = map.getSource("study-boundary");
    if (source) source.setData(state.boundary);
    else {
      map.addSource("study-boundary", {type: "geojson", data: state.boundary});
      map.addLayer({id: "boundary-fill", type: "fill", source: "study-boundary", paint: {"fill-color": "#087f5b", "fill-opacity": 0.04}});
      map.addLayer({id: "boundary-line", type: "line", source: "study-boundary", paint: {"line-color": "#075f46", "line-width": 2}});
    }
    const feature = state.boundary.type === "FeatureCollection" ? state.boundary.features[0] : state.boundary;
    const points = coordinates(feature.type === "Feature" ? feature.geometry : feature);
    if (points.length) {
      const bounds = points.reduce((box, point) => box.extend(point), new maplibregl.LngLatBounds(points[0], points[0]));
      map.fitBounds(bounds, {padding: 35, duration: 0});
    }
  }

  async function uploadDataset(file) {
    if (!file) throw new Error("Select a CSV or Excel file first.");
    const body = new FormData();
    body.append("file", file);
    busy(true);
    try { setDataset(await responseJson(await fetch("/upload", {method: "POST", body}))); }
    finally { busy(false); }
  }

  async function loadDemo() {
    busy(true);
    try { setDataset(await responseJson(await fetch("/api/demo"))); }
    finally { busy(false); }
  }

  async function loadDatabaseTable() {
    busy(true);
    try { 
      setDataset(await responseJson(await fetch("/api/export-dataset", {method: "POST"})));
    }
    finally { busy(false); }
  }

  async function loadLastDataEntrySession() {
    // Check if there's data from a recent data-entry save
    const lastDataStr = sessionStorage.getItem('trendsmapp_last_dataset');
    if (!lastDataStr) return false;
    
    try {
      const lastData = JSON.parse(lastDataStr);
      if (!Array.isArray(lastData.data) || lastData.data.length === 0) return false;
      
      // Construct a dataset payload from the imported data
      const observations = lastData.data;
      const payload = {
        message: lastData.message || 'Data imported from table editor.',
        data: observations,
        stats: {
          total_points: observations.length,
          parameter_count: [...new Set(observations.map(o => o.parameter))].length,
          timestamps: [...new Set(observations.map(o => o.timestamp))].sort(),
        },
        total_records: observations.length,
        global_min: Math.min(...observations.map(o => Number(o.value))),
        global_max: Math.max(...observations.map(o => Number(o.value))),
        timestamp_columns: [...new Set(observations.map(o => o.timestamp))].sort(),
        filename: 'data_entry_import',
        original_filename: 'data-entry-table-import.csv',
      };
      
      setDataset(payload);
      status(`Loaded ${observations.length} observations from data-entry table. Ready to analyze.`, "success");
      
      // Clear the session storage after loading
      sessionStorage.removeItem('trendsmapp_last_dataset');
      return true;
    } catch (error) {
      console.error('Failed to parse last dataset:', error);
      return false;
    }
  }

  async function uploadBoundary() {
    const file = element("boundary-file-input").files[0];
    if (!file) throw new Error("Select a GeoJSON boundary first.");
    const body = new FormData();
    body.append("file", file);
    busy(true);
    try {
      const payload = await responseJson(await fetch("/upload-boundary", {method: "POST", body}));
      state.boundaryPath = payload.path;
      await loadBoundary(payload.path);
      state.surfaces = null;
      status("Boundary validated. Regenerate surfaces for the new domain.", "success");
    } finally { busy(false); }
  }

  function selectedMethod() {
    return element("method-select").value;
  }

  function updateMethodControls() {
    const isKde = selectedMethod() === "kde";
    element("idw-power-control").hidden = isKde;
    element("kde-bandwidth-control").hidden = !isKde;
  }

  async function generateScientificSurfaces() {
    if (!state.dataset) throw new Error("Load observations first.");
    const rows = filteredObservations();
    const trigger = element("generate-button");
    trigger.disabled = true;
    busy(true);
    try {
      state.surfaces = await responseJson(await fetch("/generate-heatmap", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({
          data: rows,
          parameter: datasetParameter(),
          timestamp_columns: [...new Set(rows.map(row => row.timestamp))].sort(),
          global_min: Math.min(...rows.map(row => Number(row.value))),
          global_max: Math.max(...rows.map(row => Number(row.value))),
          method: selectedMethod(),
          idw_power: Number(element("idw-power-input").value),
          kde_bandwidth_km: Number(element("kde-bandwidth-input").value),
          colormap: element("colormap-select").value,
          boundary_path: state.boundaryPath
        })
      }));
      state.currentView = "heatmap";
      displayScientificSurface();
      updateViewButtons();
      updateLegend();
      status(`${state.surfaces.method.toUpperCase()} scientific surfaces generated on the server CPU.`, "success");
    } finally { busy(false); trigger.disabled = false; }
  }

  function scientificImageUrl() {
    const encoded = state.surfaces?.images?.[state.currentTimestamp];
    return encoded ? `data:image/png;base64,${encoded}` : null;
  }

  function displayScientificSurface() {
    const imageUrl = scientificImageUrl();
    if (!imageUrl) return;
    if (!map) {
      const container = element("map");
      container.className = "map-fallback scientific-image-fallback";
      container.innerHTML = "";
      const image = document.createElement("img");
      image.src = imageUrl;
      image.alt = `${state.surfaces.method.toUpperCase()} scientific surface for ${state.currentTimestamp}`;
      container.appendChild(image);
      return;
    }
    if (map.getLayer("scientific-surface")) map.removeLayer("scientific-surface");
    if (map.getSource("scientific-surface")) map.removeSource("scientific-surface");
    const [[minLon, minLat], [maxLon, maxLat]] = state.surfaces.bounds;
    map.addSource("scientific-surface", {
      type: "image",
      url: imageUrl,
      coordinates: [[minLon, maxLat], [maxLon, maxLat], [maxLon, minLat], [minLon, minLat]]
    });
    const layer = {id: "scientific-surface", type: "raster", source: "scientific-surface", paint: {"raster-opacity": Number(element("opacity-slider").value)}};
    if (map.getLayer("boundary-line")) map.addLayer(layer, "boundary-line");
    else map.addLayer(layer);
    setLayerVisibility();
  }

  function updateLegend() {
    if (!state.surfaces || !state.currentTimestamp) return;
    const params = new URLSearchParams({
      min: String(state.surfaces.global_min),
      max: String(state.surfaces.global_max),
      colormap: element("colormap-select").value
    });
    const gradient = element("legend-gradient");
    gradient.innerHTML = "";
    const image = document.createElement("img");
    image.src = `/legend/${encodeURIComponent(state.currentTimestamp)}.png?${params}`;
    image.alt = `${datasetParameter()} ${state.surfaces.method.toUpperCase()} colorbar`;
    gradient.appendChild(image);
    element("legend-title").textContent = `${datasetParameter()} (${state.surfaces.method.toUpperCase()})`;
    element("legend-min").textContent = Number(state.surfaces.global_min).toPrecision(4);
    element("legend-max").textContent = Number(state.surfaces.global_max).toPrecision(4);
    element("map-legend").hidden = false;
  }

  function updateViewButtons() {
    element("view-markers-btn").classList.toggle("active", state.currentView === "stations");
    element("view-heatmap-btn").classList.toggle("active", state.currentView === "heatmap");
  }

  function setView(view) {
    if (view === "stations" && !map) throw new Error(`Station map unavailable. ${state.mapReason}`);
    if (view === "heatmap" && !state.surfaces) throw new Error("Generate an IDW or KDE surface first.");
    state.currentView = view;
    if (view === "heatmap") displayScientificSurface();
    else drawStations();
    setLayerVisibility();
    updateViewButtons();
  }

  function updateAnimationPipeline() {
    const pipeline = element("animation-pipeline-select").value;
    element("animation-pipeline-description").textContent = PIPELINE_DESCRIPTIONS[pipeline];
    const method = pipeline === "scientific_kde" ? "KDE" : "IDW";
    element("run-animation-btn").textContent = `Generate scientific ${method} MP4`;
    element("method-select").value = method.toLowerCase();
    updateMethodControls();
  }

  async function exportVideo() {
    if (!state.dataset) throw new Error("Load observations first.");
    const rows = filteredObservations();
    const timestamps = [...new Set(rows.map(row => row.timestamp))].sort();
    if (timestamps.length < 2) throw new Error("MP4 export requires at least two timestamps.");
    const method = element("animation-pipeline-select").value === "scientific_kde" ? "kde" : "idw";
    const trigger = element("run-animation-btn");
    trigger.disabled = true;
    busy(true);
    try {
      const response = await fetch("/api/animate", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({
          parameter: datasetParameter(), start_date: timestamps[0], end_date: timestamps.at(-1),
          fps: Number(element("animation-fps").value),
          frames_per_transition: Number(element("frames-per-transition").value),
          filename: state.dataset.filename, boundary_path: state.boundaryPath,
          colormap: element("colormap-select").value, method,
          idw_power: Number(element("idw-power-input").value),
          kde_bandwidth_km: Number(element("kde-bandwidth-input").value),
          temporal_method: "linear_surface_interpolation"
        })
      });
      if (!response.ok) throw new Error((await response.json().catch(() => ({}))).error || "Animation export failed.");
      if (state.videoUrl) URL.revokeObjectURL(state.videoUrl);
      state.videoUrl = URL.createObjectURL(await response.blob());
      element("generated-video").src = state.videoUrl;
      element("generated-video").hidden = false;
      element("download-video").href = state.videoUrl;
      element("download-video").hidden = false;
      status(`Scientific ${method.toUpperCase()} animation exported.`, "success");
    } finally { busy(false); trigger.disabled = false; }
  }

  async function captureBlob() {
    const imageUrl = scientificImageUrl();
    if (state.currentView === "heatmap" && imageUrl) return (await fetch(imageUrl)).blob();
    if (!map) throw new Error(`Map capture unavailable. ${state.mapReason}`);
    return new Promise((resolve, reject) => map.getCanvas().toBlob(blob => blob ? resolve(blob) : reject(new Error("Map capture failed.")), "image/png"));
  }

  async function copyMap() {
    const blob = await captureBlob();
    if (!navigator.clipboard || !window.ClipboardItem) throw new Error("This browser does not support image clipboard access.");
    await navigator.clipboard.write([new ClipboardItem({"image/png": blob})]);
    status("Image copied to the clipboard.", "success");
  }

  async function downloadMap() {
    const url = URL.createObjectURL(await captureBlob());
    const link = document.createElement("a");
    link.href = url;
    link.download = state.currentView === "heatmap" ? `trendsmapp-${state.surfaces.method}.png` : "trendsmapp-map.png";
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  function safely(action) {
    return async event => {
      event?.preventDefault?.();
      try { await action(); }
      catch (error) { status(error.message || "Unexpected error.", "error"); busy(false); }
    };
  }

  function bindControls() {
    element("file-input").addEventListener("change", () => {
      const file = element("file-input").files[0];
      element("file-name").textContent = file ? file.name : "No local file selected.";
      element("upload-button").disabled = !file;
    });
    element("boundary-file-input").addEventListener("change", () => {
      const file = element("boundary-file-input").files[0];
      element("boundary-file-name").textContent = file ? file.name : "Bundled Chilika boundary.";
    });
    element("upload-button").addEventListener("click", safely(() => uploadDataset(element("file-input").files[0])));
    element("load-demo-button").addEventListener("click", safely(loadDemo));
    element("load-database-button").addEventListener("click", safely(loadDatabaseTable));
    element("upload-boundary-button").addEventListener("click", safely(uploadBoundary));
    element("open-data-entry").addEventListener("click", () => { window.location.href = "/data-entry"; });
    element("generate-button").addEventListener("click", safely(generateScientificSurfaces));
    element("method-select").addEventListener("change", updateMethodControls);
    element("animation-pipeline-select").addEventListener("change", updateAnimationPipeline);
    element("run-animation-btn").addEventListener("click", safely(exportVideo));
    element("copy-map-btn").addEventListener("click", safely(copyMap));
    element("download-map-btn").addEventListener("click", safely(downloadMap));
    element("parameter-select").addEventListener("change", () => { state.surfaces = null; populateTimestamps(); drawStations(); });
    element("timestamp-select").addEventListener("change", event => {
      state.currentTimestamp = event.target.value;
      if (state.currentView === "heatmap") displayScientificSurface();
      else drawStations();
    });
    element("view-markers-btn").addEventListener("click", safely(() => setView("stations")));
    element("view-heatmap-btn").addEventListener("click", safely(() => setView("heatmap")));
    element("opacity-slider").addEventListener("input", () => {
      element("opacity-value").textContent = Number(element("opacity-slider").value).toFixed(2);
      if (map?.getLayer("scientific-surface")) map.setPaintProperty("scientific-surface", "raster-opacity", Number(element("opacity-slider").value));
    });
    element("colormap-select").addEventListener("change", () => {
      state.surfaces = null;
      element("map-legend").hidden = true;
      status("Color scheme changed. Regenerate the scientific surfaces.");
    });
  }

  async function initializeMap() {
    map = new maplibregl.Map({container: "map", style: EMPTY_STYLE, center: [85.3, 19.6], zoom: 8, preserveDrawingBuffer: true});
    map.addControl(new maplibregl.NavigationControl(), "top-right");
    await new Promise((resolve, reject) => {
      const timeout = setTimeout(() => reject(new Error("Map initialization timed out.")), 10000);
      map.once("load", () => { clearTimeout(timeout); resolve(); });
      map.once("error", event => {
        if (!map.loaded()) { clearTimeout(timeout); reject(new Error(event.error?.message || "Map initialization failed.")); }
      });
    });
    await loadBoundary(state.boundaryPath);
  }

  async function initializeApplication() {
    bindControls();
    updateMethodControls();
    updateAnimationPipeline();
    try {
      state.configuration = await responseJson(await fetch("/api/config"));
      element("load-demo-button").hidden = !state.configuration.demo_mode;
      const capability = detectMapCapability();
      applyMapCapability(capability);
      if (capability.available) {
        try { await initializeMap(); }
        catch (error) {
          map?.remove();
          map = null;
          applyMapCapability({available: false, renderer: capability.renderer, reason: `Interactive map initialization failed: ${error.message}. IDW/KDE image generation remains available.`});
          element("map").className = "map-fallback";
          element("map").textContent = state.mapReason;
        }
      } else {
        element("map").className = "map-fallback";
        element("map").textContent = capability.reason;
      }
      // Try to auto-load data from data-entry page
      const loadedFromSession = await loadLastDataEntrySession();
      if (!loadedFromSession && state.configuration.demo_mode) {
        await loadDemo();
      }
    } catch (error) {
      status(error.message || "Application initialization failed.", "error");
    }
  }

  initializeApplication();
}());
