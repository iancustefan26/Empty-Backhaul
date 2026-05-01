from datetime import datetime

from geoalchemy2 import Geometry
from sqlalchemy import Boolean, DateTime, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class LoadRequest(Base, TimestampMixin):
    __tablename__ = "load_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    shipper_name: Mapped[str | None] = mapped_column(String(128))

    # "pharma" | "raw_poultry" | "raw_meat" | "dairy" | "frozen_vegetables" |
    # "produce" | "chemicals" | "ambient_dry"
    cargo_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    cargo_description: Mapped[str | None] = mapped_column(String(256))

    temp_min_celsius: Mapped[float] = mapped_column(Float, nullable=False)
    temp_max_celsius: Mapped[float] = mapped_column(Float, nullable=False)
    requires_pharma_logger: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # incompatible prior cargoes (e.g. "raw_meat,chemicals") — checked by Analyst agent
    forbidden_prior_cargo: Mapped[str | None] = mapped_column(String(256))

    pickup_location = mapped_column(
        Geometry(geometry_type="POINT", srid=4326, spatial_index=True),
        nullable=False,
    )
    pickup_city: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    delivery_location = mapped_column(
        Geometry(geometry_type="POINT", srid=4326, spatial_index=True),
        nullable=False,
    )
    delivery_city: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    pickup_window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    pickup_window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    weight_kg: Mapped[float] = mapped_column(Float, nullable=False)
    price_eur: Mapped[float] = mapped_column(Float, nullable=False)

    # "available" | "matched" | "in_transit" | "completed" | "cancelled"
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="available", index=True)

    def __repr__(self) -> str:
        return (
            f"<LoadRequest id={self.id} cargo={self.cargo_type} "
            f"{self.pickup_city}→{self.delivery_city} status={self.status}>"
        )
