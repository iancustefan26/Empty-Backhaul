from typing import TYPE_CHECKING

from geoalchemy2 import Geometry
from sqlalchemy import Boolean, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.route_history import RouteHistory
    from app.models.wash_certificate import WashCertificate


class Truck(Base, TimestampMixin):
    __tablename__ = "trucks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    plate_number: Mapped[str] = mapped_column(String(16), unique=True, nullable=False, index=True)
    carrier_name: Mapped[str | None] = mapped_column(String(128))

    # "frozen" | "chilled" | "ambient" | "pharma_2_8" | "multi_temp"
    temp_capability: Mapped[str] = mapped_column(String(32), nullable=False, index=True)

    # last cargo class drives compliance: "raw_meat" | "dairy" | "produce" |
    # "pharma" | "frozen" | "clean" | "chemicals"
    last_cargo: Mapped[str] = mapped_column(String(32), nullable=False)

    has_pharma_logger: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    remaining_driving_hours: Mapped[float] = mapped_column(Float, nullable=False, default=9.0)

    # "loaded" | "empty" | "returning" | "maintenance"
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="loaded", index=True)

    current_location = mapped_column(
        Geometry(geometry_type="POINT", srid=4326, spatial_index=True),
        nullable=True,
    )
    current_city: Mapped[str | None] = mapped_column(String(64), index=True)

    home_base_city: Mapped[str] = mapped_column(String(64), nullable=False)

    route_history: Mapped[list["RouteHistory"]] = relationship(
        back_populates="truck", cascade="all, delete-orphan"
    )
    wash_certificates: Mapped[list["WashCertificate"]] = relationship(
        back_populates="truck", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Truck id={self.id} plate={self.plate_number} status={self.status}>"
