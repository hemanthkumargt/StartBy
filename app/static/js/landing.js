// Landing page behaviour: nav rule on scroll, fade-in on scroll and the
// start-by calculator. Everything degrades to a readable static page if this
// script fails.

const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

document.documentElement.classList.add("js");

const nav = $("#lp-nav");
const onScroll = () => nav && nav.classList.toggle("is-stuck", window.scrollY > 8);
window.addEventListener("scroll", onScroll, { passive: true });
onScroll();

const reveals = $$(".lp-reveal");
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
    { threshold: 0.1, rootMargin: "0px 0px -30px 0px" }
  );
  reveals.forEach((el) => io.observe(el));
} else {
  reveals.forEach((el) => el.classList.add("is-in"));
}

