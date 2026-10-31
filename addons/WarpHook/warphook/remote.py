"""跨进程读链：把 base.read_chain 的能力搬到 ReadProcessMemory 上。

为什么需要它：``base.read_chain`` 是**本进程裸读**（ctypes.from_address），
只能用于「诊断脚本和游戏在同一进程」的场合；外部独立进程（启动器已退出、
DLL standalone 存活时的诊断脚本、测试工具）拿游戏对象地址去裸读必然访问
违例（真机实测：段错误 exit 139，或读到垃圾返回 None）。

本模块用 ReadProcessMemory 实现同一套链语法（含 v6 字典步/迭代位/聚合读），
失败只会得到 None，不会崩 —— 「插件偏移写错宁可读不到不能崩」的同一条纪律
在跨进程侧也要成立。

用法::

    rr = RemoteReader(pid)                 # 或 RemoteReader.by_process("x.exe")
    rr.read_chain(addr, [{'off': 0x90}], 'dict_count')
    rr.read_chain(addr, [{'dict': 'iter'}, {'off': 0x60, 'deref': False}], 'int')
"""
import ctypes

k32 = ctypes.WinDLL("kernel32", use_last_error=True)

PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_VM_READ = 0x0010
TH32CS_SNAPPROCESS = 0x00000002
MAX_LEN = 0x10000          # 容器长度上限（偏移写错时的防呆）


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [("dwSize", ctypes.c_uint32), ("cntUsage", ctypes.c_uint32),
                ("th32ProcessID", ctypes.c_uint32),
                ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
                ("th32ModuleID", ctypes.c_uint32),
                ("cntThreads", ctypes.c_uint32),
                ("th32ParentProcessID", ctypes.c_uint32),
                ("pcPriClassBase", ctypes.c_long),
                ("dwFlags", ctypes.c_uint32),
                ("szExeFile", ctypes.c_wchar * 260)]


