#!/usr/bin/env python3
"""TrackSilo - simulador del ESP32 para probar el flujo contra el edge.

Imita el firmware real (firmware/tracksilo-esp32/tracksilo-esp32.ino):
  1. (opcional) registra el dispositivo en el edge y obtiene su api_key.
  2. en loop: genera T/H, hace POST /api/v1/edge/readings con la X-API-Key,
     imprime status + actuatorCommand y "aplica" el actuador.

Ejemplos:
  # auto-registra el device (lot 1) contra el Pi y manda lecturas cada 5s
  python tracksilo_sim.py --edge http://raspberrypi.local:5000 --lot-id 1

  # usa un api_key ya emitido y manda 3 lecturas en escenario "peligro"
  python tracksilo_sim.py --api-key AbC123 --profile danger --count 3

  # una sola lectura y salir
  python tracksilo_sim.py --api-key AbC123 --once
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


def register_device(edge: str, device_id: str, lot_id: str) -> str:
    """Da de alta el device en el edge y devuelve su api_key (idempotente-ish)."""
    resp = requests.post(
        f"{edge}/api/v1/iam/devices",
        json={"device_id": device_id, "lot_id": lot_id},
        timeout=10,
    )
    if resp.status_code == 201:
        api_key = resp.json()["api_key"]
        print(f"[alta] device '{device_id}' registrado (lot={lot_id}) api_key={api_key}")
        return api_key
    if resp.status_code == 409:
        print(
            f"[alta] '{device_id}' ya existe. No puedo recuperar su api_key; "
            "pásalo con --api-key o usa otro --device-id.",
            file=sys.stderr,
        )
        sys.exit(2)
    print(f"[alta] fallo {resp.status_code}: {resp.text}", file=sys.stderr)
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
        print(f"{resp.status_code} status={body.get('status')} actuador={command}")
        if command == "ACTIVATE":
            print("       [actuador] deshumedecedor ON")
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
                        help="api_key del device; si se omite, se auto-registra")
    parser.add_argument("--lot-id", default="1",
                        help="coffeeLotId para el alta (debe existir en el backend)")
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
    api_key = args.api_key or register_device(edge, args.device_id, args.lot_id)

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
