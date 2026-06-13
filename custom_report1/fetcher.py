"""
CRM 数据获取层

从纷享销客 CRM API 拉取对象数据，供 syncer 写入 MySQL source 表。
复用已有的 FXiaokeCRM 类。
"""

import logging
import sys
from typing import Optional, Callable

logger = logging.getLogger(__name__)


def _import_fxiaoke_crm():
    """从主模块导入 FXiaokeCRM（主脚本文件名含点号，无法直接 import）。"""
    main_mod = sys.modules.get('__main__')
    if main_mod and hasattr(main_mod, 'FXiaokeCRM'):
        return main_mod.FXiaokeCRM
    raise ImportError(
        "无法导入 FXiaokeCRM：主模块未加载或未定义 FXiaokeCRM。"
        "请确保通过 DataFetcher(crm_client=...) 传入已有的 CRM 实例。"
    )


class DataFetcher:
    """CRM 数据获取器"""

    def __init__(self, crm_client=None, config: dict = None):
        """
        Args:
            crm_client: FXiaokeCRM 实例（复用已有的连接）
            config: 应用配置 dict（用于获取 CRM 凭证）
        """
        self._crm = crm_client
        self._config = config or {}

    def _get_crm(self):
        """懒加载 CRM 客户端（优先复用已有实例，避免重复创建）。"""
        if self._crm:
            return self._crm
        # 尝试从主模块获取已登录的 CRM 实例
        main_mod = sys.modules.get('__main__')
        if main_mod is not None:
            cached = getattr(main_mod, '_crm_client_instance', None)
            if cached:
                self._crm = cached
                return self._crm
        # 回退：从配置重新加载凭证创建新实例
        FXiaokeCRM = _import_fxiaoke_crm()
        try:
            if main_mod and hasattr(main_mod, 'load_config'):
                cfg = main_mod.load_config()
            else:
                cfg = self._config or {}
        except Exception:
            cfg = self._config or {}
        fx_cfg = cfg.get('fxiaoke', {})
        self._crm = FXiaokeCRM(
            app_id=fx_cfg.get('app_id', 'FSAID_1323c1a'),
            app_secret=fx_cfg.get('app_secret', 'e7f4188d14704299b375c91ddda92cb0'),
            permanent_code=fx_cfg.get('permanent_code', 'E8B8D8536B0385D035657AC2528928F0'),
            admin_mobile=fx_cfg.get('admin_mobile', '15889740213')
        )
        # 缓存到主模块，供后续复用
        if main_mod is not None:
            main_mod._crm_client_instance = self._crm
        return self._crm

    def fetch_object(self,
                     object_api_name: str,
                     max_records: int = None,
                     batch_size: int = 100,
                     filters: list = None,
                     field_projection: list[str] = None,
                     is_custom: bool = False,
                     progress_callback: Callable = None) -> tuple[list[dict], int, Optional[str]]:
        """
        拉取 CRM 对象数据

        Args:
            object_api_name: CRM 对象 API 名（如 NewOpportunityObj）
            max_records: 最大拉取记录数
            batch_size: 每批记录数
            filters: 筛选条件列表
            field_projection: 需要的字段列表（None = 全部）
            progress_callback: 进度回调 (fetched, total)

        Returns:
            (rows, total, error)
        """

        crm = self._get_crm()
        try:
            if max_records is None:
                raw_load = self._config.get('fxiaoke', {}).get('load_count', 10000)
            else:
                raw_load = max_records
            try:
                max_records = int(raw_load)
            except (TypeError, ValueError):
                max_records = 10000
            max_records = max(1, min(max_records, 10000))

            return crm.fetch_all_data_object(
                data_object_api_name=object_api_name,
                max_records=max_records,
                batch_size=batch_size,
                filters=filters,
                field_projection=field_projection,
                callback=progress_callback,
                is_custom=is_custom,
            )
        except Exception as e:
            logger.error(f"[DataFetcher] 获取 {object_api_name} 失败: {e}")
            return [], 0, str(e)

    def fetch_multiple(self,
                       object_apis: list[str],
                       max_records: int = 10000,
                       filters_map: dict = None,
                       field_projections: dict = None,
                       progress_callback: Callable = None) -> dict[str, tuple[list[dict], int, Optional[str]]]:
        """
        批量拉取多个对象的数据

        Args:
            object_apis: 对象 API 名列表
            max_records: 每个对象最大记录数
            filters_map: {api_name: [filters]} 筛选条件
            field_projections: {api_name: [fields]} 字段投影
            progress_callback: 进度回调 (api_name, fetched, total)

        Returns:
            {api_name: (rows, total, error)}
        """
        results = {}
        filters_map = filters_map or {}
        field_projections = field_projections or {}

        for api in object_apis:
            obj_filters = filters_map.get(api)
            obj_projection = field_projections.get(api)

            def _progress(fetched, total, api_name=api):
                if progress_callback:
                    progress_callback(api_name, fetched, total)

            rows, total, err = self.fetch_object(
                api, max_records=max_records,
                filters=obj_filters,
                field_projection=obj_projection,
                progress_callback=_progress,
            )
            results[api] = (rows, total, err)

            if err:
                logger.warning(f"[DataFetcher] 批量获取中 {api} 出错: {err}")

        return results
