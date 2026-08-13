/* MIT License · Copyright (c) 2026 F1 Dual Engineer contributors */
(function () {
  "use strict";

  const $ = id => document.getElementById(id);
  const state = {
    data: null,
    demo: new URLSearchParams(location.search).get("demo") === "1",
    demoTick: 0,
    trace: "speed",
    lastParticipantsKey: "",
    selectedA: null,
    selectedB: null,
    analysisReport: null,
    mapDots: new Map(),
    toastTimer: null
  };

  function text(id, value, fallback = "—") {
    const node = $(id);
    if (node) node.textContent = value === null || value === undefined || value === "" ? fallback : String(value);
  }

  function number(value, digits = 0, suffix = "") {
    return Number.isFinite(Number(value)) ? `${Number(value).toFixed(digits)}${suffix}` : "Unavailable";
  }

  function lapTime(ms) {
    if (!Number.isFinite(Number(ms)) || Number(ms) <= 0) return "—";
    const minutes = Math.floor(ms / 60000);
    return `${minutes}:${((ms % 60000) / 1000).toFixed(3).padStart(6, "0")}`;
  }

  function gap(value) {
    if (value === null || value === undefined || value === "" || value === "---") return "LEADER";
    const normalized = String(value);
    return normalized.startsWith("+") ? `${normalized}s` : normalized;
  }

  function secondsClock(raw) {
    const seconds = Math.max(0, Number(raw) || 0);
    return `${Math.floor(seconds / 60)}:${String(Math.floor(seconds % 60)).padStart(2, "0")}`;
  }

  function average(values) {
    const valid = (values || []).map(Number).filter(Number.isFinite);
    return valid.length ? valid.reduce((sum, value) => sum + value, 0) / valid.length : null;
  }

  function getEntry(index) {
    const entries = state.data?.telemetry?.["table-entries"] || [];
    return entries.find(entry => entry?.["driver-info"]?.index === index) || null;
  }

  function showToast(message) {
    const toast = $("toast");
    toast.textContent = message;
    toast.classList.add("show");
    clearTimeout(state.toastTimer);
    state.toastTimer = setTimeout(() => toast.classList.remove("show"), 2600);
  }

  function setDemo(enabled) {
    state.demo = enabled;
    $("demoBadge").hidden = !enabled;
    const url = new URL(location.href);
    if (enabled) url.searchParams.set("demo", "1"); else url.searchParams.delete("demo");
    history.replaceState({}, "", url);
    if (enabled) showToast("Representative demo telemetry enabled");
    poll();
  }

  async function poll() {
    if (state.demo) {
      state.demoTick += 1;
      state.data = window.DualEngineerDemo.makeState(state.demoTick);
      render();
      return;
    }
    try {
      const response = await fetch("/api/dual-engineer/state", { cache: "no-store" });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      state.data = await response.json();
      render();
    } catch (error) {
      renderDisconnected();
      console.debug("Dual Engineer state unavailable", error);
    }
  }

  function renderDisconnected() {
    $("connectionDot").classList.remove("live");
    text("connectionLabel", "WAITING FOR UDP");
    text("packetLabel", "Dashboard connected");
    text("recordingLabel", "ARMED");
    text("recordingDetail", "Automatic capture");
  }

  function render() {
    const data = state.data;
    const telemetry = data.telemetry || {};
    const live = Boolean(telemetry["wdt-status"] && !telemetry["in-menu"]);
    $("connectionDot").classList.toggle("live", live || state.demo);
    text("connectionLabel", state.demo ? "DEMO REPLAY" : live ? "TELEMETRY LIVE" : "WAITING FOR UDP");
    text("packetLabel", telemetry["packet-format"] ? `F1 ${telemetry["f1-game-year"] || 25} · UDP ${telemetry["packet-format"]}` : "Port 20777");
    $("demoBadge").hidden = !state.demo;
    text("sessionType", telemetry["event-type"] || telemetry["session-type"] || "NO SESSION");
    text("circuitName", telemetry.circuit && telemetry.circuit !== "---" ? telemetry.circuit : "Waiting for F1 telemetry");
    text("sessionClock", secondsClock(telemetry["session-time-left"]));
    text("sessionLap", `${telemetry["current-lap"] ?? "—"} / ${telemetry["total-laps"] ?? "—"}`);
    text("temperatures", `${telemetry["track-temperature"] ?? "—"}° / ${telemetry["air-temperature"] ?? "—"}°`);
    text("raceControl", normalizeRaceControl(telemetry["safety-car-status"]));
    text("recordingLabel", data.recording?.active ? "RECORDING" : "ARMED");
    text("recordingDetail", data.recording?.active ? `${data.recording.raw_queue_depth || 0} packets queued` : "Automatic capture");

    populateSelection();
    renderDriver("A", data.driver_a_index);
    renderDriver("B", data.driver_b_index);
    renderTiming();
    renderFeed();
    drawMap();
    drawTrace();
    renderAnalysis();
  }

  function normalizeRaceControl(value) {
    const label = String(value || "CLEAR").toUpperCase();
    if (label.includes("NO SAFETY")) return "CLEAR";
    if (label.includes("VIRTUAL")) return "VSC";
    if (label.includes("FORMATION")) return "FORMATION";
    if (label.includes("SAFETY")) return "SAFETY CAR";
    return label;
  }

  function populateSelection() {
    const participants = state.data.participants || [];
    const key = participants.map(item => `${item.index}:${item.name}`).join("|");
    if (key === state.lastParticipantsKey) return;
    state.lastParticipantsKey = key;
    for (const [select, selected] of [[$("driverASelect"), state.data.driver_a_index], [$("driverBSelect"), state.data.driver_b_index]]) {
      select.replaceChildren();
      if (!participants.length) {
        select.append(new Option("Waiting for participants", ""));
        select.disabled = true;
        continue;
      }
      select.disabled = false;
      for (const participant of participants) {
        const privacy = participant.telemetry_available ? "" : " · restricted";
        select.append(new Option(`P${participant.position || "—"}  ${participant.name}${privacy}`, String(participant.index)));
      }
      select.value = String(selected ?? "");
    }
    state.selectedA = state.data.driver_a_index;
    state.selectedB = state.data.driver_b_index;
  }

  function renderDriver(slot, index) {
    const prefix = `driver${slot}`;
    const entry = getEntry(index);
    const info = entry?.["driver-info"] || {};
    const delta = entry?.["delta-info"] || {};
    const lap = entry?.["lap-info"] || {};
    const current = lap["curr-lap"] || {};
    const last = lap["last-lap"] || {};
    const best = lap["best-lap"] || {};
    const tyre = entry?.["tyre-info"] || {};
    const live = entry?.["live-telemetry"] || { available: false };
    const warns = entry?.["warns-pens-info"] || {};
    const available = Boolean(live.available);

    text(`${prefix}Name`, info.name, `Driver ${slot}`);
    text(`${prefix}Team`, info.team, "Awaiting participant");
    text(`${prefix}Position`, info.position);
    text(`${prefix}Gap`, gap(delta["delta-to-leader"]));
    text(`${prefix}Interval`, `Ahead ${gap(delta["delta-to-car-in-front"])}`);
    text(`${prefix}Current`, lapTime(current["lap-time-ms"]));
    const deltaMs = current["delta-ms"];
    text(`${prefix}Delta`, Number.isFinite(deltaMs) ? `Delta ${deltaMs > 0 ? "+" : "−"}${Math.abs(deltaMs / 1000).toFixed(3)}` : "Delta —");
    text(`${prefix}Last`, lapTime(last["lap-time-ms"]));
    text(`${prefix}Best`, `Best ${lapTime(best["lap-time-ms"])}`);
    renderSectors(`${prefix}Sectors`, current);
    text(`${prefix}Speed`, available ? number(live["speed-kph"]) : "Unavailable");
    text(`${prefix}Gear`, available ? live.gear : "—");
    text(`${prefix}Throttle`, available ? number(live.throttle * 100, 0, "%") : "—");
    text(`${prefix}Brake`, available ? number(live.brake * 100, 0, "%") : "—");
    const card = $(`${prefix}Card`);
    const meters = card.querySelectorAll(".input-meter i span");
    meters[0].style.width = available ? `${Math.max(0, Math.min(100, live.throttle * 100))}%` : "0";
    meters[1].style.width = available ? `${Math.max(0, Math.min(100, live.brake * 100))}%` : "0";
    text(`${prefix}Tyre`, tyre["visual-tyre-compound"]);
    text(`${prefix}TyreAge`, `Age ${tyre["tyre-age"] ?? "—"} laps`);
    text(`${prefix}Wear`, available ? number(average(live["tyre-wear"]), 1, "%") : "Unavailable");
    text(`${prefix}Temps`, available ? `Surface ${number(average(live["tyre-surface-temps"]), 0, "°")}` : "Temps unavailable");
    text(`${prefix}Fuel`, available ? number(live["fuel-kg"], 1, " kg") : "Unavailable");
    text(`${prefix}FuelDelta`, available ? `Projected ${number(live["fuel-delta-laps"], 2, " laps")}` : "Delta unavailable");
    text(`${prefix}Ers`, available ? number(live["ers-store-percent"], 0, "%") : "Unavailable");
    text(`${prefix}ErsMode`, available ? `Mode ${live["ers-mode"] || "—"}` : "Mode unavailable");
    text(`${prefix}Status`, info["dnf-status"] || (live.pit ? "PIT LANE" : "RUNNING"));
    text(`${prefix}Drs`, available ? `DRS ${live.drs ? "OPEN" : info["drs-allowed"] ? "READY" : "OFF"}` : "DRS unavailable");
    text(`${prefix}Damage`, available ? number(live["damage-percent"], 0, "%") : "Unavailable");
    const penaltySeconds = warns["time-penalties"];
    const warnings = warns["corner-cutting-warnings"];
    text(`${prefix}Penalties`, penaltySeconds ? `${penaltySeconds}s penalty` : warnings ? `${warnings} warning${warnings === 1 ? "" : "s"}` : "No penalties");
    $(`${prefix}Unavailable`).hidden = available || !entry;
  }

  function renderSectors(id, current) {
    const values = [current["s1-time-ms"], current["s2-time-ms"], current["s3-time-ms"]];
    const spans = $(id).querySelectorAll("span b");
    values.forEach((value, index) => spans[index].textContent = lapTime(value).replace(/^0:/, ""));
  }

  function renderTiming() {
    const body = $("timingBody");
    const fragment = document.createDocumentFragment();
    const entries = [...(state.data.telemetry?.["table-entries"] || [])]
      .sort((left, right) => (left["driver-info"].position || 99) - (right["driver-info"].position || 99));
    for (const entry of entries) {
      const info = entry["driver-info"] || {};
      const lap = entry["lap-info"] || {};
      const delta = entry["delta-info"] || {};
      const tyre = entry["tyre-info"] || {};
      const ers = entry["ers-info"] || {};
      const row = document.createElement("tr");
      if (info.index === state.data.driver_a_index) row.className = "selected-a";
      if (info.index === state.data.driver_b_index) row.className = "selected-b";
      const current = lap["curr-lap"] || {};
      const cells = [
        [info.position], [info.name, "driver-name"], [gap(delta["delta-to-car-in-front"]), "muted"],
        [gap(delta["delta-to-leader"]), "muted"], [lapTime(lap["last-lap"]?.["lap-time-ms"])],
        [lapTime(lap["best-lap"]?.["lap-time-ms"]), info["is-fastest"] ? "purple" : ""],
        [sector(current["s1-time-ms"])], [sector(current["s2-time-ms"])], [sector(current["s3-time-ms"])],
      ];
      for (const [value, className] of cells) {
        const cell = document.createElement("td"); cell.textContent = value ?? "—"; if (className) cell.className = className; row.append(cell);
      }
      const tyreCell = document.createElement("td");
      const compound = String(tyre["visual-tyre-compound"] || "—");
      const badge = document.createElement("span"); badge.className = `compound ${compound.toLowerCase()}`; badge.textContent = compound[0]; badge.title = compound; tyreCell.append(badge); row.append(tyreCell);
      appendCell(row, tyre["tyre-age"] ?? "—");
      appendCell(row, Number.isFinite(ers["ers-percent-float"]) ? `${Math.round(ers["ers-percent-float"])}%` : "—", Number(ers["ers-percent-float"]) < 15 ? "loss" : "");
      const statusCell = document.createElement("td"); const status = document.createElement("span");
      const statusText = info["dnf-status"] || (info["is-pitting"] ? "PIT" : "RUN");
      status.className = `state-tag ${statusText === "PIT" ? "pit" : statusText ? "dnf" : ""}`.trim(); status.textContent = statusText || "RUN"; statusCell.append(status); row.append(statusCell);
      fragment.append(row);
    }
    body.replaceChildren(fragment);
  }

  function appendCell(row, value, className = "") { const cell = document.createElement("td"); cell.textContent = value; cell.className = className; row.append(cell); }
  function sector(value) { return Number.isFinite(Number(value)) && Number(value) > 0 ? (Number(value) / 1000).toFixed(3) : "—"; }

  function renderFeed() {
    const feed = state.data.feed || [];
    text("feedCount", feed.length);
    const list = $("engineerFeed");
    if (!feed.length) {
      const empty = document.createElement("li"); empty.className = "feed-empty"; empty.textContent = "Actionable messages appear as telemetry arrives."; list.replaceChildren(empty); return;
    }
    const fragment = document.createDocumentFragment();
    for (const item of feed) {
      const li = document.createElement("li"); li.className = item.level || "info";
      const timeNode = document.createElement("time"); timeNode.textContent = item.time || "NOW";
      const message = document.createElement("p"); message.textContent = item.message;
      li.append(timeNode, message); fragment.append(li);
    }
    list.replaceChildren(fragment);
  }

  function canvasSize(canvas) {
    const ratio = window.devicePixelRatio || 1;
    const rect = canvas.getBoundingClientRect();
    const width = Math.max(1, Math.floor(rect.width * ratio));
    const height = Math.max(1, Math.floor(rect.height * ratio));
    if (canvas.width !== width || canvas.height !== height) { canvas.width = width; canvas.height = height; }
    return { ctx: canvas.getContext("2d"), width, height, ratio };
  }

  function drawMap() {
    const canvas = $("trackMap");
    const { ctx, width, height, ratio } = canvasSize(canvas);
    ctx.clearRect(0, 0, width, height);
    const entries = state.data.telemetry?.["table-entries"] || [];
    const positions = entries.map(entry => {
      const point = entry["world-pos"] || [entry["live-telemetry"]?.["world-x"], entry["live-telemetry"]?.["world-z"]];
      return Number.isFinite(point?.[0]) && Number.isFinite(point?.[1]) ? { entry, x: point[0], y: point[1] } : null;
    }).filter(Boolean);
    if (!positions.length) { drawCanvasEmpty(ctx, width, height, "TRACK POSITION AWAITS MOTION DATA"); return; }
    const xs = positions.map(point => point.x), ys = positions.map(point => point.y);
    const bounds = { minX: Math.min(...xs), maxX: Math.max(...xs), minY: Math.min(...ys), maxY: Math.max(...ys) };
    const pad = 48 * ratio;
    const scale = Math.min((width - pad * 2) / Math.max(1, bounds.maxX - bounds.minX), (height - pad * 2) / Math.max(1, bounds.maxY - bounds.minY));
    const project = point => ({ x: (point.x - (bounds.minX + bounds.maxX) / 2) * scale + width / 2, y: (point.y - (bounds.minY + bounds.maxY) / 2) * scale + height / 2 });
    const center = { x: positions.reduce((sum,p)=>sum+p.x,0)/positions.length, y: positions.reduce((sum,p)=>sum+p.y,0)/positions.length };
    const outline = [...positions].sort((a,b)=>Math.atan2(a.y-center.y,a.x-center.x)-Math.atan2(b.y-center.y,b.x-center.x));
    ctx.lineJoin = "round"; ctx.lineCap = "round";
    for (const [lineWidth, color] of [[14,"#252c33"],[4,"#626d76"]]) {
      ctx.beginPath(); outline.forEach((point,index)=>{ const p=project(point); index?ctx.lineTo(p.x,p.y):ctx.moveTo(p.x,p.y); }); ctx.closePath(); ctx.lineWidth=lineWidth*ratio; ctx.strokeStyle=color; ctx.stroke();
    }
    for (const point of positions) {
      const p = project(point), info = point.entry["driver-info"] || {};
      const isA = info.index === state.data.driver_a_index, isB = info.index === state.data.driver_b_index;
      const target = state.mapDots.get(info.index) || p;
      target.x += (p.x - target.x) * .38; target.y += (p.y - target.y) * .38; state.mapDots.set(info.index, target);
      const color = isA ? css("--a") : isB ? css("--b") : info["is-pitting"] ? css("--warn") : "#c4ccd2";
      ctx.beginPath(); ctx.arc(target.x, target.y, (isA || isB ? 7 : 4) * ratio, 0, Math.PI*2); ctx.fillStyle=color; ctx.fill();
      if (isA || isB) { ctx.lineWidth=3*ratio; ctx.strokeStyle="rgba(255,255,255,.8)"; ctx.stroke(); ctx.font=`700 ${9*ratio}px ${css("--mono")}`; ctx.fillStyle=color; ctx.fillText(isA?"A":"B",target.x+10*ratio,target.y-8*ratio); }
    }
    text("mapTitle", `${state.data.telemetry?.circuit || "TRACK"} · ${positions.length} CARS`);
  }

  function drawCanvasEmpty(ctx, width, height, label) { ctx.fillStyle="#59636d"; ctx.font=`700 ${10*(window.devicePixelRatio||1)}px ${css("--mono")}`; ctx.textAlign="center"; ctx.fillText(label,width/2,height/2); ctx.textAlign="left"; }
  function css(name) { return getComputedStyle(document.documentElement).getPropertyValue(name).trim(); }

  function drawTrace() {
    const canvas = $("traceChart");
    const { ctx, width, height, ratio } = canvasSize(canvas);
    ctx.clearRect(0,0,width,height);
    const comparison = state.data.comparison || {};
    const a = comparison.driver_a?.points || [], b = comparison.driver_b?.points || [];
    text("traceAName", comparison.driver_a?.name || "Driver A"); text("traceBName", comparison.driver_b?.name || "Driver B");
    const delta = comparison.live_delta_ms;
    text("liveDelta", Number.isFinite(delta) ? `${delta > 0 ? "+" : "−"}${Math.abs(delta/1000).toFixed(3)}s` : "—");
    $("liveDelta").className = `delta-callout ${Number(delta)>0?"loss":Number(delta)<0?"gain":""}`;
    if (a.length < 2 || b.length < 2) { drawCanvasEmpty(ctx,width,height,"TRACE BUILDS THROUGH THE CURRENT LAP"); return; }
    const pad = { left:48*ratio,right:16*ratio,top:16*ratio,bottom:27*ratio };
    const fields = state.trace === "inputs" ? ["throttle","brake"] : state.trace === "gforce" ? ["g_lat","g_long"] : state.trace === "path" ? ["z"] : ["speed"];
    const all = [...a,...b].flatMap(point=>fields.map(field=>Number(point[field]))).filter(Number.isFinite);
    let min = Math.min(...all), max = Math.max(...all); if (max === min) max += 1; const distMax = Math.max(...a.map(p=>p.distance),...b.map(p=>p.distance),1);
    const x = value => pad.left + value / distMax * (width-pad.left-pad.right);
    const y = value => height-pad.bottom-(value-min)/(max-min)*(height-pad.top-pad.bottom);
    ctx.strokeStyle="#222931"; ctx.lineWidth=1;
    ctx.fillStyle="#65707a"; ctx.font=`${8*ratio}px ${css("--mono")}`;
    for(let i=0;i<=4;i++){const gy=pad.top+i*(height-pad.top-pad.bottom)/4;ctx.beginPath();ctx.moveTo(pad.left,gy);ctx.lineTo(width-pad.right,gy);ctx.stroke();const value=max-i*(max-min)/4;ctx.fillText(value.toFixed(state.trace==="speed"?0:1),4*ratio,gy+3*ratio);}
    for(let i=0;i<=4;i++){const gx=pad.left+i*(width-pad.left-pad.right)/4;ctx.beginPath();ctx.moveTo(gx,pad.top);ctx.lineTo(gx,height-pad.bottom);ctx.stroke();ctx.fillText(`${Math.round(distMax*i/400)/10}k`,gx-9*ratio,height-8*ratio);}
    const colors = [[css("--a"),css("--b")],["#47d683","#ff5b61"]];
    fields.forEach((field,fieldIndex)=>{drawLine(ctx,a,field,x,y,colors[fieldIndex]?.[0]||css("--a"),ratio,fieldIndex?1.3:2);drawLine(ctx,b,field,x,y,colors[fieldIndex]?.[1]||css("--b"),ratio,fieldIndex?1.3:2);});
  }

  function drawLine(ctx, points, field, x, y, color, ratio, lineWidth) {
    ctx.beginPath(); let started=false; for(const point of points){const value=Number(point[field]);if(!Number.isFinite(value))continue;const px=x(point.distance),py=y(value);started?ctx.lineTo(px,py):ctx.moveTo(px,py);started=true;}ctx.strokeStyle=color;ctx.lineWidth=lineWidth*ratio;ctx.globalAlpha=(field==="brake"||field==="g_long") ? 0.78 : 1;ctx.stroke();ctx.globalAlpha=1;
  }

  function signedSeconds(milliseconds) {
    return Number.isFinite(Number(milliseconds)) ? `${Number(milliseconds) >= 0 ? "+" : "−"}${Math.abs(Number(milliseconds) / 1000).toFixed(3)}` : "—";
  }

  function renderAnalysis() {
    if (state.demo) {
      text("analysisState", "DEMO DATA · Clean representative laps only. Every diagnosis includes evidence and confidence.");
      text("referenceQuality", "HIGH"); text("referenceDetails", "Same compound · clean air · tyre age +1");
      text("analysisGap", "+0.842s"); text("analysisGapLabel", "Driver A to Driver B");
      text("analysisPb", "1:22.911"); text("analysisPbLabel", "Clean lap 12");
      text("analysisTheoretical", "1:21.804"); text("analysisTheoreticalLabel", "Demo theoretical · untapped 1.107s");
      text("analysisConsistency", "±0.184s"); text("analysisConsistencyLabel", "Demo best 3 clean laps");
      renderPhases(493, 224, 125);
      renderOpportunities([
        {label:"T6–7",diagnosis:"Over-slowing",time_loss_ms:218},
        {label:"T12",diagnosis:"Traction / exit",time_loss_ms:173},
        {label:"T5",diagnosis:"Early braking",time_loss_ms:142},
        {label:"T14",diagnosis:"Line difference",time_loss_ms:94}
      ]);
      renderDiagnosis({label:"T5",time_loss_ms:142,entry_loss_ms:94,mid_loss_ms:28,exit_loss_ms:20,brake_point_difference_m:-4,brake_duration_difference_m:21,minimum_speed_difference_kph:-11,full_throttle_difference_m:0,diagnosis:"Over-slowing",confidence:"High",evidence:["Earlier brake onset","Longer brake application","Lower minimum speed"]});
      return;
    }
    const report = state.analysisReport;
    const comparison = report?.analysis?.comparison;
    if (!comparison) {
      text("analysisState", "Open a finalized recorded session to view measured clean-lap analysis.");
      text("referenceQuality", "UNAVAILABLE"); text("referenceDetails", "No comparable selected-driver laps loaded");
      for (const id of ["analysisGap", "analysisPb", "analysisTheoretical", "analysisConsistency"]) text(id, "—");
      text("analysisGapLabel", "No recorded comparison"); text("analysisPbLabel", "No session selected");
      text("analysisTheoreticalLabel", "Requires clean lap history"); text("analysisConsistencyLabel", "Requires three clean laps");
      renderPhases(null, null, null); renderOpportunities([]); renderDiagnosis(null); return;
    }
    const quality = comparison.reference_quality || {};
    text("analysisState", `${comparison.target_driver} vs ${comparison.reference_driver} · clean recorded laps ${comparison.target_lap} and ${comparison.reference_lap}`);
    text("referenceQuality", quality.label); text("referenceDetails", (quality.reasons || []).join(" · ") || "Limited context data");
    text("analysisGap", `${signedSeconds(comparison.representative_gap_ms)}s`); text("analysisGapLabel", `${comparison.target_driver} to ${comparison.reference_driver}`);
    const selectedIndex = report.recording?.driver_a_index;
    const classification = report.session?.["classification-data"] || [];
    const selected = classification.find(item => item.index === selectedIndex) || classification.find(item => item["driver-name"] === comparison.target_driver);
    const pb = selected?.["final-classification"]?.["best-lap-time-ms"];
    text("analysisPb", lapTime(pb)); text("analysisPbLabel", pb ? `${comparison.target_driver} classified best` : "Best lap unavailable");
    text("analysisTheoretical", "Unavailable"); text("analysisTheoreticalLabel", "Not derivable from this export");
    text("analysisConsistency", "Unavailable"); text("analysisConsistencyLabel", "Requires 3 complete clean laps");
    renderPhases(comparison.entry_loss_ms, comparison.mid_loss_ms, comparison.exit_loss_ms);
    const opportunities = [...(comparison.segments || [])].filter(item => item.time_loss_ms > 0).sort((a, b) => b.time_loss_ms - a.time_loss_ms).slice(0, 6);
    renderOpportunities(opportunities); renderDiagnosis(opportunities[0] || comparison.segments?.[0] || null);
  }

  function renderPhases(entry, mid, exit) {
    const values = [entry, mid, exit];
    const ids = [["entryBar", "entryLoss"], ["midBar", "midLoss"], ["exitBar", "exitLoss"]];
    const total = values.reduce((sum, value) => sum + Math.max(0, Number(value) || 0), 0);
    values.forEach((value, index) => {
      $(ids[index][0]).style.setProperty("--value", total ? `${Math.max(4, Math.max(0, Number(value) || 0) / total * 100)}%` : "0%");
      text(ids[index][1], Number.isFinite(Number(value)) ? signedSeconds(value) : "—");
    });
  }

  function renderOpportunities(segments) {
    const list = $("opportunityList"); const fragment = document.createDocumentFragment();
    const rows = segments.length ? segments : [{label:"—", diagnosis:"No measured segment analysis loaded", time_loss_ms:null}];
    for (const segment of rows) {
      const li = document.createElement("li"); const label = document.createElement("b"); const diagnosis = document.createElement("span"); const loss = document.createElement("em");
      label.textContent = segment.label; diagnosis.textContent = segment.diagnosis; loss.textContent = segment.time_loss_ms === null ? "—" : signedSeconds(segment.time_loss_ms);
      li.append(label, diagnosis, loss); fragment.append(li);
    }
    list.replaceChildren(fragment);
  }

  function difference(value, unit) {
    if (!Number.isFinite(Number(value))) return "Unavailable";
    if (Math.abs(Number(value)) < .5) return "Approximately equal";
    return `${Number(value) > 0 ? "+" : "−"}${Math.abs(Number(value)).toFixed(0)}${unit}`;
  }

  function renderDiagnosis(segment) {
    if (!segment) {
      text("diagnosisTitle", "NO SEGMENT SELECTED"); text("diagnosisConfidence", "UNAVAILABLE"); text("diagnosisPhase", "—");
      text("diagnosisBrakePoint", "Unavailable"); text("diagnosisBrakeDuration", "Unavailable"); text("diagnosisMinSpeed", "Unavailable");
      text("diagnosisThrottle", "Unavailable"); text("diagnosisName", "Insufficient data"); text("diagnosisEvidence", "Evidence appears after comparable clean laps are recorded."); return;
    }
    const phases = [["Entry", segment.entry_loss_ms], ["Mid-corner", segment.mid_loss_ms], ["Exit", segment.exit_loss_ms]].sort((a, b) => (Number(b[1]) || 0) - (Number(a[1]) || 0));
    text("diagnosisTitle", `${segment.label} · ${signedSeconds(segment.time_loss_ms)}s`); text("diagnosisConfidence", `${String(segment.confidence || "Low").toUpperCase()} CONFIDENCE`); text("diagnosisPhase", phases[0][0].toUpperCase());
    text("diagnosisBrakePoint", difference(segment.brake_point_difference_m, "m")); text("diagnosisBrakeDuration", difference(segment.brake_duration_difference_m, "m"));
    text("diagnosisMinSpeed", difference(segment.minimum_speed_difference_kph, " km/h")); text("diagnosisThrottle", difference(segment.full_throttle_difference_m, "m"));
    text("diagnosisName", segment.diagnosis); text("diagnosisEvidence", `Evidence: ${(segment.evidence || []).join(" · ") || "Limited measured channels"}. This is a correlation-based diagnosis, not causal certainty.`);
  }

  async function pinSelection() {
    const driverA = Number($("driverASelect").value), driverB = Number($("driverBSelect").value);
    if (driverA === driverB) { showToast("Driver A and Driver B must be different"); return; }
    if (state.demo) { state.data.driver_a_index=driverA; state.data.driver_b_index=driverB; state.lastParticipantsKey=""; render(); showToast("Demo driver selection pinned"); return; }
    try {
      const response = await fetch("/api/dual-engineer/selection", { method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({driver_a_index:driverA,driver_b_index:driverB}) });
      const payload = await response.json(); if(!response.ok) throw new Error(payload.error||`HTTP ${response.status}`); showToast("Driver selection pinned"); await poll();
    } catch(error) { showToast(`Could not pin drivers: ${error.message}`); }
  }

  async function loadSessions() {
    const list=$("sessionList");
    if(state.demo){renderSessions([{session_uid:"14269012",track:"Hungaroring",session_type:"Race",started_at:"2026-08-12T16:05:12Z",ended_at:"2026-08-12T16:48:31Z",finalized:true,metadata:{driver_a_name:"JOV",driver_b_name:"JAX"}}]);return;}
    try{const response=await fetch("/api/dual-engineer/sessions",{cache:"no-store"});const payload=await response.json();if(!response.ok)throw new Error(payload.error);renderSessions(payload.sessions||[]);}catch(error){list.textContent=`Unable to load sessions: ${error.message}`;}
  }

  function renderSessions(sessions){const list=$("sessionList");if(!sessions.length){const p=document.createElement("p");p.className="empty-state";p.textContent="No finalized sessions yet. Recording starts automatically when F1 telemetry arrives.";list.replaceChildren(p);return;}const fragment=document.createDocumentFragment();for(const session of sessions){const row=document.createElement("article");row.className="session-entry";const title=document.createElement("div");const strong=document.createElement("strong");strong.textContent=`${session.track||"Unknown track"} · ${session.session_type||"Session"}`;const subtitle=document.createElement("small");subtitle.textContent=`${session.metadata?.driver_a_name||"Driver A"} vs ${session.metadata?.driver_b_name||"Driver B"}`;title.append(strong,subtitle);row.append(title);const date=document.createElement("div");date.textContent=new Date(session.started_at).toLocaleDateString();row.append(date);const duration=document.createElement("div");duration.textContent=session.ended_at?`${Math.max(1,Math.round((new Date(session.ended_at)-new Date(session.started_at))/60000))} min`:"In progress";row.append(duration);const status=document.createElement("code");status.textContent=session.finalized?"FINALIZED":"RECORDING";row.append(status);const actions=document.createElement("div");actions.className="session-actions";for(const [label,action] of [["VIEW REPORT","view"],["OPEN FOLDER","open"],["EXPORT ZIP","export"]]){const button=document.createElement("button");button.className="button";button.textContent=label;button.addEventListener("click",()=>sessionAction(session.session_uid,action));actions.append(button);}row.append(actions);fragment.append(row);}list.replaceChildren(fragment);}

  async function sessionAction(uid,action){if(state.demo){if(action==="view"){document.querySelector('[data-view="analysis"]').click();showToast("Showing labeled demo analysis");}else showToast(action==="export"?"Demo mode does not create an export":"Demo mode has no local folder");return;}if(action==="export"){const form=document.createElement("form");form.method="POST";form.action=`/api/dual-engineer/sessions/${encodeURIComponent(uid)}/export`;form.hidden=true;document.body.append(form);form.submit();form.remove();return;}try{if(action==="view"){const response=await fetch(`/api/dual-engineer/sessions/${encodeURIComponent(uid)}`,{cache:"no-store"});const payload=await response.json();if(!response.ok)throw new Error(payload.error);state.analysisReport=payload;document.querySelector('[data-view="analysis"]').click();renderAnalysis();return;}const response=await fetch(`/api/dual-engineer/sessions/${encodeURIComponent(uid)}/open`,{method:"POST"});const payload=await response.json();if(!response.ok)throw new Error(payload.error);showToast("Session folder opened");}catch(error){showToast(error.message);}}

  async function loadCareer(){if(state.demo){$("careerGrid").hidden=false;$("careerEmpty").hidden=true;return;}try{const response=await fetch("/api/dual-engineer/careers",{cache:"no-store"});const payload=await response.json();if(!response.ok)throw new Error(payload.error);if(!(payload.careers||[]).length){$("careerGrid").hidden=true;$("careerEmpty").hidden=false;return;}const detailResponse=await fetch(`/api/dual-engineer/careers/${payload.careers[0].id}`,{cache:"no-store"});const detail=await detailResponse.json();if(!detailResponse.ok)throw new Error(detail.error);renderCareer(detail);}catch(error){$("careerGrid").hidden=true;$("careerEmpty").hidden=false;$("careerEmpty").textContent=`Career data unavailable: ${error.message}`;}}

  function renderCareer(detail){$("careerGrid").hidden=false;$("careerEmpty").hidden=true;const rows=detail.projection_active?detail.projected_driver_standings:detail.driver_standings;const list=$("driverStandings"),fragment=document.createDocumentFragment();for(const row of rows||[]){const li=document.createElement("li");if(row.driver_key===detail.career?.driver_b_key)li.className="driver-b-row";const rank=document.createElement("b");rank.textContent=row.rank;const name=document.createElement("strong");name.textContent=row.driver_name;const team=document.createElement("span");team.textContent=row.team||"No team";const points=document.createElement("em");points.textContent=row.points;if(row.projected_delta){const delta=document.createElement("small");delta.textContent=` +${row.projected_delta}`;points.append(delta);}li.append(rank,name,team,points);fragment.append(li);}list.replaceChildren(fragment);text("careerProjectionLabel",detail.projection_active?"IF RACE ENDS NOW":"CURRENT IMPORTED STANDINGS");text("careerRound",`ROUND ${detail.career?.current_round??0}`);const h2h=detail.head_to_head||{},a=h2h.driver_a||{},b=h2h.driver_b||{};text("warAName",a.driver_name||"Driver A");text("warBName",b.driver_name||"Driver B");text("warAScore",h2h.race_h2h?.[0]??0);text("warBScore",h2h.race_h2h?.[1]??0);text("warQualifying",`${h2h.qualifying_h2h?.[0]??0} — ${h2h.qualifying_h2h?.[1]??0}`);text("warWins",`${a.wins??0} — ${b.wins??0}`);text("warPodiums",`${a.podiums??0} — ${b.podiums??0}`);}

  async function createCareer(event){event.preventDefault();const form=$("careerForm"),data=Object.fromEntries(new FormData(form));try{if(state.demo){$("careerDialog").close();showToast("Demo career created locally for preview");return;}const response=await fetch("/api/dual-engineer/careers",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({season_name:data.season_name,game_version:"F1 25",driver_a_key:data.driver_a_key,driver_b_key:data.driver_b_key})});const payload=await response.json();if(!response.ok)throw new Error(payload.error);const constructors={};if(data.driver_a_team)constructors[data.driver_a_team]=Number(data.team_a_points)||0;if(data.driver_b_team)constructors[data.driver_b_team]=Math.max(constructors[data.driver_b_team]||0,Number(data.team_b_points)||0);const imported=await fetch(`/api/dual-engineer/careers/${payload.career.id}/import`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({current_round:Number(data.current_round)||0,drivers:[{driver_key:data.driver_a_key,driver_name:data.driver_a_name,team:data.driver_a_team||null,points:Number(data.driver_a_points)||0},{driver_key:data.driver_b_key,driver_name:data.driver_b_name,team:data.driver_b_team||null,points:Number(data.driver_b_points)||0}],constructors})});const importedPayload=await imported.json();if(!imported.ok)throw new Error(importedPayload.error);$("careerDialog").close();showToast("Career created, imported, and activated");renderCareer(importedPayload);}catch(error){showToast(error.message);}}

  function bind() {
    $("demoToggle").addEventListener("click",()=>setDemo(!state.demo));
    $("pinDrivers").addEventListener("click",pinSelection);
    $("driverASelect").addEventListener("change",event=>state.selectedA=Number(event.target.value));
    $("driverBSelect").addEventListener("change",event=>state.selectedB=Number(event.target.value));
    document.querySelectorAll(".nav-item[data-view]").forEach(button=>button.addEventListener("click",()=>{document.querySelectorAll(".nav-item[data-view]").forEach(item=>item.classList.toggle("is-active",item===button));document.querySelectorAll(".view").forEach(view=>view.classList.toggle("is-active",view.id===`view-${button.dataset.view}`));if(button.dataset.view==="sessions")loadSessions();if(button.dataset.view==="career")loadCareer();if(button.dataset.view==="analysis")renderAnalysis();setTimeout(()=>{drawMap();drawTrace();},0);}));
    document.querySelectorAll("[data-trace]").forEach(button=>button.addEventListener("click",()=>{state.trace=button.dataset.trace;document.querySelectorAll("[data-trace]").forEach(item=>item.classList.toggle("is-active",item===button));drawTrace();}));
    $("refreshSessions").addEventListener("click",loadSessions);
    $("newCareer").addEventListener("click",()=>$("careerDialog").showModal());
    $("createCareer").addEventListener("click",createCareer);
    window.addEventListener("resize",()=>{drawMap();drawTrace();},{passive:true});
  }

  bind();
  poll();
  setInterval(poll, 500);
}());
