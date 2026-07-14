# tests/debug_executor.py
import sys
import os
import logging

# إضافة المسار الرئيسي للنظام لضمان الاستيراد السليم
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# تفعيل السجلات بأعلى مستوى لرصد النبض الداخلي
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("DebugExecutor")

from core.agent_manager import initialize_secure_agent

def run_isolated_test():
    logger.info("⚡ Igniting Secure Agent Environment...")
    
    # 1. استخراج الوكيل المدير ونواة المنفذ
    manager = initialize_secure_agent()
    
    # استخراج المنفذ الفعلي من قائمة الوكلاء المدارين
    system_executor_wrapper = manager.managed_agents.get("system_executor") or list(manager.managed_agents.values())[0]
    executor_agent = system_executor_wrapper.agent
    
    # 2. صياغة الطلب الذي فجّر ثغرة الـ Pattern Matching
    target_task = "Audit our 9router repository to reverse-engineer its provider routing architecture."
    
    logger.info(f"🚀 Pushing Target Task: '{target_task}' directly to Executor.")
    print("\n" + "="*60 + "\n[START EXECUTION PATH MAP]\n" + "="*60)
    
    try:
        # استدعاء المنفذ مباشرة معزولاً عن كسل المدير
        raw_result = executor_agent.run(target_task)
        
        print("\n" + "="*60)
        logger.info(f"🏆 Raw Result Returned: {raw_result}")
        logger.info(f"📊 Result Type: {type(raw_result)}")
        
    except Exception as e:
        logger.error(f"💥 Execution Crashed: {e}", exc_info=True)

if __name__ == "__main__":
    run_isolated_test()
