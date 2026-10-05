const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
const gsapConfig = {
  overwrite: "auto",
  lazy: false,
  autoRound: false
};

function addGlassEdges() {
  const selectors = [
    ".card", ".panel", ".task-card", ".auth-card", ".assistant-card",
    ".counter-card", ".settings-card", ".activity-stream-card",
    ".dashboard__analytics-card", ".dashboard__shortcuts-card",
    ".dashboard__quick-add", ".dashboard__due-next", ".insights-card",
    ".settings-prop-card", ".oauth-modal", ".task-modal", ".modal",
    ".vnotes__item", ".lp-slip", ".lp-calc", ".lp-cta"
  ];

  document.querySelectorAll(selectors.join(",")).forEach((element) => {
    element.classList.add("glass-edge");
  });
}

function animateGlassEdges() {
  if (reducedMotion || !window.gsap) return;
  const edges = document.querySelectorAll(".glass-edge");
  if (!edges.length) return;

  window.gsap.to(edges, {
    "--edge-angle": "+=360",
    duration: 14,
    ease: "none",
    repeat: -1,
    stagger: { each: 0.12, from: "random" },
    ...gsapConfig
  });
}

function animateFloatingComponents() {
  if (reducedMotion || !window.gsap) return;
  // lp-slip owns a perspective transform and a hover transform in CSS.
  // Animating it here makes those transforms fight and causes visible jumps.
  const floating = document.querySelectorAll(".lp-cta, .fab-mic");
  if (!floating.length) return;

  window.gsap.set(floating, { willChange: "transform" });
  window.gsap.to(floating, {
    y: -6,
    duration: 3.8,
    ease: "sine.inOut",
    yoyo: true,
    repeat: -1,
    stagger: 0.35,
    force3D: true,
    ...gsapConfig
  });
}

function initEffects() {
  addGlassEdges();
  animateGlassEdges();
  animateFloatingComponents();
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", initEffects, { once: true });
} else {
  initEffects();
}
