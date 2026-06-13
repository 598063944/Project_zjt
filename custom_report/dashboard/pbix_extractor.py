"""
PBIX 元数据提取器

提取 .pbix 文件（Power BI）中的图表信息和字段映射，
作为在 BI 仪表盘中重建图表的参考。
"""

import zipfile
import json
import os
import re
import logging
from typing import Optional

from .models import DashboardDefinition, ChartWidget, _new_id

logger = logging.getLogger(__name__)


def _decode_bytes(data: bytes) -> str:
    """尝试多种编码解码字节数据"""
    for enc in ('utf-8', 'utf-16', 'utf-8-sig', 'utf-16-le', 'utf-16-be', 'gbk', 'gb2312', 'latin-1'):
        try:
            return data.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return data.decode('utf-8', errors='replace')


def extract_metadata(file_path: str) -> dict:
    """
    从 .pbix 文件中提取可视化元数据

    Args:
        file_path: .pbix 文件路径

    Returns:
        {
            'success': bool,
            'report_name': str,
            'pages': [{'name': str, 'visuals': [...]}],
            'tables': [str],
            'fields': [str],       # 所有引用字段
            'error': str,          # 仅失败时
        }
    """
    result = {
        'success': False,
        'report_name': '',
        'pages': [],
        'tables': [],
        'fields': [],
        'error': '',
    }

    if not os.path.exists(file_path):
        result['error'] = f'文件不存在: {file_path}'
        return result

    ext = os.path.splitext(file_path)[1].lower()
    if ext not in ('.pbix', '.pbit'):
        result['error'] = f'不支持的格式: {ext}，请选择 .pbix 或 .pbit 文件'
        return result

    try:
        with zipfile.ZipFile(file_path, 'r') as zf:
            # 1. 解析 Report/Layout
            layout_json = None
            for name in zf.namelist():
                if name.lower() == 'report/layout':
                    raw = zf.read(name)
                    text = _decode_bytes(raw)
                    layout_json = json.loads(text)
                    break

            if layout_json is None:
                # 尝试 DataModelSchema
                for name in zf.namelist():
                    if 'datamodelschema' in name.lower():
                        result['error'] = '该 .pbix 使用 Live Connection 模式，无可提取的可视化定义'
                        return result
                result['error'] = '未找到 Report/Layout 文件，可能不是标准 .pbix 格式'
                return result

            # 2. 提取报告名称
            result['report_name'] = _extract_report_name(zf, layout_json)

            # 3. 提取页面和可视化
            sections = layout_json.get('sections', [])
            first_container = True
            for section in sections:
                page = {
                    'name': section.get('displayName', section.get('name', '未命名页面')),
                    'visuals': [],
                }
                for container in section.get('visualContainers', []):
                    config_str = container.get('config', '{}')
                    try:
                        config = json.loads(config_str) if isinstance(config_str, str) else config_str
                    except (json.JSONDecodeError, TypeError):
                        config = {}

                    # 诊断：输出第一个有数据的容器的结构
                    if first_container:
                        sv = config.get('singleVisual', {})
                        vt = sv.get('visualType') or container.get('visualType') or ''
                        if vt and vt not in ('shape', 'image', 'actionButton', 'textbox', 'line'):
                            first_container = False
                            print(f"[BI PBIX] visualType: container={container.get('visualType')}, sv={sv.get('visualType')}")
                            print(f"[BI PBIX] vcObjects 键: {list(sv.get('vcObjects', {}).keys())[:15]}")
                            print(f"[BI PBIX] objects 键: {list(sv.get('objects', {}).keys())[:15]}")
                            try:
                                projs = sv.get('projections', config.get('projections'))
                                if isinstance(projs, list):
                                    print(f"[BI PBIX] projections 示例: {json.dumps(projs[:3], ensure_ascii=False)[:300]}")
                                elif isinstance(projs, dict):
                                    print(f"[BI PBIX] projections(dict) 键: {list(projs.keys())[:10]}")
                            except Exception:
                                pass
                            try:
                                for src_name, src in [('vcObjects', sv.get('vcObjects', {})), ('objects', sv.get('objects', {}))]:
                                    title_cfg = src.get('title')
                                    if title_cfg:
                                        print(f"[BI PBIX] {src_name}.title: {json.dumps(title_cfg, ensure_ascii=False)[:300]}")
                            except Exception:
                                pass
                            for role in ['category', 'y', 'values', 'x', 'Color', 'Size', 'X', 'Y', 'Value', 'Category']:
                                if role in sv.get('vcObjects', {}):
                                    try:
                                        role_data = sv['vcObjects'][role]
                                        print(f"[BI PBIX] vcObjects.{role}: {json.dumps(role_data, ensure_ascii=False)[:300]}")
                                    except Exception:
                                        pass
                                    break

                    # 图表类型：singleVisual.visualType > container.visualType
                    sv = config.get('singleVisual', {})
                    raw_type = sv.get('visualType') or container.get('visualType') or container.get('type') or 'unknown'

                    # 跳过装饰元素（形状、图片、按钮、分隔线）
                    _DECOR_TYPES = ('shape', 'image', 'actionButton', 'textbox', 'line', 'basicShape')
                    if raw_type in _DECOR_TYPES:
                        continue

                    visual_type = _map_visual_type(raw_type)

                    name = config.get('name', '')
                    title = _extract_visual_title(config, container)
                    display_name = title.strip("'\"") if title else ''
                    if not display_name or _is_hash_id(display_name):
                        display_name = name if not _is_hash_id(name) else f'未命名{visual_type}'
                    display_name = display_name.strip("'\"")

                    try:
                        fields = _extract_fields(config)
                    except Exception:
                        fields = []

                    page['visuals'].append({
                        'name': display_name,
                        'type': visual_type,
                        'pbix_type': raw_type,
                        'fields': fields,
                    })
                    for f in fields:
                        if f not in result['fields']:
                            result['fields'].append(f)

                result['pages'].append(page)

            # 4. 提取表名
            result['tables'] = _extract_tables(zf)

        result['success'] = True
    except zipfile.BadZipFile:
        result['error'] = '文件损坏或不是有效的 .pbix 文件'
    except Exception as e:
        result['error'] = f'提取失败: {e}'

    return result


