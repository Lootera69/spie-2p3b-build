/* Save a move accepted while reopening the same set is waiting for verification.
 * node tests/brainbloom_episode_navigation.cjs [path-to-jsdom] [http://127.0.0.1:8766]
 * The real API decides every move. Only response delivery and the 250 ms
 * autosave timer are held to make the navigation race deterministic.
 */
"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs"), path = require("node:path");
const {JSDOM, VirtualConsole} = require(process.argv[2] || "jsdom");
const base = process.argv[3] || "http://127.0.0.1:8766";
const assets = path.join(__dirname, "../src/spie/questions/brainbloom/static");
const storageKey = "brainbloom-library-v1", opened = [];
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

async function until(test, label, page) {
  const end = Date.now() + 30000;
  while (Date.now() < end) {
    const failure = page?.responses.find(response => !response.ok);
    if (failure) throw new Error(`${label}: ${failure.url} returned ${failure.status}: ${JSON.stringify(failure.value)}`);
    if (test()) return;
    await sleep(10);
  }
  throw new Error("Timed out: " + label);
}

async function generate() {
  const response = await fetch(new URL("/api/generate", base), {
    method:"POST", headers:{"Content-Type":"application/json"},
    body:JSON.stringify({topic:"activities", qtype:"multiple-choice", variation:"state-planning",
      difficulty:"medium", subject:"space, ocean", count:1, seed:1701}),
  });
  const bundle = await response.json();
  assert.equal(response.status, 200, JSON.stringify(bundle));
  assert.equal(bundle.request.engine_revision, 17);
  assert.equal(bundle.proofs[0].model.experience_version, "planning-experience-v5");
  assert.equal(bundle.summary.complete, true);
  assert.equal(bundle.proofs[0].episode.version, "planning-episode-v4");
  return bundle;
}

function load() {
  const errors = [], requests = [], responses = [];
  const console = new VirtualConsole();
  console.on("jsdomError", error => errors.push(error.message));
  const dom = new JSDOM(fs.readFileSync(path.join(assets, "index.html"), "utf8"), {
    url:base, runScripts:"outside-only", virtualConsole:console,
  });
  const w = dom.window, d = w.document;
  opened.push(w);
  Object.assign(w, {TextEncoder, TextDecoder, Blob, CompressionStream, DecompressionStream});
  const delayed = new Set(), pending = new Map();
  w.fetch = async (url, options) => {
    const body = options?.body && JSON.parse(options.body);
    requests.push({url, body});
    const response = await fetch(new URL(url, base), options);
    const value = await response.clone().json();
    responses.push({url, body, value, ok:response.ok, status:response.status});
    if (delayed.has(url)) await new Promise(resolve => { pending.set(url, resolve); });
    return response;
  };
  // Preserve the production timer's cancellation behavior, while preventing
  // the background autosave from rescuing a missing navigation flush by luck.
  const schedule = w.setTimeout.bind(w), cancel = w.clearTimeout.bind(w);
  const autosaves = new Map();
  let timerId = 1000000;
  w.setTimeout = (handler, delay, ...args) => {
    if (Number(delay) !== 250) return schedule(handler, delay, ...args);
    const id = ++timerId;
    autosaves.set(id, () => handler(...args));
    return id;
  };
  w.clearTimeout = id => { if (!autosaves.delete(id)) cancel(id); };
  for (const file of ["library.js", "player.js", "episode.js", "workspace.js", "app.js"]) {
    w.eval(fs.readFileSync(path.join(assets, file), "utf8"));
  }
  return {
    w, d, errors, requests, responses, autosaves,
    el:id => d.getElementById(id),
    storage:() => JSON.parse(w.localStorage.getItem(storageKey)),
    delay:url => delayed.add(url),
    held:url => pending.has(url),
    release(url) {
      const resume = pending.get(url);
      assert.ok(resume, `Expected a held response for ${url}`);
      pending.delete(url); delayed.delete(url); resume();
    },
  };
}

function clickButton(host, text) {
  const button = [...host.querySelectorAll("button")].find(node => node.textContent === text);
  assert.ok(button, `Missing button: ${text}`);
  assert.equal(button.disabled, false, `Button disabled: ${text}`);
  button.click();
}

