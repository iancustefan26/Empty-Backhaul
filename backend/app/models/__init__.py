from app.models.base import Base, TimestampMixin
from app.models.load_request import LoadRequest
from app.models.route_history import RouteHistory
from app.models.truck import Truck
from app.models.wash_certificate import WashCertificate

__all__ = [
    "Base",
    "TimestampMixin",
    "Truck",
    "LoadRequest",
    "RouteHistory",
    "WashCertificate",
]
