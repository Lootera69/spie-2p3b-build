/* Run with: node tests/brainbloom_library.cjs */
"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const source = fs.readFileSync(path.join(__dirname, "../src/spie/questions/brainbloom/static/library.js"), "utf8");
const plain = value => JSON.parse(JSON.stringify(value));

function storage() {
  const values = new Map();
  return {
    values, writes:0, readError:null, writeError:null,
    getItem(key) { if (this.readError) throw this.readError; return values.get(key) ?? null; },
    setItem(key, value) {
      if (this.writeError) throw this.writeError;
      this.writes++; values.set(key, String(value));
    },
  };
}
function load(target = storage()) {
  const window = {localStorage:target};
  vm.runInNewContext(source, {window});
  return {api:window.BrainBloomLibrary, library:window.BrainBloomLibrary.create(target), storage:target};
}
function bundle(seed = 1, kind = "multiple-choice") {
  const choices = ["multiple-choice", "true-false"].includes(kind) ? ["A", "B"] : [];
  return {
    version:8, generator:"brainbloom-activities-v8",
    request:{seed, category:"logic", qtype:kind, difficulty:"easy", count:1},
    items:[{title:"A saved puzzle", question:"Which letter?", type:kind, difficulty:"easy", choices,
      correctAnswer:"A", correctExplanation:"A follows the clues.", lessonContent:"Follow each clue.",
      acceptedAnswers:["A", "a"], ...(kind === "wonder" ? {sharePrompt:"What did you notice?"} : {}),
      ...(kind === "crossword" ? {crosswordData:{width:2, height:2, rows:["AA", "AA"], clues:[]}} : {})}],
    proofs:[{method:"fixture-check", scope:"Unit test fixture", steps:["Read the clue", "Select A"],
      extraEvidence:{ratio:[1, 3], flags:[true, false], empty:null}}],
    rejected:[], intendedImport:{createdBy:"symbolic-generator", reviewStatus:"draft", published:false},
    dictionary:{label:"Letters", snapshot:{terms:["A", "B"], sources:[{notice:"Retain this source notice."}]}},
    provenance:{engineRevision:12, futureField:{nested:["retain", 42]}},
    checks:{symbolic:{passed:true}}, summary:{requested:1, accepted:1, rejected:0, complete:true, published:false},
  };
}
function fails(action, code) {
  assert.throws(action, error => error.name === "BrainBloomLibraryError" && error.code === code && typeof error.message === "string" && error.message.length > 15);
}

const first = load();
const {library, api} = first;
const key = api.storageKey;
assert.equal(key, "brainbloom-library-v1");
assert.equal(api.limits.maxEntries, 20);
assert.equal(api.limits.maxBundleBytes, 2 * 1024 * 1024 - 8192);
assert.deepEqual(plain(library.list()), []);
assert.equal(first.storage.writes, 0, "Opening an empty library does not write a probe or placeholder");

const original = bundle();
const progress = {0:{selected:1, answer:"First attempt", fields:["typed answer", "grid value"], grid:["A", ""], crossword:{"1,2":"B"}, hints:2, revealed:false,
  checked:{correct:false, message:"Try again"}}};
const saved = library.save(original, progress, "  My\n puzzle set  ");
assert.match(saved.id, /^bb-[a-f0-9]{16}$/);
assert.equal(saved.title, "My puzzle set");
assert.equal(saved.count, 1);
assert.equal(saved.favorite, false);
assert.equal(saved.savedAt, saved.updatedAt);
assert.deepEqual(plain(saved.bundle), original, "The complete original bundle, including source notices and unknown fields, is retained");
assert.deepEqual(plain(saved.progress), progress);
assert.deepEqual(Object.keys(library.list()[0]).sort(), ["count", "favorite", "id", "savedAt", "title", "updatedAt"]);

original.items[0].title = "Mutated input";
progress[0].answer = "Mutated input";
saved.bundle.dictionary.label = "Mutated return value";
saved.progress[0].selected = 0;
const metadata = library.list(); metadata[0].title = "Mutated list";
const reread = library.get(saved.id);
assert.equal(reread.bundle.items[0].title, "A saved puzzle");
assert.equal(reread.bundle.dictionary.label, "Letters");
assert.equal(reread.progress[0].answer, "First attempt");
assert.equal(reread.progress[0].selected, 1);
assert.equal(reread.title, "My puzzle set");
assert.deepEqual(plain(load(first.storage).library.get(saved.id)), plain(reread), "Reload restores exact bundle and progress");

const reordered = Object.fromEntries(Object.entries(bundle()).reverse());
reordered.items[0] = Object.fromEntries(Object.entries(reordered.items[0]).reverse());
library.favorite(saved.id, true);
const duplicate = library.save(reordered, {0:{selected:0, hints:0, revealed:true}});
assert.equal(duplicate.id, saved.id, "Canonical bundle identity ignores object key order");
assert.equal(duplicate.savedAt, saved.savedAt);
assert.equal(duplicate.favorite, true);
assert.equal(duplicate.title, "My puzzle set");
assert.ok(duplicate.updatedAt > saved.updatedAt);
assert.equal(library.list().length, 1);
assert.equal(duplicate.progress[0].revealed, true);
assert.equal(library.save(bundle(), {}, "Renamed set").title, "Renamed set");
assert.equal(load().library.save(bundle()).id, saved.id, "Identical bundles receive stable IDs in independent libraries");

