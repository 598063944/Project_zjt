filepath = r'D:\Workspace\Project_001_数据批量文档处理工具\custom_report.py'

with open(filepath, 'r', encoding='utf-8') as f:
    content = f.read()

old = "        else:\n            self._bottom_status.setText(f\"❌ 刷新失败: {result.get('error', '未知错误')}\")"
new = "        else:\n            _err = result.get('error', '未知错误')\n            self._bottom_status.setText(f\"❌ 刷新失败: {_err}\")\n            if hasattr(self, '_append_output_fn') and self._append_output_fn:\n                try:\n                    self._append_output_fn(f\"[刷新] 刷新失败: {_err}\")\n                except Exception:\n                    pass\n            _light_msgbox(self, QMessageBox.Icon.Warning, \"刷新失败\", _err)"

count = content.count(old)
print(f'Pattern found {count} times')
if count == 1:
    content = content.replace(old, new, 1)
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)
    print('FIXED')
else:
    print('ERROR: pattern not found or multiple matches')
