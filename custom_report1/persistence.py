# -*- coding: utf-8 -*-
"""报表持久化层 —— MySQL 优先，JSON 配置文件回退"""

import json
import logging
from abc import ABC, abstractmethod
from datetime import datetime

from .models import ReportConfig, ReportPreset

logger = logging.getLogger(__name__)


class ReportStoreError(Exception):
    """报表存储异常"""
    pass


class AbstractReportStore(ABC):
    """报表存储抽象基类"""

    @abstractmethod
    def save_preset(self, name, config):
        """保存报表预设。config 为 ReportConfig 或 dict。"""

    @abstractmethod
    def load_preset(self, name):
        """加载报表预设。返回 ReportConfig 或 None。"""

    @abstractmethod
    def list_presets(self, filter_text=None):
        """列出所有预设。返回 list[ReportPreset]。"""

    @abstractmethod
    def delete_preset(self, name):
        """删除报表预设。"""

    @abstractmethod
    def save_last_state(self, config):
        """保存最近一次编辑状态。"""

    @abstractmethod
    def load_last_state(self):
        """加载最近一次编辑状态。返回 ReportConfig 或 None。"""

    @abstractmethod
    def is_available(self):
        """存储是否可用。"""


class JsonConfigReportStore(AbstractReportStore):
    """JSON 配置文件存储（兼容旧版行为）。

    数据存储在 config['custom_reports']['presets'] 和
    config['custom_reports']['last_state'] 中。
    """

    def __init__(self, get_config_fn, save_config_fn):
        """Args:
            get_config_fn: callable，返回完整配置 dict
            save_config_fn: callable(config_dict)，保存配置
        """
        self._get_config = get_config_fn
        self._save_config = save_config_fn

    def is_available(self):
        return True

    def _get_custom_reports(self):
        config = self._get_config()
        if 'custom_reports' not in config:
            config['custom_reports'] = {}
        return config['custom_reports']

    def save_preset(self, name, config):
        cr = self._get_custom_reports()
        if 'presets' not in cr:
            cr['presets'] = {}

        state_dict = config.to_dict() if isinstance(config, ReportConfig) else config
        cr['presets'][name] = {
            'name': name,
            'type': state_dict.get('report_type', 'report'),
            'main_source': state_dict.get('main_source', ''),
            'state': state_dict,
            'modifier': '',
            'modified': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'status': 'enabled',
        }
        self._save_config(self._get_config())

    def load_preset(self, name):
        cr = self._get_custom_reports()
        presets = cr.get('presets', {})
        entry = presets.get(name)
        if not entry:
            return None
        state = entry.get('state', {})
        return ReportConfig.from_dict(state) if state else None

    def list_presets(self, filter_text=None):
        cr = self._get_custom_reports()
        presets = cr.get('presets', {})
        result = []
        for key, entry in presets.items():
            if not isinstance(entry, dict):
                continue
            name = entry.get('name', key)
            if filter_text and filter_text.lower() not in name.lower():
                continue
            result.append(ReportPreset(
                key=key,
                name=name,
                preset_type=entry.get('type', 'report'),
                main_source=entry.get('main_source', ''),
                modifier=entry.get('modifier', ''),
                modified=entry.get('modified', ''),
                status=entry.get('status', 'enabled'),
            ))
        # 按修改时间倒序
        result.sort(key=lambda p: p.modified, reverse=True)
        return result

    def delete_preset(self, name):
        cr = self._get_custom_reports()
        presets = cr.get('presets', {})
        if name in presets:
            del presets[name]
            self._save_config(self._get_config())

    def save_last_state(self, config):
        cr = self._get_custom_reports()
        state_dict = config.to_dict() if isinstance(config, ReportConfig) else config
        cr['last_state'] = state_dict
        self._save_config(self._get_config())

    def load_last_state(self):
        cr = self._get_custom_reports()
        state = cr.get('last_state')
        return ReportConfig.from_dict(state) if state else None