// A digest collision cannot replace a different canonical bundle.
const collisions = load();
const different = collisions.library.save(bundle(2));
const collidingData = JSON.parse(collisions.storage.values.get(key));
collidingData.entries[0].id = saved.id;
collisions.storage.values.set(key, JSON.stringify(collidingData));
const resolvedCollision = collisions.library.save(bundle());
assert.equal(resolvedCollision.id, saved.id + "-1");
assert.deepEqual(plain(collisions.library.get(saved.id).bundle), plain(different.bundle));
assert.deepEqual(plain(collisions.library.get(resolvedCollision.id).bundle), bundle());
assert.equal(collisions.library.save(bundle()).id, resolvedCollision.id);

const second = library.save(bundle(2));
assert.notEqual(second.id, saved.id, "Different canonical bundles are saved separately");
assert.equal(library.list()[0].id, saved.id, "Favorites precede newer sets");
library.favorite(saved.id, false);
library.update(second.id, {0:{answer:"Newest", selected:null}});
assert.equal(library.list()[0].id, second.id);
assert.equal(library.get("missing"), null);
assert.equal(library.remove("missing"), false);
fails(() => library.update("missing", {}), "not-found");
fails(() => library.favorite("missing", true), "not-found");
fails(() => library.favorite(saved.id, "true"), "invalid");

// Each operation reads the current storage, including changes made by another page.
const otherPage = load(first.storage).library;
otherPage.save(bundle(3));
library.update(saved.id, {0:{answer:"Retained other page"}});
assert.equal(otherPage.list().length, 3);
assert.equal(otherPage.get(saved.id).progress[0].answer, "Retained other page");
assert.equal(library.remove(second.id), true);
assert.equal(load(first.storage).library.get(second.id), null);
assert.equal(library.list().length, 2);

// All supported puzzle formats can retain their input state and future JSON fields.
for (const kind of ["multiple-choice", "true-false", "type-answer", "riddle", "crossword", "wonder"]) {
  const fresh = load().library;
  const entry = fresh.save(bundle(9, kind), {0:{selected:null, answer:"", grid:[], crossword:[], hints:0, revealed:false, future:[{enabled:true}]}});
  assert.equal(fresh.get(entry.id).bundle.items[0].type, kind);
  assert.deepEqual(plain(fresh.get(entry.id).progress[0].future), [{enabled:true}]);
}

// Failed writes must not modify old records, progress, favorites, or timestamps.
const baseline = first.storage.values.get(key);
const quota = Object.assign(new Error("Quota reached"), {name:"QuotaExceededError"});
first.storage.writeError = quota;
for (const action of [
  () => library.save(bundle(50)), () => library.save(bundle(), {0:{answer:"lost"}}),
  () => library.update(saved.id, {0:{answer:"lost"}}), () => library.favorite(saved.id, true),
  () => library.remove(saved.id),
]) {
  fails(action, "quota");
  assert.equal(first.storage.values.get(key), baseline, "A failed write leaves the serialized library intact");
}
first.storage.writeError = new Error("Storage denied");
fails(() => library.save(bundle(50)), "unavailable");
assert.equal(first.storage.values.get(key), baseline);
first.storage.writeError = null;
assert.deepEqual(plain(load(first.storage).library.list()), plain(library.list()));
first.storage.readError = new Error("Storage denied");
fails(() => library.list(), "unavailable");
fails(() => library.save(bundle()), "unavailable");
first.storage.readError = null;
assert.equal(first.storage.values.get(key), baseline);

const deniedWindow = {};
Object.defineProperty(deniedWindow, "localStorage", {get() { throw new Error("Browser policy"); }});
vm.runInNewContext(source, {window:deniedWindow});
const denied = deniedWindow.BrainBloomLibrary.create();
fails(() => denied.list(), "unavailable");
fails(() => denied.save(bundle()), "unavailable");
fails(() => api.create(null).list(), "unavailable");

