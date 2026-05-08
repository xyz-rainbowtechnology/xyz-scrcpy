#!/usr/bin/env python3
import py_compile
import sys
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent.parent
menu_script = REPO_DIR / "bin" / "menu.py"

print(f"Verificando integridad de: {menu_script}")

try:
    if not menu_script.exists():
        print(f"FAIL: Archivo no encontrado en {menu_script}")
        sys.exit(1)
        
    py_compile.compile(str(menu_script), doraise=True)
    print("✓ OK: Sintaxis perfecta de XYZ / Rainbowtechnology")
    sys.exit(0)
except Exception as e:
    print(f"✗ FAIL: Error de sintaxis detectado")
    print(f"Detalle: {e}")
    sys.exit(1)
