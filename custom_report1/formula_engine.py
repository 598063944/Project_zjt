"""
公式引擎

职责:
- 解析 Excel 风格公式表达式（支持常用 Excel 函数）
- 用 pandas DataFrame 执行向量化计算
- 计算汇总行（SUM/AVG/COUNT/MAX/MIN）
"""

import pandas as pd
import numpy as np
import re
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

# ==================== 中文标点规范化 ====================

_CJK_PUNCT_MAP = str.maketrans({
    '（': '(', '）': ')', '，': ',', '：': ':',
    '“': '"', '”': '"', '‘': "'", '’': "'",
    '＋': '+', '－': '-', '×': '*', '÷': '/',
    '＝': '=', '＞': '>', '＜': '<',
})


def _normalize_expr(expr: str) -> str:
    """将中文标点转为英文标点，去除首尾等号。"""
    expr = expr.strip()
    if expr.startswith("="):
        expr = expr[1:]
    return expr.translate(_CJK_PUNCT_MAP)


# ==================== 列名安全映射 ====================

def _build_col_name_map(col_names: list[str]) -> dict[str, str]:
    """为 DataFrame 列名创建安全变量名映射。

    中文列名（如 '单价'）不能直接用于 Python eval，提取字母/数字/下划线
    作为变量名基础，冲突时追加数字后缀。
    """
    name_map: dict[str, str] = {}       # safe_var -> df_col_name
    used_vars: dict[str, int] = {}      # safe_var -> usage count

    for col in col_names:
        alpha = re.sub(r'[^a-zA-Z0-9_]', '', col)
        if not alpha:
            alpha = 'col'
        if alpha[0].isdigit():
            alpha = 'c' + alpha

        if alpha in used_vars:
            used_vars[alpha] += 1
            safe = f"{alpha}_{used_vars[alpha]}"
        else:
            used_vars[alpha] = 1
            safe = alpha

        name_map[safe] = col

    return name_map


def _replace_column_refs(expr: str, df_cols: list[str]) -> tuple[str, dict[str, str], dict[str, str]]:
    """将表达式中的列名引用替换为安全的 DataFrame 访问形式。

    步骤:
    1. 为每个列名分配安全变量名
    2. 按列名长度降序替换（避免短列名错误匹配长列名的一部分）
    3. 替换为 `_df['col_name']` 形式，使其在 eval 中直接访问

    Returns:
        safe_expr: 列名已替换为 _df[...] 访问形式的表达式
        safe_to_orig: {safe_var: original_col_name}
        orig_to_safe: {original_col_name: safe_var}
    """
    name_map = _build_col_name_map(df_cols)
    safe_to_orig = dict(name_map)
    orig_to_safe = {v: k for k, v in name_map.items()}

    # 按长度降序排序，确保最长匹配优先
    sorted_cols = sorted(df_cols, key=len, reverse=True)
    result = expr

    # 用占位符避免部分替换问题
    for col in sorted_cols:
        if col in result:
            safe = orig_to_safe.get(col)
            if safe:
                result = result.replace(col, f"_df['{col}']")

    return result, safe_to_orig, orig_to_safe


# ==================== Excel 函数映射 ====================

def _to_str_series(x):
    """将 Series 或标量安全转为字符串 Series。"""
    if isinstance(x, pd.Series):
        return x.astype(str)
    return str(x)


def _concat(*args):
    """CONCAT 函数实现：拼接多个 Series/标量为字符串。"""
    args = list(args)
    result = args[0]
    if not isinstance(result, pd.Series):
        result = str(result)
    else:
        result = result.astype(str)
    for a in args[1:]:
        if isinstance(a, pd.Series):
            result = result + a.astype(str)
        else:
            result = result + str(a)
    return result


def _text_join(sep, *args):
    """TEXTJOIN 函数实现。"""
    result = _to_str_series(args[0])
    for a in args[1:]:
        result = result + str(sep) + _to_str_series(a)
    return result


def _ifs(*args):
    """IFS 函数实现: IFS(cond1, val1, cond2, val2, ...)"""
    if len(args) < 2 or len(args) % 2 != 0:
        raise ValueError("IFS 需要成对的条件和值")
    result = pd.Series(np.nan, index=args[0].index)
    for i in range(0, len(args), 2):
        cond, val = args[i], args[i + 1]
        # 只填充尚未赋值的行
        mask = cond & result.isna()
        if isinstance(val, pd.Series):
            result = result.where(~mask, val)
        else:
            result = result.where(~mask, val)
    return result


def _isnumber(s):
    """ISNUMBER 函数实现。"""
    return s.apply(lambda x: isinstance(x, (int, float)) and not isinstance(x, bool))


def _istext(s):
    """ISTEXT 函数实现。"""
    return s.apply(lambda x: isinstance(x, str))


def _isblank(s):
    """ISBLANK 函数实现。"""
    return s.isna() | (s.astype(str).str.strip() == '')


def _replace_text(s, old, new):
    """REPLACE → 字符串替换。"""
    return s.astype(str).str.replace(old, new, regex=False)


def _substitute(s, old, new, instance=None):
    """SUBSTITUTE → 字符串替换（可选第 N 次出现）。"""
    if instance is not None:
        return s.astype(str).str.replace(old, new, n=instance)
    return s.astype(str).str.replace(old, new)


def _find(substr, s, start=0):
    """FIND → 返回子串位置（从 1 开始），未找到返回 -1。"""
    result = s.astype(str).str.find(substr, start)
    return result.where(result < 0, result + 1)


def _proper(s):
    """PROPER → 每个单词首字母大写。"""
    return s.astype(str).str.title()


def _search(find_text, within, start=1):
    """SEARCH → 不区分大小写查找子串位置（从 1 开始），未找到返回 -1。"""
    start = int(start) - 1 if start else 0
    result = within.astype(str).str.lower().str.find(str(find_text).lower(), start)
    return result.where(result < 0, result + 1)


def _exact(v1, v2):
    """EXACT → 区分大小写精确比较两个字符串。"""
    return v1.astype(str) == v2.astype(str)


def _rept(s, n):
    """REPT → 将文本重复指定次数。"""
    n = int(n)
    return s.astype(str) * n


def _text(value, fmt):
    """TEXT → 用 Python 格式说明符（如 .2f、,.0f）或 strftime 模式格式化数值/日期。"""
    fmt = str(fmt)
    if isinstance(value, pd.Series):
        def _fmt_one(x):
            if pd.isna(x):
                return ''
            try:
                if isinstance(x, (pd.Timestamp, datetime)):
                    return x.strftime(fmt)
                return format(x, fmt)
            except Exception:
                return str(x)
        return value.apply(_fmt_one)
    else:
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return ''
        if isinstance(value, (pd.Timestamp, datetime)):
            return value.strftime(fmt)
        return format(value, fmt)


