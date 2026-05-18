const yearSelect = document.getElementById("year-select");
const dateRange = document.getElementById("date-range");
const statsGrid = document.getElementById("stats-grid");
const prList = document.getElementById("pr-list");
const monthBars = document.getElementById("month-bars");
const heatmapGrid = document.getElementById("heatmap-grid");
const heatmapMonths = document.getElementById("heatmap-months");
const nerdToggle = document.getElementById("nerd-toggle");

const chatStatus = document.getElementById("chat-status");
const chatChips = document.getElementById("chat-chips");
const chatHistory = document.getElementById("chat-history");
const chatForm = document.getElementById("chat-form");
const chatInput = document.getElementById("chat-input");
const chatSend = document.getElementById("chat-send");
const chatNerd = document.getElementById("chat-nerd");

const appleStatus = document.getElementById("apple-status");
const appleStats = document.getElementById("apple-stats");
const cardioList = document.getElementById("cardio-list");
const weightTrend = document.getElementById("weight-trend");
const appleReloadBtn = document.getElementById("apple-reload");

const routineStatus = document.getElementById("routine-status");
const routineDisplay = document.getElementById("routine-display");
const routineClearBtn = document.getElementById("routine-clear");

const profileForm = document.getElementById("profile-form");
const profileAge = document.getElementById("profile-age");
const profileSex = document.getElementById("profile-sex");
const profileYears = document.getElementById("profile-years");
const profileNotes = document.getElementById("profile-notes");
const profileStatus = document.getElementById("profile-status");
const profileSaveBtn = document.getElementById("profile-save");

const NERD_STORAGE_KEY = "nerd-mode";
const MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

const SUGGESTED_QUESTIONS = [
  "Build me a PPL hypertrophy routine, 6 days a week.",
  "Schedule next week from my saved routine, starting Monday.",
  "Give me a weekly digest of last week.",
  "Which of my lifts have stalled in the last 6 weeks?",
  "Am I overtraining or under-training any muscle group?",
  "How does my volume this month compare to last month?",
];

const conversation = [];

async function fetchJson(url, opts = {}) {
  const res = await fetch(url, opts);
  if (!res.ok) throw new Error(`API error: ${res.status}`);
  return res.json();
}

const formatNumber = (n) => n.toLocaleString();

function formatMonth(ym) {
  const [y, m] = ym.split("-");
  return `${MONTH_NAMES[parseInt(m, 10) - 1]} ${y}`;
}

function escapeHtml(s) {
  const d = document.createElement("div");
  d.textContent = s;
  return d.innerHTML;
}