class MysqlReportStore(AbstractReportStore):
    """MySQL 报表存储"""

    def __init__(self, mysql_config):
        self._cfg = mysql_config
        self._conn = None
        self._available = False

    def is_available(self):
        return self._available

    def ensure_schema(self):
        """创建报表表结构（如果不存在）。"""
        try:
            conn = self._get_connection()
            if not conn:
                return False
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS custom_reports (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        name VARCHAR(255) NOT NULL,
                        type VARCHAR(32) DEFAULT 'report',
                        config_json LONGTEXT,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        modified_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                        status VARCHAR(32) DEFAULT 'enabled',
                        INDEX idx_type (type),
                        INDEX idx_name (name)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """)
            conn.commit()
            self._available = True
            return True
        except Exception as e:
            logger.warning(f"[MysqlReportStore] 建表失败: {e}")
            self._available = False
            return False

    def _get_connection(self):
        if self._conn is not None:
            try:
                self._conn.ping(reconnect=True)
                return self._conn
            except Exception:
                self._conn = None

        try:
            import pymysql
            self._conn = pymysql.connect(
                host=self._cfg.get('host', 'localhost'),
                port=int(self._cfg.get('port', 3306)),
                user=self._cfg.get('user', 'root'),
                password=self._cfg.get('password', ''),
                database=self._cfg.get('database', ''),
                charset='utf8mb4',
                autocommit=False,
            )
            return self._conn
        except ImportError:
            logger.warning("[MysqlReportStore] pymysql 未安装")
            return None
        except Exception as e:
            logger.warning(f"[MysqlReportStore] 连接失败: {e}")
            return None

    def save_preset(self, name, config):
        conn = self._get_connection()
        if not conn:
            raise ReportStoreError("MySQL 不可用")
        state_dict = config.to_dict() if isinstance(config, ReportConfig) else config
        config_json = json.dumps(state_dict, ensure_ascii=False)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO custom_reports (name, type, config_json, modified_at)
                       VALUES (%s, %s, %s, NOW())
                       ON DUPLICATE KEY UPDATE config_json=%s, modified_at=NOW()""",
                    (name, state_dict.get('report_type', 'report'), config_json, config_json)
                )
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise ReportStoreError(f"保存预设失败: {e}")

    def load_preset(self, name):
        conn = self._get_connection()
        if not conn:
            return None
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT config_json FROM custom_reports WHERE name=%s",
                    (name,)
                )
                row = cur.fetchone()
            if row:
                state = json.loads(row[0])
                return ReportConfig.from_dict(state)
            return None
        except Exception as e:
            logger.warning(f"[MysqlReportStore] 加载预设失败: {e}")
            return None

    def list_presets(self, filter_text=None):
        conn = self._get_connection()
        if not conn:
            return []
        try:
            with conn.cursor() as cur:
                if filter_text:
                    cur.execute(
                        """SELECT name, type, config_json, modified_at, status
                           FROM custom_reports WHERE name LIKE %s
                           ORDER BY modified_at DESC""",
                        (f'%{filter_text}%',)
                    )
                else:
                    cur.execute(
                        """SELECT name, type, config_json, modified_at, status
                           FROM custom_reports ORDER BY modified_at DESC"""
                    )
                rows = cur.fetchall()
            result = []
            for row in rows:
                name, rtype, config_json, modified, status = row
                state = json.loads(config_json) if config_json else {}
                result.append(ReportPreset(
                    key=name,
                    name=name,
                    preset_type=rtype or 'report',
                    main_source=state.get('main_source', ''),
                    modifier='',
                    modified=str(modified) if modified else '',
                    status=status or 'enabled',
                ))
            return result
        except Exception as e:
            logger.warning(f"[MysqlReportStore] 列出预设失败: {e}")
            return []

    def delete_preset(self, name):
        conn = self._get_connection()
        if not conn:
            return
        try:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM custom_reports WHERE name=%s", (name,))
            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.warning(f"[MysqlReportStore] 删除预设失败: {e}")

    def save_last_state(self, config):
        try:
            config_dict = config.to_dict() if isinstance(config, ReportConfig) else config
            self.save_preset('__last_state__', config_dict)
        except Exception:
            pass

    def load_last_state(self):
        return self.load_preset('__last_state__')

    def close(self):
        if self._conn:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None


def build_store(mysql_config, get_config_fn=None, save_config_fn=None):
    """构建报表存储实例。

    Args:
        mysql_config: MySQL 配置 dict
        get_config_fn: JSON 模式的配置读取回调
        save_config_fn: JSON 模式的配置保存回调

    Returns:
        AbstractReportStore
    """
    if mysql_config.get('enabled'):
        store = MysqlReportStore(mysql_config)
        if store.ensure_schema():
            logger.info("[ReportStore] 使用 MySQL 存储")
            # 尝试从 JSON 迁移数据
            if get_config_fn:
                try:
                    _migrate_json_to_mysql(store, get_config_fn)
                except Exception:
                    pass
            return store
        logger.info("[ReportStore] MySQL 不可用，回退到 JSON")

    # JSON 回退
    if get_config_fn and save_config_fn:
        logger.info("[ReportStore] 使用 JSON 配置文件存储")
        return JsonConfigReportStore(get_config_fn, save_config_fn)

    raise ReportStoreError("无法初始化任何报表存储")


def _migrate_json_to_mysql(mysql_store, get_config_fn):
    """将 JSON 配置中的预设迁移到 MySQL。"""
    config = get_config_fn()
    presets = config.get('custom_reports', {}).get('presets', {})
    if not presets:
        return
    existing = mysql_store.list_presets()
    existing_names = {p.name for p in existing}
    migrated = 0
    for name, entry in presets.items():
        if not isinstance(entry, dict):
            continue
        if name in existing_names:
            continue
        state = entry.get('state', {})
        if state:
            mysql_store.save_preset(name, ReportConfig.from_dict(state))
            migrated += 1
    if migrated:
        logger.info(f"[ReportStore] 从 JSON 迁移了 {migrated} 个预设到 MySQL")
