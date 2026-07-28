# core/dag/nodes/executor.py
import os
import ast
from core.dag.base import BaseNode, Edge
from core.dag.context import NabdExecutionContext

class ExecutorNode(BaseNode):
    """
    عقدة التنفيذ والكتابة (The Surgeon's Scalpel).
    تستلم التعديلات المُصادق عليها، تجري فحصاً نحوياً (Syntax Check) صارماً،
    ثم تقوم بكتابة التعديلات بأمان على القرص.
    """
    def __init__(self, node_id: str = "executor_node"):
        super().__init__(node_id)

    def execute(self, context: NabdExecutionContext) -> Edge:
        print("\n⚙️  [Executor Node] Applying approved modifications to disk...")
        
        # ملاحظة معمارية: نفترض هنا أن context.code_diffs يحتوي على 
        # { "مسار_الملف": "الكود_الجديد_بالكامل" } لضمان سلامة التنفيذ.
        
        # Policy: resolved workspace root is authoritative
        resolved_workspace = os.path.realpath(context.workspace_dir)
        
        for file_path, new_content in context.code_diffs.items():
            # Workspace symlink / path traversal containment
            norm_file_path = os.path.normpath(file_path)
            if os.path.isabs(norm_file_path) or norm_file_path.startswith(".."):
                print(f"❌ [Executor] FileSystem Error - Path escapes workspace: {file_path}")
                context.error_flags = True
                return Edge(target_node_id="end", reason="Fatal I/O Error: Path escapes workspace")
                
            full_path = os.path.join(resolved_workspace, norm_file_path)
            
            # 1. الدرع الأخير: الفحص النحوي (Syntax Validation) قبل المساس بالقرص
            try:
                ast.parse(new_content)
            except SyntaxError as e:
                print(f"❌ [Executor] CRITICAL: Syntax Error detected in the proposed code for {file_path}!")
                print(f"   Details: {e}")
                
                # حفظ الخطأ للوكيل لكي يتعلم منه
                context.shared_memory['execution_error'] = f"Syntax Error in {file_path}: {e}"
                print("⏪ [Executor] Rolling back! Returning to Reasoner Node to fix the syntax...")
                
                # توجيه عكسي لعقدة التفكير (الوكيل) لإصلاح خطئه النحوي
                return Edge(target_node_id="reasoner_node", reason="Syntax verification failed")

            # 2. الجراحة: الكتابة الفعلية على القرص
            try:
                target_dir = os.path.dirname(full_path)
                resolved_target_dir = os.path.realpath(target_dir)
                if not resolved_target_dir.startswith(resolved_workspace) and resolved_target_dir != resolved_workspace:
                    raise PermissionError("Directory escapes workspace")

                os.makedirs(resolved_target_dir, exist_ok=True)
                
                dir_fd = os.open(resolved_target_dir, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    import stat
                    import errno
                    basename = os.path.basename(full_path)
                    created = False
                    
                    try:
                        # Try as New Target
                        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | getattr(os, 'O_NONBLOCK', 0)
                        fd = os.open(basename, flags, 0o666, dir_fd=dir_fd)
                        created = True
                    except FileExistsError:
                        # Try as Existing Target
                        flags = os.O_WRONLY | os.O_NOFOLLOW | getattr(os, 'O_NONBLOCK', 0)
                        fd = os.open(basename, flags, dir_fd=dir_fd)
                        
                    try:
                        st = os.fstat(fd)
                        
                        # Verify regular file
                        if not stat.S_ISREG(st.st_mode):
                            raise OSError(errno.EINVAL, "Not a regular file")
                        
                        # Only after successful validation call ftruncate
                        if not created:
                            os.ftruncate(fd, 0)
                        
                        # clear nonblock flag to safely write large content
                        if hasattr(os, 'set_blocking'):
                            os.set_blocking(fd, True)
                            
                        # write
                        os.write(fd, new_content.encode('utf-8'))
                    except Exception:
                        if created:
                            # clean up a failed newly-created target only if inode identity proves it is the file created by this operation
                            try:
                                curr_st = os.stat(basename, dir_fd=dir_fd, follow_symlinks=False)
                                if curr_st.st_ino == st.st_ino and curr_st.st_dev == st.st_dev:
                                    os.unlink(basename, dir_fd=dir_fd)
                            except OSError:
                                pass
                        raise
                    finally:
                        os.close(fd)
                finally:
                    os.close(dir_fd)
                    
                print(f"✅ [Executor] Successfully deployed updates to: {file_path}")
                
            except Exception as e:
                print(f"❌ [Executor] FileSystem Error - Disk write failed for {file_path}: {e}")
                context.error_flags = True
                return Edge(target_node_id="end", reason="Fatal I/O Error")

        # 3. إفراغ ذاكرة التعديلات بعد التنفيذ الناجح
        context.code_diffs.clear()
        
        print("🏁 [Executor] All modifications applied safely. Surgery complete.")
        # التوجيه لمحطة الطرفية لفحص أو تشغيل الأوامر إن وجدت
        return Edge(target_node_id="terminal_node", reason="Code deployed, checking for execution validation")
