# -*- coding: utf-8 -*-
"""UI 验收用的独立面板启动器（只在临时数据目录上跑，绝不动 backend/data）。

用法：python tools/dev_ui_panel.py [port]
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))     # mc-server-panel/
BACKEND = os.path.join(ROOT, 'backend')
sys.path[:0] = [BACKEND, os.path.join(BACKEND, '.deps')]
os.chdir(BACKEND)

import uvicorn  # noqa: E402

if __name__ == '__main__':
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8123
    print(f'[dev_ui_panel] MC_DATA_DIR={os.environ.get("MC_DATA_DIR")}', flush=True)
    uvicorn.run('app.main:app', host='127.0.0.1', port=port, log_level='info')
