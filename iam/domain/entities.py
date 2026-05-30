from datetime import datetime
class Device:
    def __init__(self, device_id: str, api_key: str, lot_id, created_at: datetime):
        self.device_id = device_id
        self.lot_id = lot_id
        self.api_key = api_key
        self.created_at = created_at