# -*- coding: utf-8 -*-
"""
Скачивает русскую модель Vosk в папку model/ (нужно для сборки exe).

    python tools/fetch_model.py                 # компактная модель, 45 МБ
    python tools/fetch_model.py --big           # большая модель, 1.8 ГБ (точнее)
    python tools/fetch_model.py --check         # только проверить наличие
"""
from __future__ import annotations

import argparse
import os
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import config  # noqa: E402


def download(url: str, dst_zip: str) -> None:
    import urllib.request

    with urllib.request.urlopen(url, timeout=60) as resp, open(dst_zip, "wb") as fh:
        total = int(resp.headers.get("Content-Length", 0))
        done = 0
        while True:
            chunk = resp.read(1 << 20)
            if not chunk:
                break
            fh.write(chunk)
            done += len(chunk)
            if total:
                sys.stdout.write(f"\r  скачано {done * 100 // total}%   ")
                sys.stdout.flush()
    print()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--big", action="store_true", help="большая модель (точнее, но 1.8 ГБ)")
    parser.add_argument("--check", action="store_true", help="только проверить наличие")
    args = parser.parse_args()

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    name = config.BIG_MODEL_DIR if args.big else config.BUILTIN_MODEL_DIR
    url = config.BIG_MODEL_URL if args.big else config.BUILTIN_MODEL_URL
    target = os.path.join(root, "model")

    if os.path.isfile(os.path.join(target, "am", "final.mdl")):
        print(f"Модель уже на месте: {target}")
        return 0
    if args.check:
        print("Модель не найдена. Запустите: python tools/fetch_model.py")
        return 1

    print(f"Качаю {name}")
    print(f"  {url}")
    archive = os.path.join(root, name + ".zip")
    download(url, archive)
    print("  распаковка…")
    with zipfile.ZipFile(archive) as zf:
        zf.extractall(root)
    os.remove(archive)
    extracted = os.path.join(root, name)
    if os.path.isdir(extracted) and os.path.abspath(extracted) != os.path.abspath(target):
        import shutil
        if os.path.isdir(target):
            shutil.rmtree(target, ignore_errors=True)
        shutil.move(extracted, target)
    print(f"Готово: {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
