"""initial schema: postgis + trucks + load_requests + route_history + wash_certificates

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-04-30

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from geoalchemy2 import Geometry

revision: str = "0001_initial_schema"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Enable PostGIS on the Supabase Postgres instance.
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")

    # ---------- trucks ----------
    op.create_table(
        "trucks",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("plate_number", sa.String(length=16), nullable=False),
        sa.Column("carrier_name", sa.String(length=128), nullable=True),
        sa.Column("temp_capability", sa.String(length=32), nullable=False),
        sa.Column("last_cargo", sa.String(length=32), nullable=False),
        sa.Column("has_pharma_logger", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("remaining_driving_hours", sa.Float(), nullable=False, server_default=sa.text("9.0")),
        sa.Column("status", sa.String(length=16), nullable=False, server_default=sa.text("'loaded'")),
        sa.Column(
            "current_location",
            Geometry(geometry_type="POINT", srid=4326, spatial_index=False),
            nullable=True,
        ),
        sa.Column("current_city", sa.String(length=64), nullable=True),
        sa.Column("home_base_city", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("plate_number", name="uq_trucks_plate_number"),
    )
    op.create_index("ix_trucks_plate_number", "trucks", ["plate_number"], unique=True)
    op.create_index("ix_trucks_temp_capability", "trucks", ["temp_capability"])
    op.create_index("ix_trucks_status", "trucks", ["status"])
    op.create_index("ix_trucks_current_city", "trucks", ["current_city"])
    op.create_index(
        "idx_trucks_current_location",
        "trucks",
        ["current_location"],
        postgresql_using="gist",
    )

    # ---------- load_requests ----------
    op.create_table(
        "load_requests",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("shipper_name", sa.String(length=128), nullable=True),
        sa.Column("cargo_type", sa.String(length=32), nullable=False),
        sa.Column("cargo_description", sa.String(length=256), nullable=True),
        sa.Column("temp_min_celsius", sa.Float(), nullable=False),
        sa.Column("temp_max_celsius", sa.Float(), nullable=False),
        sa.Column(
            "requires_pharma_logger",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("forbidden_prior_cargo", sa.String(length=256), nullable=True),
        sa.Column(
            "pickup_location",
            Geometry(geometry_type="POINT", srid=4326, spatial_index=False),
            nullable=False,
        ),
        sa.Column("pickup_city", sa.String(length=64), nullable=False),
        sa.Column(
            "delivery_location",
            Geometry(geometry_type="POINT", srid=4326, spatial_index=False),
            nullable=False,
        ),
        sa.Column("delivery_city", sa.String(length=64), nullable=False),
        sa.Column("pickup_window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("pickup_window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("weight_kg", sa.Float(), nullable=False),
        sa.Column("price_eur", sa.Float(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default=sa.text("'available'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_load_requests_cargo_type", "load_requests", ["cargo_type"])
    op.create_index("ix_load_requests_pickup_city", "load_requests", ["pickup_city"])
    op.create_index("ix_load_requests_delivery_city", "load_requests", ["delivery_city"])
    op.create_index("ix_load_requests_status", "load_requests", ["status"])
    op.create_index(
        "idx_load_requests_pickup_location",
        "load_requests",
        ["pickup_location"],
        postgresql_using="gist",
    )
    op.create_index(
        "idx_load_requests_delivery_location",
        "load_requests",
        ["delivery_location"],
        postgresql_using="gist",
    )

    # ---------- route_history ----------
    op.create_table(
        "route_history",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "truck_id",
            sa.Integer(),
            sa.ForeignKey("trucks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "load_request_id",
            sa.Integer(),
            sa.ForeignKey("load_requests.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "start_location",
            Geometry(geometry_type="POINT", srid=4326, spatial_index=False),
            nullable=False,
        ),
        sa.Column(
            "end_location",
            Geometry(geometry_type="POINT", srid=4326, spatial_index=False),
            nullable=False,
        ),
        sa.Column("start_city", sa.String(length=64), nullable=True),
        sa.Column("end_city", sa.String(length=64), nullable=True),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("distance_km", sa.Float(), nullable=False, server_default=sa.text("0.0")),
        sa.Column("cargo_carried", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_route_history_truck_id", "route_history", ["truck_id"])
    op.create_index("ix_route_history_load_request_id", "route_history", ["load_request_id"])
    op.create_index(
        "idx_route_history_start_location",
        "route_history",
        ["start_location"],
        postgresql_using="gist",
    )
    op.create_index(
        "idx_route_history_end_location",
        "route_history",
        ["end_location"],
        postgresql_using="gist",
    )

    # ---------- wash_certificates ----------
    op.create_table(
        "wash_certificates",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "truck_id",
            sa.Integer(),
            sa.ForeignKey("trucks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("certificate_number", sa.String(length=64), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("wash_type", sa.String(length=32), nullable=False),
        sa.Column("prior_cargo", sa.String(length=64), nullable=True),
        sa.Column("issuing_facility", sa.String(length=128), nullable=True),
        sa.Column(
            "location",
            Geometry(geometry_type="POINT", srid=4326, spatial_index=False),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("certificate_number", name="uq_wash_certificates_number"),
    )
    op.create_index("ix_wash_certificates_truck_id", "wash_certificates", ["truck_id"])
    op.create_index(
        "idx_wash_certificates_location",
        "wash_certificates",
        ["location"],
        postgresql_using="gist",
    )


def downgrade() -> None:
    op.drop_index("idx_wash_certificates_location", table_name="wash_certificates")
    op.drop_index("ix_wash_certificates_truck_id", table_name="wash_certificates")
    op.drop_table("wash_certificates")

    op.drop_index("idx_route_history_end_location", table_name="route_history")
    op.drop_index("idx_route_history_start_location", table_name="route_history")
    op.drop_index("ix_route_history_load_request_id", table_name="route_history")
    op.drop_index("ix_route_history_truck_id", table_name="route_history")
    op.drop_table("route_history")

    op.drop_index("idx_load_requests_delivery_location", table_name="load_requests")
    op.drop_index("idx_load_requests_pickup_location", table_name="load_requests")
    op.drop_index("ix_load_requests_status", table_name="load_requests")
    op.drop_index("ix_load_requests_delivery_city", table_name="load_requests")
    op.drop_index("ix_load_requests_pickup_city", table_name="load_requests")
    op.drop_index("ix_load_requests_cargo_type", table_name="load_requests")
    op.drop_table("load_requests")

    op.drop_index("idx_trucks_current_location", table_name="trucks")
    op.drop_index("ix_trucks_current_city", table_name="trucks")
    op.drop_index("ix_trucks_status", table_name="trucks")
    op.drop_index("ix_trucks_temp_capability", table_name="trucks")
    op.drop_index("ix_trucks_plate_number", table_name="trucks")
    op.drop_table("trucks")

    # Leave PostGIS extension installed; other apps may rely on it.
