from typing import Optional
from iam.domain.entities import Device

class AuthService:
    def authenticate(device: Optional[Device]) -> bool:
        return device is not None

class DeviceRegistrationService:

    def generate_api_key() -> str:
        import secrets
        return secrets.token_urlsafe(32)
    
    def register_device(device_id: str) -> Device:
        """Create and persist a new device with generated credentials.
        
        Args:
            device_id: Unique identifier for the device
            
        Returns:
            Device: The created device with generated api_key
        """

        api_key = DeviceRegistrationService.generate_api_key()