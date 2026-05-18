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

const NERD_STORAGE_KEY = "nerd-mode";
const MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

const SUGGESTED_QUESTIONS = [
  "What does my workout schedule look like recently?",
  "Am I overtraining or under-training any muscle group?",
  "Which exercises have I been progressing on, and which have stalled?",
  "How does my volume this month compare to last month?",
  "Is my rest-day pattern healthy?",
  "Suggest one thing I should change in the next 2 weeks.",
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
      <li>Your question is sent to <code>POST /api/chat</code>.</li>
      <li>FastAPI passes it to a local Ollama model (default
        <code>llama3.1:8b-instruct-q4_K_M</code>, configurable via the
        <code>OLLAMA_MODEL</code> env var).</li>
      <li>The model can call any of ~8 read-only "tools" against your
        SQLite DB — schedule summary, muscle-group volume, exercise
        progression, period comparison, etc.</li>
      <li>The model gets the tool results back and writes a natural-language
        answer. No data ever leaves your machine.</li>
    </ol>
    <p>If responses feel slow, switch to the 3B model:
       <code>OLLAMA_MODEL=llama3.2:3b-instruct-q4_K_M ./run.sh</code>.</p>`;
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
}

init().catch((err) => {
  console.error(err);
  dateRange.textContent = "Could not load data. Is the API running?";
});
