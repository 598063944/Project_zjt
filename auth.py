# -*- coding: utf-8 -*-
"""
auth.py — 用户认证模块
───────────────────────
负责：密码验证、用户缓存读写、登录缓存、用户 CRUD、权限判断
依赖：core.py
被导入：common.py → 所有 Mixin / 主程序
"""

# 导入所需模块
import os

# QtWebEngine 必须在 QApplication 创建前导入

from pathlib import Path  # 路径处理
import copy
import builtins
from functools import lru_cache
from io import BytesIO
import logging  # 日志记录
import platform  # 操作系统平台信息
import shutil  # 文件操作
import json  # JSON处理
import subprocess  # 子进程管理
from contextlib import contextmanager
from datetime import datetime, timedelta  # 日期时间处理
from decimal import Decimal, ROUND_HALF_UP

import sys  # 系统相关
import sqlite3  # SQLite 本地缓存
import os  # 操作系统接口
import ssl
import time  # 时间
import threading  # 线程管理
import urllib.request
import email.utils
import pkgutil
import tempfile
import psutil  # 进程管理
import re  # 正则表达式
import uuid  # UUID 生成（API 配置等）
import hashlib  # 哈希算法
import certifi
import requests  # HTTP请求
from requests.adapters import HTTPAdapter
from urllib3.poolmanager import PoolManager


from core import *

class _LazyConfigDir:
    """延迟解析的 CONFIG_DIR 代理，避免 from __main__ import * 的时序问题"""
    _path = None
    def _get_path(self):
        import sys as _s
        _m = _s.modules.get('__main__')
        if _m is not None and hasattr(_m, 'CONFIG_DIR'):
            self._path = _m.CONFIG_DIR
        elif self._path is None:
            from pathlib import Path
            self._path = Path('.')
        return self._path
    def __truediv__(self, other):
        return self._get_path() / other
    def __str__(self):
        return str(self._get_path())
CONFIG_DIR = _LazyConfigDir()

def __getattr__(name):
    """延迟从 __main__ 获取任何未导入的变量/函数（解决 from core import * 的时序问题）"""
    import sys as _s
    _m = _s.modules.get('__main__')
    if _m is not None and hasattr(_m, name):
        return getattr(_m, name)
    raise AttributeError(f"module 'auth' has no attribute {name!r}")
 
_users_cache = None
_users_last_modified = 0

# -- lines 4728-5038 --
def password_verification():
    """
    ✅【2026-05-11 修改】密码验证功能已禁用

    原功能：首次登录时验证用户密码
    现在直接返回 True，不再进行任何验证
    """
    return True

# 用户管理相关功能
def load_user_cache():
    """加载用户缓存信息"""
    from __main__ import CACHE_SALT, get_current_time, load_config
    cache_path = CONFIG_DIR / 'user_cache.json'
    try:
        if cache_path.exists():
            with open(cache_path, 'r', encoding='utf-8') as f:
                cache = json.load(f)
                # 获取用户类型
                user_type = cache.get('user_type', 'member')
                username = cache.get('username')
                cache_date = cache.get('date')
                signature = cache.get('signature')

                # 如果是普通用户，直接返回，不需要校验过期时间和签名
                if user_type != "admin":
                    return username, user_type

                # 检查管理员缓存签名是否有效
                if username and cache_date and signature:
                    raw_str = f"{username}{user_type}{cache_date}{CACHE_SALT}"
                    expected_signature = hashlib.sha256(raw_str.encode('utf-8')).hexdigest()
                    if signature != expected_signature:
                        logging.warning("管理员缓存文件签名校验失败，可能已被篡改")
                        return None, None
                else:
                    # 管理员必须有签名
                    logging.warning("管理员缓存文件缺少签名或关键信息")
                    return None, None

                # 检查管理员缓存是否过期（要求每日重新登录）
                if cache_date:
                    # 从配置文件中读取日期格式
                    config = load_config()
                    date_formats = config.get('business_rules', {}).get('date_formats', {
                        'default': '%Y年%m月%d日',
                        'short': '%Y-%m-%d',
                        'datetime': '%Y-%m-%d %H:%M:%S'
                    })
                    today = get_current_time().strftime(date_formats.get('short', '%Y-%m-%d'))
                    if cache_date == today:
                        return cache.get('username'), user_type

        return None, None
    except Exception as e:
        logging.error(f"加载用户缓存失败: {str(e)}")
        return None, None


