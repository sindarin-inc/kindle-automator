"""SQLAlchemy 2.0 ORM models for Kindle Automator."""

from datetime import datetime
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
    was_running_at_restart: Mapped[Optional[bool]] = mapped_column(Boolean)
    styles_updated: Mapped[bool] = mapped_column(Boolean, default=False)
    timezone: Mapped[Optional[str]] = mapped_column(String(50))
    created_from_seed_clone: Mapped[bool] = mapped_column(Boolean, default=False)
    post_boot_randomized: Mapped[bool] = mapped_column(Boolean, default=False)
    needs_device_randomization: Mapped[bool] = mapped_column(Boolean, default=False)
    last_snapshot_timestamp: Mapped[Optional[datetime]] = mapped_column(DateTime)
    last_snapshot: Mapped[Optional[str]] = mapped_column(String(255))
    kindle_version_name: Mapped[Optional[str]] = mapped_column(String(50))
    kindle_version_code: Mapped[Optional[str]] = mapped_column(String(50))
    android_version: Mapped[Optional[str]] = mapped_column(String(10))
    system_image: Mapped[Optional[str]] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
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