// Malformed envelopes are reported and preserved; no automatic reset or data loss.
const malformed = ["", "{broken", "null", "[]", "{}", '{"version":2,"entries":[]}', '{"version":1,"entries":{}}'];
const envelope = JSON.parse(baseline);
const change = mutate => { const value = plain(envelope); mutate(value); return JSON.stringify(value); };
malformed.push(
  change(value => { value.extra = "unknown envelope version"; }),
  change(value => { value.entries[0].favorite = "yes"; }),
  change(value => { value.entries[0].count = 400; }),
  change(value => { value.entries[0].savedAt = "yesterday"; }),
  change(value => { value.entries[0].title = {}; }),
  change(value => { value.entries[0].id = "<script>"; }),
  change(value => { value.entries[0].bundle.items[0].choices = "wrong"; }),
  change(value => { value.entries[0].bundle.proofs = []; }),
  change(value => { value.entries[0].progress = {99:{answer:"not a card"}}; }),
  change(value => { value.entries[0].progress = {0:{revealed:"false"}}; }),
  change(value => { value.entries.push(plain(value.entries[0])); }),
  change(value => { const extra = plain(value.entries[0]); extra.id += "-1"; value.entries.push(extra); }),
);
for (const raw of malformed) {
  const broken = load(); broken.storage.values.set(key, raw);
  for (const action of [() => broken.library.list(), () => broken.library.get(saved.id),
    () => broken.library.save(bundle()), () => broken.library.update(saved.id, {}),
    () => broken.library.favorite(saved.id, true), () => broken.library.remove(saved.id)]) fails(action, "corrupt");
  assert.equal(broken.storage.values.get(key), raw);
  assert.equal(broken.storage.writes, 0);
}

const invalidProgress = [[], null, {"01":{}}, {1:{}}, {0:[]}, {0:{selected:-1}}, {0:{selected:2}},
  {0:{answer:10}}, {0:{fields:[1]}}, {0:{hints:-1}}, {0:{revealed:1}}, {0:{grid:"A"}}, {0:{crossword:null}}, {0:{future:undefined}}];
for (const candidate of invalidProgress) {
  fails(() => library.update(saved.id, candidate), "invalid");
  assert.equal(first.storage.values.get(key), baseline);
}
const invalidBundles = [null, [], {}, {...bundle(), proofs:[]}, {...bundle(), items:[]}, {...bundle(), version:NaN},
  {...bundle(), unsupported:undefined}, {...bundle(), unsupported:1n}, {...bundle(), unsupported:() => {}}];
const cycle = bundle(); cycle.self = cycle; invalidBundles.push(cycle);
const blankTitle = bundle(); blankTitle.items[0].title = "\u0000\u0001"; invalidBundles.push(blankTitle);
const getter = bundle(); Object.defineProperty(getter, "accessor", {enumerable:true, get() { throw new Error("Should not be called"); }}); invalidBundles.push(getter);
for (const candidate of invalidBundles) {
  fails(() => library.save(candidate), "invalid");
  assert.equal(first.storage.values.get(key), baseline);
}
fails(() => library.save(bundle(), {}, "x".repeat(161)), "invalid");

// Names and source content remain inert text; no HTML rendering or prototype merging.
assert.ok(!source.includes("innerHTML"));
const textOnly = load();
const inert = textOnly.library.save(bundle(), {}, '<img src=x onerror="alert(1)">');
assert.equal(inert.title, '<img src=x onerror="alert(1)">');
const specialKeys = bundle(101);
specialKeys.provenance = JSON.parse('{"__proto__":{"safe":"retained"},"constructor":"source text"}');
const special = textOnly.library.save(specialKeys);
assert.deepEqual(plain(textOnly.library.get(special.id).bundle.provenance), specialKeys.provenance);
assert.equal({}.safe, undefined);

// Count and byte limits reject explicitly without evicting older sets.
const full = load();
for (let seed = 0; seed < api.limits.maxEntries; seed++) full.library.save(bundle(seed));
const fullRaw = full.storage.values.get(key);
fails(() => full.library.save(bundle(500)), "full");
assert.equal(full.storage.values.get(key), fullRaw);
assert.equal(full.library.save(bundle(0), {0:{hints:1}}).progress[0].hints, 1, "Updating a duplicate remains possible at the entry limit");
assert.equal(full.library.list().length, api.limits.maxEntries);

const oversized = bundle(); oversized.provenance.padding = "x".repeat(api.limits.maxBundleBytes);
const sizing = load();
fails(() => sizing.library.save(oversized), "too-large");
assert.equal(sizing.storage.writes, 0);
const unicode = bundle(); unicode.provenance.padding = "🧩".repeat(Math.ceil(api.limits.maxBundleBytes / 4));
fails(() => sizing.library.save(unicode), "too-large");
const largeOne = bundle(1); largeOne.provenance.padding = "x".repeat(1600000);
const largeSaved = sizing.library.save(largeOne);
const beforeLimit = sizing.storage.values.get(key);
const largeTwo = bundle(2); largeTwo.provenance.padding = "y".repeat(1600000);
fails(() => sizing.library.save(largeTwo), "too-large");
assert.equal(sizing.storage.values.get(key), beforeLimit);
fails(() => sizing.library.update(largeSaved.id, {0:{answer:"z".repeat(1600000)}}), "too-large");
assert.equal(sizing.storage.values.get(key), beforeLimit);
assert.equal(sizing.library.list().length, 1);

console.log("BrainBloom library tests passed: persistence, copies, deduplication, progress, favorites, deletion, limits, and storage failures.");
