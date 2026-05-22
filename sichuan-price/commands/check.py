"""四川工程造价信息 - 检查源站是否有新数据更新，自动触发同步"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import subprocess
import requests
from commands.utils import load_config, get_all_periods, get_latest_period

requests.packages.urllib3.disable_warnings()

CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'config.yml')
SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def check_update():
    """检查源站是否有新周期数据，比对 last_period"""
    cfg = load_config(CONFIG_PATH)
    last_period = cfg.get('sync', {}).get('last_period', '') or ''

    print("[i] 检查源站是否有新数据...")
    print(f"  上次同步周期: {last_period or '(空)'}")

    periods = get_all_periods()
    active = [p for p in periods if p.get('State') == 1]
    if not active:
        print("[!] 未找到有效周期（State=1）")
        return None

    latest = max(active, key=lambda x: x.get('PeriodNo', 0))
    latest_name = latest['PeriodName']
    latest_guid = latest['Guid']

    print(f"  网站最新周期: {latest_name}")
    has_new = latest_name > last_period if last_period else True

    if has_new:
        print(f"\n[✓] 发现新数据: {latest_name}")
        print(f"    旧周期: {last_period or '(首次)'}")
        print(f"    新周期: {latest_name}")
        return True, latest_name, latest_guid
    else:
        print(f"\n[—] 无新数据，当前已是最新周期: {latest_name}")
        return False, latest_name, latest_guid


def trigger_sync(period_name, period_guid):
    """触发后台增量同步"""
    log_file = '/tmp/sichuan-incremental-sync.log'
    print(f"\n[→] 触发增量同步: {period_name}（后台运行）...")
    ret = subprocess.Popen(
        ['python3', 'commands/sync.py', '--force', '--no-check', f'--period={period_name}'],
        cwd=SCRIPT_DIR,
        env={**os.environ},
        stdout=open(log_file, 'w'),
        stderr=subprocess.STDOUT,
        start_new_session=True
    )
    print(f"[→] 同步已在后台启动 (PID {ret.pid})，日志: {log_file}")


if __name__ == '__main__':
    result = check_update()
    if result is None:
        print("\n检查失败，未找到有效周期")
    elif result[0]:
        _, latest_name, latest_guid = result
        print(f"\n新周期: {latest_name} ({latest_guid})")
        trigger_sync(latest_name, latest_guid)
        print("[✓] check.py 完成，sync.py 继续在后台运行")
    else:
        _, latest_name, _ = result
        print(f"\n已是最新: {latest_name}")
