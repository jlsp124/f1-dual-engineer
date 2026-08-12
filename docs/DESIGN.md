# Product design direction

## Visual thesis

A charcoal pit-wall timing sheet under low light: dense, flat and precise,
with cyan and magenta identifying the two selected drivers and semantic race
colours reserved for gains, personal bests, warnings and critical states.

## Content plan

1. Persistent session status and primary navigation.
2. Permanent Driver A and Driver B telemetry band.
3. Lap-distance-synchronised comparison and time-loss workspace.
4. Full timing tower and live track map.
5. Prioritised, confidence-aware engineer feed.
6. Dedicated sessions, career/head-to-head and setup views.

The working surface begins with operational information; it does not use a
marketing hero or a dashboard-card mosaic.

## Interaction thesis

- Live values and traces interpolate between five-Hz UI snapshots without
  animating the UDP ingest path.
- Driver pinning and reference changes use short, explicit layout transitions.
- New engineer messages reveal by priority and coalesce repeated conditions so
  the feed remains readable.

Motion is disabled or reduced when the browser requests reduced motion.
