"""Reloj lógico de Lamport (con exclusión mutua porque el servidor usa varios hilos)."""
import threading


class LamportClock:
    def __init__(self) -> None:
        self._value = 0
        self._lock = threading.Lock()

    def restore(self, value: int) -> None:
        """Al arrancar: continuar desde el mayor valor guardado (el reloj nunca retrocede)."""
        with self._lock:
            self._value = max(self._value, value)

    def tick(self) -> int:
        """Regla de envío: antes de enviar, incrementar el reloj."""
        with self._lock:
            self._value += 1
            return self._value

    def observe(self, recibido: int) -> int:
        """Regla de recepción: max(local, recibido) + 1."""
        with self._lock:
            self._value = max(self._value, recibido) + 1
            return self._value

    @property
    def value(self) -> int:
        with self._lock:
            return self._value