def _extract_report_name(zf: zipfile.ZipFile, layout_json: dict) -> str:
    """从布局或连接文件中提取报告名称"""
    name = layout_json.get('displayName', '') or layout_json.get('name', '')
    if name:
        return name

    # 尝试从 Connections 获取
    for fname in zf.namelist():
        if 'connections' in fname.lower():
            try:
                conn = json.loads(_decode_bytes(zf.read(fname)))
                if isinstance(conn, dict):
                    name = conn.get('Name', '') or conn.get('name', '')
            except Exception:
                pass
            if name:
                return name

    return '未命名报告'


def _extract_fields(config: dict) -> list[str]:
    """从可视化配置中递归提取字段引用"""
    fields = []
    if not isinstance(config, dict):
        return fields

    def _add_field(tbl: str, col: str):
        if col and col not in ('undefined', 'null', ''):
            key = f"{tbl}.{col}" if tbl else col
            if key not in fields:
                fields.append(key)

    def _walk(obj, depth=0):
        if depth > 25:
            return
        if isinstance(obj, dict):
            # SourceRef 模式（最常见）
            sr = obj.get('SourceRef')
            if isinstance(sr, dict):
                tbl = sr.get('Entity', '') or sr.get('Table', '')
                col = sr.get('Column', '') or sr.get('Name', '') or sr.get('Property', '')
                _add_field(tbl, col)
            # QueryRef
            qr = obj.get('QueryRef')
            if qr:
                fields.append(str(qr))
            # 遍历子节点
            for key, val in obj.items():
                if key in ('SourceRef', 'QueryRef', 'Literal'):
                    continue  # 已处理或跳过
                _walk(val, depth + 1)
        elif isinstance(obj, list):
            for item in obj:
                _walk(item, depth + 1)
        elif isinstance(obj, str) and depth == 0:
            pass  # 顶层字符串忽略

    # 同时搜索 singleVisual 和 objects
    _walk(config)
    sv = config.get('singleVisual', {})
    _walk(sv.get('objects', {}))
    _walk(sv.get('vcObjects', {}))

    # 从 projections 提取
    if not fields:
        projections = sv.get('projections', config.get('projections', []))
        if isinstance(projections, list):
            for p in projections:
                if isinstance(p, dict):
                    qr = p.get('queryRef', '')
                    if qr:
                        fields.append(str(qr))

    return sorted(set(fields))


