from iam.domain.entities import Device
from iam.domain.services import AuthService, DeviceRegistrationService
from iam.infrastructure.repositories import DeviceRepository


class IamApplicationService:
    def __init__(self):
        self.device_repository = DeviceRepository()
        self.auth_service = AuthService()
        self.registration_service = DeviceRegistrationService()

    def authenticate(self, device_id: str, api_key: str) -> bool:
        device = self.device_repository.find_by_id_and_api_key(device_id, api_key)
        return self.auth_service.authenticate(device)

    def register_device(self, device_id: str, lot_id: str | None = None) -> Device:
        existing_device = self.device_repository.find_by_id(device_id)
        if existing_device is not None:
            raise ValueError("device_id is already registered")

        device = self.registration_service.register_device(device_id, lot_id)
        return self.device_repository.save(device)

    def get_or_create_development_device(self) -> Device:
        return self.device_repository.get_or_create_development_device()

    def get_all_devices(self) -> list:
        return DeviceRepository.find_all()