class RemoteReader:
    """一个目标进程的只读视图。构造失败抛 OSError，之后每个读操作只返回 None。"""

    def __init__(self, pid):
        self.pid = int(pid)
        self.proc = k32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ,
                                    False, self.pid)
        if not self.proc:
            raise OSError(ctypes.get_last_error(),
                          "OpenProcess(%d) failed" % self.pid)

    # ---- 生命周期 -------------------------------------------------------
    def close(self):
        if self.proc:
            k32.CloseHandle(self.proc)
            self.proc = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False

    def __del__(self):
        try:
            self.close()
        except Exception:  # noqa: BLE001
            pass

    @classmethod
    def by_process(cls, exe_name):
        """按可执行文件名找 pid（同名多开取第一个）。找不到返回 None。"""
        snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
        if snap == ctypes.c_void_p(-1).value:
            return None
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        try:
            ok = k32.Process32FirstW(snap, ctypes.byref(entry))
            while ok:
                if entry.szExeFile.lower() == exe_name.lower():
                    return int(entry.th32ProcessID)
                ok = k32.Process32NextW(snap, ctypes.byref(entry))
        finally:
            k32.CloseHandle(snap)
        return None

    # ---- 原始读取 -------------------------------------------------------
    def read(self, addr, size):
        """读 size 字节，返回 bytes；读不到返回 None。"""
        addr = int(addr or 0)
        if not addr or size <= 0:
            return None
        buf = ctypes.create_string_buffer(size)
        got = ctypes.c_size_t(0)
        ok = k32.ReadProcessMemory(self.proc, ctypes.c_void_p(addr), buf,
                                   ctypes.c_size_t(size), ctypes.byref(got))
        return buf.raw[:got.value] if ok else None

    def can_read(self, addr, size=8):
        return self.read(addr, size) is not None

    def u64(self, addr):
        b = self.read(addr, 8)
        return ctypes.c_uint64.from_buffer_copy(b).value if b and len(b) == 8 else None

    def i32(self, addr):
        b = self.read(addr, 4)
        return ctypes.c_int32.from_buffer_copy(b).value if b and len(b) == 4 else None

    def u32(self, addr):
        v = self.i32(addr)
        return v & 0xFFFFFFFF if v is not None else None

    def f32(self, addr):
        b = self.read(addr, 4)
        return ctypes.c_float.from_buffer_copy(b).value if b and len(b) == 4 else None

    # ---- 容器（il2cpp 固定布局） ----------------------------------------
    def list_items(self, lst):
        """List<T>：返回 (items 指针, 元素数)。"""
        n = self.i32(int(lst) + 0x18)
        p = self.u64(int(lst) + 0x10)
        if n is None or not p or n < 0 or n > MAX_LEN:
            return None, 0
        return p, n

    def array_len(self, arr):
        n = self.i32(int(arr) + 0x18)
        if n is None or n < 0 or n > MAX_LEN:
            return 0
        return n

    def dict_count(self, d):
        """活跃 entry 数 = count(+0x20) - freeCount(+0x28)。

        il2cpp 字段序是 count/freeList/freeCount/version（+0x2C 是 version），
        与 .NET reference source 不同 —— 真机实测纠正，别再改回 +0x2C。
        """
        total = self.i32(int(d) + 0x20)
        free = self.i32(int(d) + 0x28)
        if total is None or free is None or total < 0 or total > MAX_LEN:
            return 0
        if free < 0 or free > total:
            return 0                    # 形状不合法（多半是陈旧/错位指针）
        return total - free

    def dict_nth(self, d, nth, stride=24, value_off=16, raw32=False):
        """跳死坑取第 nth 个活跃 entry 的 value（指针或 4B 值）。"""
        d = int(d)
        entries = self.u64(d + 0x18)
        count = self.i32(d + 0x20)
        if not entries or count is None or count <= 0 or count > MAX_LEN:
            return None
        for i in range(count):
            ent = entries + 0x20 + i * stride
            hc = self.i32(ent)
            if hc is None:
                return None
            if hc < 0:
                continue                       # Remove 留下的死坑
            if nth <= 0:
                return (self.u32(ent + value_off) if raw32
                        else self.u64(ent + value_off))
            nth -= 1
        return None

    # ---- 读链 -----------------------------------------------------------
    def read_chain(self, addr, chain=None, kind="int"):
        """与 base.read_chain 同一套链语法（dict/iter/聚合读全支持）。"""
        chain = list(chain or [])
        kind = str(kind or "int")

        if not chain:
            return self._landing_zero(addr, kind)

        cur = int(addr or 0)
        value_mode = False
        for step in chain:
            off, code, index = self._step_tuple(step)
            if value_mode:
                return None
            if code in (6, 7):                       # dict / dict_val
                if not self.can_read(cur, 0x30):
                    return None
                stride = (off >> 8) & 0xFF or 24
                voff = off & 0xFF or 16
                nth = (off >> 16) & 0x7FFF
                cur = self.dict_nth(cur, nth, stride, voff, raw32=(code == 7))
                if cur is None:
                    return None
                value_mode = (code == 7)
                continue
            if code in (4, 5):                       # list_val / array_val
                if code == 4:
                    arr, count = self.list_items(cur)
                else:
                    arr, count = cur, self.array_len(cur)
                idx = int(index if index is not None else off)
                if not arr or idx < 0 or idx >= count:
                    return None
                cur = self.i32(arr + 0x20 + idx * 4)
                if cur is None:
                    return None
                cur &= 0xFFFFFFFF
                value_mode = True
                continue
            if code in (2, 3):                       # list / array
                if code == 2:
                    arr, count = self.list_items(cur)
                else:
                    arr, count = cur, self.array_len(cur)
                idx = int(index if index is not None else off)
                if not arr or idx < 0 or idx >= count:
                    return None
                cur = self.u64(arr + 0x20 + idx * 8)
                if cur is None:
                    return None
                continue
            cur += off
            if code == 1:                            # deref
                cur = self.u64(cur)
                if not cur:
                    return None
        if value_mode:
            return self.f32(cur) if kind == "float" else cur
        return self._landing(cur, kind)

    # ---- 内部 -----------------------------------------------------------
    @staticmethod
    def _step_tuple(step):
        """把配置步归一成 (off|packed, code, index)，与 base 同一套规矩。"""
        if isinstance(step, dict):
            if "dict" in step or "dict_val" in step:
                key = "dict_val" if "dict_val" in step else "dict"
                code = 7 if key == "dict_val" else 6
                raw = step[key]
                idx = int(raw) if isinstance(raw, int) else int(step.get("index", 0))
                off = ((int(step.get("value_off", 16)) & 0xFF)
                       | ((int(step.get("stride", 24)) & 0xFF) << 8)
                       | ((idx & 0x7FFF) << 16))
                return off, code, None
            return (int(step.get("off", 0)),
                    int(step.get("deref", 1)) & 0x7
                    if not isinstance(step.get("deref"), bool)
                    else (1 if step.get("deref") else 0),
                    step.get("index"))
        if isinstance(step, (tuple, list)) and len(step) >= 2:
            v = step[1]
            code = (1 if v else 0) if isinstance(v, bool) else (int(v) & 0x7)
            return int(step[0]), code, (step[2] if len(step) > 2 else None)
        return int(step), 1, None

    def _landing_zero(self, addr, kind):
        """零跳链：addr 本身是落点（聚合读也在这里生效）。"""
        if addr is None:
            return None
        if kind == "dict_count":
            return self.dict_count(addr)
        if kind == "count":
            n = self.array_len(addr)
            return n or None
        if kind == "float":
            return self.f32(addr)
        return int(addr)

    def _landing(self, cur, kind):
        if kind == "sum":
            arr, count = self.list_items(cur)
            if not arr or count <= 0:
                return None
            b = self.read(arr + 0x20, count * 4)
            if not b:
                return None
            return sum(ctypes.c_int32.from_buffer_copy(
                b[i * 4:i * 4 + 4]).value for i in range(count))
        if kind == "count":
            n = self.array_len(cur)
            return n
        if kind == "dict_count":
            return self.dict_count(cur)
        if kind == "text":
            slen = self.i32(cur + 0x10)
            if not slen or slen <= 0 or slen > 4096:
                return None
            b = self.read(cur + 0x14, slen * 2)
            if not b:
                return None
            chars = b.decode("utf-16-le", "ignore")
            digits = "".join(ch for ch in chars[:9] if ch.isdigit())
            return int(digits) if digits else None
        if kind == "float":
            return self.f32(cur)
        if kind == "obscured":
            key, hidden = self.i32(cur), self.i32(cur + 4)
            if key is None or hidden is None:
                return None
            return key ^ hidden                  # ObscuredInt 真值 = hidden ^ key
        if not self.can_read(cur, 4):
            return None
        return self.i32(cur)
