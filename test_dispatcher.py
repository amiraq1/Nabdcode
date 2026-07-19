import time
import random
import os
import json
import concurrent.futures

# محاكاة بسيطة لفئة المايسترو لتجربتها مستقلة
class MultiAgentOrchestratorMock:
    def __init__(self, workspace_dir: str):
        self.workspace_dir = workspace_dir
        os.makedirs(os.path.join(workspace_dir, "graphify-out"), exist_ok=True)

    def process_graphify_chunks_parallel(self, file_chunks: list, prompt_template: str, max_workers: int = 3):
        results = []
        total_chunks = len(file_chunks)
        print(f"\n🚀 [Dispatcher] Launching {total_chunks} Sub-Agents in PARALLEL mode (Max Workers: {max_workers})...")

        def agent_task(chunk_data):
            chunk_num = chunk_data.get('chunk_num', 0)
            print(f"⚙️ [Agent {chunk_num}] Started processing chunk {chunk_num}/{total_chunks}...")
            
            # محاكاة وقت تفكير الوكيل (بين 1 إلى 3 ثوانٍ)
            time.sleep(random.uniform(1.0, 3.0))
            
            # محاكاة رد النموذج المعرفي
            simulated_response = {
                "chunk_id": chunk_num,
                "nodes": [{"id": f"Node_{chunk_num}_A", "type": "Class"}],
                "edges": [{"source": f"Node_{chunk_num}_A", "target": "MemoryManager"}]
            }
            return simulated_response

        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_to_chunk = {executor.submit(agent_task, chunk): chunk for chunk in file_chunks}
                
                for future in concurrent.futures.as_completed(future_to_chunk):
                    result = future.result()
                    results.append(result)
                    print(f"✅ [Dispatcher] Agent finished Chunk {result['chunk_id']} successfully!")
                    
        except Exception as e:
            print(f"⚠️ [Dispatcher] Parallel dispatch failed: {e}")
            # الارتداد للتنفيذ التسلسلي
            results = []
            for chunk in file_chunks:
                try:
                    result = agent_task(chunk)
                    results.append(result)
                    chunk_num = chunk.get('chunk_num', 0)
                    chunk_path = os.path.join(self.workspace_dir, "graphify-out", f".graphify_chunk_{chunk_num}.json")
                    with open(chunk_path, "w", encoding="utf-8") as f:
                        json.dump(result, f, ensure_ascii=False, indent=2)
                    print(f"✅ [Serial] Agent finished and saved Chunk {chunk_num}")
                except Exception as inner_e:
                    print(f"❌ [Serial] Agent failed on Chunk {chunk.get('chunk_num')}: {inner_e}")

        self._aggregate_graph_results(results)
        return results

    def _aggregate_graph_results(self, all_results: list):
        final_graph = {"nodes": [], "edges": [], "hyperedges": []}
        for res in all_results:
            final_graph["nodes"].extend(res.get("nodes", []))
            final_graph["edges"].extend(res.get("edges", []))
            
        output_path = os.path.join(self.workspace_dir, "graphify-out", ".graphify_semantic_new.json")
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(final_graph, f, ensure_ascii=False, indent=2)
        print(f"\n🎯 [Aggregation] Successfully merged {len(all_results)} chunks into {output_path}!\n")

# --- تشغيل الاختبار ---
if __name__ == "__main__":
    orchestrator = MultiAgentOrchestratorMock(workspace_dir=".")
    
    # 5 أجزاء وهمية تمثل ملفات المستودع
    mock_chunks = [{"chunk_num": i} for i in range(1, 6)]
    
    orchestrator.process_graphify_chunks_parallel(
        file_chunks=mock_chunks,
        prompt_template="Extract semantic graph for chunk CHUNK_NUM...",
        max_workers=3 # سيتم تشغيل 3 وكلاء معاً، ثم 2
    )
