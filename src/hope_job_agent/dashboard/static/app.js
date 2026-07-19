/* Kelley MSIS Career Intelligence — demo dashboard front end.
   Vanilla JS, no build step. All job data is rendered through
   createElement/textContent so posting content can never inject markup. */

"use strict";

const CONCENTRATION_VARS = ["--c1", "--c2", "--c3", "--c4", "--c5"];

const state = {
  track: "full_time",
  concentrations: new Set(),
  sources: new Set(),
  role: "",
  q: "",
  location: "",
  remote: false,
  sponsorship: false,
  sort: "recent",
  profile: null,
  offset: 0,
  limit: 24,
  total: 0,
  concentrationOrder: [],
  dbExists: true,
};

const el = (id) => document.getElementById(id);

/* ---------- theme ---------- */

function initTheme() {
  const saved = localStorage.getItem("hope-theme");
  if (saved === "light" || saved === "dark") {
    document.documentElement.dataset.theme = saved;
  }
  el("theme-toggle").addEventListener("click", () => {
    const root = document.documentElement;
    const isDark =
      root.dataset.theme === "dark" ||
      (!root.dataset.theme &&
        window.matchMedia("(prefers-color-scheme: dark)").matches);
    root.dataset.theme = isDark ? "light" : "dark";
    localStorage.setItem("hope-theme", root.dataset.theme);
  });
}

/* ---------- helpers ---------- */

function make(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = text;
  return node;
}

function hashHue(text) {
  let hash = 0;
  for (let i = 0; i < text.length; i += 1) {
    hash = (hash * 31 + text.charCodeAt(i)) >>> 0;
  }
  return hash % 360;
}

function initials(company) {
  const words = company.split(/\s+/).filter(Boolean);
  if (!words.length) return "?";
  return words
    .slice(0, 2)
    .map((word) => word[0].toUpperCase())
    .join("");
}

function relativeDate(iso) {
  if (!iso) return "date n/a";
  const posted = new Date(`${iso}T00:00:00`);
  const days = Math.floor((Date.now() - posted.getTime()) / 86400000);
  if (Number.isNaN(days)) return "date n/a";
  if (days <= 0) return "today";
  if (days === 1) return "yesterday";
  if (days < 7) return `${days}d ago`;
  if (days < 30) return `${Math.floor(days / 7)}w ago`;
  return `${Math.floor(days / 30)}mo ago`;
}

function concentrationColor(name) {
  const index = state.concentrationOrder.indexOf(name);
  return `var(${CONCENTRATION_VARS[index >= 0 ? index : 0]})`;
}

function debounce(fn, wait) {
  let timer = null;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), wait);
  };
}

async function fetchJSON(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`${url} -> HTTP ${response.status}`);
  return response.json();
}

function buildParams(extra = {}) {
  const params = new URLSearchParams();
  params.set("track", state.track);
  state.concentrations.forEach((value) => params.append("concentration", value));
  state.sources.forEach((value) => params.append("source", value));
  if (state.role) params.append("role", state.role);
  if (state.q) params.set("q", state.q);
  if (state.location) params.set("location", state.location);
  if (state.remote) params.set("remote", "true");
  if (state.sponsorship) params.set("sponsorship", "true");
  params.set("limit", String(state.limit));
  params.set("offset", String(state.offset));
  Object.entries(extra).forEach(([key, value]) => params.set(key, value));
  return params;
}

/* ---------- logo / monogram ---------- */

function logoBox(job) {
  const box = make("div", "logo-box");
  const monogram = make("div", "monogram", initials(job.company));
  monogram.style.setProperty("--mono-h", String(hashHue(job.company)));
  box.appendChild(monogram);
  if (job.company_logo) {
    const img = document.createElement("img");
    img.src = job.company_logo;
    img.alt = "";
    img.loading = "lazy";
    img.referrerPolicy = "no-referrer";
    img.addEventListener("error", () => img.remove());
    box.appendChild(img);
  }
  return box;
}

/* ---------- badges + chips ---------- */

function badgeRow(job) {
  const row = make("div", "badge-row");
  const sourceBadge = make(
    "span",
    job.source_badge === "LinkedIn" ? "badge src linkedin" : "badge src",
    job.source_badge
  );
  row.appendChild(sourceBadge);
  if (job.career_track === "internship") {
    row.appendChild(make("span", "badge intern", "Internship"));
  }
  if (job.opt_cpt_flag === true) {
    row.appendChild(make("span", "badge optcpt", "OPT/CPT friendly"));
  }
  if (job.location_type && job.location_type.toLowerCase().includes("remote")) {
    row.appendChild(make("span", "badge", "Remote"));
  }
  if (job.compensation) {
    row.appendChild(make("span", "badge comp", job.compensation));
  }
  return row;
}

