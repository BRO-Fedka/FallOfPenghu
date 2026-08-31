# Prompt for generating the Fall of Penghu visual concept

Copy everything below the separator into a new ChatGPT conversation. If possible, also attach:

1. A screenshot or export of the Penghu map.
2. Any generated concepts you want to preserve.
3. Screenshots of interfaces whose typography or density you like.

Ask the model to discuss the brief first. Generate images only after agreeing on the composition.

---

I am developing a desktop strategy game called **Fall of Penghu** in Python using pygame-ce. I need you to act as a game UI art director and produce a consistent visual concept for the game. Do not simplify this into a mobile tower-defense interface and do not replace the requested map with a generic fictional island.

## Game concept

The game takes place on the real Penghu archipelago. The player is a strategist organizing an ultimately doomed defense against increasingly large attacks by drone swarms, unmanned boats, missiles and, later, amphibious forces.

There is no final victory. The objective is to hold the inhabited islands for as long as possible. After several game days, the archipelago is blockaded and external supplies cease. The player may surrender at any time. Defeat occurs when all significant inhabited islands come under enemy control.

The player operates through a strategic map. There are no detailed 3D vehicle models. Units, infrastructure, contacts and orders are represented by restrained symbols, lines, zones and labels.

The emotional tone is:

- technically neutral and documentary;
- restrained rather than sensational;
- slightly monumental during major events;
- increasingly hopeless, but never visually chaotic;
- focused on responsibility, incomplete information and the cost of decisions.

## Main visual principle

The interface must look like a practical operational command system rather than:

- a science-fiction hologram;
- a cinematic HUD;
- a mobile tower-defense game;
- a neon cyberpunk screen;
- a conventional RTS with large unit portraits;
- a realistic 3D battlefield.

The map is simultaneously the game world, the main screen and the primary control surface. It should occupy approximately 75–85% of the screen.

Use flat panels, thin structural lines, compact labels, monospaced numbers and clear military-style symbols. Keep decoration minimal. Tension should be created by the information and events, not by excessive glow, animation or visual noise.

## Screen format

- Desktop game interface.
- Resizable window.
- Initial concept resolution: 1920×1080, 16:9.
- English interface.
- Future localization must remain possible, so do not make labels excessively narrow.
- The map must remain readable at smaller resolutions.

## Main screen composition

### Center: interactive strategic map

The map occupies most of the screen and shows:

- the real coastline of the Penghu archipelago;
- dark surrounding sea;
- subtle elevation shading;
- vegetation;
- roads;
- bridges;
- ports;
- important buildings;
- warehouses selected from existing civilian buildings;
- air-defense batteries;
- radars and sensors;
- military transport;
- logistics routes;
- detected enemy contacts;
- drone swarms;
- areas of uncertainty;
- front lines during the late game.

The player can zoom from an approximately 180 km strategic view to an approximately 300 m local view. Detail changes continuously with zoom level.

At the largest scale, show island shapes, major ports, important roads, strategic units and grouped contacts.

At medium scale, show bridges, warehouses, batteries, transport routes and important building categories.

At close scale, show individual buildings, local roads, positions, transport columns and visible damage.

Do not display every label at every zoom level.

### Top: thin strategic status bar

Show:

- game date;
- large readable clock, for example “02:17”;
- phase of day, for example “NIGHT”;
- campaign state, for example “BLOCKADE”;
- a few critical resources such as fuel, available air-defense missiles, active radars and transport capacity;
- warnings about active landings or interrupted supply.

Do not show dozens of resources simultaneously.

### Bottom: time controls

Show compact controls:

“PAUSE  0.25×  0.5×  1×  2×  4×  8×  16×”

Clearly highlight the selected speed. Nearby, show a short explanation when the speed is automatically reduced, for example:

“SPEED REDUCED — TARGET ENTERED AIR-DEFENSE ZONE”

Also show a compact timeline with known upcoming events:

- sunrise or sunset;
- a satellite observation window;
- estimated delivery arrival;
- known scenario events.

### Left: narrow map-mode toolbar

Include compact buttons for:

- normal map;
- radar mode;
- logistics;
- air-defense coverage;
- intelligence;
- infrastructure damage.

Normal map and radar mode must be instantly switchable with both a button and a keyboard shortcut.

### Right: contextual object panel

This panel appears or changes when an object is selected.

For a friendly unit, show:

- type and call sign;
- current state;
- current order;
- route;
- estimated arrival or completion time;
- fuel;
- functional damage;
- relevant actions.

For an air-defense battery, additionally show:

- ammunition;
- engagement sector;
- allowed target types;
- current targets;
- reload or deployment time;
- engagement doctrine.

For an enemy contact, show:

- confidence level;
- estimated type;
- estimated number;
- speed;
- course;
- altitude, if known;
- time of last detection;
- whether it is an individual target or a swarm contact.

Avoid a universal arcade-style health bar. Display functional states such as damaged radar, lost launcher, interrupted reload or closed bridge.

### Event log

Place a compact event log near an edge of the screen. Each message should contain:

- timestamp;
- category;
- short description;
- importance;
- an action for centering the map on the event.

Messages must not cover the center of the map during an attack. Reserve large modal messages for blockade, surrender and final defeat.

