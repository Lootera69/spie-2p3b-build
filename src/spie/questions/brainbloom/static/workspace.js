"use strict";
window.BrainBloomWorkspace = {
  create({workspace, splitter, reset}) {
    const storageKey = "brainbloom-workspace-split-v1";
    let preference = null;
    try {
      const saved = JSON.parse(localStorage.getItem(storageKey));
      if (typeof saved === "number" && saved > 0 && saved < 1) preference = saved;
    } catch { /* Automatic sizing also works without browser storage. */ }
    let state = "empty", active = true, drag = null;
    const clamp = (value, min, max) => Math.min(max, Math.max(min, value));
    function geometry() {
      const width = workspace.getBoundingClientRect().width - (splitter.offsetWidth || 20);
      if (width < 610) return null;
      return {width, min:290 / width, max:1 - 320 / width};
    }
    function applySize() {
      if (!active) return;
      const bounds = geometry();
      if (!bounds) return;
      const ratio = clamp(preference ?? (state === "drafts" ? .28 : .6), bounds.min, bounds.max);
      workspace.style.setProperty("--brief-width", `${ratio * bounds.width}px`);
      splitter.setAttribute("aria-valuemin", String(Math.round(bounds.min * 100)));
      splitter.setAttribute("aria-valuemax", String(Math.round(bounds.max * 100)));
      splitter.setAttribute("aria-valuenow", String(Math.round(ratio * 100)));
      splitter.setAttribute("aria-valuetext", `${Math.round(ratio * 100)}% brief, ${Math.round((1 - ratio) * 100)}% drafts${preference === null ? ", automatic sizing" : ""}`);
    }
    function saveSizes() {
      try {
        if (preference !== null) localStorage.setItem(storageKey, JSON.stringify(preference));
        else localStorage.removeItem(storageKey);
      } catch { /* Keep the chosen sizes for this page when storage is unavailable. */ }
    }
    function finishDrag() {
      if (!drag) return;
      const {pointerId} = drag;
      drag = null;
      document.body.classList.remove("resizing-workspace");
      if (splitter.hasPointerCapture?.(pointerId)) splitter.releasePointerCapture(pointerId);
      saveSizes();
    }
    function autoSize() {
      finishDrag();
      preference = null;
      saveSizes(); applySize();
    }
    function resize(ratio) {
      const bounds = geometry();
      if (!bounds) return;
      preference = clamp(ratio, bounds.min, bounds.max);
      applySize();
    }
    splitter.addEventListener("pointerdown", event => {
      if (!active || drag || event.button !== 0 || event.isPrimary === false) return;
      const bounds = geometry();
      if (!bounds) return;
      event.preventDefault();
      splitter.focus({preventScroll:true});
      const ratio = clamp(preference ?? (state === "drafts" ? .28 : .6), bounds.min, bounds.max);
      drag = {pointerId:event.pointerId, x:event.clientX, width:ratio * bounds.width, moved:false};
      splitter.setPointerCapture?.(event.pointerId);
      document.body.classList.add("resizing-workspace");
    });
    splitter.addEventListener("pointermove", event => {
      if (!drag || event.pointerId !== drag.pointerId) return;
      if (event.clientX === drag.x && !drag.moved) return;
      drag.moved = true;
      const bounds = geometry();
      if (bounds) resize((drag.width + event.clientX - drag.x) / bounds.width);
    });
    for (const type of ["pointerup", "pointercancel", "lostpointercapture"]) {
      splitter.addEventListener(type, event => { if (drag?.pointerId === event.pointerId) finishDrag(); });
    }
    window.addEventListener("blur", finishDrag);
    window.addEventListener("resize", finishDrag);
    splitter.addEventListener("dblclick", autoSize);
    splitter.addEventListener("keydown", event => {
      if (!active) return;
      if (event.key === "Enter") { event.preventDefault(); autoSize(); return; }
      if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
      const bounds = geometry();
      if (!bounds) return;
      event.preventDefault();
      const current = clamp(preference ?? (state === "drafts" ? .28 : .6), bounds.min, bounds.max);
      const step = event.shiftKey ? .1 : .02;
      resize(event.key === "Home" ? bounds.min : event.key === "End" ? bounds.max : current + (event.key === "ArrowLeft" ? -step : step));
      saveSizes();
    });
    reset.addEventListener("click", autoSize);
    if (typeof ResizeObserver !== "undefined") new ResizeObserver(applySize).observe(workspace);
    return {
      update({hasDrafts, compact, playMode}) {
        const nextState = hasDrafts ? "drafts" : "empty";
        const nextActive = !compact && !playMode;
        if (nextState !== state || !nextActive) finishDrag();
        state = nextState; active = nextActive;
        workspace.dataset.hasDrafts = String(Boolean(hasDrafts));
        splitter.hidden = !active; reset.hidden = !active;
        applySize();
      },
    };
  },
};
