/* Kelley MSIS Career Intelligence — demo dashboard front end.
   Vanilla JS, no build step. All job data is rendered through
   createElement/textContent so posting content can never inject markup. */

"use strict";

const CONCENTRATION_VARS = ["--c1", "--c2", "--c3", "--c4", "--c5"];

const state = {
  view: "jobs", // "jobs" | "posts"
  track: "full_time",
  concentrations: new Set(),
  sources: new Set(),
  role: "",
  q: "",
  location: "",
  company: "",
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
  // Jobs send a date (YYYY-MM-DD); posts send a full ISO datetime.
  const posted = iso.includes("T") ? new Date(iso) : new Date(`${iso}T00:00:00`);
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

function buildPostParams(extra = {}) {
  const params = new URLSearchParams();
  state.concentrations.forEach((value) => params.append("concentration", value));
  if (state.company) params.set("company", state.company);
  if (state.q) params.set("q", state.q);
  params.set("sort", state.sort);
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
    `badge src src-${job.source_slug || "other"}`,
    job.source_badge
  );
  if (job.source_attribution) sourceBadge.title = job.source_attribution;
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
  meta.appendChild(make("span", "loc", `\u{1F4CD} ${job.location}`));
  if (job.posted_date) {
    meta.appendChild(
      make("span", null, `\u{1F552} ${relativeDate(job.posted_date)}`)
    );
  }
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

  if (job.source_attribution) {
    let provenance = job.source_attribution;
    if (job.retrieved_at) {
      const retrieved = new Date(job.retrieved_at);
      if (!Number.isNaN(retrieved.getTime())) {
        provenance += ` · retrieved ${retrieved.toLocaleDateString([], {
          month: "short",
          day: "numeric",
        })}`;
      }
    }
    body.appendChild(make("div", "drawer-source", provenance));
  }

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

  if (job.matched_keywords && job.matched_keywords.length) {
    const why = make("div", "why-panel");
    why.appendChild(make("h4", null, "Why this is MSIS-relevant"));
    const chips = make("div", "kw-row");
    job.matched_keywords.forEach((keyword) => {
      chips.appendChild(make("span", "kw-chip", keyword));
    });
    why.appendChild(chips);
    body.appendChild(why);
  }

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

  renderConcBlock(stats.by_concentration);

  const chips = el("source-chips");
  chips.replaceChildren();
  stats.by_source.forEach((item) => {
    const chip = make("button", "chip");
    chip.type = "button";
    chip.dataset.source = item.name;
    chip.appendChild(document.createTextNode(item.name));
    chip.appendChild(make("span", "legend-count", String(item.count)));
    chip.addEventListener("click", () => {
      toggleSetValue(state.sources, item.name);
      resetAndRefresh();
    });
    chips.appendChild(chip);
  });

  const atsSources = stats.by_source.filter(
    (item) => item.name !== "LinkedIn" && item.count > 0
  ).length;
  const parts = [];
  if (stats.by_source.some((item) => item.name === "LinkedIn" && item.count > 0)) {
    parts.push("LinkedIn via Apify");
  }
  if (atsSources) {
    parts.push(
      `${atsSources} employer ATS platform${atsSources === 1 ? "" : "s"}`
    );
  }
  el("source-note").textContent = parts.length
    ? `Aggregated live from ${parts.join(" + ")} · ` +
      `${stats.company_count} companies`
    : "";
  syncActiveChips();
}