## Normal map mode

The normal map is a simplified geographic and topographic representation, not a satellite photograph.

Use:

- muted sea and land colors;
- subtle terrain relief;
- simplified vegetation;
- readable roads and bridges;
- restrained building footprints;
- compact infrastructure icons;
- blue friendly military symbols;
- green logistics routes;
- amber warnings;
- red only for confirmed hostile threats.

Nearby drones moving in approximately the same direction may be combined into one visual marker with a count and one direction vector. If members of the group move in different directions, show two or three short vectors rather than an arrow for every drone.

## Radar map mode

Show the same world through a more abstract operational style:

- very dark sea;
- thin island contours;
- subtle coordinate grid;
- sensor sectors;
- selected air-defense engagement sector;
- tracked contacts;
- uncertain contact regions;
- predicted movement corridors;
- short trails showing recent movement.

Do not permanently display the range circles of every radar and weapon. Show coverage primarily for selected objects or in a dedicated overlay.

An individually identified drone is displayed as a separate contact.

A target detected as a swarm is displayed as a single cluster marker with:

- estimated number or number range;
- course;
- speed;
- confidence;
- age of information;
- visible indication when the swarm begins to split.

The transition from one swarm symbol to many contacts must be gradual rather than suddenly replacing one icon with hundreds of dots.

## Visual hierarchy and colors

Use a restrained, low-saturation palette.

- Neutral cold gray-blue tones: geography and interface structure.
- Blue: friendly forces.
- Red: confirmed hostile forces only.
- Amber: uncertainty, danger and warnings.
- Green: selected or available logistics routes.
- Muted gray: old or lost contacts.

Color must not be the only carrier of meaning. Use different shapes, line patterns and labels so the interface remains readable for color-blind players.

The map is primary. Panels are secondary. Critical warnings are visible but should not dominate the entire screen.

## Drone swarm visualization

At strategic zoom:

- show one cluster marker instead of hundreds of points;
- show estimated quantity as a range if information is incomplete;
- keep the marker compact so it does not cover geography;
- show a direction vector and a predicted corridor;
- indicate splitting before creating separate new groups.

At operational zoom:

- gradually reveal individually tracked contacts;
- retain a group marker for unresolved members;
- show only short trails and current vectors;
- avoid drawing full routes for every drone.

The physical simulation may contain hundreds or up to approximately 1,000 drones, but the screen must remain readable.

## Important screen states to design

Create a coherent visual system that can support these states:

1. Calm daytime preparation in normal map mode.
2. Nighttime drone attack in normal map mode.
3. The same attack in radar mode.
4. A satellite observation window during which movement is dangerous.
5. A damaged bridge interrupting a logistics route.
6. A supply ship or convoy being intercepted.
7. Full blockade announcement.
8. Enemy landing and a moving front line.
9. Final operational report after defeat.

## Primary concept image

Generate a wide 16:9 concept for the main game screen during an active nighttime attack in normal map mode.

The real Penghu archipelago is visible from above. The sea is dark, the islands use muted geographic colors, and roads, bridges, ports, sparse buildings and subtle elevation are visible.

Friendly radars, air-defense batteries, warehouses and transport are shown as small blue operational symbols.

A large enemy drone swarm approaches from the northwest. At strategic scale it is represented by one compact cluster marker with an estimated number and several vectors indicating an emerging split. Several confirmed individual drones are shown as separate small contacts.

One air-defense battery is selected. Display only its engagement sector, ammunition and assigned targets.

One bridge is damaged. A green logistics route has been automatically redirected through a port.

At the top show:

- “02:17”
- “NIGHT”
- “BLOCKADE”
- critical fuel and missile indicators.

At the bottom show:

- “PAUSE  0.25×  0.5×  1×  2×  4×  8×  16×”
- “1×” selected;
- “SPEED REDUCED — TARGET ENTERED AIR-DEFENSE ZONE”.

Place a narrow mode toolbar on the left, a compact selected-battery panel on the right and several short timestamped warnings near an edge.

The result must look like a plausible playable desktop interface, not a promotional cinematic HUD.

All English labels must be short, readable and correctly spelled. Avoid fake paragraphs, unreadable microtext, random icons, overlapping panels and excessive glowing circles.

## Deliverables

Do not try to create every asset in one image. Work in this order:

1. Briefly analyze the requirements and identify any contradiction or missing visual decision.
2. Propose three different layout directions using short descriptions.
3. Generate 4–8 rough variants of the main nighttime screen.
4. Keep the strongest composition and refine it through edits.
5. Generate the same composition in radar mode.
6. Generate a calm daytime version.
7. Generate a close view of a port, warehouse and air-defense battery.
8. Generate a blockade announcement screen.
9. Generate a final operational report.
10. Produce a separate icon sheet for units, contacts, infrastructure and functional damage.

Maintain consistent panel placement, typography, icon language, line thickness and colors across all images.

Before generating the first image, ask me specifically for:

- the current Penghu map export;
- preferred UI density;
- preferred typography direction;
- two or three palette references;
- whether the panels should be fixed or collapsible;
- whether military symbols should resemble NATO APP-6, use an original system or use a hybrid approach;
- minimum supported resolution;
- accessibility requirements beyond color-blind readability.

