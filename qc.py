#!/usr/bin/env python3
"""Doc P4 QC gate CLI: python3 qc.py <video> [work_dir] -> PASS/FAIL, exit 1."""
import os
import sys

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from src.qc import run_checks  # noqa: E402

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("ishlatish: python3 qc.py short.mp4 [work_dir]")
        sys.exit(2)
    # cfg: secrets'siz (QC faqat video sozlamalarini o'qiydi)
    cfg = {}
    try:
        import yaml
        _p = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "config.yaml")
        with open(_p, encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
    except Exception as e:
        print(f"[qc] config.yaml o'qilmadi ({e}) — standart cfg bilan davom")
    work = sys.argv[2] if len(sys.argv) > 2 else None
    ok, _ = run_checks(sys.argv[1], cfg=cfg, work=work)
    sys.exit(0 if ok else 1)