function toDateKey(d) {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

function renderYearReview(data) {
  if (!data.has_data) {
    statsGrid.innerHTML = `<p class="empty-state">No workouts logged for ${data.year}.</p>`;
    prList.innerHTML = "";
    monthBars.innerHTML = "";
    return;
  }

  const cards = [
    { label: "Workouts", value: data.total_sessions },
    { label: "Total sets", value: formatNumber(data.total_sets) },
    { label: "Volume (tons)", value: data.total_volume_tons },
    { label: "Volume (lbs)", value: formatNumber(data.total_volume_lbs) },
    { label: "Cardio miles", value: data.total_miles },
    { label: "Time in gym (hrs)", value: data.total_hours },
    { label: "Longest streak", value: `${data.longest_streak_days} days` },
    {
      label: "Top exercise",
      value: data.top_exercise ? data.top_exercise.name.split("(")[0].trim() : "—",
    },
  ];

  statsGrid.innerHTML = cards
    .map((c) => `
      <div class="stat-card">
        <div class="value">${c.value}</div>
        <div class="label">${c.label}</div>
      </div>`)
    .join("");

  prList.innerHTML = data.personal_records
    .map((p) => `
      <li>
        <span class="exercise">${escapeHtml(p.exercise)}</span>
        <span class="weight">${p.max_weight_lbs} lb</span>
      </li>`)
    .join("");

  const maxSessions = Math.max(...data.months.map((m) => m.sessions), 1);
  monthBars.innerHTML = data.months
    .map((m) => {
      const pct = (m.sessions / maxSessions) * 100;
      return `
        <div class="month-row">
          <span>${formatMonth(m.month).slice(0, 3)}</span>
          <div class="bar-wrap"><div class="bar" style="width:${pct}%"></div></div>
          <span>${m.sessions}</span>
        </div>`;
    })
    .join("");
}

function buildHeatmapDays(year, dayMap) {
  const start = new Date(year, 0, 1);
  const end = new Date(year, 11, 31);
  const cells = [];

  const pad = (start.getDay() + 6) % 7;
  for (let i = 0; i < pad; i++) {
    cells.push(null);
  }

  for (let d = new Date(start); d <= end; d.setDate(d.getDate() + 1)) {
    const key = toDateKey(d);
    cells.push(dayMap.get(key) || { date: key, level: 0, sessions: 0, volume: 0 });
  }
  return cells;
}

function renderHeatmap(data, year) {
  const dayMap = new Map(data.days.map((d) => [d.date, d]));
  const cells = buildHeatmapDays(year, dayMap);

  const weeks = [];
  for (let i = 0; i < cells.length; i += 7) {
    weeks.push(cells.slice(i, i + 7));
  }
  while (weeks.length && weeks[weeks.length - 1].every((c) => c === null)) {
    weeks.pop();
  }

  heatmapGrid.innerHTML = weeks
    .map((week) => {
      const dayCells = week
        .map((cell) => {
          if (!cell) return `<div class="heatmap-cell empty"></div>`;
          const level = cell.level || 0;
          const title = cell.sessions
            ? `${cell.date}: ${cell.sessions} session(s), ${formatNumber(cell.volume)} lb volume`
            : `${cell.date}: rest`;
          return `<div class="heatmap-cell l${level}" title="${escapeHtml(title)}"></div>`;
        })
        .join("");
      return `<div class="heatmap-week">${dayCells}</div>`;
    })
    .join("");

  const monthSpans = [];
  let lastMonth = -1;
  weeks.forEach((week, wi) => {
    const first = week.find((c) => c);
    if (first) {
      const m = parseInt(first.date.slice(5, 7), 10) - 1;
      if (m !== lastMonth) {
        monthSpans.push({ week: wi, label: MONTH_NAMES[m] });
        lastMonth = m;
      }
    }
  });

  heatmapMonths.innerHTML = monthSpans
    .map((m) => `<span style="left:${m.week * 15}px">${m.label}</span>`)
    .join("");
}

function applyNerdMode(on) {
  document.body.classList.toggle("nerd-mode", on);
  nerdToggle.setAttribute("aria-pressed", on ? "true" : "false");
  nerdToggle.textContent = on ? "Hide nerd mode" : "For nerds";
}

function appendChatMessage(role, content, opts = {}) {
  const wrap = document.createElement("div");
  wrap.className = `chat-msg chat-msg-${role}`;
  const bubble = document.createElement("div");
  bubble.className = "chat-bubble";
  if (opts.loading) {
    bubble.innerHTML = `<span class="chat-dots"><span></span><span></span><span></span></span>`;
  } else {
    bubble.innerHTML = formatAnswerMarkdown(content);
  }
  wrap.appendChild(bubble);

  if (opts.tools && opts.tools.length) {
    const meta = document.createElement("div");
    meta.className = "chat-tools nerd-only";
    meta.textContent = `tools used: ${opts.tools.join(", ")}`;
    wrap.appendChild(meta);
  }
  chatHistory.appendChild(wrap);
  chatHistory.scrollTop = chatHistory.scrollHeight;
  return wrap;
}

// Tiny markdown-ish formatter: bold **x**, line breaks, bullet lists, inline code.
function formatAnswerMarkdown(text) {
  const escaped = escapeHtml(text);
  return escaped
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/^- (.+)$/gm, "<li>$1</li>")
    .replace(/(<li>.*<\/li>)/s, "<ul>$1</ul>")
    .replace(/\n{2,}/g, "</p><p>")
    .replace(/\n/g, "<br/>")
    .replace(/^/, "<p>")
    .concat("</p>");
}

