"""Repository for user data access with atomic operations."""

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, selectinload

from database.models import (
    DeviceIdentifiers,
    EmulatorSettings,
    LibrarySettings,
    ReadingSettings,
    User,
    UserPreference,
)

logger = logging.getLogger(__name__)


class UserRepository:
    """Repository for managing user data with atomic database operations."""

    def __init__(self, session: Session):
        self.session = session

    def get_user_by_email(self, email: str) -> Optional[User]:
        """
        Get a user by email address with all related data.

        Args:
            email: The user's email address

        Returns:
            User object with all relationships loaded, or None if not found
        """
        try:
            stmt = (
                select(User)
                .where(User.email == email)
                .options(
                    selectinload(User.emulator_settings),
                    selectinload(User.device_identifiers),
                    selectinload(User.library_settings),
                    selectinload(User.reading_settings),
                    selectinload(User.preferences),
                )
            )
            return self.session.execute(stmt).scalar_one_or_none()
        except SQLAlchemyError as e:
            logger.error(f"Error fetching user by email {email}: {e}")
            raise

    def create_user(self, email: str, avd_name: Optional[str] = None) -> User:
        """
        Create a new user with default settings.

        Args:
            email: The user's email address
            avd_name: Optional AVD name

        Returns:
            The created User object
        """
        try:
            user = User(email=email, avd_name=avd_name)
            self.session.add(user)

            # Create default related records
            emulator_settings = EmulatorSettings(user=user)
            device_identifiers = DeviceIdentifiers(user=user)
            library_settings = LibrarySettings(user=user)
            reading_settings = ReadingSettings(user=user)

            self.session.add_all(
                [
                    emulator_settings,
                    device_identifiers,
                    library_settings,
                    reading_settings,
                ]
            )

            self.session.commit()
            self.session.refresh(user)
            logger.debug(f"Created new user: {email}")
            return user
        except IntegrityError as e:
            self.session.rollback()
            logger.error(f"User {email} already exists: {e}")
            raise
        except SQLAlchemyError as e:
            self.session.rollback()
            logger.error(f"Error creating user {email}: {e}")
            raise

    def get_or_create_user(self, email: str, avd_name: Optional[str] = None) -> tuple[User, bool]:
        """
        Get an existing user or create a new one.

        Args:
            email: The user's email address
            avd_name: Optional AVD name for new users

        Returns:
            Tuple of (User object, was_created boolean)
        """
        user = self.get_user_by_email(email)
        if user:
            return user, False
        else:
            user = self.create_user(email, avd_name)
            return user, True

    def update_user_field(self, email: str, field: str, value: Any) -> bool:
        """
        Update a specific field for a user atomically.

        Args:
            email: The user's email address
            field: The field name to update
            value: The new value

        Returns:
            True if update was successful, False otherwise
        """
        try:
            # Handle nested fields
            if "." in field:
                return self._update_nested_field(email, field, value)

            # Handle top-level user fields
            stmt = (
                update(User)
                .where(User.email == email)
                .values({field: value, "updated_at": datetime.now(timezone.utc)})
            )
            result = self.session.execute(stmt)
            self.session.commit()

            if result.rowcount > 0:
                logger.debug(f"Updated {field} for user {email}")
                return True
            else:
                logger.warning(f"No user found with email {email}")
                return False

        except SQLAlchemyError as e:
            self.session.rollback()
            logger.error(f"Error updating field {field} for user {email}: {e}")
            raise

    def _update_nested_field(self, email: str, field_path: str, value: Any) -> bool:
        """Update a nested field (e.g., emulator_settings.hw_overlays_disabled)."""
        parts = field_path.split(".", 1)
        section = parts[0]
        field = parts[1] if len(parts) > 1 else None

        user = self.get_user_by_email(email)
        if not user:
            logger.warning(f"No user found with email {email}")
            return False

        try:
            if section == "emulator_settings":
                if not user.emulator_settings:
                    user.emulator_settings = EmulatorSettings(user=user)
                try:
                    setattr(user.emulator_settings, field, value)
                except AttributeError as e:
                    logger.error(f"Field '{field}' does not exist in EmulatorSettings model: {e}")
                    return False

            elif section == "device_identifiers":
                if not user.device_identifiers:
                    user.device_identifiers = DeviceIdentifiers(user=user)
                try:
                    setattr(user.device_identifiers, field, value)
                except AttributeError as e:
                    logger.error(f"Field '{field}' does not exist in DeviceIdentifiers model: {e}")
                    return False

            elif section == "library_settings":
                if not user.library_settings:
                    user.library_settings = LibrarySettings(user=user)
                try:
                    setattr(user.library_settings, field, value)
                except AttributeError as e:
                    logger.error(f"Field '{field}' does not exist in LibrarySettings model: {e}")
                    return False

            elif section == "reading_settings":
                if not user.reading_settings:
                    user.reading_settings = ReadingSettings(user=user)
                try:
                    setattr(user.reading_settings, field, value)
                except AttributeError as e:
                    logger.error(f"Field '{field}' does not exist in ReadingSettings model: {e}")
                    return False

            elif section == "preferences":
                self._update_preference(user, field, value)

            else:
                logger.error(f"Unknown section: {section}")
                return False

            user.updated_at = datetime.now(timezone.utc)
            user.version += 1
            self.session.commit()
            return True

        except SQLAlchemyError as e:
            self.session.rollback()
            logger.error(f"Error updating nested field {field_path}: {e}")
            raise

    def _update_preference(self, user: User, key: str, value: Any) -> None:
        """Update or create a user preference."""
        from sqlalchemy.dialects.postgresql import insert

        # Convert value to string format for storage
        str_value = json.dumps(value) if not isinstance(value, str) else value

        # Use PostgreSQL's INSERT ... ON CONFLICT for atomic upsert
        stmt = insert(UserPreference).values(user_id=user.id, preference_key=key, preference_value=str_value)
        stmt = stmt.on_conflict_do_update(
            index_elements=["user_id", "preference_key"],
            set_={"preference_value": stmt.excluded.preference_value},
        )
        self.session.execute(stmt)

        # Refresh the user's preferences relationship to ensure consistency
        self.session.expire(user, ["preferences"])

    def update_last_used(self, email: str, emulator_id: Optional[str] = None) -> bool:
        """
        Update the last_used timestamp for a user.

        Args:
            email: The user's email address
            emulator_id: Optional emulator ID (not stored but logged)

        Returns:
            True if update was successful
        """
        try:
            now = datetime.now(timezone.utc)
            stmt = update(User).where(User.email == email).values(last_used=now, updated_at=now)
            result = self.session.execute(stmt)
            self.session.commit()

            if result.rowcount > 0:
                logger.debug(f"Updated last_used for {email}")
                if emulator_id:
                    logger.debug(f"Emulator ID: {emulator_id}")
                return True
            return False

        except SQLAlchemyError as e:
            self.session.rollback()
            logger.error(f"Error updating last_used for {email}: {e}")
            raise

    def update_auth_state(self, email: str, authenticated: bool) -> bool:
        """
        Update authentication state for a user.

        Args:
            email: The user's email address
            authenticated: Whether the user is authenticated

        Returns:
            True if update was successful
        """
        try:
            values = {"updated_at": datetime.now(timezone.utc)}
            if authenticated:
                values["auth_date"] = datetime.now(timezone.utc)
                values["auth_failed_date"] = None  # Clear any previous auth failure
            else:
                values["auth_failed_date"] = datetime.now(timezone.utc)

            stmt = update(User).where(User.email == email).values(**values)
            result = self.session.execute(stmt)
            self.session.commit()

            return result.rowcount > 0

        except SQLAlchemyError as e:
            self.session.rollback()
            logger.error(f"Error updating auth state for {email}: {e}")
            raise

    def get_all_users(self) -> List[User]:
        """
        Get all users with their related data.

        Returns:
            List of all User objects
        """
        try:
            stmt = select(User).options(
                selectinload(User.emulator_settings),
                selectinload(User.device_identifiers),
                selectinload(User.library_settings),
                selectinload(User.reading_settings),
                selectinload(User.preferences),
            )
            return list(self.session.execute(stmt).scalars())
        except SQLAlchemyError as e:
            logger.error(f"Error fetching all users: {e}")
            raise

    def get_recently_used_users(self, limit: int = 10) -> List[User]:
        """
        Get recently used users ordered by last_used timestamp.

        Args:
            limit: Maximum number of users to return

        Returns:
            List of User objects ordered by last_used DESC
        """
        try:
            stmt = (
                select(User)
                .where(User.last_used.isnot(None))
                .order_by(User.last_used.desc())
                .limit(limit)
                .options(
                    selectinload(User.emulator_settings),
                    selectinload(User.device_identifiers),
                    selectinload(User.library_settings),
                    selectinload(User.reading_settings),
                    selectinload(User.preferences),
                )
            )
            return list(self.session.execute(stmt).scalars())
        except SQLAlchemyError as e:
            logger.error(f"Error fetching recently used users: {e}")
            raise

    def user_to_dict(self, user: User) -> Dict[str, Any]:
        """
        Convert a User object to a dictionary matching the old JSON format.

        Args:
            user: The User object to convert

        Returns:
            Dictionary representation of the user
        """
        result = {
            "email": user.email,
            "avd_name": user.avd_name,
            "last_used": int(user.last_used.timestamp()) if user.last_used else None,
            "last_used_date": user.last_used.isoformat() if user.last_used else None,
            "auth_date": user.auth_date.isoformat() if user.auth_date else None,
            "was_running_at_restart": user.was_running_at_restart,
            "restart_on_server": user.restart_on_server,
            "styles_updated": user.styles_updated,
            "timezone": user.timezone,
            "created_from_seed_clone": user.created_from_seed_clone,
            "post_boot_randomized": user.post_boot_randomized,
            "needs_device_randomization": user.needs_device_randomization,
            "last_snapshot_timestamp": (
                user.last_snapshot_timestamp.isoformat() if user.last_snapshot_timestamp else None
            ),
            "last_snapshot": user.last_snapshot,
            "kindle_version_name": user.kindle_version_name,
            "kindle_version_code": user.kindle_version_code,
        }

        # Add emulator settings
        if user.emulator_settings:
            result["emulator_settings"] = {
                "hw_overlays_disabled": user.emulator_settings.hw_overlays_disabled,
                "animations_disabled": user.emulator_settings.animations_disabled,
                "sleep_disabled": user.emulator_settings.sleep_disabled,
                "status_bar_disabled": user.emulator_settings.status_bar_disabled,
                "auto_updates_disabled": user.emulator_settings.auto_updates_disabled,
                "memory_optimizations_applied": user.emulator_settings.memory_optimizations_applied,
                "memory_optimization_timestamp": (
                    int(user.emulator_settings.memory_optimization_timestamp.timestamp())
                    if user.emulator_settings.memory_optimization_timestamp
                    else None
                ),
                "appium_device_initialized": user.emulator_settings.appium_device_initialized,
                "keyboard_disabled": user.emulator_settings.keyboard_disabled,
            }

        # Add device identifiers
        if user.device_identifiers:
            result["device_identifiers"] = {
                "hw.wifi.mac": user.device_identifiers.hw_wifi_mac,
                "hw.ethernet.mac": user.device_identifiers.hw_ethernet_mac,
                "ro.serialno": user.device_identifiers.ro_serialno,
                "ro.build.id": user.device_identifiers.ro_build_id,
                "ro.product.name": user.device_identifiers.ro_product_name,
                "android_id": user.device_identifiers.android_id,
            }

        # Add library settings
        if user.library_settings:
            result["library_settings"] = {
                "view_type": user.library_settings.view_type,
                "group_by_series": user.library_settings.group_by_series,
                "actively_reading_title": user.library_settings.actively_reading_title,
            }

        # Add reading settings
        if user.reading_settings:
            result["reading_settings"] = {
                "theme": user.reading_settings.theme,
                "font_size": user.reading_settings.font_size,
                "real_time_highlighting": user.reading_settings.real_time_highlighting,
                "about_book": user.reading_settings.about_book,
                "page_turn_animation": user.reading_settings.page_turn_animation,
                "popular_highlights": user.reading_settings.popular_highlights,
                "highlight_menu": user.reading_settings.highlight_menu,
            }

        # Add preferences
        if user.preferences:
            result["preferences"] = {
                pref.preference_key: (
                    json.loads(pref.preference_value)
                    if pref.preference_value and pref.preference_value.startswith(("[", "{"))
                    else pref.preference_value
                )
                for pref in user.preferences
            }
        else:
            result["preferences"] = {}

        return result

    def get_users_with_restart_flag(self) -> List[User]:
        """Get users who have was_running_at_restart flag set to True."""
        try:
            stmt = (
                select(User)
                .where(User.was_running_at_restart == True)
                .options(selectinload(User.emulator_settings))
            )
            return list(self.session.execute(stmt).scalars())
        except SQLAlchemyError as e:
            logger.error(f"Database error getting users with restart flag: {e}")
            return []

    def clear_restart_flags(self) -> int:
        """Clear all was_running_at_restart flags and return count of updated records."""
        try:
            stmt = update(User).where(User.was_running_at_restart == True).values(was_running_at_restart=None)
            result = self.session.execute(stmt)
            self.session.commit()
            return result.rowcount
        except SQLAlchemyError as e:
            logger.error(f"Database error clearing restart flags: {e}")
            self.session.rollback()
            return 0

    def clear_restart_flags_and_servers(self) -> int:
        """Clear all was_running_at_restart flags and restart_on_server values."""
        try:
            stmt = (
                update(User)
                .where(User.was_running_at_restart == True)
                .values(was_running_at_restart=None, restart_on_server=None)
            )
            result = self.session.execute(stmt)
            self.session.commit()
            return result.rowcount
        except SQLAlchemyError as e:
            logger.error(f"Database error clearing restart flags and servers: {e}")
            self.session.rollback()
            return 0

    def get_user_by_emulator_id(self, emulator_id: str) -> Optional[User]:
        """Get user by emulator_id stored in preferences."""
        try:
            # Look for emulator_id in user preferences
            stmt = (
                select(User)
                .join(UserPreference)
                .where(UserPreference.preference_key == "emulator_id")
                .where(UserPreference.preference_value == emulator_id)
                .options(selectinload(User.emulator_settings), selectinload(User.preferences))
            )
            return self.session.execute(stmt).scalar_one_or_none()
        except SQLAlchemyError as e:
            logger.error(f"Database error getting user by emulator_id: {e}")
            return None

    def get_inactive_users(self, cutoff_datetime: datetime) -> List[User]:
        """Get users who haven't been active since the cutoff date and aren't in cold storage."""
        try:
            # First, get users who have cold_storage_date set (to exclude them)
            cold_storage_subquery = (
                select(User.id)
                .join(UserPreference)
                .where(UserPreference.preference_key == "cold_storage_date")
                .where(UserPreference.preference_value.is_not(None))
            )

            # Get users with last_used before cutoff and not in cold storage
            stmt = (
                select(User)
                .where(User.last_used < cutoff_datetime)
                .where(User.id.notin_(cold_storage_subquery))
                .where(User.email != "seed_clone@amazon.com")  # Never archive seed clone
                .options(selectinload(User.preferences))
            )
            return list(self.session.execute(stmt).scalars())
        except SQLAlchemyError as e:
            logger.error(f"Database error getting inactive users: {e}")
            return []

    def get_users_with_avd_names(self, avd_names: List[str]) -> List[User]:
        """Get users who have one of the specified AVD names."""
        try:
            stmt = (
                select(User)
                .where(User.avd_name.in_(avd_names))
                .options(selectinload(User.emulator_settings), selectinload(User.preferences))
            )
            return list(self.session.execute(stmt).scalars())
        except SQLAlchemyError as e:
            logger.error(f"Database error getting users by AVD names: {e}")
            return []

    def clear_emulator_settings(self, email: str) -> bool:
        """
        Clear all emulator settings for a user by resetting to defaults.

        Args:
            email: The user's email address

        Returns:
            True if successful, False otherwise
        """
        try:
            user = self.get_user_by_email(email)
            if not user:
                logger.warning(f"User {email} not found")
                return False

            if not user.emulator_settings:
                user.emulator_settings = EmulatorSettings(user=user)

            # Reset all settings to defaults
            user.emulator_settings.hw_overlays_disabled = False
            user.emulator_settings.animations_disabled = False
            user.emulator_settings.sleep_disabled = False
            user.emulator_settings.status_bar_disabled = False
            user.emulator_settings.auto_updates_disabled = False
            user.emulator_settings.memory_optimizations_applied = False
            user.emulator_settings.memory_optimization_timestamp = None
            user.emulator_settings.appium_device_initialized = False
            user.emulator_settings.keyboard_disabled = False

            user.updated_at = datetime.now(timezone.utc)
            user.version += 1
            self.session.commit()

            logger.debug(f"Cleared emulator settings for {email}")
            return True

        except SQLAlchemyError as e:
            self.session.rollback()
            logger.error(f"Error clearing emulator settings for {email}: {e}")
            return False

    def update_snapshot_dirty_status(
        self, email: str, is_dirty: bool, dirty_since: Optional[datetime] = None
    ) -> bool:
        """
        Update snapshot dirty status for a user.

        Args:
            email: The user's email address
            is_dirty: Whether the snapshot is dirty
            dirty_since: When the snapshot became dirty (None if clearing)

        Returns:
            True if successful, False otherwise
        """
        try:
            values = {
                "snapshot_dirty": is_dirty,
                "snapshot_dirty_since": dirty_since,
                "updated_at": datetime.now(timezone.utc),
            }

            stmt = update(User).where(User.email == email).values(**values)
            result = self.session.execute(stmt)
            self.session.commit()

            if result.rowcount > 0:
                logger.debug(f"Updated snapshot dirty status for {email}: dirty={is_dirty}")
                return True
            return False

        except SQLAlchemyError as e:
            self.session.rollback()
            logger.error(f"Error updating snapshot dirty status for {email}: {e}")
            return False