function renderConcBlock(byConcentration) {
  const covered = byConcentration.filter((item) => item.count > 0).length;
  el("conc-note").textContent =
    covered >= byConcentration.length && covered > 0
      ? "all five tracks represented"
      : `${covered} of ${byConcentration.length} tracks represented`;

  const bar = el("conc-bar");
  const legend = el("conc-legend");
  bar.replaceChildren();
  legend.replaceChildren();
  const total = byConcentration.reduce((sum, item) => sum + item.count, 0);
  byConcentration.forEach((item) => {
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
    node.classList.toggle("active", state.sources.has(node.dataset.source));
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
  if (state.view === "posts") {
    return refreshPosts(append);
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

/* ---------- posts ---------- */

function postAuthor(post) {
  return post.author_name || post.company_name || "LinkedIn";
}

function postCard(post) {
  const card = make("article", "card post-card");
  card.tabIndex = 0;
  card.setAttribute("role", "button");
  card.setAttribute("aria-label", `Hiring post by ${postAuthor(post)}`);

  const top = make("div", "card-top");
  top.appendChild(logoBox({ company: postAuthor(post), company_logo: null }));
  const heading = make("div", "card-heading");
  heading.appendChild(make("h3", "job-title", postAuthor(post)));
  if (post.author_name && post.company_name) {
    heading.appendChild(make("div", "job-company", post.company_name));
  }
  top.appendChild(heading);
  if (post.relevance_score != null) {
    top.appendChild(make("span", "score-pill", String(post.relevance_score)));
  }
  card.appendChild(top);

  const meta = make("div", "meta-row");
  meta.appendChild(make("span", null, `\u{1F4E3} Hiring post`));
  if (post.published_at) {
    meta.appendChild(
      make("span", null, `\u{1F552} ${relativeDate(post.published_at)}`)
    );
  }
  card.appendChild(meta);

  const badges = make("div", "badge-row");
  badges.appendChild(make("span", "badge src src-linkedin", "LinkedIn"));
  if (post.has_signal) {
    badges.appendChild(make("span", "badge opportunity", "Opportunity"));
  }
  card.appendChild(badges);

  if (post.content_excerpt) {
    card.appendChild(make("p", "post-excerpt", post.content_excerpt));
  }
  if (post.concentration_tags.length) card.appendChild(concentrationChips(post));

  if (post.has_signal && post.signal_summary) {
    const hint = make("div", "post-signal-hint");
    hint.appendChild(make("span", "post-signal-icon", "\u{1F4A1}"));
    hint.appendChild(make("span", null, post.signal_summary));
    card.appendChild(hint);
  }

  const actions = make("div", "card-actions");
  actions.appendChild(make("span", "details-link", "View details →"));
  const view = make("a", "apply-btn", "View post ↗");
  view.href = post.source_url;
  view.target = "_blank";
  view.rel = "noopener noreferrer";
  view.addEventListener("click", (event) => event.stopPropagation());
  actions.appendChild(view);
  card.appendChild(actions);

  const open = () => openPostDrawer(post.post_key);
  card.addEventListener("click", open);
  card.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      open();
    }
  });
  return card;
}

async function openPostDrawer(postKey) {
  let post;
  try {
    post = await fetchJSON(`/api/posts/${encodeURIComponent(postKey)}`);
  } catch (error) {
    console.error(error);
    return;
  }
  const body = el("drawer-body");
  body.replaceChildren();

  const top = make("div", "drawer-top");
  top.appendChild(logoBox({ company: postAuthor(post), company_logo: null }));
  const heading = make("div");
  const title = make("h2", "drawer-title", postAuthor(post));
  title.id = "drawer-title";
  heading.appendChild(title);
  if (post.author_name && post.company_name) {
    heading.appendChild(make("div", "drawer-company", post.company_name));
  }
  top.appendChild(heading);
  body.appendChild(top);

  const badges = make("div", "drawer-badges");
  const badgeRowEl = make("div", "badge-row");
  badgeRowEl.appendChild(make("span", "badge src src-linkedin", "LinkedIn post"));
  if (post.published_at) {
    badgeRowEl.appendChild(
      make("span", "badge", relativeDate(post.published_at))
    );
  }
  badges.appendChild(badgeRowEl);
  if (post.concentration_tags.length) {
    const chips = concentrationChips(post);
    chips.style.marginTop = "6px";
    badges.appendChild(chips);
  }
  body.appendChild(badges);

  body.appendChild(
    make("div", "drawer-source", "Fetched from LinkedIn via the Apify posts scraper")
  );

  (post.signals || []).forEach((signal) => {
    const panel = make("div", "match-panel");
    const title = signal.confidence != null
      ? `${signal.topic} — opportunity (AI-extracted, ${Math.round(
          signal.confidence * 100
        )}% confidence)`
      : `${signal.topic} — opportunity (AI-extracted)`;
    panel.appendChild(make("h4", null, title));
    panel.appendChild(make("p", null, signal.summary));
    if (signal.role_tags && signal.role_tags.length) {
      const chips = make("div", "kw-row");
      signal.role_tags.forEach((tag) => chips.appendChild(make("span", "kw-chip", tag)));
      panel.appendChild(chips);
    }
    body.appendChild(panel);
  });

  if (post.matched_keywords && post.matched_keywords.length) {
    const why = make("div", "why-panel");
    why.appendChild(make("h4", null, "Why this is MSIS-relevant"));
    const chips = make("div", "kw-row");
    post.matched_keywords.forEach((keyword) => {
      chips.appendChild(make("span", "kw-chip", keyword));
    });
    why.appendChild(chips);
    body.appendChild(why);
  }

  const content = make("div", "drawer-desc");
  content.appendChild(make("h4", null, "The post"));
  post.content
    .split(/\n{2,}/)
    .filter((part) => part.trim())
    .forEach((part) => content.appendChild(make("p", null, part.trim())));
  body.appendChild(content);

  const actions = make("div", "drawer-actions");
  const view = make("a", "apply-btn", "View post on LinkedIn ↗");
  view.href = post.source_url;
  view.target = "_blank";
  view.rel = "noopener noreferrer";
  actions.appendChild(view);
  body.appendChild(actions);

  el("drawer").hidden = false;
  el("drawer-backdrop").hidden = false;
  el("drawer-close").focus();
}

function renderPostStats(stats) {
  state.dbExists = stats.db_exists;
  el("statsbar").hidden = false;
  el("stat-total").textContent = stats.total_posts;
  el("stat-companies").textContent = stats.company_count;
  el("stat-new").textContent = stats.new_this_week;
  el("stat-sponsor").textContent = stats.with_opportunity;
  el("count-posts").textContent = stats.total_posts;

  if (stats.latest_post_at) {
    const when = new Date(stats.latest_post_at);
    el("updated-chip").textContent = `Latest post ${when.toLocaleString([], {
      month: "short",
      day: "numeric",
      hour: "numeric",
      minute: "2-digit",
    })}`;
  } else {
    el("updated-chip").textContent = "No posts yet";
  }

  renderConcBlock(stats.by_concentration);
}

function renderPostFacets(facets) {
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

  const companyBox = el("company-filters");
  companyBox.replaceChildren();
  facets.companies.forEach((item) => {
    const chip = make("button", "chip");
    chip.type = "button";
    chip.classList.toggle("active", state.company === item.name);
    chip.appendChild(document.createTextNode(item.name));
    chip.appendChild(make("span", "legend-count", String(item.count)));
    chip.addEventListener("click", () => {
      state.company = state.company === item.name ? "" : item.name;
      el("company-input").value = state.company;
      resetAndRefresh();
    });
    companyBox.appendChild(chip);
  });
}

function renderPostResultMeta() {
  const meta = el("result-meta");
  meta.replaceChildren();
  meta.appendChild(make("strong", null, String(state.total)));
  const suffix =
    state.sort === "relevance"
      ? " hiring posts · by MSIS relevance"
      : " hiring posts · newest first";
  meta.appendChild(document.createTextNode(suffix));
}

function showPostsEmptyState() {
  const empty = el("empty-state");
  empty.hidden = false;
  if (!state.dbExists) {
    el("empty-title").textContent = "Posts need the platform database";
    const body = el("empty-body");
    body.replaceChildren(
      document.createTextNode("Point the dashboard at Postgres, then ingest posts:"),
      make(
        "code",
        null,
        "python -m hope_job_agent.pipeline.run_posts --apify-dataset-id <id>"
      )
    );
  } else {
    el("empty-title").textContent = "No matching posts";
    el("empty-body").textContent =
      "Try clearing a filter, broadening your search, or changing the company.";
  }
}

async function refreshPosts(append) {
  const cards = el("cards");
  el("empty-state").hidden = true;
  try {
    const data = await fetchJSON(`/api/posts?${buildPostParams()}`);
    state.total = data.total;
    renderPostFacets(data.facets);
    if (!append) cards.replaceChildren();
    data.posts.forEach((post) => cards.appendChild(postCard(post)));
    renderPostResultMeta();
    const shown = cards.children.length;
    el("load-more").hidden = shown >= state.total;
    if (!shown) showPostsEmptyState();
  } catch (error) {
    console.error(error);
    el("result-meta").textContent =
      "Could not reach the dashboard API. Is uvicorn running?";
  }
}

async function loadPostStats() {
  try {
    renderPostStats(await fetchJSON("/api/posts/stats"));
  } catch (error) {
    console.error(error);
  }
}

function setView(view) {
  if (view === state.view) return;
  state.view = view;
  el("view-jobs").setAttribute("aria-selected", String(view === "jobs"));
  el("view-posts").setAttribute("aria-selected", String(view === "posts"));

  const posts = view === "posts";
  // Jobs-only chrome hides in Posts mode; the concentration + search + sort
  // controls are shared across both views.
  document.querySelector(".track-toggle").hidden = posts;
  el("profile-panel").hidden = posts;
  el("jobs-filters").hidden = posts;
  el("posts-filters").hidden = !posts;
  document.querySelector(".source-block").hidden = posts;
  document.querySelectorAll(".jobs-only-option").forEach((node) => {
    node.hidden = posts;
  });
  el("stat-total-label").textContent = posts ? "Hiring posts" : "Open roles";
  el("stat-sponsor-label").textContent = posts
    ? "With opportunity"
    : "OPT/CPT friendly";

  if (posts && state.sort === "company") {
    state.sort = "recent";
    el("sort-select").value = "recent";
  }
  // Posts never rank by profile, so sorting is always available in Posts mode.
  el("sort-select").disabled = posts ? false : Boolean(state.profile);
  history.replaceState(null, "", posts ? "#posts" : "#jobs");

  if (posts) {
    loadPostStats();
  } else {
    loadStats();
  }
  resetAndRefresh();
}

/* ---------- wiring ---------- */

function initControls() {
  el("view-jobs").addEventListener("click", () => setView("jobs"));
  el("view-posts").addEventListener("click", () => setView("posts"));

  el("company-input").addEventListener(
    "input",
    debounce((event) => {
      state.company = event.target.value.trim();
      resetAndRefresh();
    }, 280)
  );

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
    state.company = "";
    state.remote = false;
    state.sponsorship = false;
    state.sort = "recent";
    el("search-input").value = "";
    el("location-input").value = "";
    el("company-input").value = "";
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

async function loadStats() {
  try {
    renderStats(await fetchJSON("/api/stats"));
  } catch (error) {
    console.error(error);
  }
}

async function loadPostCount() {
  // Populate the Posts tab badge without switching views.
  try {
    const stats = await fetchJSON("/api/posts/stats");
    el("count-posts").textContent = stats.total_posts;
  } catch (error) {
    console.error(error);
  }
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
    loadPostCount();
    if (location.hash === "#posts") {
      setView("posts");
    } else {
      await refresh(false);
    }
  } catch (error) {
    console.error(error);
    el("result-meta").textContent =
      "Could not reach the dashboard API. Is uvicorn running?";
  }
}

init();
