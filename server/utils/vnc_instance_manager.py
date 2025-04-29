import json
import logging
import os
import random
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Default path to VNC instance mapping file
VNC_INSTANCE_MAP_PATH = "/opt/vnc_instance_map.json"


class VNCInstanceManager:
    """
    Manages multiple VNC instances and assigns them to user profiles.
    """

    def __init__(self, map_path: str = VNC_INSTANCE_MAP_PATH):
        """
        Initialize the VNC instance manager.
        
        Args:
            map_path: Path to the VNC instance mapping JSON file
        """
        self.map_path = map_path
        self.instances = []
        self.load_instances()
        
    def load_instances(self) -> bool:
        """
        Load VNC instance mappings from the JSON file.
        
        Returns:
            bool: True if instances were loaded successfully, False otherwise
        """
        try:
            if os.path.exists(self.map_path):
                with open(self.map_path, 'r') as f:
                    data = json.load(f)
                    self.instances = data.get('instances', [])
                    logger.info(f"Loaded {len(self.instances)} VNC instances from {self.map_path}")
                    return True
            else:
                # Create a default mapping for development environments
                logger.warning(f"VNC instance map not found at {self.map_path}, creating default instances")
                self.instances = self._create_default_instances()
                self.save_instances()
                return True
        except Exception as e:
            logger.error(f"Error loading VNC instances: {e}")
            self.instances = self._create_default_instances()
            return False
    
    def _create_default_instances(self) -> List[Dict]:
        """
        Create default VNC instances for development environments.
        
        Returns:
            List[Dict]: List of default VNC instances
        """
        return [
            {
                "id": i,
                "display": i,
                "vnc_port": 5900 + i,
                "novnc_port": 6080 + i,
                "launcher": f"/usr/local/bin/vnc-emulator-launcher-{i}.sh",
                "assigned_profile": None
            }
            for i in range(1, 9)  # Create 8 default instances
        ]
    
    def save_instances(self) -> bool:
        """
        Save VNC instance mappings to the JSON file.
        
        Returns:
            bool: True if instances were saved successfully, False otherwise
        """
        try:
            data = {
                "instances": self.instances,
                "version": 1
            }
            with open(self.map_path, 'w') as f:
                json.dump(data, f, indent=2)
            logger.info(f"Saved {len(self.instances)} VNC instances to {self.map_path}")
            return True
        except Exception as e:
            logger.error(f"Error saving VNC instances: {e}")
            return False
    
    def get_instance_for_profile(self, email: str) -> Optional[Dict]:
        """
        Get the VNC instance assigned to a specific profile.
        
        Args:
            email: Email address of the profile
            
        Returns:
            Optional[Dict]: VNC instance dictionary or None if not assigned
        """
        # First check if any instance is already assigned to this profile
        for instance in self.instances:
            if instance.get("assigned_profile") == email:
                return instance
        return None
    
    def assign_instance_to_profile(self, email: str, instance_id: Optional[int] = None) -> Optional[Dict]:
        """
        Assign a VNC instance to a profile.
        
        Args:
            email: Email address of the profile
            instance_id: Optional specific instance ID to assign
            
        Returns:
            Optional[Dict]: The assigned instance or None if assignment failed
        """
        # First check if this profile already has an assigned instance
        existing = self.get_instance_for_profile(email)
        if existing:
            logger.info(f"Profile {email} is already assigned to VNC instance {existing['id']}")
            return existing
        
        if instance_id is not None:
            # Try to assign the specified instance
            for instance in self.instances:
                if instance["id"] == instance_id:
                    if instance["assigned_profile"] is None:
                        # Assign this instance
                        instance["assigned_profile"] = email
                        self.save_instances()
                        logger.info(f"Assigned VNC instance {instance_id} to profile {email}")
                        return instance
                    else:
                        logger.warning(f"VNC instance {instance_id} is already assigned to {instance['assigned_profile']}")
                        return None
                        
            logger.warning(f"VNC instance {instance_id} not found")
            return None
        
        # Find an available instance to assign
        for instance in self.instances:
            if instance["assigned_profile"] is None:
                # Found an available instance
                instance["assigned_profile"] = email
                self.save_instances()
                logger.info(f"Assigned VNC instance {instance['id']} to profile {email}")
                return instance
        
        # No available instances, try to find the least recently used
        # This would require timestamp tracking, which we'll implement later if needed
        
        # For now, just return None indicating no instances are available
        logger.warning(f"No available VNC instances for profile {email}")
        return None
    
    def release_instance_from_profile(self, email: str) -> bool:
        """
        Release the VNC instance assigned to a profile.
        
        Args:
            email: Email address of the profile
            
        Returns:
            bool: True if an instance was released, False otherwise
        """
        for instance in self.instances:
            if instance.get("assigned_profile") == email:
                instance["assigned_profile"] = None
                self.save_instances()
                logger.info(f"Released VNC instance {instance['id']} from profile {email}")
                return True
        
        logger.info(f"No VNC instance found assigned to profile {email}")
        return False
    
    def get_novnc_url(self, email: str, host: str = "localhost") -> Optional[str]:
        """
        Get the noVNC URL for a profile's assigned instance.
        
        Args:
            email: Email address of the profile
            host: Host name or IP address
            
        Returns:
            Optional[str]: The noVNC URL or None if no instance is assigned
        """
        instance = self.get_instance_for_profile(email)
        if instance:
            port = instance["novnc_port"]
            # Always include the default VNC password ("changeme")
            # This will be overridden if a password parameter is provided in the request
            return f"http://{host}:{port}/vnc.html?autoconnect=true&password=changeme"
        return None
    
    def get_vnc_port(self, email: str) -> Optional[int]:
        """
        Get the VNC port for a profile's assigned instance.
        
        Args:
            email: Email address of the profile
            
        Returns:
            Optional[int]: The VNC port or None if no instance is assigned
        """
        instance = self.get_instance_for_profile(email)
        if instance:
            return instance["vnc_port"]
        return None
    
    def get_x_display(self, email: str) -> Optional[int]:
        """
        Get the X display number for a profile's assigned instance.
        
        Args:
            email: Email address of the profile
            
        Returns:
            Optional[int]: The X display number or None if no instance is assigned
        """
        instance = self.get_instance_for_profile(email)
        if instance:
            return instance["display"]
        return None
    
    def get_launcher_script(self, email: str) -> Optional[str]:
        """
        Get the emulator launcher script for a profile's assigned instance.
        
        Args:
            email: Email address of the profile
            
        Returns:
            Optional[str]: Path to the launcher script or None if no instance is assigned
        """
        instance = self.get_instance_for_profile(email)
        if instance:
            return instance["launcher"]
        return None