def save_user_cache(username, user_type="admin"):
    """保存用户缓存信息"""
    from __main__ import CACHE_SALT, get_current_time, load_config
    cache_path = CONFIG_DIR / 'user_cache.json'
    try:
        # 确保.config目录存在
        cache_path.parent.mkdir(exist_ok=True)
        # 从配置文件中读取日期格式
        config = load_config()
        date_formats = config.get('business_rules', {}).get('date_formats', {
            'default': '%Y年%m月%d日',
            'short': '%Y-%m-%d',
            'datetime': '%Y-%m-%d %H:%M:%S'
        })

        # 创建缓存内容
        current_date = get_current_time().strftime(date_formats.get('short', '%Y-%m-%d'))

        # 计算签名，防止缓存文件被篡改
        raw_str = f"{username}{user_type}{current_date}{CACHE_SALT}"
        signature = hashlib.sha256(raw_str.encode('utf-8')).hexdigest()

        cache_content = {
            "username": username,
            "user_type": user_type,
            "date": current_date,
            "signature": signature
        }
        # 写入缓存文件
        with open(cache_path, 'w', encoding='utf-8') as f:
            json.dump(cache_content, f, ensure_ascii=False, indent=2)

    except Exception as e:
        logging.error(f"保存用户缓存失败: {str(e)}")


def clear_user_cache():
    """清除用户缓存信息"""
    cache_path = CONFIG_DIR / 'user_cache.json'
    try:
        if cache_path.exists():
            cache_path.unlink()

    except Exception as e:
        logging.error(f"清除用户缓存失败: {str(e)}")


