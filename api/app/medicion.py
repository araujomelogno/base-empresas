"""V3 (D53): cuántas consultas hace un lote y cuánto tiempo pasa esperando a la base.

Envuelve la conexión del lote mientras dura la medición: cada execute (y cada COPY) suma una consulta y su tiempo.
No cuenta el aviso de progreso, que va por otra conexión."""
import time


class _Cursor:
    def __init__(self, cur, med):
        self._cur, self._med = cur, med

    def __enter__(self):
        self._cur.__enter__()
        return self

    def __exit__(self, *a):
        return self._cur.__exit__(*a)

    def execute(self, *a, **k):
        with self._med.midiendo():
            return self._cur.execute(*a, **k)

    def executemany(self, query, params, *a, **k):
        params = list(params)
        with self._med.midiendo(len(params)):
            return self._cur.executemany(query, params, *a, **k)

    def copy(self, *a, **k):
        self._med.consultas += 1
        return _Copy(self._cur.copy(*a, **k), self._med)

    def __getattr__(self, nombre):
        return getattr(self._cur, nombre)


class _Copy:
    def __init__(self, cp, med):
        self._cp, self._med, self._t0 = cp, med, 0.0

    def __enter__(self):
        self._t0 = time.monotonic()
        return self._cp.__enter__()

    def __exit__(self, *a):
        try:
            return self._cp.__exit__(*a)
        finally:
            self._med.segundos += time.monotonic() - self._t0


class Medicion:
    def __init__(self, conn):
        self.conn = conn
        self.consultas = 0
        self.segundos = 0.0

    def midiendo(self, n: int = 1):
        med = self

        class _M:
            def __enter__(self):
                self.t0 = time.monotonic()

            def __exit__(self, *a):
                med.consultas += n
                med.segundos += time.monotonic() - self.t0
        return _M()

    def __enter__(self):
        # conn.execute usa conn.cursor() por dentro: alcanza con envolver el cursor
        med = self
        self._cursor = self.conn.cursor

        def cursor(*a, **k):
            return _Cursor(med._cursor(*a, **k), med)
        self.conn.cursor = cursor
        return self

    def __exit__(self, *a):
        del self.conn.cursor   # vuelve al método de la clase
