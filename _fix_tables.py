import pathlib

file = pathlib.Path("D:/Workspace/Project_001_数据批量文档处理工具/custom_report.py")
content = file.read_text("utf-8")

old1 = (
    '        try:\n'
    '            result1 = self._db.execute("SHOW TABLES LIKE \'对象-%\'") or []\n'
    '            result2 = self._db.execute("SHOW TABLES LIKE \'sr_%\'") or []\n'
    '            crm_tables = result1 + result2\n'
    '        except Exception as e:\n'
    '            self._show_placeholder("查询失败", str(e)[:80])\n'
    '            return\n'
    '\n'
    '        # 1. CRM 对象表\n'
    '        for row in crm_tables:\n'
    '            table_name = list(row.values())[0] if row else ""\n'
    '            if not table_name:\n'
    '                continue\n'
    '            self._add_table_item(table_name, \'crm\')\n'
    '\n'
    '        # 2. Excel 导入表\n'
    '        try:\n'
    '            ex_tables = self._db.execute("SHOW TABLES LIKE \'ex_%\'") or []\n'
    '        except Exception:\n'
    '            ex_tables = []\n'
    '\n'
    '        for row in ex_tables:\n'
    '            table_name = list(row.values())[0] if row else ""\n'
    '            if not table_name:\n'
    '                continue\n'
    '            self._add_table_item(table_name, \'excel\')\n'
    '\n'
    '        # 3. 其他 MySQL 表（仅在显式请求时加载）\n'
    '        if include_mysql_tables:\n'
    '            managed_prefixes = (\'对象-\', \'sr_\', \'ex_\', \'cr_\', \'报表-\')\n'
)

new1 = (
    '        try:\n'
    '            crm_tables = self._db.execute("SHOW TABLES LIKE \'对象-%\'") or []\n'
    '        except Exception as e:\n'
    '            self._show_placeholder("查询失败", str(e)[:80])\n'
    '            return\n'
    '\n'
    '        # 1. 对象表（仅显示 对象-XXX）\n'
    '        for row in crm_tables:\n'
    '            table_name = list(row.values())[0] if row else ""\n'
    '            if not table_name:\n'
    '                continue\n'
    '            self._add_table_item(table_name, \'crm\')\n'
    '\n'
    '        # 2. (sr_% / ex_% / 普通MySQL表等不再显示)\n'
    '\n'
    '        # 3. (已根据用户要求隐藏，不显示其他MySQL表)\n'
    '        if include_mysql_tables:\n'
)

if old1 in content:
    content = content.replace(old1, new1, 1)
    print("替换1 成功")
else:
    print("替换1 失败")
    idx = content.find("result1 = self._db.execute")
    if idx >= 0:
        print("附近文本:", repr(content[idx:idx+350]))

old2 = (
    '            managed_prefixes = (\'对象-\', \'sr_\', \'ex_\', \'cr_\', \'报表-\')\n'
    '            try:\n'
    '                all_tables = self._db.execute("SHOW TABLES") or []\n'
    '            except Exception:\n'
    '                all_tables = []\n'
    '\n'
    '            for row in all_tables:\n'
    '                table_name = list(row.values())[0] if row else ""\n'
    '                if not table_name:\n'
    '                    continue\n'
    '                if any(table_name.startswith(p) for p in managed_prefixes):\n'
    '                    continue\n'
    '                self._add_table_item(table_name, \'mysql\')\n'
)

new2 = (
    '            # (已根据用户要求隐藏，不再显示普通MySQL表)\n'
    '            pass\n'
)

if old2 in content:
    content = content.replace(old2, new2, 1)
    print("替换2 成功")
else:
    print("替换2 失败")

file.write_text(content, "utf-8")
print("保存完成")
