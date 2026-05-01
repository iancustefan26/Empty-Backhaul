from datetime import datetime

from geoalchemy2 import Geometry
from sqlalchemy import DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class RouteHistory(Base, TimestampMixin):
    __tablename__ = "route_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    truck_id: Mapped[int] = mapped_column(
        ForeignKey("trucks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    load_request_id: Mapped[int | None] = mapped_column(
        ForeignKey("load_requests.id", ondelete="SET NULL"), nullable=True, index=True
    )

    start_location = mapped_column(
        Geometry(geometry_type="POINT", srid=4326, spatial_index=True),
        nullable=False,
    )
    end_location = mapped_column(
        Geometry(geometry_type="POINT", srid=4326, spatial_index=True),
        nullable=False,
    )

    start_city: Mapped[str | None] = mapped_column(String(64))
    end_city: Mapped[str | None] = mapped_column(String(64))

    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    distance_km: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    cargo_carried: Mapped[str | None] = mapped_column(String(64))

    truck = relationship("Truck", back_populates="route_history")

    def __repr__(self) -> str:
        return f"<RouteHistory id={self.id} truck={self.truck_id} {self.start_city}→{self.end_city}>"