async function askQuestion(question) {
  if (!question.trim()) return;

  appendChatMessage("user", question);
  conversation.push({ role: "user", content: question });
  const placeholder = appendChatMessage("assistant", "", { loading: true });
  chatSend.disabled = true;
  chatInput.disabled = true;

  try {
    const body = JSON.stringify({ question, history: conversation.slice(0, -1) });
    const data = await fetchJson("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body,
    });
    placeholder.remove();
    appendChatMessage("assistant", data.answer || "(empty response)", {
      tools: data.tools_used || [],
    });
    conversation.push({ role: "assistant", content: data.answer || "" });
    refreshAgentSideEffects(data.tools_used);
  } catch (err) {
    placeholder.remove();
    appendChatMessage("assistant",
      "**Couldn't reach the LLM.** Make sure Ollama is running (`ollama serve`) " +
      "and the model is pulled. See the chat-panel notes in nerd mode for details.\n\n" +
      `\`${err.message}\``);
  } finally {
    chatSend.disabled = false;
    chatInput.disabled = false;
    chatInput.focus();
  }
}

function renderChatChips() {
  chatChips.innerHTML = SUGGESTED_QUESTIONS
    .map((q, i) => `<button class="chip" type="button" data-idx="${i}">${escapeHtml(q)}</button>`)
    .join("");
  chatChips.querySelectorAll(".chip").forEach((btn) => {
    btn.addEventListener("click", () => {
      const q = SUGGESTED_QUESTIONS[parseInt(btn.dataset.idx, 10)];
      chatInput.value = q;
      askQuestion(q);
      chatInput.value = "";
    });
  });
}

function renderChatNerdNote() {
  chatNerd.innerHTML = `
    <strong>How the chat works</strong>
    <ol>
      <li>Your question goes to <code>POST /api/chat</code>, which forwards it
        to a local Ollama model (default <code>qwen2.5:7b-instruct-q4_K_M</code>;
        override with <code>OLLAMA_MODEL</code> / <code>OLLAMA_HOST</code>).</li>
      <li>The model calls the read/write tools as needed, gets their results,
        and replies as plain text. Nothing ever leaves this machine.</li>
    </ol>
    <p>If the 7B model feels slow on your hardware, try the 3B:
       <code>OLLAMA_MODEL=qwen2.5:3b-instruct-q4_K_M ./run.sh</code>.</p>`;
}

function renderWeightSparkline(samples) {
  if (!samples || samples.length === 0) {
    weightTrend.innerHTML = `<p class="empty-state">No weight samples in Apple Health.</p>`;
    return;
  }
  if (samples.length === 1) {
    const s = samples[0];
    weightTrend.innerHTML =
      `<div class="weight-single">${s.value} lb` +
      `<span class="weight-date">${escapeHtml(s.date)}</span></div>`;
    return;
  }

  const W = 320, H = 80, PAD = 6;
  const values = samples.map((s) => s.value);
  const minV = Math.min(...values);
  const maxV = Math.max(...values);
  const range = Math.max(maxV - minV, 0.5);
  const x = (i) => PAD + (i * (W - PAD * 2)) / Math.max(samples.length - 1, 1);
  const y = (v) => PAD + (H - PAD * 2) * (1 - (v - minV) / range);
  const points = samples.map((s, i) => `${x(i).toFixed(1)},${y(s.value).toFixed(1)}`).join(" ");
  const first = samples[0], last = samples[samples.length - 1];
  const delta = last.value - first.value;
  const arrow = delta > 0 ? "▲" : delta < 0 ? "▼" : "·";

  weightTrend.innerHTML = `
    <div class="weight-stats">
      <span class="weight-current">${last.value} lb</span>
      <span class="weight-delta ${delta > 0 ? "up" : delta < 0 ? "down" : ""}">
        ${arrow} ${Math.abs(delta).toFixed(1)} lb
      </span>
      <span class="weight-range">${escapeHtml(first.date)} → ${escapeHtml(last.date)}</span>
    </div>
    <svg class="sparkline" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">
      <polyline points="${points}" fill="none" stroke="currentColor" stroke-width="1.5"/>
    </svg>`;
}

