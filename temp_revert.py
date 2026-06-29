import sys, py_compile
sys.stdout.reconfigure(encoding="utf-8")
PATH = "D:/Workspace/Project_001_数据批量文档处理工具/network.py"
with open(PATH, "r", encoding="utf-8") as f:
    lines = f.readlines()

# Current state: batch version at lines 537-563
# Revert to original row-by-row
# The original code is just the original lines 537-557 (before I changed them)
# I need to replace lines 536-563 (the batch version) with the original for loop

new_loop = [
    "                for row in rows:\n",
    "                    _id = str(row.get('_id', '')).strip()\n",
    "                    if not _id:\n",
    "                        skipped += 1\n",
    "                        continue\n",
    "                    if _id in seen_ids:\n",
    "                        skipped += 1\n",
    "                        continue\n",
    "                    seen_ids.add(_id)\n",
    "                    data_json = json.dumps(row, ensure_ascii=False)\n",
    "                    row_hash = hashlib.sha1(data_json.encode('utf-8')).hexdigest()\n",
    "                    cur.execute(\n",
    '                        f"INSERT INTO `{table}` (_id, data_json, _hash, cached_at) "\n',
    '                        f"VALUES (%s, %s, %s, NOW()) "\n',
    '                        f"ON DUPLICATE KEY UPDATE "\n',
    '                        f"data_json = IF(VALUES(`_hash`) != `_hash`, VALUES(data_json), data_json), "\n',
    '                        f"`_hash` = IF(VALUES(`_hash`) != `_hash`, VALUES(`_hash`), `_hash`), "\n',
    '                        f"cached_at = IF(VALUES(`_hash`) != `_hash`, NOW(), cached_at)",\n',
    "                        (_id, data_json, row_hash)\n",
    "                    )\n",
    "                    inserted += 1\n",
]

# Replace lines 536-563 (the batch version) with the original for loop
# The batch version had:
# L537: upsert_sql = (...)
# L545: batch = []
# L546-561: loop with batch.append and cur.executemany
# L562-563: if batch: cur.executemany
# Total: 28 lines (536-563 inclusive)

# Replace with 20 lines (the original for loop)
lines[536:564] = new_loop

with open(PATH, "w", encoding="utf-8") as f:
    f.writelines(lines)

# Verify
try:
    py_compile.compile(PATH, doraise=True)
    print("Reverted to original row-by-row. py_compile: OK")
except py_compile.PyCompileError as e:
    print(f"py_compile: FAILED - {e}")