def _extract_tables(zf: zipfile.ZipFile) -> list[str]:
    """从 DataModel 中提取表名"""
    tables = []
    for name in zf.namelist():
        if 'datamodel' in name.lower() and name.lower().endswith('.json'):
            try:
                dm = json.loads(_decode_bytes(zf.read(name)))
                if isinstance(dm, dict):
                    model = dm.get('model', dm)
                    for tbl in model.get('tables', []):
                        tbl_name = tbl.get('name', '') or tbl.get('Name', '')
                        if tbl_name and not tbl_name.startswith('_'):
                            tables.append(tbl_name)
            except Exception:
                pass
            if tables:
                break
    return sorted(set(tables))


# 常见 PBIX visualType → 中文名映射
_PBIX_TYPE_MAP = {
    # 柱状图
    'barChart': '柱状图', 'columnChart': '柱状图',
    'clusteredBarChart': '簇状柱状图', 'clusteredColumnChart': '簇状柱状图',
    'stackedBarChart': '堆叠柱状图', 'stackedColumnChart': '堆叠柱状图',
    'hundredPercentStackedBarChart': '百分比堆叠柱状图',
    'hundredPercentStackedColumnChart': '百分比堆叠柱状图',
    'ribbonChart': '带状图',
    # 折线/面积
    'lineChart': '折线图', 'areaChart': '面积图', 'stackedAreaChart': '堆叠面积图',
    # 饼/环形
    'pieChart': '饼图', 'donutChart': '环形图',
    'barOfPieChart': '饼图',
    # 散点/气泡
    'scatterChart': '散点图', 'waterfallChart': '瀑布图',
    # 树图/漏斗
    'treemap': '矩形树图', 'funnel': '漏斗图',
    'decompositionTree': '分解树', 'decompositionTreeVisual': '分解树',
    # 卡片/KPI
    'card': '指标卡', 'cardVisual': '指标卡', 'multiRowCard': '多行卡片', 'kpi': 'KPI',
    # 表/矩阵
    'tableEx': '表格', 'pivotTable': '透视表', 'matrix': '矩阵',
    # 仪表
    'gauge': '仪表盘',
    # 切片器
    'slicer': '切片器',
    # 地图
    'map': '地图', 'filledMap': '填充地图', 'shapeMap': '形状地图',
    # 自定义
    'scriptVisual': '脚本可视化', 'customVisual': '自定义可视化',
    # 装饰
    'shape': '形状(装饰)', 'image': '图片(装饰)', 'actionButton': '按钮(装饰)',
    'textbox': '文本框(装饰)', 'line': '分隔线(装饰)',
    # 其他
    'qna': '问答', 'keyDriversVisual': '关键影响因素',
}


def _map_visual_type(pbix_type: str) -> str:
    """将 PBIX visualType 映射为中文名"""
    if pbix_type in _PBIX_TYPE_MAP:
        return _PBIX_TYPE_MAP[pbix_type]
    # 处理带 GUID/Hex 后缀的自定义视觉（如 deneb7E15..., barOfPieChartEF91...）
    import re
    base = re.sub(r'[0-9A-F]{20,}$', '', pbix_type)
    if base and base != pbix_type and base in _PBIX_TYPE_MAP:
        return _PBIX_TYPE_MAP[base]
    if base and base != pbix_type:
        return f'自定义({base})'
    return f'自定义({pbix_type[:20]})'


def _extract_visual_title(config: dict, container: dict) -> str:
    """从 PBIX 可视化配置中提取标题（多路径 fallback）"""
    # 路径 1: container 上的直接属性
    for key in ('friendlyName', 'displayName', 'title'):
        val = container.get(key, '')
        if val and not _is_hash_id(str(val)):
            return str(val)

    # 路径 2: vcObjects.title / objects.title
    for src_key in ('vcObjects', 'objects'):
        try:
            src = config.get('singleVisual', {}).get(src_key, {})
            title_cfg = src.get('title', [])
            if isinstance(title_cfg, list) and title_cfg:
                val = _extract_literal_value(title_cfg[0])
                if val:
                    return val
        except Exception:
            pass

    # 路径 3: 全量扫描 Literal.Value，找最长的人类可读文本
    return _deep_find_title(config)


