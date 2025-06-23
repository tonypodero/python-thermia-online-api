from typing import List, Optional, Tuple

from ThermiaOnlineAPI.api.ThermiaAPI import ThermiaAPI
from ThermiaOnlineAPI.exceptions import AuthenticationException, NetworkException
from ThermiaOnlineAPI.model.HeatPump import ThermiaHeatPump


class Thermia:
    def __init__(self, username: str = None, password: str = None,
                 access_token: str = None, refresh_token: str = None):
        """
        Initialize Thermia API client with flexible authentication options

        Args:
            username: User email/username (required if tokens not provided)
            password: User password (required if tokens not provided)
            access_token: Existing access token (optional)
            refresh_token: Existing refresh token (optional)

        Examples:
            # Credential authentication
            thermia = Thermia("user@example.com", "password")

            # Token authentication
            thermia = Thermia(access_token="token", refresh_token="refresh")

            # Mixed with fallback
            thermia = Thermia("user@example.com", "password", "token", "refresh")
        """
        # Store credentials for potential re-authentication
        self._username = username
        self._password = password

        # Initialize the improved API
        self.api_interface = ThermiaAPI(
            email=username,
            password=password,
            access_token=access_token,
            refresh_token=refresh_token
        )

        # For backward compatibility
        self.connected = self.api_interface.authenticated

        # Initialize heat pumps
        self.heat_pumps = self.fetch_heat_pumps()

    def fetch_heat_pumps(self) -> List[ThermiaHeatPump]:
        """
        Fetch and initialize heat pump objects

        Returns:
            List of ThermiaHeatPump objects
        """
        try:
            devices = self.api_interface.get_devices()
            heat_pumps = []

            for device in devices:
                heat_pumps.append(ThermiaHeatPump(device, self.api_interface))

            return heat_pumps

        except Exception as e:
            print(f"Error fetching heat pumps: {e}")
            return []

    def update_data(self) -> None:
        """
        Update data for all heat pumps
        """
        for heat_pump in self.heat_pumps:
            heat_pump.update_data()

    def get_tokens(self) -> Tuple[Optional[str], Optional[str]]:
        """
        Get current authentication tokens for storage/reuse

        Returns:
            Tuple of (access_token, refresh_token)
        """
        return self.api_interface.get_tokens()

    def update_tokens(self, access_token: str, refresh_token: str = None) -> None:
        """
        Update authentication tokens

        Args:
            access_token: New access token
            refresh_token: New refresh token (optional)
        """
        self.api_interface.update_tokens(access_token, refresh_token)
        self.connected = self.api_interface.authenticated

    def refresh_heat_pumps(self) -> List[ThermiaHeatPump]:
        """
        Force refresh of heat pumps list (useful after authentication changes)

        Returns:
            Updated list of ThermiaHeatPump objects
        """
        self.heat_pumps = self.fetch_heat_pumps()
        return self.heat_pumps

    def is_authenticated(self) -> bool:
        """
        Check if the API is currently authenticated

        Returns:
            True if authenticated, False otherwise
        """
        return self.api_interface.authenticated

    def get_device_count(self) -> int:
        """
        Get the number of available heat pumps

        Returns:
            Number of heat pumps
        """
        return len(self.heat_pumps)

    def get_heat_pump_by_id(self, device_id: str) -> Optional[ThermiaHeatPump]:
        """
        Get a specific heat pump by device ID

        Args:
            device_id: The device ID to search for

        Returns:
            ThermiaHeatPump object if found, None otherwise
        """
        for heat_pump in self.heat_pumps:
            if str(heat_pump.id) == str(device_id):
                return heat_pump
        return None

    def get_heat_pump_by_name(self, name: str) -> Optional[ThermiaHeatPump]:
        """
        Get a specific heat pump by name

        Args:
            name: The device name to search for

        Returns:
            ThermiaHeatPump object if found, None otherwise
        """
        for heat_pump in self.heat_pumps:
            if heat_pump.name and heat_pump.name.lower() == name.lower():
                return heat_pump
        return None

    def has_active_alarms(self) -> bool:
        """
        Check if any heat pump has active alarms

        Returns:
            True if any heat pump has active alarms
        """
        for heat_pump in self.heat_pumps:
            if heat_pump.active_alarm_count > 0:
                return True
        return False

    def get_total_active_alarms(self) -> int:
        """
        Get total number of active alarms across all heat pumps

        Returns:
            Total number of active alarms
        """
        total = 0
        for heat_pump in self.heat_pumps:
            total += heat_pump.active_alarm_count
        return total

    def __str__(self) -> str:
        """String representation of Thermia instance"""
        status = "Connected" if self.connected else "Disconnected"
        pump_count = len(self.heat_pumps)
        return f"Thermia({status}, {pump_count} heat pump(s))"

    def __repr__(self) -> str:
        """Detailed representation of Thermia instance"""
        return f"Thermia(connected={self.connected}, heat_pumps={len(self.heat_pumps)})"

    # Backward compatibility methods
    @property
    def authenticated(self) -> bool:
        """Backward compatibility property"""
        return self.connected

    def get_api(self) -> ThermiaAPI:
        """
        Get the underlying API interface for advanced usage

        Returns:
            ThermiaAPI instance
        """
        return self.api_interface