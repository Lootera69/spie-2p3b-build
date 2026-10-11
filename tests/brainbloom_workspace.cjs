/* Isolated desktop workspace interactions. No server or browser is required.
 * node tests/brainbloom_workspace.cjs [path-to-jsdom]
 */
"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs"), path = require("node:path");
const {JSDOM, VirtualConsole} = require(process.argv[2] || "jsdom");
const source = fs.readFileSync(path.join(__dirname, "../src/spie/questions/brainbloom/static/workspace.js"), "utf8");
const storageKey = "brainbloom-workspace-split-v1";
const opened = [];

function load({saved, blocked = false, width = 1420} = {}) {
  const errors = [], vc = new VirtualConsole();
  vc.on("jsdomError", error => errors.push(error.message));
  const dom = new JSDOM(`<!doctype html><body>
    <div id="workspace">
      <aside id="setup-pane"><div id="setup-scroll"><input id="subject" value="ocean, space"></div></aside>
      <div id="workspace-splitter" role="separator" tabindex="0" aria-orientation="vertical"></div>
      <section id="drafts-pane"><div id="results">An existing puzzle</div></section>
    </div><button id="reset-layout" type="button">Auto layout</button>
  </body>`, {url:"http://localhost/", runScripts:"outside-only", virtualConsole:vc});
  const w = dom.window, d = w.document;
  opened.push(w);
  if (saved !== undefined) w.localStorage.setItem(storageKey, saved);
  if (blocked) {
    for (const method of ["getItem", "setItem", "removeItem"]) {
      w.Storage.prototype[method] = () => { throw new w.DOMException("Storage denied", "SecurityError"); };
    }
  }
  const workspace = d.getElementById("workspace"), splitter = d.getElementById("workspace-splitter");
  const reset = d.getElementById("reset-layout"), captured = new Set();
  let currentWidth = width;
  workspace.getBoundingClientRect = () => ({x:40, y:0, left:40, top:0,
    right:40 + currentWidth, bottom:700, width:currentWidth, height:700});
  Object.defineProperty(workspace, "clientWidth", {get:() => currentWidth});
  Object.defineProperty(splitter, "offsetWidth", {get:() => 20});
  splitter.setPointerCapture = id => captured.add(id);
  splitter.hasPointerCapture = id => captured.has(id);
  splitter.releasePointerCapture = id => captured.delete(id);
  w.eval(source);
  const controller = w.BrainBloomWorkspace.create({workspace, splitter, reset});
  let state = {hasDrafts:false, compact:false, playMode:false};
  function update(next = {}) { state = {...state, ...next}; controller.update(state); }
  update();
  const el = id => d.getElementById(id);
  return {w, d, workspace, splitter, reset, captured, errors, el, update,
    width:() => Number.parseFloat(workspace.style.getPropertyValue("--brief-width")),
    usable:() => currentWidth - 20,
    resize(value) { currentWidth = value; update(); },
    stored:() => w.localStorage.getItem(storageKey),
    key(key, shiftKey = false) {
      const event = new w.KeyboardEvent("keydown", {key, shiftKey, bubbles:true, cancelable:true});
      splitter.dispatchEvent(event); return event;
    },
    pointer(type, x, extra = {}) {
      const event = new w.MouseEvent(type, {clientX:x, button:0, bubbles:true, cancelable:true});
      for (const [name, value] of Object.entries({pointerId:7, pointerType:"mouse", isPrimary:true, ...extra})) {
        Object.defineProperty(event, name, {value});
      }
      splitter.dispatchEvent(event); return event;
    },
    splitX:() => 40 + Number.parseFloat(workspace.style.getPropertyValue("--brief-width")) + 10,
  };
}
function near(actual, expected, message) {
  assert.ok(Number.isFinite(actual) && Math.abs(actual - expected) <= 1,
    `${message}: expected ${expected}, got ${actual}`);
}
function ratio(page, expected, message) {
  near(page.width(), page.usable() * expected, message);
  near(Number(page.splitter.getAttribute("aria-valuenow")), expected * 100, `${message}: accessible percentage`);
}
function idle(page, message) {
  assert.equal(page.d.body.classList.contains("resizing-workspace"), false, message);
}

