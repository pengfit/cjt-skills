"""状态查看命令"""
import sys
import os
import requests

SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SCRIPT_DIR)

try:
    import urllib3
    urllib3.disable_warnings()
except Exception:
    pass


def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(os.path.dirname(script_dir), "config.yml")

    from commands.utils import load_config
    config = load_config(config_path)

    es_host = config["es"]["host"]
    es_index = config["es"]["index"]
    last_update_date = config["sync"].get("last_update_date", "")

    print(f"{'='*50}")
    print(f"  西安工程造价材料信息同步状态")
    print(f"{'='*50}")
    print(f"  目标索引:  {es_index}")
    print(f"  ES 地址:   {es_host}")
    print(f"  上次同步:  {last_update_date or '首次全量'}")
    print(f"  目标区县:  {', '.join(config['site']['counties'])}")

    # ES 统计
    try:
        # 文档总数
        resp = requests.post(
            f"{es_host}/{es_index}/_count",
            json={"query": {"match_all": {}}},
            timeout=10,
            verify=False
        )
        if resp.status_code == 200:
            count = resp.json().get("count", 0)
            print(f"\n  ES 文档总数: {count:,}")
    except Exception:
        pass

    # 按区县统计
    try:
        body = {
            "size": 0,
            "aggs": {
                "by_county": {
                    "terms": {"field": "county", "size": 20}
                }
            }
        }
        resp = requests.post(
            f"{es_host}/{es_index}/_search",
            json=body,
            timeout=10,
            verify=False
        )
        if resp.status_code == 200:
            aggs = resp.json().get("aggregations", {}).get("by_county", {}).get("buckets", [])
            if aggs:
                print(f"\n  各区县文档数:")
                for bucket in aggs:
                    print(f"    {bucket['key']}: {bucket['doc_count']:,}")
    except Exception:
        pass

    # 最新更新时间
    try:
        resp = requests.post(
            f"{es_host}/{es_index}/_search",
            json={"size": 1, "sort": [{"update_date": "desc"}], "_source": ["update_date"]},
            timeout=10,
            verify=False
        )
        if resp.status_code == 200:
            hits = resp.json().get("hits", {}).get("hits", [])
            if hits:
                latest = hits[0]["_source"].get("update_date", "?")
                print(f"\n  最新更新时间: {latest}")
    except Exception:
        pass

    print(f"{'='*50}")


if __name__ == "__main__":
    main()