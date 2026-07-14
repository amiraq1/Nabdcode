"""Debug tool: test ReAct loop with abstract tasks (no file extensions)."""
import sys, os, logging, json, urllib.request
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("DebugReAct")

NVIDIA_KEY = os.getenv("NVIDIA_API_KEY", 
    "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")
NVIDIA_URL = "https://integrate.api.nvidia.com/v1/chat/completions"

def _nvidia_chat(messages):
    adapted = []
    for m in messages:
        role = m.get("role", "user")
        content = m.get("content", "")
        if role == "tool":
            adapted.append({"role": "user", "content": f"[Tool Result]\n{content}"})
        elif role == "assistant" and content:
            adapted.append({"role": "assistant", "content": str(content)[:2000]})
        elif role in ("system", "user"):
            adapted.append({"role": role, "content": str(content)[:4000]})
    
    payload = json.dumps({
        "model": "meta/llama-3.1-8b-instruct",
        "messages": adapted,
        "temperature": 0.1,
        "max_tokens": 4096,
    }).encode()
    
    req = urllib.request.Request(
        NVIDIA_URL, data=payload,
        headers={
            "Authorization": f"Bearer {NVIDIA_KEY}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read().decode())
        return data["choices"][0]["message"]["content"]

from pathlib import Path
from smolagents import CodeAgent, LiteLLMModel
from tools.secure_tools import SecureWorkspaceReader, SecureGitInspector

LiteLLMModel.chat = lambda self, msgs: _nvidia_chat(msgs)

reader = SecureWorkspaceReader(workspace_root=str(Path.cwd()))
git = SecureGitInspector()

agent = CodeAgent(
    tools=[reader, git],
    model=LiteLLMModel(),
    max_steps=4,
    name="TestAgent",
)

# Pure abstract task: NO keywords → forces ReAct loop (no fast-path match)
task = 'Analyze the architecture of this project. Use available tools to inspect the project and report what you find about its structure.'
logger.info(f"ABSTRACT TASK: {task}")
result = agent.run(task)
print("\n" + "="*60)
print(f"FINAL RESULT ({len(str(result))} chars):")
print(str(result)[:2000])
