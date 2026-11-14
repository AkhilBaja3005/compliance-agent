# Graphite branding

## Color palette

| Color | Hex |
| --- | --- |
| Near black | `#030710` |
| Dark navy | `#0D1322` |
| Navy | `#161F34` |
| Slate | `#2F4B68` |
| Muted blue | `#40668D` |
| Steel blue | `#7F97B2` |
| Primary blue | `#006DDD` |
| Sky blue | `#7FC8FF` |
| Light blue | `#99D3FF` |
| Pale blue | `#B2DEFF` |
| Border blue | `#CCE9FF` |
| Background blue | `#E5F4FF` |
| Surface blue | `#F2FAFF` |
| Purple | `#7E65AE` |

## Dashboard usage

- Main background: `#E5F4FF`.
- Panels and top bar: `#F2FAFF`.
- Sidebar: `#0D1322`, with light text.
- Primary actions and active navigation: `#006DDD`.
- Main text: `#161F34`; secondary text: `#40668D`.
- Borders: `#CCE9FF`.
- Human review accent: `#7E65AE`.

## Severity and status colors

Keep the brand palette for the interface. Use these semantic colors for warning
levels, findings, charts, and status messages:

| Level | Color | Hex |
| --- | --- | --- |
| Low / passed | Green | `#15803D` |
| Medium / suspected gap | Yellow | `#CA8A04` |
| High | Orange | `#EA580C` |
| Critical / confirmed violation | Red | `#DC2626` |

Badges and notices use matching pale backgrounds with darker text for readability.
Human review remains purple (`#7E65AE`); informational and unspecified findings
use neutral steel blue (`#7F97B2`). Keep text labels alongside colors.

## Logo

Use [the icon-only PNG](../assets/graphite_report_logo.png) with separate
“graphite” text for dashboard branding. Keep its aspect ratio and transparency.
Use the same icon for the favicon and footer.

The dashboard styles live in
[dashboard.css](../src/dashboard/static/dashboard.css).
