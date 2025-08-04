"""Flask-Admin setup for database inspection and management."""

import os

from flask import Flask, redirect, request, url_for
from flask_admin import Admin, AdminIndexView
from flask_admin.contrib.sqla import ModelView
from sqlalchemy.orm import Session, scoped_session

from database.models import (
    Base,
    DeviceIdentifiers,
    EmulatorSettings,
    EmulatorShutdownFailure,
    LibrarySettings,
    ReadingSettings,
    StaffToken,
    User,
    UserPreference,
    VNCInstance,
)


class SecureAdminIndexView(AdminIndexView):
    """Admin index view with staff token auth check."""

    def is_accessible(self):
        """Check if current user can access the admin panel."""
        # Check for staff token
        staff_token = request.cookies.get("staff_token")
        if staff_token:
            # Import here to avoid circular imports
            from database.connection import get_db
            from database.models import StaffToken

            with get_db() as session:
                token = session.query(StaffToken).filter_by(token=staff_token, revoked=False).first()
                if token:
                    return True

        # In development, allow access by default if no token provided
        return os.getenv("FLASK_ENV") == "development" and not staff_token

    def inaccessible_callback(self, name, **kwargs):
        """Redirect to login page when access is denied."""
        return "Access denied. Please use a valid staff token.", 403


class SecureModelView(ModelView):
    """Base model view with common settings."""

    can_view_details = True
    column_display_pk = True
    column_hide_backrefs = False
    can_export = True
    export_types = ["csv", "json"]

    def is_accessible(self):
        """Check if current user can access this view."""
        # Check for staff token
        staff_token = request.cookies.get("staff_token")
        if staff_token:
            # Import here to avoid circular imports
            from database.connection import get_db
            from database.models import StaffToken

            with get_db() as session:
                token = session.query(StaffToken).filter_by(token=staff_token, revoked=False).first()
                if token:
                    return True

        # In development, allow access by default if no token provided
        return os.getenv("FLASK_ENV") == "development" and not staff_token

    def inaccessible_callback(self, name, **kwargs):
        """Redirect to login page when access is denied."""
        return "Access denied. Please use a valid staff token.", 403


class UserView(SecureModelView):
    """Customized view for User model."""

    column_searchable_list = ["email", "avd_name"]
    column_filters = ["email", "avd_name", "last_used", "auth_date", "created_at"]
    column_default_sort = ("last_used", True)
    column_list = [
        "id",
        "email",
        "avd_name",
        "last_used",
        "auth_date",
        "kindle_version_name",
        "android_version",
        "snapshot_dirty",
    ]


class VNCInstanceView(SecureModelView):
    """Customized view for VNC instances."""

    column_searchable_list = ["assigned_profile", "emulator_id"]
    column_filters = ["assigned_profile", "appium_running", "display"]
    column_list = [
        "id",
        "display",
        "vnc_port",
        "appium_port",
        "emulator_port",
        "assigned_profile",
        "appium_running",
    ]


class EmulatorShutdownFailureView(SecureModelView):
    """View for emulator shutdown failures."""

    column_searchable_list = ["user_email", "failure_type", "error_message"]
    column_filters = ["user_email", "failure_type", "created_at"]
    column_default_sort = ("created_at", True)
    column_list = ["id", "user_email", "failure_type", "error_message", "emulator_id", "created_at"]


class StaffTokenView(SecureModelView):
    """View for staff tokens - read only for security."""

    can_create = False
    can_edit = False
    can_delete = False
    column_list = ["id", "token", "created_at", "last_used", "revoked"]
    column_default_sort = ("created_at", True)
    column_formatters = {"token": lambda v, c, m, p: f"{m.token[:8]}..." if m.token else ""}


def init_admin(app: Flask, db_session) -> Admin:
    """Initialize Flask-Admin with all models."""
    admin = Admin(
        app,
        name="Kindle Automator Admin",
        template_mode="bootstrap4",
        index_view=SecureAdminIndexView(),
    )

    # Add all models to admin
    admin.add_view(UserView(User, db_session))
    admin.add_view(VNCInstanceView(VNCInstance, db_session))
    admin.add_view(EmulatorShutdownFailureView(EmulatorShutdownFailure, db_session))
    admin.add_view(SecureModelView(EmulatorSettings, db_session))
    admin.add_view(SecureModelView(DeviceIdentifiers, db_session))
    admin.add_view(SecureModelView(LibrarySettings, db_session))
    admin.add_view(SecureModelView(ReadingSettings, db_session))
    admin.add_view(SecureModelView(UserPreference, db_session))
    admin.add_view(StaffTokenView(StaffToken, db_session))

    return admin
