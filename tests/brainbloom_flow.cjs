/* DOM integration tests against the running local API. No real browser is controlled.
 * node tests/brainbloom_flow.cjs [path-to-jsdom] [http://127.0.0.1:8766]
 */
"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const {JSDOM, VirtualConsole} = require(process.argv[2] || "jsdom");
const base = process.argv[3] || "http://127.0.0.1:8766";
const assets = path.join(__dirname, "../src/spie/questions/brainbloom/static");
const errors = [], sent = [], generated = [];
const console = new VirtualConsole();
console.on("jsdomError", error => errors.push(error.message));
const dom = new JSDOM(fs.readFileSync(path.join(assets, "index.html"), "utf8"), {
  url:base, runScripts:"outside-only", virtualConsole:console,
});
const window = dom.window, document = window.document;
const downloads = [], exportBlobs = new Map();
window.URL.createObjectURL = blob => {
  const url = `blob:workshop-export-${exportBlobs.size}`;
  exportBlobs.set(url, blob);
  return url;
};
window.URL.revokeObjectURL = url => exportBlobs.delete(url);
window.HTMLAnchorElement.prototype.click = function () {
  downloads.push({name:this.download, blob:exportBlobs.get(this.href)});
};
const stylesheet = document.createElement("style");
stylesheet.textContent = fs.readFileSync(path.join(assets, "style.css"), "utf8");
document.head.append(stylesheet);
let delayedSubject = "";
window.fetch = async (url, options) => {
  const body = options?.body ? JSON.parse(options.body) : null;
  sent.push({url, body});
  const response = await fetch(new URL(url, base), options);
  if (url === "/api/generate" && response.ok) generated.push(await response.clone().json());
  if (url === "/api/prepare" && body.subject === delayedSubject) await sleep(700);
  return response;
};
window.eval(fs.readFileSync(path.join(assets, "app.js"), "utf8"));
const el = id => document.getElementById(id);
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
async function until(predicate, description) {
  const deadline = Date.now() + 15000;
  while (Date.now() < deadline) {
    if (predicate()) return;
    await sleep(20);
  }
  throw new Error(description + ": " + el("topic-status").textContent + " / " + el("status").textContent);
}
function change(id, value, event = "change") {
  el(id).value = value;
  el(id).dispatchEvent(new window.Event(event, {bubbles:true}));
}
const meaning = term => document.querySelector(`select[data-topic="${term}"]`);
async function chooseMeaning(term, text) {
  await until(() => meaning(term), "Meaning selector for " + term);
  const select = meaning(term);
  const option = [...select.options].find(o => o.textContent.includes(text));
  assert.ok(option, "Expected dictionary meaning: " + text);
  select.focus();
  change(select.id, option.value);
  await until(() => meaning(term)?.value === option.value && !el("topic-status").textContent.startsWith("Checking"), "Meaning saved");
  assert.equal(document.activeElement, meaning(term), "Meaning lookup preserves keyboard focus");
  return option.value;
}

