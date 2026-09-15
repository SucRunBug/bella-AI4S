#!/usr/bin/env python3
"""Create a minimal project without replacing existing files (standard library only)."""
import argparse
from datetime import date
import json
from pathlib import Path


def initialize(root, title, domain):
    root = Path(root).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    state = f'''# {title.replace(chr(10), ' ')}

更新日期：{date.today().isoformat()}
研究类型／学科：{domain.replace(chr(10), ' ')}

## 当前问题与本轮产物
尚未填写。

## 数据、方法与资源边界
尚未填写；自动实验预算未设定。

## 已有决定及原因
暂无。

## 完成的产物与检查
暂无。

## 未解问题／证据缺口
暂无登记，不代表没有缺口。

## 下一步
根据现有材料确定本轮任务。
'''
    files = {'research_state.md': state,
             'evidence.json': json.dumps({'schema_version': 1, 'sources': [], 'claims': []}, indent=2) + '\n',
             'experiments.jsonl': ''}
    results = []
    for name, content in files.items():
        path = root / name
        try:
            with path.open('x', encoding='utf-8') as handle:
                handle.write(content)
            results.append({'path': str(path), 'status': 'created'})
        except FileExistsError:
            results.append({'path': str(path), 'status': 'preserved'})
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True)
    parser.add_argument('--title', required=True)
    parser.add_argument('--domain', default='跨学科，按课题适配')
    args = parser.parse_args()
    try:
        print(json.dumps(initialize(args.root, args.title, args.domain), ensure_ascii=False, indent=2))
    except OSError as exc:
        parser.exit(2, f'Initialization failed: {exc}\n')


if __name__ == '__main__':
    main()
