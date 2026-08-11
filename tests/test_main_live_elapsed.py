"""UI-CC-9b: الزمن الحقيقي في مسار main.py الحي."""
import time
from pathlib import Path

def test_no_hardcoded_zero_elapsed():
    src = Path("ui/event_wiring.py").read_text()
    assert "elapsed=0.0," not in src, "ما زال elapsed=0.0 ثابتاً في ui/event_wiring.py"

def test_live_sites_use_elapsed_for():
    src = Path("ui/event_wiring.py").read_text()
    assert src.count("_elapsed_for(_turn_index)") >= 2

def test_elapsed_for_increases():
    import main
    main._mark_step(901)
    time.sleep(0.12)
    assert main._elapsed_for(901) >= 0.1

def test_elapsed_for_resets_on_new_step():
    import main
    main._mark_step(902)
    assert main._elapsed_for(902) < 0.05
