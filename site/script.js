function arrangeStorySections() {
  const article = document.querySelector("#edited-article");
  if (!article) return;

  const sequence = [
    ".story-header",
    ".story-intro",
    ".story-summary",
    ".story-takeaways",
    ".story-speed",
    ".story-speed-figure",
    ".story-slots",
    ".story-slots-figure",
    ".story-components",
    ".story-components-figure",
    ".story-subjects",
    ".story-subjects-figure",
    ".story-enrollment",
    ".story-enrollment-figure",
    ".story-course-cases",
    ".story-survey",
    ".story-planning",
    ".story-history",
    ".story-bicycle",
    ".story-bicycle-figure",
    ".story-campus",
    ".story-cdf",
    ".story-campus-map",
    ".story-route",
    ".story-counting",
    ".story-methods",
  ];
  sequence.forEach((selector) => {
    const section = article.querySelector(selector);
    if (section) article.append(section);
  });
}

arrangeStorySections();

const progress = document.querySelector(".reading-progress span");

function updateProgress() {
  if (!progress) return;
  const scrollable = document.documentElement.scrollHeight - window.innerHeight;
  const ratio = scrollable > 0 ? window.scrollY / scrollable : 0;
  progress.style.width = `${Math.min(1, Math.max(0, ratio)) * 100}%`;
}

const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
const reveals = document.querySelectorAll(".reveal");

if (reducedMotion || !("IntersectionObserver" in window)) {
  reveals.forEach((element) => element.classList.add("is-visible"));
} else {
  const observer = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          entry.target.classList.add("is-visible");
          observer.unobserve(entry.target);
        }
      });
    },
    { rootMargin: "0px 0px -8%", threshold: 0.08 },
  );
  reveals.forEach((element) => observer.observe(element));
}

window.addEventListener("scroll", updateProgress, { passive: true });
window.addEventListener("resize", updateProgress);
updateProgress();

const SVG_NAMESPACE = "http://www.w3.org/2000/svg";
const MAP_WIDTH = 1000;
const MAP_HEIGHT = 620;
const TEN_MINUTES = 10;

function createSvgElement(tag, attributes = {}) {
  const element = document.createElementNS(SVG_NAMESPACE, tag);
  Object.entries(attributes).forEach(([name, value]) => {
    element.setAttribute(name, String(value));
  });
  return element;
}

function routeKey(left, right, directional) {
  return directional ? `${left}|${right}` : [left, right].sort().join("|");
}

function formatMinutes(value) {
  return `${value.toFixed(1)} min`;
}

