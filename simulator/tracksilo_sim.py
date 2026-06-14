#!/usr/bin/env python3
"""TrackSilo - simulador del ESP32 para probar el flujo contra el edge.

Imita el firmware real (firmware/tracksilo-esp32/tracksilo-esp32.ino):
  1. se ANUNCIA al edge (phone-home) con su device_id y recibe su api_key.
  2. en loop: genera T/H, hace POST /api/v1/edge/readings con la X-API-Key,
     imprime status + humidityAlert/temperatureAlert y "aplica" los dos
     actuadores (pin 18 humedad, pin 19 temperatura).

El lote NO se configura aquí: se asigna desde la web /onboarding del edge.
Mientras no tenga lote, el edge bufferea las lecturas sin sincronizar.

Ejemplos:
  # se anuncia contra el Pi y manda lecturas cada 5s
  python tracksilo_sim.py --edge http://raspberrypi.local:5000

  # simula otro dispositivo (otro device_id => aparece como otro IoT en la web)
  python tracksilo_sim.py --device-id esp32-sim-02

  # usa un api_key ya emitido y manda 3 lecturas en escenario "caliente"
  python tracksilo_sim.py --api-key AbC123 --profile hot --count 3

  # una sola lectura y salir
  python tracksilo_sim.py --once
"""
from __future__ import annotations

import argparse
import random
import sys
import time

import requests

# Rangos por escenario (temperatura °C, humedad %).
PROFILES = {
    "optimal": ((18.0, 24.0), (52.0, 68.0)),
    "hot": ((28.0, 34.0), (50.0, 65.0)),
    "humid": ((20.0, 25.0), (75.0, 90.0)),
    "random": ((10.0, 35.0), (40.0, 95.0)),
}


def announce(edge: str, device_id: str) -> str:
    """Phone-home: se anuncia al edge y obtiene su api_key (idempotente)."""
    resp = requests.post(
        f"{edge}/api/v1/iam/devices/announce",
        json={"deviceId": device_id},
        timeout=10,
    )
    if resp.status_code == 200:
        body = resp.json()
        assigned = body.get("assigned")
        api_key = body["api_key"]
        estado = "con lote" if assigned else "PENDIENTE (asígnale un lote en /onboarding)"
        print(f"[announce] '{device_id}' {estado}; api_key={api_key}")
        return api_key
    print(f"[announce] fallo {resp.status_code}: {resp.text}", file=sys.stderr)
    sys.exit(2)


def make_reading(profile: str) -> tuple[float, float]:
    (t_lo, t_hi), (h_lo, h_hi) = PROFILES[profile]
    return round(random.uniform(t_lo, t_hi), 1), round(random.uniform(h_lo, h_hi), 1)


def send_reading(edge: str, device_id: str, api_key: str, temp: float, hum: float) -> None:
    try:
        resp = requests.post(
            f"{edge}/api/v1/edge/readings",
            headers={"X-API-Key": api_key},
            json={"deviceId": device_id, "temperature": temp, "humidity": hum},
            timeout=10,
        )
    except requests.RequestException as err:
        print(f"[edge] POST fallo: {err}", file=sys.stderr)
        return

    print(f"[dht] T={temp}C H={hum}%  ->  ", end="")
    if resp.status_code in (200, 201):
        body = resp.json()
        command = body.get("actuatorCommand", "NONE")
        humidity_alert = body.get("humidityAlert", False)
        temperature_alert = body.get("temperatureAlert", False)
        print(
            f"{resp.status_code} status={body.get('status')} actuador={command} "
            f"humedad={'ON' if humidity_alert else 'OFF'} "
            f"temperatura={'ON' if temperature_alert else 'OFF'}"
        )
        if humidity_alert:
            print("       [pin18] actuador de humedad ON")
        if temperature_alert:
            print("       [pin19] actuador de temperatura ON")
    elif resp.status_code == 401:
        print("401: revisa device_id / api_key", file=sys.stderr)
    else:
        print(f"{resp.status_code} {resp.text}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Simulador del ESP32 TrackSilo")
    parser.add_argument("--edge", default="http://raspberrypi.local:5000",
                        help="URL base del edge (default: http://raspberrypi.local:5000)")
    parser.add_argument("--device-id", default="tracksilo-sim-001",
                        help="id del dispositivo simulado")
    parser.add_argument("--api-key", default=None,
                        help="api_key del device; si se omite, se anuncia y la obtiene")
    parser.add_argument("--profile", choices=list(PROFILES), default="optimal",
                        help="escenario de valores a generar")
    parser.add_argument("--interval", type=float, default=5.0,
                        help="segundos entre lecturas (default: 5)")
    parser.add_argument("--count", type=int, default=0,
                        help="número de lecturas (0 = infinito)")
    parser.add_argument("--once", action="store_true",
                        help="manda una sola lectura y termina")
    args = parser.parse_args()

    edge = args.edge.rstrip("/")
    api_key = args.api_key or announce(edge, args.device_id)

    total = 1 if args.once else args.count
    sent = 0
    try:
        while True:
            temp, hum = make_reading(args.profile)
            send_reading(edge, args.device_id, api_key, temp, hum)
            sent += 1
            if total and sent >= total:
                break
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\n[sim] detenido.")


if __name__ == "__main__":
    main()
