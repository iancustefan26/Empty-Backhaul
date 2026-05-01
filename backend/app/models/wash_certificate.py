from datetime import datetime

from geoalchemy2 import Geometry
from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class WashCertificate(Base, TimestampMixin):
    __tablename__ = "wash_certificates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    truck_id: Mapped[int] = mapped_column(
        ForeignKey("trucks.id", ondelete="CASCADE"), nullable=False, index=True
    )

    certificate_number: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)

    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # "standard" | "deep" | "pharma_grade" | "ansvsa_official"
    wash_type: Mapped[str] = mapped_column(String(32), nullable=False)

    prior_cargo: Mapped[str | None] = mapped_column(String(64))

    issuing_facility: Mapped[str | None] = mapped_column(String(128))

    location = mapped_column(
        Geometry(geometry_type="POINT", srid=4326, spatial_index=True),
        nullable=True,
    )

    truck = relationship("Truck", back_populates="wash_certificates")

    def __repr__(self) -> str:
        return f"<WashCertificate id={self.id} truck={self.truck_id} no={self.certificate_number}>"