function renderAppleHealth(data) {
  if (!data.xml_present) {
    appleStatus.textContent =
      "No Apple Health export found. Drop the unzipped export at apple_health_export/export.xml, then click Reload XML.";
    appleStats.innerHTML = "";
    cardioList.innerHTML = "";
    weightTrend.innerHTML = "";
    appleReloadBtn.disabled = false;
    return;
  }
  if (!data.loaded || data.workouts_total === 0) {
    appleStatus.textContent = "Apple Health export present but not yet loaded. Click Reload XML.";
    appleStats.innerHTML = "";
    cardioList.innerHTML = "";
    weightTrend.innerHTML = "";
    return;
  }

  appleStatus.textContent =
    `${data.workouts_total} workouts · ${data.non_strength_workouts} non-lifting · ` +
    `${data.first_workout_date} → ${data.last_workout_date}`;

  const cards = [
    {
      label: "Latest weight",
      value: data.latest_weight ? `${data.latest_weight.value} ${data.latest_weight.unit}` : "—",
    },
    {
      label: "Resting HR",
      value: data.latest_resting_hr ? `${data.latest_resting_hr.value} bpm` : "—",
    },
    {
      label: "HRV (SDNN)",
      value: data.latest_hrv_sdnn_ms ? `${data.latest_hrv_sdnn_ms.value} ms` : "—",
    },
    {
      label: "Avg steps (28d)",
      value: data.avg_steps_last_28d ? formatNumber(Math.round(data.avg_steps_last_28d)) : "—",
    },
    {
      label: "Avg active kcal (28d)",
      value: data.avg_active_kcal_last_28d ? Math.round(data.avg_active_kcal_last_28d) : "—",
    },
    {
      label: "Non-lifting workouts",
      value: data.non_strength_workouts,
    },
  ];
  appleStats.innerHTML = cards
    .map((c) => `
      <div class="stat-card">
        <div class="value">${c.value}</div>
        <div class="label">${c.label}</div>
      </div>`)
    .join("");

  renderWeightSparkline(data.weight_trend);
}

function renderCardioList(payload) {
  if (!payload || !payload.sessions_list || payload.sessions_list.length === 0) {
    cardioList.innerHTML = `<li class="empty-state">No non-lifting workouts in the last ${payload?.weeks || 4} weeks.</li>`;
    return;
  }
  cardioList.innerHTML = payload.sessions_list
    .map((s) => {
      const parts = [];
      if (s.duration_min) parts.push(`${s.duration_min} min`);
      if (s.distance_mi)  parts.push(`${s.distance_mi} mi`);
      if (s.energy_kcal)  parts.push(`${s.energy_kcal} kcal`);
      const meta = parts.join(" · ");
      return `
        <li>
          <span class="cardio-date">${escapeHtml(s.date)}</span>
          <span class="cardio-activity">${escapeHtml(s.activity)}</span>
          <span class="cardio-meta">${escapeHtml(meta || "—")}</span>
          <span class="cardio-source">${escapeHtml(s.source)}</span>
        </li>`;
    })
    .join("");
}

async function loadAppleHealth() {
  try {
    appleStatus.textContent = "Loading…";
    const [summary, cardio] = await Promise.all([
      fetchJson("/api/apple-health/summary"),
      fetchJson("/api/apple-health/cardio?weeks=4").catch(() => null),
    ]);
    renderAppleHealth(summary);
    renderCardioList(cardio);
  } catch (err) {
    appleStatus.textContent = `Apple Health unavailable. ${err.message}`;
  }
}