function concentrationChips(job) {
  const row = make("div", "tag-row");
  job.concentration_tags.forEach((name, index) => {
    const chip = make("span", "conc-chip");
    const dot = make("span", "dot");
    dot.style.background = concentrationColor(name);
    chip.appendChild(dot);
    chip.appendChild(
      document.createTextNode(job.concentration_codes[index] || name)
    );
    chip.title = name;
    row.appendChild(chip);
  });
  return row;
}

/* ---------- cards ---------- */

function jobCard(job, match) {
  const card = make("article", "card");
  card.tabIndex = 0;
  card.setAttribute("role", "button");
  card.setAttribute("aria-label", `${job.title} at ${job.company}`);

  const top = make("div", "card-top");
  top.appendChild(logoBox(job));
  const heading = make("div", "card-heading");
  heading.appendChild(make("h3", "job-title", job.title));
  heading.appendChild(make("div", "job-company", job.company));
  top.appendChild(heading);
  if (match) {
    top.appendChild(make("span", "score-pill", match.score.toFixed(1)));
  }
  card.appendChild(top);

  const meta = make("div", "meta-row");
  meta.appendChild(make("span", null, `\u{1F4CD} ${job.location}`));
  meta.appendChild(make("span", null, `\u{1F552} ${relativeDate(job.posted_date)}`));
  if (job.seniority) meta.appendChild(make("span", null, job.seniority));
  card.appendChild(meta);

  card.appendChild(badgeRow(job));
  if (job.concentration_tags.length) card.appendChild(concentrationChips(job));

  if (match && match.reasons.length) {
    const reasons = make("div", "reasons");
    const list = make("ul");
    match.reasons.slice(0, 2).forEach((reason) => {
      list.appendChild(make("li", null, reason));
    });
    reasons.appendChild(list);
    card.appendChild(reasons);
  }

  const actions = make("div", "card-actions");
  actions.appendChild(make("span", "details-link", "View details →"));
  const apply = make("a", "apply-btn", "Apply ↗");
  apply.href = job.apply_url || job.url;
  apply.target = "_blank";
  apply.rel = "noopener noreferrer";
  apply.addEventListener("click", (event) => event.stopPropagation());
  actions.appendChild(apply);
  card.appendChild(actions);

  const open = () => openDrawer(job.job_key, match);
  card.addEventListener("click", open);
  card.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      open();
    }
  });
  return card;
}

/* ---------- drawer ---------- */

async function openDrawer(jobKey, match) {
  let job;
  try {
    job = await fetchJSON(`/api/jobs/${encodeURIComponent(jobKey)}`);
  } catch (error) {
    console.error(error);
    return;
  }
  const body = el("drawer-body");
  body.replaceChildren();

  const top = make("div", "drawer-top");
  top.appendChild(logoBox(job));
  const heading = make("div");
  heading.appendChild(make("h2", "drawer-title", job.title));
  heading.id = "drawer-title";
  heading.appendChild(make("div", "drawer-company", job.company));
  top.appendChild(heading);
  body.appendChild(top);

  const badges = make("div", "drawer-badges");
  badges.appendChild(badgeRow(job));
  if (job.concentration_tags.length) {
    const chips = concentrationChips(job);
    chips.style.marginTop = "6px";
    badges.appendChild(chips);
  }
  body.appendChild(badges);

  if (match) {
    const panel = make("div", "match-panel");
    panel.appendChild(
      make("h4", null, `Match score ${match.score.toFixed(1)} — why this role`)
    );
    const list = make("ul");
    match.reasons.forEach((reason) => list.appendChild(make("li", null, reason)));
    panel.appendChild(list);
    const breakdown = make("div", "breakdown");
    Object.entries(match.score_breakdown || {}).forEach(([key, value]) => {
      if (!value) return;
      breakdown.appendChild(
        make("span", "breakdown-chip", `${key.replaceAll("_", " ")} +${value}`)
      );
    });
    if (breakdown.children.length) panel.appendChild(breakdown);
    body.appendChild(panel);
  }

  const metaGrid = make("div", "meta-grid");
  const cells = [
    ["Location", job.location],
    ["Workplace", job.location_type],
    ["Employment", job.employment_type],
    ["Experience", job.seniority],
    ["Department", job.department],
    ["Sector", job.sector],
    ["Compensation", job.compensation],
    ["Posted", job.posted_date ? relativeDate(job.posted_date) : null],
    ["Source", job.source_badge],
    ["MSIS relevance", job.relevance_score != null ? `${job.relevance_score}` : null],
    ["Applicants", job.applications_count],
  ];
  cells.forEach(([key, value]) => {
    if (!value) return;
    const cell = make("div", "meta-cell");
    cell.appendChild(make("div", "k", key));
    cell.appendChild(make("div", "v", value));
    metaGrid.appendChild(cell);
  });
  body.appendChild(metaGrid);

  const desc = make("div", "drawer-desc");
  desc.appendChild(make("h4", null, "About this role"));
  job.description
    .split(/\n{2,}/)
    .filter((part) => part.trim())
    .forEach((part) => desc.appendChild(make("p", null, part.trim())));
  body.appendChild(desc);

  const actions = make("div", "drawer-actions");
  const apply = make("a", "apply-btn", "Apply on employer site ↗");
  apply.href = job.apply_url || job.url;
  apply.target = "_blank";
  apply.rel = "noopener noreferrer";
  actions.appendChild(apply);
  const original = make("a", "ghost-btn", "View original posting");
  original.href = job.url;
  original.target = "_blank";
  original.rel = "noopener noreferrer";
  original.style.textDecoration = "none";
  original.style.textAlign = "center";
  actions.appendChild(original);
  body.appendChild(actions);

  el("drawer").hidden = false;
  el("drawer-backdrop").hidden = false;
  el("drawer-close").focus();
}

