import inspect
from core.llm import OpenRouterClient

print(f"Is generator function: {inspect.isgeneratorfunction(OpenRouterClient.stream)}")
