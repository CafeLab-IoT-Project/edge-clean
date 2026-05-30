from peewee import CharField, DateTimeField

from shared.infrastructure.database import BaseModel


class DeviceModel(BaseModel):
    device_id = CharField(primary_key=True, max_length=50)
    api_key = CharField()
    lot_id = CharField(null=True)
    created_at = DateTimeField()

    class Meta:
        table_name = "devices"
