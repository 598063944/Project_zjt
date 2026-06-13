# -*- coding: utf-8 -*-
"""
core.py - 核心工具模块（从主文件重新导出）
注意：此文件由恢复脚本自动生成，所有函数从 __main__ 重新导出。
原始 core.py 因 PowerShell GBK 编码损坏被替换。
"""

from __main__ import *

def load_config():
    """加载配置（延迟从 __main__ 获取，避免 from __main__ import * 的时序问题）"""
    import sys as _sys
    _m = _sys.modules.get('__main__')
    if _m is not None and hasattr(_m, 'load_config'):
        return _m.load_config()
    return {}

def load_user_runtime_state():
    import sys as _sys
    _m = _sys.modules.get('__main__')
    if _m is not None and hasattr(_m, 'load_user_runtime_state'):
        return _m.load_user_runtime_state()
    return {}

def deep_merge_dict(a, b):
    import sys as _sys
    _m = _sys.modules.get('__main__')
    if _m is not None and hasattr(_m, 'deep_merge_dict'):
        return _m.deep_merge_dict(a, b)
    return b
 
def append_user_operation_record(text):
    import sys as _sys
    _m = _sys.modules.get('__main__')
    if _m is not None and hasattr(_m, 'append_user_operation_record'):
        return _m.append_user_operation_record(text)

def save_user_runtime_state(state, immediate=False, merge=True):
    import sys as _sys
    _m = _sys.modules.get('__main__')
    if _m is not None and hasattr(_m, 'save_user_runtime_state'):
        return _m.save_user_runtime_state(state, immediate=immediate, merge=merge)

def save_config(config, immediate=False):
    import sys as _sys
    _m = _sys.modules.get('__main__')
    if _m is not None and hasattr(_m, 'save_config'):
        return _m.save_config(config, immediate=immediate)

class _LazyOperationLog:
    def __getattr__(self, name):
        import sys as _s
        _m = _s.modules.get('__main__')
        if _m is not None and hasattr(_m, 'operation_log'):
            return getattr(_m.operation_log, name)
        raise AttributeError(name)
operation_log = _LazyOperationLog()

def perform_requests_request(method, url, **kwargs):
    import sys as _sys
    _m = _sys.modules.get('__main__')
    if _m is not None and hasattr(_m, 'perform_requests_request'):
        return _m.perform_requests_request(method, url, **kwargs)
 
def flush_pending_config():
    import sys as _sys
    _m = _sys.modules.get('__main__')
    if _m is not None and hasattr(_m, 'flush_pending_config'):
        return _m.flush_pending_config()
 
class _LazyAppConfig:
    def __getattr__(self, name):
        import sys as _s
        _m = _s.modules.get('__main__')
        if _m is not None and hasattr(_m, 'AppConfig'):
            return getattr(_m.AppConfig, name)
        raise AttributeError(name)
    def __call__(self, *args, **kwargs):
        import sys as _s
        _m = _s.modules.get('__main__')
        if _m is not None and hasattr(_m, 'AppConfig'):
            return _m.AppConfig(*args, **kwargs)
AppConfig = _LazyAppConfig()

# 显式重新导出（确保名称可用）
__all__ = [name for name in dir() if not name.startswith("_")]
