from collections import namedtuple
from datetime import datetime, timezone

import peewee

from iotmonitoring.domain.entities import ActuatorEvent, SensorReading, StorageThresholds
from iotmonitoring.infrastructure.models import (
    ActuatorEventModel,
    BackendAccountModel,
    SensorReadingModel,
    StorageThresholdsModel,
)

BackendAccount = namedtuple("BackendAccount", ["base_url", "email", "password"])


class SensorReadingRepository:
    @staticmethod
    def save(reading: SensorReading) -> SensorReading:
        record = SensorReadingModel.create(
            device_id=reading.device_id,
            temperature=reading.temperature,
            humidity=reading.humidity,
            recorded_at=reading.recorded_at,
        )
        return SensorReading(
            record.device_id,
            record.temperature,
            record.humidity,
            record.recorded_at,
            record.id,
        )

    @staticmethod
    def find_latest_by_device_id(device_id: str) -> SensorReading | None:
        try:
            record = (
                SensorReadingModel
                .select()
                .where(SensorReadingModel.device_id == device_id)
                .order_by(SensorReadingModel.recorded_at.desc(), SensorReadingModel.id.desc())
                .get()
            )
            return SensorReading(
                record.device_id,
                record.temperature,
                record.humidity,
                record.recorded_at,
                record.id,
            )
        except peewee.DoesNotExist:
            return None

    @staticmethod
    def find_recent_by_device_id(device_id: str, limit: int = 10) -> list[SensorReading]:
        records = (
            SensorReadingModel
            .select()
            .where(SensorReadingModel.device_id == device_id)
            .order_by(SensorReadingModel.recorded_at.desc(), SensorReadingModel.id.desc())
            .limit(limit)
        )
        return [
            SensorReading(
                record.device_id,
                record.temperature,
                record.humidity,
                record.recorded_at,
                record.id,
            )
            for record in records
        ]

    @staticmethod
    def find_unsynced(limit: int = 50) -> list[SensorReading]:
        records = (
            SensorReadingModel
            .select()
            .where(SensorReadingModel.is_synced == False)  # noqa: E712 (peewee needs ==)
            .order_by(SensorReadingModel.recorded_at.asc(), SensorReadingModel.id.asc())
            .limit(limit)
        )
        return [
            SensorReading(
                record.device_id,
                record.temperature,
                record.humidity,
                record.recorded_at,
                record.id,
            )
            for record in records
        ]

    @staticmethod
    def count_unsynced() -> int:
        return (
            SensorReadingModel
            .select()
            .where(SensorReadingModel.is_synced == False)  # noqa: E712 (peewee needs ==)
            .count()
        )

    @staticmethod
    def count_by_device(device_id: str) -> int:
        return (
            SensorReadingModel
            .select()
            .where(SensorReadingModel.device_id == device_id)
            .count()
        )

    @staticmethod
    def delete_all() -> int:
        return SensorReadingModel.delete().execute()

    @staticmethod
    def mark_synced(reading_id: int, synced_at: datetime | None = None) -> None:
        (
            SensorReadingModel
            .update(is_synced=True, synced_at=synced_at or datetime.now(timezone.utc))
            .where(SensorReadingModel.id == reading_id)
            .execute()
        )


class StorageThresholdsRepository:
    @staticmethod
    def save_current(thresholds: StorageThresholds) -> StorageThresholds:
        (
            StorageThresholdsModel
            .update(is_current=False)
            .where(StorageThresholdsModel.device_id == thresholds.device_id)
            .execute()
        )
        record = StorageThresholdsModel.create(
            device_id=thresholds.device_id,
            min_temperature=thresholds.min_temperature,
            max_temperature=thresholds.max_temperature,
            min_humidity=thresholds.min_humidity,
            max_humidity=thresholds.max_humidity,
            is_current=True,
        )
        return StorageThresholds(
            record.device_id,
            record.min_temperature,
            record.max_temperature,
            record.min_humidity,
            record.max_humidity,
            record.id,
            record.is_current,
        )

    @staticmethod
    def delete_all() -> int:
        return StorageThresholdsModel.delete().execute()

    @staticmethod
    def find_current_by_device_id(device_id: str) -> StorageThresholds | None:
        try:
            record = (
                StorageThresholdsModel
                .select()
                .where(
                    (StorageThresholdsModel.device_id == device_id)
                    & (StorageThresholdsModel.is_current == True)
                )
                .order_by(StorageThresholdsModel.id.desc())
                .get()
            )
            return StorageThresholds(
                record.device_id,
                record.min_temperature,
                record.max_temperature,
                record.min_humidity,
                record.max_humidity,
                record.id,
                record.is_current,
            )
        except peewee.DoesNotExist:
            return None


class ActuatorEventRepository:
    @staticmethod
    def save(event: ActuatorEvent) -> ActuatorEvent:
        record = ActuatorEventModel.create(
            device_id=event.device_id,
            event_type=event.event_type,
            triggered_at=event.triggered_at,
            resolved_at=event.resolved_at,
        )
        return ActuatorEvent(
            record.device_id,
            record.event_type,
            record.triggered_at,
            record.id,
            record.resolved_at,
        )

    @staticmethod
    def delete_all() -> int:
        return ActuatorEventModel.delete().execute()

    @staticmethod
    def find_recent_by_device_id(device_id: str, limit: int = 10) -> list[ActuatorEvent]:
        records = (
            ActuatorEventModel
            .select()
            .where(ActuatorEventModel.device_id == device_id)
            .order_by(ActuatorEventModel.triggered_at.desc(), ActuatorEventModel.id.desc())
            .limit(limit)
        )
        return [
            ActuatorEvent(
                record.device_id,
                record.event_type,
                record.triggered_at,
                record.id,
                record.resolved_at,
            )
            for record in records
        ]


class BackendAccountRepository:
    @staticmethod
    def get() -> BackendAccount | None:
        try:
            record = (
                BackendAccountModel
                .select()
                .order_by(BackendAccountModel.id.desc())
                .get()
            )
            return BackendAccount(record.base_url, record.email, record.password)
        except peewee.DoesNotExist:
            return None

    @staticmethod
    def save(base_url: str, email: str, password: str) -> None:
        # Cuenta única: reemplaza cualquier registro previo.
        BackendAccountModel.delete().execute()
        BackendAccountModel.create(
            base_url=base_url,
            email=email,
            password=password,
            updated_at=datetime.now(timezone.utc),
        )
