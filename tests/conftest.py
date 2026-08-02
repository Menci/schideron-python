from __future__ import annotations

from copy import deepcopy

import pytest


@pytest.fixture
def conditioner_status_payload() -> dict[str, str]:
    return {
        "definition": "airconControl",
        "product_model": "MistsubishiThermostat-MODBUS-RTU",
        "brand": "Mistsubishi Electric",
        "category": "HVAC",
        "device_id": "1",
        "device_name": "1",
        "state": "2",
        "mode": "1",
        "fanspeed": "4",
        "temperature_type": "0",
        "set_temperature": "270",
        "room_temperature": "280",
        "outside_temperature": "0",
        "set_humidity": "0",
        "room_humidity": "0",
        "PM2.5": "0",
        "PB": "1",
        "interface": "USB3",
    }


@pytest.fixture
def heating_status_payload() -> dict[str, str]:
    return {
        "definition": "airconControl",
        "product_model": "HaiLin-FloorHeating-MODBUS-RTU",
        "brand": "海林自控",
        "category": "HVAC",
        "device_id": "101",
        "device_name": "7",
        "state": "1",
        "mode": "0",
        "fanspeed": "0",
        "temperature_type": "0",
        "set_temperature": "0",
        "room_temperature": "0",
        "outside_temperature": "0",
        "set_humidity": "0",
        "room_humidity": "0",
        "PM2.5": "0",
        "PB": "101",
        "interface": "MODBUS_A",
    }


@pytest.fixture
def status_copy():
    return deepcopy
