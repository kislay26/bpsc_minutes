"""Embed the tested modules in one pasteable Kaggle cell; no ZIP update needed."""
import ast
from pathlib import Path

root = Path(__file__).resolve().parent
path = root / 'kaggle/KAGGLE_GEMINI_TRIAL.py'
cell = path.read_text(encoding='utf-8-sig')
prefix = cell[:cell.index('program = ')]
suffix = cell[cell.index("compile(program, '<gemini-page-trial>', 'exec')"):]
suffix = suffix.replace('timeout=300', 'timeout=600')
suffix = suffix.replace('timeout=600', 'timeout=1800')
suffix = suffix.replace("('inventory.json', 'ownership.json', 'blocks.json', 'response.json', 'annotated_page.pdf', 'crop_preview.pdf')",
                        "('validation.json', 'inventory.json', 'ownership.json', 'blocks.json', 'response.json', 'annotated_page.pdf', 'crop_preview.pdf')")
suffix = suffix.replace("('response.json', 'annotated_page.pdf', 'crop_preview.pdf')",
                        "('inventory.json', 'ownership.json', 'blocks.json', 'response.json', 'annotated_page.pdf', 'crop_preview.pdf')")
program = ('import sys, types\n'
           'regions = types.ModuleType("region_assignment")\n'
           'sys.modules["region_assignment"] = regions\n'
           'exec(' + repr((root / 'region_assignment.py').read_text(encoding='utf-8')) + ', regions.__dict__)\n'
           'quota = types.ModuleType("gemini_quota")\n'
           'sys.modules["gemini_quota"] = quota\n'
           'exec(' + repr((root / 'gemini_quota.py').read_text(encoding='utf-8')) + ', quota.__dict__)\n'
           'raster = types.ModuleType("raster_layout")\n'
           'raster.__file__ = "raster_layout.py"\n'
           'sys.modules["raster_layout"] = raster\n'
           'exec(' + repr((root / 'raster_layout.py').read_text(encoding='utf-8')) + ', raster.__dict__)\n'
           'layout = types.ModuleType("native_layout")\n'
           'sys.modules["native_layout"] = layout\n'
           'exec(' + repr((root / 'native_layout.py').read_text(encoding='utf-8')) + ', layout.__dict__)\n'
           + (root / 'gemini_layout_trial.py').read_text(encoding='utf-8'))
compile(program, '<embedded trial>', 'exec')
assert "'''" not in program
output = prefix + "program = textwrap.dedent(r'''\n" + program + "\n''')\n" + suffix
ast.parse(output)
path.write_text(output, encoding='utf-8')
print('Rebuilt one-cell Gemini trial; embedded code and notebook cell compile.')
