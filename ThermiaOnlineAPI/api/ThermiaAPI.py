import logging
from collections import ChainMap
from datetime import datetime, timedelta
import requests
from requests.adapters import HTTPAdapter, Retry
from requests import cookies
import json
import hashlib
from typing import Dict, Optional, Tuple

from ThermiaOnlineAPI.const import (
    REG_GROUP_HOT_WATER,
    REG_GROUP_OPERATIONAL_OPERATION,
    REG_GROUP_OPERATIONAL_STATUS,
    REG_GROUP_OPERATIONAL_TIME,
    REG_GROUP_TEMPERATURES,
    REG_HOT_WATER_STATUS,
    REG__HOT_WATER_BOOST,
    REG_OPERATIONMODE,
    THERMIA_CONFIG_URL,
    THERMIA_AZURE_AUTH_URL,
    THERMIA_AZURE_AUTH_CLIENT_ID_AND_SCOPE,
    THERMIA_AZURE_AUTH_REDIRECT_URI,
    THERMIA_INSTALLATION_PATH,
)

from ..exceptions.AuthenticationException import AuthenticationException
from ..exceptions.NetworkException import NetworkException
from ..model.HeatPump import ThermiaHeatPump
from ..utils import utils

_LOGGER = logging.getLogger(__name__)

# Azure auth URLs
AZURE_AUTH_AUTHORIZE_URL = THERMIA_AZURE_AUTH_URL + "/oauth2/v2.0/authorize"
AZURE_AUTH_GET_TOKEN_URL = THERMIA_AZURE_AUTH_URL + "/oauth2/v2.0/token"
AZURE_SELF_ASSERTED_URL = THERMIA_AZURE_AUTH_URL + "/SelfAsserted"
AZURE_AUTH_CONFIRM_URL = (
        THERMIA_AZURE_AUTH_URL + "/api/CombinedSigninAndSignup/confirmed"
)

# Azure default headers
azure_auth_request_headers = {
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"
}

# Fix for multiple operation modes with the same value
REG_OPERATIONMODE_SKIP_VALUES = ["REG_VALUE_OPERATION_MODE_SERVICE"]


