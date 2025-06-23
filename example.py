from datetime import datetime, timedelta
import os
import json

from ThermiaOnlineAPI import Thermia  # Use the improved wrapper instead of direct API

CHANGE_HEAT_PUMP_DATA_DURING_TEST = (
    False  # Set to True if you want to change heat pump data during test
)

# Token storage file (optional - remove if you don't want file storage)
TOKEN_FILE = "thermia_tokens.json"

USERNAME = None
PASSWORD = None
ACCESS_TOKEN = None
REFRESH_TOKEN = None


def load_tokens_from_file():
    """Load tokens from file if it exists"""
    if os.path.exists(TOKEN_FILE):
        try:
            with open(TOKEN_FILE, 'r') as f:
                tokens = json.load(f)
                return tokens.get('access_token'), tokens.get('refresh_token')
        except Exception as e:
            print(f"Error loading tokens: {e}")
    return None, None


def save_tokens_to_file(access_token, refresh_token):
    """Save tokens to file"""
    try:
        with open(TOKEN_FILE, 'w') as f:
            json.dump({
                'access_token': access_token,
                'refresh_token': refresh_token
            }, f, indent=2)
        print("Tokens saved successfully")
    except Exception as e:
        print(f"Error saving tokens: {e}")


def load_credentials_from_env():
    """Load credentials and tokens from .env file"""
    global USERNAME, PASSWORD, ACCESS_TOKEN, REFRESH_TOKEN

    if os.path.exists(".env"):
        with open(".env", "r") as env_file:
            for line in env_file:
                line = line.strip()
                if line.startswith("USERNAME="):
                    USERNAME = line.split("=", 1)[1].strip()
                elif line.startswith("PASSWORD="):
                    PASSWORD = line.split("=", 1)[1].strip()
                elif line.startswith("ACCESS_TOKEN="):
                    ACCESS_TOKEN = line.split("=", 1)[1].strip()
                elif line.startswith("REFRESH_TOKEN="):
                    REFRESH_TOKEN = line.split("=", 1)[1].strip()


def get_credentials_from_user():
    """Get credentials from user input if not available"""
    global USERNAME, PASSWORD

    if not USERNAME:
        USERNAME = input("Enter username: ")
    if not PASSWORD:
        PASSWORD = input("Enter password: ")


def authenticate_thermia():
    """Authenticate with Thermia API using the best available method"""
    global ACCESS_TOKEN, REFRESH_TOKEN

    # Load from environment/file
    load_credentials_from_env()

    # Try to load tokens from file if not in env
    if not ACCESS_TOKEN:
        file_access_token, file_refresh_token = load_tokens_from_file()
        if file_access_token:
            ACCESS_TOKEN = file_access_token
            REFRESH_TOKEN = file_refresh_token

    thermia = None

    # Method 1: Try existing tokens first
    if ACCESS_TOKEN:
        try:
            print("Attempting authentication with existing tokens...")
            thermia = Thermia(access_token=ACCESS_TOKEN, refresh_token=REFRESH_TOKEN)

            # Test connection by checking if we have heat pumps
            if thermia.heat_pumps and len(thermia.heat_pumps) > 0:
                print("✓ Successfully authenticated with existing tokens")

                # Update tokens in case they were refreshed
                new_access_token, new_refresh_token = thermia.get_tokens()
                if new_access_token != ACCESS_TOKEN or new_refresh_token != REFRESH_TOKEN:
                    print("Tokens were refreshed, saving updated tokens...")
                    save_tokens_to_file(new_access_token, new_refresh_token)

                return thermia
            else:
                print("✗ Token authentication failed - no heat pumps found")
                thermia = None
        except Exception as e:
            print(f"✗ Token authentication failed: {e}")
            thermia = None

    # Method 2: Fallback to username/password
    if thermia is None:
        print("Falling back to username/password authentication...")

        # Get credentials if not available
        if not USERNAME or not PASSWORD:
            get_credentials_from_user()

        try:
            thermia = Thermia(username=USERNAME, password=PASSWORD)

            # Test connection by checking if we have heat pumps
            if thermia.heat_pumps and len(thermia.heat_pumps) > 0:
                print("✓ Successfully authenticated with credentials")

                # Save tokens for future use
                access_token, refresh_token = thermia.get_tokens()
                save_tokens_to_file(access_token, refresh_token)

                return thermia
            else:
                print("✗ Credential authentication failed - no heat pumps found")
                thermia = None

        except Exception as e:
            print(f"✗ Credential authentication failed: {e}")
            thermia = None

    if thermia is None:
        raise Exception("All authentication methods failed. Please check your credentials.")

    return thermia


