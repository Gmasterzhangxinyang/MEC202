#!/usr/bin/env python3
"""
启动 Demo
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from demo_app import app, init_db, seed_history

if __name__ == '__main__':
    init_db()
    seed_history()
    print('\n' + '='*50)
    print('  文档盖章机器人  DEMO')
    print('='*50)
    print('  账号：admin / admin123')
    print('  账号：operator1 / op123')
    print('  账号：reviewer1 / reviewer123')
    print()
    print('  访问：http://127.0.0.1:5001')
    print('  Ctrl+C 停止')
    print('='*50 + '\n')
    app.run(host='0.0.0.0', port=5001, debug=False)
