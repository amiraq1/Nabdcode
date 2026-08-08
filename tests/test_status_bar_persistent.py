def test_status_bar_is_persistent():
    """Persistent UI: AgentStatusBar must use transient=False to remain visible after completion."""
    import ast
    import pathlib

    source = pathlib.Path('ui/widgets/status_bar.py').read_text()
    tree = ast.parse(source)

    # البحث عن Live call والتحقق من transient=False
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id == 'Live':
                for keyword in node.keywords:
                    if keyword.arg == 'transient':
                        if isinstance(keyword.value, ast.Constant):
                            assert keyword.value.value == False, \
                                f"AgentStatusBar uses transient={keyword.value.value}, must be transient=False to remain visible"
                        elif isinstance(keyword.value, ast.NameConstant):  # Python < 3.8
                            assert keyword.value.value == False, \
                                f"AgentStatusBar uses transient={keyword.value.value}, must be transient=False"

    # إذا لم نجد transient أصلاً، فهذا فشل أيضاً
    assert 'transient' in source, "transient parameter not found in AgentStatusBar"
