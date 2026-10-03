# Dashboard overview

The dashboard is a local personal information system. It combines manually entered state, local databases, device observations, and selected integration snapshots. This context exposes only compact analytical facts from domains with usable current data.

The source application owns data collection, validation, calculations, and persistence. This isolated workspace owns none of those responsibilities. Its role is limited to reading documented exports and producing grounded analysis when asked.

Application code calculates facts; AI interprets facts.

Use `manifest.json` to discover available files, then read the matching schema and the semantics in `README.md`. Do not assume that a dashboard feature exists merely because it is common in other personal dashboards.
