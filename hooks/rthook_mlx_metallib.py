"""PyInstaller runtime hook: garante que o MLX encontre o metallib no bundle.

O MLX C++ (libmlx.dylib) usa dladdr() para localizar a si mesmo, e então busca
o metallib em caminhos relativos como ../Resources/mlx/mlx.metallib.
No PyInstaller, a libmlx.dylib vai para Frameworks/mlx/lib/ mas o metallib
vai para Resources/mlx/lib/ — caminhos incompatíveis.

Este hook cria um symlink para que o MLX encontre o metallib onde espera.
Alternativa: setar a variável de ambiente MLX_METALLIB_PATH (se suportada).
"""

import os
import shutil
import sys
from contextlib import suppress


def _ensure_mlx_metallib():
    """Cria symlink Resources/ relativo ao libmlx.dylib se necessário."""
    if not getattr(sys, "frozen", False):
        return  # Só roda em apps empacotados

    # No PyInstaller .app bundle:
    #   sys._MEIPASS não é usado em modo BUNDLE; os paths são:
    #   Frameworks/ (binaries) e Resources/ (datas)
    # Mas em modo onedir/COLLECT, sys._MEIPASS aponta para o dir base.

    meipass = getattr(sys, "_MEIPASS", None)
    if not meipass:
        return

    # Localizar o mlx.metallib real
    # PyInstaller coloca collect_data_files('mlx') em <meipass>/mlx/lib/
    metallib_candidates = [
        os.path.join(meipass, "mlx", "lib", "mlx.metallib"),
        os.path.join(meipass, "Resources", "mlx", "lib", "mlx.metallib"),
    ]

    metallib_real = None
    for candidate in metallib_candidates:
        resolved = os.path.realpath(candidate)
        if os.path.exists(resolved):
            metallib_real = resolved
            break

    if not metallib_real:
        return  # metallib não encontrado, MLX vai falhar naturalmente

    # A libmlx.dylib vai estar em <meipass>/mlx/lib/ (via binaries)
    # O MLX C++ busca metallib relativo ao dylib em:
    #   <dylib_dir>/mlx.metallib  (mesmo diretório)
    # Garantir que existe lá
    dylib_dir = os.path.join(meipass, "mlx", "lib")
    target_metallib = os.path.join(dylib_dir, "mlx.metallib")

    if not os.path.exists(target_metallib) and os.path.isdir(dylib_dir):
        try:
            os.symlink(metallib_real, target_metallib)
        except OSError:
            # Se symlink falha (permissões), tenta copiar
            with suppress(OSError):
                shutil.copy2(metallib_real, target_metallib)


_ensure_mlx_metallib()
