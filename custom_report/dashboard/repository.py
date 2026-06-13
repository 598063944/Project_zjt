"""
仪表盘 + Excel 数据集持久化层

存储后端: JSON 文件
- dashboards.json: 仪表盘定义
- excel_datasets.json: Excel/CSV 导入数据集
"""

import json
import os
import logging
from datetime import datetime
from typing import Optional
from copy import deepcopy

from .models import DashboardDefinition, ChartWidget, ExcelDataset

logger = logging.getLogger(__name__)


def _get_config_dir() -> str:
    """获取 .config 目录路径"""
    config_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        '.config'
    )
    os.makedirs(config_dir, exist_ok=True)
    return config_dir


# ==================== DashboardRepository ====================

class DashboardRepository:
    """仪表盘配置 CRUD"""

    def __init__(self, storage_path: str = None):
        self._path = storage_path or os.path.join(_get_config_dir(), 'dashboards.json')
        self._cache: dict[str, DashboardDefinition] = {}
        self._load()

    def _load(self):
        if not os.path.exists(self._path):
            self._cache = {}
            return
        try:
            with open(self._path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            dashboards_data = data.get('dashboards', {}) if isinstance(data, dict) else {}
            for did, ddata in dashboards_data.items():
                try:
                    self._cache[did] = DashboardDefinition.from_dict(ddata)
                except Exception as e:
                    logger.warning(f"加载仪表盘 {did} 失败: {e}")
        except Exception as e:
            logger.error(f"加载仪表盘配置失败: {e}")
            self._cache = {}

    def _save(self):
        data = {
            'version': 1,
            'dashboards': {did: db.to_dict() for did, db in self._cache.items()},
        }
        tmp_path = self._path + '.tmp'
        try:
            with open(tmp_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, self._path)
        except Exception:
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass
            raise

    # ---------- CRUD ----------

    def list_all(self, search: str = None) -> list[DashboardDefinition]:
        result = list(self._cache.values())
        result.sort(key=lambda d: d.modified_at or '', reverse=True)
        if search:
            s = search.lower()
            result = [d for d in result if s in d.name.lower() or s in (d.description or '').lower()]
        return result

    def get(self, dashboard_id: str) -> Optional[DashboardDefinition]:
        return self._cache.get(dashboard_id)

    def save(self, dashboard: DashboardDefinition):
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        if not dashboard.created_at:
            dashboard.created_at = now
        dashboard.modified_at = now
        dashboard.version = (dashboard.version or 0) + 1
        self._cache[dashboard.id] = dashboard
        self._save()

    def delete(self, dashboard_id: str) -> bool:
        if dashboard_id in self._cache:
            del self._cache[dashboard_id]
            self._save()
            return True
        return False

    def duplicate(self, dashboard_id: str, new_name: str) -> Optional[DashboardDefinition]:
        original = self._cache.get(dashboard_id)
        if not original:
            return None
        new_db = deepcopy(original)
        from .models import _new_id
        new_db.id = _new_id(12)
        new_db.name = new_name
        new_db.created_at = ''
        new_db.modified_at = ''
        new_db.version = 0
        self.save(new_db)
        return new_db

    def count(self) -> int:
        return len(self._cache)


# ==================== ExcelDatasetRepository ====================

class ExcelDatasetRepository:
    """Excel 数据集 CRUD"""

    def __init__(self, storage_path: str = None):
        self._path = storage_path or os.path.join(_get_config_dir(), 'excel_datasets.json')
        self._cache: dict[str, ExcelDataset] = {}
        self._load()

    def _load(self):
        if not os.path.exists(self._path):
            self._cache = {}
            return
        try:
            with open(self._path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            datasets_data = data.get('datasets', {}) if isinstance(data, dict) else {}
            for did, ddata in datasets_data.items():
                try:
                    self._cache[did] = ExcelDataset.from_dict(ddata)
                except Exception as e:
                    logger.warning(f"加载数据集 {did} 失败: {e}")
        except Exception as e:
            logger.error(f"加载数据集配置失败: {e}")
            self._cache = {}

    def _save(self):
        data = {
            'version': 1,
            'datasets': {did: ds.to_dict() for did, ds in self._cache.items()},
        }
        tmp_path = self._path + '.tmp'
        try:
            with open(tmp_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, self._path)
        except Exception:
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass
            raise

    def list_all(self) -> list[ExcelDataset]:
        result = list(self._cache.values())
        result.sort(key=lambda d: d.created_at or '', reverse=True)
        return result

    def get(self, dataset_id: str) -> Optional[ExcelDataset]:
        return self._cache.get(dataset_id)

    def save(self, dataset: ExcelDataset):
        if not dataset.created_at:
            dataset.created_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        self._cache[dataset.id] = dataset
        self._save()

    def delete(self, dataset_id: str) -> bool:
        if dataset_id in self._cache:
            del self._cache[dataset_id]
            self._save()
            return True
        return False

    def count(self) -> int:
        return len(self._cache)