function initializeRouteLab(lab) {
  const elements = {
    origin: lab.querySelector("#route-origin"),
    destination: lab.querySelector("#route-destination"),
    swap: lab.querySelector("#swap-route"),
    modeFieldset: lab.querySelector(".mode-control"),
    modeButtons: [...lab.querySelectorAll("[data-mode]")],
    speedFieldset: lab.querySelector(".speed-control"),
    speedButtons: [...lab.querySelectorAll("[data-speed]")],
    speedLabel: lab.querySelector("#speed-control-label"),
    overhead: lab.querySelector("#building-overhead"),
    overheadLabel: lab.querySelector("#overhead-label"),
    result: lab.querySelector(".route-result"),
    resultContext: lab.querySelector("#route-result-context"),
    resultTime: lab.querySelector("#route-result-time"),
    resultVerdict: lab.querySelector("#route-result-verdict"),
    distance: lab.querySelector("#route-distance"),
    margin: lab.querySelector("#route-margin"),
    status: lab.querySelector("#route-status"),
    map: lab.querySelector("#route-map"),
    mapTitle: lab.querySelector("#route-map-title"),
    mapDescription: lab.querySelector("#route-map-description"),
    facilities: lab.querySelector("#map-facilities"),
    endpoints: lab.querySelector("#map-endpoints"),
    route: lab.querySelector("#map-route"),
    routeShadow: lab.querySelector("#map-route-shadow"),
    scenarios: lab.querySelector("#scenario-grid"),
  };

  const state = {
    data: null,
    facilitiesById: new Map(),
    mode: "walk",
    speed: 3,
    overhead: 0,
  };

  function modeMetadata() {
    return state.data.modes[state.mode];
  }

  function routeForSelection() {
    const originId = elements.origin.value;
    const destinationId = elements.destination.value;
    const mode = modeMetadata();
    const key = routeKey(originId, destinationId, mode.directional_routes);
    const stored = state.data.routes[state.mode][key];
    if (!stored) return null;
    const storedOrigin = key.split("|")[0];
    const path =
      mode.directional_routes || originId === storedOrigin
        ? stored.path
        : [...stored.path].reverse();
    return {
      ...stored,
      path,
      origin: state.facilitiesById.get(originId),
      destination: state.facilitiesById.get(destinationId),
    };
  }

  function mapProjection(path) {
    const referenceLatitude = path.reduce((sum, point) => sum + point[1], 0) / path.length;
    const longitudeScale = 111320 * Math.cos((referenceLatitude * Math.PI) / 180);
    const projected = path.map(([longitude, latitude]) => [
      longitude * longitudeScale,
      -latitude * 111320,
    ]);
    let minimumX = Math.min(...projected.map((point) => point[0]));
    let maximumX = Math.max(...projected.map((point) => point[0]));
    let minimumY = Math.min(...projected.map((point) => point[1]));
    let maximumY = Math.max(...projected.map((point) => point[1]));
    let spanX = Math.max(220, maximumX - minimumX) * 1.28;
    let spanY = Math.max(160, maximumY - minimumY) * 1.28;
    const centerX = (minimumX + maximumX) / 2;
    const centerY = (minimumY + maximumY) / 2;
    const targetAspect = MAP_WIDTH / MAP_HEIGHT;
    if (spanX / spanY > targetAspect) spanY = spanX / targetAspect;
    else spanX = spanY * targetAspect;
    minimumX = centerX - spanX / 2;
    maximumX = centerX + spanX / 2;
    minimumY = centerY - spanY / 2;
    maximumY = centerY + spanY / 2;

    function project([longitude, latitude]) {
      const xMeters = longitude * longitudeScale;
      const yMeters = -latitude * 111320;
      return [
        ((xMeters - minimumX) / (maximumX - minimumX)) * MAP_WIDTH,
        ((yMeters - minimumY) / (maximumY - minimumY)) * MAP_HEIGHT,
      ];
    }

    function contains(point) {
      const [x, y] = project(point);
      return x >= 0 && x <= MAP_WIDTH && y >= 0 && y <= MAP_HEIGHT;
    }

    return { project, contains };
  }

  function addEndpoint(group, point, label, className, anchor) {
    const [x, y] = point;
    const circle = createSvgElement("circle", { cx: x, cy: y, r: 16, class: className });
    const text = createSvgElement("text", {
      x: anchor === "start" ? x + 24 : x - 24,
      y: y - 22,
      class: "map-label",
      "text-anchor": anchor,
    });
    text.textContent = label;
    group.append(circle, text);
  }

  function renderMap(route) {
    const projection = mapProjection(route.path);
    const screenPoints = route.path.map(projection.project);
    const pathData = screenPoints
      .map(([x, y], index) => `${index ? "L" : "M"}${x.toFixed(1)},${y.toFixed(1)}`)
      .join(" ");
    elements.route.setAttribute("d", pathData);
    elements.routeShadow.setAttribute("d", pathData);
    elements.facilities.replaceChildren();
    state.data.facilities.forEach((facility) => {
      const coordinates = [facility.longitude, facility.latitude];
      if (!projection.contains(coordinates)) return;
      const [x, y] = projection.project(coordinates);
      const circle = createSvgElement("circle", {
        cx: x,
        cy: y,
        r: 5,
        class: "map-facility",
      });
      const title = createSvgElement("title");
      title.textContent = facility.label;
      circle.append(title);
      elements.facilities.append(circle);
    });

    elements.endpoints.replaceChildren();
    addEndpoint(
      elements.endpoints,
      screenPoints[0],
      route.origin.label,
      "map-origin",
      "start",
    );
    addEndpoint(
      elements.endpoints,
      screenPoints.at(-1),
      route.destination.label,
      "map-destination",
      "end",
    );

    elements.mapTitle.textContent = `${route.origin.label} to ${route.destination.label}`;
    elements.mapDescription.textContent = `Estimated shortest ${modeMetadata().label.toLowerCase()} route on the modeled network from ${route.origin.label} to ${route.destination.label}.`;
  }

  function updateScenarios() {
    const cards = [10, 12, 15].map((passingPeriod) => {
      const scenario = state.data.scenarios.find(
        (candidate) =>
          candidate.passing_period_minutes === passingPeriod &&
          Number(candidate.walking_speed_mph) === 3 &&
          candidate.building_overhead_minutes === 0,
      );
      const card = document.createElement("article");
      const periodClass =
        passingPeriod === 10
          ? " current"
          : passingPeriod === 15
            ? " historical"
            : "";
      card.className = `scenario-card${periodClass}`;
      const label = document.createElement("span");
      label.textContent =
        passingPeriod === 15
          ? "15-minute historical-budget comparison"
          : `${passingPeriod}-minute passing period`;
      const value = document.createElement("strong");
      value.textContent = scenario ? `${(scenario.share_feasible * 100).toFixed(1)}%` : "--";
      const track = document.createElement("div");
      track.className = "scenario-track";
      const fill = document.createElement("span");
      fill.className = "scenario-fill";
      fill.style.width = scenario ? `${scenario.share_feasible * 100}%` : "0";
      track.append(fill);
      const detail = document.createElement("p");
      detail.textContent = scenario
        ? `${scenario.feasible_pairs.toLocaleString()} of ${scenario.total_pairs.toLocaleString()} potential pairings at 3 mph`
        : "Scenario unavailable";
      card.append(label, value, track, detail);
      return card;
    });
    elements.scenarios.replaceChildren(...cards);
  }

  function updateModeControls() {
    const mode = modeMetadata();
    lab.classList.toggle("bike-mode", state.mode === "bike");
    elements.modeButtons.forEach((button) => {
      const active = button.dataset.mode === state.mode;
      button.classList.toggle("active", active);
      button.setAttribute("aria-pressed", String(active));
    });
    elements.speedLabel.textContent = `${mode.label} speed scenario`;
    elements.speedButtons.forEach((button, index) => {
      const speed = Number(mode.speeds_mph[index]);
      button.dataset.speed = String(speed);
      button.textContent = `${speed} mph`;
      const active = speed === state.speed;
      button.classList.toggle("active", active);
      button.setAttribute("aria-pressed", String(active));
    });
    const strong = document.createElement("strong");
    strong.textContent = "Reserve two minutes";
    const detail = document.createTextNode(
      state.mode === "bike"
        ? " for bike handling and building transitions"
        : " for leaving and entering buildings",
    );
    elements.overheadLabel.replaceChildren(strong, detail);
  }

  function updateRoute() {
    const route = routeForSelection();
    const mode = modeMetadata();
    if (!route) {
      elements.resultContext.textContent = `No connected ${mode.label.toLowerCase()} route`;
      elements.resultTime.textContent = "--";
      elements.resultVerdict.textContent = "This facility pair is not connected in the saved network.";
      elements.distance.textContent = "--";
      elements.margin.textContent = "--";
      elements.status.textContent = "Choose another pair of facilities.";
      return;
    }

    const networkMinutes = route.distance_meters / (state.speed * 1609.344 / 60);
    const totalMinutes = networkMinutes + state.overhead;
    const margin = TEN_MINUTES - totalMinutes;
    const fits = margin >= 0;

    elements.result.classList.toggle("fits", fits);
    elements.resultContext.textContent = `${mode.label}: ${route.origin.label} to ${route.destination.label} at ${state.speed} mph`;
    elements.resultTime.textContent = formatMinutes(totalMinutes);
    elements.resultVerdict.textContent = fits
      ? `Modeled time fits inside ten minutes with ${Math.abs(margin).toFixed(1)} minutes to spare.`
      : `Modeled time exceeds the ten-minute window by ${Math.abs(margin).toFixed(1)} minutes.`;
    elements.distance.textContent = `${Math.round(route.distance_meters).toLocaleString()} m`;
    elements.margin.textContent = `${margin >= 0 ? "+" : "-"}${Math.abs(margin).toFixed(1)} min`;
    elements.status.textContent =
      state.mode === "bike"
        ? "Bicycle estimate follows mapped access and one-way tags; parking and walking the bike are not modeled."
        : "Walking estimate excludes indoor travel; facility-to-network connectors are not path-verified.";
    renderMap(route);
  }

  function populateFacilities() {
    const options = state.data.facilities.map((facility) => {
      const option = document.createElement("option");
      option.value = facility.id;
      option.textContent = facility.label;
      return option;
    });
    elements.origin.replaceChildren(...options.map((option) => option.cloneNode(true)));
    elements.destination.replaceChildren(...options);
    elements.origin.value = state.data.featured_route.origin_id;
    elements.destination.value = state.data.featured_route.destination_id;
    elements.origin.disabled = false;
    elements.destination.disabled = false;
    elements.swap.disabled = false;
    elements.modeFieldset.disabled = false;
    elements.speedFieldset.disabled = false;
    elements.overhead.disabled = false;
  }

  elements.origin.addEventListener("change", updateRoute);
  elements.destination.addEventListener("change", updateRoute);
  elements.swap.addEventListener("click", () => {
    const origin = elements.origin.value;
    elements.origin.value = elements.destination.value;
    elements.destination.value = origin;
    updateRoute();
  });
  elements.modeButtons.forEach((button) => {
    button.addEventListener("click", () => {
      state.mode = button.dataset.mode;
      state.speed = Number(modeMetadata().default_speed_mph);
      updateModeControls();
      updateRoute();
    });
  });
  elements.speedButtons.forEach((button) => {
    button.setAttribute("aria-pressed", String(button.classList.contains("active")));
    button.addEventListener("click", () => {
      state.speed = Number(button.dataset.speed);
      elements.speedButtons.forEach((candidate) => {
        const active = candidate === button;
        candidate.classList.toggle("active", active);
        candidate.setAttribute("aria-pressed", String(active));
      });
      updateRoute();
    });
  });
  elements.overhead.addEventListener("change", () => {
    state.overhead = elements.overhead.checked ? 2 : 0;
    updateRoute();
  });

  fetch(lab.dataset.source)
    .then((response) => {
      if (!response.ok) throw new Error(`Route data returned ${response.status}`);
      return response.json();
    })
    .then((data) => {
      state.data = data;
      state.facilitiesById = new Map(data.facilities.map((facility) => [facility.id, facility]));
      state.mode = data.featured_route.travel_mode;
      state.speed = Number(data.featured_route.speed_mph);
      state.overhead = Number(data.featured_route.building_overhead_minutes);
      populateFacilities();
      updateModeControls();
      updateScenarios();
      updateRoute();
    })
    .catch((error) => {
      elements.resultContext.textContent = "Interactive unavailable";
      elements.resultTime.textContent = "--";
      elements.resultVerdict.textContent = "The static findings remain available below.";
      elements.status.textContent = error.message;
      elements.scenarios.textContent = "Passing-period scenarios could not be loaded.";
    });
}

const routeLab = document.querySelector("#route-checker");
if (routeLab) initializeRouteLab(routeLab);