async function reloadAppleHealth() {
  appleReloadBtn.disabled = true;
  appleStatus.textContent = "Reloading Apple Health XML (this can take 5–60s)…";
  try {
    const res = await fetchJson("/api/apple-health/reload", { method: "POST" });
    if (res.ok === false) {
      appleStatus.textContent = `Reload failed: ${res.reason || "unknown"}`;
    } else {
      await loadAppleHealth();
    }
  } catch (err) {
    appleStatus.textContent = `Reload failed: ${err.message}`;
  } finally {
    appleReloadBtn.disabled = false;
  }
}

// ── Saved routine (reusable template, no dates) ─────────────────────────
function renderRoutine(r) {
  if (!r || !r.exists || !r.sessions || r.sessions.length === 0) {
    routineStatus.innerHTML =
      `No routine saved yet. Ask the chat for a split — e.g. <em>"build me a PPL hypertrophy routine"</em>.`;
    routineDisplay.innerHTML = "";
    return;
  }
  routineStatus.textContent =
    `${escapeHtml(r.name)} · ${r.sessions.length} session${r.sessions.length === 1 ? "" : "s"}` +
    (r.updated_at ? ` · updated ${r.updated_at}` : "");

  const cards = r.sessions
    .map((s) => `
      <div class="routine-card">
        <div class="routine-card-head">
          <span class="routine-title">${escapeHtml(s.title || "")}</span>
        </div>
        ${s.notes ? `<p class="routine-notes">${escapeHtml(s.notes)}</p>` : ""}
        <ul class="routine-exercises">
          ${(s.exercises || []).map((ex) => `<li>${formatExerciseLine(ex)}</li>`).join("")}
        </ul>
      </div>`)
    .join("");

  const head = r.notes
    ? `<p class="routine-meta">${escapeHtml(r.notes)}</p>`
    : "";

  routineDisplay.innerHTML = head + `<div class="routine-grid">${cards}</div>`;
}

async function loadRoutine() {
  try {
    const r = await fetchJson("/api/routine");
    renderRoutine(r);
  } catch (err) {
    routineStatus.textContent = `Couldn't load routine: ${err.message}`;
    routineDisplay.innerHTML = "";
  }
}

async function clearRoutine() {
  if (!confirm("Delete the saved routine?")) return;
  routineClearBtn.disabled = true;
  try {
    await fetchJson("/api/routine", { method: "DELETE" });
    await loadRoutine();
  } catch (err) {
    routineStatus.textContent = `Clear failed: ${err.message}`;
  } finally {
    routineClearBtn.disabled = false;
  }
}

function formatExerciseLine(ex) {
  if (typeof ex === "string") return escapeHtml(ex);
  const parts = [`<strong>${escapeHtml(ex.name || "")}</strong>`];
  const detail = [];
  if (ex.sets)       detail.push(`${ex.sets} sets`);
  if (ex.reps)       detail.push(`${escapeHtml(String(ex.reps))} reps`);
  if (ex.weight_lbs) detail.push(`${ex.weight_lbs} lb`);
  if (detail.length) parts.push(`<span class="ex-detail">${detail.join(" · ")}</span>`);
  if (ex.notes)      parts.push(`<span class="ex-note">${escapeHtml(ex.notes)}</span>`);
  return parts.join(" ");
}

function parseOptionalInt(el) {
  const v = (el.value || "").trim();
  if (!v) return null;
  const n = parseInt(v, 10);
  return Number.isNaN(n) ? null : n;
}

function parseOptionalFloat(el) {
  const v = (el.value || "").trim();
  if (!v) return null;
  const n = parseFloat(v);
  return Number.isNaN(n) ? null : n;
}

function applyProfileToForm(p) {
  profileAge.value = p.age != null ? String(p.age) : "";
  profileSex.value = p.sex || "";
  profileYears.value = p.years_trained != null ? String(p.years_trained) : "";
  profileNotes.value = p.notes || "";
}

