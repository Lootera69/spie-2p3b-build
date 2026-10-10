/* Portable puzzle links. No remote service or publication. */
(function (root) {
  "use strict";
  const maxBytes = 2 * 1024 * 1024 - 8192, maxLinkLength = 24000;
  const prefix = "#bb=1.";
  function base64(bytes) {
    let raw = "";
    for (let i = 0; i < bytes.length; i += 8192) raw += String.fromCharCode(...bytes.subarray(i, i + 8192));
    return root.btoa(raw).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  }
  function unbase64(text) {
    if (!/^[A-Za-z0-9_-]+$/.test(text)) throw new Error("This puzzle link is not valid.");
    const raw = root.atob(text.replace(/-/g, "+").replace(/_/g, "/"));
    return Uint8Array.from(raw, char => char.charCodeAt(0));
  }
  async function bounded(stream, limit) {
    const reader = stream.getReader(), chunks = [];
    let total = 0;
    try {
      while (true) {
        const {done, value} = await reader.read();
        if (done) break;
        total += value.length;
        if (total > limit) { await reader.cancel(); throw new Error("This puzzle link is too large to open safely."); }
        chunks.push(value);
      }
    } finally { reader.releaseLock(); }
    const result = new Uint8Array(total);
    let offset = 0;
    for (const chunk of chunks) { result.set(chunk, offset); offset += chunk.length; }
    return result;
  }
  async function shareURL(bundle, href) {
    const bytes = new TextEncoder().encode(JSON.stringify({format:"brainbloom-share-v1", bundle}));
    if (bytes.length > maxBytes) throw new Error("This set is too large for a puzzle link. Share fewer puzzles or download draft JSON.");
    let payload = bytes, encoding = "j";
    if (typeof root.CompressionStream === "function") {
      const compressed = await bounded(new Blob([bytes]).stream().pipeThrough(new root.CompressionStream("gzip")), maxBytes);
      if (compressed.length < bytes.length) { payload = compressed; encoding = "g"; }
    }
    const url = new URL(href); url.hash = prefix + encoding + "." + base64(payload);
    if (url.href.length > maxLinkLength) throw new Error("This set is too large for a puzzle link. Share fewer puzzles or download draft JSON.");
    return url.href;
  }
  async function readShare(hash) {
    if (!hash.startsWith("#bb=")) return null;
    if (hash.length > maxLinkLength || !hash.startsWith(prefix)) throw new Error("This puzzle link is unsupported or too large.");
    const encoding = hash.slice(prefix.length, prefix.length + 1);
    if (hash[prefix.length + 1] !== "." || !["g", "j"].includes(encoding)) throw new Error("This puzzle link is not valid.");
    let payload;
    try {
      payload = unbase64(hash.slice(prefix.length + 2));
      if (encoding === "g") {
        if (typeof root.DecompressionStream !== "function") throw new Error("Open this compressed puzzle link in a current browser.");
        payload = await bounded(new Blob([payload]).stream().pipeThrough(new root.DecompressionStream("gzip")), maxBytes);
      }
      if (payload.length > maxBytes) throw new Error("This puzzle link is too large.");
      const value = JSON.parse(new TextDecoder("utf-8", {fatal:true}).decode(payload));
      if (!value || value.format !== "brainbloom-share-v1" || !value.bundle ||
          Object.keys(value).sort().join(",") !== "bundle,format") throw new Error("Invalid puzzle link data.");
      return value.bundle;
    } catch (error) {
      if (/current browser|too large/.test(error.message)) throw error;
      throw new Error("This puzzle link is damaged or incomplete. Ask for a new link.");
    }
  }
  root.BrainBloomPlayer = Object.freeze({shareURL, readShare, maxBytes, maxLinkLength});
})(window);
