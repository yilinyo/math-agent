"""Compatibility command for the current settings/resource browser checks.

The SQLite library is no longer exposed in settings. All edit checks run on
automatically created disposable resources, never on the supplied server.
"""
import sys

from check_settings_ui import main


if __name__ == '__main__':
    print('知识管理页面已改为实际资源管理；使用隔离临时资源执行设置页检查。')
    if '--url' in sys.argv:
        index = sys.argv.index('--url')
        if index + 1 >= len(sys.argv):
            raise SystemExit('--url 缺少参数')
        del sys.argv[index:index + 2]
        print('旧 --url 参数不再使用，不会修改该服务中的资源。')
    main()