# Main execution
try:
    # Authenticate using the best available method
    thermia = authenticate_thermia()

    # Test that we have heat pumps
    if not thermia.heat_pumps or len(thermia.heat_pumps) == 0:
        print("No heat pumps found in your account")
        exit(1)

    print(f"\nAuthentication successful! Found {len(thermia.heat_pumps)} heat pump(s)")

    heat_pump = thermia.heat_pumps[0]

    print("Creating debug file")
    with open("debug.txt", "w") as f:
        f.write(heat_pump.debug())

    print("Debug file created")

    print("\n" + "=" * 50)
    print("HEAT PUMP INFORMATION")
    print("=" * 50)

    print(f"Heat pump model: {heat_pump.model}")
    print(f"Heat pump model id: {heat_pump.model_id}")

    print("\n" + "-" * 30)
    print("REGISTER GROUPS")
    print("-" * 30)

    print(f"All available register groups: {heat_pump.get_all_available_register_groups()}")

    try:
        heating_curve_registers = heat_pump.get_available_registers_for_group("REG_GROUP_HEATING_CURVE")
        print(f"Available registers for 'REG_GROUP_HEATING_CURVE' group: {heating_curve_registers}")
    except Exception as e:
        print(f"Could not get heating curve registers: {e}")

    print("\n" + "-" * 30)
    print("TEMPERATURES")
    print("-" * 30)

    temperatures = [
        ("Supply Line Temperature", heat_pump.supply_line_temperature),
        ("Desired Supply Line Temperature", heat_pump.desired_supply_line_temperature),
        ("Return Line Temperature", heat_pump.return_line_temperature),
        ("Brine Out Temperature", heat_pump.brine_out_temperature),
        ("Pool Temperature", heat_pump.pool_temperature),
        ("Brine In Temperature", heat_pump.brine_in_temperature),
        ("Cooling Tank Temperature", heat_pump.cooling_tank_temperature),
        ("Cooling Supply Line Temperature", heat_pump.cooling_supply_line_temperature),
        ("Heat Temperature", heat_pump.heat_temperature),
    ]

    for temp_name, temp_value in temperatures:
        print(f"{temp_name}: {temp_value}")

    print("\n" + "-" * 30)
    print("OPERATIONAL STATUS")
    print("-" * 30)

    print(f"Running operational statuses: {heat_pump.running_operational_statuses}")
    print(f"Available operational statuses: {heat_pump.available_operational_statuses}")
    print(f"Available operational statuses map: {heat_pump.available_operational_statuses_map}")

    print("\n" + "-" * 30)
    print("POWER STATUS")
    print("-" * 30)

    print(f"Running power statuses: {heat_pump.running_power_statuses}")
    print(f"Available power statuses: {heat_pump.available_power_statuses}")
    print(f"Available power statuses map: {heat_pump.available_power_statuses_map}")

    print(f"\nIntegral: {heat_pump.operational_status_integral}")
    print(f"Pid: {heat_pump.operational_status_pid}")

    print("\n" + "-" * 30)
    print("OPERATIONAL TIMES")
    print("-" * 30)

    operational_times = [
        ("Compressor Operational Time", heat_pump.compressor_operational_time),
        ("Heating Operational Time", heat_pump.heating_operational_time),
        ("Hot Water Operational Time", heat_pump.hot_water_operational_time),
        ("Auxiliary Heater 1 Operational Time", heat_pump.auxiliary_heater_1_operational_time),
        ("Auxiliary Heater 2 Operational Time", heat_pump.auxiliary_heater_2_operational_time),
        ("Auxiliary Heater 3 Operational Time", heat_pump.auxiliary_heater_3_operational_time),
    ]

    for time_name, time_value in operational_times:
        print(f"{time_name}: {time_value}")

    print("\n" + "-" * 30)
    print("ALARMS")
    print("-" * 30)

    print(f"Active Alarm Count: {heat_pump.active_alarm_count}")
    if heat_pump.active_alarm_count > 0:
        print(f"Active Alarms: {heat_pump.active_alarms}")
    else:
        print("No active alarms")

    print("\n" + "-" * 30)
    print("OPERATION MODE")
    print("-" * 30)

    print(f"Operation Mode: {heat_pump.operation_mode}")
    print(f"Available Operation Modes: {heat_pump.available_operation_modes}")
    print(f"Available Operation Modes Map: {heat_pump.available_operation_mode_map}")
    print(f"Is Operation Mode Read Only: {heat_pump.is_operation_mode_read_only}")

    print("\n" + "-" * 30)
    print("HOT WATER")
    print("-" * 30)

    print(f"Hot Water Switch State: {heat_pump.hot_water_switch_state}")
    print(f"Hot Water Boost Switch State: {heat_pump.hot_water_boost_switch_state}")

    print("\n" + "-" * 30)
    print("HISTORICAL DATA")
    print("-" * 30)

    print(f"Available historical data registers: {heat_pump.historical_data_registers}")

    try:
        historical_data = heat_pump.get_historical_data_for_register(
            "REG_OUTDOOR_TEMPERATURE",
            datetime.now() - timedelta(days=1),
            datetime.now(),
        )
        print(
            f"Historical data for outdoor temperature during past 24h: {len(historical_data) if historical_data else 0} data points")
        if historical_data and len(historical_data) > 0:
            print(f"Sample data point: {historical_data[0]}")
    except Exception as e:
        print(f"Could not get historical data: {e}")

    print("\n" + "-" * 30)
    print("HEATING CURVE")
    print("-" * 30)

    try:
        heating_curve_data = heat_pump.get_register_data_by_register_group_and_name(
            "REG_GROUP_HEATING_CURVE", "REG_HEATING_HEAT_CURVE"
        )
        print(f"Heating Curve Register Data: {heating_curve_data}")
    except Exception as e:
        print(f"Could not get heating curve data: {e}")

    print("\n" + "-" * 30)
    print("UPDATING DATA")
    print("-" * 30)

    print("Updating heat pump data...")
    thermia.update_data()
    print("Data updated successfully")

    if CHANGE_HEAT_PUMP_DATA_DURING_TEST:
        print("\n" + "-" * 30)
        print("MAKING CHANGES (TEST MODE)")
        print("-" * 30)

        print("⚠️  Making changes to heat pump settings...")

        try:
            print("Setting temperature to 19°C...")
            heat_pump.set_temperature(19)

            print("Setting heating curve to 30...")
            heat_pump.set_register_data_by_register_group_and_name(
                "REG_GROUP_HEATING_CURVE", "REG_HEATING_HEAT_CURVE", 30
            )

            print("Setting operation mode to COMPRESSOR...")
            heat_pump.set_operation_mode("COMPRESSOR")

            if heat_pump.hot_water_switch_state is not None:
                print("Setting hot water switch state...")
                heat_pump.set_hot_water_switch_state(1)

            if heat_pump.hot_water_boost_switch_state is not None:
                print("Setting hot water boost switch state...")
                heat_pump.set_hot_water_boost_switch_state(1)

            print("✓ All changes applied successfully")

        except Exception as e:
            print(f"✗ Error making changes: {e}")

    print("\n" + "=" * 50)
    print("FINAL STATUS")
    print("=" * 50)

    print(f"Heat Temperature: {heat_pump.heat_temperature}")
    print(f"Operation Mode: {heat_pump.operation_mode}")
    print(f"Available Operation Modes: {heat_pump.available_operation_modes}")
    print(f"Hot Water Switch State: {heat_pump.hot_water_switch_state}")
    print(f"Hot Water Boost Switch State: {heat_pump.hot_water_boost_switch_state}")

    # Save updated tokens one more time
    try:
        final_access_token, final_refresh_token = thermia.get_tokens()
        save_tokens_to_file(final_access_token, final_refresh_token)
    except Exception as e:
        print(f"Note: Could not save final tokens: {e}")

    print("\n✓ Example completed successfully!")

except Exception as e:
    print(f"\n✗ Error: {e}")
    print("\nTroubleshooting tips:")
    print("1. Check your internet connection")
    print("2. Verify your username and password")
    print("3. Make sure your .env file is properly formatted")
    print("4. If using tokens, ensure they haven't expired")
    print("5. Try deleting the tokens file to force re-authentication")