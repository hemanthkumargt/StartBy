// Landing page behaviour: sticky-nav state, scroll reveal, count-up numbers,
// hero tilt + countdown, card spotlight and the start-by calculator.
// Everything degrades to a fully readable static page if this script fails.

const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

document.documentElement.classList.add("js");

// ---- Sticky nav gets a glass background once the page scrolls ----
const nav = $("#lp-nav");
const onScroll = () => nav && nav.classList.toggle("is-stuck", window.scrollY > 8);
window.addEventListener("scroll", onScroll, { passive: true });
onScroll();

// ---- Scroll reveal (staggered per group) ----
const reveals = $$(".lp-reveal");
reveals.forEach((el, i) => el.style.setProperty("--d", `${(i % 4) * 70}ms`));
if ("IntersectionObserver" in window && !reduceMotion) {
  const io = new IntersectionObserver(
    (entries) => {
      for (const e of entries) {
        if (e.isIntersecting) {
          e.target.classList.add("is-in");
          io.unobserve(e.target);
        }
      }
    },
    { threshold: 0.12, rootMargin: "0px 0px -40px 0px" }
  );
  reveals.forEach((el) => io.observe(el));
} else {
  reveals.forEach((el) => el.classList.add("is-in"));
}

// ---- Count-up numbers in the proof strip ----
function countUp(el) {
  const target = Number(el.dataset.count);
  const suffix = el.dataset.suffix || "";
  if (reduceMotion) {
    el.textContent = target + suffix;
    return;
  }
  const t0 = performance.now();
  const dur = 1100;
  const tick = (now) => {
    const p = Math.min(1, (now - t0) / dur);
    el.textContent = Math.round(target * (1 - Math.pow(1 - p, 3))) + suffix;
    if (p < 1) requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
}
const counters = $$("[data-count]");
if ("IntersectionObserver" in window) {
  const co = new IntersectionObserver((entries) => {
    for (const e of entries) {
      if (e.isIntersecting) {
        countUp(e.target);
        co.unobserve(e.target);
      }
    }
  });
  counters.forEach((el) => co.observe(el));
} else {
  counters.forEach(countUp);
}

// ---- Hero: live countdown + gentle pointer tilt ----
const countdown = $("#lp-countdown");
const fill = $("#lp-bar-fill");
if (countdown && !reduceMotion) {
  let left = 42 * 60 + 17;
  const total = 3 * 3600;
  setInterval(() => {
    left = left > 0 ? left - 1 : 42 * 60 + 17;
    const h = String(Math.floor(left / 3600)).padStart(2, "0");
    const m = String(Math.floor((left % 3600) / 60)).padStart(2, "0");
    const s = String(left % 60).padStart(2, "0");
    countdown.textContent = `${h}:${m}:${s}`;
    if (fill) fill.style.width = `${Math.max(4, 100 - (left / total) * 100 * 4)}%`;
  }, 1000);
}

const mock = $("#lp-mock");
const finePointer = window.matchMedia("(hover: hover) and (pointer: fine)").matches;
if (mock && finePointer && !reduceMotion) {
  const visual = mock.parentElement;
  visual.addEventListener("pointermove", (e) => {
    const r = visual.getBoundingClientRect();
    const x = (e.clientX - r.left) / r.width - 0.5;
    const y = (e.clientY - r.top) / r.height - 0.5;
    mock.style.transform = `rotateY(${-7 + x * 10}deg) rotateX(${4 - y * 8}deg)`;
  });
  visual.addEventListener("pointerleave", () => {
    mock.style.transform = "";
  });
}

// ---- Card spotlight follows the cursor ----
$$(".lp-card").forEach((card) => {
  card.addEventListener("pointermove", (e) => {
    const r = card.getBoundingClientRect();
    card.style.setProperty("--mx", `${e.clientX - r.left}px`);
    card.style.setProperty("--my", `${e.clientY - r.top}px`);
  });
});

// ---- Start-by calculator: same formula and risk bands as the app ----
// start_by = due - estimate * multiplier * (1 + 15% buffer); red once start-by
// has passed, amber within 24 h of it, green otherwise.
const BUFFER = 0.15;
const AMBER_WINDOW_H = 24;
const inDue = $("#in-due");
const inEst = $("#in-est");
const inMul = $("#in-mul");

function fmtHours(h) {
  const abs = Math.abs(h);
  const d = Math.floor(abs / 24);
  const hh = Math.floor(abs % 24);
  const mm = Math.round((abs * 60) % 60);
  const parts = [];
  if (d) parts.push(`${d}d`);
  if (hh || d) parts.push(`${hh}h`);
  if (!d) parts.push(`${String(mm).padStart(2, "0")}m`);
  return parts.join(" ");
}

function recalc() {
  if (!inDue || !inEst || !inMul) return;
  const due = Number(inDue.value);
  const est = Number(inEst.value);
  const mul = Number(inMul.value);
  const lead = est * mul * (1 + BUFFER);
  const startIn = due - lead;

  $("#o-due").textContent = due;
  $("#o-est").textContent = est;
  $("#o-mul").textContent = mul.toFixed(1);

  const out = $("#o-start");
  const chip = $("#o-risk");
  let tone = "green";
  let label = "On track";
  if (startIn <= 0) {
    tone = "red";
    label = "Start now. You're already behind";
    out.textContent = `${fmtHours(startIn)} ago`;
  } else {
    if (startIn <= AMBER_WINDOW_H) {
      tone = "amber";
      label = "Starting soon";
    }
    out.textContent = fmtHours(startIn);
  }
  chip.className = `lp-chip is-${tone}`;
  chip.textContent = label;
  $("#o-explain").textContent =
    `${est}h × ${mul.toFixed(1)} × 1.15 buffer = ${lead.toFixed(1)}h of lead time before the deadline.`;
}
[inDue, inEst, inMul].forEach((el) => el && el.addEventListener("input", recalc));
recalc();
