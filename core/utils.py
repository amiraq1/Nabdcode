import shlex
import subprocess
from typing import Tuple

def safe_execute_command(command: str, timeout: int = 30) -> Tuple[int, str, str]:
    """
    Executes a shell command securely without shell=True.
    Supports piped commands securely by connecting subprocess pipes.
    """
    cmd_str = command.strip()
    if not cmd_str:
        return -1, "", "Empty command."
        
    is_bg = (
        cmd_str.endswith("&")
        or any(srv in cmd_str for srv in ["http.server", "uvicorn", "npm run dev", "npm start"])
        or cmd_str.startswith("nohup ")
    )
    if is_bg:
        bg_cmd = cmd_str[:-1].strip() if cmd_str.endswith("&") else cmd_str
        for redir in ["> /dev/null 2>&1", ">/dev/null 2>&1", "> /dev/null", ">/dev/null"]:
            if bg_cmd.endswith(redir):
                bg_cmd = bg_cmd[:-len(redir)].strip()
        try:
            args = shlex.split(bg_cmd)
            if not args:
                return -1, "", "Empty background command."
            proc = subprocess.Popen(
                args,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                start_new_session=True,
            )
            return 0, f"Background server process started successfully (PID: {proc.pid}).", ""
        except Exception as e:
            return -1, "", f"Failed to start background process: {e}"

    try:
        if "|" in cmd_str:
            segments = [seg.strip() for seg in cmd_str.split("|") if seg.strip()]
            if not segments:
                return -1, "", "Invalid piped command."
                
            procs = []
            prev_stdout = None
            for i, seg in enumerate(segments):
                args = shlex.split(seg)
                if not args:
                    return -1, "", f"Failed to parse segment: {seg}"
                
                is_last = (i == len(segments) - 1)
                proc = subprocess.Popen(
                    args,
                    stdin=prev_stdout,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True
                )
                if prev_stdout is not None:
                    prev_stdout.close()
                prev_stdout = proc.stdout
                procs.append(proc)
                
            last_proc = procs[-1]
            stdout_data, stderr_data = last_proc.communicate(timeout=timeout)
            
            for p in procs[:-1]:
                p.poll()
                if p.returncode is None:
                    p.kill()
                    p.wait()
                    
            return last_proc.returncode or 0, stdout_data or "", stderr_data or ""
        else:
            args = shlex.split(cmd_str)
            if not args:
                return -1, "", "Command parsing resulted in empty arguments."
            result = subprocess.run(
                args,
                shell=False,
                capture_output=True,
                text=True,
                timeout=timeout
            )
            return result.returncode, result.stdout or "", result.stderr or ""
    except subprocess.TimeoutExpired:
        return -1, "", f"Command execution timed out after {timeout} seconds."
    except Exception as e:
        return -1, "", f"Execution failure: {type(e).__name__}: {str(e)}"

def truncate(text: str, max_len: int = 2000) -> str:
    if not text:
        return ""
    if len(text) <= max_len:
        return text
    return text[:max_len] + f"\n... [Truncated to {max_len} characters]"
