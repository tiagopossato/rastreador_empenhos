from __future__ import annotations

import threading
import time


class RateLimiter:
    """Espaça chamadas de uma API, compartilhando o limite entre todas as threads do processo."""

    def __init__(self, max_por_minuto: int) -> None:
        if max_por_minuto <= 0:
            raise ValueError("O limite por minuto deve ser positivo.")
        self._intervalo = 60.0 / max_por_minuto
        self._lock = threading.Lock()
        self._ultima = 0.0
        self._ativo = True

    @property
    def intervalo(self) -> float:
        return self._intervalo

    def desativar(self) -> None:
        """Desliga a espera (usado nos testes, que não fazem chamadas reais)."""
        with self._lock:
            self._ativo = False

    def aguardar(self) -> None:
        """Bloqueia até que o intervalo mínimo desde a última chamada tenha passado."""
        with self._lock:
            if not self._ativo:
                return
            agora = time.monotonic()
            espera = self._intervalo - (agora - self._ultima)
            if self._ultima and espera > 0:
                time.sleep(espera)
            self._ultima = time.monotonic()

    def reiniciar(self) -> None:
        with self._lock:
            self._ultima = 0.0


PNCP_LIMITER = RateLimiter(600)
CONTRATOS_GOV_LIMITER = RateLimiter(240)
