import logging
import os
import signal
import subprocess
from typing import Optional

logger = logging.getLogger(__name__)


class ProcessManager:
    def __init__(self, pid_dir: str = "logs"):
        self.pid_dir = pid_dir
        os.makedirs(pid_dir, exist_ok=True)

    def save_pid(self, name: str, pid: int):
        """Save process ID to file"""
        with open(os.path.join(self.pid_dir, f"{name}.pid"), "w") as f:
            f.write(str(pid))

    def get_pid(self, name: str) -> Optional[int]:
        """Get process ID from file"""
        try:
            with open(os.path.join(self.pid_dir, f"{name}.pid")) as f:
                return int(f.read().strip())
        except:
            return None

    def kill_process(self, name: str):
        """Kill process by name"""
        pid = self.get_pid(name)
        if pid:
            try:
                os.kill(pid, signal.SIGTERM)
                logger.info(f"Killed {name} process with PID {pid}")
            except ProcessLookupError:
                logger.info(f"No {name} process found with PID {pid}")
            except Exception as e:
                logger.error(f"Error killing {name} process: {e}")
            finally:
                self.remove_pid(name)

    def remove_pid(self, name: str):
        """Remove PID file"""
        try:
            os.remove(os.path.join(self.pid_dir, f"{name}.pid"))
        except:
            pass
