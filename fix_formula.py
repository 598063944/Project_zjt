import re

with open('custom_report.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Add helper functions before Excel registry header
helper_code = """

def _left_text(s, n=1):
    s_str = s.astype(str)
    if isinstance(n, pd.Series):
        n_int = pd.to_numeric(n, errors='coerce').fillna(0).astype(int)
        return pd.Series([s_str.iloc[i][:n_int.iloc[i]] for i in range(len(s_str))], index=s.index)
    return s_str.str[:int(n)]


def _right_text(s, n=1):
    s_str = s.astype(str)
    if isinstance(n, pd.Series):
        n_int = pd.to_numeric(n, errors='coerce').fillna(0).astype(int)
        return pd.Series([s_str.iloc[i][-n_int.iloc[i]:] for i in range(len(s_str))], index=s.index)
    return s_str.str[-int(n):]


def _mid_text(s, start, n):
    s_str = s.astype(str)
    if isinstance(start, pd.Series) or isinstance(n, pd.Series):
        start_int = pd.to_numeric(start, errors='coerce').fillna(1).astype(int)
        n_int = pd.to_numeric(n, errors='coerce').fillna(0).astype(int)
        return pd.Series([s_str.iloc[i][start_int.iloc[i] - 1:start_int.iloc[i] - 1 + n_int.iloc[i]] for i in range(len(s_str))], index=s.index)
    return s_str.str[int(start) - 1:int(start) - 1 + int(n)]


"""

header = '# ==================== Excel 函数注册表 ===================='
content = content.replace(header, helper_code + header, 1)

# 2. Update LEFT/RIGHT/MID in registry
old_left = "'LEFT':      (lambda s, n=1: s.astype(str).str.slice(stop=n), 1, 2),"
new_left = "'LEFT':      (_left_text, 1, 2),"
content = content.replace(old_left, new_left, 1)

old_right = "'RIGHT':     (lambda s, n=1: s.astype(str).str.slice(start=-n), 1, 2),"
new_right = "'RIGHT':     (_right_text, 1, 2),"
content = content.replace(old_right, new_right, 1)

old_mid = "'MID':       (lambda s, start, n: s.astype(str).str.slice(start=start - 1, stop=start - 1 + n), 3, 3),"
new_mid = "'MID':       (_mid_text, 3, 3),"
content = content.replace(old_mid, new_mid, 1)

with open('custom_report.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("Patch applied successfully")