async function main() {
  assert.equal(document.documentElement.dataset.theme, "light");
  assert.equal(el("theme-toggle").getAttribute("aria-pressed"), "false");
  el("theme-toggle").click();
  assert.equal(document.documentElement.dataset.theme, "dark");
  assert.equal(el("theme-toggle").textContent, "Light mode");
  assert.equal(el("theme-toggle").getAttribute("aria-pressed"), "true");
  assert.equal(window.localStorage.getItem("brainbloom-theme"), "dark");
  el("theme-toggle").click();
  assert.equal(document.documentElement.dataset.theme, "light");
  assert.equal(window.localStorage.getItem("brainbloom-theme"), "light");
  await until(() => !el("generate").disabled, "Initial settings ready");
  assert.equal(el("topic").value, "auto");
  assert.equal(el("difficulty").value, "hard");
  assert.match(el("activity-help").textContent, /Solve a set of clues/);
  assert.match(el("setup").textContent, /20 authored topics across 28 pack versions/);
  assert.ok(el("designer-guide").open);
  assert.ok(![...el("topic").options].some(o => o.value === "logic-grid"));
  assert.match(el("topic-status").textContent, /All 2 topics/);
  assert.equal(el("sense"), null);
  assert.equal(el("variation-rule"), null);
  assert.equal(el("advanced").open, false);
  assert.ok([...el("topic").options].every(o => !/Bayesian|generator|reasoning lab/i.test(o.textContent)));

  change("subject", "bank, crane", "input");
  await until(() => meaning("bank") && meaning("crane"), "Both ambiguous topics displayed");
  await until(() => !el("generate").disabled, "Ambiguous meanings selected automatically");
  assert.equal(meaning("bank").value, "", "Automatic selections remain automatic overrides");
  assert.equal(meaning("crane").value, "");
  assert.ok(!document.querySelector("details[data-topic='bank']").open);
  const bank = await chooseMeaning("bank", "financial institution");
  assert.equal(meaning("crane").value, "");
  const crane = await chooseMeaning("crane", "wading");
  await until(() => !el("generate").disabled, "Both meanings ready");
  assert.equal(meaning("bank").value, bank);
  change("topic", "planning");
  await until(() => !el("generate").disabled, "Planning ready");
  change("qtype", "type-answer");
  await until(() => !el("generate").disabled, "Typed planning ready");
  assert.equal(el("topic").value, "planning", "Compatible activity must be preserved");
  el("generate").click();
  await until(() => !el("download").disabled, "Two-topic puzzle generated");
  assert.equal(generated.at(-1).summary.accepted, 1,
    "Expected a playable draft: " + JSON.stringify(generated.at(-1).rejected));
  assert.deepEqual(generated.at(-1).request.meanings, {bank, crane});
  assert.equal(generated.at(-1).version, 5);
  assert.ok(generated.at(-1).proofs[0].model.names.includes("BANK"));
  assert.ok(generated.at(-1).proofs[0].model.names.includes("CRANE"));
  assert.equal(document.querySelectorAll(".card").length, 1);
  el("download").click();
  assert.equal(downloads.length, 1);
  assert.match(downloads[0].name, /^brainbloom-logic-type-answer-\d+\.draft\.json$/);
  assert.equal(downloads[0].blob.type, "application/json");
  const exportedText = await new Promise((resolve, reject) => {
    const reader = new window.FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = () => reject(reader.error);
    reader.readAsText(downloads[0].blob);
  });
  assert.deepEqual(JSON.parse(exportedText), generated.at(-1),
    "Download must retain the entire replay bundle and its source notices");
  assert.equal(exportBlobs.size, 0, "Export releases its object URL");

  change("subject", "bank, crane, space", "input");
  await until(() => !el("generate").disabled, "Added topic ready");
  assert.equal(meaning("bank").value, bank);
  assert.equal(meaning("crane").value, crane);
  assert.match(el("topic-status").textContent, /All 3 topics/);
  assert.equal(document.querySelectorAll(".card").length, 1, "Editing keeps the previous draft");

  change("subject", "space, unknownxyz", "input");
  await until(() => el("topic-status").textContent.includes("unknownxyz"), "Unknown word shown");
  assert.ok(el("generate").disabled);
  change("subject", "space123", "input");
  await until(() => el("topic-status").textContent.includes("space123"), "Unsupported topic remains visible");
  assert.ok(el("generate").disabled, "Unsupported characters must not silently select space");
  delayedSubject = "space, ocean";
  change("subject", delayedSubject, "input");
  el("lookup").click();
  await until(() => sent.at(-1)?.body?.subject === delayedSubject, "Slow lookup dispatched");
  change("subject", "space, plants", "input");
  await until(() => !el("generate").disabled, "Newer lookup ready");
  await sleep(800);
  assert.match(el("topic-meanings").textContent, /plants/);
  assert.doesNotMatch(el("topic-meanings").textContent, /ocean/);
  delayedSubject = "";

  change("subject", "space, ocean, animals, plants, science, logic", "input");
  change("qtype", "crossword");
  change("difficulty", "easy");
  await until(() => el("difficulty").options[2].disabled === false && el("topic-status").textContent.includes("No activity"), "Too-small crossword rejected");
  assert.ok(el("generate").disabled);
  assert.ok(el("difficulty").options[0].disabled);
  assert.ok(el("difficulty").options[1].disabled);
  change("difficulty", "hard");
  await until(() => !el("generate").disabled, "All six topics fit a hard crossword");
  assert.ok(el("search-controls").hidden);
  assert.equal(el("topic").value, "auto");

  // Exact crossword board size, recommendation and preserved manual preference.
  assert.ok(!el("crossword-controls").hidden);
  assert.equal(el("crossword-size").options.length, 12);
  assert.match(el("crossword-size-tiles").textContent, /Recommended/);
  assert.equal(el("crossword-size-tiles").querySelectorAll(".size-tile").length, 11);
  assert.equal(el("crossword-size-tiles").querySelector(".size-featured").getAttribute("aria-pressed"), "true");
  change("subject", "space, ocean", "input");
  change("difficulty", "easy");
  for (const size of [5, 15]) {
    [...el("crossword-size-tiles").querySelectorAll(".size-tile")].find(b => b.textContent === `${size} × ${size}`).click();
    await until(() => !el("generate").disabled, `Size ${size} ready`);
    const countBefore = generated.length;
    el("generate").click();
    await until(() => generated.length > countBefore && !el("download").disabled, "Sized crossword generated");
    assert.equal(generated.at(-1).request.crossword_size, size);
    assert.equal(generated.at(-1).items[0].crosswordData.size, size);
    assert.equal(el("results").querySelectorAll(".crossword-cell").length, size * size);
    assert.equal(el("crossword-size").value, String(size));
  }

  change("subject", "clock, mirror", "input");
  change("qtype", "wonder");
  await chooseMeaning("clock", "timepiece");
  await chooseMeaning("mirror", "surface");
  await until(() => !el("generate").disabled, "Reflection ready");
  assert.ok(el("crossword-controls").hidden);
  assert.ok(el("difficulty-controls").hidden);
  assert.equal(el("count").max, "1");
  assert.ok(el("variation").disabled, "A fixed reflection has no alternate version");
  change("count", "2", "input");
  await until(() => el("topic-status").textContent.includes("at most 1"), "Finite count explained");
  assert.ok(el("generate").disabled);
  change("count", "1", "input");
  change("subject", "", "input");
  change("category", "science");
  change("qtype", "multiple-choice");
  await until(() => !el("generate").disabled, "Default science scenario ready");
  assert.match(el("topic-status").textContent, /built-in scenario/);
  assert.match(el("activity-help").textContent, /speed and journeys/);

  // A viewport-contained split view has two independent scroll roots.
  assert.equal(window.getComputedStyle(el("setup-scroll")).overflow, "auto");
  assert.equal(window.getComputedStyle(el("results")).overflow, "auto");
  assert.equal(window.getComputedStyle(document.body).overflow, "hidden");
  assert.ok(!el("setup-scroll").contains(el("generate")), "Actions stay outside settings scroll");
  assert.ok(!el("results").contains(el("download")), "Download stays outside draft scroll");
  Object.defineProperty(window, "innerWidth", {value:390, configurable:true});
  window.dispatchEvent(new window.Event("resize"));
  assert.equal(el("pane-tabs").hidden, false);
  el("setup-tab").click();
  assert.ok(el("drafts-pane").hidden && !el("setup-pane").hidden);

  change("category", "logic");
  change("subject", "space, ocean", "input");
  change("topic", "custom");
  const instructions = "Make 2 easy typed-answer puzzles. Unscramble words.";
  change("instructions", instructions, "input");
  await until(() => !el("apply-instructions").hidden, "Written settings await explicit application");
  assert.equal(el("count").value, "1", "Text must not silently change the form");
  assert.equal(el("qtype").value, "multiple-choice");
  assert.ok(el("generate").disabled);
  el("apply-instructions").click();
  await until(() => !el("generate").disabled, "Applied instructions are ready");
  assert.equal(el("topic").value, "custom");
  assert.equal(el("count").value, "2");
  assert.equal(el("difficulty").value, "easy");
  assert.equal(el("qtype").value, "type-answer");
  assert.match(el("instruction-feedback").textContent, /Unscramble a word/);
  el("setup-scroll").scrollTop = 420;
  el("results").scrollTop = 250;
  const before = generated.length;
  el("generate").click();
  await until(() => generated.length > before && !el("download").disabled, "Custom draft displayed");
  assert.equal(generated.at(-1).request.instructions, instructions);
  assert.equal(generated.at(-1).items.length, 2);
  assert.ok(el("setup-pane").hidden && !el("drafts-pane").hidden);
  assert.equal(el("results").scrollTop, 0, "New drafts start at the top of their own pane");
  assert.equal(document.activeElement, el("status"), "Generation announces and focuses results");
  assert.equal(el("drafts-tab").textContent, "Drafts (2)");
  el("setup-tab").click();
  assert.equal(el("setup-scroll").scrollTop, 420, "Returning to setup preserves its scroll position");
  assert.equal(el("instructions").value, instructions);

  change("instructions", "Unscramble words without vowels.", "input");
  await until(() => el("instruction-feedback").textContent.includes("cannot apply"), "Unsupported rule flagged");
  assert.ok(el("generate").disabled && el("apply-instructions").hidden);
  change("topic", "anagram");
  await until(() => !el("generate").disabled, "Preset mode still works independently");
  assert.ok(el("instruction-controls").hidden);
  el("setup-tab").dispatchEvent(new window.KeyboardEvent("keydown", {key:"ArrowRight", bubbles:true}));
  assert.equal(document.activeElement, el("drafts-tab"));
  assert.equal(el("drafts-tab").getAttribute("aria-selected"), "true");
  el("drafts-tab").dispatchEvent(new window.KeyboardEvent("keydown", {key:"Home", bubbles:true}));
  assert.equal(el("setup-tab").getAttribute("aria-selected"), "true");
  Object.defineProperty(window, "innerWidth", {value:1280, configurable:true});
  window.dispatchEvent(new window.Event("resize"));
  assert.ok(el("pane-tabs").hidden && !el("setup-pane").hidden && !el("drafts-pane").hidden);

  // Real creator-authored grids: source selection, ambiguity, contradiction and play.
  change("count", "1", "input");
  change("design-mode", "manual");
  await until(() => !el("generate").disabled, "Custom-grid example ready");
  assert.ok(el("dictionary-controls").hidden && !el("grid-controls").hidden);
  assert.match(el("grid-status").textContent, /2 arrangements/);
  assert.ok(![...el("grid-answer-group").options].some(o => o.value === "Animal"));
  change("grid-target", "Tea");
  await until(() => !el("generate").disabled, "Answer groups follow the chosen target");
  assert.equal(el("grid-answer-group").value, "");
  assert.ok(![...el("grid-answer-group").options].some(o => o.value === "Drink"));
  change("grid-complete", "no");
  await until(() => el("grid-status").textContent.includes("Add a rule"), "Strict ambiguity explained");
  assert.ok(el("generate").disabled);
  change("grid-groups", "Animal: Tiger, Lion, Owl", "input");
  change("grid-rules", "Tiger is before Lion.\nLion is before Tiger.", "input");
  await until(() => el("grid-status").textContent.includes("rules conflict"), "Conflicting rules explained");
  assert.ok(el("generate").disabled);
  change("grid-rules", "Tiger must appear before Lion.\nOwl cannot be next to Tiger.", "input");
  await until(() => !el("generate").disabled, "Authored-only order is unique");
  assert.deepEqual([...el("grid-answer-group").options].map(o => o.value), ["", "Position"]);
  change("grid-target", "Owl");
  change("grid-answer-group", "Position");
  await until(() => !el("generate").disabled, "Specific grid query ready");
  const beforeGrid = generated.length;
  el("generate").click();
  await until(() => generated.length > beforeGrid && !el("download").disabled, "Authored grid generated");
  assert.equal(generated.at(-1).version, 6);
  assert.equal(generated.at(-1).items[0].correctAnswer, "3");
  assert.equal(generated.at(-1).proofs[0].added_rules.length, 0);
  assert.equal(document.querySelectorAll(".logic-table select").length, 3);
  const gridSelects = [...document.querySelectorAll(".logic-table select")];
  ["Tiger", "Lion", "Owl"].forEach((value, i) => { gridSelects[i].value = value; });
  [...el("results").querySelectorAll("button")].find(b => b.textContent === "Check working grid").click();
  assert.match(el("results").textContent, /3\/3 entries match/);
  el("results").querySelector(".reveal").click();
  assert.ok(gridSelects.every(s => s.disabled));
  assert.match(el("results").textContent, /unique complete grid is shown/);

  // A beginner supplies no groups or rules: the designer invents everything.
  change("design-mode", "automatic");
  await until(() => !el("generate").disabled, "Return to automatic design");
  assert.equal(el("subject").value, "space, ocean", "Manual mode preserves topic input");
  assert.ok(el("grid-controls").hidden && !el("dictionary-controls").hidden);
  el("try-autopilot").click();
  await until(() => !el("generate").disabled, "Easy animal walkthrough ready");
  assert.equal(el("topic").value, "autopilot");
  assert.equal(el("subject").value, "animals");
  assert.equal(el("difficulty").value, "easy");
  const beforeAuto = generated.length;
  el("generate").click();
  await until(() => generated.length > beforeAuto && !el("download").disabled, "Autonomous puzzle ready");
  const auto = generated.at(-1);
  assert.equal(auto.version, 7);
  assert.equal(auto.request.grid, null);
  assert.equal(auto.proofs[0].authored_rules.length, 0);
  assert.ok(auto.proofs[0].added_rules.length >= 2);
  assert.match(el("results").textContent, /How BrainBloom designed this/);
  const hint = [...el("results").querySelectorAll("button")].find(b => b.textContent === "Show next hint");
  assert.ok(hint);
  assert.doesNotMatch(el("results").textContent, /Start with this clue:/);
  hint.click();
  assert.match(el("results").textContent, /Start with this clue:/);
  assert.equal(errors.length, 0, errors.join("\n"));
  process.stdout.write("Workshop DOM flow passed: automatic meanings, optional overrides, strict input, hard reasoning defaults, instructions, custom grids, grading, JSON export, responsive panels and preserved state.\n");
}
main().then(() => window.close()).catch(error => {
  window.close();
  process.stderr.write(error.stack + "\n");
  process.exitCode = 1;
});
