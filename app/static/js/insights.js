import { apiFetch } from "./api.js";
import { showToast } from "./toast.js";

const TREND_TEXT = {
  improving: "Trend: your estimates are getting more accurate.",
  worsening: "Trend: your estimates are drifting further from reality.",
  steady: "Trend: your estimate accuracy is steady.",
};

function text(tag, value, className) {
  const node = document.createElement(tag);
  node.textContent = value;
  if (className) node.className = className;
  return node;
}

function renderOverload(overload) {
  const card = document.getElementById("overload-card");
  card.dataset.level = overload.level;
  document.getElementById("overload-message").textContent = overload.message;
  const list = document.getElementById("overload-tasks");
  list.replaceChildren(
    ...overload.top_tasks.map((t) =>
      text("li", `${t.title} — ${t.risk === "red" ? "start now" : "start soon"}`, `insights-list__item insights-list__item--${t.risk}`)
    )
  );
}

function renderReport(report) {
  document.getElementById("report-summary").textContent = report.summary;

  const trendEl = document.getElementById("report-trend");
  const trendText = TREND_TEXT[report.trend.direction];
  trendEl.hidden = !trendText;
  if (trendText) {
    trendEl.textContent = `${trendText} (${report.trend.previous_ratio}x → ${report.trend.recent_ratio}x)`;
  }

  document.getElementById("report-by-tag-wrap").hidden = report.by_tag.length === 0;
  document.getElementById("report-by-tag").replaceChildren(
    ...report.by_tag.map((row) => {
      const tr = document.createElement("tr");
      tr.append(
        text("td", row.tag),
        text("td", String(row.samples)),
        text("td", `${row.avg_ratio.toFixed(2)}x`),
        text("td", row.multiplier ? `${row.multiplier.toFixed(2)}x` : "—")
      );
      return tr;
    })
  );

  document.getElementById("report-series-wrap").hidden = report.series.length === 0;
  // Bars are scaled so 1.0x (a perfect estimate) sits at a fixed 50% mark.
  document.getElementById("report-series").replaceChildren(
    ...report.series.map((point) => {
      const li = document.createElement("li");
      li.className = "insights-bars__row";
      const bar = document.createElement("span");
      bar.className = `insights-bars__bar ${point.ratio > 1.1 ? "is-over" : point.ratio < 0.9 ? "is-under" : "is-on"}`;
      bar.style.width = `${Math.min(100, (point.ratio / 2) * 100)}%`;
      li.append(
        text("span", point.title, "insights-bars__label"),
        bar,
        text("span", `${point.ratio.toFixed(2)}x (${point.actual_hours}h / ${point.estimate_hours}h)`, "insights-bars__value")
      );
      return li;
    })
  );
}

(async () => {
  try {
    const data = await apiFetch("/api/insights");
    renderOverload(data.overload);
    renderReport(data.report_card);
  } catch (err) {
    showToast(err.message, "error");
    // Don't leave "Loading…" up for ever once the toast has gone.
    for (const id of ["overload-message", "report-summary"]) {
      const el = document.getElementById(id);
      if (el) el.textContent = "Couldn't load this right now — refresh the page to try again.";
    }
  }
})();
