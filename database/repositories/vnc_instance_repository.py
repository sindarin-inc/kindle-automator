"""Repository for VNC instance database operations."""

import logging
import socket
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import and_, func, select, update
from sqlalchemy.orm import Session

from database.connection import db_connection
from database.models import VNCInstance

logger = logging.getLogger(__name__)


class VNCInstanceRepository:
    """Repository for VNC instance database operations."""

    def __init__(self):
        """Initialize the repository."""
        self.server_name = socket.gethostname()
        logger.info(
            f"VncInstanceRepository initialized with server_name='{self.server_name}' from socket.gethostname()"
        )

    def get_all_instances(self) -> List[VNCInstance]:
        """Get all VNC instances for the current server."""
        with db_connection.get_session() as session:
            stmt = (
                select(VNCInstance)
                .where(VNCInstance.server_name == self.server_name)
                .order_by(VNCInstance.id)
            )
            return list(session.scalars(stmt).all())

    def get_instance_by_id(self, instance_id: int) -> Optional[VNCInstance]:
        """Get a VNC instance by ID on the current server."""
        with db_connection.get_session() as session:
            stmt = select(VNCInstance).where(
                and_(VNCInstance.id == instance_id, VNCInstance.server_name == self.server_name)
            )
            return session.scalar(stmt)

    def get_instance_by_profile(self, email: str) -> Optional[VNCInstance]:
        """Get the VNC instance assigned to a specific profile on the current server."""
        with db_connection.get_session() as session:
            stmt = select(VNCInstance).where(
                and_(VNCInstance.assigned_profile == email, VNCInstance.server_name == self.server_name)
            )
            instances = list(session.scalars(stmt).all())

            # Check for multiple assignments (should never happen with the new assign_instance_to_profile logic)
            if len(instances) > 1:
                logger.error(
                    f"CRITICAL: User {email} has {len(instances)} VNC instances assigned! "
                    f"Instance IDs: {[i.id for i in instances]}, "
                    f"Displays: {[i.display for i in instances]}, "
                    f"Emulator ports: {[i.emulator_port for i in instances]}, "
                    f"Emulator IDs: {[i.emulator_id for i in instances]}. "
                    f"This violates the one-instance-per-user rule. Returning first instance."
                )
                # Return the first one to maintain backward compatibility, but log the error
                return instances[0]

            return instances[0] if instances else None

    def get_assigned_instances(self) -> List[VNCInstance]:
        """Get all VNC instances that are assigned to profiles on the current server."""
        with db_connection.get_session() as session:
            stmt = (
                select(VNCInstance)
                .where(
                    and_(
                        VNCInstance.assigned_profile.isnot(None), VNCInstance.server_name == self.server_name
                    )
                )
                .order_by(VNCInstance.id)
            )
            return list(session.scalars(stmt).all())

    def get_unassigned_instances(self) -> List[VNCInstance]:
        """Get all VNC instances that are not assigned to any profile on the current server."""
        with db_connection.get_session() as session:
            stmt = (
                select(VNCInstance)
                .where(
                    and_(VNCInstance.assigned_profile.is_(None), VNCInstance.server_name == self.server_name)
                )
                .order_by(VNCInstance.id)
            )
            return list(session.scalars(stmt).all())

    def create_instance(
        self,
        display: int,
        vnc_port: int,
        appium_port: int,
        emulator_port: int,
        appium_system_port: int,
        appium_chromedriver_port: int,
        appium_mjpeg_server_port: int,
        assigned_profile: Optional[str] = None,
    ) -> VNCInstance:
        """Create a new VNC instance for the current server."""
        logger.info(f"Creating VNC instance with server_name='{self.server_name}' for display={display}")
        with db_connection.get_session() as session:
            instance = VNCInstance(
                server_name=self.server_name,
                display=display,
                vnc_port=vnc_port,
                appium_port=appium_port,
                emulator_port=emulator_port,
                appium_system_port=appium_system_port,
                appium_chromedriver_port=appium_chromedriver_port,
                appium_mjpeg_server_port=appium_mjpeg_server_port,
                assigned_profile=assigned_profile,
                appium_running=False,
            )
            session.add(instance)
            session.commit()
            session.refresh(instance)
            return instance

    def assign_instance_to_profile(self, instance_id: int, email: str) -> bool:
        """Assign a VNC instance to a profile on the current server."""
        with db_connection.get_session() as session:
            # CRITICAL: First check if this email already has ANY instance assigned
            existing_check = select(VNCInstance).where(
                and_(VNCInstance.assigned_profile == email, VNCInstance.server_name == self.server_name)
            )
            existing_instances = list(session.scalars(existing_check).all())

            if existing_instances:
                logger.error(
                    f"BLOCKED: Cannot assign instance {instance_id} to {email} - "
                    f"user already has {len(existing_instances)} instance(s) assigned: "
                    f"{[i.id for i in existing_instances]}. Each user must have exactly one instance."
                )
                return False

            # Now proceed with the assignment
            stmt = (
                update(VNCInstance)
                .where(
                    and_(
                        VNCInstance.id == instance_id,
                        VNCInstance.assigned_profile.is_(None),
                        VNCInstance.server_name == self.server_name,
                    )
                )
                .values(assigned_profile=email, updated_at=datetime.now(timezone.utc))
            )
            result = session.execute(stmt)
            session.commit()
            return result.rowcount > 0

    def release_instance_from_profile(self, email: str) -> bool:
        """Release the VNC instance assigned to a profile on the current server."""
        with db_connection.get_session() as session:
            stmt = (
                update(VNCInstance)
                .where(
                    and_(VNCInstance.assigned_profile == email, VNCInstance.server_name == self.server_name)
                )
                .values(
                    assigned_profile=None,
                    emulator_id=None,
                    appium_pid=None,
                    appium_running=False,
                    appium_last_health_check=None,
                    updated_at=datetime.now(timezone.utc),
                )
            )
            result = session.execute(stmt)
            session.commit()
            return result.rowcount > 0

    def update_emulator_id(self, email: str, emulator_id: Optional[str]) -> bool:
        """Update the emulator ID for a profile's assigned instance on the current server."""
        with db_connection.get_session() as session:
            # When setting an emulator ID, we should match by email only
            # The emulator port may not match the assigned port if the emulator was started
            # on a different port or if there was a port mismatch during startup
            if emulator_id and emulator_id.startswith("emulator-"):
                try:
                    # Extract port from emulator ID for logging purposes
                    emulator_port = int(emulator_id.split("-")[1])

                    # First check what port this email is assigned to
                    check_stmt = select(VNCInstance).where(
                        and_(
                            VNCInstance.assigned_profile == email, VNCInstance.server_name == self.server_name
                        )
                    )
                    instance = session.scalar(check_stmt)

                    if not instance:
                        logger.error(f"No VNC instance found for {email} on {self.server_name}")
                        return False

                    if instance.emulator_port != emulator_port:
                        logger.warning(
                            f"Port mismatch for {email}: VNC instance has port {instance.emulator_port} "
                            f"but emulator ID {emulator_id} implies port {emulator_port}. "
                            f"Updating emulator ID anyway based on email match."
                        )

                    # Update by email only, not by port
                    stmt = (
                        update(VNCInstance)
                        .where(
                            and_(
                                VNCInstance.assigned_profile == email,
                                VNCInstance.server_name == self.server_name,
                            )
                        )
                        .values(emulator_id=emulator_id, updated_at=datetime.now(timezone.utc))
                    )
                except (ValueError, IndexError):
                    logger.error(f"Invalid emulator_id format: {emulator_id}")
                    return False
            else:
                # When clearing emulator ID (setting to None), update by email only
                stmt = (
                    update(VNCInstance)
                    .where(
                        and_(
                            VNCInstance.assigned_profile == email, VNCInstance.server_name == self.server_name
                        )
                    )
                    .values(emulator_id=emulator_id, updated_at=datetime.now(timezone.utc))
                )

            result = session.execute(stmt)
            session.commit()
            return result.rowcount > 0

    def update_appium_status(
        self,
        email: str,
        appium_running: bool,
        appium_pid: Optional[int] = None,
        appium_last_health_check: Optional[datetime] = None,
    ) -> bool:
        """Update Appium status for a profile's assigned instance on the current server."""
        with db_connection.get_session() as session:
            values = {
                "appium_running": appium_running,
                "appium_pid": appium_pid,
                "updated_at": datetime.now(timezone.utc),
            }
            if appium_last_health_check is not None:
                values["appium_last_health_check"] = appium_last_health_check

            stmt = (
                update(VNCInstance)
                .where(
                    and_(VNCInstance.assigned_profile == email, VNCInstance.server_name == self.server_name)
                )
                .values(**values)
            )
            result = session.execute(stmt)
            session.commit()
            return result.rowcount > 0

    def reset_all_appium_states(self) -> int:
        """Reset all appium_running states to false on the current server. Returns count of reset instances."""
        with db_connection.get_session() as session:
            stmt = (
                update(VNCInstance)
                .where(and_(VNCInstance.appium_running == True, VNCInstance.server_name == self.server_name))
                .values(
                    appium_running=False,
                    appium_pid=None,
                    updated_at=datetime.now(timezone.utc),
                )
            )
            result = session.execute(stmt)
            session.commit()
            return result.rowcount

    def get_next_available_id(self) -> int:
        """Get the next available instance ID for the current server."""
        with db_connection.get_session() as session:
            stmt = select(func.max(VNCInstance.display)).where(VNCInstance.server_name == self.server_name)
            max_display = session.scalar(stmt)
            return (max_display or 0) + 1

    def bulk_create_instances(self, instances_data: List[dict]) -> List[VNCInstance]:
        """Bulk create multiple VNC instances for the current server."""
        logger.info(
            f"Bulk creating {len(instances_data)} VNC instances with server_name='{self.server_name}'"
        )
        with db_connection.get_session() as session:
            instances = []
            for data in instances_data:
                data["server_name"] = self.server_name
                logger.debug(
                    f"Setting server_name='{self.server_name}' for display={data.get('display', 'unknown')}"
                )
                instance = VNCInstance(**data)
                instances.append(instance)
                session.add(instance)
            session.commit()
            for instance in instances:
                session.refresh(instance)
            return instances

    def clear_stale_emulator_ids(self, active_emulator_ids: List[str]) -> int:
        """Clear emulator IDs that are not in the active list on the current server."""
        with db_connection.get_session() as session:
            stmt = (
                update(VNCInstance)
                .where(
                    and_(
                        VNCInstance.emulator_id.isnot(None),
                        VNCInstance.emulator_id.notin_(active_emulator_ids) if active_emulator_ids else True,
                        VNCInstance.server_name == self.server_name,
                    )
                )
                .values(emulator_id=None, updated_at=datetime.now(timezone.utc))
            )
            result = session.execute(stmt)
            session.commit()
            return result.rowcount

    def get_instance_by_emulator_id(self, emulator_id: str) -> Optional[VNCInstance]:
        """Get a VNC instance by emulator ID on the current server."""
        with db_connection.get_session() as session:
            stmt = select(VNCInstance).where(
                and_(VNCInstance.emulator_id == emulator_id, VNCInstance.server_name == self.server_name)
            )
            return session.scalar(stmt)

    def count_instances(self) -> int:
        """Get total count of VNC instances on the current server."""
        with db_connection.get_session() as session:
            stmt = select(func.count(VNCInstance.id)).where(VNCInstance.server_name == self.server_name)
            return session.scalar(stmt) or 0

    def delete_instance(self, instance_id: int) -> bool:
        """Delete a VNC instance by ID on the current server."""
        with db_connection.get_session() as session:
            instance = session.get(VNCInstance, instance_id)
            if instance and instance.server_name == self.server_name:
                session.delete(instance)
                session.commit()
                return True
            return False

    def mark_booting(self, email: str) -> bool:
        """Mark a VNC instance as booting."""
        with db_connection.get_session() as session:
            stmt = (
                update(VNCInstance)
                .where(
                    and_(VNCInstance.assigned_profile == email, VNCInstance.server_name == self.server_name)
                )
                .values(is_booting=True, boot_started_at=datetime.now(timezone.utc))
            )
            result = session.execute(stmt)
            session.commit()
            return result.rowcount > 0

    def mark_booted(self, email: str) -> bool:
        """Mark a VNC instance as finished booting."""
        with db_connection.get_session() as session:
            stmt = (
                update(VNCInstance)
                .where(
                    and_(VNCInstance.assigned_profile == email, VNCInstance.server_name == self.server_name)
                )
                .values(is_booting=False, boot_started_at=None)
            )
            result = session.execute(stmt)
            session.commit()
            return result.rowcount > 0

    def is_booting(self, email: str) -> bool:
        """Check if a VNC instance is currently booting (non-stale)."""
        with db_connection.get_session() as session:
            stmt = select(VNCInstance).where(
                and_(VNCInstance.assigned_profile == email, VNCInstance.server_name == self.server_name)
            )
            instance = session.scalar(stmt)
            if not instance or not instance.is_booting:
                return False

            # Check if it's stale (booting for more than 60 seconds)
            if instance.boot_started_at:
                from datetime import timedelta

                # PostgreSQL returns naive datetimes, so we need to make them timezone-aware
                # All our timestamps are stored as UTC in the database
                boot_started = instance.boot_started_at
                if boot_started.tzinfo is None:
                    boot_started = boot_started.replace(tzinfo=timezone.utc)

                current_time = datetime.now(timezone.utc)
                elapsed = current_time - boot_started

                if elapsed > timedelta(seconds=60):
                    # It's stale, mark it as not booting
                    logger.warning(
                        f"Found stale booting status for {email} (booting for {elapsed.total_seconds():.1f}s), clearing it"
                    )
                    stmt = (
                        update(VNCInstance)
                        .where(
                            and_(
                                VNCInstance.assigned_profile == email,
                                VNCInstance.server_name == self.server_name,
                            )
                        )
                        .values(is_booting=False, boot_started_at=None)
                    )
                    session.execute(stmt)
                    session.commit()
                    return False

            return True