function closeDrawer() {
  el("drawer").hidden = true;
  el("drawer-backdrop").hidden = true;
}

/* ---------- stats bar ---------- */

function renderStats(stats) {
  state.dbExists = stats.db_exists;
  el("statsbar").hidden = false;
  el("stat-total").textContent = stats.total_jobs;
  el("stat-companies").textContent = stats.company_count;
  el("stat-new").textContent = stats.new_this_week;
  el("stat-sponsor").textContent = stats.sponsorship_count;
  el("count-internship").textContent = stats.internship_count;
  el("count-full_time").textContent = stats.full_time_count;

  if (stats.latest_run) {
    const when = new Date(stats.latest_run.completed_at);
    el("updated-chip").textContent = `Updated ${when.toLocaleString([], {
      month: "short",
      day: "numeric",
      hour: "numeric",
      minute: "2-digit",
    })}`;
    el("footer-run").textContent =
      `Last pipeline run: ${stats.latest_run.source} · ` +
      `${stats.latest_run.unique_count} unique roles · ` +
      `rules-v0 classifier · deterministic-v0 ranker`;
  } else {
    el("updated-chip").textContent = "No pipeline runs yet";
  }

  const bar = el("conc-bar");
  const legend = el("conc-legend");
  bar.replaceChildren();
  legend.replaceChildren();
  const total = stats.by_concentration.reduce((sum, item) => sum + item.count, 0);
  stats.by_concentration.forEach((item) => {
    const seg = make("div", "conc-seg");
    seg.style.flexGrow = String(Math.max(item.count, total ? 0 : 1));
    seg.style.background = concentrationColor(item.name);
    seg.title = `${item.name}: ${item.count}`;
    bar.appendChild(seg);

    const legendBtn = make("button", "legend-item");
    legendBtn.type = "button";
    const swatch = make("span", "legend-swatch");
    swatch.style.background = concentrationColor(item.name);
    legendBtn.appendChild(swatch);
    legendBtn.appendChild(document.createTextNode(item.code || item.name));
    legendBtn.appendChild(make("span", "legend-count", String(item.count)));
    legendBtn.title = item.name;
    legendBtn.addEventListener("click", () => {
      toggleSetValue(state.concentrations, item.name);
      resetAndRefresh();
    });
    legend.appendChild(legendBtn);
  });

  const chips = el("source-chips");
  chips.replaceChildren();
  stats.by_source.forEach((item) => {
    const chip = make("button", "chip");
    chip.type = "button";
    chip.appendChild(document.createTextNode(item.name));
    chip.appendChild(make("span", "legend-count", String(item.count)));
    chip.addEventListener("click", () => {
      toggleSetValue(state.sources, item.name);
      resetAndRefresh();
    });
    chips.appendChild(chip);
  });
  syncActiveChips();
}

function toggleSetValue(set, value) {
  if (set.has(value)) set.delete(value);
  else set.add(value);
}

