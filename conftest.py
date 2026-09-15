"""pytest 全局配置：无显示器环境下使用 offscreen 平台，并保证项目根可导入。"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
