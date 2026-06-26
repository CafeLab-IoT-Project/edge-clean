"""Bus de eventos en memoria para empujar cambios del edge a consumidores en vivo.

El endpoint SSE del dashboard se suscribe aquí; los caminos de código que cambian
datos (una lectura nueva, un umbral actualizado) publican un evento, de modo que la
pantalla se refresca en el instante en que el dato cambia, sin polling.

Es deliberadamente simple: el payload es solo una etiqueta; cada consumidor
reconstruye su propio snapshot cuando recibe la señal.
"""
import logging
import queue
import threading

logger = logging.getLogger(__name__)

# Etiquetas de evento.
READING = "reading"
THRESHOLDS = "thresholds"


class EventBus:
    """Pub/sub thread-safe: cada suscriptor recibe su propia cola."""

    def __init__(self):
        self._subscribers: set[queue.Queue] = set()
        self._lock = threading.Lock()

    def subscribe(self) -> "queue.Queue[str]":
        q: queue.Queue[str] = queue.Queue(maxsize=100)
        with self._lock:
            self._subscribers.add(q)
        return q

    def unsubscribe(self, q) -> None:
        with self._lock:
            self._subscribers.discard(q)

    def publish(self, event_type: str) -> None:
        with self._lock:
            subscribers = list(self._subscribers)
        for q in subscribers:
            try:
                q.put_nowait(event_type)
            except queue.Full:
                # Consumidor lento: descartamos en vez de bloquear al productor.
                logger.debug("Drop %s: cola de un suscriptor llena", event_type)


# Singleton compartido por todo el edge.
bus = EventBus()