def _extract_literal_value(obj, depth=0) -> str:
    """从嵌套对象中提取 Literal.Value"""
    if depth > 8:
        return ''
    if isinstance(obj, dict):
        if 'Literal' in obj and isinstance(obj['Literal'], dict):
            val = obj['Literal'].get('Value', '')
            if isinstance(val, str) and len(val) > 1:
                return val
        if 'Value' in obj and isinstance(obj['Value'], str) and len(obj['Value']) > 1:
            return obj['Value']
        for v in obj.values():
            r = _extract_literal_value(v, depth + 1)
            if r:
                return r
    elif isinstance(obj, list):
        for item in obj:
            r = _extract_literal_value(item, depth + 1)
            if r:
                return r
    return ''


def _deep_find_title(obj, depth=0) -> str:
    """全量扫描所有 Literal.Value，返回最可能是标题的文本（最长非哈希字符串）"""
    if depth > 8:
        return ''
    candidates = []

    def _collect(obj, d):
        if d > 8:
            return
        if isinstance(obj, dict):
            if 'Literal' in obj and isinstance(obj['Literal'], dict):
                val = obj['Literal'].get('Value', '')
                if isinstance(val, str) and len(val) > 2 and not _is_hash_id(val):
                    candidates.append(val)
            for v in obj.values():
                _collect(v, d + 1)
        elif isinstance(obj, list):
            for item in obj:
                _collect(item, d + 1)

    _collect(obj, 0)
    # 返回最长的候选（排除包含 SQL/DAX 代码特征的）
    candidates = [c for c in candidates if not c.startswith('let ') and '=' not in c[:3]]
    return max(candidates, key=len) if candidates else ''


def _is_hash_id(s: str) -> bool:
    """判断字符串是否为哈希 ID（16~24 位 hex）"""
    s = (s or '').strip("'\"")
    return bool(re.match(r'^[0-9a-fA-F]{12,30}$', s))


# ====== PBIX 类型 → 我们的图表类型 ======
_PBIX_TO_OUR_TYPE = {
    'barChart': 'bar', 'columnChart': 'bar', 'clusteredBarChart': 'bar',
    'clusteredColumnChart': 'bar', 'stackedBarChart': 'stacked_bar',
    'stackedColumnChart': 'stacked_bar',
    'lineChart': 'line', 'areaChart': 'area', 'stackedAreaChart': 'stacked_area',
    'pieChart': 'pie', 'donutChart': 'pie',
    'scatterChart': 'scatter', 'waterfallChart': 'waterfall',
    'treemap': 'treemap', 'funnel': 'funnel',
    'card': 'card', 'cardVisual': 'card', 'kpi': 'card',
    'tableEx': 'table', 'matrix': 'table', 'pivotTable': 'table',
    'gauge': 'gauge', 'slicer': 'table',
    'map': 'map_china', 'filledMap': 'map_china',
    'decompositionTree': 'tree', 'decompositionTreeVisual': 'tree',
    'ribbonChart': 'bar', 'keyDriversVisual': 'bar',
}


def _get_role_field(role_data) -> str:
    """从 PBIX role 数据中提取字段引用"""
    if not role_data:
        return ''
    data = role_data[0] if isinstance(role_data, list) else role_data
    if not isinstance(data, dict):
        return ''
    # 尝试 SourceRef
    sr = data.get('expr', {}).get('SourceRef', data.get('SourceRef', {}))
    if isinstance(sr, dict):
        col = sr.get('Column', '') or sr.get('Name', '') or sr.get('Property', '')
        return col
    # 尝试 queryRef
    qr = data.get('queryRef', '')
    if qr and isinstance(qr, str):
        return qr.split('.')[-1] if '.' in qr else qr
    return ''


