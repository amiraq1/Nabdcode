"""Debug tool: test multi-root ReAct loop against 9router with real analysis."""
import sys, os, logging
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("DebugMultiRoot")

from core.agent_manager import initialize_secure_agent

manager = initialize_secure_agent()
executor = next(iter(manager.managed_agents.values())).agent

# مهمة تجريدية بحتة — لا امتدادات ملفات — تضرب ReAct loop مباشرة
task = ('What is the provider routing fallback strategy in the 9router project? '
        'Use the tools to read the relevant files and report the architecture.')
logger.info(f"MULTI-ROOT REACT TASK: {task}")
result = executor.run(task)
print("\n" + "="*60)
print(f"FINAL ANALYSIS ({len(str(result))} chars):")
print(str(result)[:3000])