function syncActiveChips() {
  document.querySelectorAll("#conc-legend .legend-item").forEach((node) => {
    node.classList.toggle("active", state.concentrations.has(node.title));
  });
  document.querySelectorAll("#source-chips .chip").forEach((node) => {
    node.classList.toggle(
      "active",
      state.sources.has(node.firstChild.textContent)
    );
  });
}

/* ---------- facets / sidebar ---------- */

function renderFacets(facets) {
  const concBox = el("concentration-filters");
  concBox.replaceChildren();
  facets.concentrations.forEach((item) => {
    concBox.appendChild(
      checkRow({
        label: item.code || item.name,
        title: item.name,
        count: item.count,
        checked: state.concentrations.has(item.name),
        color: concentrationColor(item.name),
        onChange: () => {
          toggleSetValue(state.concentrations, item.name);
          resetAndRefresh();
        },
      })
    );
  });

  const sourceBox = el("source-filters");
  sourceBox.replaceChildren();
  facets.sources.forEach((item) => {
    sourceBox.appendChild(
      checkRow({
        label: item.name,
        title: item.name,
        count: item.count,
        checked: state.sources.has(item.name),
        onChange: () => {
          toggleSetValue(state.sources, item.name);
          resetAndRefresh();
        },
      })
    );
  });

  const roleSelect = el("role-filter");
  const current = state.role;
  roleSelect.replaceChildren(make("option", null, "All target roles"));
  roleSelect.firstChild.value = "";
  facets.roles.forEach((item) => {
    const option = make("option", null, `${item.name} (${item.count})`);
    option.value = item.name;
    roleSelect.appendChild(option);
  });
  roleSelect.value = current;
  if (roleSelect.value !== current) {
    state.role = "";
  }
  syncActiveChips();
}

function checkRow({ label, title, count, checked, color, onChange }) {
  const row = make("label", "check-row");
  row.title = title;
  const input = document.createElement("input");
  input.type = "checkbox";
  input.checked = checked;
  input.addEventListener("change", onChange);
  row.appendChild(input);
  if (color) {
    const dot = make("span", "dot");
    dot.style.background = color;
    row.appendChild(dot);
  }
  row.appendChild(make("span", null, label));
  row.appendChild(make("span", "count", String(count)));
  return row;
}

/* ---------- profiles ---------- */

function renderProfiles(profiles) {
  const list = el("profile-list");
  list.replaceChildren();

  const none = make("button", "profile-card active");
  none.type = "button";
  none.dataset.profile = "";
  none.appendChild(make("div", "profile-name", "Browse without a profile"));
  none.appendChild(make("div", "profile-meta", "Program-wide view, no ranking"));
  none.addEventListener("click", () => selectProfile(null));
  list.appendChild(none);

  profiles.forEach((profile) => {
    const cardBtn = make("button", "profile-card");
    cardBtn.type = "button";
    cardBtn.dataset.profile = profile.student_id;
    const nameRow = make("div", "profile-name", profile.name);
    if (profile.needs_cpt_opt) {
      nameRow.appendChild(make("span", "profile-badge", "needs CPT/OPT"));
    }
    cardBtn.appendChild(nameRow);
    cardBtn.appendChild(
      make(
        "div",
        "profile-meta",
        `${profile.concentration} · ${profile.academic_stage || "MSIS"}`
      )
    );
    cardBtn.addEventListener("click", () => selectProfile(profile.student_id));
    list.appendChild(cardBtn);
  });
}

function selectProfile(studentId) {
  state.profile = studentId;
  document.querySelectorAll(".profile-card").forEach((node) => {
    node.classList.toggle("active", (node.dataset.profile || null) === studentId);
  });
  el("sort-select").disabled = Boolean(studentId);
  resetAndRefresh();
}

/* ---------- results ---------- */

function renderResultMeta() {
  const meta = el("result-meta");
  meta.replaceChildren();
  const strong = make("strong", null, String(state.total));
  meta.appendChild(strong);
  const trackLabel =
    state.track === "internship" ? "internship roles" : "full-time roles";
  let suffix = ` ${trackLabel}`;
  if (state.profile) {
    suffix += " · ranked for the selected profile";
  } else if (state.sort === "recent") {
    suffix += " · newest first";
  } else if (state.sort === "relevance") {
    suffix += " · by MSIS relevance";
  } else {
    suffix += " · by company";
  }
  meta.appendChild(document.createTextNode(suffix));
}

