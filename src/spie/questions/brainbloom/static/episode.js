/* A transcript player: the engine, never the browser, decides state and actions. */
(function (root) {
  "use strict";
  function el(tag, text, className) {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    if (className) node.className = className;
    return node;
  }
  function button(text, action, className = "secondary") {
    const node = el("button", text, className); node.type = "button";
    node.addEventListener("click", action); return node;
  }
  function mount(host, {bundle, index, saved, onProgress, isCurrent}) {
    const scenario = bundle.proofs[index].episode;
    let actions = saved?.actions?.slice() || [], hintLevel = saved?.hint_level || 0;
    let started = saved?.started === true, revision = 0, pending = false, view = null;
    const panel = el("section", undefined, "episode-player");
    panel.setAttribute("aria-label", "Playable planning scenario");
    panel.append(el("p", scenario.introduction), el("p", scenario.objective, "episode-objective"));
    panel.append(el("blockquote", `${scenario.dialogue.speaker}: “${scenario.dialogue.opening}”`, "episode-dialogue"));
    const map = el("details", undefined, "episode-map");
    map.append(el("summary", "Full map & rules · plan ahead"));
    const routes = el("table", undefined, "episode-routes"), header = el("tr");
    ["One-way route", "Energy", "Gate needed"].forEach(text => header.append(el("th", text)));
    const thead = el("thead"); thead.append(header); routes.append(thead);
    const tbody = el("tbody");
    scenario.source_facts.filter(fact => fact.id.startsWith("route.")).forEach(fact => {
      const row = el("tr"), value = fact.value;
      [scenario.rooms[value.origin].name + " → " + scenario.rooms[value.destination].name,
        String(value.energy), value.gate === -1 ? "None" : "AB"[value.gate]].forEach(text => row.append(el("td", text)));
      tbody.append(row);
    });
    routes.append(tbody); map.append(routes);
    scenario.source_facts.filter(fact => !fact.id.startsWith("room.") && !fact.id.startsWith("route.")).forEach(fact => map.append(el("p", fact.text)));
    panel.append(map);
    const live = el("div", undefined, "episode-live"), message = el("p", "", "episode-message");
    message.setAttribute("role", "status"); message.setAttribute("aria-live", "polite");
    const toolbar = el("div", undefined, "episode-toolbar");
    const start = button(started ? "Resume scenario" : "Start scenario", () => request(actions, hintLevel));
    const undo = button("Undo last action", () => request(actions.slice(0, -1), 0));
    const restart = button("Restart scenario", () => request([], 0));
    undo.disabled = true; restart.hidden = !started;
    toolbar.append(start, undo, restart); panel.append(toolbar, message, live); host.append(panel);

    function snapshot() { return {started, actions:actions.slice(), hint_level:hintLevel}; }
    function active() { return panel.isConnected && isCurrent(); }
    function draw() {
      live.replaceChildren();
      const state = view.state;
      live.append(el("h4", `${state.location_name} · action ${state.steps}`, "episode-location"));
      const stateLine = el("p", `Energy ${state.energy}/${state.capacity} · Gate A ${state.gates[0] ? "open" : "closed"} · Gate B ${state.gates[1] ? "open" : "closed"} · Recharge ${state.recharged ? "used" : "unused"}`, "episode-state");
      live.append(stateLine);
      if (view.status === "dead_end") {
        const destination = scenario.resolution.destination || "hall";
        live.append(el("p", `This route cannot reach the ${destination} from here. Undo an action to rethink the plan.`, "episode-dead-end"));
      }
      if (!view.can_append && !view.goal_reached) live.append(el("p", "This play history has reached its 128-action limit. Undo or restart to continue exploring."));
      const last = view.history.at(-1);
      if (last && !view.resolution) {
        live.append(el("p", last.text, "episode-consequence"));
        live.append(el("blockquote", `${last.dialogue.speaker}: “${last.dialogue.text}”`, "episode-dialogue"));
      }
      if (view.resolution) {
        const ending = el("div", undefined, "episode-resolution");
        ending.append(el("h4", scenario.resolution.heading || "Farewell delivered"), el("p", view.resolution.text),
          el("blockquote", `${view.resolution.dialogue.speaker}: “${view.resolution.dialogue.text}”`), el("p", view.resolution.replay_summary));
        live.append(ending);
      } else {
        const choices = el("div", undefined, "episode-actions");
        view.local_actions.forEach(action => {
          const row = el("div", undefined, "episode-action");
          const choose = button(action.label, () => request([...actions, action.id], 0), "secondary episode-move");
          choose.dataset.action = action.id; choose.disabled = !action.legal || !view.can_append || pending;
          row.append(choose, el("p", action.legal ? action.consequence : action.reasons.join(" "), "hint"));
          choices.append(row);
        });
        live.append(choices);
        const help = button(hintLevel === 0 ? "Hint: an observation" : hintLevel === 1 ? "Hint: connect the facts" : "Show a suggested next action",
          () => request(actions, Math.min(3, hintLevel + 1)), "secondary episode-hint");
        help.disabled = hintLevel >= 3 || pending; live.append(help);
        if (view.hint) {
          live.append(el("p", view.hint.text, "episode-hint-text"));
          const evidence = el("details"); evidence.append(el("summary", "Facts behind this hint"));
          const facts = new Map(view.facts.map(fact => [fact.id, fact]));
          view.hint.fact_ids.forEach(id => { if (facts.has(id)) evidence.append(el("p", facts.get(id).text)); });
          live.append(evidence);
        }
      }
      if (view.history.length) {
        const history = el("details", undefined, "episode-history"), list = el("ol");
        history.append(el("summary", `Your action history (${view.history.length})`));
        view.history.forEach(event => list.append(el("li", `${event.label}. ${event.text}`)));
        history.append(list); live.append(history);
      }
    }
    async function request(nextActions, nextHint) {
      const token = ++revision;
      pending = true; start.disabled = true; undo.disabled = true;
      live.querySelectorAll("button").forEach(node => { node.disabled = true; });
      message.textContent = "Replaying your actions…";
      try {
        const response = await fetch("/api/play-episode", {method:"POST", headers:{"Content-Type":"application/json"},
          body:JSON.stringify({bundle, index, actions:nextActions, hint_level:nextHint})});
        const data = await response.json();
        if (token !== revision || !active()) return;
        if (!response.ok) throw new Error(data.error || "Could not replay this scenario.");
        view = data; actions = data.actions.slice(); hintLevel = nextHint; started = true; pending = false;
        start.hidden = true; restart.hidden = false;
        message.textContent = data.goal_reached ? "Scenario complete." : "Your position is ready.";
        draw(); onProgress(snapshot());
      } catch (error) {
        if (token !== revision || !active()) return;
        pending = false; message.textContent = error instanceof TypeError ? "Cannot reach the engine. Your last accepted position is preserved." : error.message;
        restart.hidden = false;
        if (view) draw();
      } finally {
        if (token === revision && active()) {
          pending = false; start.disabled = false; undo.disabled = !view || actions.length === 0;
        }
      }
    }
    return {snapshot};
  }
  root.BrainBloomEpisode = {mount};
})(window);