class ThermiaAPI:
    def __init__(self,
                 auth_url: str,
                 auth_client_id: str,
                 auth_redirect_uri: str,
                 email: str = None,
                 password: str = None,
                 access_token: str = None,
                 refresh_token: str = None):
        """
        Initialize ThermiaAPI with authentication parameters and either credentials or existing tokens

        Args:
            auth_url: Authentication URL (required)
            auth_client_id: Authentication client ID and scope (required)
            auth_redirect_uri: Authentication redirect URI (required)
            email: User email (required if tokens are not provided)
            password: User password (required if tokens are not provided)
            access_token: Existing access token (optional)
            refresh_token: Existing refresh token (optional)
        """
        # Validate required auth parameters
        if not auth_url or not auth_client_id or not auth_redirect_uri:
            raise ValueError("Authentication parameters (auth_url, auth_client_id, auth_redirect_uri) are required")

        # Validate input parameters
        has_credentials = email is not None and password is not None
        has_tokens = access_token is not None

        if not has_credentials and not has_tokens:
            raise ValueError("Either provide email/password or access_token")

        self.__email = email
        self.__password = password
        self.__access_token = access_token
        self.__refresh_token = refresh_token
        self.__token_expires_on = None
        self.__refresh_token_expires_on = None

        # Store authentication parameters
        self.__auth_url = auth_url
        self.__auth_client_id = auth_client_id
        self.__auth_redirect_uri = auth_redirect_uri

        # Create instance auth URLs
        self.__auth_authorize_url = self.__auth_url + "/oauth2/v2.0/authorize"
        self.__auth_token_url = self.__auth_url + "/oauth2/v2.0/token"
        self.__auth_self_asserted_url = self.__auth_url + "/SelfAsserted"
        self.__auth_confirm_url = self.__auth_url + "/api/CombinedSigninAndSignup/confirmed"

        # Default request headers
        self.__auth_request_headers = {
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"
        }

        self.__default_request_headers = {
            "Authorization": "Bearer ",
            "Content-Type": "application/json",
            "cache-control": "no-cache",
            "Access-Control-Allow-Origin": "*",
        }

        self.__session = requests.Session()
        retry = Retry(
            total=20, backoff_factor=0.1, status_forcelist=[500, 502, 503, 504]
        )
        adapter = HTTPAdapter(max_retries=retry)
        self.__session.mount("https://", adapter)

        self.configuration = self.__fetch_configuration()

        # If we have an access token, use it; otherwise authenticate with credentials
        if self.__access_token:
            self.__update_authorization_header()
            self.authenticated = True
        else:
            self.authenticated = self.__authenticate()
    
    def get_tokens(self) -> Tuple[Optional[str], Optional[str]]:
        """
        Get current access and refresh tokens

        Returns:
            Tuple of (access_token, refresh_token)
        """
        return (self.__access_token, self.__refresh_token)

    def update_tokens(self, access_token: str, refresh_token: str = None) -> None:
        """
        Update the API instance with new tokens

        Args:
            access_token: New access token
            refresh_token: New refresh token (optional)
        """
        self.__access_token = access_token
        if refresh_token:
            self.__refresh_token = refresh_token
        self.__update_authorization_header()
        self.authenticated = True

    def __update_authorization_header(self):
        """Update the authorization header with current access token"""
        if self.__access_token:
            self.__default_request_headers["Authorization"] = f"Bearer {self.__access_token}"

    def __authenticate_refresh_token(self) -> Optional[Dict]:
        """
        Attempt to refresh the access token using the refresh token

        Returns:
            Token response dict on success, None on failure
        """
        if not self.__refresh_token:
            return None

        request_token_data = {
            "client_id": self.__auth_client_id,
            "redirect_uri": self.__auth_redirect_uri,
            "scope": self.__auth_client_id,
            "refresh_token": self.__refresh_token,
            "grant_type": "refresh_token",
        }

        request_token = self.__session.post(
            self.__auth_token_url,
            headers=self.__auth_request_headers,
            data=request_token_data,
        )

        if request_token.status_code != 200:
            error_text = (
                    "Refresh token authentication failed. Status: "
                    + str(request_token.status_code)
                    + ", Response: "
                    + request_token.text
            )
            _LOGGER.info(error_text)

            # Clear invalid tokens
            self.__access_token = None
            self.__refresh_token = None
            self.__token_expires_on = None
            self.__refresh_token_expires_on = None
            return None

        try:
            return json.loads(request_token.text)
        except Exception as e:
            _LOGGER.error(f"Error parsing refresh token response: {e}")
            return None

    def __authenticate_with_credentials(self) -> Dict:
        """
        Authenticate using email and password

        Returns:
            Token response dict
        """
        if not self.__email or not self.__password:
            raise AuthenticationException("Email and password required for credential authentication")

        code_challenge = utils.generate_challenge(43)

        request_auth_data = {
            "client_id": self.__auth_client_id,
            "scope": self.__auth_client_id,
            "redirect_uri": self.__auth_redirect_uri,
            "response_type": "code",
            "code_challenge": str(
                utils.base64_url_encode(
                    hashlib.sha256(code_challenge.encode("utf-8")).digest()
                ),
                "utf-8",
            ),
            "code_challenge_method": "S256",
        }

        request_auth = self.__session.get(
            self.__auth_authorize_url, data=request_auth_data
        )

        state_code = ""
        csrf_token = ""

        if request_auth.status_code == 200:
            settings_string = request_auth.text.split("var SETTINGS = ")
            settings_string = settings_string[1].split("};")[0] + "}"
            if len(settings_string) > 0:
                try:
                    settings = json.loads(settings_string)
                    state_code = str(settings["transId"]).split("=")[1]
                    csrf_token = settings["csrf"]
                except Exception as e:
                    _LOGGER.error(
                        "Error parsing authorization API settings. "
                        + str(request_auth.text),
                        e,
                    )
                    raise NetworkException(
                        "Error parsing authorization API settings. "
                        + request_auth.text,
                        e,
                    )
        else:
            _LOGGER.error(
                "Error fetching authorization API. Status: "
                + str(request_auth.status_code)
                + ", Response: "
                + request_auth.text
            )
            raise NetworkException(
                "Error fetching authorization API.", request_auth.reason
            )

        request_self_asserted_data = {
            "request_type": "RESPONSE",
            "signInName": self.__email,
            "password": self.__password,
        }

        request_self_asserted_query_params = {
            "tx": "StateProperties=" + state_code,
            "p": "B2C_1A_SignUpOrSigninOnline",
        }

        request_self_asserted = self.__session.post(
            self.__auth_self_asserted_url,
            cookies=request_auth.cookies,
            data=request_self_asserted_data,
            headers={**self.__auth_request_headers, "X-Csrf-Token": csrf_token},
            params=request_self_asserted_query_params,
        )

        if (
                request_self_asserted.status_code != 200
                or '{"status":"400"' in request_self_asserted.text
        ):
            _LOGGER.error(
                "Error in API authentication. Wrong credentials "
                + str(request_self_asserted.text)
            )
            raise AuthenticationException(
                "Error in API authentication. Wrong credentials"
            )

        request_confirmed_cookies = request_self_asserted.cookies
        cookie_obj = cookies.create_cookie(
            name="x-ms-cpim-csrf", value=request_auth.cookies.get("x-ms-cpim-csrf")
        )
        request_confirmed_cookies.set_cookie(cookie_obj)

        request_confirmed_params = {
            "csrf_token": csrf_token,
            "tx": "StateProperties=" + state_code,
            "p": "B2C_1A_SignUpOrSigninOnline",
        }

        request_confirmed = self.__session.get(
            self.__auth_confirm_url,
            cookies=request_confirmed_cookies,
            params=request_confirmed_params,
        )

        request_token_data = {
            "client_id": self.__auth_client_id,
            "redirect_uri": self.__auth_redirect_uri,
            "scope": self.__auth_client_id,
            "code": utils.get_list_value_or_default(
                request_confirmed.url.split("code="), 1, ""
            ),
            "code_verifier": code_challenge,
            "grant_type": "authorization_code",
        }

        request_token = self.__session.post(
            self.__auth_token_url,
            headers=self.__auth_request_headers,
            data=request_token_data,
        )

        if request_token.status_code != 200:
            error_text = (
                    "Authentication request failed, please check credentials. Status: "
                    + str(request_token.status_code)
                    + ", Response: "
                    + request_token.text
            )
            _LOGGER.error(error_text)
            raise AuthenticationException(error_text)

        try:
            return json.loads(request_token.text)
        except Exception as e:
            _LOGGER.error(f"Error parsing authentication response: {e}")
            raise NetworkException(f"Error parsing authentication response: {e}")

    def __authenticate(self) -> bool:
        """
        Main authentication method - tries refresh token first, then credentials

        Returns:
            True if authentication successful, False otherwise
        """
        token_response = None

        # Try refresh token first if available and potentially valid
        if (self.__refresh_token and
                (self.__refresh_token_expires_on is None or
                 self.__refresh_token_expires_on > datetime.now().timestamp())):
            _LOGGER.info("Attempting to refresh access token")
            token_response = self.__authenticate_refresh_token()

        # If refresh failed or no refresh token, try credentials
        if token_response is None:
            if self.__email and self.__password:
                _LOGGER.info("Authenticating with credentials")
                token_response = self.__authenticate_with_credentials()
            else:
                _LOGGER.error("No valid authentication method available")
                raise AuthenticationException("No valid authentication method available")

        # Update token information
        self.__access_token = token_response["access_token"]
        self.__refresh_token = token_response.get("refresh_token", self.__refresh_token)

        # Handle expires_on (can be string or int)
        expires_on = token_response["expires_on"]
        if isinstance(expires_on, str):
            self.__token_expires_on = int(expires_on)
        else:
            self.__token_expires_on = expires_on

        # Set refresh token expiry to 6 hours from now for safety
        self.__refresh_token_expires_on = (datetime.now() + timedelta(hours=6)).timestamp()

        self.__update_authorization_header()

        _LOGGER.info("Authentication successful, tokens updated.")
        return True

    def __check_token_validity(self):
        """
        Check if tokens are valid and refresh/reauthenticate if necessary
        """
        # Check if access token is still valid
        if (self.__token_expires_on and
                self.__token_expires_on > datetime.now().timestamp()):
            return  # Token is still valid

        # Access token expired or not set, try to refresh or reauthenticate
        _LOGGER.info("Access token expired or invalid, attempting refresh/reauthentication")
        self.authenticated = self.__authenticate()

    def get_devices(self):
        self.__check_token_validity()

        url = self.configuration["apiBaseUrl"] + "/api/v1/installationsInfo"
        request = self.__session.get(url, headers=self.__default_request_headers)
        status = request.status_code

        if status != 200:
            _LOGGER.error(
                "Error fetching devices. Status: "
                + str(status)
                + ", Response: "
                + request.text
            )
            return []

        response = utils.get_response_json_or_log_and_raise_exception(
            request, "Error getting devices."
        )

        return response.get("items", [])

    def get_device_by_id(self, device_id: str):
        self.__check_token_validity()

        devices = self.get_devices()

        device = [d for d in devices if str(d["id"]) == device_id]

        if len(device) != 1:
            _LOGGER.error("Error getting device by id: " + str(device_id))
            return None

        return device[0]

    def get_device_info(self, device_id: str):
        self.__check_token_validity()

        url = self.configuration["apiBaseUrl"] + "/api/v1/installations/" + device_id
        request = self.__session.get(url, headers=self.__default_request_headers)
        status = request.status_code

        if status != 200:
            _LOGGER.error(
                "Error fetching device info. Status: "
                + str(status)
                + ", Response: "
                + str(request.text)
            )
            return None

        return utils.get_response_json_or_log_and_raise_exception(
            request, "Error getting device info."
        )

    def get_device_status(self, device_id: str):
        self.__check_token_validity()

        url = (
                self.configuration["apiBaseUrl"]
                + "/api/v1/installationstatus/"
                + device_id
                + "/status"
        )
        request = self.__session.get(url, headers=self.__default_request_headers)
        status = request.status_code

        if status != 200:
            _LOGGER.error(
                "Error fetching device status. Status :"
                + str(status)
                + ", Response: "
                + request.text
            )
            return None

        return utils.get_response_json_or_log_and_raise_exception(
            request, "Error fetching device status."
        )

    def get_all_alarms(self, device_id: str):
        self.__check_token_validity()

        url = (
                self.configuration["apiBaseUrl"]
                + "/api/v1/installation/"
                + str(device_id)
                + "/events?onlyActiveAlarms=false"
        )
        request = self.__session.get(url, headers=self.__default_request_headers)
        status = request.status_code

        if status != 200:
            _LOGGER.error(
                "Error in getting device's alarms. Status: "
                + str(status)
                + ", Response: "
                + request.text
            )
            return None

        return utils.get_response_json_or_log_and_raise_exception(
            request, "Error in getting device's alarms."
        )

    def get_historical_data_registers(self, device_id: str):
        self.__check_token_validity()

        url = (
                self.configuration["apiBaseUrl"]
                + "/api/v1/DataHistory/installation/"
                + str(device_id)
        )
        request = self.__session.get(url, headers=self.__default_request_headers)
        status = request.status_code

        if status != 200:
            _LOGGER.error(
                "Error in historical data registers. Status: "
                + str(status)
                + ", Response: "
                + request.text
            )
            return None

        return utils.get_response_json_or_log_and_raise_exception(
            request, "Error in historical data registers."
        )

    def get_historical_data(
            self, device_id: str, register_id, start_date_str, end_date_str
    ):
        self.__check_token_validity()

        url = (
                self.configuration["apiBaseUrl"]
                + "/api/v1/datahistory/installation/"
                + str(device_id)
                + "/register/"
                + str(register_id)
                + "/minute?periodStart="
                + start_date_str
                + "&periodEnd="
                + end_date_str
        )
        request = self.__session.get(url, headers=self.__default_request_headers)
        status = request.status_code

        if status != 200:
            _LOGGER.error(
                "Error in historical data for specific register. Status: "
                + str(status)
                + ", Response: "
                + request.text
            )
            return None

        return utils.get_response_json_or_log_and_raise_exception(
            request, "Error in historical data for specific register."
        )

    def get_all_available_groups(self, installation_profile_id: int):
        self.__check_token_validity()

        url = (
                self.configuration["apiBaseUrl"]
                + "/api/v1/installationprofiles/"
                + str(installation_profile_id)
                + "/groups"
        )

        request = self.__session.get(url, headers=self.__default_request_headers)
        status = request.status_code

        if status != 200:
            _LOGGER.error(
                "Error in getting available groups. Status: "
                + str(status)
                + ", Response: "
                + request.text
            )
            return None

        return utils.get_response_json_or_log_and_raise_exception(
            request, "Error in getting available groups."
        )

    def get__group_temperatures(self, device_id: str):
        return self.__get_register_group(device_id, REG_GROUP_TEMPERATURES)

    def get__group_operational_status(self, device_id: str):
        return self.__get_register_group(device_id, REG_GROUP_OPERATIONAL_STATUS)

    def get__group_operational_time(self, device_id: str):
        return self.__get_register_group(device_id, REG_GROUP_OPERATIONAL_TIME)

    def get_group_operational_operation(self, device: ThermiaHeatPump):
        return self.__get_group_operational_operation_from_register_group(
            device, REG_GROUP_OPERATIONAL_OPERATION
        )

    def get_group_operational_operation_from_status(self, device: ThermiaHeatPump):
        return self.__get_group_operational_operation_from_register_group(
            device, REG_GROUP_OPERATIONAL_STATUS
        )

    def __get_group_operational_operation_from_register_group(
            self, device: ThermiaHeatPump, register_group: str
    ):
        register_data = self.__get_register_group(device.id, register_group)

        data = [d for d in register_data if d["registerName"] == REG_OPERATIONMODE]

        if len(data) != 1:
            # Operation mode not supported
            return None

        data = data[0]

        device.set_register_index_operation_mode(data["registerId"])

        current_operation_mode_value = int(data.get("registerValue"))
        operation_modes_data = data.get("valueNames")

        if operation_modes_data is not None:
            operation_modes_map = map(
                lambda values: (
                    {
                        values.get("value"): values.get("name").split(
                            "REG_VALUE_OPERATION_MODE_"
                        )[1],
                    }
                    if values.get("name") not in REG_OPERATIONMODE_SKIP_VALUES
                    else {}
                ),
                operation_modes_data,
            )
            operation_modes_list = list(filter(lambda x: x != {}, operation_modes_map))
            operation_modes = ChainMap(*operation_modes_list)

            current_operation_mode = [
                name
                for value, name in operation_modes.items()
                if value == current_operation_mode_value
            ]
            if len(current_operation_mode) != 1:
                # Something has gone wrong or operation mode not supported
                return None

            return {
                "current": current_operation_mode[0],
                "available": operation_modes,
                "isReadOnly": data["isReadOnly"],
            }

        return None

    def __get_switch_register_index_and_value_from_group_by_register_name(
            self, register_group: list, register_name: str
    ):
        default_return_object = {
            "registerId": None,
            "registerValue": None,
        }

        switch_data_list = [
            d for d in register_group if d["registerName"] == register_name
        ]

        if len(switch_data_list) != 1:
            # Switch not supported
            return default_return_object

        switch_data: dict = switch_data_list[0]

        register_value = switch_data.get("registerValue")

        if register_value is None:
            return default_return_object

        # Validate that register is a switch
        switch_states_data = switch_data.get("valueNames")

        if switch_states_data is None or len(switch_states_data) != 2:
            return default_return_object

        return {
            "registerId": switch_data["registerId"],
            "registerValue": int(register_value),
        }

    def get_group_hot_water(self, device: ThermiaHeatPump) -> Dict[str, Optional[int]]:
        register_data: list = self.__get_register_group(device.id, REG_GROUP_HOT_WATER)

        hot_water_switch_data = (
            self.__get_switch_register_index_and_value_from_group_by_register_name(
                register_data, REG_HOT_WATER_STATUS
            )
        )
        hot_water_boost_switch_data = (
            self.__get_switch_register_index_and_value_from_group_by_register_name(
                register_data, REG__HOT_WATER_BOOST
            )
        )

        device.set_register_index_hot_water_switch(hot_water_switch_data["registerId"])

        device.set_register_index_hot_water_boost_switch(
            hot_water_boost_switch_data["registerId"]
        )

        return {
            "hot_water_switch": hot_water_switch_data["registerValue"],
            "hot_water_boost_switch": hot_water_boost_switch_data["registerValue"],
        }

    def set_temperature(self, device: ThermiaHeatPump, temperature):
        device_temperature_register_index = device.get_register_indexes()["temperature"]
        if device_temperature_register_index is None:
            _LOGGER.error(
                "Error setting device's temperature. No temperature register index."
            )
            return

        self.__set_register_value(
            device, device_temperature_register_index, temperature
        )

    def set_operation_mode(self, device: ThermiaHeatPump, mode):
        if device.is_operation_mode_read_only:
            _LOGGER.error(
                "Error setting device's operation mode. Operation mode is read only."
            )
            return

        operation_mode_int = None

        for value, name in device.available_operation_mode_map.items():
            if name == mode:
                operation_mode_int = value

        if operation_mode_int is None:
            _LOGGER.error(
                "Error setting device's operation mode. Invalid operation mode."
            )
            return

        device_operation_mode_register_index = device.get_register_indexes()[
            "operation_mode"
        ]
        if device_operation_mode_register_index is None:
            _LOGGER.error(
                "Error setting device's operation mode. No operation mode register index."
            )
            return

        self.__set_register_value(
            device, device_operation_mode_register_index, operation_mode_int
        )

    def set_hot_water_switch_state(
            self, device: ThermiaHeatPump, state: int
    ):  # 0 - off, 1 - on
        register_index = device.get_register_indexes()["hot_water_switch"]
        if register_index is None:
            _LOGGER.error(
                "Error setting device's hot water switch state. No hot water switch register index."
            )
            return

        self.__set_register_value(device, register_index, state)

    def set_hot_water_boost_switch_state(
            self, device: ThermiaHeatPump, state: int
    ):  # 0 - off, 1 - on
        register_index = device.get_register_indexes()["hot_water_boost_switch"]
        if register_index is None:
            _LOGGER.error(
                "Error setting device's hot water boost switch state. No hot water boost switch register index."
            )
            return

        self.__set_register_value(device, register_index, state)

    def get_register_group_json(self, device_id: str, register_group: str) -> list:
        return self.__get_register_group(device_id, register_group)

    def set_register_value(
            self, device: ThermiaHeatPump, register_index: int, value: int
    ):
        self.__set_register_value(device, register_index, value)

    def __get_register_group(self, device_id: str, register_group: str) -> list:
        self.__check_token_validity()

        url = (
                self.configuration["apiBaseUrl"]
                + THERMIA_INSTALLATION_PATH
                + str(device_id)
                + "/Groups/"
                + register_group
        )
        request = self.__session.get(url, headers=self.__default_request_headers)
        status = request.status_code

        if status != 200:
            _LOGGER.error(
                "Error in getting device's register group: "
                + register_group
                + ", Status: "
                + str(status)
                + ", Response: "
                + request.text
            )
            return []

        return utils.get_response_json_or_log_and_raise_exception(
            request, "Error in getting device's register group: " + register_group
        )

    def __set_register_value(
            self, device: ThermiaHeatPump, register_index: int, register_value: int
    ):
        self.__check_token_validity()

        url = (
                self.configuration["apiBaseUrl"]
                + THERMIA_INSTALLATION_PATH
                + str(device.id)
                + "/Registers"
        )
        body = {
            "registerSpecificationId": register_index,
            "registerValue": register_value,
            "clientUuid": "api-client-uuid",
        }

        request = self.__session.post(
            url, headers=self.__default_request_headers, json=body
        )

        status = request.status_code
        if status != 200:
            _LOGGER.error(
                "Error setting register "
                + str(register_index)
                + " value. Status: "
                + str(status)
                + ", Response: "
                + request.text
            )

    def __fetch_configuration(self):
        request = self.__session.get(THERMIA_CONFIG_URL)
        status = request.status_code

        if status != 200:
            _LOGGER.error(
                "Error fetching API configuration. Status: "
                + str(status)
                + ", Response: "
                + request.text
            )
            raise NetworkException("Error fetching API configuration.", status)

        return utils.get_response_json_or_log_and_raise_exception(
            request, "Error fetching API configuration."
        )