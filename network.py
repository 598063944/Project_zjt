# -*- coding: utf-8 -*-
"""
network.py — 数据访问层
─────────────────────────
负责：CRM API 封装（FXiaokeCRM）、MySQL 缓存（MysqlCache）、本地缓存（CRMCache）、后台任务管理（BackgroundTaskManager）
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

def __getattr__(name):
    """延迟从 __main__ 获取任何未导入的变量/函数（解决 from core import * 的时序问题）"""
    import sys as _s
    _m = _s.modules.get('__main__')
    if _m is not None and hasattr(_m, name):
        return getattr(_m, name)
    raise AttributeError(f"module 'network' has no attribute {name!r}")
 
# -- lines 40-989 --
class FXiaokeCRM:    #CRM订单字段
    """纷享销客CRM接口封装。"""

    def __init__(self, app_id, app_secret, permanent_code, admin_mobile):
        """初始化纷享销客CRM客户端。"""
        self.app_id = app_id
        self.app_secret = app_secret
        self.permanent_code = permanent_code
        self.admin_mobile = admin_mobile
        self.base_url = "https://open.fxiaoke.com"
        self.corp_access_token = None
        self.corp_id = None
        self.current_open_user_id = None

    def get_corp_access_token(self):
        """获取纷享销客企业访问令牌。"""
        url = f"{self.base_url}/cgi/corpAccessToken/get/V2"
        headers = {"Content-Type": "application/json"}
        data = {
            "appId": self.app_id,
            "appSecret": self.app_secret,
            "permanentCode": self.permanent_code
        }
        try:
            response = perform_requests_request('post', url, headers=headers, json=data, timeout=60)
            if response.status_code != 200:
                return False, f"HTTP Error: {response.status_code}"
            result = response.json()
            if result.get("errorCode") == 0:
                self.corp_access_token = result.get("corpAccessToken")
                self.corp_id = result.get("corpId")
                return True, "OK"
            else:
                return False, result.get("errorMessage", "Unknown error")
        except Exception as e:
            return False, f"{e} | verify={REQUESTS_VERIFY} ssl_ctx={REQUESTS_SSL_CONTEXT is not None} cert_src={_CERT_SOURCE}"

    def get_open_user_id_by_mobile(self):
        """根据管理员手机号查询对应的 openUserId。"""
        if not self.corp_access_token:
            ok, msg = self.get_corp_access_token()
            if not ok:
                return None, msg
        url = f"{self.base_url}/cgi/user/getByMobile"
        data = {
            "corpAccessToken": self.corp_access_token,
            "corpId": self.corp_id,
            "mobile": self.admin_mobile
        }
        try:
            response = perform_requests_request(
                'post',
                url,
                headers={"Content-Type": "application/json"},
                json=data,
                timeout=60,
            )
            if response.status_code == 200:
                result = response.json()
                if result.get("errorCode") == 0:
                    emp_list = result.get("empList", [])
                    if emp_list:
                        uid = emp_list[0].get("openUserId")
                        self.current_open_user_id = uid
                        return uid, emp_list[0].get("name", "")
            return None, "User not found"
        except Exception as e:
            return None, str(e)

    def query_user_list(self, department_id, fetch_child=True, show_department_detail=False):
        """获取部门下成员信息(详细)。

        Args:
            department_id: 部门ID，为非负整数，999999 代表全公司
            fetch_child: 是否同时获取子部门员工
            show_department_detail: 是否返回部门详情
        """
        if not self.corp_access_token:
            ok, msg = self.get_corp_access_token()
            if not ok:
                return None, msg

        url = f"{self.base_url}/cgi/user/list"
        data = {
            "corpAccessToken": self.corp_access_token,
            "corpId": self.corp_id,
            "departmentId": department_id,
            "fetchChild": fetch_child,
        }
        if show_department_detail:
            data["showDepartmentIdsDetail"] = True
        try:
            response = perform_requests_request(
                'post',
                url,
                headers={"Content-Type": "application/json"},
                json=data,
                timeout=60,
            )
            if response.status_code != 200:
                return None, f"HTTP {response.status_code}"
            result = response.json()
            if result.get("errorCode") == 0:
                return result.get("userList"), None
            return None, result.get("errorMessage", "Query failed")
        except Exception as e:
            return None, str(e)

    def query_department_list(self, department_id=999999, fetch_child=True):
        """获取部门列表。

        Args:
            department_id: 父部门ID，999999 为根部门
            fetch_child: 是否获取子部门
        """
        if not self.corp_access_token:
            ok, msg = self.get_corp_access_token()
            if not ok:
                return None, msg

        url = f"{self.base_url}/cgi/department/list"
        data = {
            "corpAccessToken": self.corp_access_token,
            "corpId": self.corp_id,
            "departmentId": department_id,
            "fetchChild": fetch_child,
        }
        try:
            response = perform_requests_request(
                'post', url,
                headers={"Content-Type": "application/json"},
                json=data, timeout=60,
            )
            if response.status_code != 200:
                return None, f"HTTP {response.status_code}"
            result = response.json()
            if result.get("errorCode") == 0:
                return result.get("departments"), None
            return None, result.get("errorMessage", "Query failed")
        except Exception as e:
            return None, str(e)

    def query_data_object(self, data_object_api_name, offset=0, limit=100, filters=None, field_projection=None, find_explicit_total_num=True, is_custom=False):
        """按对象类型查询 CRM 数据。

        Args:
            is_custom: True 使用自定义对象接口 /cgi/crm/custom/v2/data/query，
                       False 使用预设对象接口 /cgi/crm/v2/data/query
        """
        if not self.corp_access_token:
            ok, msg = self.get_corp_access_token()
            if not ok:
                return None, msg
        if not self.current_open_user_id:
            uid, msg = self.get_open_user_id_by_mobile()
            if not uid:
                return None, msg

        if is_custom:
            url = f"{self.base_url}/cgi/crm/custom/v2/data/query"
        else:
            url = f"{self.base_url}/cgi/crm/v2/data/query"

        search_query_info = {
            "offset": offset,
            "limit": limit,
            "filters": filters or []
        }
        if field_projection:
            search_query_info["fieldProjection"] = field_projection

        data = {
            "corpAccessToken": self.corp_access_token,
            "corpId": self.corp_id,
            "currentOpenUserId": self.current_open_user_id,
            "data": {
                "dataObjectApiName": data_object_api_name,
                "search_query_info": search_query_info
            },
            "find_explicit_total_num": find_explicit_total_num
        }
        try:
            response = perform_requests_request(
                'post',
                url,
                headers={"Content-Type": "application/json"},
                json=data,
                timeout=60,
            )
            if response.status_code != 200:
                return None, f"HTTP {response.status_code}"
            result = response.json()
            if result.get("errorCode") == 0:
                return result.get("data"), None
            return None, result.get("errorMessage", "Query failed")
        except Exception as e:
            return None, str(e)

    def fetch_all_data_object(self, data_object_api_name, max_records=10000, batch_size=100, filters=None, field_projection=None, callback=None, is_custom=False):
        """按对象类型分页拉取数据；field_projection 为空时由接口返回全部默认字段。

        Args:
            is_custom: True 使用自定义对象接口，False 使用预设对象接口
        """
        all_rows = []
        total = 0
        offset = 0
        try:
            target_records = int(max_records)
        except (TypeError, ValueError):
            target_records = 10000
        try:
            batch_size = int(batch_size)
        except (TypeError, ValueError):
            batch_size = 100

        target_records = max(1, min(target_records, 10000))
        batch_size = max(1, batch_size)

        while offset < target_records:
            current_limit = min(batch_size, target_records - offset)
            data, err = self.query_data_object(
                data_object_api_name=data_object_api_name,
                offset=offset,
                limit=current_limit,
                filters=filters,
                field_projection=field_projection,
                find_explicit_total_num=True,
                is_custom=is_custom,
            )
            if err:
                return all_rows, total, err
            if not data:
                break
            if not isinstance(data, dict):
                break
            rows = data.get("dataList", [])
            total = data.get("total", 0)
            if not rows:
                break
            all_rows.extend(rows)
            if len(all_rows) >= target_records:
                all_rows = all_rows[:target_records]
                if callback:
                    callback(len(all_rows), total)
                break
            if callback:
                callback(len(all_rows), total)
            if len(rows) < current_limit:
                break
            offset += current_limit
        return all_rows, total, None

    def fetch_customer_accounts_by_ids(self, account_ids, batch_size=100):
        """按客户 ID 批量补充客户档案信息。"""
        account_map = {}
        unique_ids = [account_id for account_id in dict.fromkeys(account_ids or []) if account_id]
        if not unique_ids:
            return account_map, None

        for start in range(0, len(unique_ids), batch_size):
            batch_ids = unique_ids[start:start + batch_size]
            data, err = self.query_data_object(
                data_object_api_name="AccountObj",
                offset=0,
                limit=max(len(batch_ids), 1),
                filters=[{
                    "field_name": "_id",
                    "operator": "IN",
                    "field_values": batch_ids,
                }],
                field_projection=["_id", "name", "field_UBjkv__c", "field_WEB1y__c", "tel", "field_Qjze2__c", "address", "location"],
                find_explicit_total_num=False,
            )
            if err:
                return account_map, err

            for row in (data or {}).get("dataList", []):
                account_id = str(row.get("_id", "")).strip()
                if account_id:
                    account_map[account_id] = row
        return account_map, None


class BackgroundTaskManager:
    """轻量级后台任务管理器，基于 threading.Thread + pyqtSignal 模式。

    负责追踪活跃任务的生命周期（pending → running → completed/error），
    并通过 pyqtSignal 通知 UI 更新状态栏。
    """

    def __init__(self, status_signal, done_signal, error_signal):
        self._tasks = {}          # task_id -> {'name': str, 'thread': Thread}
        self._lock = threading.Lock()
        self.status_changed = status_signal    # pyqtSignal(str, str, str)
        self.task_done = done_signal           # pyqtSignal(str, bool, str)
        self.task_error = error_signal         # pyqtSignal(str, str)

    def start(self, task_id, name, worker_fn, *args, timeout=None, **kwargs):
        """启动后台任务。worker_fn 在 daemon 线程中运行。

        Args:
            timeout: 超时秒数。超时后自动标记任务失败并通知 UI。
        """
        completed = threading.Event()

        def wrapper():
            try:
                self.status_changed.emit(task_id, name, 'running')
                result = worker_fn(*args, **kwargs)
                if not completed.is_set():
                    completed.set()
                    self.status_changed.emit(task_id, name, 'completed')
                    if isinstance(result, tuple) and len(result) == 2:
                        self.task_done.emit(task_id, result[0], result[1] or '')
                    else:
                        self.task_done.emit(task_id, True, '')
            except Exception as e:
                if not completed.is_set():
                    completed.set()
                    self.status_changed.emit(task_id, name, 'error')
                    self.task_error.emit(task_id, str(e)[:200])
            finally:
                completed.set()
                with self._lock:
                    self._tasks.pop(task_id, None)

        def _on_timeout():
            if completed.is_set():
                return
            completed.set()
            self.status_changed.emit(task_id, name, 'error')
            self.task_done.emit(task_id, False, f'连接测试超时（{timeout}秒未响应），已自动停止')
            with self._lock:
                self._tasks.pop(task_id, None)

        t = threading.Thread(target=wrapper, daemon=True)
        with self._lock:
            self._tasks[task_id] = {'name': name, 'thread': t}
        self.status_changed.emit(task_id, name, 'pending')
        t.start()

        if timeout and timeout > 0:
            timer = threading.Timer(timeout, _on_timeout)
            timer.daemon = True
            timer.start()

    def is_running(self, task_id):
        with self._lock:
            return task_id in self._tasks

    @property
    def active_count(self):
        with self._lock:
            return len(self._tasks)

    def active_task_names(self):
        with self._lock:
            return [v['name'] for v in self._tasks.values()]


class MysqlCache:
    """MySQL 缓存：每个 CRM 对象一张表，_id 为主键，data_json 存行数据"""

    def __init__(self):
        self._conn = None
        self._last_error = None

    @property
    def available(self):
        """MySQL 是否可用（已启用且连接成功）"""
        return self._get_conn() is not None

    @property
    def status_message(self):
        """当前状态描述"""
        if self._conn and self._conn.open:
            return "✅ MySQL 缓存已连接"
        cfg = load_config().get('mysql_config', {})
        if not cfg.get('enabled'):
            return "⚠️ MySQL 缓存未启用（请在 设置→MySQL配置 中启用）"
        if self._last_error:
            return f"❌ MySQL 连接失败: {self._last_error}"
        return "⚠️ MySQL 缓存未连接"

    def _get_conn(self):
        if self._conn and self._conn.open:
            return self._conn
        cfg = load_config().get('mysql_config', {})
        if not cfg.get('enabled'):
            self._last_error = '未启用'
            return None
        import pymysql
        try:
            self._conn = pymysql.connect(
                host=cfg.get('host', '127.0.0.1'),
                port=int(cfg.get('port', 3306)),
                user=cfg.get('user', ''),
                password=cfg.get('password', ''),
                database=cfg.get('database', ''),
                charset='utf8mb4',
                connect_timeout=5,
                cursorclass=pymysql.cursors.DictCursor,
                autocommit=True,
            )
            return self._conn
        except Exception as e:
            self._last_error = str(e)
            logging.error(f"[MysqlCache] 连接失败: {e}")
            return None

    def _table_name(self, api_name):
        return f"crm_cache_{api_name}"

    def _ensure_table(self, api_name):
        conn = self._get_conn()
        if not conn:
            return False
        table = self._table_name(api_name)
        try:
            with conn.cursor() as cur:
                cur.execute(f"""CREATE TABLE IF NOT EXISTS `{table}` (
                    `_id` VARCHAR(128) PRIMARY KEY,
                    `data_json` LONGTEXT,
                    `cached_at` DATETIME DEFAULT CURRENT_TIMESTAMP
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")
            return True
        except Exception as e:
            logging.error(f"[MysqlCache] 建表失败 {table}: {e}")
            return False

    def get_all(self, api_name):
        conn = self._get_conn()
        if not conn or not self._ensure_table(api_name):
            return None
        table = self._table_name(api_name)
        try:
            with conn.cursor() as cur:
                cur.execute(f"SELECT data_json FROM `{table}`")
                rows = cur.fetchall()
            import json
            return [json.loads(r['data_json']) for r in rows]
        except Exception as e:
            logging.error(f"[MysqlCache] 读取失败 {api_name}: {e}")
            return None

    def upsert_all(self, api_name, rows):
        if not rows:
            return
        conn = self._get_conn()
        if not conn or not self._ensure_table(api_name):
            return
        table = self._table_name(api_name)
        import json, hashlib
        skipped = 0
        inserted = 0
        updated = 0
        seen_ids = set()  # 防止同批次 _id 重复导致 1062 主键冲突
        try:
            with conn.cursor() as cur:
                # 确保 _hash 列存在且为 VARCHAR(40)（兼容旧表 VARCHAR(32)）
                cur.execute(f"SHOW COLUMNS FROM `{table}` LIKE '_hash'")
                col_info = cur.fetchone()
                if not col_info:
                    cur.execute(f"ALTER TABLE `{table}` ADD COLUMN `_hash` VARCHAR(40) DEFAULT ''")
                else:
                    col_type = col_info.get('Type', '').lower()
                    import re
                    m = re.search(r'\d+', col_type)
                    cur_len = int(m.group()) if m else 0
                    if cur_len < 40:
                        cur.execute(f"ALTER TABLE `{table}` MODIFY COLUMN `_hash` VARCHAR(40) DEFAULT ''")
                for row in rows:
                    _id = str(row.get('_id', '')).strip()
                    if not _id:
                        skipped += 1
                        continue
                    if _id in seen_ids:
                        skipped += 1
                        continue
                    seen_ids.add(_id)
                    data_json = json.dumps(row, ensure_ascii=False)
                    row_hash = hashlib.sha1(data_json.encode('utf-8')).hexdigest()
                    cur.execute(
                        f"INSERT INTO `{table}` (_id, data_json, _hash, cached_at) "
                        f"VALUES (%s, %s, %s, NOW()) "
                        f"ON DUPLICATE KEY UPDATE "
                        f"data_json = IF(VALUES(`_hash`) != `_hash`, VALUES(data_json), data_json), "
                        f"`_hash` = IF(VALUES(`_hash`) != `_hash`, VALUES(`_hash`), `_hash`), "
                        f"cached_at = IF(VALUES(`_hash`) != `_hash`, NOW(), cached_at)",
                        (_id, data_json, row_hash)
                    )
                    inserted += 1
                if skipped:
                    logging.warning(f"[MysqlCache] JSON缓存表 {api_name}: {skipped} 条记录因 _id 为空被跳过")
            logging.info(f"[MysqlCache] JSON缓存表 {api_name}: 写入 {inserted} 条，跳过 {skipped} 条")
        except Exception as e:
            logging.error(f"[MysqlCache] 写入失败 {api_name}: {e}")

    def replace_cleaned_all(self, table_name, rows, headers, cleanup_old=True, field_type_map=None):
        """增量写入清洗后的数据表（按 _id 比对更新，可选清理不在本次批次中的旧记录）

        Args:
            table_name: 中文表名（如 对象-销售订单）
            rows: [{'字段中文名': 清洗值, ...}, ...]，每行含 _id
            headers: 中文表头列表
            cleanup_old: 是否清理不在本次批次中的旧记录。全量同步用 True，分页/限量查询用 False
            field_type_map: {字段中文名: CRM类型}，数值字段用 DOUBLE 列 + 保留数值
        """
        if not rows:
            return False, "无数据"
        conn = self._get_conn()
        if not conn:
            return False, self.status_message
        import json, hashlib, uuid
        from custom_report import get_mysql_type_for_field, is_numeric_field_type, safe_numeric_value
        batch_id = uuid.uuid4().hex
        type_map = field_type_map or {}
        try:
            safe_cols = []
            for h in headers:
                safe = h.replace('`', '``')
                safe_cols.append(safe)
            with conn.cursor() as cur:
                # 确保表存在（数值字段用 DOUBLE，其余 LONGTEXT）
                col_defs = ['`_id` VARCHAR(128) PRIMARY KEY',
                            '`_hash` VARCHAR(40)',
                            '`_sync_time` DATETIME DEFAULT CURRENT_TIMESTAMP',
                            '`_sync_batch_id` VARCHAR(36) DEFAULT \'\'']
                for h in safe_cols:
                    ftype = type_map.get(h, '')
                    mysql_type = get_mysql_type_for_field(ftype)
                    col_defs.append(f'`{h}` {mysql_type}')
                cols_sql = ', '.join(col_defs)
                cur.execute(f"CREATE TABLE IF NOT EXISTS `{table_name}` ({cols_sql}) "
                            f"ENGINE=InnoDB DEFAULT CHARSET=utf8mb4")

                # 确保所有字段列存在（动态加列，统一用 LONGTEXT 避免类型转换错误）
                existing = {}
                cur.execute(f"SHOW COLUMNS FROM `{table_name}`")
                for r in cur.fetchall():
                    existing[r.get('Field', '')] = r.get('Type', 'LONGTEXT')
                for h in safe_cols + ['_hash', '_sync_time', '_sync_batch_id']:
                    ftype = type_map.get(h, '')
                    expected_type = get_mysql_type_for_field(ftype) if h not in ('_hash', '_sync_time', '_sync_batch_id') else None
                    if h not in existing:
                        col_type = 'VARCHAR(40)' if h == '_hash' else (
                            'VARCHAR(36)' if h == '_sync_batch_id' else (
                            'DATETIME DEFAULT CURRENT_TIMESTAMP' if h == '_sync_time' else 'LONGTEXT'))
                        cur.execute(f"ALTER TABLE `{table_name}` ADD COLUMN `{h}` {col_type}")
                    elif h == '_hash' and existing[h].lower().startswith('varchar'):
                        # 旧表 _hash 可能是 VARCHAR(32)，需扩容为 VARCHAR(40)
                        import re
                        m = re.search(r'\d+', existing[h])
                        cur_len = int(m.group()) if m else 0
                        if cur_len < 40:
                            cur.execute(f"ALTER TABLE `{table_name}` MODIFY COLUMN `_hash` VARCHAR(40) DEFAULT ''")
                    elif h not in ('_hash', '_sync_batch_id', '_sync_time'):
                        existing_type = existing[h].lower()
                        # 非文本类型（DOUBLE/INT等）统一改为 LONGTEXT，避免 "Incorrect DOUBLE value" 错误
                        if 'double' in existing_type or 'int' in existing_type or 'decimal' in existing_type or 'float' in existing_type:
                            try:
                                cur.execute(f"ALTER TABLE `{table_name}` MODIFY COLUMN `{h}` LONGTEXT")
                            except Exception:
                                pass

                # 构建 upsert SQL（含批次标记）
                upsert_cols = ['_id', '_hash', '_sync_time', '_sync_batch_id'] + safe_cols
                placeholders = ', '.join(['%s'] * len(upsert_cols))
                insert_sql = (
                    f"INSERT INTO `{table_name}` "
                    f"(`{'`, `'.join(upsert_cols)}`) VALUES ({placeholders}) "
                    f"ON DUPLICATE KEY UPDATE "
                )
                update_parts = []
                for h in safe_cols:
                    update_parts.append(
                        f"`{h}` = IF(VALUES(`_hash`) != `_hash`, VALUES(`{h}`), `{h}`)")
                update_parts.append(
                    "`_hash` = IF(VALUES(`_hash`) != `_hash`, VALUES(`_hash`), `_hash`)")
                update_parts.append(
                    "`_sync_time` = IF(VALUES(`_hash`) != `_hash`, NOW(), `_sync_time`)")
                # 批次标记始终更新（不受 hash 变更影响）
                update_parts.append(
                    "`_sync_batch_id` = VALUES(`_sync_batch_id`)")
                insert_sql += ', '.join(update_parts)

                # 批量执行（每批 500 行）
                batch = []
                inserted = 0
                skipped = 0
                seen_ids = set()  # 防止同批次 _id 重复导致 1062 主键冲突
                for row in rows:
                    _id = str(row.get('_id', '')).strip()
                    if not _id:
                        skipped += 1
                        continue
                    if _id in seen_ids:
                        skipped += 1
                        continue
                    seen_ids.add(_id)
                    # 计算字段值哈希（数值字段用原值，非数值字段转 str）
                    row_vals = {}
                    for h in headers:
                        ftype = type_map.get(h, '')
                        if is_numeric_field_type(ftype):
                            v = row.get(h)
                            try:
                                row_vals[h] = float(v) if v not in (None, '') else None
                            except (ValueError, TypeError):
                                row_vals[h] = str(v) if v is not None else ''
                        else:
                            row_vals[h] = str(row.get(h, '') or '')
                    row_hash = hashlib.sha1(
                        json.dumps(row_vals, sort_keys=True, ensure_ascii=False, default=str).encode('utf-8')
                    ).hexdigest()
                    vals = [_id, row_hash, None, batch_id]  # _sync_time 用 NOW()
                    for h in headers:
                        ftype = type_map.get(h, '')
                        val = safe_numeric_value(row.get(h, ''), ftype)
                        vals.append(val)
                    batch.append(vals)
                    inserted += 1

                    if len(batch) >= 500:
                        cur.executemany(insert_sql, batch)
                        batch.clear()

                if batch:
                    cur.executemany(insert_sql, batch)

                # 清理不在本次批次中的旧记录（已在 CRM 中删除的）
                deleted = 0
                if cleanup_old:
                    cur.execute(
                        f"DELETE FROM `{table_name}` WHERE `_sync_batch_id` != %s",
                        (batch_id,)
                    )
                    deleted = cur.rowcount

            if skipped:
                logging.warning(f"[MysqlCache] 清洗表 {table_name}: {skipped} 条记录因 _id 为空被跳过")
            if deleted:
                logging.info(f"[MysqlCache] 清洗表 {table_name}: 清理 {deleted} 条过期记录")
            msg = f"已写入 {inserted} 条（增量同步）"
            if deleted:
                msg += f"，清理 {deleted} 条过期记录"
            if skipped:
                msg += f"，跳过 {skipped} 条（_id 为空）"
            return True, msg
        except Exception as e:
            logging.error(f"[MysqlCache] 清洗表写入失败 {table_name}: {e}")
            return False, str(e)[:100]

    def clear(self, api_name):
        conn = self._get_conn()
        if not conn:
            return
        table = self._table_name(api_name)
        try:
            with conn.cursor() as cur:
                cur.execute(f"TRUNCATE TABLE `{table}`")
        except Exception as e:
            logging.error(f"[MysqlCache] 清除失败 {api_name}: {e}")

    def close(self):
        if self._conn and self._conn.open:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None


class CRMCache:
    """SQLite 本地缓存，用于存储从 CRM API 获取的数据对象。

    每个 CRM 对象类型（如 SalesOrderObj、NewOpportunityObj）对应一张表，
    完整记录存为 JSON，常用字段冗余为独立列并建立索引。
    """

    def __init__(self, db_path):
        self._db_path = str(db_path)
        os.makedirs(str(Path(self._db_path).parent), exist_ok=True)
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._ensure_meta_table()

    # ---------- 内部工具 ----------

    @staticmethod
    def _sanitize_name(api_name):
        """将 CRM 对象 API 名称转为安全的表名。"""
        safe = ''.join(c if c.isalnum() else '_' for c in str(api_name))
        return f"crm_{safe}"

    def _ensure_meta_table(self):
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS _cache_meta (
                object_api_name TEXT PRIMARY KEY,
                total_api_count INTEGER DEFAULT 0,
                cached_count    INTEGER DEFAULT 0,
                last_sync_time  TEXT
            )
        """)
        self._conn.commit()

    def _ensure_object_table(self, object_api_name):
        table = self._sanitize_name(object_api_name)
        self._conn.execute(f"""
            CREATE TABLE IF NOT EXISTS {table} (
                _id          TEXT PRIMARY KEY NOT NULL,
                record_data  TEXT NOT NULL,
                create_time  REAL,
                owner_name   TEXT,
                account_name TEXT,
                life_status  TEXT,
                record_type  TEXT,
                name         TEXT,
                cached_at    TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        self._conn.execute(f"""
            CREATE INDEX IF NOT EXISTS idx_{table}_create_time
            ON {table}(create_time)
        """)
        self._conn.execute(f"""
            CREATE INDEX IF NOT EXISTS idx_{table}_life_status
            ON {table}(life_status)
        """)
        self._conn.commit()

    # ---------- 核心 CRUD ----------

    def upsert_records(self, object_api_name, records, total_api_count=None):
        """批量 upsert：按 _id 有则更新，无则插入。返回 (inserted, updated)。"""
        self._ensure_object_table(object_api_name)
        table = self._sanitize_name(object_api_name)
        inserted = 0
        updated = 0

        for record in (records or []):
            if not isinstance(record, dict):
                continue
            rid = str(record.get('_id', '')).strip()
            if not rid:
                continue

            record_json = json.dumps(record, ensure_ascii=False)

            create_time = record.get('create_time')
            if isinstance(create_time, (int, float)):
                create_time = float(create_time)
            else:
                create_time = None

            owner = record.get('owner__r', {})
            owner_name = (owner.get('name', '') if isinstance(owner, dict) else str(owner)) if owner else ''
            account = record.get('account_id__r', {})
            account_name = (account.get('name', '') if isinstance(account, dict) else str(account)) if account else ''
            life_status = str(record.get('life_status', ''))
            record_type = str(record.get('record_type', ''))
            name = str(record.get('name', ''))

            existing = self._conn.execute(
                f"SELECT _id FROM {table} WHERE _id = ?", (rid,)
            ).fetchone()

            if existing:
                self._conn.execute(
                    f"""UPDATE {table} SET record_data=?, create_time=?, owner_name=?,
                        account_name=?, life_status=?, record_type=?, name=?,
                        cached_at=datetime('now') WHERE _id=?""",
                    (record_json, create_time, owner_name, account_name,
                     life_status, record_type, name, rid)
                )
                updated += 1
            else:
                self._conn.execute(
                    f"""INSERT INTO {table} (_id, record_data, create_time, owner_name,
                        account_name, life_status, record_type, name)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (rid, record_json, create_time, owner_name, account_name,
                     life_status, record_type, name)
                )
                inserted += 1

        self._conn.execute(
            "INSERT OR REPLACE INTO _cache_meta (object_api_name, total_api_count, cached_count, last_sync_time) VALUES (?, ?, (SELECT COUNT(*) FROM {0}), datetime('now'))".format(table),
            (object_api_name, total_api_count or 0)
        )
        self._conn.commit()
        return inserted, updated

    def get_all_records(self, object_api_name):
        """返回指定对象类型的所有缓存记录（完整 JSON 解码）。"""
        self._ensure_object_table(object_api_name)
        table = self._sanitize_name(object_api_name)
        rows = self._conn.execute(
            f"SELECT record_data FROM {table} ORDER BY create_time DESC"
        ).fetchall()
        result = []
        for (record_data,) in rows:
            try:
                result.append(json.loads(record_data))
            except json.JSONDecodeError:
                result.append({'_id': '', '_raw': record_data})
        return result

    def get_record_by_id(self, object_api_name, record_id):
        """按 _id 获取单条记录，找不到返回 None。"""
        self._ensure_object_table(object_api_name)
        table = self._sanitize_name(object_api_name)
        row = self._conn.execute(
            f"SELECT record_data FROM {table} WHERE _id = ?", (str(record_id),)
        ).fetchone()
        if row:
            try:
                return json.loads(row[0])
            except json.JSONDecodeError:
                return {'_id': record_id, '_raw': row[0]}
        return None

    def get_record_count(self, object_api_name):
        """返回缓存中的记录数。"""
        self._ensure_object_table(object_api_name)
        table = self._sanitize_name(object_api_name)
        return self._conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]

    def get_meta(self, object_api_name):
        """返回同步元数据字典。"""
        row = self._conn.execute(
            "SELECT total_api_count, cached_count, last_sync_time FROM _cache_meta WHERE object_api_name = ?",
            (object_api_name,)
        ).fetchone()
        if row:
            return {'total_api_count': row[0], 'cached_count': row[1], 'last_sync_time': row[2]}
        return {}

    def delete_record(self, object_api_name, record_id):
        """删除单条记录。"""
        self._ensure_object_table(object_api_name)
        table = self._sanitize_name(object_api_name)
        self._conn.execute(f"DELETE FROM {table} WHERE _id = ?", (str(record_id),))
        self._conn.commit()

    def delete_all_records(self, object_api_name):
        """清空指定对象类型的所有缓存。"""
        self._ensure_object_table(object_api_name)
        table = self._sanitize_name(object_api_name)
        self._conn.execute(f"DELETE FROM {table}")
        self._conn.commit()

    # ---------- 映射数据表（每个字段独立列，存储映射+清洗后的数据） ----------

    def _ensure_mapped_table(self, object_api_name, field_columns):
        """创建映射数据表，每个 CRM 字段 + 用户覆盖字段独立一列"""
        table = self._sanitize_name(object_api_name) + '_mapped'
        col_defs = ['_id TEXT PRIMARY KEY NOT NULL']
        for col in field_columns:
            safe_col = ''.join(c if c.isalnum() else '_' for c in str(col))
            if safe_col and safe_col != '_id':
                col_defs.append(f'"{safe_col}" TEXT')
        col_defs.append('_from_mapped_cache INTEGER DEFAULT 1')
        col_defs.append("mapped_at TEXT NOT NULL DEFAULT (datetime('now'))")
        self._conn.execute(f"""
            CREATE TABLE IF NOT EXISTS {table} (
                {', '.join(col_defs)}
            )
        """)
        self._conn.commit()
        return table

    def _get_mapped_table_columns(self, object_api_name):
        """获取映射表的所有列名"""
        table = self._sanitize_name(object_api_name) + '_mapped'
        rows = self._conn.execute(f"PRAGMA table_info({table})").fetchall()
        return [r[1] for r in rows]

    def upsert_mapped_records(self, object_api_name, field_columns, rows):
        """批量写入映射数据：按 _id 有则更新，无则插入。返回 (inserted, updated)。"""
        table = self._ensure_mapped_table(object_api_name, field_columns)
        existing_cols = set(self._get_mapped_table_columns(object_api_name))
        inserted = 0
        updated = 0

        for row in (rows or []):
            if not isinstance(row, dict):
                continue
            rid = str(row.get('_id', '')).strip()
            if not rid:
                continue

            # 只写入表中已存在的列
            valid_cols = [c for c in row if c in existing_cols and c != '_from_mapped_cache' and c != 'mapped_at']
            if not valid_cols:
                continue

            placeholders = ', '.join(['?'] * len(valid_cols))
            col_names = ', '.join(f'"{c}"' for c in valid_cols)
            values = [str(row.get(c, '') or '') for c in valid_cols]

            existing = self._conn.execute(
                f"SELECT _id FROM {table} WHERE _id = ?", (rid,)
            ).fetchone()

            if existing:
                set_clause = ', '.join(f'"{c}"=?' for c in valid_cols)
                self._conn.execute(
                    f"UPDATE {table} SET {set_clause}, mapped_at=datetime('now') WHERE _id=?",
                    values + [rid]
                )
                updated += 1
            else:
                self._conn.execute(
                    f"INSERT INTO {table} (_id, {col_names}) VALUES (?, {placeholders})",
                    [rid] + values
                )
                inserted += 1

        self._conn.commit()
        return inserted, updated

    def get_all_mapped_records(self, object_api_name):
        """返回映射表中所有记录（每个字段已是映射+清洗后的值）"""
        table = self._sanitize_name(object_api_name) + '_mapped'
        rows = self._conn.execute(
            f"SELECT * FROM {table} ORDER BY create_time DESC"
        ).fetchall()
        if not rows:
            return []
        col_names = [desc[0] for desc in self._conn.execute(
            f"SELECT * FROM {table} LIMIT 0"
        ).description]
        result = []
        for row in rows:
            record = dict(zip(col_names, row))
            record['_from_mapped_cache'] = True
            result.append(record)
        return result

    def update_mapped_field(self, object_api_name, record_id, field_name, value):
        """更新映射表中单条记录的单个字段"""
        table = self._sanitize_name(object_api_name) + '_mapped'
        safe_col = ''.join(c if c.isalnum() else '_' for c in str(field_name))
        rows = self._conn.execute(f"PRAGMA table_info({table})").fetchall()
        existing_cols = {r[1] for r in rows}
        if safe_col not in existing_cols:
            self._conn.execute(f'ALTER TABLE {table} ADD COLUMN "{safe_col}" TEXT')
            self._conn.commit()
        self._conn.execute(
            f'UPDATE {table} SET "{safe_col}"=?, mapped_at=datetime(\'now\') WHERE _id=?',
            (str(value or ''), str(record_id))
        )
        self._conn.commit()

    def get_mapped_record_count(self, object_api_name):
        """返回映射表中的记录数"""
        table = self._sanitize_name(object_api_name) + '_mapped'
        row = self._conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
        return row[0] if row else 0

    def close(self):
        try:
            self._conn.close()
        except Exception:
            pass



user_type = None
