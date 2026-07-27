import dataclasses
import os, re, json, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
out = os.path.join(root, 'tests', 'snapshots')
os.makedirs(out, exist_ok=True)

# ── 1. Event snapshot ─────────────────────────────────────────────────
events = set()
for dirname in ('engine', 'core', 'tools'):
    d = os.path.join(root, dirname)
    for base, dirs, files in os.walk(d):
        dirs[:] = [d for d in dirs if d != '__pycache__']
        for f in files:
            if not f.endswith('.py'):
                continue
            path = os.path.join(base, f)
            try:
                text = open(path).read()
            except Exception:
                continue
            for m in re.finditer(r'bus\.emit\(["\']([^"\']+)["\']', text):
                events.add(m.group(1))

with open(os.path.join(out, 'event_snapshot.json'), 'w') as f:
    json.dump(sorted(events), f, indent=2)
print(f'Event snapshot: {len(events)} events written.')

# ── 2. Schema snapshot ────────────────────────────────────────────────

def _get_fields(cls):
    return {f.name: {'type': str(f.type.__name__ if hasattr(f.type, '__name__') else f.type),
                     'default': repr(f.default)}
            for f in dataclasses.fields(cls)}

schema = {}

# Attempt import of every monitored schema class.
_imports = [
    ('EvidenceRecord', 'core.evidence', 'EvidenceRecord'),
    ('VerificationResult', 'core.evidence', 'VerificationResult'),
    ('TodoItem', 'core.todo', 'TodoItem'),
    ('FinalizationDecision', 'core.convergence_gate', 'FinalizationDecision'),
    ('TodoEvidenceLink', 'core.convergence_gate', 'TodoEvidenceLink'),
    ('TurnOutcome', 'core.turn_outcome', 'TurnOutcome'),
]

try:
    from core.accept_edits_state import WalRecord
    _imports.append(('WalRecord', 'core.accept_edits_state', 'WalRecord'))
except (ImportError, AttributeError):
    pass

for name, module, cls_name in _imports:
    try:
        mod = __import__(module, fromlist=[cls_name])
        cls = getattr(mod, cls_name)
        schema[name] = {'module': module, 'fields': _get_fields(cls)}
    except (ImportError, AttributeError) as e:
        print(f'  WARNING: could not import {name}: {e}')

with open(os.path.join(out, 'schema_snapshot.json'), 'w') as f:
    json.dump(schema, f, indent=2, default=str)
print(f'Schema snapshot: {len(schema)} classes written.')