def load_login_cache():
    """加载登录输入缓存"""
    cache_path = CONFIG_DIR / 'login_cache.json'
    try:
        if cache_path.exists():
            with open(cache_path, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception as e:
        logging.error(f"加载登录缓存失败: {str(e)}")
    return {"account": "", "password": ""}


def save_login_cache(account, password):
    """保存登录输入缓存"""
    cache_path = CONFIG_DIR / 'login_cache.json'
    try:
        # 确保.config目录存在
        cache_path.parent.mkdir(exist_ok=True)
        # 创建缓存内容
        cache_content = {
            "account": account,
            "password": password
        }
        # 写入缓存文件
        with open(cache_path, 'w', encoding='utf-8') as f:
            json.dump(cache_content, f, ensure_ascii=False, indent=2)

    except Exception as e:
        logging.error(f"保存登录缓存失败: {str(e)}")


def clear_login_cache():
    """清除登录输入缓存"""
    cache_path = CONFIG_DIR / 'login_cache.json'
    try:
        if cache_path.exists():
            cache_path.unlink()

    except Exception as e:
        logging.error(f"清除登录缓存失败: {str(e)}")


def load_deleted_user_ids():
    """加载已删除的用户ID"""
    deleted_ids_path = CONFIG_DIR / 'deleted_user_ids.json'
    try:
        if deleted_ids_path.exists():
            with open(deleted_ids_path, 'r', encoding='utf-8') as f:
                content = f.read().strip()
                if content:
                    return json.loads(content)
                else:
                    return []
    except Exception as e:
        logging.error(f"加载已删除用户ID失败: {str(e)}")
    return []


def save_deleted_user_ids(deleted_ids):
    """保存已删除的用户ID"""
    deleted_ids_path = CONFIG_DIR / 'deleted_user_ids.json'
    try:
        # 确保.config目录存在
        deleted_ids_path.parent.mkdir(exist_ok=True)
        # 写入已删除的用户ID
        with open(deleted_ids_path, 'w', encoding='utf-8') as f:
            json.dump(deleted_ids, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logging.error(f"保存已删除用户ID失败: {str(e)}")





def init_user_database():
    """初始化用户数据库"""
    # 确保.config目录存在
    users_path = CONFIG_DIR / 'users.json'
    try:
        # 确保.config目录存在
        users_path.parent.mkdir(exist_ok=True)
        # 检查users.json文件是否存在
        if not users_path.exists():
            # 创建默认的用户数据
            default_users = {
                "users": [
                    {
                        "username": "Zengjiataoadmin",
                        "password": "Zeng0213@",
                        "user_id": "001",
                        "created_at": get_current_time().strftime('%Y-%m-%d %H:%M:%S'),
                        "role": "admin",
                        "permissions": {
                            "field_format": True,
                            "field_mapping": True,
                            "template": True,
                            "feature_selection": True
                        }
                    }
                ]
            }
            # 写入默认用户数据
            with open(users_path, 'w', encoding='utf-8') as f:
                json.dump(default_users, f, ensure_ascii=False, indent=2)

        return True
    except Exception as e:
        logging.error(f"初始化用户数据失败: {str(e)}")
        return False


def normalize_user_permissions(user):
    """统一修正用户权限，确保历史用户数据兼容最新权限策略"""
    if not isinstance(user, dict):
        return user

    role = user.get('role', 'member')
    permissions = user.get('permissions') or {}
    if not isinstance(permissions, dict):
        permissions = {}

    default_permissions = {
        "path": True,
        "field_format": True,
        "field_mapping": True,
        "template": True,
        "product_list": True,
        "feature_selection": True,
        "database_config": False
    }

    for key, value in default_permissions.items():
        permissions.setdefault(key, value)

    if role != "admin":
        # 普通用户至少允许修改路径和功能配置（包含Excel文件路径）
        permissions["path"] = True
        permissions["feature_selection"] = True
        permissions["database_config"] = False

    user['permissions'] = permissions
    return user


def load_users():
    """加载用户信息"""
    global _users_cache, _users_last_modified

    # 从配置文件加载
    users_path = CONFIG_DIR / 'users.json'
    try:
        if users_path.exists():
            # 检查文件的最后修改时间
            current_modified = users_path.stat().st_mtime
            # 如果缓存存在且文件未修改，直接返回缓存
            if _users_cache and current_modified == _users_last_modified:
                for user in _users_cache.get('users', []):
                    normalize_user_permissions(user)
                return _users_cache
            # 否则重新加载文件
            with open(users_path, 'r', encoding='utf-8') as f:
                users_data = json.load(f)
                for user in users_data.get('users', []):
                    normalize_user_permissions(user)
                # 更新缓存和最后修改时间
                _users_cache = users_data
                _users_last_modified = current_modified
                return users_data

        return {"users": []}
    except Exception as e:
        logging.error(f"加载用户信息失败: {str(e)}")
        return {"users": []}


def save_users(users_data):
    """保存用户信息"""
    global _users_cache, _users_last_modified
    users = users_data.get('users', [])

    for user in users:
        normalize_user_permissions(user)


    # 保存到users.json文件，不使用users.db
    users_path = CONFIG_DIR / 'users.json'
    try:
        # 确保.config目录存在
        users_path.parent.mkdir(exist_ok=True)

        # 写入用户信息文件
        with open(users_path, 'w', encoding='utf-8') as f:
            json.dump(users_data, f, ensure_ascii=False, indent=2)

        # 清除缓存，确保下次加载时重新读取文件
        _users_cache = None
        _users_last_modified = 0
    except Exception as e:
        logging.error(f"保存用户信息到users.json文件失败: {str(e)}")


def is_admin(username, password):
    """检查是否为管理员"""
    # 管理员信息硬编码在代码中，不写入配置文件
    return (username == "Zengjiataoadmin" or username == "001") and password == "Zeng0213@"



user_type = None
