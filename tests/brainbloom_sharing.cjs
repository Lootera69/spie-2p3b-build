/* Portable links, without a server or a browser session.
 * node tests/brainbloom_sharing.cjs [path-to-jsdom]
 */
"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs"), path = require("node:path");
const {test} = require("node:test");
const {gzipSync} = require("node:zlib");
const {JSDOM, VirtualConsole} = require(process.argv[2] || "jsdom");
const source = fs.readFileSync(path.join(__dirname, "../src/spie/questions/brainbloom/static/player.js"), "utf8");
const format = "brainbloom-share-v1";
const plain = value => JSON.parse(JSON.stringify(value));
const base = "https://example.test/workshop/?theme=ocean#old-fragment";

function load(t, {compress = true, decompress = true} = {}) {
  const errors = [], console = new VirtualConsole();
  console.on("jsdomError", error => errors.push(error.message));
  const dom = new JSDOM("<!doctype html><html><body></body></html>", {
    url:base, runScripts:"outside-only", virtualConsole:console,
  });
  const w = dom.window;
  // JSDOM does not provide stream-capable Blob or browser compression APIs.
  // The real Node implementations exercise gzip, decoding and bounded streams.
  Object.assign(w, {TextEncoder, TextDecoder, Blob,
    CompressionStream:compress ? CompressionStream : undefined,
    DecompressionStream:decompress ? DecompressionStream : undefined});
  w.fetch = () => { throw new Error("Player helpers must not make network requests"); };
  w.eval(source);
  t.after(() => { w.close(); assert.deepEqual(errors, []); });
  return {api:w.BrainBloomPlayer, w};
}

function fragment(bytes, encoding = "j") {
  return `#bb=1.${encoding}.${Buffer.from(bytes).toString("base64url")}`;
}
function envelope(value, encoding = "j") {
  const bytes = Buffer.from(JSON.stringify(value));
  return fragment(encoding === "g" ? gzipSync(bytes) : bytes, encoding);
}
function bundle() {
  return {
    version:8, generator:"brainbloom-activities-v8",
    request:{seed:7, category:"logic", qtype:"multiple-choice", difficulty:"easy", count:1},
    items:[{title:"Ocean café — café / 海", type:"multiple-choice", question:"Which symbol follows?",
      choices:["α", "β", "🌊"], correctAnswer:"🌊", correctExplanation:"Keep every proof field.",
      lessonContent:"Compare every stated constraint. ".repeat(100)}],
    proofs:[{method:"fixture-check", steps:["First deduction", "Second deduction"],
      extra:{nullValue:null, flags:[false, true], exactRatio:[2, 7]}}],
    dictionary:{sources:[{notice:"Preserve the source attribution."}]},
    provenance:{future:{unknownFields:["retained", 42]}}
  };
}

