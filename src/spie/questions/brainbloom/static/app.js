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
let lookupRevision = 0, prepareTimer = null, prepared = null, meanings = {};
let activePane = "setup";
const paneScrollPositions = {setup:0, drafts:0};
// Preserve numeric signs, fraction bars and decimal points when grading typed answers.
const normalize = text => text.normalize("NFKC").toLowerCase().replace(/\s+/g, " ").trim();
function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}
function populate(select, entries, preferred) {
  select.replaceChildren();
  entries.forEach(([value, label]) => { const option = element("option", label); option.value = value; select.append(option); });
  if (entries.some(([value]) => value === preferred)) select.value = preferred;
}
function readBrief() {
  const gridMode = byId("topic").value === "logic-grid";
  const grid = {groups:byId("grid-groups").value, rules:byId("grid-rules").value,
    complete:byId("grid-complete").value === "yes", target:byId("grid-target").value,
    answer_group:byId("grid-answer-group").value};
  const brief = {category:byId("category").value, qtype:byId("qtype").value,
    activity:byId("topic").value, subject:gridMode ? "" : byId("subject").value.trim(), meanings:gridMode ? {} : {...meanings},
    difficulty:byId("difficulty").value, count:Number(byId("count").value),
    seed:Number(byId("seed").value), search_effort:byId("search-effort").value,
    instructions:byId("topic").value === "custom" ? byId("instructions").value : ""};
  if (gridMode || byId("topic").value === "custom") brief.grid = grid;
  if (brief.qtype === "crossword") brief.crossword_size = byId("crossword-size").value ? Number(byId("crossword-size").value) : null;
  return brief;
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
function logicGridPlayer(proof, card) {
  const details = element("details"); details.open = true;
  details.append(element("summary", "Working grid"));
  if (proof.quality?.hints?.length) {
    const hints = element("details"); hints.append(element("summary", "Need a solving hint?"));
    const next = element("button", "Show next hint", "secondary"); next.type = "button";
    const text = element("div"); text.setAttribute("aria-live", "polite");
    let index = 0;
    next.addEventListener("click", () => {
      text.append(element("p", proof.quality.hints[index++]));
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
  check.addEventListener("click", () => {
    const matches = inputs.filter(({select, answer}) => select.value === answer).length;
    feedback.textContent = `${matches}/${inputs.length} entries match the unique solution.`;
  });
  details.append(wrap, check, feedback); card.append(details);
  return () => { inputs.forEach(({select, answer}) => { select.value = answer; select.disabled = true; }); check.disabled = true; feedback.textContent = "The unique complete grid is shown."; };
}
function updateControls() {
  form.querySelectorAll("select, input, textarea, button").forEach(control => { control.disabled = busy || !config; });
  byId("generate").disabled = busy || !prepared?.ready;
  byId("variation").disabled = busy || !prepared?.ready || (prepared.selected_activity === "word-wonder" && prepared.max_count === 1);
  if (prepared?.selected_activity === "logic-grid" && prepared.max_count === 1 && prepared.grid_analysis?.solution_count === 1) byId("variation").disabled = true;
  for (const option of byId("difficulty").options) {
    const rule = prepared?.difficulty_options.find(d => d.id === option.value);
    option.disabled = rule ? !rule.available : false;
  }
}
function updatePanes() {
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
    const fields = parsed.fields, activity = fields.activity || parsed.resolved_activity;
    feedback.append(element("p", `Activity: ${config.workshop.activities[activity]?.label || "Choose a compatible activity"}.`));
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
  const choices = [["auto", "Choose for me"], ["custom", "Describe it in my own words…"]];
  data.activities.filter(a => (a.available || a.id === brief.activity) && (a.id !== "logic-grid" || brief.activity === "logic-grid")).forEach(a => choices.push([a.id, a.label]));
  populate(byId("topic"), choices, brief.activity);
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
  if (data.uses_topics && data.lookup.using_category) byId("topic-status").textContent += ` Using ${config.categories[brief.category]} vocabulary because topics are blank.`;
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
function showCard(item, proof) {
  const card = element("article", undefined, "card"), id = ++nextCard;
  const head = element("div", undefined, "card-head");
  const level = item.type === "wonder" ? "unscored" : item.difficulty;
  head.append(element("h3", item.title), element("span", `${typeLabels[item.type]} · ${level} · draft`, "badge"));
  card.append(head, element("p", item.question, "prompt"));
  if (proof.topic_coverage) card.append(element("p", `Includes every topic: ${proof.topic_coverage.map(t => t.term).join(", ")}.`, "hint"));
  const buttons = []; let selected = null, input = null, showGrid = null;
  if (proof.solution_table) {
    if (proof.autopilot) {
      const designed = element("details"); designed.append(element("summary", "How BrainBloom designed this"));
      proof.autopilot.decisions.forEach(text => designed.append(element("p", text)));
      card.append(designed);
    }
    const clues = element("details"); clues.append(element("summary", proof.autopilot ? "Clues invented by BrainBloom" : "Your rules and engine-added clues"));
    proof.authored_rules.forEach((r, i) => clues.append(element("p", `Your rule ${i + 1}: ${r.text}.`)));
    proof.added_rules.forEach(r => clues.append(element("p", `Added to ensure uniqueness: ${r.text}.`)));
    if (!proof.added_rules.length) clues.append(element("p", "No additional clues were needed."));
    card.append(clues); showGrid = logicGridPlayer(proof, card);
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
    input = element("input"); input.type = "text"; input.id = label.htmlFor; input.autocomplete = "off";
    card.append(label, input);
    if (item.hintText) {
      const hints = element("details"); hints.append(element("summary", "Need a hint?"));
      item.hintText.split("\n").forEach(line => hints.append(element("p", line))); card.append(hints);
    }
  } else card.append(element("p", "Take a moment to consider it. Wonders are unscored.", "hint"));
  const reveal = element("button", item.type === "wonder" ? "Reveal insight" : item.type === "crossword" ? "Reveal completed grid" : "Reveal answer & reasoning", "reveal"); reveal.type = "button";
  reveal.addEventListener("click", () => {
    const answer = element("div", undefined, "answer");
    buttons.forEach((button, i) => {
      button.disabled = true; button.classList.remove("chosen");
      if (item.choices[i] === item.correctAnswer) button.classList.add("correct");
      else if (i === selected) button.classList.add("wrong");
    });
    if (input) {
      input.disabled = true;
      if (input.value.trim()) answer.append(element("p", item.acceptedAnswers.some(a => normalize(a) === normalize(input.value)) ? "Your answer is correct." : "Your answer did not match an accepted answer."));
    }
    if (showGrid) showGrid();
    if (item.type !== "wonder" && item.type !== "crossword") answer.append(element("p", `Answer: ${item.correctAnswer}`));
    answer.append(element("p", item.correctExplanation));
    const steps = element("ol", undefined, "reasoning-steps");
    (proof.steps || []).forEach(step => steps.append(element("li", step))); answer.append(steps);
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
      if (quality.minimum_supporting_clues) details.append(element("p", `Answer requires at least ${quality.minimum_supporting_clues} supporting clues.${quality.all_clues_necessary_for_full_solution ? " Every displayed clue is necessary for the unique full arrangement." : ""}`));
      if (quality.evidence_steps) details.append(element("p", `${quality.hypotheses} hypotheses, ${quality.evidence_steps} evidence steps. Exact posterior margin: ${quality.posterior_margin}.`));
      if (quality.expected_questions) details.append(element("p", `Optimal expected cost: ${quality.expected_questions} questions; checked by decision-tree rollout and exhaustive policy evaluation.`));
      details.append(element("p", "Search scores are family-specific structural heuristics, not ratings from players or comparisons with frontier AI models."));
    }
    details.append(element("p", "Difficulty is a structural estimate. Wording, clue quality, and novelty still need editorial review."));
    answer.append(details); reveal.replaceWith(answer);
  });
  card.append(reveal); return card;
}
async function generate(event) {
  event?.preventDefault();
  if (busy || !config || !form.reportValidity()) return;
  const brief = readBrief();
  let generating = false;
  busy = true;
  updateControls();
  status.className = "";
  try {
    const plan = await prepareBrief(brief);
    if (!plan?.ready) throw new Error(plan?.message || "Please check the settings above.");
    const request = plan.request;
    bundle = null; byId("download").disabled = true;
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
    data.items.forEach((item, i) => results.append(showCard(item, data.proofs[i])));
    data.rejected.forEach(rejection => results.append(element("div", "Draft withheld: " + (rejection.issues.map(x => typeof x === "string" ? x : `${x.rule}: ${x.message}`).join("; ") || "Editorial warnings; see report."), "reject")));
    byId("drafts-tab").textContent = `Drafts (${data.items.length})`;
    showDrafts(true);
    byId("download").textContent = data.items.length ? "Download draft JSON ↓" : "Download rejection report ↓"; byId("download").disabled = false;
  } catch (error) { status.className = "error"; status.textContent = error instanceof TypeError ? "Cannot reach the local generator. Restart it and try again." : error.message; if (generating) showDrafts(true); }
  finally { busy = false; updateControls(); results.setAttribute("aria-busy", "false"); }
}
form.addEventListener("submit", generate);
for (const id of ["category", "qtype", "topic", "difficulty", "search-effort"]) {
  byId(id).addEventListener("change", () => {
    if (id === "topic") {
      byId("grid-controls").hidden = byId("topic").value !== "logic-grid";
      byId("dictionary-controls").hidden = byId("topic").value === "logic-grid";
      byId("instruction-controls").hidden = byId("topic").value !== "custom";
      if (byId("topic").value === "custom") byId("instructions").focus();
    }
    if (id === "category" || id === "qtype") {
      const activity = config.workshop.activities[byId("topic").value];
      if (activity && (!activity.categories.includes(byId("category").value) || !activity.types.includes(byId("qtype").value))) byId("topic").value = "auto";
    }
    schedulePreparation(0);
  });
}
byId("subject").addEventListener("input", () => {
  if (byId("subject").value.trim() && config?.workshop.activities[byId("topic").value]?.uses_topics === false) byId("topic").value = "auto";
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
  const manual = byId("design-mode").value === "manual";
  if (manual) {
    if (!["multiple-choice", "true-false", "type-answer", "riddle"].includes(byId("qtype").value)) byId("qtype").value = "multiple-choice";
    byId("topic").append(new Option("Create a custom logic grid", "logic-grid"));
    byId("creator-mode").open = true;
  }
  byId("topic").value = manual ? "logic-grid" : "auto";
  schedulePreparation(0);
});
byId("try-autopilot").addEventListener("click", () => {
  byId("category").value = "logic"; byId("qtype").value = "multiple-choice";
  if (![...byId("topic").options].some(o => o.value === "autopilot")) byId("topic").append(new Option("Design a clue puzzle for me", "autopilot"));
  byId("topic").value = "autopilot"; byId("subject").value = "animals";
  meanings = {}; byId("difficulty").value = "easy"; byId("count").value = "1";
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
fetch("/api/config").then(response => { if (!response.ok) throw new Error("Setup unavailable"); return response.json(); }).then(data => {
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
  prepareBrief();
}).catch(() => { byId("setup").textContent = "Could not load the supported families. Restart the generator and reload this page."; });
