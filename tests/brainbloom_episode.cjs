/* Transcript player against the real local API, including stale-response recovery. */
"use strict";
const assert = require("node:assert/strict"), fs = require("node:fs"), path = require("node:path");
const {JSDOM} = require(process.argv[2] || "jsdom");
const base = process.argv[3] || "http://127.0.0.1:8766";
const revision = Number(process.argv[4] || 17);
const assets = path.join(__dirname, "../src/spie/questions/brainbloom/static");
const windows = [], sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
const plain = value => JSON.parse(JSON.stringify(value));
async function until(test, label) {
  const end = Date.now() + 30000;
  while (Date.now() < end) { if (test()) return; await sleep(20); }
  throw new Error("Timed out: " + label);
}
async function post(route, data) {
  const response = await fetch(new URL(route, base), {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(data)});
  const value = await response.json(); assert.equal(response.status, 200, JSON.stringify(value)); return value;
}
function page(bundle, saved) {
  const dom = new JSDOM("<main></main>", {url:base, runScripts:"outside-only"});
  const w = dom.window; windows.push(w);
  ["library.js", "episode.js"].forEach(file => w.eval(fs.readFileSync(path.join(assets, file), "utf8")));
  const host = w.document.querySelector("main"), updates = [], requests = [];
  let delay = false, release = null, fail = false, current = true;
  w.fetch = async (url, options) => {
    const body = JSON.parse(options.body); requests.push(body);
    const response = await fetch(new URL(url, base), options);
    if (delay) { delay = false; await new Promise(resolve => { release = resolve; }); }
    if (fail) { fail = false; throw new w.TypeError("disconnected"); }
    return response;
  };
  const controller = w.BrainBloomEpisode.mount(host, {bundle, index:0, saved,
    onProgress:state => updates.push(plain(state)), isCurrent:() => current});
  const click = text => [...host.querySelectorAll("button")].find(button => button.textContent === text).click();
  return {w, host, updates, requests, controller, click,
    delay:() => { delay = true; }, held:() => !!release, release:() => { release(); release = null; },
    fail:() => { fail = true; }, leave:() => { current = false; }};
}
async function main() {
  const bundle = await post("/api/generate", {topic:"activities", variation:"state-planning", difficulty:"easy", subject:"space, ocean", seed:7, engine_revision:revision});
  assert.equal(bundle.request.engine_revision, revision);
  assert.equal(bundle.proofs[0].episode.version, {11:"planning-episode-v1", 12:"planning-episode-v2", 13:"planning-episode-v2", 14:"planning-episode-v3", 15:"planning-episode-v4", 16:"planning-episode-v4", 17:"planning-episode-v4"}[revision]);
  const original = JSON.stringify(bundle), proof = bundle.proofs[0], solution = proof.model.solution;
  const a = page(bundle);
  assert.equal(a.host.querySelectorAll(".episode-state").length, 0);
  assert.ok(!a.host.textContent.includes(proof.strategy.explanation));
  a.click("Start scenario");
  await until(() => a.updates.length === 1, "start");
  for (let level = 1; level <= 3; level++) {
    a.host.querySelector(".episode-hint").click();
    await until(() => a.controller.snapshot().hint_level === level, "hint " + level);
    assert.ok(a.host.querySelector(".episode-hint-text").textContent);
    if (level < 3) assert.ok(!a.host.querySelector(".episode-hint-text").textContent.includes("shortest legal continuation"));
  }
  const first = solution[0]; a.host.querySelector(`[data-action="${first}"]`).click();
  await until(() => a.controller.snapshot().actions.length === 1, "first move");
  assert.equal(a.controller.snapshot().hint_level, 0, "Help resets at each new position");
  const library = a.w.BrainBloomLibrary.create();
  const saved = library.save(bundle, {0:{episode:a.controller.snapshot()}});
  const b = page(library.get(saved.id).bundle, library.get(saved.id).progress[0].episode);
  b.click("Resume scenario");
  await until(() => b.updates.length === 1, "resume transcript");
  assert.deepEqual(b.updates[0].actions, [first]);
  assert.equal(JSON.stringify(bundle), original, "Canonical bundle stays immutable");
  const before = plain(b.controller.snapshot());
  b.fail(); b.host.querySelector(`[data-action="${solution[1]}"]`).click();
  await until(() => b.host.querySelector(".episode-message").textContent.includes("preserved"), "failed request");
  assert.deepEqual(plain(b.controller.snapshot()), before);
  assert.equal(b.host.querySelector(`[data-action="${solution[1]}"]`).disabled, false);
  b.delay(); b.host.querySelector(`[data-action="${solution[1]}"]`).click();
  await until(b.held, "old request held");
  b.click("Restart scenario");
  await until(() => b.controller.snapshot().actions.length === 0, "new restart accepted");
  b.release(); await sleep(80);
  assert.equal(b.controller.snapshot().actions.length, 0, "Late move cannot overwrite a restart");
  for (const [i, action] of solution.entries()) {
    const move = b.host.querySelector(`[data-action="${action}"]`); assert.ok(move && !move.disabled);
    move.click(); await until(() => b.controller.snapshot().actions.length === i + 1, "action " + i);
  }
  assert.ok(b.host.querySelector(".episode-resolution"));
  assert.equal(b.host.querySelector(".episode-resolution h4").textContent,
    proof.episode.resolution.heading || "Farewell delivered");
  assert.equal(b.host.querySelectorAll(".episode-move").length, 0);
  b.click("Undo last action");
  await until(() => b.controller.snapshot().actions.length === solution.length - 1, "undo success");
  assert.equal(b.host.querySelector(".episode-resolution"), null);
  b.delay(); b.host.querySelector(`[data-action="${solution.at(-1)}"]`).click();
  await until(b.held, "detached response held");
  b.leave(); b.release(); await sleep(80);
  assert.equal(b.controller.snapshot().actions.length, solution.length - 1);
  const forged = {...plain(before), actions:["teleport"]};
  const c = page(bundle, forged); c.click("Resume scenario");
  await until(() => c.host.querySelector(".episode-message").textContent.includes("illegal"), "forged transcript rejected");
  assert.equal(c.host.querySelector(".episode-state"), null);
  c.click("Restart scenario"); await until(() => c.updates.length === 1, "restart bad save");
  assert.deepEqual(c.updates[0].actions, []);
  for (const actions of [false, [1], ["x".repeat(41)], Array(129).fill("recharge")]) {
    assert.throws(() => library.save(bundle, {0:{episode:{started:true, actions, hint_level:0}}}), /invalid format/);
  }
  assert.ok(a.requests.every(request => JSON.stringify(request.bundle) === original));
  if (revision >= 12) {
    const premises = new Set();
    for (let seed = 101; seed <= 120 && premises.size < 3; seed++) {
      const story = await post("/api/generate", {topic:"activities", variation:"state-planning",
        difficulty:"easy", subject:"space, ocean", seed, engine_revision:revision});
      const scenario = story.proofs[0].episode;
      if (premises.has(scenario.premise)) continue;
      premises.add(scenario.premise);
      const ending = page(story, {started:true, actions:story.proofs[0].model.solution, hint_level:0});
      ending.click("Resume scenario");
      await until(() => ending.updates.length === 1, "complete " + scenario.premise);
      assert.equal(ending.host.querySelector(".episode-resolution h4").textContent,
        scenario.resolution.heading, "Each story uses its own verified ending");
      assert.ok(ending.host.querySelector(".episode-resolution").textContent.includes(
        scenario.characters.caretaker.name));
    }
    assert.equal(premises.size, 3, "All three authored premises are playable");
  }
  process.stdout.write("Episode DOM passed: complete replay, hints, immutable save/resume, undo, errors, stale responses, transcript tampering and library bounds.\n");
}
main().catch(error => { process.stderr.write(error.stack + "\n"); process.exitCode = 1; }).finally(() => windows.forEach(w => w.close()));
