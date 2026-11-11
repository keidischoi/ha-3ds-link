# Changelog

Each version has its own [GitHub release](https://github.com/keidischoi/ha-3ds-link/releases). The site side is the IoT link plugin ([keidischoi/g7-plugin-custom-iot_link](https://github.com/keidischoi/g7-plugin-custom-iot_link)).

## 0.8 — storage box pictures and one device per personal / company (2026-11-11)

- **0.8.14** 🗂 The box type picked on the site (storage bin · filament dryer · shelf) chooses the picture; boxes with no type still go by their name. Needs IoT link 1.19.14+ and stock management 0.3.123+.
- **0.8.13** 🎨 Box colours synced from the site (the colour picked in stock management, or the one its name gives): bin lid, dryer and shelf edges and a dot before the name. Humidity warnings still turn it orange / red. Needs IoT link 1.19.13+.
- **0.8.12** Warning colours on the box picture: bin lid, dryer body and shelf back turn orange from 50 % humidity and red over the box limit; the tile border follows.
- **0.8.11** 🧪 Resin drawn as bottles (stock list, box pictures, *Not in a box*) and counted apart from filament rolls (kg = filament only). An empty box no longer draws an empty slot.
- **0.8.10** Box pictures: humidity and temperature side by side on one line at the top; rolls use the full width below.
- **0.8.9** Filament dryer and *Not in a box* desk translucent too — every picture fits dark themes.
- **0.8.8** Storage bin and shelf translucent instead of solid white; temperature text in the theme colour.
- **0.8.7** Rolls back in the pictures, the analogue gauge removed; `spools: separate` shows only the numbers.
- **0.8.6** Box pictures show the box's temperature and humidity in big numbers (📡 *No sensor* when none).
- **0.8.5** 🧵 *Not in a box* tile for rolls in no storage box; card option `box_look: list` for the earlier text tiles.
- **0.8.4** The box name picks the picture: filament dryer · open shelf · clear storage bin.
- **0.8.3** Card option `spools` (rolls inside the box pictures or separate).
- **0.8.2** Storage boxes drawn as pictures with their rolls inside.
- **0.8.1** The connect screen no longer pre-fills a site address — known sites are offered in a list.
- **0.8.0** One device per personal / company scope using the device page's own boxes: *Controls* (🔄 Refresh now button) · *Sensors* (emoji per category) · *Diagnostic* (connected sensors). The 0.7 category devices are removed automatically.

## 0.7 — personal and company data (2026-11-11)

- **0.7.1** Category devices sit under their personal / company device.
- **0.7.0** Pick 👤 personal and / or each 🏢 company when connecting (Configure → *Personal / company data* later). Bids and requests split per scope (company: bids placed as the company, requests recommended to it). Cards and the sidebar panel choose a server · scope.

## 0.6 — dashboard cards and sidebar panel (2026-11-11)

- **0.6.1** Every sensor connected to the site is its own entity (online / offline / never). Cards pick the site with the most data when there are several.
- **0.6.0** Four dashboard cards (everything · printers · filament stock · sensors) and a 3DSSync sidebar panel; *Printing now* and *Sensors online* sensors.

## 0.5 — site → Home Assistant sensors (2026-11-11)

- **0.5.0** Notices, orders, bids, filament stock and one sensor per storage box read from the site every 5 minutes.

## Earlier

- **0.4.2** Renamed to **3DSSync** (domain `g7_link` unchanged).
- **0.4.0 – 0.4.1** Several Home Assistant servers on one link code — each tells the site which server it is.
- **0.3.x** Works with the renamed IoT link plugin; storage box names matched when almost the same.
- **0.1 – 0.2** First versions: push humidity / temperature, printer state and camera snapshots to the site.
