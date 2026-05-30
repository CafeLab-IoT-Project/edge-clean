from typing import Optional

import peewee

from iam.domain.entities import Device
from iam.infrastructure.models import DeviceModel


class DeviceRepository:
    @staticmethod
    def find_by_id(device_id: str) -> Optional[Device]:
        try:
            device = DeviceModel.get(DeviceModel.device_id == device_id)
            return Device(
                device.device_id,
                device.api_key,
                device.lot_id,
                device.created_at
            )
        except peewee.DoesNotExist:
            return None

    @staticmethod
    def find_by_id_and_api_key(device_id: str, api_key: str) -> Optional[Device]:
        try:
            device = DeviceModel.get(
                (DeviceModel.device_id == device_id) & (DeviceModel.api_key == api_key)
            )
            return Device(
                device.device_id,
                device.api_key,
                device.lot_id,
                device.created_at
            )
        except peewee.DoesNotExist:
            return None

    @staticmethod
    def save(device: Device) -> Device:
        DeviceModel.create(
            device_id=device.device_id,
            api_key=device.api_key,
            lot_id=device.lot_id,
            created_at=device.created_at,
        )
        return device
