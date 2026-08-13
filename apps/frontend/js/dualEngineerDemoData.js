/* MIT License · Copyright (c) 2026 F1 Dual Engineer contributors */
(function () {
  "use strict";

  const drivers = [
    ["JOV", "Apex GP"], ["JAX", "Apex GP"], ["LEC", "Ferrari"], ["NOR", "McLaren"],
    ["VER", "Red Bull Racing"], ["RUS", "Mercedes"], ["PIA", "McLaren"], ["HAM", "Ferrari"],
    ["ANT", "Mercedes"], ["ALO", "Aston Martin"], ["GAS", "Alpine"], ["TSU", "Red Bull Racing"],
    ["HUL", "Sauber"], ["OCO", "Haas"], ["STR", "Aston Martin"], ["ALB", "Williams"],
    ["BEA", "Haas"], ["SAI", "Williams"], ["LAW", "Racing Bulls"], ["BOR", "Sauber"]
  ];
  const compounds = ["Medium", "Medium", "Soft", "Medium", "Hard", "Medium", "Soft", "Hard"];

  function lap(ms) {
    if (!Number.isFinite(ms)) return null;
    const minutes = Math.floor(ms / 60000);
    return `${minutes}:${((ms % 60000) / 1000).toFixed(3).padStart(6, "0")}`;
  }

  function makeTrace(index, tick) {
    const points = [];
    const offset = index === 0 ? 0 : 110;
    for (let distance = 0; distance <= 4381; distance += 45) {
      const phase = distance / 4381 * Math.PI * 12;
      const braking = Math.max(0, Math.sin(phase + .72) - .48) * 1.9;
      const speed = 294 - braking * 122 + Math.sin(phase * .47) * 18 + (index === 0 ? -2 : 4);
      const timeMs = distance * (19600 + offset) / 1000 + Math.sin(phase) * 120 + offset;
      points.push({
        distance,
        time_ms: timeMs,
        speed: Math.max(72, speed),
        brake: Math.min(1, braking),
        throttle: Math.max(0, Math.min(1, 1 - braking * .96 + Math.sin(phase - .5) * .08)),
        steering: Math.sin(phase * .95) * Math.max(.12, braking * .65),
        gear: Math.max(2, Math.min(8, Math.round(speed / 42))),
        rpm: 7200 + (speed % 65) * 65,
        g_lat: Math.sin(phase * .95) * 3.4,
        g_long: braking ? -4.2 * braking : 1.2,
        x: Math.cos(distance / 4381 * Math.PI * 2) * (140 + 35 * Math.sin(phase / 3)),
        z: Math.sin(distance / 4381 * Math.PI * 2) * (92 + 22 * Math.cos(phase / 2))
      });
    }
    const progress = Math.floor((tick * 2.1 + index * 510) % points.length);
    return points.slice(0, Math.max(8, progress));
  }

  function entry(index, tick) {
    const [name, team] = drivers[index];
    const lapBase = 83120 + index * 245 + (index % 3) * 118;
    const distanceProgress = ((tick * 38 + 3900 - index * 173) % 4381 + 4381) % 4381;
    const angle = distanceProgress / 4381 * Math.PI * 2;
    const tyre = compounds[index % compounds.length];
    const telemetryAvailable = index !== 13;
    const speed = Math.round(198 + 102 * Math.max(0, Math.cos(angle * 5)));
    const brake = Math.max(0, Math.sin(angle * 7 + .8) - .62) * 2.4;
    const throttle = Math.max(0, Math.min(1, 1 - brake + Math.sin(angle * 4) * .08));
    const motionX = Math.cos(angle) * (145 + 35 * Math.sin(angle * 3));
    const motionZ = Math.sin(angle) * (94 + 20 * Math.cos(angle * 2));
    const gap = index === 0 ? 0 : 1740 + index * 1620;
    const interval = index === 0 ? 0 : 690 + (index % 4) * 410;
    const sectorBase = Math.round(lapBase / 3);
    const available = value => telemetryAvailable ? value : null;
    return {
      "driver-info": {
        position: index + 1, "grid-position": ((index + 3) % 20) + 1, name, team,
        "is-fastest": index === 2, "is-player": index === 0, "is-secondary-player": index === 1,
        "dnf-status": index === 19 ? "DNF" : "", index, "telemetry-setting": telemetryAvailable ? "Public" : "Restricted",
        "is-pitting": index === 9, drs: index % 5 === 0, "drs-activated": index % 5 === 0,
        "drs-allowed": index % 3 === 0, "drs-distance": 0
      },
      "delta-info": {
        delta: index === 0 ? "---" : `+${(interval / 1000).toFixed(3)}`,
        "delta-to-car-in-front": index === 0 ? "---" : `+${(interval / 1000).toFixed(3)}`,
        "delta-to-leader": index === 0 ? "---" : `+${(gap / 1000).toFixed(3)}`
      },
      "ers-info": { "ers-percent-float": available(68 - index * 1.8), "ers-mode": available(index % 4 === 0 ? "Overtake" : "Medium") },
      "lap-info": {
        "current-lap": 18, "lap-distance": distanceProgress,
        "last-lap": { "lap-time-ms": lapBase + (index % 2 ? 238 : 0), "s1-time-ms": sectorBase - 250, "s2-time-ms": sectorBase + 620, "s3-time-ms": sectorBase - 370, "is-valid": true },
        "best-lap": { "lap-time-ms": lapBase - 480, "s1-time-ms": sectorBase - 390, "s2-time-ms": sectorBase + 480, "s3-time-ms": sectorBase - 570, "is-valid": true },
        "curr-lap": { "lap-time-ms": Math.round(distanceProgress / 4381 * lapBase), "s1-time-ms": sectorBase - 320, "s2-time-ms": sectorBase + 510, "s3-time-ms": null, "delta-ms": index === 0 ? -142 : 86, "is-valid": true },
        "top-speed-kmph": 321 - index % 5
      },
      "warns-pens-info": { "corner-cutting-warnings": index % 7 === 0 ? 1 : 0, "time-penalties": index === 7 ? 5 : 0, "num-dt": 0, "num-sg": 0 },
      "tyre-info": { "visual-tyre-compound": tyre, "tyre-age": 4 + index % 9, "current-wear": telemetryAvailable ? { "front-left-wear": 23 + index, "front-right-wear": 24 + index, "rear-left-wear": 21 + index, "rear-right-wear": 22 + index } : null },
      "damage-info": {},
      "fuel-info": { "fuel-in-tank": available(34.8 - index * .1), "fuel-remaining-laps": available(index === 0 ? .72 : .48) },
      "pit-info": {},
      "2026-regs-info": {},
      "live-telemetry": {
        available: telemetryAvailable, status: telemetryAvailable ? "Available" : "Unavailable",
        "speed-kph": available(speed), throttle: available(throttle), brake: available(brake), steering: available(Math.sin(angle * 7) * .34),
        gear: available(Math.max(2, Math.min(8, Math.round(speed / 42)))), rpm: available(7200 + speed * 17),
        "g-lateral": available(Math.sin(angle * 7) * 3.2), "g-longitudinal": available(brake ? -3.8 : 1.1),
        "tyre-surface-temps": available([91 + index % 5, 92, 88, 89]), "tyre-inner-temps": available([99, 100, 96, 97]),
        "tyre-wear": available([23 + index, 24 + index, 21 + index, 22 + index]),
        "fuel-kg": available(34.8 - index * .1), "fuel-delta-laps": available(index === 0 ? .72 : .48),
        "ers-store-percent": available(68 - index * 1.8), "ers-deployed-percent": available(31 + index % 8), "ers-harvested-percent": available(21 + index % 6),
        "ers-mode": available(index % 4 === 0 ? "Overtake" : "Medium"), drs: available(index % 5 === 0),
        "damage-percent": available(index === 5 ? 8 : 0), pit: index === 9, "world-x": motionX, "world-z": motionZ,
        "wheel-speeds": null, "wheel-slip-ratios": null, "wheel-slip-angles": null
      },
      "world-pos": [motionX, motionZ],
      _demo: { lap: lap(lapBase) }
    };
  }

  window.DualEngineerDemo = {
    makeState(tick) {
      const entries = drivers.map((_, index) => entry(index, tick));
      const traceA = makeTrace(0, tick);
      const traceB = makeTrace(1, tick);
      return {
        enabled: true,
        driver_a_index: 0,
        driver_b_index: 1,
        participants: entries.map(item => ({
          index: item["driver-info"].index,
          name: item["driver-info"].name,
          team: item["driver-info"].team,
          position: item["driver-info"].position,
          telemetry_available: item["live-telemetry"].available,
          is_player: item["driver-info"]["is-player"],
          is_secondary_player: item["driver-info"]["is-secondary-player"]
        })),
        recording: { active: true, session_uid: 14269012, raw_queue_depth: 12, dropped_raw_packets: 0, dropped_structured_samples: 0, latest_export: null },
        comparison: {
          driver_a: { index: 0, name: "JOV", points: traceA },
          driver_b: { index: 1, name: "JAX", points: traceB },
          live_delta_ms: traceA.length && traceB.length ? -126.4 : null,
          normalization: "lap-distance"
        },
        feed: [
          { time: "16:42:18", level: "pace", message: "JOV gaining 0.21s/lap on JAX over the last three clean laps" },
          { time: "16:41:52", level: "warning", message: "JAX rear degradation trend is 1.8% higher this stint · medium confidence" },
          { time: "16:41:21", level: "pace", message: "JOV T5 remains largest loss · minimum speed −9 km/h" },
          { time: "16:40:46", level: "info", message: "JAX entered DRS range of JOV" },
          { time: "16:39:09", level: "warning", message: "Pit window opens in 3 laps · traffic risk moderate" }
        ],
        telemetry: {
          "live-data": true, "f1-game-year": 25, "packet-format": 2025, circuit: "Hungaroring", "circuit-len": 4381,
          "event-type": "Race", "session-uid": 14269012, "session-time-left": 2174, "total-laps": 35, "current-lap": 18,
          "track-temperature": 39, "air-temperature": 27, "safety-car-status": "No Safety Car", "race-ended": false,
          "wdt-status": true, "in-menu": false, "table-entries": entries
        }
      };
    }
  };
}());