def _ceiling(num, significance=1):
    """CEILING → 将数值向上舍入到指定基数的倍数。"""
    significance = float(significance) if significance != 0 else 1.0
    return np.ceil(num / significance) * significance


def _floor_func(num, significance=1):
    """FLOOR → 将数值向下舍入到指定基数的倍数。"""
    significance = float(significance) if significance != 0 else 1.0
    return np.floor(num / significance) * significance


def _ln(num):
    """LN → 自然对数（以 e 为底）。"""
    return np.log(num)


def _log_func(num, base=10):
    """LOG → 以指定底数的对数。"""
    if isinstance(base, pd.Series):
        return np.log(num) / np.log(base)
    base = float(base)
    if base == 10:
        return np.log10(num)
    return np.log(num) / np.log(float(base))


def _exp_func(num):
    """EXP → e 的 n 次幂。"""
    return np.exp(num)


def _parse_criteria(series, criteria_str):
    """解析条件字符串，返回布尔掩码。

    支持: '>100', '<50', '>=10', '<=5', '<>0', '!=0', '=text', 'text'（等于）。
    """
    criteria_str = str(criteria_str)
    floating = True
    try:
        float(criteria_str)
        # criteria_str 本身是个数字字符串，无法判断比较意图，按精确文本匹配处理
        return series.astype(str) == criteria_str
    except ValueError:
        pass

    if criteria_str.startswith('>='):
        s = series.astype(float)
        return s >= float(criteria_str[2:])
    elif criteria_str.startswith('<='):
        s = series.astype(float)
        return s <= float(criteria_str[2:])
    elif criteria_str.startswith('<>'):
        s = series.astype(float)
        return s != float(criteria_str[2:])
    elif criteria_str.startswith('!='):
        s = series.astype(float)
        return s != float(criteria_str[2:])
    elif criteria_str.startswith('>'):
        s = series.astype(float)
        return s > float(criteria_str[1:])
    elif criteria_str.startswith('<'):
        s = series.astype(float)
        return s < float(criteria_str[1:])
    elif criteria_str.startswith('='):
        return series.astype(str) == criteria_str[1:]
    else:
        return series.astype(str) == criteria_str


def _countif(series, criteria):
    """COUNTIF → 统计满足条件的单元格数量。"""
    mask = _parse_criteria(series, criteria)
    return mask.sum()


def _sumif(series, criteria, sum_series=None):
    """SUMIF → 对满足条件的单元格求和。"""
    mask = _parse_criteria(series, criteria)
    source = sum_series if sum_series is not None else series
    return source[mask].sum()


def _averageif(series, criteria, avg_series=None):
    """AVERAGEIF → 对满足条件的单元格求平均值。"""
    mask = _parse_criteria(series, criteria)
    source = avg_series if avg_series is not None else series
    return source[mask].mean()


def _edate(start_date, months):
    """EDATE → 返回指定月份数之前或之后的日期。"""
    start_dt = pd.to_datetime(start_date, errors='coerce')
    if isinstance(months, pd.Series):
        result = []
        for d, m in zip(start_dt, months):
            if pd.notna(d) and pd.notna(m):
                result.append(d + pd.DateOffset(months=int(m)))
            else:
                result.append(pd.NaT)
        return pd.Series(result, index=start_dt.index)
    return start_dt + pd.DateOffset(months=int(months))


def _eomonth(start_date, months):
    """EOMONTH → 返回指定月份数之前或之后月份的最后一天。"""
    import calendar as _cal
    start_dt = pd.to_datetime(start_date, errors='coerce')
    if isinstance(months, pd.Series):
        result = []
        for d, m in zip(start_dt, months):
            if pd.notna(d) and pd.notna(m):
                offset_date = d + pd.DateOffset(months=int(m))
                last_day = _cal.monthrange(offset_date.year, offset_date.month)[1]
                result.append(pd.Timestamp(offset_date.year, offset_date.month, last_day))
            else:
                result.append(pd.NaT)
        return pd.Series(result, index=start_dt.index)
    offset_date = start_dt + pd.DateOffset(months=int(months))
    last_day = _cal.monthrange(offset_date.year, offset_date.month)[1]
    return pd.Timestamp(offset_date.year, offset_date.month, last_day)


def _time(h, m, s):
    """TIME → 将时、分、秒合并为时间字符串 HH:MM:SS。"""
    h, m, s = [pd.to_numeric(arg, errors='coerce') for arg in (h, m, s)]
    return (h.astype(int).astype(str).str.zfill(2) + ':' +
            m.astype(int).astype(str).str.zfill(2) + ':' +
            s.astype(int).astype(str).str.zfill(2))


def _yearfrac(start, end, basis=0):
    """YEARFRAC → 返回两个日期之间的年份小数。basis: 0=US 30/360, 1=实际/实际。"""
    start_dt = pd.to_datetime(start, errors='coerce')
    end_dt = pd.to_datetime(end, errors='coerce')
    diff = (end_dt - start_dt).dt.days.astype(float)
    if basis == 0:
        return diff / 360.0
    else:
        years = end_dt.dt.year - start_dt.dt.year
        # 粗略日数：年份天数按 365.25 近似
        return diff / 365.25


def _isoweeknum(date):
    """ISOWEEKNUM → ISO 周数（周一开始）。"""
    return pd.to_datetime(date, errors='coerce').dt.isocalendar().week.astype(float)


def _even(num):
    """EVEN → 向上舍入到最接近的偶数。"""
    num = pd.to_numeric(num, errors='coerce')
    return np.ceil(num / 2) * 2


def _odd(num):
    """ODD → 向上舍入到最接近的奇数。"""
    num = pd.to_numeric(num, errors='coerce')
    return np.ceil((num - 1) / 2) * 2 + 1


def _trunc(num, digits=0):
    """TRUNC → 将数字截断到指定位数（不四舍五入）。"""
    factor = 10 ** int(digits)
    return np.trunc(pd.to_numeric(num, errors='coerce') * factor) / factor


def _pi():
    """PI → 圆周率 π。"""
    return np.pi


def _radians(deg):
    """RADIANS → 角度转弧度。"""
    return pd.to_numeric(deg, errors='coerce') * np.pi / 180.0


def _degrees(rad):
    """DEGREES → 弧度转角度。"""
    return pd.to_numeric(rad, errors='coerce') * 180.0 / np.pi


def _sign(num):
    """SIGN → 返回数字的符号（-1, 0, 1）。"""
    return np.sign(pd.to_numeric(num, errors='coerce'))


