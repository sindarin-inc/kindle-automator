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
            return session.scalar(stmt)

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
            stmt = (
                update(VNCInstance)
                .where(
                    and_(VNCInstance.assigned_profile == email, VNCInstance.server_name == self.server_name)
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
