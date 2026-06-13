with open("custom_report.py", "r", encoding="utf-8") as f:
    lines = f.readlines()

fixes = {
    21564: (8, "def _add_dirs(parent_menu, children):"),
    21565: (12, "for node in children:"),
    21566: (16, "np = node['path']"),
    21567: (16, 'if np == "__root__":'),
    21568: (20, "if node.get('children'):"),
    21569: (24, "_add_dirs(parent_menu, node['children'])"),
    21570: (20, "continue"),
    21571: (16, 'parent_menu.addAction'),
    21572: (16, "if node.get('children'):"),
    21573: (20, "sub = parent_menu.addMenu"),
    21574: (20, "sub.setStyleSheet"),
    21575: (20, "_add_dirs(sub, node['children'])"),
    21576: (8, "if folders:"),
    21577: (12, "for root_node in folders:"),
    21578: (16, "if root_node.get('children'):"),
    21579: (20, "_add_dirs(move_menu, root_node['children'])"),
}

fixed = 0
for idx, (target, content_check) in fixes.items():
    if idx >= len(lines):
        continue
    stripped = lines[idx].lstrip()
    old_indent = len(lines[idx]) - len(stripped)
    current_content = stripped.strip()
    print(f"L{idx+1}: old={old_indent} target={target} content={current_content[:40]!r}")
    if old_indent != target:
        lines[idx] = " " * target + current_content + "\n"
        fixed += 1

print(f"Fixed {fixed} lines")
with open("custom_report.py", "w", encoding="utf-8") as f:
    f.writelines(lines)
