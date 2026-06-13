"""
Excel / CSV 导入器

将 Excel/CSV 文件导入为 MySQL 表，供 BI 仪表盘作为数据源使用。
"""

import os
import logging
from datetime import datetime

import pandas as pd
import numpy as np

from .models import ExcelDataset, _new_id

logger = logging.getLogger(__name__)

# MySQL 列类型映射
_PD_TYPE_TO_MYSQL = {
    'int64': 'BIGINT',
    'int32': 'INT',
    'float64': 'DOUBLE',
    'float32': 'FLOAT',
    'bool': 'TINYINT(1)',
    'datetime64[ns]': 'DATETIME',
    'object': 'LONGTEXT',
    'string': 'VARCHAR(512)',
}

SUPPORTED_EXTENSIONS = ['.xlsx', '.xls', '.csv', '.json']


class ExcelImporter:
    """Excel / CSV 文件导入器"""

    def __init__(self, db):
        """
        Args:
            db: ReportDatabase 实例（用于建表 + 写入）
        """
        self._db = db

    @staticmethod
    def get_supported_formats() -> list[str]:
        return SUPPORTED_EXTENSIONS

    @staticmethod
    def preview(file_path: str, nrows: int = 50) -> dict:
        """
        预览文件前 N 行，返回 {columns: [...], rows: [...], total_rows_estimate: int}
        """
        ext = os.path.splitext(file_path)[1].lower()
        try:
            if ext == '.csv':
                df = pd.read_csv(file_path, nrows=nrows)
            elif ext == '.json':
                df = pd.read_json(file_path, nrows=nrows)
            else:
                df = pd.read_excel(file_path, nrows=nrows)
        except Exception as e:
            return {'error': str(e), 'columns': [], 'rows': [], 'total_rows_estimate': 0}

        # 推断列信息
        columns = []
        for col in df.columns:
            dtype = df[col].dtype
            col_info = {
                'key': _clean_column_name(str(col)),
                'label': str(col),
                'data_type': _infer_data_type(dtype, df[col]),
            }
            columns.append(col_info)

        # 将 DataFrame 转为 dict 列表（处理 NaN）
        rows = df.rename(columns={c: _clean_column_name(str(c)) for c in df.columns})
        rows = rows.where(pd.notnull(rows), None).to_dict(orient='records')

        return {
            'columns': columns,
            'rows': rows,
            'total_rows_estimate': len(df),
        }

    def import_file(self, file_path: str, progress_callback=None) -> ExcelDataset:
        """
        导入文件到 MySQL，返回 ExcelDataset 对象。

        Args:
            file_path: Excel/CSV 文件路径
            progress_callback: callable(percent, message)

        Returns:
            ExcelDataset 对象

        Raises:
            ValueError: 文件格式不支持或读取失败
            RuntimeError: MySQL 写入失败
        """
        ext = os.path.splitext(file_path)[1].lower()
        if ext not in SUPPORTED_EXTENSIONS:
            raise ValueError(f"不支持的格式: {ext}，支持: {', '.join(SUPPORTED_EXTENSIONS)}")

        # 1. 读取文件
        if progress_callback:
            progress_callback(10, f"读取文件: {os.path.basename(file_path)}")

        try:
            if ext == '.csv':
                df = pd.read_csv(file_path)
            elif ext == '.json':
                df = pd.read_json(file_path)
            else:
                df = pd.read_excel(file_path)
        except Exception as e:
            raise ValueError(f"读取文件失败: {e}")

        if df.empty:
            raise ValueError("文件为空，无数据可导入")

        # 2. 清理列名
        rename_map = {c: _clean_column_name(str(c)) for c in df.columns}
        df = df.rename(columns=rename_map)

        # 3. 推断列信息
        columns = []
        for col in df.columns:
            dtype = df[col].dtype
            columns.append({
                'key': col,
                'label': str(col),
                'data_type': _infer_data_type(dtype, df[col]),
            })

        # 4. 创建 MySQL 表
        dataset_id = _new_id()
        table_name = f"ex_{dataset_id}"

        if progress_callback:
            progress_callback(30, f"创建 MySQL 表: {table_name}")

        if not self._db or not self._db.available:
            raise RuntimeError("MySQL 数据库未连接，无法导入")

        try:
            self._create_table(table_name, columns)
        except Exception as e:
            raise RuntimeError(f"创建表失败: {e}")

        # 5. 批量写入数据
        total_rows = len(df)
        batch_size = 500
        written = 0

        if progress_callback:
            progress_callback(40, f"写入数据: 0 / {total_rows}")

        # 处理 NaN / NaT / inf
        import numpy as np
        df = df.replace([np.nan, np.inf, -np.inf, pd.NaT], None)
        df = df.where(pd.notnull(df), None)

        for start in range(0, total_rows, batch_size):
            end = min(start + batch_size, total_rows)
            batch = df.iloc[start:end]
            rows = batch.to_dict(orient='records')

            try:
                self._db.execute_many_insert(table_name, columns, rows)
                written += len(rows)
            except Exception as e:
                raise RuntimeError(f"写入数据失败 (行 {start}-{end}): {e}")

            if progress_callback:
                pct = 40 + int((written / total_rows) * 60)
                progress_callback(pct, f"写入数据: {written} / {total_rows}")

        # 6. 创建 Dataset 对象
        dataset = ExcelDataset(
            id=dataset_id,
            name=os.path.splitext(os.path.basename(file_path))[0],
            source_file=os.path.abspath(file_path),
            file_type=ext.lstrip('.'),
            columns=columns,
            row_count=total_rows,
            mysql_table=table_name,
        )

        if progress_callback:
            progress_callback(100, "导入完成")

        logger.info(f"Excel 导入完成: {dataset.name} → {table_name} ({total_rows} 行)")
        return dataset

    def _create_table(self, table_name: str, columns: list[dict]):
        """创建 MySQL 表"""
        col_defs = []
        for col in columns:
            mysql_type = _PD_TYPE_TO_MYSQL.get(col['data_type'], 'LONGTEXT')
            col_name = _escape_identifier(col['key'])
            col_defs.append(f"`{col_name}` {mysql_type}")

        sql = (
            f"CREATE TABLE IF NOT EXISTS `{table_name}` ("
            + ", ".join(col_defs)
            + ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
        )
        self._db.execute(sql)

    def _insert_batch(self, table_name: str, columns: list[dict], rows: list[dict]):
        """批量插入数据（使用 executemany 优化）"""
        if not rows:
            return

        col_names = [_escape_identifier(c['key']) for c in columns]
        placeholders = ', '.join(['%s'] * len(col_names))
        sql = (
            f"INSERT INTO `{table_name}` "
            f"(`{'`, `'.join(col_names)}`) "
            f"VALUES ({placeholders})"
        )

        values = []
        for row in rows:
            row_values = []
            for col in columns:
                val = row.get(col['key'])
                if isinstance(val, (np.integer,)):
                    val = int(val)
                elif isinstance(val, (np.floating,)):
                    val = None if np.isnan(val) else float(val)
                elif isinstance(val, (np.bool_,)):
                    val = bool(val)
                elif isinstance(val, pd.Timestamp):
                    val = val.to_pydatetime()
                row_values.append(val)
            values.append(row_values)

        # 使用 pymysql executemany 直接写入（绕过 db.execute 的单条限制）
        conn = self._db._get_conn() if hasattr(self._db, '_get_conn') else None
        if conn:
            try:
                with conn.cursor() as cur:
                    cur.executemany(sql, values)
                return
            except Exception:
                pass

        # 回退：逐条插入
        for val in values:
            self._db.execute(sql, val)


