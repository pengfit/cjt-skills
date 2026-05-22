"""格式化输出工具"""

def format_number(n, decimals=2):
    """格式化数字，保留小数位"""
    if n is None:
        return '/'
    try:
        return f"{float(n):.{decimals}f}"
    except (ValueError, TypeError):
        return str(n)


def format_date(date_str, fmt='%Y-%m-%d'):
    """格式化日期"""
    if not date_str:
        return ''
    return date_str
