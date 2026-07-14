import os
from core.agent_manager import initialize_secure_agent

def main():
    print("🚀 Initializing Hierarchical Agent System...")
    workspace = os.getcwd()
    manager_agent = initialize_secure_agent(workspace_path=workspace)
    
    # 🟩 إزالة الكلمات المفتاحية المربكة (مثل Test) واستخدام لغة توجيهية صارمة
    complex_task = """
    Please demonstrate your automation skills by strictly executing these steps in order:
    1. Delegate to 'system_executor' to WRITE a file named 'calc_math.py' using secure_file_system with action='write', path='calc_math.py', and content exactly:
       print(6 * 5 * 4 * 3 * 2 * 1)
    2. Delegate to 'system_executor' to run this shell command via secure_shell: python3 calc_math.py
    3. Return the exact numerical output in your Final Answer.
    Do NOT use shell redirection (>) or the test runner.
    """
    
    print("\n🎯 Task:")
    print(complex_task)
    print("-" * 50)
    print("🧠 Agent is thinking... (Watching for proper tool routing)\n")
    
    try:
        final_result = manager_agent.run(complex_task)
        
        print("\n" + "=" * 50)
        print("✅ Manager Final Report:")
        print(final_result)
        print("=" * 50)
        
        print("\n🔍 Execution Logs:")
        # 🟩 طريقة آمنة لسحب سجلات التفكير تناسب النسخة المضمنة لديك
        logs = getattr(manager_agent, 'logs', None)
        if logs:
            for step in logs:
                print(str(step))
        else:
            print("No 'logs' attribute found. Agent might use a different state tracker.")
            
    except Exception as e:
        print(f"\n❌ Error during execution: {str(e)}")

if __name__ == "__main__":
    main()
