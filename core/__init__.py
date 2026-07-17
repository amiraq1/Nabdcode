# Core package — strict modular architecture
#
# All internal imports use direct module paths (e.g. from core.parser import X).
# The legacy barrel re-exports have been removed to eliminate the SCC
# (Strongly Connected Component) mega-cycle.  If you need a symbol,
# import it from its canonical module:
#
#   from core.parser   import validate_tool_call
#   from core.sanitize import sanitize
#   from core.security import validate
#   ...
