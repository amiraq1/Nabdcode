# ui.design — TUI Design System foundation (Am+8 D-0)

Additive infrastructure only. No widget or behavior was modified by D-0.

```
ui/design/ -> theme/color.py    (Color primitive — sole ownership of color literals)
             theme/semantic.py  (SEMANTIC — single source of color meaning)
             tokens/            (Spacing, Gap, Padding, Margin, Radius, Elevation,
                                Density, ProgressDensity, AnimationSpeed, Scale)
             icons/registry.py  (Icon — no raw Unicode in widgets)
             animation/         (AnimationProfile, Spinner, AnimationSpec — defined; not implemented)
             typography/        (PRESETS — pick a preset, never hand-build style)
             layout/            (LAYOUT constants — no magic numbers)
             state/             (UIState + UI_STATES registry + state_of)
             primitives/widget.py   (abstract Widget base contract)
             contracts/widgets.py   (10 abstract widget interfaces)
```

Usage (future widgets — D-1+):

```python
from ui.design import SEMANTIC, PRESETS, UIState, state_of, Icon, LAYOUT

color = SEMANTIC.success            # Color — never a raw hex string
typo  = PRESETS["section_title"]    # TypographyPreset
state = state_of(UIState.THINKING)  # StateRecord: color, icon, spinner, profile, priority
glyph = Icon.glyph(Icon.SUCCESS)    # resolve a glyph in one place
width = LAYOUT.panel_default_width  # layout constant
```

Dependency hierarchy (strict, acyclic):

```
widgets (future) -> primitives -> theme -> tokens
icons, animation                       state -> theme + icons + animation
typography -> theme + tokens
layout     -> tokens
contracts  -> primitives + theme + state + icons
```

Migration of legacy `ui/theme.py` / `engine/ui_theme.py` to this system is D-1+.
See `docs/AM8_D0_INFRASTRUCTURE.md`.
