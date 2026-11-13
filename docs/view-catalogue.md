# View catalogue

Every route of the PWA's hash router, the panel it shows and the navigation
item it belongs to. Everything between the markers is generated from the
router's tables in `public/navigation.js` (`NAV_ROUTES`, `NAV_LINK_ROUTES`,
the segment lists and `ROUTE_ALIASES`) by
`node tests/navigation-state.test.cjs --write`; a test fails when it is out of
date. An unknown route opens the default route.

<!-- BEGIN GENERATED VIEWS -->
Default route: `#coach`. Navigation items: `#coach`, `#plan`, `#nutrition`, `#analysis`, `#more`.

| Route | Panel | Navigation item |
| --- | --- | --- |
| `#analysis` | `dataPanel` | `analysis` |
| `#analysis/cycling` | `dataPanel` | `analysis` |
| `#analysis/load` | `dataPanel` | `analysis` |
| `#analysis/recovery` | `dataPanel` | `analysis` |
| `#analysis/running` | `dataPanel` | `analysis` |
| `#coach` | `chatPanel` | `coach` |
| `#more` | `settingsPanel` | `more` |
| `#more/appearance` | `settingsPanel` | `more` |
| `#more/coach` | `settingsPanel` | `more` |
| `#more/connections` | `settingsPanel` | `more` |
| `#more/equipment` | `settingsPanel` | `more` |
| `#more/operations` | `settingsPanel` | `more` |
| `#more/profile` | `profilePanel` | `more` |
| `#nutrition` | `nutritionPanel` | `nutrition` |
| `#nutrition/body` | `nutritionPanel` | `nutrition` |
| `#nutrition/diary` | `nutritionPanel` | `nutrition` |
| `#nutrition/products` | `nutritionPanel` | `nutrition` |
| `#nutrition/week` | `nutritionPanel` | `nutrition` |
| `#plan` | `workoutsPanel` | `plan` |
| `#plan/library` | `workoutsPanel` | `plan` |
| `#plan/overview` | `workoutsPanel` | `plan` |
| `#plan/season` | `workoutsPanel` | `plan` |

Kalender segments: `overview`, `library`, `season`.
Mehr segments: `profile`, `equipment`, `connections`, `coach`, `operations`, `appearance`.

Former routes that open another view:

- `#analysis/performance` opens `#analysis/running`
- `#analysis/sessions` opens `#plan/overview`
<!-- END GENERATED VIEWS -->
