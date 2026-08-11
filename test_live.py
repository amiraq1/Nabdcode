from rich.console import Console
from rich.live import Live
import io

buf = io.StringIO()
c = Console(file=buf, force_terminal=True, color_system="truecolor")
live = Live("Hello", console=c, auto_refresh=False)
with live:
    live.update("World", refresh=True)
print(repr(buf.getvalue()))
