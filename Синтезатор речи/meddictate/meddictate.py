#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
МедДиктовка — точка входа.

Запуск из исходников:      python meddictate.py
Самопроверка:              python meddictate.py --selftest
Отчёт по словарю:          python meddictate.py --model-check
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.main import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