def _clean_column_name(name: str) -> str:
    """清理列名：移除特殊字符，确保 MySQL 兼容"""
    import re
    # 去空格
    name = name.strip()
    # 替换中文标点为下划线
    name = name.replace('（', '_').replace('）', '').replace('（', '_').replace('）', '')
    # 替换非字母数字中文下划线为下划线
    name = re.sub(r'[^\w一-鿿]', '_', name)
    # 去连续下划线
    name = re.sub(r'_+', '_', name)
    # 去首尾下划线
    name = name.strip('_')
    if not name:
        name = 'column'
    # 确保不以数字开头
    if name[0].isdigit():
        name = '_' + name
    return name


def _escape_identifier(name: str) -> str:
    """转义 MySQL 标识符中的反引号"""
    return name.replace('`', '``')


def _infer_data_type(dtype, series) -> str:
    """从 pandas dtype 推断统一的数据类型"""
    dtype_str = str(dtype)

    if dtype_str.startswith('int'):
        return 'int64'
    elif dtype_str.startswith('float'):
        return 'float64'
    elif dtype_str.startswith('bool'):
        return 'bool'
    elif dtype_str.startswith('datetime'):
        return 'datetime64[ns]'

    # object 类型：尝试进一步推断
    if dtype_str == 'object':
        # 尝试检测是否为日期
        try:
            pd.to_datetime(series.dropna().head(10))
            return 'datetime64[ns]'
        except (ValueError, TypeError):
            pass
        return 'object'

    return 'object'