function storedEpisode(page, id) {
  return page.storage().entries.find(entry => entry.id === id).progress[0].episode;
}

async function main() {
  const bundle = await generate(), original = JSON.stringify(bundle);
  const a = load();
  await until(() => !a.el("generate").disabled, "setup ready", a);
  const library = a.w.BrainBloomLibrary.create();
  const entry = library.save(bundle, {0:{episode:{started:false, actions:[], hint_level:0}}});
  a.el("open-library").click();
  clickButton(a.d.querySelector(".library-entry"), "Open & resume");
  await until(() => a.d.querySelector(".episode-player") && !a.el("save-puzzles").disabled,
    "initial verified set opened", a);
  const card = a.d.querySelector(".card"), episode = card.querySelector(".episode-player");
  clickButton(episode, "Start scenario");
  await until(() => /action 0$/.test(episode.querySelector(".episode-location")?.textContent || ""),
    "initial position accepted", a);
  a.el("save-puzzles").click();
  assert.deepEqual(storedEpisode(a, entry.id), {started:true, actions:[], hint_level:0});
  assert.equal(a.autosaves.size, 0, "Saving the baseline cancels its pending autosave");

  const first = bundle.proofs[0].model.solution[0];
  a.delay("/api/play-episode");
  const move = episode.querySelector(`[data-action="${first}"]`);
  assert.ok(move && !move.disabled, "The first verified move must be available");
  move.click();
  await until(() => a.held("/api/play-episode"), "move checked but delivery held", a);

  a.delay("/api/verify-saved");
  a.el("open-library").click();
  clickButton(a.d.querySelector(".library-entry"), "Open & resume");
  await until(() => a.held("/api/verify-saved"), "same saved set verification held", a);
  assert.equal(a.d.querySelector(".card"), card, "Old player stays mounted during verification");
  assert.equal(a.el("results").inert, true);
  assert.deepEqual(storedEpisode(a, entry.id).actions, []);

  a.release("/api/play-episode");
  await until(() => /action 1$/.test(episode.querySelector(".episode-location")?.textContent || ""),
    "move accepted during saved-set verification", a);
  assert.deepEqual(storedEpisode(a, entry.id).actions, [],
    "The move is accepted in memory, but the 250 ms autosave has not run");
  assert.equal(a.autosaves.size, 1, "An accepted move queued an autosave");
  const accepted = a.responses.find(response => response.url === "/api/play-episode"
    && response.body.actions.length === 1).value;
  // Reopening proceeds before the queued autosave. The navigation flush itself
  // must persist the accepted move before re-reading this same set's progress.
  a.release("/api/verify-saved");
  await until(() => a.d.querySelector(".card") !== card && !a.el("save-puzzles").disabled,
    "same set reopened before autosave", a);
  assert.deepEqual(storedEpisode(a, entry.id), {started:true, actions:[first], hint_level:0},
    "Reopening must retain the move accepted after its initial progress flush");
  assert.equal(a.autosaves.size, 0, "Navigation explicitly flushed and cancelled the pending save");
  assert.deepEqual(a.storage().entries.find(item => item.id === entry.id).bundle, JSON.parse(original),
    "Saving episode progress must not change canonical puzzle content");

  const resumed = a.d.querySelector(".episode-player");
  clickButton(resumed, "Resume scenario");
  await until(() => /action 1$/.test(resumed.querySelector(".episode-location")?.textContent || ""),
    "latest accepted transcript resumed", a);
  const resumedRequest = a.requests.filter(request => request.url === "/api/play-episode").at(-1);
  assert.deepEqual(resumedRequest.body.actions, [first], "Resume sends the accepted transcript");
  assert.match(resumed.querySelector(".episode-state").textContent,
    new RegExp(`Energy ${accepted.state.energy}/${accepted.state.capacity}`));
  a.w.dispatchEvent(new a.w.Event("pagehide"));
  assert.deepEqual(storedEpisode(a, entry.id).actions, [first]);
  assert.deepEqual(a.errors, []);
  process.stdout.write("Episode navigation passed: a move accepted during saved-set verification survives immediate reopen, storage and replay before autosave.\n");
}

main().catch(error => { process.stderr.write(error.stack + "\n"); process.exitCode = 1; })
  .finally(() => opened.forEach(w => w.close()));
