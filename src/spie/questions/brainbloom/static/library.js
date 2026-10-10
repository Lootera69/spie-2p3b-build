/* Browser-local puzzle sets. Complete bundles are retained for verified replay. */
(function (root) {
  "use strict";
  const storageKey = "brainbloom-library-v1";
  const limits = Object.freeze({maxEntries:20, maxBytes:3 * 1024 * 1024,
    maxBundleBytes:2 * 1024 * 1024 - 8192, maxTitleLength:160});
  const types = new Set(["multiple-choice", "true-false", "type-answer", "crossword", "riddle", "wonder"]);
  const recordFields = ["id", "title", "savedAt", "updatedAt", "favorite", "count", "bundle", "progress"];

  function error(code, message) {
    const result = new Error(message);
    result.name = "BrainBloomLibraryError";
    result.code = code;
    return result;
  }
  function invalid() {
    throw error("invalid", "This puzzle set or its progress has an invalid format and could not be saved.");
  }
  function object(value) {
    if (value === null || typeof value !== "object" || Array.isArray(value)) return false;
    const prototype = Object.getPrototypeOf(value);
    return prototype === null || Object.getPrototypeOf(prototype) === null;
  }
  function strings(value) { return Array.isArray(value) && value.every(part => typeof part === "string"); }
  function bytes(text) {
    let size = 0;
    for (const character of text) {
      const code = character.codePointAt(0);
      size += code <= 0x7f ? 1 : code <= 0x7ff ? 2 : code <= 0xffff ? 3 : 4;
    }
    return size;
  }
  // Sorted keys make deduplication independent of object property insertion order.
  // Reject values JSON would silently discard, and never invoke custom toJSON/getters.
  function canonical(value, ancestors = new Set(), depth = 0) {
    if (depth > 64) invalid();
    if (value === null || typeof value === "string" || typeof value === "boolean") return JSON.stringify(value);
    if (typeof value === "number") {
      if (!Number.isFinite(value)) invalid();
      return JSON.stringify(value);
    }
    if ((!Array.isArray(value) && !object(value)) || ancestors.has(value)) invalid();
    if (Object.getOwnPropertySymbols(value).some(key => Object.prototype.propertyIsEnumerable.call(value, key))) invalid();
    ancestors.add(value);
    const keys = Object.keys(value);
    if (Array.isArray(value) && keys.length !== value.length) invalid();
    const parts = (Array.isArray(value) ? Array.from({length:value.length}, (_, i) => String(i)) : keys.sort()).map(key => {
      const property = Object.getOwnPropertyDescriptor(value, key);
      if (!property || !("value" in property)) invalid();
      const part = canonical(property.value, ancestors, depth + 1);
      return Array.isArray(value) ? part : JSON.stringify(key) + ":" + part;
    });
    ancestors.delete(value);
    return Array.isArray(value) ? "[" + parts.join(",") + "]" : "{" + parts.join(",") + "}";
  }
  function copy(value) { return JSON.parse(JSON.stringify(value)); }
  function validateBundle(bundle) {
    if (!object(bundle) || !Number.isSafeInteger(bundle.version) || bundle.version < 1 ||
        typeof bundle.generator !== "string" || !bundle.generator.trim() || !object(bundle.request) ||
        typeof bundle.request.category !== "string" || !types.has(bundle.request.qtype) ||
        !Array.isArray(bundle.items) || !bundle.items.length || bundle.items.length > 1000 ||
        !Array.isArray(bundle.proofs) || bundle.proofs.length !== bundle.items.length ||
        !Array.isArray(bundle.rejected) || !object(bundle.intendedImport) ||
        bundle.intendedImport.createdBy !== "symbolic-generator" ||
        bundle.intendedImport.reviewStatus !== "draft" || bundle.intendedImport.published !== false) invalid();
    bundle.items.forEach((item, index) => {
      if (!object(item) || !types.has(item.type) ||
          !["title", "question", "difficulty", "correctAnswer", "correctExplanation", "lessonContent"].every(key => typeof item[key] === "string") ||
          !title(item.title) || !strings(item.choices) ||
          (item.acceptedAnswers !== undefined && !strings(item.acceptedAnswers))) invalid();
      if (["type-answer", "riddle"].includes(item.type) && !strings(item.acceptedAnswers)) invalid();
      if (item.type === "wonder" && typeof item.sharePrompt !== "string") invalid();
      if (item.type === "crossword" && !object(item.crosswordData)) invalid();
      const proof = bundle.proofs[index];
      if (!object(proof) || typeof proof.method !== "string" || typeof proof.scope !== "string" ||
          (proof.steps !== undefined && !strings(proof.steps))) invalid();
    });
  }
  function validateProgress(progress, bundle) {
    if (!object(progress)) invalid();
    for (const [key, state] of Object.entries(progress)) {
      if (!/^(0|[1-9]\d*)$/.test(key) || Number(key) >= bundle.items.length || !object(state)) invalid();
      if ("selected" in state && state.selected !== null &&
          (!Number.isInteger(state.selected) || state.selected < 0 || state.selected >= bundle.items[Number(key)].choices.length)) invalid();
      if ("answer" in state && typeof state.answer !== "string") invalid();
      if ("fields" in state && !strings(state.fields)) invalid();
      if ("hints" in state && (!Number.isSafeInteger(state.hints) || state.hints < 0)) invalid();
      if ("revealed" in state && typeof state.revealed !== "boolean") invalid();
      for (const name of ["grid", "crossword"]) {
        if (name in state && !Array.isArray(state[name]) && !object(state[name])) invalid();
      }
    }
  }
  function title(value) {
    return value.replace(/[\u0000-\u001f\u007f]/g, " ").replace(/\s+/g, " ").trim();
  }
  function timestamp(value) {
    return typeof value === "string" && Number.isFinite(Date.parse(value)) && new Date(value).toISOString() === value;
  }
  function metadata(entry) {
    const {id, title, savedAt, updatedAt, favorite, count} = entry;
    return {id, title, savedAt, updatedAt, favorite, count};
  }
  function bundleId(text) {
    let first = 2166136261, second = 2246822507;
    for (let i = 0; i < text.length; i++) {
      first = Math.imul(first ^ text.charCodeAt(i), 16777619);
      second = Math.imul(second ^ text.charCodeAt(i), 3266489909);
    }
    return "bb-" + (first >>> 0).toString(16).padStart(8, "0") + (second >>> 0).toString(16).padStart(8, "0");
  }
  function now(previous) { return new Date(Math.max(Date.now(), previous ? Date.parse(previous) + 1 : 0)).toISOString(); }

  function create(storage) {
    function area() {
      try {
        const target = storage === undefined ? root.localStorage : storage;
        if (!target || typeof target.getItem !== "function" || typeof target.setItem !== "function") throw new Error();
        return target;
      } catch {
        throw error("unavailable", "Browser storage is unavailable. Allow local storage to save puzzle sets on this device.");
      }
    }
    function read() {
      let raw;
      try { raw = area().getItem(storageKey); }
      catch { throw error("unavailable", "Browser storage is unavailable. Allow local storage to use your saved puzzle library."); }
      if (raw === null) return {version:1, entries:[]};
      try {
        if (typeof raw !== "string" || bytes(raw) > limits.maxBytes) invalid();
        const data = JSON.parse(raw);
        if (!object(data) || data.version !== 1 || Object.keys(data).sort().join(",") !== "entries,version" ||
            !Array.isArray(data.entries) || data.entries.length > limits.maxEntries) invalid();
        const ids = new Set(), bundles = new Set();
        for (const entry of data.entries) {
          if (!object(entry) || Object.keys(entry).sort().join(",") !== recordFields.slice().sort().join(",") ||
              typeof entry.id !== "string" || !/^bb-[a-f0-9]{16}(?:-[1-9]\d*)?$/.test(entry.id) || ids.has(entry.id) ||
              typeof entry.title !== "string" || !entry.title || title(entry.title) !== entry.title || entry.title.length > limits.maxTitleLength ||
              !timestamp(entry.savedAt) || !timestamp(entry.updatedAt) || entry.updatedAt < entry.savedAt ||
              typeof entry.favorite !== "boolean") invalid();
          validateBundle(entry.bundle);
          validateProgress(entry.progress, entry.bundle);
          if (entry.count !== entry.bundle.items.length) invalid();
          const serialized = canonical(entry.bundle);
          if (bytes(serialized) > limits.maxBundleBytes || bundles.has(serialized)) invalid();
          canonical(entry.progress);
          ids.add(entry.id); bundles.add(serialized);
        }
        return data;
      } catch {
        throw error("corrupt", "Your saved puzzle library could not be read. Its stored data has been left unchanged.");
      }
    }
    function write(data) {
      const serialized = JSON.stringify(data);
      if (bytes(serialized) > limits.maxBytes) throw error("too-large", "The saved puzzle library would exceed its 3 MB limit. Remove a saved set before trying again. Your library was not changed.");
      try { area().setItem(storageKey, serialized); }
      catch (cause) {
        if (cause && (cause.name === "QuotaExceededError" || cause.name === "NS_ERROR_DOM_QUOTA_REACHED" || cause.code === 22 || cause.code === 1014)) {
          throw error("quota", "Browser storage is full. Remove a saved set or free browser space, then try again. Your library was not changed.");
        }
        throw error("unavailable", "Browser storage is unavailable. Your library was not changed.");
      }
    }
    function find(data, id) {
      const entry = data.entries.find(candidate => candidate.id === id);
      if (!entry) throw error("not-found", "This puzzle set is no longer in your library. Refresh the library and try again.");
      return entry;
    }
    return Object.freeze({
      list() {
        return read().entries.map(metadata).sort((a, b) => Number(b.favorite) - Number(a.favorite) ||
          b.updatedAt.localeCompare(a.updatedAt) || a.id.localeCompare(b.id));
      },
      get(id) { return copy(read().entries.find(entry => entry.id === id) || null); },
      save(bundle, progress = {}, optionalName) {
        const data = read();
        const serialized = canonical(bundle);
        if (bytes(serialized) > limits.maxBundleBytes) throw error("too-large", "This puzzle set is too large to save and reopen in this browser. Try saving a smaller set.");
        const savedBundle = JSON.parse(serialized), savedProgress = JSON.parse(canonical(progress));
        validateBundle(savedBundle); validateProgress(savedProgress, savedBundle);
        let entry = data.entries.find(candidate => canonical(candidate.bundle) === serialized);
        if (!entry && data.entries.length >= limits.maxEntries) throw error("full", "Your library already has 20 saved puzzle sets. Remove one before saving another.");
        if (optionalName !== undefined && typeof optionalName !== "string") invalid();
        const requestedTitle = optionalName === undefined ? "" : title(optionalName);
        if (requestedTitle.length > limits.maxTitleLength) throw error("invalid", "Use a puzzle set name of 160 characters or fewer.");
        if (!entry) {
          const base = bundleId(serialized);
          let id = base, collision = 0;
          while (data.entries.some(candidate => candidate.id === id)) id = base + "-" + (++collision);
          const savedAt = now();
          const defaultTitle = title(savedBundle.items[0].title) + (savedBundle.items.length > 1 ? ` + ${savedBundle.items.length - 1} more` : "");
          entry = {id, title:requestedTitle || defaultTitle.slice(0, limits.maxTitleLength).trim(), savedAt, updatedAt:savedAt,
            favorite:false, count:savedBundle.items.length, bundle:savedBundle, progress:savedProgress};
          data.entries.push(entry);
        } else {
          entry.progress = savedProgress;
          if (requestedTitle) entry.title = requestedTitle;
          entry.updatedAt = now(entry.updatedAt);
        }
        write(data);
        return copy(entry);
      },
      update(id, progress) {
        const data = read(), entry = find(data, id), savedProgress = JSON.parse(canonical(progress));
        validateProgress(savedProgress, entry.bundle);
        entry.progress = savedProgress; entry.updatedAt = now(entry.updatedAt);
        write(data);
        return copy(entry);
      },
      remove(id) {
        const data = read(), index = data.entries.findIndex(entry => entry.id === id);
        if (index === -1) return false;
        data.entries.splice(index, 1); write(data); return true;
      },
      favorite(id, value) {
        if (typeof value !== "boolean") invalid();
        const data = read(), entry = find(data, id);
        entry.favorite = value; entry.updatedAt = now(entry.updatedAt);
        write(data);
        return copy(entry);
      },
    });
  }
  root.BrainBloomLibrary = Object.freeze({create, storageKey, limits});
})(window);