def extract_to_dashboard(file_path: str) -> dict:
    """
    从 .pbix/.pbit 文件直接生成仪表盘定义，含图表和字段映射。

    Returns:
        {
            'success': bool,
            'dashboard': DashboardDefinition or None,
            'report_name': str,
            'chart_count': int,
            'error': str,
        }
    """
    result = {
        'success': False,
        'dashboard': None,
        'report_name': '',
        'chart_count': 0,
        'error': '',
    }

    if not os.path.exists(file_path):
        result['error'] = f'文件不存在: {file_path}'
        return result

    ext = os.path.splitext(file_path)[1].lower()
    if ext not in ('.pbix', '.pbit'):
        result['error'] = f'不支持的格式: {ext}'
        return result

    try:
        with zipfile.ZipFile(file_path, 'r') as zf:
            layout_json = None
            for name in zf.namelist():
                if name.lower() == 'report/layout':
                    layout_json = json.loads(_decode_bytes(zf.read(name)))
                    break
            if not layout_json:
                result['error'] = '未找到 Report/Layout'
                return result

            report_name = _extract_report_name(zf, layout_json)
            dashboard = DashboardDefinition(name=report_name or 'PBIX 导入')
            charts = []
            _DECOR_TYPES = ('shape', 'image', 'actionButton', 'textbox', 'line', 'basicShape')

            for section in layout_json.get('sections', []):
                for container in section.get('visualContainers', []):
                    config_str = container.get('config', '{}')
                    try:
                        config = json.loads(config_str) if isinstance(config_str, str) else config_str
                    except Exception:
                        config = {}

                    sv = config.get('singleVisual', {})
                    raw_type = sv.get('visualType') or container.get('visualType') or ''
                    if raw_type in _DECOR_TYPES:
                        continue

                    # 图表类型
                    our_type = _PBIX_TO_OUR_TYPE.get(raw_type, 'bar')
                    # 标题
                    title = _extract_visual_title(config, container).strip("'\"")
                    if not title or _is_hash_id(title):
                        title = _map_visual_type(raw_type)

                    # 提取字段映射
                    vc = sv.get('vcObjects', {})
                    x_field = _get_role_field(vc.get('category') or vc.get('Category') or vc.get('x') or vc.get('X') or vc.get('Axis'))
                    y_field = _get_role_field(vc.get('y') or vc.get('Y') or vc.get('values') or vc.get('Values') or vc.get('measures') or vc.get('Measure'))
                    color_field = _get_role_field(vc.get('Color') or vc.get('Legend') or vc.get('series') or vc.get('Series'))
                    size_field = _get_role_field(vc.get('Size') or vc.get('bubbleSize'))

                    # 如果没有从 vcObjects 提取到，尝试从 projections 提取
                    if not x_field or not y_field:
                        projs = sv.get('projections', config.get('projections', []))
                        if isinstance(projs, list) and len(projs) >= 2:
                            if not x_field and len(projs) > 0:
                                x_field = str(projs[0].get('queryRef', '')).split('.')[-1]
                            if not y_field and len(projs) > 1:
                                y_field = str(projs[1].get('queryRef', '')).split('.')[-1]

                    # 位置：从 PBIX 容器坐标推算
                    x = container.get('x', 0)
                    y = container.get('y', 0)
                    w = container.get('width', 400)
                    h = container.get('height', 300)
                    col = max(0, int(x / 400))
                    row = max(0, int(y / 300))
                    col_span = max(1, int(w / 400))
                    row_span = max(1, int(h / 300))

                    y_fields = [y_field] if y_field else []
                    chart = ChartWidget(
                        id=_new_id(),
                        chart_type=our_type,
                        title=title,
                        x_field=x_field,
                        y_fields=y_fields,
                        aggregate_funcs={y_field: 'SUM'} if y_field else {},
                        color_field=color_field or '',
                        size_field=size_field or '',
                        position=(row, col),
                        size=(row_span, col_span),
                        data_source_type='report',
                        data_source_id='',
                        data_source_name='(需手动选择数据源)',
                    )
                    charts.append(chart)

            dashboard.charts = charts
            result['dashboard'] = dashboard
            result['chart_count'] = len(charts)
            result['report_name'] = report_name
            result['success'] = True

    except Exception as e:
        result['error'] = str(e)

    return result