def _product(*args):
    """PRODUCT → 返回所有参数的乘积。"""
    result = 1
    for a in args:
        if isinstance(a, pd.Series):
            a = pd.to_numeric(a, errors='coerce').fillna(1)
        result = result * a
    return result


def _quotient(num, denom):
    """QUOTIENT → 整数除法（舍弃余数）。"""
    return (pd.to_numeric(num, errors='coerce') // pd.to_numeric(denom, errors='coerce'))


def _fact(n):
    """FACT → 阶乘。"""
    import math
    n = pd.to_numeric(n, errors='coerce')
    if isinstance(n, pd.Series):
        return n.apply(lambda x: math.factorial(int(x)) if pd.notna(x) and x >= 0 else np.nan)
    return math.factorial(int(n)) if n >= 0 else np.nan


def _value(text):
    """VALUE → 将文本转为数字。"""
    return pd.to_numeric(text.astype(str), errors='coerce')


def _fixed(num, decimals=2, no_commas=False):
    """FIXED → 格式化数字，保留指定位小数，可选千位分隔符。"""
    fmt = f"{{:,.{int(decimals)}f}}"
    if no_commas:
        fmt = f"{{:.{int(decimals)}f}}"
    num = pd.to_numeric(num, errors='coerce')
    if isinstance(num, pd.Series):
        return num.apply(lambda x: fmt.format(x) if pd.notna(x) else '')
    return fmt.format(num) if pd.notna(num) else ''


def _char(code):
    """CHAR → 返回指定 ASCII 码对应的字符。"""
    code = pd.to_numeric(code, errors='coerce')
    if isinstance(code, pd.Series):
        return code.apply(lambda x: chr(int(x)) if pd.notna(x) and 0 <= x <= 1114111 else '')
    return chr(int(code)) if 0 <= code <= 1114111 else ''


def _code(text):
    """CODE → 返回第一个字符的 Unicode 码点。"""
    t = text.astype(str)
    if isinstance(t, pd.Series):
        return t.apply(lambda x: ord(x[0]) if len(x) > 0 else np.nan)
    return ord(t[0]) if len(t) > 0 else np.nan


def _clean(text):
    """CLEAN → 移除文本中的不可打印字符。"""
    import unicodedata
    t = text.astype(str)
    if isinstance(t, pd.Series):
        return t.apply(lambda x: ''.join(ch for ch in x if unicodedata.category(ch)[0] != 'C' or ch in '\t\n\r'))
    return ''.join(ch for ch in t if unicodedata.category(ch)[0] != 'C' or ch in '\t\n\r')


def _xor(a, b):
    """XOR → 逻辑异或。"""
    return np.logical_xor(a.astype(bool), b.astype(bool))


def _switch(expr, *cases, default=None):
    """SWITCH → 根据表达式匹配 case 返回对应值，无匹配返回 default。"""
    expr_val = expr
    if isinstance(expr_val, pd.Series):
        expr_val = expr_val.iloc[0] if len(expr_val) > 0 else None
    # cases are pairs: case1, result1, case2, result2, ...
    for i in range(0, len(cases) - 1, 2):
        if expr_val == cases[i]:
            return cases[i + 1]
    if len(cases) % 2 == 1:
        return cases[-1]  # last arg is default
    return default


def _median(*args):
    """MEDIAN → 返回中位数。"""
    arr = np.array([pd.to_numeric(a, errors='coerce').values
                     if isinstance(a, pd.Series) else a for a in args])
    return np.nanmedian(arr, axis=0)


def _stdev(*args):
    """STDEV → 样本标准差。"""
    arr = np.array([pd.to_numeric(a, errors='coerce').values
                     if isinstance(a, pd.Series) else a for a in args])
    return np.nanstd(arr, axis=0, ddof=1)


def _stdevp(*args):
    """STDEVP → 总体标准差。"""
    arr = np.array([pd.to_numeric(a, errors='coerce').values
                     if isinstance(a, pd.Series) else a for a in args])
    return np.nanstd(arr, axis=0, ddof=0)


def _var(*args):
    """VAR → 样本方差。"""
    arr = np.array([pd.to_numeric(a, errors='coerce').values
                     if isinstance(a, pd.Series) else a for a in args])
    return np.nanvar(arr, axis=0, ddof=1)


def _varp(*args):
    """VARP → 总体方差。"""
    arr = np.array([pd.to_numeric(a, errors='coerce').values
                     if isinstance(a, pd.Series) else a for a in args])
    return np.nanvar(arr, axis=0, ddof=0)


def _large(arr, k):
    """LARGE → 返回第 k 个最大值。"""
    arr = pd.to_numeric(arr, errors='coerce').values
    k = int(k)
    # 返回标量
    sorted_arr = np.sort(arr[~np.isnan(arr)])
    if k <= 0 or k > len(sorted_arr):
        return np.nan
    return sorted_arr[-k]


def _small(arr, k):
    """SMALL → 返回第 k 个最小值。"""
    arr = pd.to_numeric(arr, errors='coerce').values
    k = int(k)
    sorted_arr = np.sort(arr[~np.isnan(arr)])
    if k <= 0 or k > len(sorted_arr):
        return np.nan
    return sorted_arr[k - 1]


def _rank(value, ref, order=0):
    """RANK → 返回数值在数组中的排名。order: 0=降序（默认），非0=升序。"""
    val = pd.to_numeric(value, errors='coerce')
    arr = pd.to_numeric(ref, errors='coerce').values
    # 对每一行计算排名
    if isinstance(val, pd.Series):
        result = []
        for v in val:
            if pd.isna(v):
                result.append(np.nan)
            else:
                clean = arr[~np.isnan(arr)]
                if order == 0:
                    result.append((clean > v).sum() + 1)
                else:
                    result.append((clean < v).sum() + 1)
        return pd.Series(result, index=val.index)
    else:
        clean = arr[~np.isnan(arr)]
        if order == 0:
            return (clean > val).sum() + 1
        else:
            return (clean < val).sum() + 1


def _mode(*args):
    """MODE → 返回出现最频繁的值。"""
    arr = np.concatenate([a.astype(str).values if isinstance(a, pd.Series) else [str(a)]
                          for a in args])
    if len(arr) == 0:
        return ''
    unique, counts = np.unique(arr, return_counts=True)
    return unique[np.argmax(counts)]


# ==================== Excel 函数注册表 ====================
_EXCEL_FUNC_REGISTRY: dict[str, tuple[callable, int, int | None]] = {
    # --- 日期时间 ---
    'YEAR':      (lambda s: pd.to_datetime(s, errors='coerce').dt.year, 1, 1),
    'MONTH':     (lambda s: pd.to_datetime(s, errors='coerce').dt.month, 1, 1),
    'QUARTER':   (lambda s: pd.to_datetime(s, errors='coerce').dt.quarter, 1, 1),
    'DAY':       (lambda s: pd.to_datetime(s, errors='coerce').dt.day, 1, 1),
    'HOUR':      (lambda s: pd.to_datetime(s, errors='coerce').dt.hour, 1, 1),
    'MINUTE':    (lambda s: pd.to_datetime(s, errors='coerce').dt.minute, 1, 1),
    'SECOND':    (lambda s: pd.to_datetime(s, errors='coerce').dt.second, 1, 1),
    'WEEKDAY':   (lambda s: pd.to_datetime(s, errors='coerce').dt.dayofweek + 1, 1, 1),
    'WEEKNUM':   (lambda s, rt=2: _weeknum(s, rt), 1, 2),
    'DATEDIF':   (lambda start, end, unit: _datedif(start, end, unit), 3, 3),
    'DATE':      (lambda y, m, d: pd.to_datetime({'year': y, 'month': m, 'day': d}), 3, 3),
    'TODAY':     (lambda: pd.Timestamp.now().normalize(), 0, 0),
    'NOW':       (lambda: pd.Timestamp.now(), 0, 0),
    'EDATE':     (_edate, 2, 2),
    'EOMONTH':   (_eomonth, 2, 2),
    'TIME':      (_time, 3, 3),
    'YEARFRAC':  (_yearfrac, 2, 3),
    'ISOWEEKNUM': (_isoweeknum, 1, 1),

    # --- 逻辑 ---
    'IF':        (lambda cond, a, b: np.where(cond, a, b), 3, 3),
    'IFS':       (_ifs, 2, None),
    'AND':       (lambda *args: np.logical_and.reduce(args), 1, None),
    'OR':        (lambda *args: np.logical_or.reduce(args), 1, None),
    'NOT':       (lambda x: ~(x.astype(bool)), 1, 1),
    'IFERROR':   (lambda val, fallback: val.where(~val.isna() & ~val.astype(str).str.contains('\\[公式错误\\]', na=False), fallback), 2, 2),
    'TRUE':      (lambda: True, 0, 0),
    'FALSE':     (lambda: False, 0, 0),
    'XOR':       (_xor, 2, 2),
    'SWITCH':    (_switch, 3, None),

    # --- 数学 ---
    'ROUND':     (lambda s, n=0: s.round(n), 1, 2),
    'ROUNDUP':   (lambda s, n=0: np.ceil(s * 10**n) / 10**n, 1, 2),
    'ROUNDDOWN': (lambda s, n=0: np.floor(s * 10**n) / 10**n, 1, 2),
    'INT':       (lambda s: s.astype(float).astype(int), 1, 1),
    'ABS':       (lambda s: s.abs(), 1, 1),
    'MOD':       (lambda a, b: a % b, 2, 2),
    'SQRT':      (lambda s: np.sqrt(s), 1, 1),
    'POWER':     (lambda base, exp: np.power(base, exp), 2, 2),
    'SUM':       (lambda *args: sum(args), 1, None),
    'AVERAGE':   (lambda *args: sum(args) / len(args), 1, None),
    'COUNT':     (lambda *args: sum(1 for a in args), 1, None),
    'MAX':       (lambda *args: np.maximum.reduce(args), 1, None),
    'MIN':       (lambda *args: np.minimum.reduce(args), 1, None),
    'CEILING':   (_ceiling, 1, 2),
    'FLOOR':     (_floor_func, 1, 2),
    'LN':        (_ln, 1, 1),
    'LOG':       (_log_func, 1, 2),
    'EXP':       (_exp_func, 1, 1),
    'EVEN':      (_even, 1, 1),
    'ODD':       (_odd, 1, 1),
    'TRUNC':     (_trunc, 1, 2),
    'PI':        (_pi, 0, 0),
    'RADIANS':   (_radians, 1, 1),
    'DEGREES':   (_degrees, 1, 1),
    'SIGN':      (_sign, 1, 1),
    'FACT':      (_fact, 1, 1),
    'PRODUCT':   (_product, 1, None),
    'QUOTIENT':  (_quotient, 2, 2),

    # --- 文本 ---
    'LEFT':      (lambda s, n=1: s.astype(str).str[:n], 1, 2),
    'RIGHT':     (lambda s, n=1: s.astype(str).str[-n:], 1, 2),
    'MID':       (lambda s, start, n: s.astype(str).str[start - 1:start - 1 + n], 3, 3),
    'LEN':       (lambda s: s.astype(str).str.len(), 1, 1),
    'UPPER':     (lambda s: s.astype(str).str.upper(), 1, 1),
    'LOWER':     (lambda s: s.astype(str).str.lower(), 1, 1),
    'TRIM':      (lambda s: s.astype(str).str.strip(), 1, 1),
    'CONCAT':    (_concat, 1, None),
    'CONCATENATE': (_concat, 1, None),
    'TEXTJOIN':  (_text_join, 2, None),
    'REPLACE':   (_replace_text, 3, 3),
    'SUBSTITUTE': (_substitute, 3, 4),
    'FIND':      (_find, 2, 3),
    'TEXT':      (_text, 2, 2),
    'PROPER':    (_proper, 1, 1),
    'SEARCH':    (_search, 2, 3),
    'EXACT':     (_exact, 2, 2),
    'REPT':      (_rept, 2, 2),
    'VALUE':     (_value, 1, 1),
    'FIXED':     (_fixed, 1, 3),
    'CHAR':      (_char, 1, 1),
    'CODE':      (_code, 1, 1),
    'CLEAN':     (_clean, 1, 1),

    # --- 条件统计 ---
    'COUNTIF':   (_countif, 2, 2),
    'SUMIF':     (_sumif, 2, 3),
    'AVERAGEIF': (_averageif, 2, 3),

    # --- 统计 ---
    'MEDIAN':    (_median, 1, None),
    'STDEV':     (_stdev, 1, None),
    'STDEVP':    (_stdevp, 1, None),
    'VAR':       (_var, 1, None),
    'VARP':      (_varp, 1, None),
    'LARGE':     (_large, 2, 2),
    'SMALL':     (_small, 2, 2),
    'RANK':      (_rank, 2, 3),
    'MODE':      (_mode, 1, None),

    # --- 类型判断 ---
    'ISNUMBER':  (_isnumber, 1, 1),
    'ISTEXT':    (_istext, 1, 1),
    'ISBLANK':   (_isblank, 1, 1),
    'ISNA':      (lambda s: s.isna(), 1, 1),
}


def _weeknum(s, return_type=2):
    """WEEKNUM 实现。

    Args:
        s: 日期 Series
        return_type: 1=周日开始, 2=周一开始（默认，ISO 标准）
    """
    s = pd.to_datetime(s, errors='coerce')
    # 将 return_type 转为 int（处理标量或 Series）
    if isinstance(return_type, pd.Series):
        return_type = return_type.iloc[0] if len(return_type) > 0 else 2
    if isinstance(return_type, (int, float, np.integer, np.floating)):
        rt = int(return_type)
    else:
        rt = 2
    if rt == 1:
        # 周日开始：%U 从 0 计数，+1 对齐 Excel 从 1 开始
        return s.dt.strftime('%U').astype(int) + 1
    else:
        # 周一开始（ISO 8601）
        return s.dt.isocalendar().week.astype(int)


def _datedif(start, end, unit):
    """DATEDIF 实现（单位: "Y"/"M"/"D"）。"""
    start = pd.to_datetime(start, errors='coerce')
    end = pd.to_datetime(end, errors='coerce')
    diff = end - start
    unit = str(unit).upper().strip('"\'')
    if unit == 'Y':
        return (diff.dt.days / 365.25).astype(int)
    elif unit == 'M':
        return (diff.dt.days / 30.44).astype(int)
    elif unit == 'D':
        return diff.dt.days
    return diff.dt.days


# ==================== 公式解析与求值 ====================

def _tokenize_excel_formula(expr: str) -> list[tuple[str, str]]:
    """将 Excel 公式拆分为 token 列表。

    每项为 (type, value)，type 包括:
      'func'   - 函数名（后跟 '('）
      'lparen' - '('
      'rparen' - ')'
      'comma'  - ','
      'col'    - 列引用（会被替换）
      'literal' - 字符串字面量 'xxx' 或 "xxx"
      'number' - 数字
      'op'     - 运算符 + - * / > < = & 等
      'ident'  - 其他标识符
    """
    tokens = []
    i = 0
    n = len(expr)

    while i < n:
        ch = expr[i]

        # 空白
        if ch.isspace():
            i += 1
            continue

        # 字符串字面量
        if ch in ("'", '"'):
            quote = ch
            j = i + 1
            while j < n and expr[j] != quote:
                if expr[j] == '\\':
                    j += 1
                j += 1
            tokens.append(('literal', expr[i:j + 1]))
            i = j + 1
            continue

        # 数字
        if ch.isdigit() or (ch == '.' and i + 1 < n and expr[i + 1].isdigit()):
            j = i
            while j < n and (expr[j].isdigit() or expr[j] == '.'):
                j += 1
            tokens.append(('number', expr[i:j]))
            i = j
            continue

        # 括号 / 逗号
        if ch == '(':
            # 前一个 token 是标识符 → 函数名
            if tokens and tokens[-1][0] == 'ident':
                prev_val = tokens.pop()[1]
                if prev_val.upper() in _EXCEL_FUNC_REGISTRY:
                    tokens.append(('func', prev_val.upper()))
                else:
                    # 不是注册的函数，还原为 ident
                    tokens.append(('ident', prev_val))
            tokens.append(('lparen', '('))
            i += 1
            continue
        if ch == ')':
            tokens.append(('rparen', ')'))
            i += 1
            continue
        if ch == ',':
            tokens.append(('comma', ','))
            i += 1
            continue

        # 运算符
        if ch in '+-*/><=&|^%':
            if i + 1 < n and expr[i:i + 2] in ('>=', '<=', '!=', '=='):
                tokens.append(('op', expr[i:i + 2]))
                i += 2
            else:
                tokens.append(('op', ch))
                i += 1
            continue

        # 标识符（列名、函数名、关键字）
        j = i
        while j < n and not expr[j].isspace() and expr[j] not in '(),\'"+-*/><=&|^%':
            j += 1
        ident = expr[i:j]
        # 如果紧接着是 (, 会作为函数名处理
        tokens.append(('ident', ident))
        i = j

    return tokens


def _convert_tokens_to_python(tokens: list[tuple[str, str]],
                               col_map: dict[str, str]) -> str:
    """将 Excel token 列表转换为 Python 表达式。

    Args:
        tokens: token 列表
        col_map: {原始列名: 安全 DF 列名} 映射（实际已被替换）

    Returns:
        Python 表达式字符串
    """
    parts = []
    for ttype, tval in tokens:
        if ttype == 'func':
            # Excel 函数 → Python 函数引用（通过 _EF 命名空间访问）
            parts.append(f"_EF['{tval}']")
        elif ttype == 'lparen':
            parts.append('(')
        elif ttype == 'rparen':
            parts.append(')')
        elif ttype == 'comma':
            parts.append(',')
        elif ttype == 'op':
            parts.append(tval)
        elif ttype == 'number':
            parts.append(tval)
        elif ttype == 'literal':
            parts.append(tval)
        elif ttype == 'ident':
            # 标识符可能是列名 → 替换为 _df[...] 访问
            # 先检查是否匹配任一列名
            if tval in col_map:
                parts.append(f"_df['{tval}']")
            else:
                parts.append(tval)
        else:
            parts.append(tval)

    return ' '.join(parts)


def _eval_formula(expr: str, df: pd.DataFrame) -> pd.Series:
    """对 DataFrame 求值单个 Excel 公式。

    算法:
    1. 解析 token
    2. 识别列名（通过 _find_col_refs_in_tokens 辅助匹配 df 的列）
    3. 转换成 Python 表达式
    4. 在受控命名空间中 eval

    Args:
        expr: 规范化后的 Excel 公式（已去等号、已替换中文标点）
        df: 数据 DataFrame

    Returns:
        计算结果 Series
    """
    # 构建列名匹配表
    df_cols = df.columns.tolist()
    col_map = {c: c for c in df_cols}  # 保持原始列名不变

    # 尝试简单情况：纯算术表达式 → 直接用 df.eval
    if not _has_excel_func(expr):
        safe_expr, safe_map, _ = _replace_column_refs(expr, df_cols)
        rename_map = {v: k for k, v in safe_map.items()}
        temp_df = df.rename(columns=rename_map)
        try:
            return temp_df.eval(safe_expr)
        except Exception:
            pass

    # 复杂情况：有 Excel 函数 → tokenize + convert
    tokens = _tokenize_excel_formula(expr)

    # 将 tokens 中未识别的 ident 尝试匹配列名
    col_set = set(df_cols)
    for idx, (ttype, tval) in enumerate(tokens):
        if ttype == 'ident' and tval in col_set:
            tokens[idx] = ('col', tval)
        elif ttype == 'ident':
            # 尝试模糊匹配
            for col in df_cols:
                if col in tval or tval in col:
                    # 不自动替换，保持原样（可能是变量名）
                    pass

    # 构建 Python 表达式
    py_expr = _build_python_expr_from_tokens(tokens, df_cols)

    # 构建受控的 eval 命名空间
    namespace = {
        '_df': df,
        '_EF': _build_func_wrappers(),
        'np': np,
        'pd': pd,
    }

    try:
        result = eval(py_expr, {"__builtins__": {}}, namespace)
        return _ensure_series(result, df.index)
    except Exception as e:
        raise ValueError(f"公式求值失败: {e}")


def _has_excel_func(expr: str) -> bool:
    """检查表达式是否包含 Excel 函数调用。"""
    for func_name in _EXCEL_FUNC_REGISTRY:
        pattern = r'\b' + func_name + r'\s*\('
        if re.search(pattern, expr, re.IGNORECASE):
            return True
    return False


def _build_func_wrappers() -> dict:
    """构建函数包装器：从注册表中提取纯函数部分。

    返回 {FUNC_NAME: callable}，但包装了参数处理逻辑。
    """
    wrappers = {}
    for name, (func, min_args, max_args) in _EXCEL_FUNC_REGISTRY.items():
        wrappers[name] = func
    return wrappers


def _build_python_expr_from_tokens(tokens: list[tuple[str, str]],
                                    df_cols: list[str]) -> str:
    """将 token 列表转换为可执行的 Python 表达式字符串。

    转换规则:
    - func(token)  → _EF['FUNC_NAME'](
    - col(token)   → _df['col_name']
    - ident(token) → token（可能是 True/False/None）
    - 其余保持原样
    """
    parts = []
    col_set = set(df_cols)

    for ttype, tval in tokens:
        if ttype == 'func':
            # 函数引用，不追加 '(' — 由紧跟的 lparen 处理
            parts.append(f"_EF['{tval}']")
        elif ttype == 'lparen':
            parts.append('(')
        elif ttype == 'rparen':
            parts.append(')')
        elif ttype == 'comma':
            parts.append(',')
        elif ttype == 'col':
            parts.append(f"_df['{tval}']")
        elif ttype == 'ident':
            upper = tval.upper()
            if upper in ('TRUE', 'FALSE', 'NONE'):
                parts.append(upper == 'TRUE' and 'True' or (upper == 'FALSE' and 'False' or 'None'))
            elif _is_number(tval):
                parts.append(tval)
            elif tval in col_set:
                parts.append(f"_df['{tval}']")
            else:
                parts.append(tval)
        elif ttype == 'number':
            parts.append(tval)
        elif ttype == 'literal':
            parts.append(tval)
        elif ttype == 'op':
            parts.append(' ' + tval + ' ')
        else:
            parts.append(tval)

    return ''.join(parts)


def _is_number(s: str) -> bool:
    try:
        float(s)
        return True
    except ValueError:
        return False


def _ensure_series(result, index) -> pd.Series:
    """确保结果是 pandas Series（标量值广播为 Series）。"""
    if isinstance(result, pd.Series):
        return result
    if isinstance(result, pd.DataFrame):
        return result.iloc[:, 0]
    if np.isscalar(result):
        return pd.Series(result, index=index)
    return pd.Series(result, index=index)


# ==================== 公式列入口 ====================

def eval_formula_columns(df: pd.DataFrame, columns: list) -> pd.DataFrame:
    """对 DataFrame 应用所有公式列。

    Args:
        df: 数据 DataFrame
        columns: FieldColumn 对象列表

    Returns:
        增加了计算列的 DataFrame
    """
    for col in columns:
        if not _is_formula(col):
            continue
        if not col.formula_expression.strip():
            continue

        expr = _normalize_expr(col.formula_expression)
        display = col.display_name or '计算列'

        try:
            result = _eval_formula(expr, df)
            df[display] = result
        except Exception as e:
            logger.warning(f"[FormulaEngine] 公式计算失败 '{display}': {e}")
            df[display] = f"[公式错误]"

    return df


def _is_formula(col) -> bool:
    """检查 FieldColumn 是否为公式类型。"""
    if hasattr(col, 'computation_type'):
        return col.computation_type == 'formula'
    return False


# ==================== 汇总行计算 ====================

def compute_summary_row(df: pd.DataFrame, columns: list) -> dict:
    """计算汇总行。

    对每个可见列的数值列计算 SUM，文本列留空。
    如果列定义了 aggregate_func，优先使用对应的聚合函数。
    """
    summary = {}
    for col in columns:
        if hasattr(col, 'visible') and not col.visible:
            continue
        name = col.display_name if hasattr(col, 'display_name') else col
        if name not in df.columns:
            continue

        series = df[name]
        agg_func = getattr(col, 'aggregate_func', '') if hasattr(col, 'aggregate_func') else ''

        if agg_func:
            summary[name] = _apply_agg(series, agg_func)
        elif pd.api.types.is_numeric_dtype(series):
            summary[name] = series.sum()
        else:
            summary[name] = ""

    return summary


def _apply_agg(series, agg_func: str):
    """对 Series 应用聚合函数。"""
    func = agg_func.upper().strip()
    try:
        if func == 'SUM':
            return series.sum()
        elif func == 'AVG':
            return series.mean()
        elif func == 'COUNT':
            return series.count()
        elif func == 'MAX':
            return series.max()
        elif func == 'MIN':
            return series.min()
    except Exception:
        return ""
    return ""


# ==================== 跨页准确汇总（SQL 层）====================

def build_summary_sql(table_name: str, columns: list, db_columns: list[str]) -> str:
    """生成用于汇总查询的 SQL 片段。"""
    agg_parts = []
    for col in columns:
        if hasattr(col, 'visible') and not col.visible:
            continue
        name = col.display_name if hasattr(col, 'display_name') else str(col)
        if name not in db_columns:
            continue
        agg_parts.append(f"SUM(`{name}`) AS `{name}`")

    if not agg_parts:
        return ""
    return f"SELECT {', '.join(agg_parts)} FROM `{table_name}`"


# ==================== Excel 公式 → MySQL SQL 翻译 ====================

# Excel 函数 → MySQL 函数映射（名称不同或参数格式不同才需要映射；同名函数无需列出）
_EXCEL_TO_MYSQL_FUNC: dict[str, str] = {
    'LEN': 'CHAR_LENGTH',
    'MID': 'SUBSTRING',
    'INT': 'FLOOR',
    'CONCATENATE': 'CONCAT',
    'TODAY': 'CURDATE',
    'NOW': 'NOW',
    'ABS': 'ABS',
    'REPT': 'REPEAT',
    'CEILING': 'CEILING',
    'FLOOR': 'FLOOR',
    'LN': 'LN',
    'LOG': 'LOG',
    'EXP': 'EXP',
    'TRUNC': 'TRUNCATE',
}

# 无 MySQL 等价函数的 Excel 函数集合 —— 包含这些函数的公式将退回 pandas 计算
_UNTRANSLATABLE_FUNCS: set[str] = {
    'TEXTJOIN', 'IFS', 'IFERROR',
    'ISNUMBER', 'ISTEXT', 'ISBLANK', 'ISNA',
    'FIND', 'REPLACE', 'SUBSTITUTE',
    'DATEDIF',
    'ROUNDUP', 'ROUNDDOWN',
    'AND', 'OR',
    'WEEKDAY',
    'PROPER', 'SEARCH', 'EXACT',
    'COUNTIF', 'SUMIF', 'AVERAGEIF',
    'EDATE', 'EOMONTH',
    'TIME', 'YEARFRAC', 'ISOWEEKNUM',
    'TRUE', 'FALSE', 'XOR', 'SWITCH',
    'EVEN', 'ODD',
    'FACT', 'PRODUCT', 'QUOTIENT',
    'VALUE', 'FIXED', 'CHAR', 'CODE', 'CLEAN',
    'MEDIAN', 'STDEV', 'STDEVP', 'VAR', 'VARP',
    'LARGE', 'SMALL', 'RANK', 'MODE',
}


def _translate_weeknum(expr: str) -> str:
    """将 Excel WEEKNUM 翻译为 MySQL WEEK。

    WEEKNUM(date)       → WEEK(date, 3)   (默认 return_type=2: 周一开始，含 1/1 的周为第 1 周)
    WEEKNUM(date, 1)    → WEEK(date, 2)   (周日开始)
    WEEKNUM(date, 2)    → WEEK(date, 3)   (周一开始)
    """
    def _replace(m):
        args_str = m.group(1).strip()
        if ',' in args_str:
            # 有第二个参数：找到第一个不在括号内的逗号
            depth = 0
            split_pos = -1
            for i, ch in enumerate(args_str):
                if ch == '(':
                    depth += 1
                elif ch == ')':
                    depth -= 1
                elif ch == ',' and depth == 0:
                    split_pos = i
                    break
            if split_pos > 0:
                date_part = args_str[:split_pos].strip()
                mode_part = args_str[split_pos + 1:].strip()
                if mode_part == '1':
                    return f'WEEK({date_part}, 2)'
                else:
                    return f'WEEK({date_part}, 3)'
        return f'WEEK({args_str}, 3)'

    return re.sub(r'WEEKNUM\s*\(', '__WEEKNUM_START__(', expr, flags=re.IGNORECASE)


# Excel → MySQL 日期格式转换映射（不含 mm，因其含义取决于上下文）
_EXCEL_TO_MYSQL_DATE_FORMAT = [
    ('yyyy', '%Y'), ('yy', '%y'),
    ('MMMM', '%M'), ('MMM', '%b'), ('MM', '%m'),
    ('dddd', '%W'), ('ddd', '%a'), ('dd', '%d'),
    ('HH', '%H'), ('hh', '%h'),
    ('ss', '%S'),
    ('AM/PM', '%p'), ('A/P', '%p'),
]


def _excel_date_format_to_mysql(excel_fmt: str) -> str:
    """将 Excel 日期格式字符串转换为 MySQL DATE_FORMAT 格式字符串。

    Excel 中 mm 含义取决于上下文：
      - 与 H/h/s 同时出现时 → 分钟 → MySQL %i
      - 否则 → 月份 → MySQL %m
    """
    result = excel_fmt
    for excel_pat, mysql_pat in _EXCEL_TO_MYSQL_DATE_FORMAT:
        result = result.replace(excel_pat, mysql_pat)

    # 在上下文敏感的映射之前，先完成 MM → %m，再根据格式中是否含时间成分来决定 mm 的含义
    has_time_context = bool(re.search(r'[Hhs]', excel_fmt))
    if has_time_context:
        result = result.replace('mm', '%i')   # 分钟
    else:
        result = result.replace('mm', '%m')   # 月份（纯日期格式）
    return result


def _has_date_format_patterns(fmt: str) -> bool:
    """判断格式字符串是否包含日期格式模式（y, M, d, H, h, s 等）。"""
    date_indicators = {'y', 'M', 'd', 'H', 'h', 's', 'A', 'P', '上午', '下午'}
    return any(c in fmt for c in date_indicators)


def _split_func_args(args_str: str, count: int) -> list[str]:
    """按顶层逗号分割函数参数，忽略嵌套括号内的逗号。"""
    parts = []
    depth = 0
    start = 0
    for i, ch in enumerate(args_str):
        if ch == '(':
            depth += 1
        elif ch == ')':
            depth -= 1
        elif ch == ',' and depth == 0:
            parts.append(args_str[start:i].strip())
            start = i + 1
            if len(parts) >= count - 1:
                break
    parts.append(args_str[start:].strip())
    return parts


def _translate_date_to_sql(expr: str) -> str:
    """将 Excel DATE(year, month, day) 翻译为 MySQL STR_TO_DATE 表达式。"""
    def _replace(m):
        args_str = m.group(1).strip()
        parts = _split_func_args(args_str, 3)
        if len(parts) < 3:
            return m.group(0)  # 无法解析，保留原样
        y, m_name, d = parts[0], parts[1], parts[2]
        return (
            f"STR_TO_DATE(CONCAT({y}, '-', LPAD({m_name}, 2, '0'), '-', "
            f"LPAD({d}, 2, '0')), '%Y-%m-%d')"
        )

    # 使用手动字符级匹配来正确处理嵌套括号
    result = []
    i = 0
    n = len(expr)
    while i < n:
        # 查找 DATE(
        if i + 4 < n and expr[i:i+4].upper() == 'DATE':
            j = i + 4
            # 跳过空格
            while j < n and expr[j] == ' ':
                j += 1
            if j < n and expr[j] == '(':
                # 找到匹配的右括号
                depth = 1
                k = j + 1
                while k < n and depth > 0:
                    if expr[k] == '(':
                        depth += 1
                    elif expr[k] == ')':
                        depth -= 1
                    k += 1
                if depth == 0:
                    args_str = expr[j+1:k-1].strip()
                    parts = _split_func_args(args_str, 3)
                    if len(parts) >= 3:
                        y, m_name, d = parts[0], parts[1], parts[2]
                        result.append(
                            f"STR_TO_DATE(CONCAT({y}, '-', LPAD({m_name}, 2, '0'), '-', "
                            f"LPAD({d}, 2, '0')), '%Y-%m-%d')"
                        )
                        i = k
                        continue
            # 未匹配到完整的 DATE(...)，保留原字符
            result.append(expr[i])
            i += 1
        else:
            result.append(expr[i])
            i += 1

    return ''.join(result)


def _translate_text_to_sql(expr: str) -> str:
    """将 Excel TEXT(value, format_string) 翻译为 MySQL DATE_FORMAT 或 CAST。

    对于日期格式 → DATE_FORMAT(value, mysql_format)
    对于数值格式 → CAST(value AS CHAR)
    """
    result = []
    i = 0
    n = len(expr)
    while i < n:
        # 查找 TEXT(
        if i + 4 < n and expr[i:i+4].upper() == 'TEXT':
            j = i + 4
            while j < n and expr[j] == ' ':
                j += 1
            if j < n and expr[j] == '(':
                depth = 1
                k = j + 1
                while k < n and depth > 0:
                    if expr[k] == '(':
                        depth += 1
                    elif expr[k] == ')':
                        depth -= 1
                    k += 1
                if depth == 0:
                    args_str = expr[j+1:k-1].strip()
                    parts = _split_func_args(args_str, 2)
                    if len(parts) >= 2:
                        value_expr = parts[0]
                        fmt_str = parts[1].strip()

                        # 去除外层引号
                        if (fmt_str.startswith('"') and fmt_str.endswith('"')) or \
                           (fmt_str.startswith("'") and fmt_str.endswith("'")):
                            fmt_str = fmt_str[1:-1]

                        if _has_date_format_patterns(fmt_str):
                            mysql_fmt = _excel_date_format_to_mysql(fmt_str)
                            result.append(
                                f"DATE_FORMAT({value_expr}, '{mysql_fmt}')"
                            )
                        else:
                            result.append(f"CAST({value_expr} AS CHAR)")
                        i = k
                        continue
            result.append(expr[i])
            i += 1
        else:
            result.append(expr[i])
            i += 1

    return ''.join(result)


def translate_formula_to_sql(expr: str, column_names: list[str],
                             table_alias: str = '_base') -> str | None:
    """将 Excel 公式表达式翻译为 MySQL SQL 表达式。

    列引用替换为 `{alias}`.`列名` 形式，Excel 函数映射为 MySQL 等价函数。
    若公式包含 MySQL 不支持的函数，返回 None（由调用方退回 pandas 计算）。

    Args:
        expr: 原始公式表达式（如 '=单价*数量' 或 '=IF(金额>1000, "大额", "小额")'）
        column_names: 内层查询的列名列表（用于匹配并替换列引用）
        table_alias: 子查询别名（默认 '_base'）

    Returns:
        MySQL SQL 表达式字符串，或 None（表示无法翻译）
    """
    expr = _normalize_expr(expr)
    if not expr.strip():
        return 'NULL'

    # 检查公式是否被截断（包含省略号等异常 Unicode 字符）
    _TRUNCATION_INDICATORS = {'…', '‥', '．'}  # …, ‥, ．
    for ch in _TRUNCATION_INDICATORS:
        if ch in expr:
            logger.warning(f"[FormulaSQL] 公式包含截断标记 U+{ord(ch):04X}，退回 pandas 计算")
            return None

    # 检查括号是否成对（防止截断或损毁的公式生成无效 SQL）
    if expr.count('(') != expr.count(')'):
        logger.warning(f"[FormulaSQL] 公式括号不匹配 (左={expr.count('(')} 右={expr.count(')')})，退回 pandas 计算")
        return None

    # 检查是否包含不可翻译的 Excel 函数
    for func in _UNTRANSLATABLE_FUNCS:
        if re.search(r'\b' + func + r'\s*\(', expr, re.IGNORECASE):
            logger.info(f"[FormulaSQL] 公式包含不支持的函数 '{func}'，退回 pandas 计算")
            return None

    # 先处理字符串字面量：保护起来避免列名误匹配
    literals = {}

    def _save_literal(m):
        key = f'\x00L{len(literals)}\x00'
        literals[key] = m.group(0)
        return key

    expr = re.sub(r"'[^']*'", _save_literal, expr)
    expr = re.sub(r'"[^"]*"', _save_literal, expr)

    # 特殊处理 WEEKNUM → MySQL WEEK
    expr = _translate_weeknum(expr)
    # 还原 WEEKNUM 占位符（_translate_weeknum 替换了函数名开头，这里补全参数处理）
    # 简化处理：直接匹配完整的 WEEKNUM(...) 调用
    if '__WEEKNUM_START__' in expr:
        expr = _finish_weeknum_translation(expr)

    # 按列名长度降序替换列引用（避免短列名错误匹配长列名的一部分）
    sorted_cols = sorted(column_names, key=len, reverse=True)
    for col in sorted_cols:
        if col in expr:
            quoted = f"`{col.replace('`', '``')}`"
            expr = expr.replace(col, f"{table_alias}.{quoted}")

    # 恢复字面量
    for key, val in literals.items():
        expr = expr.replace(key, val)

    # 特殊处理 DATE → MySQL STR_TO_DATE
    expr = _translate_date_to_sql(expr)
    # 特殊处理 TEXT → MySQL DATE_FORMAT / CAST
    expr = _translate_text_to_sql(expr)

    # 翻译 Excel 函数 → MySQL 函数
    expr = _translate_functions(expr)

    # 翻译后再次检查括号是否成对（防止翻译过程引入问题）
    if expr.count('(') != expr.count(')'):
        logger.warning(f"[FormulaSQL] 翻译后括号不匹配 (左={expr.count('(')} 右={expr.count(')')})，退回 pandas 计算")
        return None

    return expr


def _finish_weeknum_translation(expr: str) -> str:
    """完成 WEEKNUM → WEEK 的翻译（处理括号内的参数）。"""
    def _replace_full(m):
        args_str = m.group(1).strip()
        if ',' in args_str:
            depth = 0
            split_pos = -1
            for i, ch in enumerate(args_str):
                if ch == '(':
                    depth += 1
                elif ch == ')':
                    depth -= 1
                elif ch == ',' and depth == 0:
                    split_pos = i
                    break
            if split_pos > 0:
                date_part = args_str[:split_pos].strip()
                mode_part = args_str[split_pos + 1:].strip()
                if mode_part == '1':
                    return f'WEEK({date_part}, 2)'
                else:
                    return f'WEEK({date_part}, 3)'
        return f'WEEK({args_str}, 3)'

    return re.sub(r'__WEEKNUM_START__\s*\(([^()]*(?:\([^()]*\)[^()]*)*)\)',
                  _replace_full, expr)


def _translate_functions(expr: str) -> str:
    """将表达式中的 Excel 函数名替换为 MySQL 等价函数名。"""
    for excel_func, mysql_func in _EXCEL_TO_MYSQL_FUNC.items():
        pattern = r'\b' + excel_func + r'\s*\('
        if re.search(pattern, expr, re.IGNORECASE):

            def _replace(m, mf=mysql_func):
                return mf + m.group(0)[len(excel_func):]

            expr = re.sub(pattern, _replace, expr, flags=re.IGNORECASE)
    return expr
