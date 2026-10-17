"use strict";
const byId = id => document.getElementById(id);
const themeKey = "brainbloom-theme";
const themeToggle = byId("theme-toggle");
function setTheme(theme) {
  const dark = theme === "dark";
  document.documentElement.dataset.theme = dark ? "dark" : "light";
  themeToggle.setAttribute("aria-pressed", String(dark));
  themeToggle.textContent = dark ? "Light mode" : "Dark mode";
}
try { setTheme(localStorage.getItem(themeKey) || "dark"); }
catch { setTheme("dark"); }
themeToggle.addEventListener("click", () => {
  const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
  setTheme(next);
  try { localStorage.setItem(themeKey, next); } catch { /* Switching still works without storage. */ }
});
window.addEventListener("storage", event => {
  if (event.key === themeKey) setTheme(event.newValue);
});
const studioHeadlines = [
  ["Thoughtfully made.", "Ready to challenge."],
  ["A little curiosity.", "A new possibility."],
  ["Start with an idea.", "Leave with a puzzle."],
  ["Make room for wonder.", "Give thought a turn."],
  ["Small clues.", "Big discoveries."],
  ["A fresh perspective.", "A finer puzzle."],
  ["Built with purpose.", "Played with curiosity."],
  ["Give ideas a shape.", "Give minds a challenge."],
  ["One good question.", "Many bright moments."],
  ["Follow your curiosity.", "Find your next puzzle."],
  ["A spark of an idea.", "A moment of discovery."],
  ["Create the challenge.", "Invite the discovery."],
  ["Make every clue count.", "Make every answer matter."],
  ["Where ideas connect.", "And puzzles begin."],
  ["Bring a little wonder.", "Build something clever."],
  ["Fresh ideas.", "Thoughtful challenges."],
  ["Set the scene.", "Spark the thinking."],
  ["A new way to ask.", "A new way to think."],
  ["Find the connection.", "Create the challenge."],
  ["Turn words into clues.", "Turn clues into wonder."],
  ["Designed to engage.", "Made to be explored."],
  ["A thoughtful beginning.", "A satisfying discovery."],
  ["Build a little mystery.", "Leave a trail of clues."],
  ["Let ideas bloom.", "Let curiosity lead."],
  ["Craft the question.", "Celebrate the thinking."],
  ["Beyond the obvious.", "Into the interesting."],
  ["Make something curious.", "Give someone a spark."],
  ["A place for ideas.", "A space for discovery."],
  ["From simple beginnings.", "To clever connections."],
  ["Explore a thought.", "Shape a challenge."],
  ["A clue worth following.", "A puzzle worth making."],
  ["Inspire a pause.", "Invite a new thought."],
  ["Keep the wonder.", "Sharpen the question."],
  ["Create with intention.", "Challenge with care."],
  ["Your next idea.", "Their next discovery."],
  ["Let the clues unfold.", "Let the thinking begin."],
  ["Thought takes shape.", "Curiosity takes over."],
  ["A fresh page.", "A clever possibility."],
  ["Something to ponder.", "Something to share."],
  ["Open a possibility.", "Create a little wonder."],
];
function refreshStudioHeadline() {
  let previous = -1;
  try {
    const saved = sessionStorage.getItem("brainbloom-studio-headline");
    if (saved !== null && /^\d+$/.test(saved)) previous = Number(saved);
  } catch { /* The headline also works when browser storage is unavailable. */ }
  const candidates = studioHeadlines.map((_, index) => index).filter(index => index !== previous);
  const selected = candidates[Math.floor(Math.random() * candidates.length)];
  const [first, second] = studioHeadlines[selected];
  byId("studio-headline").replaceChildren(document.createTextNode(first), document.createElement("br"), document.createTextNode(" " + second));
  try { sessionStorage.setItem("brainbloom-studio-headline", String(selected)); } catch { /* Optional storage. */ }
}
refreshStudioHeadline();
const form = byId("generator"), status = byId("status"), results = byId("results");
const typeLabels = {"multiple-choice":"Multiple Choice", "true-false":"True / False", "type-answer":"Type Answer", crossword:"Crossword", riddle:"Riddle", wonder:"Wonder"};
let bundle = null, busy = false, config = null, nextCard = 0;
const library = window.BrainBloomLibrary?.create();
let savedId = null, progress = {}, progressDirty = false, saveTimer = null, openingSaved = false;
let playMode = false, shareRevision = 0, pendingSharedHash = null;
let lookupRevision = 0, prepareTimer = null, prepared = null, meanings = {};
let activePane = "setup";
const paneScrollPositions = {setup:0, drafts:0};
const workspaceLayout = window.BrainBloomWorkspace.create({workspace:byId("workspace"), splitter:byId("workspace-splitter"), reset:byId("reset-layout")});
// Preserve numeric signs, fraction bars and decimal points when grading typed answers.
const normalize = text => text.normalize("NFKC").toLowerCase().replace(/\s+/g, " ").trim();
function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}
function saveNotice(message, failed = false) {
  byId("save-status").textContent = message;
  byId("save-status").classList.toggle("error", failed);
}
function flushProgress() {
  clearTimeout(saveTimer); saveTimer = null;
  if (!savedId || !library || !progressDirty) return true;
  try {
    library.update(savedId, progress);
    progressDirty = false;
    saveNotice("Saved in this browser · Progress saves automatically.");
    return true;
  } catch (error) { saveNotice(`Progress could not be saved. ${error.message}`, true); return false; }
}
function rememberProgress(index, state) {
  if (JSON.stringify(progress[index]) === JSON.stringify(state)) return;
  progress[index] = state;
  progressDirty = true;
  if (savedId) {
    clearTimeout(saveTimer);
    saveTimer = setTimeout(flushProgress, 250);
  }
}
function libraryButton(text, action) {
  const button = element("button", text, "small"); button.type = "button";
  button.addEventListener("click", action); return button;
}
function renderLibrary() {
  const list = byId("library-list"); list.replaceChildren();
  byId("library-status").textContent = "";
  try {
    if (!library) throw new Error("Puzzle storage is unavailable. You can still download your drafts.");
    const entries = library.list();
    byId("open-library").textContent = entries.length ? `My library (${entries.length})` : "My library";
    if (!entries.length) list.append(element("p", "No saved puzzles yet. Generate a puzzle, then choose Save puzzles.", "hint"));
    for (const entry of entries) {
      const row = element("article", undefined, "library-entry");
      row.append(element("h4", entry.title));
      row.append(element("p", `${entry.count} ${entry.count === 1 ? "puzzle" : "puzzles"} · Saved ${new Date(entry.updatedAt).toLocaleDateString()}`, "hint"));
      const actions = element("div", undefined, "library-actions");
      const open = libraryButton("Open & resume", () => openSaved(entry.id));
      open.disabled = busy || openingSaved;
      const favorite = libraryButton(entry.favorite ? "★ Favourite" : "☆ Favourite", () => {
        try { library.favorite(entry.id, !entry.favorite); renderLibrary(); }
        catch (error) { byId("library-status").textContent = error.message; }
      });
      favorite.setAttribute("aria-pressed", String(entry.favorite));
      const remove = libraryButton("Remove", () => {
        // Confirmation is inline and names the save, so accidental taps are recoverable.
        const confirm = element("div", undefined, "library-actions");
        confirm.append(element("span", "Remove this saved set from this browser?"));
        confirm.append(libraryButton("Remove saved set", () => {
          try {
            library.remove(entry.id);
            if (savedId === entry.id) { clearTimeout(saveTimer); savedId = null; saveNotice("Removed from library. The open puzzles are still available."); }
            renderLibrary(); updateControls();
          } catch (error) { byId("library-status").textContent = error.message; }
        }), libraryButton("Keep it", renderLibrary));
        actions.replaceWith(confirm);
      });
      actions.append(open, favorite, remove); row.append(actions); list.append(row);
    }
  } catch (error) { byId("library-status").textContent = error.message; }
}
function toggleLibrary(open) {
  byId("library-panel").hidden = !open;
  byId("open-library").setAttribute("aria-expanded", String(open));
  if (open) { renderLibrary(); showDrafts(); byId("library-title").focus(); }
  else byId("open-library").focus();
}
async function openSaved(id) {
  if (busy || openingSaved) return;
  if (!flushProgress()) return;
  openingSaved = true; busy = true; updateControls(); renderLibrary();
  results.inert = true;
  byId("library-status").textContent = "Checking this saved puzzle before reopening it…";
  try {
    const entry = library.get(id);
    if (!entry) throw new Error("This saved puzzle was removed. Refresh the library.");
    const response = await fetch("/api/verify-saved", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({bundle:entry.bundle})});
    const data = await response.json();
    if (!response.ok || !data.ok) throw new Error(data.error || "The saved puzzle could not be checked.");
    // An in-flight action may have completed while this bundle was verified.
    if (!flushProgress()) return;
    // Read again after replay so another tab's updated progress is respected.
    const latest = library.get(id);
    if (!latest) throw new Error("This saved puzzle was removed while opening it.");
    invalidatePlayer();
    bundle = entry.bundle; savedId = id; progress = latest.progress; progressDirty = false;
    results.replaceChildren();
    bundle.items.forEach((item, i) => results.append(showCard(item, bundle.proofs[i], i)));
    byId("download").disabled = false; byId("download").textContent = "Download draft JSON ↓";
    byId("drafts-tab").textContent = `Drafts (${bundle.items.length})`;
    status.className = ""; status.textContent = `${entry.title} · Saved puzzle checked. Your progress has been restored.`;
    saveNotice("Saved in this browser · Progress saves automatically.");
    toggleLibrary(false); showDrafts(true);
  } catch (error) {
    byId("library-status").textContent = error instanceof TypeError ? "Cannot reach the generator to check this save. Try again when connected." : error.message;
  } finally {
    openingSaved = false; busy = false; results.inert = false; updateControls();
    const message = byId("library-status").textContent;
    renderLibrary(); byId("library-status").textContent = message;
    resumeSharedLink();
  }
}
function populate(select, entries, preferred) {
  select.replaceChildren();
  entries.forEach(([value, label]) => { const option = element("option", label); option.value = value; select.append(option); });
  if (entries.some(([value]) => value === preferred)) select.value = preferred;
}
function chooseAutomaticActivity() {
  const select = byId("topic");
  if (![...select.options].some(option => option.value === "auto")) select.append(new Option("Choose for me", "auto"));
  select.value = "auto";
}
function readBrief() {
  const gridMode = byId("topic").value === "logic-grid";
  const grid = {groups:byId("grid-groups").value, rules:byId("grid-rules").value,
    complete:byId("grid-complete").value === "yes", target:byId("grid-target").value,
    answer_group:byId("grid-answer-group").value};
  const brief = {category:byId("category").value, qtype:byId("qtype").value,
    collection:byId("collection").value,
    activity:byId("topic").value, subject:gridMode ? "" : byId("subject").value.trim(), meanings:gridMode ? {} : {...meanings},
    difficulty:byId("difficulty").value, count:Number(byId("count").value),
    seed:Number(byId("seed").value), search_effort:byId("search-effort").value,
    instructions:byId("topic").value === "custom" ? byId("instructions").value : ""};
  if (gridMode || byId("topic").value === "custom") brief.grid = grid;
  if (brief.qtype === "crossword") brief.crossword_size = byId("crossword-size").value ? Number(byId("crossword-size").value) : null;
  if (["autopilot", "logic-grid"].includes(brief.activity)) {
    brief.reasoning_mode = byId("reasoning-mode").value;
    const minimum = byId("min-supporting-clues").value;
    brief.min_supporting_clues = minimum === "auto" ? "auto" : Number(minimum);
  }
  return brief;
}
function updateReasoningControls() {
  const supported = ["autopilot", "logic-grid"].includes(byId("topic").value);
  byId("reasoning-controls").hidden = !supported;
}
function renderGridSetup(data, brief) {
  const active = brief.activity === "logic-grid" || data.selected_activity === "logic-grid";
  byId("grid-controls").hidden = !active;
  byId("dictionary-controls").hidden = brief.activity === "logic-grid";
  byId("grid-diagnostics").replaceChildren();
  if (!active) return;
  byId("grid-status").textContent = data.message;
  if (!data.grid_analysis) return;
  const analysis = data.grid_analysis;
  populate(byId("grid-target"), [["", "Choose a value for me"], ...analysis.groups.flatMap(g => g.values.map(v => [v, `${v} (${g.name})`]))], byId("grid-target").value);
  updateGridAnswers(analysis.groups);
  if (analysis.witnesses.length) {
    const details = element("details"); details.append(element("summary", "Why more clues are needed"));
    details.append(element("p", "Both arrangements below satisfy your current rules. Added clues will distinguish them."));
    analysis.witnesses.forEach(rows => details.append(gridTable(rows)));
    byId("grid-diagnostics").append(details);
  }
}
function updateGridAnswers(groups) {
  const target = byId("grid-target").value;
  const compatible = groups.length > 1 ? groups.filter(g => !g.values.includes(target)) : [];
  populate(byId("grid-answer-group"), [["", "Choose for me"], ["Position", "Position"], ...compatible.map(g => [g.name, g.name])], byId("grid-answer-group").value);
}
function gridTable(rows) {
  const table = element("table", undefined, "logic-table"), head = element("tr");
  Object.keys(rows[0]).forEach(name => { const th = element("th", name); th.scope = "col"; head.append(th); });
  const thead = element("thead"); thead.append(head); table.append(thead);
  const body = element("tbody");
  rows.forEach(row => { const tr = element("tr"); Object.values(row).forEach(value => tr.append(element("td", String(value)))); body.append(tr); });
  table.append(body);
  const wrap = element("div", undefined, "table-scroll"); wrap.append(table); return wrap;
}
function logicGridPlayer(proof, card, index) {
  const cardBundle = bundle;
  const details = element("details"); details.open = true;
  details.append(element("summary", "Working grid"));
  if (proof.quality?.hints?.length) {
    const hints = element("details"); hints.append(element("summary", "Need a solving hint?"));
    const next = element("button", "Show next hint", "secondary next-hint"); next.type = "button";
    next.dataset.shown = "0";
    const text = element("div"); text.setAttribute("aria-live", "polite");
    let index = 0;
    next.addEventListener("click", () => {
      text.append(element("p", proof.quality.hints[index++]));
      next.dataset.shown = String(index);
      next.disabled = index === proof.quality.hints.length;
      if (next.disabled) next.textContent = "All hints shown";
    });
    hints.append(text, next);
    card.append(hints);
  }
  const table = element("table", undefined, "logic-table"), head = element("tr");
  ["Position", ...proof.model.groups.map(g => g.name)].forEach(name => { const th = element("th", name); th.scope = "col"; head.append(th); });
  const thead = element("thead"); thead.append(head); table.append(thead);
  const body = element("tbody"), inputs = [];
  proof.solution_table.forEach(row => {
    const tr = element("tr"), th = element("th", String(row.Position)); th.scope = "row"; tr.append(th);
    proof.model.groups.forEach(group => {
      const td = element("td"), select = element("select");
      select.setAttribute("aria-label", `${group.name} at position ${row.Position}`);
      populate(select, [["", "—"], ...group.values.map(v => [v,v])]);
      inputs.push({select, answer:row[group.name]}); td.append(select); tr.append(td);
    });
    body.append(tr);
  });
  table.append(body); const wrap = element("div", undefined, "table-scroll"); wrap.append(table);
  const feedback = element("p", "", "feedback"); feedback.setAttribute("role", "status");
  const check = element("button", "Check working grid", "secondary"); check.type = "button";
  let revision = 0;
  inputs.forEach(({select}) => select.addEventListener("change", () => {
    ++revision; feedback.textContent = "";
    inputs.forEach(({select}) => { select.classList.remove("grid-conflict"); select.removeAttribute("aria-invalid"); });
  }));
  check.addEventListener("click", async () => {
    const current = ++revision;
    check.disabled = true; feedback.textContent = "Checking your entries against the clues…";
    try {
      const response = await fetch("/api/check-grid", {method:"POST", headers:{"Content-Type":"application/json"},
        body:JSON.stringify({bundle:cardBundle, index, entries:inputs.map(({select}) => select.value)})});
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "The grid could not be checked.");
      if (current !== revision || !card.isConnected) return;
      feedback.textContent = data.message;
      feedback.dataset.result = data.correct ? "correct" : data.consistent ? "incomplete" : "incorrect";
      inputs.forEach(({select}) => { select.classList.remove("grid-conflict"); select.removeAttribute("aria-invalid"); });
      for (const conflict of data.conflicts) for (const cell of conflict.cells) {
        inputs[cell]?.select.classList.add("grid-conflict"); inputs[cell]?.select.setAttribute("aria-invalid", "true");
      }
    } catch (error) {
      if (current === revision && card.isConnected) feedback.textContent = error instanceof TypeError ? "Cannot reach the generator. Your entries are kept; try again." : error.message;
    } finally { check.disabled = card.classList.contains("revealed"); }
  });
  details.append(wrap, check, feedback); card.append(details);
  return () => { ++revision; inputs.forEach(({select, answer}) => { select.value = answer; select.disabled = true; select.classList.remove("grid-conflict"); select.removeAttribute("aria-invalid"); }); check.disabled = true; feedback.textContent = "The unique complete grid is shown."; };
}
function updateControls() {
  form.querySelectorAll("select, input, textarea, button:not(#reset-layout)").forEach(control => { control.disabled = busy || !config; });
  byId("generate").disabled = busy || !prepared?.ready;
  byId("save-puzzles").disabled = busy || !bundle?.items?.length || !library;
  byId("save-puzzles").textContent = savedId ? "Save progress" : "Save puzzles";
  for (const id of ["play-mode", "share-puzzles"]) byId(id).disabled = busy || !bundle?.items?.length;
  byId("copy-share").disabled = busy || !byId("share-link").value;
  byId("variation").disabled = busy || !prepared?.ready || (prepared.selected_activity === "word-wonder" && prepared.max_count === 1);
  if (prepared?.selected_activity === "logic-grid" && prepared.max_count === 1 && prepared.grid_analysis?.solution_count === 1) byId("variation").disabled = true;
  for (const option of byId("difficulty").options) {
    const rule = prepared?.difficulty_options.find(d => d.id === option.value);
    option.disabled = rule ? !rule.available : false;
  }
}
function updatePanes() {
  workspaceLayout.update({hasDrafts:Boolean(bundle?.items?.length), compact:window.innerWidth <= 760, playMode});
  if (playMode) {
    byId("pane-tabs").hidden = true; byId("setup-pane").hidden = true; byId("drafts-pane").hidden = false;
    byId("drafts-pane").setAttribute("role", "region"); byId("drafts-pane").setAttribute("aria-labelledby", "drafts-title");
    return;
  }
  const compact = window.innerWidth <= 760;
  byId("pane-tabs").hidden = !compact;
  for (const name of ["setup", "drafts"]) {
    const panel = byId(`${name}-pane`), tab = byId(`${name}-tab`);
    const scroll = name === "setup" ? byId("setup-scroll") : results;
    if (!panel.hidden) paneScrollPositions[name] = scroll.scrollTop;
    panel.hidden = compact && activePane !== name;
    if (!panel.hidden) scroll.scrollTop = paneScrollPositions[name];
    panel.setAttribute("role", compact ? "tabpanel" : "region");
    panel.setAttribute("aria-labelledby", `${name}-${compact ? "tab" : "title"}`);
    tab.setAttribute("aria-selected", String(activePane === name));
    tab.tabIndex = activePane === name ? 0 : -1;
  }
}
function showDrafts(focus = false) {
  activePane = "drafts";
  updatePanes();
  results.scrollTop = 0;
  if (focus) status.focus({preventScroll:true});
}
function renderInstructions(data, brief) {
  const custom = brief.activity === "custom";
  byId("instruction-controls").hidden = !custom;
  const feedback = byId("instruction-feedback"); feedback.replaceChildren();
  byId("apply-instructions").hidden = true;
  if (!custom || !data.instruction) return;
  const parsed = data.instruction;
  byId("instructions").setAttribute("aria-invalid", String(parsed.status === "clarify"));
  feedback.classList.toggle("needs-clarification", parsed.status === "clarify");
  feedback.append(element("strong", parsed.status === "clarify" ? "Please clarify" : "How I understand this"));
  if (parsed.status === "clarify") {
    parsed.issues.forEach(issue => feedback.append(element("p", issue)));
  } else {
    const fields = parsed.fields, activity = parsed.resolved_activity || fields.activity;
    feedback.append(element("p", `Activity: ${config.workshop.activities[activity]?.label || "Choose a compatible activity"}.`));
    const collection = parsed.resolved_collection || config.workshop.activities[activity]?.collection;
    if (collection) feedback.append(element("p", `Collection: ${config.workshop.collections[collection].label}. ${config.workshop.collections[collection].description}`));
    const labels = {subject:"Topics", count:"Puzzles", difficulty:"Challenge", qtype:"Answer format"};
    for (const [key, label] of Object.entries(labels)) {
      if (fields[key] !== undefined) feedback.append(element("p", `${label}: ${key === "qtype" ? typeLabels[fields[key]] : fields[key]}.`));
    }
    parsed.include_topics.forEach(topic => feedback.append(element("p", `Include topics: ${topic}.`)));
    if (parsed.status === "apply") {
      feedback.append(element("p", "These instructions change your settings. Apply them, or edit the text before generating."));
      byId("apply-instructions").hidden = false;
    } else feedback.append(element("p", "Matched using local rules. All other form settings still apply."));
  }
}
function renderPreparation(data, brief) {
  const focusedTopic = document.activeElement?.dataset?.topic;
  prepared = data;
  // Keep explicit overrides only, so context changes can re-rank automatic meanings.
  if (brief.activity !== "logic-grid" && data.selected_activity !== "logic-grid") {
    meanings = Object.fromEntries(Object.entries(brief.meanings).filter(([term, sense]) =>
      data.lookup.groups.some(group => group.term === term && group.choices.some(choice => choice.id === sense))));
  }
  const collection = data.selected_collection || brief.collection || "core";
  populate(byId("collection"), Object.entries(config.workshop.collections).map(([id, details]) => [id, details.label]), collection);
  if (collection !== "core") byId("activity-collections").open = true;
  byId("collection-notice").textContent = `${config.workshop.collections[collection].label}: ${data.policy_notice || config.workshop.collections[collection].description}`;
  const selected = config.workshop.activities[brief.activity]?.canonical_id || brief.activity;
  const choices = [];
  if (["core", "explore"].includes(collection) || brief.activity === "auto") choices.push(["auto", "Choose for me"]);
  choices.push(["custom", "Describe it in my own words…"]);
  data.activities.filter(a => a.visible && a.collection === collection && (a.available || a.id === selected)).sort((a, b) => a.menu_order - b.menu_order).forEach(a => choices.push([a.id, a.label]));
  populate(byId("topic"), choices, selected);
  byId("design-mode").value = brief.activity === "logic-grid" ? "manual" : "automatic";
  byId("autopilot-help").hidden = data.selected_activity !== "autopilot";
  byId("activity-help").textContent = data.description || "Choose settings that can include all your topics.";
  if (brief.activity === "auto" && data.selected_activity) {
    const activity = data.activities.find(a => a.id === data.selected_activity);
    byId("activity-help").textContent = `Suggested: ${activity.label}. ${activity.description}`;
  }
  if (brief.activity === "custom") byId("activity-help").textContent = "Write your brief below. Review the interpretation before creating your puzzle.";
  renderInstructions(data, brief);
  renderGridSetup(data, brief);
  updateReasoningControls();
  byId("reasoning-help").textContent = "The engine checks these requirements before showing a puzzle. Stricter choices may leave no suitable puzzle within the search. Clue counts apply to the question asked; deduction only requires a complete grid without assumed cases.";
  byId("crossword-controls").hidden = brief.qtype !== "crossword";
  if (brief.qtype === "crossword") {
    const recommendation = data.crossword_recommendation;
    byId("crossword-recommendation").textContent = recommendation
      ? (recommendation.recommended ? `Recommended: ${recommendation.recommended}×${recommendation.recommended}. ` : "") + recommendation.reason + (data.ready ? "" : ` ${data.message}`)
      : data.message;
    const entries = [["", "Use recommended size"], ...Array.from({length:11}, (_, i) => {
      const size = i + 5, option = data.crossword_size_options?.find(o => o.id === size);
      return [String(size), `${size}×${size}${option && !option.available ? " — words do not fit" : ""}`];
    })];
    populate(byId("crossword-size"), entries, brief.crossword_size == null ? "" : String(brief.crossword_size));
    const tiles = byId("crossword-size-tiles"); tiles.replaceChildren();
    const recommended = recommendation?.recommended;
    if (recommended) {
      const featured = element("button", undefined, "size-featured"); featured.type = "button";
      featured.append(element("span", "Recommended", "size-ribbon"), element("strong", `${recommended} × ${recommended}`), element("span", "A compact fit for your words", "size-caption"));
      featured.setAttribute("aria-pressed", String(brief.crossword_size == null));
      featured.addEventListener("click", () => { byId("crossword-size").value = ""; schedulePreparation(0); });
      tiles.append(featured);
    }
    const sizes = element("div", undefined, "size-options");
    for (let size = 5; size <= 15; size++) {
      const tile = element("button", `${size} × ${size}`, "size-tile"); tile.type = "button";
      const option = data.crossword_size_options?.find(o => o.id === size);
      tile.dataset.unavailable = String(Boolean(option && !option.available));
      tile.title = option?.reason || "Choose this board size";
      tile.setAttribute("aria-pressed", String(brief.crossword_size === size));
      tile.addEventListener("click", () => { byId("crossword-size").value = String(size); schedulePreparation(0); });
      sizes.append(tile);
    }
    tiles.append(sizes);
    byId("crossword-size").hidden = true;
    if (recommended) byId("crossword-recommendation").textContent = recommendation.reason + (data.ready ? "" : ` ${data.message}`);
  }
  byId("difficulty-controls").hidden = !data.difficulty_relevant;
  byId("difficulty-hint").textContent = data.difficulty_help || data.message;
  byId("search-controls").hidden = !data.search_relevant;
  byId("count").max = String(data.max_count);
  byId("count-hint").textContent = data.max_count < 20 ? `These settings allow up to ${data.max_count} distinct drafts.` : "Create up to 20 different drafts. Small word pools may support fewer.";
  byId("topic-status").textContent = data.message;
  if (data.uses_topics && data.lookup.using_category) byId("topic-status").textContent += brief.qtype === "crossword"
    ? " Using uncommon English vocabulary because topics are blank."
    : ` Using ${config.categories[brief.category]} vocabulary because topics are blank.`;
  byId("topic-meanings").replaceChildren();
  byId("topic-words").replaceChildren();
  const showTopics = Boolean(brief.subject || data.uses_topics);
  byId("word-preview").hidden = !showTopics;
  if (showTopics) {
    data.lookup.groups.forEach((group, index) => {
      const chosen = group.choices.find(choice => choice.id === group.selected);
      const summary = element("p", `${group.term} · ${chosen?.definition || "No usable meaning found"} (${group.word_count || 0} related words)`, "hint");
      byId("topic-meanings").append(summary);
      if (group.choices.length > 1) {
        const details = element("details"); details.dataset.topic = group.term;
        details.open = focusedTopic === group.term;
        details.append(element("summary", `Change meaning for ${group.term} (optional)`));
        if (group.selection_reason) details.append(element("p", group.selection_reason, "hint"));
        const label = element("label", `Meaning for ${group.term}`);
        const select = element("select"); select.id = `meaning-${index}`; label.htmlFor = select.id;
        select.dataset.topic = group.term;
        populate(select, [["", "Choose automatically"], ...group.choices.map(c => [c.id, c.source ? `${c.definition} (${c.source})` : c.definition])], meanings[group.term] || "");
        select.addEventListener("change", () => {
          if (select.value) meanings[group.term] = select.value; else delete meanings[group.term];
          schedulePreparation(0);
        });
        details.append(label, select);
        byId("topic-meanings").append(details);
      }
    });
    data.lookup.unknown_terms.forEach(term => {
      const suggestions = data.lookup.suggestions[term] || [];
      byId("topic-meanings").append(element("p", `Could not find “${term}”. ${suggestions.length ? "Try: " + suggestions.join(", ") + "." : "Check its spelling or use a broader word."}`, "hint"));
    });
    (data.lookup.context?.topics || []).forEach(topic => {
      const group = element("p", `${topic.term}: ${topic.words.join(", ")}`);
      byId("topic-words").append(group);
    });
  }
  updateControls();
  if (focusedTopic) {
    const replacement = [...byId("topic-meanings").querySelectorAll("select")].find(select => select.dataset.topic === focusedTopic);
    replacement?.focus({preventScroll:true});
  }
}
function schedulePreparation(delay = 180) {
  clearTimeout(prepareTimer);
  lookupRevision++;
  prepared = null;
  updateReasoningControls();
  byId("count").max = "20";
  byId("topic-status").textContent = "Checking how your choices fit together…";
  byId("crossword-recommendation").textContent = "Checking word lengths and crossings…";
  if (!byId("grid-controls").hidden) byId("grid-status").textContent = "Checking your groups and rules…";
  updateControls();
  prepareTimer = setTimeout(() => prepareBrief(), delay);
}
async function prepareBrief(brief = readBrief()) {
  clearTimeout(prepareTimer);
  const revision = ++lookupRevision;
  try {
    const response = await fetch("/api/prepare", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(brief)});
    const data = await response.json();
    if (revision !== lookupRevision) return null;
    if (!response.ok) throw new Error(data.error || "Could not check these settings.");
    renderPreparation(data, brief);
    return data;
  } catch (error) {
    if (revision === lookupRevision) {
      prepared = null;
      byId("topic-status").textContent = error instanceof TypeError ? "Cannot reach the workshop. Restart it and try again." : error.message;
      byId("crossword-recommendation").textContent = byId("topic-status").textContent;
      if (!byId("grid-controls").hidden) byId("grid-status").textContent = byId("topic-status").textContent;
      updateControls();
    }
    return null;
  }
}
function crosswordPlayer(item, card) {
  const data = item.crosswordData, inputs = [], cells = [];
  card.append(element("p", `${data.size}×${data.size} board · ${data.clues.length} entries`, "hint"));
  const grid = element("div", undefined, "crossword-grid");
  grid.style.gridTemplateColumns = `repeat(${data.size}, minmax(0, 1fr))`;
  grid.setAttribute("aria-label", `${data.size} by ${data.size} crossword grid`);
  const numbers = new Map(data.clues.map(c => [`${c.startRow},${c.startCol}`, c.number]));
  data.grid.forEach((row, r) => row.forEach((letter, c) => {
    const cell = element("div", undefined, letter === null ? "crossword-cell blocked" : "crossword-cell");
    if (letter !== null) {
      if (numbers.has(`${r},${c}`)) cell.append(element("span", String(numbers.get(`${r},${c}`)), "clue-number"));
      const input = element("input"); input.type = "text"; input.maxLength = 1;
      input.autocomplete = "off"; input.spellcheck = false;
      input.setAttribute("aria-label", `Row ${r + 1}, column ${c + 1}`);
      input.addEventListener("input", () => { input.value = input.value.replace(/[^a-z]/gi, "").toUpperCase(); input.classList.remove("wrong", "correct"); });
      input.addEventListener("keydown", event => {
        const delta = {ArrowLeft:[0,-1], ArrowRight:[0,1], ArrowUp:[-1,0], ArrowDown:[1,0]}[event.key];
        if (!delta) return;
        event.preventDefault(); let rr = r + delta[0], cc = c + delta[1];
        while (rr >= 0 && cc >= 0 && rr < data.size && cc < data.size) {
          const found = cells.find(x => x.r === rr && x.c === cc);
          if (found) { found.input.focus(); break; }
          rr += delta[0]; cc += delta[1];
        }
      });
      inputs.push({input, letter}); cells.push({r,c,input}); cell.append(input);
    }
    grid.append(cell);
  }));
  card.append(grid);
  const clues = element("div", undefined, "clue-lists");
  for (const direction of ["across", "down"]) {
    const group = element("div"); group.append(element("h4", direction === "across" ? "Across" : "Down"));
    data.clues.filter(c => c.direction === direction).forEach(c => group.append(element("p", `${c.number}. ${c.clue} (${c.answer.length})`)));
    clues.append(group);
  }
  const feedback = element("p", "", "feedback"); feedback.setAttribute("role", "status");
  const check = element("button", "Check grid", "secondary"); check.type = "button";
  check.addEventListener("click", () => {
    let correct = 0;
    inputs.forEach(({input, letter}) => {
      const matches = input.value.toUpperCase() === letter;
      input.classList.toggle("correct", matches); input.classList.toggle("wrong", !matches);
      if (matches) correct++;
    });
    feedback.textContent = correct === inputs.length ? "All letters match the clues and crossings." : `${correct}/${inputs.length} letters match. Keep working on the highlighted cells.`;
  });
  card.append(clues, check, feedback);
  return () => { inputs.forEach(({input, letter}) => { input.value = letter; input.disabled = true; input.classList.remove("wrong", "correct"); }); check.disabled = true; feedback.textContent = "The completed grid is shown."; };
}
function showCard(item, proof, index = 0) {
  const card = element("article", undefined, "card"), id = ++nextCard;
  let episodePlayer = null;
  const cardBundle = bundle, saved = progress[index] || {};
  card.dataset.index = String(index);
  const head = element("div", undefined, "card-head");
  const level = item.type === "wonder" ? "unscored" : item.difficulty;
  head.append(element("h3", item.title), element("span", `${typeLabels[item.type]} · ${level} · draft`, "badge"));
  card.append(head, element("p", item.question, "prompt"));
  if (proof.topic_coverage) card.append(element("p", `Includes every topic: ${proof.topic_coverage.map(t => t.term).join(", ")}.`, "hint"));
  const buttons = []; let selected = null, input = null, showGrid = null;
  if (proof.solution_table) {
    if (proof.autopilot) {
      const designed = element("details", undefined, "creator-detail"); designed.append(element("summary", "How BrainBloom designed this"));
      proof.autopilot.decisions.forEach(text => designed.append(element("p", text)));
      card.append(designed);
    }
    const clues = element("details", undefined, "creator-detail"); clues.append(element("summary", proof.autopilot ? "Clues invented by BrainBloom" : "Your rules and engine-added clues"));
    proof.authored_rules.forEach((r, i) => clues.append(element("p", `Your rule ${i + 1}: ${r.text}.`)));
    proof.added_rules.forEach(r => clues.append(element("p", `Added to ensure uniqueness: ${r.text}.`)));
    if (!proof.added_rules.length) clues.append(element("p", "No additional clues were needed."));
    card.append(clues); showGrid = logicGridPlayer(proof, card, index);
  }
  if (item.type === "crossword") showGrid = crosswordPlayer(item, card);
  else if (item.choices.length) {
    const options = element("div", undefined, "options");
    item.choices.forEach((choice, i) => {
      const button = element("button", undefined, "option"); button.type = "button";
      button.setAttribute("aria-pressed", "false");
      button.append(element("span", String.fromCharCode(65 + i), "letter"), element("span", choice));
      button.addEventListener("click", () => {
        selected = i;
        buttons.forEach((b, j) => { b.classList.toggle("chosen", j === i); b.setAttribute("aria-pressed", String(j === i)); });
      });
      buttons.push(button); options.append(button);
    });
    card.append(options);
  } else if (item.type !== "wonder") {
    const label = element("label", "Your answer"); label.htmlFor = `answer-${id}`;
    input = element("input"); input.type = "text"; input.id = label.htmlFor; input.autocomplete = "off"; input.maxLength = 2000;
    card.append(label, input);
    if (item.hintText) {
      const hints = element("details"); hints.append(element("summary", "Need a hint?"));
      item.hintText.split("\n").forEach(line => hints.append(element("p", line))); card.append(hints);
    }
  } else card.append(element("p", "Take a moment to consider it. Wonders are unscored.", "hint"));
  let feedbackRevision = 0, checking = false;
  const feedback = element("p", "", "answer-feedback"); feedback.setAttribute("role", "status");
  const check = element("button", "Check answer", "small check-answer"); check.type = "button";
  if (item.type !== "wonder" && item.type !== "crossword") {
    card.append(check, feedback);
    check.addEventListener("click", async () => {
      if (checking || card.classList.contains("revealed")) return;
      const answer = input ? input.value.trim() : selected === null ? "" : item.choices[selected];
      if (!answer) { feedback.textContent = input ? "Enter an answer first." : "Choose an answer first."; return; }
      const revision = ++feedbackRevision;
      checking = true; check.disabled = true; feedback.textContent = "Checking your answer…"; delete feedback.dataset.result;
      try {
        const response = await fetch("/api/check-answer", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({bundle:cardBundle, index, answer})});
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || "The answer could not be checked.");
        if (revision !== feedbackRevision || !card.isConnected) return;
        feedback.textContent = data.message;
        feedback.dataset.result = data.correct ? "correct" : "incorrect";
      } catch (error) {
        if (revision === feedbackRevision && card.isConnected) feedback.textContent = error instanceof TypeError ? "Cannot reach the generator. Your answer is kept; try checking again." : error.message;
      } finally { checking = false; check.disabled = card.classList.contains("revealed"); }
    });
  }
  const reveal = element("button", item.type === "wonder" ? "Reveal insight" : item.type === "crossword" ? "Reveal completed grid" : "Reveal answer & reasoning", "reveal"); reveal.type = "button";
  reveal.addEventListener("click", () => {
    card.classList.add("revealed"); ++feedbackRevision;
    check.disabled = true; feedback.textContent = "";
    const answer = element("div", undefined, "answer");
    buttons.forEach((button, i) => {
      button.disabled = true; button.classList.remove("chosen");
      if (normalize(item.choices[i]) === normalize(item.correctAnswer)) button.classList.add("correct");
      else if (i === selected) button.classList.add("wrong");
    });
    if (input) {
      input.disabled = true;
      if (input.value.trim()) answer.append(element("p", item.acceptedAnswers.some(a => normalize(a) === normalize(input.value)) ? "Your answer is correct." : "Your answer did not match an accepted answer."));
    }
    if (showGrid) showGrid();
    if (item.type !== "wonder" && item.type !== "crossword") answer.append(element("p", `Answer: ${item.correctAnswer}`));
    answer.append(element("p", item.correctExplanation, item.type === "crossword" ? "vocabulary-recap" : ""));
    if (!proof.learning_vocabulary) {
      const steps = element("ol", undefined, "reasoning-steps");
      (proof.steps || []).forEach(step => steps.append(element("li", step))); answer.append(steps);
    }
    if (item.type === "wonder") answer.append(element("p", item.sharePrompt));
    else {
      const lesson = element("details"); lesson.append(element("summary", "Teaching notes"));
      item.lessonContent.split("\n").forEach(line => lesson.append(element("p", line))); answer.append(lesson);
    }
    const details = element("details"); details.append(element("summary", "What was checked"));
    if (proof.solution_table) details.append(element("p", `${proof.authored_rules.length} creator rules preserved; ${proof.added_rules.length} extra clues added. The complete grid has exactly one solution, checked by Z3 and exhaustive enumeration.`));
    if (proof.solution_table && proof.quality) details.append(element("p", proof.quality.analysis_version ? `The explanation contains ${proof.quality.reasoning_steps} checked deductions, including ${proof.quality.case_checks} explicit case checks. ${proof.quality.propagation_complete ? "These deductions complete the grid." : "Further exhaustive checking is needed to complete this grid."} Difficulty and enjoyment have not been measured with players.` : `Legacy exhaustive clue-elimination analysis: ${proof.quality.reasoning_steps} narrowing steps. This is not a player-calibrated quality rating.`));
    if (proof.instruction_interpretation) details.append(element("p", "Your written instructions were matched to supported rules and checked against the saved puzzle settings."));
    if (proof.topic_coverage) proof.topic_coverage.forEach(t => details.append(element("p", `${t.term}: used ${t.used_words.join(", ")}.`)));
    if (proof.search) details.append(element("p", `Compared ${proof.search.budget} alternatives; ${proof.search.qualified} met the rules. The selected draft passed independent answer checks.`));
    details.append(element("p", proof.method.replaceAll("-", " ")), element("p", proof.scope));
    if (proof.quality?.warnings?.length) proof.quality.warnings.forEach(warning => details.append(element("p", `Quality note: ${warning}.`)));
    if (proof.source) details.append(element("p", `Dictionary: ${proof.source} · Meaning: ${proof.selected_sense}`));
    if (proof.quality) {
      const quality = proof.quality;
      const task = proof.player_task;
      if (task) {
        const label = item.type === "true-false" ? "Displayed claim" : "Displayed question";
        details.append(element("p", `${label} requires at least ${task.minimum_supporting_clues} supporting clues.`));
        details.append(element("p", `Identifying the card without answer choices requires at least ${task.open_answer_supporting_clues} clues.`));
        if (quality.all_clues_necessary_for_full_solution) details.append(element("p", "Every displayed clue is necessary for the unique full arrangement."));
      } else if (quality.minimum_supporting_clues) details.append(element("p", `Answer requires at least ${quality.minimum_supporting_clues} supporting clues.${quality.all_clues_necessary_for_full_solution ? " Every displayed clue is necessary for the unique full arrangement." : ""}`));
      if (quality.evidence_steps) details.append(element("p", `${quality.hypotheses} hypotheses, ${quality.evidence_steps} evidence steps. Exact posterior margin: ${quality.posterior_margin}.`));
      if (quality.expected_questions) details.append(element("p", `Optimal expected cost: ${quality.expected_questions} questions; checked by decision-tree rollout and exhaustive policy evaluation.`));
      details.append(element("p", "Search scores are family-specific structural heuristics, not ratings from players or comparisons with frontier AI models."));
    }
    if (proof.reasoning_constraints) {
      const checked = proof.reasoning_constraints;
      details.append(element("p", `Creator reasoning requirements checked: ${checked.deduction_only ? "the full grid is solved without assumed cases" : "a verified solving method is used"}. Exact clue support for this question: ${checked.minimum_supporting_clues}.`));
    }
    details.append(element("p", "Difficulty is a structural estimate. Wording, clue quality, and novelty still need editorial review."));
    answer.append(details); reveal.replaceWith(answer);
  });
  card.append(reveal);
  // Progress is a separate browser record; the replayable puzzle is never edited.
  const fields = [...card.querySelectorAll("input, select")];
  if (Array.isArray(saved.fields)) fields.forEach((field, i) => {
    if (typeof saved.fields[i] === "string") field.value = saved.fields[i].slice(0, 2000);
  });
  if (Number.isInteger(saved.selected) && buttons[saved.selected]) buttons[saved.selected].click();
  const hint = card.querySelector(".next-hint");
  if (hint && Number.isInteger(saved.hints) && saved.hints > 0) {
    for (let i = 0; i < Math.min(saved.hints, proof.quality.hints.length); i++) hint.click();
    hint.closest("details").open = true;
  }
  if (saved.revealed === true) reveal.click();
  const remember = () => rememberProgress(index, {
    selected, fields:fields.map(field => field.value),
    hints:Number(hint?.dataset.shown || 0), revealed:card.classList.contains("revealed"),
    ...(episodePlayer ? {episode:episodePlayer.snapshot()} : {}),
  });
  const edited = () => { ++feedbackRevision; feedback.textContent = ""; delete feedback.dataset.result; remember(); };
  card.addEventListener("input", edited); card.addEventListener("change", edited);
  card.addEventListener("click", event => {
    if (event.target.closest(".option")) edited();
    else remember();
  });
  if (proof.episode) {
    const quiz = element("details", undefined, "episode-quiz");
    quiz.append(element("summary", "First-move challenge & solution · contains spoilers"));
    [...card.children].filter(child => child !== head).forEach(child => quiz.append(child));
    episodePlayer = BrainBloomEpisode.mount(card, {
      bundle:cardBundle, index, saved:saved.episode,
      isCurrent:() => bundle === cardBundle,
      onProgress:() => remember(),
    });
    card.append(quiz);
  }
  return card;
}
async function generate(event) {
  event?.preventDefault();
  if (busy || !config || !form.reportValidity()) return;
  const brief = readBrief();
  if (!flushProgress()) return;
  let generating = false;
  busy = true;
  results.inert = true;
  updateControls();
  status.className = "";
  try {
    const plan = await prepareBrief(brief);
    if (!plan?.ready) throw new Error(plan?.message || "Please check the settings above.");
    const request = plan.request;
    if (!flushProgress()) return;
    invalidatePlayer();
    bundle = null; savedId = null; progress = {}; progressDirty = false; saveNotice(""); updateControls(); byId("download").disabled = true;
    results.setAttribute("aria-busy", "true"); results.replaceChildren();
    status.textContent = "Creating your puzzles and checking every answer…";
    generating = true;
    showDrafts(true);
    const response = await fetch("/api/generate", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(request)});
    const data = await response.json(); if (!response.ok) throw new Error(data.error || "Generation failed.");
    bundle = data;
    status.textContent = `${data.summary.accepted}/${data.summary.requested} drafts ready · ${config.categories[data.request.category]} · ${data.request.qtype === "wonder" ? "unscored" : data.request.difficulty}.`;
    if (data.dictionary) status.textContent += ` Topics: ${data.dictionary.label}.`;
    if (!data.summary.complete) { status.className = "error"; status.textContent += ` ${data.summary.rejected} withheld by editorial checks. Try a smaller batch or another family.`; }
    if (data.checks.platform_verifier?.status === "not-supported-for-type") status.textContent += " Native format checks passed; Studio's quiz-only verifier does not cover this type.";
    data.items.forEach((item, i) => results.append(showCard(item, data.proofs[i], i)));
    saveNotice(data.items.length ? "Save these puzzles to keep your progress in this browser." : "");
    data.rejected.forEach(rejection => results.append(element("div", "Draft withheld: " + (rejection.issues.map(x => typeof x === "string" ? x : `${x.rule}: ${x.message}`).join("; ") || "Editorial warnings; see report."), "reject")));
    byId("drafts-tab").textContent = `Drafts (${data.items.length})`;
    showDrafts(true);
    byId("download").textContent = data.items.length ? "Download draft JSON ↓" : "Download rejection report ↓"; byId("download").disabled = false;
  } catch (error) { status.className = "error"; status.textContent = error instanceof TypeError ? "Cannot reach the local generator. Restart it and try again." : error.message; if (generating) showDrafts(true); }
  finally {
    busy = false; results.inert = false; updateControls(); results.setAttribute("aria-busy", "false");
    resumeSharedLink();
  }
}
form.addEventListener("submit", generate);
function setPlayMode(enabled) {
  playMode = enabled;
  document.body.classList.toggle("play-mode", enabled);
  byId("play-mode").textContent = enabled ? "Back to creator" : "Play mode";
  byId("play-mode").setAttribute("aria-pressed", String(enabled));
  byId("drafts-title").textContent = enabled ? "Your puzzles" : "Your drafts";
  results.setAttribute("aria-label", enabled ? "Puzzles to play" : "Puzzle drafts");
  showDrafts();
}
function closeSharePanel(focus = true) {
  byId("share-panel").hidden = true;
  byId("share-puzzles").setAttribute("aria-expanded", "false");
  if (focus) byId("share-puzzles").focus();
  ++shareRevision;
}
function invalidatePlayer() {
  closeSharePanel(false);
  byId("share-link").value = ""; byId("share-status").textContent = "";
  if (!pendingSharedHash && location.hash.startsWith("#bb=")) history.replaceState(null, "", location.pathname + location.search);
}
byId("play-mode").addEventListener("click", () => setPlayMode(!playMode));
byId("share-puzzles").addEventListener("click", async () => {
  if (busy || !bundle?.items?.length) return;
  if (!byId("share-panel").hidden) { closeSharePanel(); return; }
  const revision = ++shareRevision, sharedBundle = bundle;
  byId("share-panel").hidden = false; byId("share-puzzles").setAttribute("aria-expanded", "true");
  byId("share-link").value = ""; byId("copy-share").disabled = true;
  byId("copy-share").textContent = "Copy link";
  byId("share-status").textContent = "Preparing your puzzle link…";
  try {
    const url = await window.BrainBloomPlayer.shareURL(sharedBundle, location.href);
    if (revision !== shareRevision || sharedBundle !== bundle) return;
    byId("share-link").value = url; byId("copy-share").disabled = false;
    byId("share-status").textContent = "Recipients start with blank puzzles and can reveal answers when ready.";
    if (["localhost", "127.0.0.1", "[::1]"].includes(location.hostname)) byId("share-status").textContent += " This local preview link works only on this computer. Create links on your deployed website to share with others.";
    byId("share-link").focus(); byId("share-link").select();
  } catch (error) { if (revision === shareRevision) byId("share-status").textContent = error.message; }
});
byId("copy-share").addEventListener("click", async () => {
  const link = byId("share-link");
  if (!link.value) return;
  const revision = shareRevision;
  try {
    await navigator.clipboard.writeText(link.value);
    if (revision === shareRevision) byId("copy-share").textContent = "Copied";
  } catch {
    if (revision !== shareRevision) return;
    link.focus(); link.select();
    byId("share-status").textContent = "Select and copy the link from the field above.";
  }
});
byId("close-share").addEventListener("click", () => closeSharePanel());
byId("share-panel").addEventListener("keydown", event => {
  if (event.key === "Escape") { event.preventDefault(); closeSharePanel(); }
});
function resumeSharedLink() {
  if (!pendingSharedHash || busy || !config) return;
  const pending = pendingSharedHash; pendingSharedHash = null;
  if (location.hash === pending) loadSharedLink();
}
async function loadSharedLink() {
  if (!location.hash.startsWith("#bb=")) { pendingSharedHash = null; return; }
  if (busy || !config) { pendingSharedHash = location.hash; return; }
  if (!flushProgress()) return;
  pendingSharedHash = null;
  const openedHash = location.hash;
  busy = true; results.inert = true; updateControls();
  status.className = ""; status.textContent = "Checking the shared puzzles before opening them…";
  showDrafts(true);
  try {
    const shared = await window.BrainBloomPlayer.readShare(openedHash);
    const response = await fetch("/api/verify-saved", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({bundle:shared})});
    const data = await response.json();
    if (location.hash !== openedHash) return;
    if (!response.ok || !data.ok || !data.count) throw new Error(data.error || "This link has no playable puzzles.");
    if (!flushProgress()) return;
    closeSharePanel(false);
    byId("share-link").value = "";
    bundle = shared; savedId = null; progress = {}; progressDirty = false;
    results.replaceChildren(); bundle.items.forEach((item, i) => results.append(showCard(item, bundle.proofs[i], i)));
    byId("download").disabled = false; byId("download").textContent = "Download draft JSON ↓";
    byId("drafts-tab").textContent = `Drafts (${bundle.items.length})`;
    setPlayMode(true);
    status.textContent = `${bundle.items.length} shared ${bundle.items.length === 1 ? "puzzle" : "puzzles"} checked and ready to play.`;
    saveNotice("Save these puzzles to keep your progress in this browser.");
  } catch (error) {
    status.className = "error";
    status.textContent = error instanceof TypeError ? "Cannot reach the generator to check this link. Try again when connected." : error.message;
  } finally {
    busy = false; results.inert = false; updateControls();
    resumeSharedLink();
  }
}
window.addEventListener("hashchange", loadSharedLink);
byId("save-puzzles").addEventListener("click", () => {
  if (!bundle?.items?.length || !library || busy) return;
  clearTimeout(saveTimer);
  try {
    const entry = library.save(bundle, progress);
    savedId = entry.id; progressDirty = false; saveNotice("Saved in this browser · Progress saves automatically.");
    renderLibrary(); updateControls();
  } catch (error) { saveNotice(error.message, true); }
});
byId("open-library").addEventListener("click", () => toggleLibrary(byId("library-panel").hidden));
byId("close-library").addEventListener("click", () => toggleLibrary(false));
byId("library-panel").addEventListener("keydown", event => {
  if (event.key === "Escape") { event.preventDefault(); toggleLibrary(false); }
});
window.addEventListener("pagehide", flushProgress);
document.addEventListener("visibilitychange", () => { if (document.visibilityState === "hidden") flushProgress(); });
window.addEventListener("storage", event => {
  if (event.key !== null && event.key !== window.BrainBloomLibrary?.storageKey) return;
  try {
    if (savedId && !library.get(savedId)) {
      savedId = null; clearTimeout(saveTimer);
      saveNotice("This save was removed in another tab. Save puzzles to keep your current progress.");
      updateControls();
    }
  } catch (error) { saveNotice(error.message, true); }
  renderLibrary();
});
renderLibrary();
for (const id of ["category", "qtype", "topic", "difficulty", "search-effort", "reasoning-mode", "min-supporting-clues"]) {
  byId(id).addEventListener("change", () => {
    if (id === "topic") {
      byId("grid-controls").hidden = byId("topic").value !== "logic-grid";
      byId("dictionary-controls").hidden = byId("topic").value === "logic-grid";
      byId("instruction-controls").hidden = byId("topic").value !== "custom";
      if (byId("topic").value === "custom") byId("instructions").focus();
    }
    if (id === "category" || id === "qtype") {
      if (id === "qtype" && ["wonder", "crossword"].includes(byId("qtype").value)) byId("collection").value = byId("qtype").value === "wonder" ? "explore" : "core";
      else if (id === "qtype" && byId("collection").value === "explore") byId("collection").value = "core";
      const activity = config.workshop.activities[byId("topic").value];
      if (activity && (!activity.categories.includes(byId("category").value) || !activity.types.includes(byId("qtype").value))) chooseAutomaticActivity();
    }
    schedulePreparation(0);
  });
}
byId("collection").addEventListener("change", () => {
  const collection = byId("collection").value;
  if (collection === "explore") byId("qtype").value = "wonder";
  else if (byId("qtype").value === "wonder" || (collection !== "core" && byId("qtype").value === "crossword")) byId("qtype").value = "multiple-choice";
  const candidates = Object.entries(config.workshop.activities).filter(([, activity]) =>
    activity.visible && activity.collection === collection && activity.categories.includes(byId("category").value) && activity.types.includes(byId("qtype").value));
  const selected = ["core", "explore"].includes(collection) ? "auto" : candidates[0]?.[0] || "custom";
  const choices = [["auto", "Choose for me"], ["custom", "Describe it in my own words…"], ...candidates.map(([id, activity]) => [id, activity.label])];
  populate(byId("topic"), choices, selected);
  schedulePreparation(0);
});
byId("subject").addEventListener("input", () => {
  if (byId("subject").value.trim() && config?.workshop.activities[byId("topic").value]?.uses_topics === false) chooseAutomaticActivity();
  byId("topic-meanings").replaceChildren(); byId("topic-words").replaceChildren();
  schedulePreparation();
});
byId("instructions").addEventListener("input", () => {
  byId("apply-instructions").hidden = true;
  byId("instruction-feedback").textContent = "Checking your instructions…";
  schedulePreparation(250);
});
for (const id of ["grid-groups", "grid-rules"]) byId(id).addEventListener("input", () => {
  if (id === "grid-groups") { byId("grid-target").value = ""; byId("grid-answer-group").value = ""; }
  schedulePreparation(350);
});
for (const id of ["grid-complete", "grid-target", "grid-answer-group"]) byId(id).addEventListener("change", () => {
  if (id === "grid-target" && prepared?.grid_analysis) updateGridAnswers(prepared.grid_analysis.groups);
  schedulePreparation(0);
});
byId("crossword-size").addEventListener("change", () => schedulePreparation(0));
function loadGridExample() {
  const example = config.workshop.grid_example;
  byId("grid-groups").value = example.groups; byId("grid-rules").value = example.rules;
  byId("grid-complete").value = "yes";
  populate(byId("grid-target"), [["", "Choose a value for me"], [example.target, example.target]], example.target);
  populate(byId("grid-answer-group"), [["", "Choose for me"], ["Position", "Position"], [example.answer_group, example.answer_group]], example.answer_group);
}
byId("grid-example").addEventListener("click", () => { loadGridExample(); schedulePreparation(0); });
byId("design-mode").addEventListener("change", () => {
  byId("collection").value = "core";
  const manual = byId("design-mode").value === "manual";
  if (manual) {
    if (!["multiple-choice", "true-false", "type-answer", "riddle"].includes(byId("qtype").value)) byId("qtype").value = "multiple-choice";
    if (![...byId("topic").options].some(option => option.value === "logic-grid")) byId("topic").append(new Option("Create a custom logic grid", "logic-grid"));
    byId("creator-mode").open = true;
  }
  if (manual) byId("topic").value = "logic-grid";
  else chooseAutomaticActivity();
  schedulePreparation(0);
});
byId("try-autopilot").addEventListener("click", () => {
  byId("collection").value = "core";
  byId("category").value = "logic"; byId("qtype").value = "multiple-choice";
  if (![...byId("topic").options].some(o => o.value === "autopilot")) byId("topic").append(new Option("Design a clue puzzle for me", "autopilot"));
  byId("topic").value = "autopilot"; byId("subject").value = "animals";
  meanings = {}; byId("difficulty").value = "easy"; byId("count").value = "1";
  byId("reasoning-mode").value = "auto"; byId("min-supporting-clues").value = "auto";
  byId("design-mode").value = "automatic";
  schedulePreparation(0);
});
byId("apply-instructions").addEventListener("click", () => {
  const changes = prepared?.instruction?.changes;
  if (!changes || busy) return;
  for (const [key, value] of Object.entries(changes)) byId(key).value = String(value);
  schedulePreparation(0);
});
for (const name of ["setup", "drafts"]) {
  byId(`${name}-tab`).addEventListener("click", () => { activePane = name; updatePanes(); });
  byId(`${name}-tab`).addEventListener("keydown", event => {
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    activePane = event.key === "Home" ? "setup" : event.key === "End" ? "drafts" : name === "setup" ? "drafts" : "setup";
    updatePanes(); byId(`${activePane}-tab`).focus();
  });
}
window.addEventListener("resize", updatePanes);
updatePanes();
byId("count").addEventListener("input", () => schedulePreparation());
byId("seed").addEventListener("input", () => schedulePreparation());
byId("lookup").addEventListener("click", () => schedulePreparation(0));
byId("variation").addEventListener("click", () => {
  const step = Math.max(1, Number(byId("count").value)) * 30 + 1;
  byId("seed").value = (Number(byId("seed").value) + step) % 4294967296;
  form.requestSubmit();
});
byId("download").addEventListener("click", () => {
  if (!bundle) return;
  const url = URL.createObjectURL(new Blob([JSON.stringify(bundle, null, 2) + "\n"], {type:"application/json"}));
  const link = element("a"); link.href = url; link.download = `brainbloom-${bundle.request.category}-${bundle.request.qtype}-${bundle.request.seed}.draft.json`;
  document.body.append(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000);
});
fetch("/api/config").then(response => { if (!response.ok) throw new Error("Setup unavailable"); return response.json(); }).then(async data => {
  config = data; populate(byId("category"), Object.entries(data.categories), "logic");
  loadGridExample();
  populate(byId("qtype"), data.types.map(type => [type, typeLabels[type]]), "multiple-choice");
  updateControls();
  data.dictionary.examples.forEach(word => { const option = element("option"); option.value = word; byId("topic-examples").append(option); });
  data.workshop.instruction_examples.forEach(text => {
    const button = element("button", text, "instruction-example"); button.type = "button";
    button.addEventListener("click", () => { byId("instructions").value = text; schedulePreparation(0); });
    byId("instruction-examples").append(button);
  });
  byId("setup").textContent = (data.bank ? `${data.bank.rows_compared.toLocaleString()} bank questions available for lexical duplicate checks. ` : "No existing bank configured. ") + (data.platform_verifier ? "Studio quiz editorial checks enabled. Crossword and Wonder use native format checks." : "Studio editorial checks not configured.");
  const dictionary = data.dictionary;
  byId("setup").textContent += ` Vocabulary: ${dictionary.indexed_terms.toLocaleString()} lookup terms; ${dictionary.unique_topic_count} authored topics across ${dictionary.pack_version_count} pack versions${dictionary.wordnet_available ? "; Princeton WordNet" : ""}${dictionary.oewn_available ? "; Open English WordNet 2024" : ""}.`;
  if (dictionary.sources) {
    const details = element("details"); details.append(element("summary", "Vocabulary sources and usable coverage"));
    details.append(element("p", "Meaning records can overlap across sources. Usable entries pass a letter and length filter; this does not guarantee a suitable puzzle or add reasoning skills."));
    dictionary.sources.forEach(source => details.append(element("p", `${source.name}: ${source.indexed_terms.toLocaleString()} lookup terms; ${source.unique_senses.toLocaleString()} source-qualified meanings; ${source.alias_terms.toLocaleString()} aliases; ${source.usable_entry_pairs.toLocaleString()} usable word/meaning pairs; ${source.relationships.toLocaleString()} ${source.relation_scope}.`)));
    byId("setup").after(details);
  }
  byId("setup").textContent += data.history?.enabled ? ` Saved-design comparison enabled (${data.history.designs} previous designs).` : " Cross-session design comparison is off.";
  await prepareBrief();
  await loadSharedLink();
}).catch(() => { byId("setup").textContent = "Could not load the supported families. Restart the generator and reload this page."; });
