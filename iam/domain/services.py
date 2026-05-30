from typing import Optional
from iam.domain.entities import Device
from datetime import datetime

class AuthService:
    @staticmethod
    def authenticate(device: Optional[Device]) -> bool:
        return device is not None

class DeviceRegistrationService:
    @staticmethod
    def generate_api_key() -> str:
        import secrets
        return secrets.token_urlsafe(32)
    
    @staticmethod
    def register_device(device_id: str, lot_id: str | None = None) -> Device:
        """Create and persist a new device with generated credentials.
        
        Args:
            device_id: Unique identifier for the device
            
        Returns:
            Device: The created device with generated api_key
        """

        # Business rule: device_id must be valid
        if not device_id or not isinstance(device_id, str):
            raise ValueError("device_id must be a non-empty string")
        
        if len(device_id) > 50:
            raise ValueError("device_id must not exceed 50 characters")
        
        if not device_id.replace("-", "").replace("_", "").isalnum():
            raise ValueError("device_id must contain only alphanumeric, dash, and underscore characters")

        api_key = DeviceRegistrationService.generate_api_key()
        created_at = datetime.utcnow()
        
        return Device(device_id, api_key, lot_id, created_at)
    
