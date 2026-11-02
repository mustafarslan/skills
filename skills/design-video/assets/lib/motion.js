/* motion.js — small time-based helpers for design-video compositions.
   Framework-free. Everything is a pure function of time `t` (seconds), so any frame can be
   computed on its own, in any order, with the same result.
   Exposed as the global `M`. */
(function (g) {
  const clamp01 = (v) => Math.min(1, Math.max(0, v));
  const lerp = (a, b, k) => a + (b - a) * k;

  // CSS cubic-bezier(x1, y1, x2, y2) as a function of progress 0..1 (bisection, deterministic).
  function bezier(x1, y1, x2, y2) {
    const poly = (a1, a2) => (s) => 3 * a1 * s * (1 - s) * (1 - s) + 3 * a2 * s * s * (1 - s) + s * s * s;
    const X = poly(x1, x2), Y = poly(y1, y2);
    return (x) => {
      x = clamp01(x);
      if (x === 0 || x === 1) return x;
      let lo = 0, hi = 1;
      for (let i = 0; i < 40; i++) { const mid = (lo + hi) / 2; if (X(mid) < x) lo = mid; else hi = mid; }
      return Y((lo + hi) / 2);
    };
  }

  // The motion rules in one place: ease-out in, ease-in out, no overshoot (y stays within 0..1).
  const ease = {
    linear: (x) => clamp01(x),
    out: bezier(0.16, 1, 0.3, 1),     // entrances
    in: bezier(0.7, 0, 0.84, 1),      // exits
    inOut: bezier(0.65, 0, 0.35, 1),  // moves from one place to another
  };

  // Progress of `t` through [a, b], eased and clamped to 0..1.
  const span = (t, a, b, e = ease.linear) => e(clamp01((t - a) / (b - a)));

  // Entrance at time `at`: fade + rise. Returns { o: opacity, y: px offset }.
  function enter(t, at, dur = 0.4, dist = 24) {
    const p = span(t, at, at + dur, ease.out);
    return { o: p, y: (1 - p) * dist };
  }
  // Exit starting at time `at`, 30% shorter than an entrance by default.
  function leave(t, at, dur = 0.28) {
    const p = span(t, at, at + dur, ease.in);
    return { o: 1 - p, y: 0 };
  }
  const stagger = (i, gap = 0.07) => i * gap;

  // Typewriter: the first characters of `text` visible at time t.
  const typewriter = (text, t, at, cps = 24) => text.slice(0, Math.max(0, Math.floor((t - at) * cps)));

  // Count from `from` to `to` between times a and b.
  const counter = (t, a, b, from, to) => lerp(from, to, span(t, a, b, ease.out));

  // Reading time rule: 0.35 s per word + 1 s, then hold 0.5 s after the motion ends.
  const words = (s) => (String(s).trim().match(/\S+/g) || []).length;
  const minOnScreen = (s) => 0.35 * words(s) + 1 + 0.5;

  // Apply an {o, y} state to an element.
  function put(el, s) { el.style.opacity = String(s.o); el.style.transform = `translateY(${s.y}px)`; }

  g.M = { clamp01, lerp, bezier, ease, span, enter, leave, stagger, typewriter, counter, words, minOnScreen, put };
})(typeof window !== 'undefined' ? window : globalThis);
