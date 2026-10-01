/* Isolated theme behaviour, including reload and blocked browser storage. */
"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const source = fs.readFileSync(path.join(__dirname, "../src/spie/questions/brainbloom/static/app.js"), "utf8");
const themeCode = source.slice(0, source.indexOf("const studioHeadlines ="));
assert.ok(themeCode.includes("setTheme"), "Theme initializer must precede the workshop startup");

function load(saved, blocked = false) {
  const store = new Map(saved === undefined ? [] : [["brainbloom-theme", saved]]);
  const listeners = {};
  const toggle = {
    textContent:"Dark mode", attributes:{},
    setAttribute(name, value) { this.attributes[name] = value; },
    addEventListener(name, callback) { listeners[name] = callback; },
  };
  const document = {
    documentElement:{dataset:{}},
    getElementById(id) { assert.equal(id, "theme-toggle"); return toggle; },
  };
  const localStorage = {
    getItem(key) { if (blocked) throw Error("Storage denied"); return store.get(key) ?? null; },
    setItem(key, value) { if (blocked) throw Error("Storage denied"); store.set(key, value); },
  };
  vm.runInNewContext(themeCode, {document, localStorage,
    window:{addEventListener(name, callback) { listeners[name] = callback; }} });
  return {document, toggle, store, listeners};
}

const first = load();
assert.equal(first.document.documentElement.dataset.theme, "light");
assert.equal(first.toggle.attributes["aria-pressed"], "false");
first.listeners.click();
assert.equal(first.document.documentElement.dataset.theme, "dark");
assert.equal(first.toggle.attributes["aria-pressed"], "true");
assert.equal(first.toggle.textContent, "Light mode");
assert.equal(first.store.get("brainbloom-theme"), "dark");
const reloaded = load(first.store.get("brainbloom-theme"));
assert.equal(reloaded.document.documentElement.dataset.theme, "dark");
reloaded.listeners.click();
assert.equal(reloaded.store.get("brainbloom-theme"), "light");
reloaded.listeners.storage({key:"brainbloom-theme", newValue:"dark"});
assert.equal(reloaded.document.documentElement.dataset.theme, "dark");
assert.equal(load("unexpected").document.documentElement.dataset.theme, "light");
const blocked = load(undefined, true);
blocked.listeners.click();
assert.equal(blocked.document.documentElement.dataset.theme, "dark");
console.log("BrainBloom theme tests passed");