test("raw share roundtrip preserves the complete bundle and replaces only the URL fragment", async t => {
  const {api, w} = load(t, {compress:false});
  const original = bundle(), before = JSON.stringify(original);
  const shared = new URL(await api.shareURL(original, base));
  assert.match(shared.hash, /^#bb=1\.j\.[A-Za-z0-9_-]+$/);
  assert.equal(shared.origin, "https://example.test");
  assert.equal(shared.pathname, "/workshop/");
  assert.equal(shared.search, "?theme=ocean");
  assert.ok(!shared.href.includes("old-fragment"));
  assert.deepEqual(plain(await api.readShare(shared.hash)), original);
  assert.equal(JSON.stringify(original), before, "Sharing does not mutate canonical content");
  assert.equal(w.location.href, base, "Making a link does not navigate or publish it");
  assert.equal(w.localStorage.length, 0);
});

test("gzip share roundtrip uses compression and keeps unknown proof and source fields", async t => {
  const {api} = load(t);
  const original = bundle();
  const shared = new URL(await api.shareURL(original, base));
  assert.match(shared.hash, /^#bb=1\.g\.[A-Za-z0-9_-]+$/);
  assert.deepEqual(plain(await api.readShare(shared.hash)), original);
  const receiver = load(t);
  assert.deepEqual(plain(await receiver.api.readShare(shared.hash)), original);
});

test("raw links open even when decompression is unavailable", async t => {
  const {api} = load(t, {compress:false, decompress:false});
  const original = bundle();
  const shared = new URL(await api.shareURL(original, base));
  assert.deepEqual(plain(await api.readShare(shared.hash)), original);
  await assert.rejects(api.readShare(envelope({format, bundle:original}, "g")), /current browser/);
});

test("ordinary fragments are ignored and unsupported versions or malformed headers fail", async t => {
  const {api} = load(t);
  for (const hash of ["", "#top", "#bb", "#other=1.j.data"]) {
    assert.equal(await api.readShare(hash), null);
  }
  for (const hash of ["#bb=", "#bb=2.j.YQ", "#bb=01.j.YQ"]) {
    await assert.rejects(api.readShare(hash), /unsupported|too large/);
  }
  for (const hash of ["#bb=1.x.YQ", "#bb=1.j:YQ", "#bb=1.g", "#bb=1..YQ"]) {
    await assert.rejects(api.readShare(hash), /not valid/);
  }
});

test("corrupt base64, UTF-8, JSON, gzip, and invalid envelopes give an actionable error", async t => {
  const {api} = load(t);
  const bad = [
    "#bb=1.j.", "#bb=1.j.a", "#bb=1.j.+/=", "#bb=1.j.Y Q",
    fragment([0xc3, 0x28]), fragment(Buffer.from("{unfinished")),
    fragment(Buffer.from("not a gzip stream"), "g"),
    fragment(gzipSync(Buffer.from(JSON.stringify({format, bundle:bundle()}))).subarray(0, 12), "g"),
    ...[null, [], "text", {}, {format}, {format, bundle:null}, {format, bundle:false},
      {format:"future-format", bundle:{}}, {format, bundle:{}, extra:true}].map(value => envelope(value)),
  ];
  for (const hash of bad) await assert.rejects(api.readShare(hash), /damaged or incomplete/);
});

test("share byte and URL length limits fail before producing an unusable link", async t => {
  const {api} = load(t);
  await assert.rejects(api.shareURL({padding:"x".repeat(api.maxBytes)}, base), /too large/);
  // Limits count UTF-8 bytes, so a shorter string can still exceed the budget.
  await assert.rejects(api.shareURL({padding:"海".repeat(Math.ceil(api.maxBytes / 3))}, base), /too large/);
  const raw = load(t, {compress:false}).api;
  await assert.rejects(raw.shareURL({padding:"x".repeat(20000)}, base), /too large/);
  await assert.rejects(api.shareURL({}, "https://example.test/?q=" + "x".repeat(api.maxLinkLength)), /too large/);
  await assert.rejects(api.readShare("#bb=1.j." + "A".repeat(api.maxLinkLength)), /unsupported or too large/);
});

test("compressed links enforce the decompressed byte limit and accept its exact boundary", async t => {
  const {api} = load(t);
  const emptySize = Buffer.byteLength(JSON.stringify({format, bundle:{padding:""}}));
  const atLimit = {format, bundle:{padding:"x".repeat(api.maxBytes - emptySize)}};
  assert.equal(Buffer.byteLength(JSON.stringify(atLimit)), api.maxBytes);
  const compressed = envelope(atLimit, "g");
  assert.ok(compressed.length < api.maxLinkLength);
  assert.equal((await api.readShare(compressed)).padding.length, atLimit.bundle.padding.length);
  const shared = await api.shareURL(atLimit.bundle, base);
  assert.match(new URL(shared).hash, /^#bb=1\.g\./);
  const tooLarge = envelope({format, bundle:{padding:atLimit.bundle.padding + "x"}}, "g");
  assert.ok(tooLarge.length < api.maxLinkLength, "A small fragment can expand beyond the byte cap");
  await assert.rejects(api.readShare(tooLarge), /too large/);
});
