# AM+8 — Phase D-0: UI Design System Infrastructure

**Mission status:** INFRASTRUCTURE ONLY (Am+8 D-0). No visual redesign. No behavior
change. No widget rewrite. No feature addition. The application's appearance and
behavior are unchanged.

**Verification:** py_compile clean on all modules; full test suite
`1621 passed, 1 skipped, 0 failures` (1610 baseline + 11 new infrastructure
invariant tests in `tests/test_design_infrastructure.py`). git status confirms
D-0 is purely additive — only `ui/design/*`, the new test, `docs/R5_EVIDENCE/*`,
and `R5_AUTO_APPROVE.md` were added; `ui/widgets/*`, `ui/theme.py`,
`ui/nabd_textual.py`, `engine/ui_theme.py`, `core/ui_bridge.py` are untouched.

---

## 1. Folder structure

```
ui/design/
├── __init__.py                 # public API surface (36 re-exports)
├── theme/
│   ├── __init__.py
│   ├── color.py                # Color value object (sole owner of color literals)
│   └── semantic.py             # SemanticTheme / SEMANTIC (single source of color meaning)
├── tokens/
│   ├── __init__.py
│   ├── spacing.py              # Spacing, Gap, Padding, Margin
│   └── sizing.py               # Radius, Elevation, Density, ProgressDensity, AnimationSpeed, Scale
├── icons/
│   ├── __init__.py
│   └── registry.py             # Icon registry (distinct glyphs, no aliases)
├── animation/
│   ├── __init__.py
│   └── profiles.py             # AnimationProfile, Spinner, AnimationSpec (definitions only)
├── typography/
│   ├── __init__.py
│   └── presets.py              # TypographyPreset presets (name+scale+emphasis+color)
├── layout/
│   ├── __init__.py
│   └── constants.py            # Layout constants (bar heights, panel widths, gaps)
├── state/
│   ├── __init__.py
│   └── ui_state.py             # UIState enum + StateRecord registry
├── primitives/
│   ├── __init__.py
│   └── widget.py               # abstract Widget base contract
└── contracts/
    ├── __init__.py
    └── widgets.py              # abstract widget interfaces (10 contracts)
```

> D-0 lives under `ui/design/` rather than `ui/theme/` to avoid colliding with
> the legacy `ui/theme.py` file that existing widgets/tests import. The legacy
> modules (`ui/theme.py`, `engine/ui_theme.py`) are migrated to `ui/design` in
> D-1+ (see Migration path). D-0 itself touches nothing legacy.

---

## 2. Dependency hierarchy (acyclic, strict)

```
widgets (future)  ->  primitives  ->  theme  ->  tokens
icons, animation                       state   ->  theme + icons + animation
typography -> theme + tokens
layout     -> tokens
contracts  -> primitives + theme + state + icons
```

Lower layers never import higher layers. Importing every submodule succeeds,
which is the acyclicity proof baked into `test_no_circular_imports`.

---

## 3. Systems (single source of truth)

| System | Module | Owns | Why single-source |
|---|---|---|---|
| Color primitive | `theme/color.py` | the `Color` type + hex normalization | the only place a color literal is parsed/validated |
| Color meaning | `theme/semantic.py` | `SEMANTIC` (Surface, Background, Border, Text, ..., Accent) | widgets read `SEMANTIC.x`; raw hex never appears in widgets |
| Spacing metrics | `tokens/spacing.py` | `SPACING`, `GAP`, `PADDING`, `MARGIN` | one owner of every distance |
| Geometry metrics | `tokens/sizing.py` | `RADIUS`, `ELEVATION`, `DENSITY`, `PROGRESS_DENSITY`, `ANIMATION_SPEED`, `SCALE` | one owner of every geometry metric |
| Icons | `icons/registry.py` | `Icon` enum | widgets resolve glyphs via `Icon.glyph(m)`; no hardcoded Unicode in widgets |
| Animation | `animation/profiles.py` | `AnimationProfile`, `Spinner`, `AnimationSpec` | definitions only (D-0 does NOT animate) |
| Typography | `typography/presets.py` | `PRESETS` (TerminalTitle, SectionTitle, Normal, ..., Error) | widgets pick a preset; never hand-build style |
| Layout | `layout/constants.py` | `LAYOUT` | no magic numbers in widgets |
| State | `state/ui_state.py` | `UIState`, `UI_STATES`, `state_of()` | every widget consumes a `UIState` instead of inventing status |

---

## 4. How D-1 through D-8 consume this infrastructure

- **D-1 (token import):** migrate `ui/theme.py::COLORS`/`PALETTE`/`PANEL_STYLES` to
  reference `SEMANTIC` + `tokens`; re-export legacy names from `ui/design` for
  backward compatibility so imports in `ui/widgets/*` and tests keep working.
  The duplicated `success`/`error`/`warning`/`info` (defined twice in legacy with
  conflicting values) collapses to one definition in `semantic.py`.
- **D-2 (state wiring):** replace ad-hoc status strings in
  `ui/widgets/status_bar.py` and `ui/live_thought.py` with `UIState` + `state_of`.
- **D-3 (icon migration):** `tool_result.py`/`footer.py` badges switch from
  hardcoded Unicode to `Icon.glyph(Icon.SUCCESS)` etc.
- **D-4 (typography):** text rendering routes through `PRESETS[...]` instead of
  bare Rich style strings.
- **D-5 (layout):** panel dimensions read `LAYOUT.panel_*` / `LAYOUT.padding`.
- **D-6 (spinner/animation):** `ui/widgets/spinner.py` consumes `AnimationSpec`
  / `Spinner` profiles (implementations added here, not in D-0).
- **D-7 (contracts):** each legacy widget subclasses the matching abstract
  contract (`StatusWidget`, `ToolWidget`, ...) so the surface area is enforced.
- **D-8 (verification):** `test_design_infrastructure.py` becomes the regression
  gate that blocks any color/spacing/typography drift.

---

## 5. Non-goals (confirmed out of D-0 scope)

- No screen redesigned; `ToolResultWidget`, `AgentStatusBar`, the Rich Live render
  path, RTL, keyboard shortcuts, and `core/ui_bridge.py` are untouched.
- No animation implemented (profiles defined only).
- No legacy `ui/theme.py` / `engine/ui_theme.py` removed (migration is D-1+).

## 6. Invariant guarantees (enforced by tests/test_design_infrastructure.py)

- Raw `Color(...)` construction occurs only inside `ui/design/theme/`
  (`test_raw_colors_only_in_theme_owner`).
- `Color` and token dataclasses are frozen/immutable (`test_color_is_immutable`).
- Every `UIState` has a complete `StateRecord` (color, icon, spinner, profile,
  priority); every `Icon`/`AnimationProfile`/`Spinner`/`PRESETS`/`LAYOUT` entry
  is present and well-typed.
- `Widget` and all 10 contracts are abstract and cannot be instantiated
  directly (`test_widget_and_contracts_are_abstract`).

## 7. Evidence

- `docs/R5_EVIDENCE/r5_full_suite3_after_design.log` — full suite
  `1621 passed, 1 skipped, 0 failures`.
- `tests/test_design_infrastructure.py` — 11 invariant tests, all passing.