async function loadProfile() {
  const baseSubtitle =
    "Optional basics that are not in your Hevy or Apple Health export. Saved here and " +
    "added to the coach’s instructions each time you chat.";
  try {
    const p = await fetchJson("/api/profile");
    applyProfileToForm(p);
    if (p.has_any && p.updated_at) {
      profileStatus.textContent = `${baseSubtitle} Last saved ${p.updated_at}.`;
    } else {
      profileStatus.textContent = baseSubtitle;
    }
  } catch (err) {
    profileStatus.textContent = `Couldn't load profile: ${err.message}`;
  }
}

async function saveProfile() {
  profileSaveBtn.disabled = true;
  const body = {
    age: parseOptionalInt(profileAge),
    sex: (profileSex.value || "").trim() || null,
    years_trained: parseOptionalFloat(profileYears),
    notes: (profileNotes.value || "").trim() || null,
  };
  try {
    const r = await fetchJson("/api/profile", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (r.ok === false) {
      profileStatus.textContent = r.error || "Save failed.";
      return;
    }
    applyProfileToForm(r);
    profileStatus.textContent =
      "Saved. The chat will use this on your next message." +
      (r.updated_at ? ` (${r.updated_at})` : "");
  } catch (err) {
    profileStatus.textContent = `Save failed: ${err.message}`;
  } finally {
    profileSaveBtn.disabled = false;
  }
}

// Refresh whatever the LLM might have written this turn.
function refreshAgentSideEffects(toolsUsed) {
  if (!toolsUsed || toolsUsed.length === 0) return;
  if (toolsUsed.some((t) => t === "save_routine" || t === "clear_routine")) {
    loadRoutine();
  }
}

async function loadYear(year) {
  const [review, heatmap, summary] = await Promise.all([
    fetchJson(`/api/year-review/${year}`),
    fetchJson(`/api/heatmap?year=${year}`),
    fetchJson("/api/summary"),
  ]);

  if (summary.first_date) {
    dateRange.textContent = `${summary.first_date} → ${summary.last_date} · ${summary.sessions} sessions all time`;
  }

  renderYearReview(review);
  renderHeatmap(heatmap, year);
}

async function checkChatHealth() {
  try {
    const r = await fetchJson("/api/chat/health");
    if (r.ok) {
      chatStatus.textContent = `Connected to Ollama · model: ${r.model}`;
      chatStatus.classList.remove("chat-status-warn");
    } else {
      chatStatus.textContent = `Ollama not reachable (${r.error || "unknown"}). The chat won't work until you start it.`;
      chatStatus.classList.add("chat-status-warn");
    }
  } catch {
    chatStatus.textContent = "Chat backend offline.";
    chatStatus.classList.add("chat-status-warn");
  }
}

async function init() {
  applyNerdMode(localStorage.getItem(NERD_STORAGE_KEY) === "1");
  nerdToggle.addEventListener("click", () => {
    const next = !document.body.classList.contains("nerd-mode");
    applyNerdMode(next);
    localStorage.setItem(NERD_STORAGE_KEY, next ? "1" : "0");
  });

  renderChatChips();
  renderChatNerdNote();
  checkChatHealth();

  chatForm.addEventListener("submit", (e) => {
    e.preventDefault();
    const q = chatInput.value;
    chatInput.value = "";
    askQuestion(q);
  });
  chatInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      chatForm.requestSubmit();
    }
  });

  const { years } = await fetchJson("/api/years");
  yearSelect.innerHTML = years
    .map((y) => `<option value="${y}">${y}</option>`)
    .join("");

  const defaultYear = years[0] || new Date().getFullYear();
  yearSelect.value = defaultYear;

  yearSelect.addEventListener("change", () => loadYear(parseInt(yearSelect.value, 10)));
  await loadYear(defaultYear);

  appleReloadBtn.addEventListener("click", reloadAppleHealth);
  loadAppleHealth();

  routineClearBtn.addEventListener("click", clearRoutine);
  profileSaveBtn.addEventListener("click", () => saveProfile());
  profileForm.addEventListener("submit", (e) => {
    e.preventDefault();
    saveProfile();
  });
  loadRoutine();
  loadProfile();
}

init().catch((err) => {
  console.error(err);
  dateRange.textContent = "Could not load data. Is the API running?";
});
