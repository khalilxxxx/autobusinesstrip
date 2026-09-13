"""只构建完整 Demo 的共享契约，不读取或改写历史配置包。"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BEGIN = '# BEGIN CURRENT BATCH INPUT RULES\n'
END = '# END CURRENT BATCH INPUT RULES\n'


def build_nodes():
    rules = (ROOT / 'common/input_rules.py').read_text()
    contract = (ROOT / 'common/interpretation_contract.py').read_text()
    wrappers = json.loads((ROOT / 'common/entrypoints.json').read_text())
    for name, wrapper in wrappers.items():
        (ROOT / 'nodes' / (name + '.py')).write_text(
            '# 自动生成：修改完整Demo_Dify接入/common 后运行 build_nodes.py。\n'
            + rules + '\n\n' + contract + '\n\n' + wrapper)
    for name in ('N02', 'N06'):
        path = ROOT / 'nodes' / (name + '.py')
        source = path.read_text()
        if BEGIN in source:
            source = source.split(BEGIN)[0] + source.split(END, 1)[1]
        path.write_text(BEGIN + rules + END + source)


if __name__ == '__main__':
    build_nodes()
