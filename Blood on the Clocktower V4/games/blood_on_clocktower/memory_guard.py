"""内存守卫 — 申请释放、防崩、自动降级"""
import ctypes, os, time, psutil
import gc, torch

class MemoryGuard:
    @staticmethod
    def free_mem_gb():
        """当前可用内存(GB)"""
        return psutil.virtual_memory().available / 1e9

    @staticmethod
    def gpu_free_gb():
        """GPU可用显存(GB)"""
        try:
            return torch.cuda.mem_get_info()[0] / 1e9
        except:
            return 0

    @staticmethod
    def release_system_caches():
        """释放所有能释放的系统缓存"""
        # 1. 清空自己的Python进程工作集
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetCurrentProcess()
        kernel32.SetProcessWorkingSetSize(handle, -1, -1)

        # 2. 清空所有进程工作集（不杀进程，只释放空闲页）
        freed = 0
        for pid in psutil.pids():
            try:
                h = kernel32.OpenProcess(0x1F0FFF, False, pid)
                if h:
                    kernel32.SetProcessWorkingSetSize(h, -1, -1)
                    kernel32.CloseHandle(h)
                    freed += 1
            except:
                pass

        # 3. Python垃圾回收
        gc.collect()

        # 4. torch缓存清理
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.synchronize()

        before = psutil.virtual_memory().available / 1e9
        print(f"MemoryGuard: 释放了 {freed} 个进程工作集, 可用内存 {before:.1f}GB")
        return before

    @staticmethod
    def can_load_model(model_size_gb=3):
        """检查是否能加载模型"""
        ram = MemoryGuard.free_mem_gb()
        gpu = MemoryGuard.gpu_free_gb()
        needed = model_size_gb * 1.5  # 需要1.5倍模型大小
        
        if gpu > needed:
            return True, f"GPU够用({gpu:.1f}GB > {needed:.1f}GB)"
        elif ram > needed:
            return True, f"RAM够用({ram:.1f}GB > {needed:.1f}GB)"
        else:
            return False, f"内存不足: GPU={gpu:.1f}GB RAM={ram:.1f}GB, 需要{needed:.1f}GB。请重启电脑释放缓存"

    @staticmethod
    def safe_load_model(load_fn, model_name="model"):
        """安全加载模型：先释放→再检查→再加载→防崩"""
        # Step 1: 尽力释放
        MemoryGuard.release_system_caches()
        
        # Step 2: 检查
        ok, reason = MemoryGuard.can_load_model()
        print(f"[MemoryGuard] {reason}")
        if not ok:
            return None, reason
        
        # Step 3: 加载（带异常保护）
        try:
            before = torch.cuda.mem_get_info()[0] / 1e9 if torch.cuda.is_available() else 0
            print(f"[MemoryGuard] 开始加载{model_name}...")
            model = load_fn()
            after = torch.cuda.mem_get_info()[0] / 1e9 if torch.cuda.is_available() else 0
            print(f"[MemoryGuard] {model_name}加载完成, GPU显存: {before:.1f}→{after:.1f}GB")
            return model, "OK"
        except Exception as e:
            # 崩了立即清内存
            torch.cuda.empty_cache()
            gc.collect()
            return None, str(e)[:100]

    @staticmethod
    def release_after_inference():
        """推理后释放临时内存"""
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
