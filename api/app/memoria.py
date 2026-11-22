"""Memoria del proceso (R1, D52): cada lote la deja en el log y avisa si se acerca al límite de la instancia."""
import logging
import os

from . import settings

log = logging.getLogger(__name__)
AVISO = 0.75  # warning si el proceso pasa del 75 % del límite


def rss_mb() -> int | None:
    """Memoria residente actual del proceso, en MB (Linux: /proc/self/statm)."""
    try:
        with open("/proc/self/statm") as f:
            paginas = int(f.read().split()[1])
        return round(paginas * os.sysconf("SC_PAGE_SIZE") / 2 ** 20)
    except (OSError, ValueError, IndexError):
        return None


def limite_mb() -> int | None:
    """El límite de memoria de la instancia: MEMORIA_LIMITE_MB (lo pone desplegar.sh) o el del cgroup."""
    if settings.MEMORIA_LIMITE_MB:
        return settings.MEMORIA_LIMITE_MB
    for ruta in ("/sys/fs/cgroup/memory.max", "/sys/fs/cgroup/memory/memory.limit_in_bytes"):
        try:
            with open(ruta) as f:
                v = f.read().strip()
            if v.isdigit() and int(v) < 2 ** 50:
                return int(v) // 2 ** 20
        except OSError:
            continue
    return None


def revisar(contexto: str) -> int | None:
    """Devuelve el RSS y deja un warning si pasa del 75 % del límite."""
    rss, lim = rss_mb(), limite_mb()
    if rss and lim and rss > AVISO * lim:
        log.warning("%s: el proceso usa %s MB, más del %d %% del límite (%s MB)", contexto, rss, int(AVISO * 100), lim)
    return rss
