#!/usr/bin/env python3
"""
一键启动脚本：
  python run.py

等价于：
  cd MEC202
  python main.py
"""
import sys
import os

# 确保项目根目录在 Python 路径中
ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from database.models import init_db, seed_demo_data
from web.app import app
from config import WEB_HOST, WEB_PORT

if __name__ == '__main__':
    print('=' * 45)
    print('  文档盖章机器人系统')
    print('=' * 45)
    init_db()
    seed_demo_data()
    print('[OK] 数据库初始化完成')
    print()
    print('  演示账号:')
    print('    管理员  : admin      / admin123')
    print('    操作员  : operator1  / op123')
    print('    复审员  : reviewer1  / reviewer123')
    print()
    print(f'  访问地址: http://127.0.0.1:{WEB_PORT}')
    print('  按 Ctrl+C 停止')
    print('=' * 45)
    app.run(host=WEB_HOST, port=WEB_PORT, debug=False)