function showEmptyState() {
  const empty = el("empty-state");
  empty.hidden = false;
  if (!state.dbExists) {
    el("empty-title").textContent = "No pipeline data yet";
    const body = el("empty-body");
    body.replaceChildren(
      document.createTextNode("Populate the local store first:"),
      make(
        "code",
        null,
        "python -m hope_job_agent.pipeline.run_mvp --source all --output outputs/demo.csv"
      )
    );
  } else {
    el("empty-title").textContent = "No matching roles";
    el("empty-body").textContent =
      "Try clearing a filter, broadening your search, or switching tracks.";
  }
}

async function refresh(append = false) {
  if (!append) {
    state.offset = 0;
  }
  const cards = el("cards");
  el("empty-state").hidden = true;

  try {
    let jobsWithMatches;
    if (state.profile) {
      const [matchData, jobData] = await Promise.all([
        fetchJSON(
          `/api/profiles/${encodeURIComponent(state.profile)}/matches?` +
            buildParams()
        ),
        fetchJSON(`/api/jobs?${buildParams({ limit: "1" })}`),
      ]);
      state.total = matchData.total;
      jobsWithMatches = matchData.matches.map((match) => [match.job, match]);
      renderFacets(jobData.facets);
    } else {
      const jobData = await fetchJSON(
        `/api/jobs?${buildParams({ sort: state.sort })}`
      );
      state.total = jobData.total;
      jobsWithMatches = jobData.jobs.map((job) => [job, null]);
      renderFacets(jobData.facets);
    }

    if (!append) cards.replaceChildren();
    jobsWithMatches.forEach(([job, match]) => {
      cards.appendChild(jobCard(job, match));
    });

    renderResultMeta();
    const shown = cards.children.length;
    el("load-more").hidden = shown >= state.total;
    if (!shown) showEmptyState();
  } catch (error) {
    console.error(error);
    el("result-meta").textContent =
      "Could not reach the dashboard API. Is uvicorn running?";
  }
}

function resetAndRefresh() {
  refresh(false);
}

/* ---------- wiring ---------- */

function initControls() {
  ["internship", "full_time"].forEach((track) => {
    el(`track-${track}`).addEventListener("click", () => {
      state.track = track;
      el("track-internship").setAttribute(
        "aria-selected",
        String(track === "internship")
      );
      el("track-full_time").setAttribute(
        "aria-selected",
        String(track === "full_time")
      );
      resetAndRefresh();
    });
  });

  el("search-input").addEventListener(
    "input",
    debounce((event) => {
      state.q = event.target.value.trim();
      resetAndRefresh();
    }, 280)
  );

  el("location-input").addEventListener(
    "input",
    debounce((event) => {
      state.location = event.target.value.trim();
      resetAndRefresh();
    }, 280)
  );

  el("role-filter").addEventListener("change", (event) => {
    state.role = event.target.value;
    resetAndRefresh();
  });

  el("remote-toggle").addEventListener("change", (event) => {
    state.remote = event.target.checked;
    resetAndRefresh();
  });

  el("sponsorship-toggle").addEventListener("change", (event) => {
    state.sponsorship = event.target.checked;
    resetAndRefresh();
  });

  el("sort-select").addEventListener("change", (event) => {
    state.sort = event.target.value;
    resetAndRefresh();
  });

  el("reset-filters").addEventListener("click", () => {
    state.concentrations.clear();
    state.sources.clear();
    state.role = "";
    state.q = "";
    state.location = "";
    state.remote = false;
    state.sponsorship = false;
    state.sort = "recent";
    el("search-input").value = "";
    el("location-input").value = "";
    el("remote-toggle").checked = false;
    el("sponsorship-toggle").checked = false;
    el("sort-select").value = "recent";
    resetAndRefresh();
  });

  el("load-more").addEventListener("click", () => {
    state.offset += state.limit;
    refresh(true);
  });

  el("drawer-close").addEventListener("click", closeDrawer);
  el("drawer-backdrop").addEventListener("click", closeDrawer);
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closeDrawer();
  });
}

async function init() {
  initTheme();
  initControls();
  try {
    const taxonomy = await fetchJSON("/api/meta/taxonomy");
    state.concentrationOrder = taxonomy.concentrations.map((item) => item.name);
    const [stats, profiles] = await Promise.all([
      fetchJSON("/api/stats"),
      fetchJSON("/api/profiles"),
    ]);
    renderStats(stats);
    renderProfiles(profiles);
    await refresh(false);
  } catch (error) {
    console.error(error);
    el("result-meta").textContent =
      "Could not reach the dashboard API. Is uvicorn running?";
  }
}

init();
