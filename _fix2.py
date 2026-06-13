import pathlib

file = pathlib.Path("D:/Workspace/Project_001_数据批量文档处理工具/custom_report.py")
content = file.read_text("utf-8")

# 构建匹配文本，含 \r\n
old1 = (
    "        try:\r\n"
    '            result1 = self._db.execute("SHOW TABLES LIKE \'对象-%\'") or []\r\n'
    '            result2 = self._db.execute("SHOW TABLES LIKE \'sr_%\'") or []\r\n'
    "            crm_tables = result1 + result2\r\n"
    "        except Exception as e:\r\n"
    '            self._show_placeholder("查询失败", str(e)[:80])\r\n'
    "            return\r\n"
    "\r\n"
    "        # 1. CRM 对象表\r\n"
    "        for row in crm_tables:\r\n"
    '            table_name = list(row.values())[0] if row else ""\r\n'
    "            if not table_name:\r\n"
    "                continue\r\n"
    "            self._add_table_item(table_name, 'crm')\r\n"
    "\r\n"
    "        # 2. Excel 导入表\r\n"
    "        try:\r\n"
    "            ex_tables = self._db.execute(\"SHOW TABLES LIKE 'ex_%'\") or []\r\n"
    "        except Exception:\r\n"
    "            ex_tables = []\r\n"
    "\r\n"
    "        for row in ex_tables:\r\n"
    '            table_name = list(row.values())[0] if row else ""\r\n'
    "            if not table_name:\r\n"
    "                continue\r\n"
    "            self._add_table_item(table_name, 'excel')\r\n"
    "\r\n"
    "        # 3. 其他 MySQL 表（仅在显式请求时加载）\r\n"
    "        if include_mysql_tables:\r\n"
    "            managed_prefixes = ('对象-', 'sr_', 'ex_', 'cr_', '报表-')\r\n"
)

new1 = (
    "        try:\r\n"
    "            crm_tables = self._db.execute(\"SHOW TABLES LIKE '对象-%'\") or []\r\n"
    "        except Exception as e:\r\n"
    '            self._show_placeholder("查询失败", str(e)[:80])\r\n'
    "            return\r\n"
    "\r\n"
    "        # 1. 对象表（仅显示 对象-XXX）\r\n"
    "        for row in crm_tables:\r\n"
    '            table_name = list(row.values())[0] if row else ""\r\n'
    "            if not table_name:\r\n"
    "                continue\r\n"
    "            self._add_table_item(table_name, 'crm')\r\n"
    "\r\n"
    "        # 2. (sr_% / ex_% / 普通MySQL表等不再显示)\r\n"
    "\r\n"
    "        # 3. (已根据用户要求隐藏，不显示其他MySQL表)\r\n"
    "        if include_mysql_tables:\r\n"
)

if old1 in content:
    content = content.replace(old1, new1, 1)
    print("替换1 成功")
else:
    print("替换1 失败")
    # 精确查找每个片段来排查
    idx = content.find("result1 = self._db.execute")
    if idx >= 0:
        piece = content[idx:idx+len(old1)]
        for i, (a, b) in enumerate(zip(old1, piece)):
            if a != b:
                print(f"第{i}个字符不同: expect({repr(a)}) vs actual({repr(b)})")
                print(f"期望后续: {repr(old1[i:i+50])}")
                print(f"实际后续: {repr(piece[i:i+50])}")
                break

old2 = (
    "            managed_prefixes = ('对象-', 'sr_', 'ex_', 'cr_', '报表-')\r\n"
    "            try:\r\n"
    '                all_tables = self._db.execute("SHOW TABLES") or []\r\n'
    "            except Exception:\r\n"
    "                all_tables = []\r\n"
    "\r\n"
    "            for row in all_tables:\r\n"
    '                table_name = list(row.values())[0] if row else ""\r\n'
    "                if not table_name:\r\n"
    "                    continue\r\n"
    "                if any(table_name.startswith(p) for p in managed_prefixes):\r\n"
    "                    continue\r\n"
    "                self._add_table_item(table_name, 'mysql')\r\n"
)

new2 = (
    "            # (已根据用户要求隐藏，不再显示普通MySQL表)\r\n"
    "            pass\r\n"
)

if old2 in content:
    content = content.replace(old2, new2, 1)
    print("替换2 成功")
else:
    print("替换2 失败")

file.write_text(content, "utf-8")
print("保存完成")
