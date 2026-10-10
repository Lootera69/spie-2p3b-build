/* Player/library integration against the real local API.
 * node tests/brainbloom_player.cjs [path-to-jsdom] [http://127.0.0.1:8775]
 */
"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs"), path = require("node:path");
const {JSDOM, VirtualConsole} = require(process.argv[2] || "jsdom");
const base = process.argv[3] || "http://127.0.0.1:8775";
const assets = path.join(__dirname, "../src/spie/questions/brainbloom/static");
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
const opened = [];
async function until(test, label) {
  for (let i = 0; i < 1500; i++) { if (test()) return; await sleep(20); }
  throw new Error("Timed out: " + label);
}
async function navigateHash(page, hash) {
  await new Promise(resolve => {
    page.w.addEventListener("hashchange", resolve, {once:true});
    page.w.location.hash = hash;
  });
}
function load(saved, options = {}) {
  const errors = [], generated = [], requests = [], responses = [];
  const vc = new VirtualConsole(); vc.on("jsdomError", e => errors.push(e.message));
  const dom = new JSDOM(fs.readFileSync(path.join(assets, "index.html"), "utf8"), {
    url:options.url || base, runScripts:"outside-only", virtualConsole:vc,
  });
  const w = dom.window, d = w.document; opened.push(w);
  Object.assign(w, {TextEncoder, TextDecoder, Blob, CompressionStream, DecompressionStream});
  if (saved) w.localStorage.setItem("brainbloom-library-v1", saved);
  const delayed = new Set(options.delayVerify ? ["/api/verify-saved"] : []), pending = new Map();
  w.fetch = async (url, options) => {
    requests.push({url, body:options?.body && JSON.parse(options.body)});
    const response = await fetch(new URL(url, base), options);
    responses.push({url, ok:response.ok, status:response.status});
    if (url === "/api/generate" && response.ok) generated.push(await response.clone().json());
    if (delayed.has(url)) await new Promise(resolve => { pending.set(url, resolve); });
    return response;
  };
  for (const file of ["library.js", "player.js", "app.js"]) w.eval(fs.readFileSync(path.join(assets, file), "utf8"));
  const el = id => d.getElementById(id);
  const storage = () => w.localStorage.getItem("brainbloom-library-v1");
  return {w,d,el,errors,generated,requests,responses,storage,
    delay(url = "/api/check-answer") { delayed.add(url); },
    release(url = "/api/check-answer", keepDelayed = false) {
      if (!keepDelayed) delayed.delete(url);
      const resume = pending.get(url); pending.delete(url); resume();
    },
    released:(url = "/api/check-answer") => pending.has(url)};
}
async function main() {
  const a = load();
  await until(() => !a.el("generate").disabled, "setup ready");
  a.el("reasoning-mode").value = "deduction-only";
  a.el("min-supporting-clues").value = "4";
  a.el("try-autopilot").click();
  assert.equal(a.el("reasoning-mode").value, "auto", "The easy example resets an earlier deduction-only requirement");
  assert.equal(a.el("min-supporting-clues").value, "auto", "The easy example clears an earlier minimum of four clues");
  await until(() => a.el("topic").value === "autopilot" && !a.el("generate").disabled, "animal brief ready");
  a.el("generate").click();
  await until(() => a.generated.length && !a.el("save-puzzles").disabled, "puzzle generated");
  assert.equal(a.generated[0].request.difficulty, "easy");
  assert.equal(a.generated[0].request.reasoning_mode, "auto");
  assert.equal(a.generated[0].request.min_supporting_clues, "auto");
  const original = JSON.stringify(a.generated[0]);
  const card = a.d.querySelector(".card"), item = a.generated[0].items[0];
  a.el("play-mode").click();
  assert.equal(a.el("play-mode").getAttribute("aria-pressed"), "true");
  assert.ok(a.d.body.classList.contains("play-mode"));
  assert.equal(a.el("setup-pane").hidden, true);
  assert.equal(a.el("drafts-pane").hidden, false);
  assert.equal(a.el("results").getAttribute("aria-label"), "Puzzles to play");
  assert.equal(a.el("drafts-title").textContent, "Your puzzles");
  assert.equal(a.d.querySelector(".card"), card, "Mode changes preserve the active puzzle");
  a.el("play-mode").click();
  assert.equal(a.el("play-mode").getAttribute("aria-pressed"), "false");
  assert.ok(!a.d.body.classList.contains("play-mode"));
  assert.equal(a.el("setup-pane").hidden, false);
  assert.equal(a.el("drafts-title").textContent, "Your drafts");
  const choices = [...card.querySelectorAll(".option")];
  const wrong = item.choices.findIndex(c => c !== item.correctAnswer);
  const right = item.choices.indexOf(item.correctAnswer);
  choices[wrong].click();
  card.querySelector(".check-answer").click();
  await until(() => card.querySelector(".answer-feedback").dataset.result === "incorrect", "specific wrong feedback");
  assert.match(card.querySelector(".answer-feedback").textContent, /clue|position|arrangement/i);
  assert.ok(card.querySelector(".reveal"), "Checking does not reveal the full answer");
  a.delay(); card.querySelector(".check-answer").click();
  await until(a.released, "delayed response prepared");
  choices[right].click(); a.release(); await sleep(40);
  assert.equal(card.querySelector(".answer-feedback").textContent, "", "Old answer feedback discarded");
  card.querySelector(".check-answer").click();
  await until(() => card.querySelector(".answer-feedback").dataset.result === "correct", "correct feedback");

  const proof = a.generated[0].proofs[0], groupCount = proof.model.groups.length;
  const gridInputs = [...card.querySelectorAll(".logic-table select")];
  const gridCheck = [...card.querySelectorAll("button")].find(button => button.textContent === "Check working grid");
  const gridFeedback = gridCheck.parentNode.querySelector(".feedback");
  const setGrid = (cell, value) => { gridInputs[cell].value = value; gridInputs[cell].dispatchEvent(new a.w.Event("change", {bubbles:true})); };
  const duplicated = proof.model.groups[0].values[0];
  setGrid(0, duplicated); setGrid(groupCount, duplicated); gridCheck.click();
  await until(() => gridFeedback.dataset.result === "incorrect" && !gridCheck.disabled, "duplicate grid feedback");
  assert.match(gridFeedback.textContent, /appears in positions 1, 2.*exactly once/);
  assert.deepEqual(gridInputs.map((select, i) => select.classList.contains("grid-conflict") ? i : -1).filter(i => i >= 0), [0, groupCount]);
  assert.equal(gridInputs[0].getAttribute("aria-invalid"), "true");
  const checkedGrid = a.requests.find(request => request.url === "/api/check-grid");
  assert.equal(JSON.stringify(checkedGrid.body.bundle), original, "Grid checks send the original verified bundle");
  assert.equal(checkedGrid.body.index, 0);
  assert.equal(checkedGrid.body.entries.length, gridInputs.length);
  assert.equal(checkedGrid.body.entries[groupCount], duplicated);
  a.delay("/api/check-grid"); gridCheck.click();
  await until(() => a.released("/api/check-grid"), "delayed grid response prepared");
  const solution = proof.solution_table.flatMap(row => proof.model.groups.map(group => row[group.name]));
  solution.forEach((value, i) => setGrid(i, value));
  a.release("/api/check-grid");
  await until(() => !gridCheck.disabled, "stale grid check settled");
  assert.equal(gridFeedback.textContent, "", "Changing a cell discards feedback for the old entries");
  assert.equal(card.querySelectorAll(".grid-conflict, .logic-table [aria-invalid]").length, 0);
  gridCheck.click();
  await until(() => gridFeedback.dataset.result === "correct" && !gridCheck.disabled, "complete grid success");
  assert.match(gridFeedback.textContent, /complete grid.*satisfies every clue/);
  assert.ok(card.querySelector(".reveal"), "A correct grid check does not reveal the full explanation");
  gridInputs.forEach((_, i) => setGrid(i, ""));
  a.el("save-puzzles").click();
  assert.match(a.el("save-status").textContent, /Saved in this browser/);
  const grid = card.querySelector(".logic-table select");
  grid.value = grid.options[1].value; grid.dispatchEvent(new a.w.Event("change", {bubbles:true}));
  card.querySelector(".next-hint").click();
  a.w.dispatchEvent(new a.w.Event("pagehide"));
  assert.equal(JSON.stringify(a.generated[0]), original, "Playing never mutates the canonical bundle");

  const b = load(a.storage());
  await until(() => !b.el("generate").disabled, "reloaded setup ready");
  b.el("open-library").click();
  const savedRow = b.d.querySelector(".library-entry");
  assert.ok(savedRow);
  const favorite = savedRow.querySelector("[aria-pressed]"); favorite.click();
  assert.equal(b.d.querySelector(".library-entry [aria-pressed]").getAttribute("aria-pressed"), "true");
  b.d.querySelector(".library-entry button").click();
  await until(() => b.d.querySelector(".card") && !b.el("save-puzzles").disabled, "reopen checked save");
  assert.ok(b.requests.some(r => r.url === "/api/verify-saved"));
  const resumed = b.d.querySelector(".card");
  assert.equal(resumed.querySelector(".logic-table select").value, grid.value);
  assert.equal(resumed.querySelector(".next-hint").dataset.shown, "1");
  assert.equal([...resumed.querySelectorAll(".option")][right].getAttribute("aria-pressed"), "true");
  resumed.querySelector(".reveal").click(); b.w.dispatchEvent(new b.w.Event("pagehide"));
  b.el("open-library").click(); b.d.querySelector(".library-entry button").click();
  await until(() => b.d.querySelector(".card.revealed") && !b.el("save-puzzles").disabled, "revealed state restored");
  assert.ok(!b.d.querySelector(".card .reveal"));

  b.el("share-puzzles").click();
  await until(() => !!b.el("share-link").value && !b.el("copy-share").disabled, "revealed game share link ready");
  assert.equal(b.el("share-panel").hidden, false);
  assert.match(b.el("share-status").textContent, /Recipients start with blank puzzles/);
  const sharedURL = b.el("share-link").value;
  assert.deepEqual(JSON.parse(JSON.stringify(await b.w.BrainBloomPlayer.readShare(new URL(sharedURL).hash))), JSON.parse(original),
    "Sharing a revealed game sends canonical content without its progress");
  const shared = load(b.storage(), {url:sharedURL, delayVerify:true});
  await until(() => shared.released("/api/verify-saved"), "shared bundle verified but held before rendering");
  assert.equal(shared.d.querySelector(".card"), null, "A shared bundle is not rendered before server verification");
  assert.match(shared.el("status").textContent, /Checking the shared puzzles/);
  assert.equal(shared.el("share-puzzles").disabled, true);
  const sharedVerification = shared.requests.find(request => request.url === "/api/verify-saved");
  assert.deepEqual(sharedVerification.body.bundle, JSON.parse(original));
  assert.equal(shared.responses.find(response => response.url === "/api/verify-saved").ok, true);
  shared.release("/api/verify-saved");
  await until(() => shared.d.querySelector(".card") && !shared.el("save-puzzles").disabled, "verified shared puzzle opened");
  const sharedCard = shared.d.querySelector(".card");
  assert.equal(sharedCard.classList.contains("revealed"), false);
  assert.equal(sharedCard.querySelector(".answer"), null);
  assert.ok(sharedCard.querySelector(".reveal"));
  assert.equal(sharedCard.querySelectorAll(".option[aria-pressed='true'], .correct, .wrong").length, 0);
  assert.deepEqual([...sharedCard.querySelectorAll(".logic-table select")].map(select => select.value), solution.map(() => ""));
  assert.equal(sharedCard.querySelector(".next-hint").dataset.shown, "0");
  assert.equal(sharedCard.querySelector(".answer-feedback").textContent, "");
  assert.equal(shared.el("play-mode").getAttribute("aria-pressed"), "true");
  assert.equal(shared.el("setup-pane").hidden, true);
  assert.match(shared.el("status").textContent, /shared puzzle checked and ready to play/);
  assert.equal(shared.requests.filter(request => request.url === "/api/generate").length, 0,
    "Opening a share checks the saved puzzle without regenerating a replacement");

  const tampered = JSON.parse(original); tampered.proofs[0].solution_positions[0] = 99;
  const tamperedURL = await b.w.BrainBloomPlayer.shareURL(tampered, base);
  const rejectedShare = load(undefined, {url:tamperedURL, delayVerify:true});
  await until(() => rejectedShare.released("/api/verify-saved"), "tampered shared proof rejected by API");
  assert.equal(rejectedShare.d.querySelector(".card"), null);
  assert.equal(rejectedShare.responses.find(response => response.url === "/api/verify-saved").ok, false);
  rejectedShare.release("/api/verify-saved");
  await until(() => rejectedShare.el("status").classList.contains("error"), "tampered share error displayed");
  assert.equal(rejectedShare.d.querySelector(".card"), null, "Rejected proof data never becomes a playable card");
  assert.ok(rejectedShare.el("status").textContent.length > 10);
  assert.equal(rejectedShare.el("play-mode").disabled, true);
  assert.equal(rejectedShare.el("save-puzzles").disabled, true);

  // Hash navigation while an unrelated generation is busy must be resumed.
  const sharedHash = new URL(sharedURL).hash;
  const queuedGeneration = load();
  await until(() => !queuedGeneration.el("generate").disabled, "queued-generation setup ready");
  queuedGeneration.el("try-autopilot").click();
  await until(() => queuedGeneration.el("topic").value === "autopilot" && !queuedGeneration.el("generate").disabled,
    "queued-generation animal brief ready");
  queuedGeneration.el("seed").value = "8";
  queuedGeneration.delay("/api/generate"); queuedGeneration.el("generate").click();
  await until(() => queuedGeneration.released("/api/generate"), "generation held while navigating to a share");
  assert.equal(queuedGeneration.generated[0].request.seed, 8);
  await navigateHash(queuedGeneration, sharedHash);
  assert.equal(queuedGeneration.requests.filter(request => request.url === "/api/verify-saved").length, 0,
    "The shared-link check waits until the ongoing generation settles");
  queuedGeneration.delay("/api/verify-saved"); queuedGeneration.release("/api/generate");
  await until(() => queuedGeneration.released("/api/verify-saved"), "queued share resumed after generation");
  assert.equal(queuedGeneration.w.location.hash, sharedHash);
  assert.deepEqual(queuedGeneration.requests.find(request => request.url === "/api/verify-saved").body.bundle,
    JSON.parse(original));
  queuedGeneration.release("/api/verify-saved");
  await until(() => /shared puzzle checked and ready to play/.test(queuedGeneration.el("status").textContent)
    && !queuedGeneration.el("save-puzzles").disabled, "queued share replaces the newly generated puzzle");
  assert.equal(queuedGeneration.d.querySelector(".card .prompt").textContent, item.question);
  assert.equal(queuedGeneration.el("play-mode").getAttribute("aria-pressed"), "true");
  assert.deepEqual([...queuedGeneration.d.querySelectorAll(".card .logic-table select")].map(select => select.value),
    solution.map(() => ""));

  // Opening a saved game calls invalidatePlayer; it must preserve a newer hash
  // and open that shared puzzle with fresh progress after its own replay ends.
  const queuedSaved = load(b.storage(), {delayVerify:true});
  await until(() => !queuedSaved.el("generate").disabled, "queued saved-game setup ready");
  queuedSaved.el("open-library").click();
  queuedSaved.d.querySelector(".library-entry button").click();
  await until(() => queuedSaved.released("/api/verify-saved"), "saved-game replay held while navigating to a share");
  await navigateHash(queuedSaved, sharedHash);
  assert.equal(queuedSaved.requests.filter(request => request.url === "/api/verify-saved").length, 1);
  queuedSaved.release("/api/verify-saved", true);
  await until(() => queuedSaved.requests.filter(request => request.url === "/api/verify-saved").length === 2
    && queuedSaved.released("/api/verify-saved"), "queued share resumed after saved-game replay");
  assert.equal(queuedSaved.w.location.hash, sharedHash, "Saved-game cleanup preserves the queued share fragment");
  assert.ok(queuedSaved.d.querySelector(".card.revealed"), "The saved progress was restored before opening the queued share");
  queuedSaved.release("/api/verify-saved");
  await until(() => /shared puzzle checked and ready to play/.test(queuedSaved.el("status").textContent)
    && !queuedSaved.el("save-puzzles").disabled, "queued share opens with fresh progress after saved game");
  assert.equal(queuedSaved.d.querySelector(".card.revealed"), null);
  assert.ok(queuedSaved.d.querySelector(".card .reveal"));
  assert.equal(queuedSaved.d.querySelector(".card .prompt").textContent, item.question);
  assert.equal(queuedSaved.d.querySelector(".card .next-hint").dataset.shown, "0");
  assert.deepEqual([...queuedSaved.d.querySelectorAll(".card .logic-table select")].map(select => select.value),
    solution.map(() => ""));
  // An untouched stale tab must not write old progress on pagehide.
  a.w.localStorage.setItem("brainbloom-library-v1", b.storage());
  a.w.dispatchEvent(new a.w.StorageEvent("storage", {key:"brainbloom-library-v1"}));
  const newerProgress = a.storage();
  a.w.dispatchEvent(new a.w.Event("pagehide"));
  assert.equal(a.storage(), newerProgress, "Untouched stale tabs preserve newer progress");
  const external = a.w.BrainBloomLibrary.create();
  external.remove(external.list()[0].id);
  a.w.dispatchEvent(new a.w.StorageEvent("storage", {key:"brainbloom-library-v1"}));
  assert.equal(a.el("save-puzzles").textContent, "Save puzzles", "Removed saves detach without losing the open puzzle");
  assert.match(a.el("save-status").textContent, /removed in another tab/);

  // Both a typed answer and individual crossword cells survive reopening.
  for (const qtype of ["type-answer", "crossword"]) {
    const response = await fetch(base + "/api/generate", {method:"POST", headers:{"Content-Type":"application/json"},
      body:JSON.stringify({topic:qtype === "crossword" ? "crossword" : "arithmetic", qtype, category:"puzzles", difficulty:"easy", seed:7})});
    assert.ok(response.ok); const bundle = await response.json();
    const lib = b.w.BrainBloomLibrary.create(), entry = lib.save(bundle, {"0":{fields:[qtype === "crossword" ? "Z" : "my unfinished answer"]}});
    b.el("open-library").click();
    // Panel might already be open; make its state explicit.
    if (b.el("library-panel").hidden) b.el("open-library").click();
    const row = [...b.d.querySelectorAll(".library-entry")].find(r => r.querySelector("h4").textContent === entry.title);
    row.querySelector("button").click();
    await until(() => b.el("status").textContent.startsWith(entry.title) && !b.el("save-puzzles").disabled, "typed/crossword restore");
    assert.equal(b.d.querySelector(".card input").value, qtype === "crossword" ? "Z" : "my unfinished answer");
  }
  b.el("open-library").click();
  const count = b.d.querySelectorAll(".library-entry").length;
  const row = b.d.querySelector(".library-entry");
  [...row.querySelectorAll("button")].find(x => x.textContent === "Remove").click();
  [...row.querySelectorAll("button")].find(x => x.textContent === "Remove saved set").click();
  assert.equal(b.d.querySelectorAll(".library-entry").length, count - 1);
  const bad = load("not json");
  bad.el("open-library").click();
  assert.match(bad.el("library-status").textContent, /corrupt|read|invalid/i);
  assert.equal(bad.storage(), "not json", "Corrupt saves are not silently overwritten");
  await until(() => !bad.el("generate").disabled, "corrupt storage does not block generation");
  assert.deepEqual(a.errors.concat(b.errors, bad.errors, shared.errors, rejectedShare.errors,
    queuedGeneration.errors, queuedSaved.errors), []);
  console.log("Player integration passed: coaching and grid checks, stale responses, play mode, verified and queued sharing, blank shared progress, rejected tampering, easy-example reset, save/reload, hints, typed answers, crossword, favourites and removal.");
}
main().catch(e => {console.error(e); process.exitCode = 1;}).finally(() => opened.forEach(w => w.close()));
