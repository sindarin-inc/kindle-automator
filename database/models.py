"""SQLAlchemy 2.0 ORM models for Kindle Automator."""

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Base class for all models."""

    pass


class User(Base):
    """User model representing a Kindle account profile."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    avd_name: Mapped[Optional[str]] = mapped_column(String(255))
    last_used: Mapped[Optional[datetime]] = mapped_column(DateTime, index=True)
    auth_date: Mapped[Optional[datetime]] = mapped_column(DateTime)
    auth_failed_date: Mapped[Optional[datetime]] = mapped_column(DateTime)
    was_running_at_restart: Mapped[Optional[bool]] = mapped_column(Boolean)
    styles_updated: Mapped[bool] = mapped_column(Boolean, default=False)
    timezone: Mapped[Optional[str]] = mapped_column(String(50))
    created_from_seed_clone: Mapped[bool] = mapped_column(Boolean, default=False)
    post_boot_randomized: Mapped[bool] = mapped_column(Boolean, default=False)
    needs_device_randomization: Mapped[bool] = mapped_column(Boolean, default=False)
    last_snapshot_timestamp: Mapped[Optional[datetime]] = mapped_column(DateTime)
    last_snapshot: Mapped[Optional[str]] = mapped_column(String(255))
    snapshot_dirty: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    snapshot_dirty_since: Mapped[Optional[datetime]] = mapped_column(DateTime)
    cold_storage_date: Mapped[Optional[datetime]] = mapped_column(DateTime)
    kindle_version_name: Mapped[Optional[str]] = mapped_column(String(50))
    kindle_version_code: Mapped[Optional[str]] = mapped_column(String(50))
    android_version: Mapped[Optional[str]] = mapped_column(String(10))
    system_image: Mapped[Optional[str]] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    # Relationships
    emulator_settings: Mapped["EmulatorSettings"] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
    device_identifiers: Mapped["DeviceIdentifiers"] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
    library_settings: Mapped["LibrarySettings"] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
    reading_settings: Mapped["ReadingSettings"] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
    preferences: Mapped[list["UserPreference"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    vnc_instance: Mapped[Optional["VNCInstance"]] = relationship(back_populates="user", uselist=False)

    def __repr__(self) -> str:
        return f"<User(email={self.email}, avd_name={self.avd_name})>"


class EmulatorSettings(Base):
    """Emulator settings for a user."""

    __tablename__ = "emulator_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    hw_overlays_disabled: Mapped[bool] = mapped_column(Boolean, default=False)
    animations_disabled: Mapped[bool] = mapped_column(Boolean, default=False)
    sleep_disabled: Mapped[bool] = mapped_column(Boolean, default=False)
    status_bar_disabled: Mapped[bool] = mapped_column(Boolean, default=False)
    auto_updates_disabled: Mapped[bool] = mapped_column(Boolean, default=False)
    memory_optimizations_applied: Mapped[bool] = mapped_column(Boolean, default=False)
    memory_optimization_timestamp: Mapped[Optional[datetime]] = mapped_column(DateTime)
    appium_device_initialized: Mapped[bool] = mapped_column(Boolean, default=False)
    keyboard_disabled: Mapped[bool] = mapped_column(Boolean, default=False)

    # Relationship
    user: Mapped["User"] = relationship(back_populates="emulator_settings")


class DeviceIdentifiers(Base):
    """Device identifiers for a user's AVD."""

    __tablename__ = "device_identifiers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    hw_wifi_mac: Mapped[Optional[str]] = mapped_column(String(20))
    hw_ethernet_mac: Mapped[Optional[str]] = mapped_column(String(20))
    ro_serialno: Mapped[Optional[str]] = mapped_column(String(50))
    ro_build_id: Mapped[Optional[str]] = mapped_column(String(50))
    ro_product_name: Mapped[Optional[str]] = mapped_column(String(100))
    android_id: Mapped[Optional[str]] = mapped_column(String(50))

    # Relationship
    user: Mapped["User"] = relationship(back_populates="device_identifiers")


class LibrarySettings(Base):
    """Library display settings for a user."""

    __tablename__ = "library_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    view_type: Mapped[Optional[str]] = mapped_column(String(20))
    group_by_series: Mapped[bool] = mapped_column(Boolean, default=False)
    actively_reading_title: Mapped[Optional[str]] = mapped_column(Text)
    filter_book_count: Mapped[Optional[int]] = mapped_column(Integer)
    scroll_book_count: Mapped[Optional[int]] = mapped_column(Integer)
    last_series_group_check: Mapped[Optional[datetime]] = mapped_column(DateTime)

    # Relationship
    user: Mapped["User"] = relationship(back_populates="library_settings")


class ReadingSettings(Base):
    """Reading display settings for a user."""

    __tablename__ = "reading_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    theme: Mapped[Optional[str]] = mapped_column(String(20))
    font_size: Mapped[Optional[str]] = mapped_column(String(20))
    real_time_highlighting: Mapped[bool] = mapped_column(Boolean, default=False)
    about_book: Mapped[bool] = mapped_column(Boolean, default=False)
    page_turn_animation: Mapped[bool] = mapped_column(Boolean, default=False)
    popular_highlights: Mapped[bool] = mapped_column(Boolean, default=False)
    highlight_menu: Mapped[bool] = mapped_column(Boolean, default=False)

    # Relationship
    user: Mapped["User"] = relationship(back_populates="reading_settings")


class UserPreference(Base):
    """Generic key-value preferences for a user."""

    __tablename__ = "user_preferences"
    __table_args__ = (UniqueConstraint("user_id", "preference_key", name="uq_user_preference"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    preference_key: Mapped[str] = mapped_column(String(255), nullable=False)
    preference_value: Mapped[Optional[str]] = mapped_column(Text)

    # Relationship
    user: Mapped["User"] = relationship(back_populates="preferences")


class VNCInstance(Base):
    """VNC instance representing a virtual display and associated ports."""

    __tablename__ = "vnc_instances"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    server_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    display: Mapped[int] = mapped_column(Integer, nullable=False)
    vnc_port: Mapped[int] = mapped_column(Integer, nullable=False)
    appium_port: Mapped[int] = mapped_column(Integer, nullable=False)
    emulator_port: Mapped[int] = mapped_column(Integer, nullable=False)
    emulator_id: Mapped[Optional[str]] = mapped_column(String(50))
    assigned_profile: Mapped[Optional[str]] = mapped_column(
        String(255), ForeignKey("users.email", ondelete="SET NULL"), index=True
    )
    appium_pid: Mapped[Optional[int]] = mapped_column(Integer)
    appium_running: Mapped[bool] = mapped_column(Boolean, default=False)
    appium_last_health_check: Mapped[Optional[datetime]] = mapped_column(DateTime)
    appium_system_port: Mapped[int] = mapped_column(Integer, nullable=False)
    appium_chromedriver_port: Mapped[int] = mapped_column(Integer, nullable=False)
    appium_mjpeg_server_port: Mapped[int] = mapped_column(Integer, nullable=False)
    is_booting: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    boot_started_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationship
    user: Mapped[Optional["User"]] = relationship(back_populates="vnc_instance")

    # Table constraints and indexes
    __table_args__ = (
        UniqueConstraint("server_name", "display", name="uq_vnc_server_display"),
        UniqueConstraint("server_name", "vnc_port", name="uq_vnc_server_vnc_port"),
        UniqueConstraint("server_name", "appium_port", name="uq_vnc_server_appium_port"),
        UniqueConstraint("server_name", "emulator_port", name="uq_vnc_server_emulator_port"),
        UniqueConstraint("server_name", "appium_system_port", name="uq_vnc_server_appium_system_port"),
        UniqueConstraint(
            "server_name", "appium_chromedriver_port", name="uq_vnc_server_appium_chromedriver_port"
        ),
        UniqueConstraint(
            "server_name", "appium_mjpeg_server_port", name="uq_vnc_server_appium_mjpeg_server_port"
        ),
        Index("idx_vnc_assigned_profile", "assigned_profile"),
        Index("idx_vnc_server_name", "server_name"),
    )

    def __repr__(self) -> str:
        return f"<VNCInstance(id={self.id}, server_name={self.server_name}, display={self.display}, assigned_profile={self.assigned_profile})>"


class StaffToken(Base):
    """Staff authentication token."""

    __tablename__ = "staff_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    token: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )
    last_used: Mapped[Optional[datetime]] = mapped_column(DateTime)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    def __repr__(self) -> str:
        return f"<StaffToken(id={self.id}, token={self.token[:8]}..., revoked={self.revoked})>"


class EmulatorShutdownFailure(Base):
    """Tracks emulator shutdown failures, particularly snapshot/placemark sync failures."""

    __tablename__ = "emulator_shutdown_failures"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    failure_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    stdout: Mapped[Optional[str]] = mapped_column(Text)
    stderr: Mapped[Optional[str]] = mapped_column(Text)
    emulator_id: Mapped[Optional[str]] = mapped_column(String(50))
    snapshot_attempted: Mapped[bool] = mapped_column(Boolean, default=False)
    placemark_sync_attempted: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False, index=True
    )

    def __repr__(self) -> str:
        return f"<EmulatorShutdownFailure(id={self.id}, user_email={self.user_email}, failure_type={self.failure_type})>"
