import sys
import re

with open("main.py", "r") as f:
    lines = f.readlines()

start_idx = -1
end_idx = -1

for i, line in enumerate(lines):
    if "# ── Event Wiring ─" in line:
        start_idx = i
    if line.startswith("# ── System Setup ─"):
        end_idx = i
        break

if start_idx == -1 or end_idx == -1:
    print("Could not find boundaries")
    sys.exit(1)

extracted_lines = lines[start_idx:end_idx]

# Remove extracted lines from main.py, and insert the import alias
new_main_lines = lines[:start_idx] + [
    "# ── Event Wiring ───────────────────────────────────────────────────────────\n",
    "from ui.event_wiring import (wire_events, _mark_step, _elapsed_for, status_bar)  # ARCH-5\n",
    "\n"
] + lines[end_idx:]

with open("main.py", "w") as f:
    f.writelines(new_main_lines)

# Create ui/event_wiring.py
# Add imports missing for the extracted block
event_wiring_lines = [
    '"""Event wiring module for NABD OS (ARCH-5 extracted)."""\n',
    "from __future__ import annotations\n",
    "import time\n",
]

event_wiring_lines.extend(extracted_lines)

with open("ui/event_wiring.py", "w") as f:
    f.writelines(event_wiring_lines)
