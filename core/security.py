import shlex
from typing import Tuple
from core.constants import SAFE_BINARIES, DANGEROUS_STRICT

def validate(command: str) -> Tuple[bool, str]:
    if not command or not command.strip():
        return False, "Command is empty."
        
    cmd_str = command.strip()
    
    for op in DANGEROUS_STRICT:
        if op in cmd_str:
            return False, f"Forbidden operator '{op}' detected in command."
            
    if "|" in cmd_str:
        segments = cmd_str.split("|")
        for segment in segments:
            seg_str = segment.strip()
            if not seg_str:
                return False, "Empty pipe segment detected."
            try:
                parts = shlex.split(seg_str)
                if not parts or parts[0] not in SAFE_BINARIES:
                    return False, f"Binary '{parts[0] if parts else 'unknown'}' is not whitelisted."
            except ValueError as e:
                return False, f"Command parsing error: {e}"
        return True, "Safe piped command."
        
    try:
        parts = shlex.split(cmd_str)
        if not parts:
            return False, "Command could not be parsed into arguments."
        if parts[0] not in SAFE_BINARIES:
            return False, f"Binary '{parts[0]}' is not whitelisted."
        return True, "Safe single command."
    except ValueError as e:
        return False, f"Command parsing error: {e}"

def is_safe_command(command: str) -> bool:
    return validate(command)[0]
