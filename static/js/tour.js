(function () {
  "use strict";

  const STORAGE_KEY = "trendsmapp_tour_completed";
  const AUTO_START_DELAY_MS = 900;

  // Set this to an external "how to get a GeoJSON" tutorial URL when available.
  // While empty, the boundary step shows a disabled placeholder instead of a dead link.
  const GEOJSON_GUIDE_URL = "";

  const FORMAT_EXAMPLE = [
    "Long form (one row per observation):",
    "latitude,longitude,timestamp,value,parameter",
    "19.50,85.10,2024-01-01T00:00:00Z,2.1,chlorophyll",
    "",
    "Wide form (one column per date):",
    "latitude,longitude,2024-01-01,2024-02-01",
    "19.50,85.10,2.1,2.5",
  ].join("\n");

  const STEPS = [
    {
      target: ".control-panel header",
      title: "Welcome to Trendsmapp",
      body: () => [
        element("p", "This tool turns validated environmental monitoring tables into publication-ready spatial surfaces and MP4 animations. Everything scientific runs on the server CPU; your browser only displays results."),
        element("p", "Take the one-minute tour, or skip it - you can restart anytime with the button under the title."),
      ],
    },
    {
      target: "#card-load",
      title: "1. Load your observations",
      body: () => [
        element("p", "Upload the file you want to analyze as CSV, XLSX, or XLS (up to 100,000 observations). Coordinates must be explicit columns - positional guessing is never applied."),
        element("pre", FORMAT_EXAMPLE),
        element("p", "Aliases such as lat/lon or x/y are accepted; blank wide-format cells are treated as unsampled."),
      ],
    },
    {
      target: "#card-load .button-group",
      title: "Or start from existing data",
      body: () => [
        element("p", "\"Load example\" opens the bundled validation workbook instantly - no upload needed."),
        element("p", "\"Load saved table\" pulls measurements you entered on the Edit table page out of the database and makes them mappable."),
      ],
    },
    {
      target: "#card-boundary",
      title: "2. Set the study boundary",
      body: () => {
        const fragment = document.createDocumentFragment();
        fragment.appendChild(element("p", "Upload one GeoJSON Polygon or MultiPolygon that outlines your study area. Surfaces are computed on a grid and masked outside this shape."));
        if (GEOJSON_GUIDE_URL) {
          const link = document.createElement("a");
          link.href = GEOJSON_GUIDE_URL;
          link.target = "_blank";
          link.rel = "noopener noreferrer";
          link.className = "tour-link";
          link.textContent = "How to get or draw a GeoJSON \u2197";
          fragment.appendChild(link);
        } else {
          const placeholder = element("span", "External GeoJSON guide: link coming soon.");
          placeholder.className = "tour-muted";
          fragment.appendChild(placeholder);
        }
        return [fragment];
      },
    },
    {
      target: "#card-view",
      title: "3. Choose what you view",
      body: () => [
        element("p", "Switch between raw station markers and the interpolated scientific surface. Then pick the parameter, the timestamp, the estimator, and its parameters."),
        element("p", "The map needs WebGL2; without it, generated surfaces appear as ordinary images and every export still works."),
      ],
    },
    {
      target: "#method-select",
      title: "Scientific parameters explained",
      body: () => [
        element("p", "IDW power (0.1-5): how strongly nearby stations dominate. Low values blend broadly and smoothly; high values sharpen local peaks around stations."),
        element("p", "KDE bandwidth in kilometres (0.1-100): the radius of a Gaussian kernel-weighted mean. Small bandwidths keep local detail, large ones generalize across the region."),
      ],
    },
    {
      target: "#generate-button",
      title: "Generate the surface",
      body: () => [
        element("p", "One click computes an IDW or KDE surface on the server for the selected timestamp, masked to your boundary and colored with a fixed dataset-wide range so frames stay comparable."),
        element("p", "Color scheme and opacity restyle the overlay; the map legend is rendered from the exact matplotlib colorbar."),
      ],
    },
    {
      target: "#card-animation",
      title: "4. Animate over time",
      body: () => [
        element("p", "Pick a server pipeline (IDW or KDE), playback FPS, and transition frames per interval. Frames between observed dates are labelled \"Interpolated\" and distributed proportionally to real time gaps."),
        element("p", "The result downloads as an H.264 MP4 with method metadata embedded in the response headers."),
      ],
    },
    {
      target: "#open-data-entry",
      title: "Edit data as a spreadsheet",
      body: () => [
        element("p", "\"Edit table\" opens a grid editor backed by the database: add parameters and timestamps, paste from Excel, delete or rename series persistently."),
        element("p", "Saved rows flow back here through \"Load saved table\"."),
      ],
    },
    {
      target: "#card-capture",
      title: "Capture results",
      body: () => [
        element("p", "Copy the current view straight to the clipboard or download it as a PNG - handy for figures and slide decks."),
      ],
    },
    {
      target: null,
      title: "You are ready",
      body: () => [
        element("p", "That's the whole workflow: load validated data, define a boundary, generate IDW/KDE surfaces, animate them, and export publication assets."),
        element("p", "Restart this tour anytime with the button under the title."),
      ],
    },
  ];

  let active = false;
  let index = 0;
  let refs = null;
  let previousFocus = null;

  function element(tag, text) {
    const node = document.createElement(tag);
    node.textContent = text;
    return node;
  }

  function resolveTarget(selector) {
    if (!selector) return null;
    return document.querySelector(selector);
  }

  function markCompleted() {
    try { localStorage.setItem(STORAGE_KEY, "1"); } catch (error) { /* storage unavailable */ }
  }

  function hasCompletedTour() {
    try { return localStorage.getItem(STORAGE_KEY) === "1"; } catch (error) { return false; }
  }

  function buildInterface() {
    const root = document.getElementById("tour-root");
    while (root.firstChild) root.removeChild(root.firstChild);

    const clickCatcher = document.createElement("div");
    clickCatcher.className = "tour-click-catcher";

    const spotlight = document.createElement("div");
    spotlight.className = "tour-spotlight";

    const card = document.createElement("section");
    card.className = "tour-card";
    card.setAttribute("role", "dialog");
    card.setAttribute("aria-modal", "true");
    card.setAttribute("aria-labelledby", "tour-title");

    const headerRow = document.createElement("div");
    headerRow.className = "tour-header";
    const counter = element("span", "");
    counter.className = "tour-counter";
    const closeButton = element("button", "\u00d7");
    closeButton.type = "button";
    closeButton.className = "tour-close";
    closeButton.setAttribute("aria-label", "Skip tour");
    headerRow.appendChild(counter);
    headerRow.appendChild(closeButton);

    const titleNode = document.createElement("h3");
    titleNode.id = "tour-title";

    const bodyNode = document.createElement("div");
    bodyNode.className = "tour-body";

    const footer = document.createElement("div");
    footer.className = "tour-footer";
    const backButton = element("button", "Back");
    backButton.type = "button";
    backButton.className = "secondary tour-nav";
    const nextButton = element("button", "Next");
    nextButton.type = "button";
    nextButton.className = "tour-nav";
    const skipButton = element("button", "Skip tour");
    skipButton.type = "button";
    skipButton.className = "secondary tour-skip";
    footer.appendChild(backButton);
    footer.appendChild(nextButton);

    card.appendChild(headerRow);
    card.appendChild(titleNode);
    card.appendChild(bodyNode);
    card.appendChild(footer);
    card.appendChild(skipButton);

    root.appendChild(clickCatcher);
    root.appendChild(spotlight);
    root.appendChild(card);

    return { root, spotlight, card, counter, title: titleNode, body: bodyNode, back: backButton, next: nextButton, skip: skipButton, close: closeButton };
  }

  function placeCard(target) {
    const padding = 8;
    const margin = 14;
    const viewport = { width: window.innerWidth, height: window.innerHeight };

    if (!target) {
      refs.spotlight.style.display = "none";
      const cardRect = refs.card.getBoundingClientRect();
      refs.card.style.left = `${Math.max((viewport.width - cardRect.width) / 2, 12)}px`;
      refs.card.style.top = `${Math.max((viewport.height - cardRect.height) / 2, 12)}px`;
      return;
    }

    refs.spotlight.style.display = "";
    const rect = target.getBoundingClientRect();
    refs.spotlight.style.left = `${rect.left - padding}px`;
    refs.spotlight.style.top = `${rect.top - padding}px`;
    refs.spotlight.style.width = `${rect.width + padding * 2}px`;
    refs.spotlight.style.height = `${rect.height + padding * 2}px`;

    const cardSize = { width: refs.card.offsetWidth, height: refs.card.offsetHeight };
    const placements = [
      { left: rect.right + margin, top: rect.top + rect.height / 2 - cardSize.height / 2 },
      { left: rect.left, top: rect.bottom + margin },
      { left: rect.left, top: rect.top - cardSize.height - margin },
      { left: rect.left - cardSize.width - margin, top: rect.top + rect.height / 2 - cardSize.height / 2 },
    ];
    let chosen = placements.find(
      (spot) =>
        spot.left >= 12 &&
        spot.top >= 12 &&
        spot.left + cardSize.width <= viewport.width - 12 &&
        spot.top + cardSize.height <= viewport.height - 12
    );
    if (!chosen) chosen = placements[1];

    refs.card.style.left = `${Math.min(Math.max(chosen.left, 12), viewport.width - cardSize.width - 12)}px`;
    refs.card.style.top = `${Math.min(Math.max(chosen.top, 12), viewport.height - cardSize.height - 12)}px`;
  }

  function renderStep() {
    const step = STEPS[index];
    const target = resolveTarget(step.target);

    refs.counter.textContent = `Step ${index + 1} of ${STEPS.length}`;
    refs.title.textContent = step.title;
    while (refs.body.firstChild) refs.body.removeChild(refs.body.firstChild);
    step.body().forEach((node) => refs.body.appendChild(node));

    refs.back.disabled = index === 0;
    refs.next.textContent = index === STEPS.length - 1 ? "Finish" : "Next";
    refs.skip.classList.toggle("hidden", index === STEPS.length - 1);

    if (target && typeof target.scrollIntoView === "function") {
      const reduceMotion = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      target.scrollIntoView({ behavior: reduceMotion ? "auto" : "smooth", block: "nearest" });
    }
    requestAnimationFrame(() => placeCard(target));
    setTimeout(() => placeCard(target), 260);
    refs.next.focus({ preventScroll: true });
  }

  function go(delta) {
    const nextIndex = index + delta;
    if (nextIndex < 0 || nextIndex >= STEPS.length) {
      finish();
      return;
    }
    index = nextIndex;
    renderStep();
  }

  function finish() {
    active = false;
    markCompleted();
    document.removeEventListener("keydown", onKeyDown, true);
    window.removeEventListener("resize", reposition);
    window.removeEventListener("scroll", reposition, true);
    refs.root.hidden = true;
    while (refs.root.firstChild) refs.root.removeChild(refs.root.firstChild);
    refs = null;
    if (previousFocus && typeof previousFocus.focus === "function") previousFocus.focus();
  }

  function reposition() {
    if (!active || !refs) return;
    const target = resolveTarget(STEPS[index].target);
    placeCard(target);
  }

  function onKeyDown(event) {
    if (!active) return;
    if (event.key === "Escape") { event.preventDefault(); finish(); }
    else if (event.key === "ArrowRight") { event.preventDefault(); go(1); }
    else if (event.key === "ArrowLeft") { event.preventDefault(); go(-1); }
  }

  function start() {
    if (active) return;
    active = true;
    index = 0;
    previousFocus = document.activeElement;
    refs = buildInterface();
    refs.root.hidden = false;
    refs.next.addEventListener("click", () => go(1));
    refs.back.addEventListener("click", () => go(-1));
    refs.skip.addEventListener("click", finish);
    refs.close.addEventListener("click", finish);
    window.addEventListener("resize", reposition);
    window.addEventListener("scroll", reposition, true);
    document.addEventListener("keydown", onKeyDown, true);
    renderStep();
  }

  window.TrendsmappTour = { start };

  document.addEventListener("DOMContentLoaded", () => {
    const trigger = document.getElementById("start-tour-button");
    if (trigger) trigger.addEventListener("click", start);
    if (!hasCompletedTour()) {
      window.setTimeout(start, AUTO_START_DELAY_MS);
    }
  });
}());
