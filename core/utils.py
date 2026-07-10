import shlex
import subprocess
import threading
from typing import List, Tuple

from core.security import split_pipe_segments, validate
from core.sanitize import sanitize


def safe_execute_command(command: str, timeout: int = 30) -> Tuple[int, str, str]:
    """
    Executes a shell command securely without shell=True.
    Supports piped commands securely by connecting subprocess pipes.
    Pipe segment boundaries are determined by the canonical parser
    in core.security (quote-aware via shlex punctuation_chars).
    """
    cmd_str = command.strip()
    if not cmd_str:
        return -1, "", "Empty command."

    ok, err = validate(cmd_str)
    if not ok:
        return -1, "", f"Security validation failed: {err}"

    try:
        raw_tokens = shlex.split(cmd_str)
    except Exception as e:
        return -1, "", f"Command tokenization error: {e}"

    is_bg = (
        raw_tokens[-1] == "&"
        or cmd_str.endswith("&")
        or (
            len(raw_tokens) > 1
            and raw_tokens[0] in ("uvicorn", "python", "python3")
            and any("http.server" in t for t in raw_tokens)
        )
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
        ok, segments, err = split_pipe_segments(cmd_str)
        if ok and len(segments) > 1:
            # Piped command — drain all stderr concurrently to prevent pipe buffer deadlock
            procs: List[subprocess.Popen] = []
            prev_stdout = None
            stderr_parts: list[list[str]] = [[] for _ in segments]
            stderr_threads: list[threading.Thread] = []

            def _drain_stderr(idx: int, pipe) -> None:
                """Read all stderr from process idx into stderr_parts[idx]."""
                try:
                    for line in pipe:
                        stderr_parts[idx].append(line)
                except ValueError:
                    pass
                finally:
                    try:
                        pipe.close()
                    except Exception:
                        pass

            for i, seg_tokens in enumerate(segments):
                proc = subprocess.Popen(
                    seg_tokens,
                    stdin=prev_stdout,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                if prev_stdout is not None:
                    prev_stdout.close()
                prev_stdout = proc.stdout
                procs.append(proc)
                # Drain stderr in a thread so it never blocks the pipe
                t = threading.Thread(target=_drain_stderr, args=(i, proc.stderr), daemon=True)
                t.start()
                stderr_threads.append(t)

            last_proc = procs[-1]
            stdout_data, stderr_data = last_proc.communicate(timeout=timeout)

            # Wait for stderr drainers to finish
            for t in stderr_threads:
                t.join(timeout=5)

            # Kill any hung intermediate processes
            for p in procs[:-1]:
                p.poll()
                if p.returncode is None:
                    p.kill()
                    p.wait()

            combined_stderr = "".join("".join(part) for part in stderr_parts)
            return last_proc.returncode or 0, sanitize(stdout_data or ""), sanitize(combined_stderr or "")
        else:
            # Simple command
            args = shlex.split(cmd_str)
            if not args:
                return -1, "", "Command parsing resulted in empty arguments."
            result = subprocess.run(
                args,
                shell=False,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            return result.returncode, sanitize(result.stdout or ""), sanitize(result.stderr or "")

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