try {
  const page = load();
  ratio(page, .60, "An empty desktop gives more room to the brief");
  assert.equal(page.splitter.hidden, false);
  assert.equal(page.reset.hidden, false);
  assert.equal(page.stored(), null, "Automatic sizing does not create a manual preference");
  page.update({hasDrafts:true});
  ratio(page, .28, "A generated or restored puzzle gets more room");
  page.update({hasDrafts:false});
  ratio(page, .60, "Returning to no puzzles restores the expanded brief");

  // A manual preference survives generation; unrelated pane state also survives.
  page.el("subject").value = "bank, crane";
  page.el("setup-scroll").scrollTop = 420;
  page.el("results").scrollTop = 175;
  page.el("subject").focus();
  page.key("ArrowRight");
  ratio(page, .62, "Right arrow expands the brief by two percentage points");
  page.update({hasDrafts:true});
  ratio(page, .62, "Generating a puzzle preserves the user's manual layout");
  page.key("ArrowRight", true);
  ratio(page, .72, "Shift-arrow changes the split by ten percentage points");
  page.update({hasDrafts:false});
  ratio(page, .72, "Clearing the puzzles preserves the manual layout");
  page.update({hasDrafts:true});
  ratio(page, .72, "Regeneration never fights the manual preference");
  assert.equal(page.el("subject").value, "bank, crane");
  assert.equal(page.el("setup-scroll").scrollTop, 420);
  assert.equal(page.el("results").scrollTop, 175);
  assert.equal(page.d.activeElement, page.el("subject"), "Layout updates do not steal focus");
  const stored = JSON.parse(page.stored());
  near(stored * 100, 72, "The shared manual preference is saved");
  const reloaded = load({saved:page.stored()});
  ratio(reloaded, .72, "Manual size survives reload before generation");
  reloaded.update({hasDrafts:true});
  ratio(reloaded, .72, "Manual size survives reload after generation");

  page.reset.click();
  ratio(page, .28, "Auto layout restores the current content default");
  assert.equal(page.stored(), null, "Auto layout clears the manual preference");
  page.update({hasDrafts:false});
  ratio(page, .60, "Auto layout follows the content state again");
  page.key("ArrowLeft");
  ratio(page, .58, "Left arrow makes the brief smaller");
  page.key("Enter");

  // Focusing or clicking the separator alone must not turn off automatic sizing.
  let clickX = page.splitX();
  page.pointer("pointerdown", clickX);
  page.pointer("pointermove", clickX);
  page.pointer("pointerup", clickX);
  assert.equal(page.stored(), null, "A click without movement does not save a manual size");
  page.update({hasDrafts:true});
  ratio(page, .28, "Automatic sizing still follows generation after a click");
  page.update({hasDrafts:false});
  ratio(page, .60, "Enter returns to automatic sizing");
  page.key("ArrowRight");
  page.splitter.dispatchEvent(new page.w.MouseEvent("dblclick", {bubbles:true}));
  ratio(page, .60, "Double-click returns to automatic sizing");

  // User sizes stay inside both pane limits and recover after temporary clamping.
  page.key("Home");
  near(page.width(), 290, "Home reaches the brief's minimum usable width");
  page.key("ArrowLeft");
  near(page.width(), 290, "Keyboard sizing cannot cross the brief minimum");
  page.key("End");
  near(page.width(), page.usable() - 320, "End keeps a minimum width for drafts");
  page.key("ArrowRight");
  near(page.width(), page.usable() - 320, "Keyboard sizing cannot cross the drafts minimum");
  page.key("Enter");
  page.key("ArrowRight", true);
  ratio(page, .70, "A manual ratio is selected before narrowing the window");
  page.resize(780);
  near(page.width(), 440, "A narrow desktop clamps the draft pane to 320px");
  page.resize(1420);
  ratio(page, .70, "Widening restores the preferred ratio after temporary clamping");
  page.key("Enter");

  // Dragging works at either content state, including outside the pane bounds.
  let start = page.splitX();
  page.pointer("pointerdown", start);
  assert.ok(page.d.body.classList.contains("resizing-workspace"), "A drag sets the shared resizing cursor");
  assert.ok(page.captured.has(7), "The splitter captures the dragging pointer");
  page.pointer("pointermove", start + 140);
  ratio(page, .70, "Pointer movement resizes the brief");
  page.pointer("pointerup", start + 140);
  idle(page, "Pointer release ends the drag");
  assert.equal(page.captured.has(7), false, "Pointer capture is released after dragging");
  const dragPreference = page.stored();
  ratio(load({saved:dragPreference}), .70, "A completed drag persists across reload");
  page.pointer("pointermove", start - 200);
  ratio(page, .70, "Pointer movement after release cannot resize the panes");
  start = page.splitX();
  page.pointer("pointerdown", start);
  page.pointer("pointermove", -10000);
  near(page.width(), 290, "A drag outside the left edge respects the brief minimum");
  page.pointer("pointermove", 10000);
  near(page.width(), page.usable() - 320, "A drag outside the right edge respects the draft minimum");
  page.pointer("pointerup", 10000);

  for (const end of ["pointercancel", "lostpointercapture", "blur"]) {
    page.key("Enter");
    start = page.splitX();
    page.pointer("pointerdown", start);
    page.pointer("pointermove", start + 28);
    if (end === "blur") page.w.dispatchEvent(new page.w.Event("blur"));
    else page.pointer(end, start + 28);
    idle(page, `${end} ends the drag and clears the resizing cursor`);
    const stoppedWidth = page.width();
    page.pointer("pointermove", start + 200);
    near(page.width(), stoppedWidth, `${end} prevents further pointer movement from resizing`);
  }

  for (const hiddenState of [{compact:true}, {playMode:true}]) {
    page.key("Enter");
    page.key("ArrowRight");
    start = page.splitX();
    page.pointer("pointerdown", start);
    page.update(hiddenState);
    assert.equal(page.splitter.hidden, true, "Mobile and play mode hide the separator");
    assert.equal(page.reset.hidden, true, "Mobile and play mode hide the layout control");
    idle(page, "Leaving the desktop split cancels an in-flight drag");
    page.pointer("pointermove", start + 100);
    page.pointer("pointerup", start + 100);
    page.update({compact:false, playMode:false});
    assert.equal(page.splitter.hidden, false);
    assert.equal(page.reset.hidden, false);
    ratio(page, .62, "Returning from mobile or play mode preserves the manual layout");
  }
  page.key("Enter");
  start = page.splitX();
  page.pointer("pointerdown", start);
  page.update({hasDrafts:true});
  idle(page, "A generation state change cancels an in-flight drag");
  page.pointer("pointermove", start + 140);
  ratio(page, .28, "A stale drag cannot override the new drafts layout");

  for (const malformed of ["invalid JSON", "null", "[]", "0", "1", "-2", "1e999", '"wide"', '{"empty":.6,"drafts":.28}']) {
    const invalid = load({saved:malformed});
    ratio(invalid, .60, "Malformed storage falls back to the empty automatic layout");
    invalid.update({hasDrafts:true});
    ratio(invalid, .28, "Malformed storage falls back to the drafts automatic layout");
    assert.deepEqual(invalid.errors, [], "Malformed saved preferences do not break startup");
  }
  const blocked = load({blocked:true});
  ratio(blocked, .60, "Blocked storage preserves automatic layout");
  blocked.key("ArrowRight");
  ratio(blocked, .62, "Manual resizing still works when storage is blocked");
  blocked.update({hasDrafts:true});
  blocked.update({hasDrafts:false});
  ratio(blocked, .62, "The session remembers manual sizing without storage");
  blocked.reset.click();
  ratio(blocked, .60, "Reset still works when storage is blocked");
  for (const current of [page, reloaded, blocked]) assert.deepEqual(current.errors, []);
  console.log("BrainBloom workspace interaction tests passed");
} finally {
  for (const window of opened) window.close();
}
