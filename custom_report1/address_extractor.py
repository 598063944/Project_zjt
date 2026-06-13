"""
地址提取器

职责:
- 加载 ChinaCitys.json 构建省/市/区名称匹配集合
- 对文本进行地址信息提取（省全称/省简称/市/区）

用法:
    extractor = AddressExtractor("ChinaCitys.json")
    result = extractor.extract("广东省广州市天河区某路123号", level="city")
    # → "广州市"
"""

import json
import os
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# 省份后缀（用于生成简称）
_PROVINCE_SUFFIXES = [
    "壮族自治区", "维吾尔自治区", "回族自治区",
    "特别行政区",
    "省", "市", "自治区",
]


class AddressExtractor:
    """地址提取引擎"""

    def __init__(self, json_path: str = None):
        """
        Args:
            json_path: ChinaCitys.json 的路径，默认自动查找
        """
        self._json_path = json_path  # None 表示自动查找
        self._province_names: list[str] = []        # 按长度降序
        self._province_short_names: list[str] = []   # 按长度降序
        self._city_names: list[str] = []
        self._area_names: list[str] = []
        self._short_to_full: dict[str, str] = {}     # 简称 → 全称
        self._city_to_province: dict[str, str] = {}  # 市 → 省全称
        self._city_to_province_short: dict[str, str] = {}  # 市 → 省简称
        self._area_to_city: dict[str, str] = {}      # 区 → 市
        self._area_to_province: dict[str, str] = {}  # 区 → 省全称
        self._area_to_province_short: dict[str, str] = {}  # 区 → 省简称
        self._city_short_names: list[str] = []       # 市去掉后缀（如"南通"），按长度降序
        self._city_short_to_full: dict[str, str] = {}  # "南通" → "南通市"
        self._loaded = False

    def _resolve_json_path(self) -> str:
        """解析 ChinaCitys.json 的路径（多级回退）。"""
        candidates = []

        # 1. 相对于 address_extractor.py 的项目根目录
        try:
            base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            candidates.append(os.path.join(base, "ChinaCitys.json"))
        except Exception:
            pass

        # 2. 当前工作目录
        candidates.append(os.path.join(os.getcwd(), "ChinaCitys.json"))

        # 3. 可执行文件所在目录（PyInstaller 兼容）
        try:
            import sys
            exe_dir = os.path.dirname(sys.executable)
            candidates.append(os.path.join(exe_dir, "ChinaCitys.json"))
            # 也尝试 _MEIPASS (PyInstaller 临时目录)
            meipass = getattr(sys, '_MEIPASS', None)
            if meipass:
                candidates.append(os.path.join(meipass, "ChinaCitys.json"))
        except Exception:
            pass

        for p in candidates:
            if os.path.isfile(p):
                return p

        # 全部失败，返回第一个候选作为诊断用
        return candidates[0] if candidates else "ChinaCitys.json"

    def _ensure_loaded(self):
        """延迟加载 JSON（首次调用时加载）。"""
        if self._loaded:
            return
        # 注意：_loaded 只在加载成功后才置 True，失败后下次调用会重试
        path = self._json_path or self._resolve_json_path()
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            logger.warning(f"[AddressExtractor] 加载失败 ({path}): {e}")
            return
        except Exception as e:
            logger.warning(f"[AddressExtractor] 加载异常 ({path}): {e}")
            return

        provinces = []
        province_shorts = []
        cities = []
        areas = []
        short_to_full = {}
        city_to_province = {}
        city_to_province_short = {}
        area_to_city = {}
        area_to_province = {}
        area_to_province_short = {}
        city_short_to_full = {}

        for p in data:
            province = p.get("province", "")
            if not province:
                continue
            provinces.append(province)

            # 简称
            short = self._to_short_name(province)
            if short:
                province_shorts.append(short)
                short_to_full[short] = province

            for c in p.get("citys", []):
                city = c.get("city", "")
                if city:
                    cities.append(city)
                    city_to_province[city] = province
                    if short:
                        city_to_province_short[city] = short
                    # 去掉后缀 "市" → 简称（如 "南通市" → "南通"）
                    if city.endswith('市') and len(city) > 1:
                        city_short = city[:-1]
                        if city_short not in city_short_to_full:
                            city_short_to_full[city_short] = city
                for a in c.get("areas", []):
                    area = a.get("area", "")
                    if area:
                        areas.append(area)
                        area_to_city[area] = city
                        area_to_province[area] = province
                        if short:
                            area_to_province_short[area] = short

        # 按长度降序排列（避免短名称抢先匹配长名称）
        provinces.sort(key=len, reverse=True)
        province_shorts.sort(key=len, reverse=True)
        cities.sort(key=len, reverse=True)
        areas.sort(key=len, reverse=True)

        self._province_names = provinces
        self._province_short_names = province_shorts
        self._city_names = cities
        self._area_names = areas
        self._short_to_full = short_to_full
        self._city_to_province = city_to_province
        self._city_to_province_short = city_to_province_short
        self._area_to_city = area_to_city
        self._area_to_province = area_to_province
        self._area_to_province_short = area_to_province_short
        city_short_names = sorted(city_short_to_full.keys(), key=len, reverse=True)
        self._city_short_names = city_short_names
        self._city_short_to_full = city_short_to_full
        self._loaded = True
        logger.info(
            f"[AddressExtractor] 已加载 {path}: "
            f"省={len(provinces)}, 市={len(cities)}, 区={len(areas)}"
        )

    @staticmethod
    def _to_short_name(province: str) -> str:
        """省份全称 → 简称。

        例: '广东省' → '广东', '北京市' → '北京',
            '内蒙古自治区' → '内蒙古', '广西壮族自治区' → '广西'
        """
        for suffix in _PROVINCE_SUFFIXES:
            if province.endswith(suffix) and province != suffix:
                return province[:-len(suffix)]
        return province

    def extract(self, text: str, level: str = "city") -> Optional[str]:
        """
        从文本中提取指定层级的地址信息。

        Args:
            text: 待匹配的原始文本（如 "广东省广州市天河区某路123号"）
            level: "province" | "province_short" | "city" | "area"

        Returns:
            匹配到的名称，未匹配返回 None
        """
        if not text or not isinstance(text, str):
            return None

        text = text.strip()
        if not text:
            return None

        self._ensure_loaded()

        # 辅助：通过市名（含简称）反查省
        def _find_province_via_city(txt):
            for name in self._city_names:
                if name in txt:
                    return self._city_to_province.get(name)
            for short_name in self._city_short_names:
                if short_name in txt:
                    full = self._city_short_to_full.get(short_name, '')
                    return self._city_to_province.get(full)
            return None

        def _find_province_short_via_city(txt):
            for name in self._city_names:
                if name in txt:
                    return self._city_to_province_short.get(name)
            for short_name in self._city_short_names:
                if short_name in txt:
                    full = self._city_short_to_full.get(short_name, '')
                    return self._city_to_province_short.get(full)
            return None

        def _find_city(txt):
            for name in self._city_names:
                if name in txt:
                    return name
            for short_name in self._city_short_names:
                if short_name in txt:
                    return self._city_short_to_full.get(short_name, '')
            return None

        if level == "province":
            for name in self._province_names:
                if name in text:
                    return name
            p = _find_province_via_city(text)
            if p:
                return p
            for area_name in self._area_names:
                if area_name in text:
                    province = self._area_to_province.get(area_name)
                    if province:
                        return province
        elif level == "province_short":
            for name in self._province_short_names:
                if name in text:
                    return name
            s = _find_province_short_via_city(text)
            if s:
                return s
            for area_name in self._area_names:
                if area_name in text:
                    short = self._area_to_province_short.get(area_name)
                    if short:
                        return short
        elif level == "city":
            c = _find_city(text)
            if c:
                return c
            for area_name in self._area_names:
                if area_name in text:
                    city = self._area_to_city.get(area_name)
                    if city:
                        return city
        elif level == "area":
            for name in self._area_names:
                if name in text:
                    return name

        return None

    def extract_from_columns(self, row: dict, source_cols: list[str],
                             level: str = "city") -> Optional[str]:
        """
        从行数据的多个候选列中依次尝试提取地址。

        Args:
            row: 数据行 dict（key=显示名, value=文本值）
            source_cols: 候选列显示名列表，按优先级排列
            level: 提取层级

        Returns:
            第一个匹配到的结果，全部未匹配返回 None
        """
        for col_name in source_cols:
            if not col_name:
                continue
            text = row.get(col_name)
            if not text:
                continue
            result = self.extract(str(text), level)
            if result:
                return result
        return None
