"""Support for Tuya Fan."""

from __future__ import annotations

from typing import Any

from tuya_sharing import CustomerDevice, Manager

from homeassistant.components.fan import (
    DIRECTION_FORWARD,
    DIRECTION_REVERSE,
    FanEntity,
    FanEntityFeature,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util.percentage import (
    ordered_list_item_to_percentage,
    percentage_to_ordered_list_item,
)

try:
    from custom_components.tuya.fan import ( # type: ignore
        TUYA_SUPPORT_TYPE as TUYA_SUPPORT_TYPE_TUYA
    )
except ImportError:
    from homeassistant.components.tuya.fan import (
        TUYA_SUPPORT_TYPE as TUYA_SUPPORT_TYPE_TUYA
    )
from .util import (
    append_sets
)

from .multi_manager.multi_manager import XTConfigEntry
from .base import EnumTypeData, IntegerTypeData, TuyaEntity
from .const import TUYA_DISCOVERY_NEW, DPCode, DPType

TUYA_SUPPORT_TYPE = {
}


async def async_setup_entry(
    hass: HomeAssistant, entry: XTConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up tuya fan dynamically through tuya discovery."""
    hass_data = entry.runtime_data

    merged_categories = TUYA_SUPPORT_TYPE
    if not entry.runtime_data.multi_manager.sharing_account or not entry.runtime_data.multi_manager.sharing_account.reuse_config:
        merged_categories = append_sets(TUYA_SUPPORT_TYPE, TUYA_SUPPORT_TYPE_TUYA)

    @callback
    def async_discover_device(device_map) -> None:
        """Discover and add a discovered tuya fan."""
        entities: list[TuyaFanEntity] = []
        device_ids = [*device_map]
        for device_id in device_ids:
            if device := hass_data.manager.device_map.get(device_id):
                if device and device.category in merged_categories:
                    entities.append(TuyaFanEntity(device, hass_data.manager))
        async_add_entities(entities)

    async_discover_device([*hass_data.manager.device_map])

    entry.async_on_unload(
        async_dispatcher_connect(hass, TUYA_DISCOVERY_NEW, async_discover_device)
    )


class TuyaFanEntity(TuyaEntity, FanEntity):
    """Tuya Fan Device."""

    _direction: EnumTypeData | None = None
    _oscillate: DPCode | None = None
    _presets: EnumTypeData | None = None
    _speed: IntegerTypeData | None = None
    _speeds: EnumTypeData | None = None
    _switch: DPCode | None = None
    _attr_name = None

    def __init__(
        self,
        device: CustomerDevice,
        device_manager: Manager,
    ) -> None:
        """Init Tuya Fan Device."""
        super().__init__(device, device_manager)

        self._switch = self.find_dpcode(
            (DPCode.SWITCH_FAN, DPCode.FAN_SWITCH, DPCode.SWITCH, DPCode.POWER, DPCode.POWER2), prefer_function=True
        )

        self._attr_preset_modes = []
        if enum_type := self.find_dpcode(
            (DPCode.FAN_MODE, DPCode.MODE), dptype=DPType.ENUM, prefer_function=True
        ):
            self._presets = enum_type
            self._attr_supported_features |= FanEntityFeature.PRESET_MODE
            self._attr_preset_modes = enum_type.range

        # Find speed controls, can be either percentage or a set of speeds
        dpcodes = (
            DPCode.FAN_SPEED_PERCENT,
            DPCode.FAN_SPEED,
            DPCode.SPEED,
            DPCode.FAN_SPEED_ENUM,
        )
        if int_type := self.find_dpcode(
            dpcodes, dptype=DPType.INTEGER, prefer_function=True
        ):
            self._attr_supported_features |= FanEntityFeature.SET_SPEED
            self._speed = int_type
        elif enum_type := self.find_dpcode(
            dpcodes, dptype=DPType.ENUM, prefer_function=True
        ):
            self._attr_supported_features |= FanEntityFeature.SET_SPEED
            self._speeds = enum_type

        if dpcode := self.find_dpcode(
            (DPCode.SWITCH_HORIZONTAL, DPCode.SWITCH_VERTICAL), prefer_function=True
        ):
            self._oscillate = dpcode
            self._attr_supported_features |= FanEntityFeature.OSCILLATE

        if enum_type := self.find_dpcode(
            DPCode.FAN_DIRECTION, dptype=DPType.ENUM, prefer_function=True
        ):
            self._direction = enum_type
            self._attr_supported_features |= FanEntityFeature.DIRECTION

    def set_preset_mode(self, preset_mode: str) -> None:
        """Set the preset mode of the fan."""
        if self._presets is None:
            return
        self._send_command([{"code": self._presets.dpcode, "value": preset_mode}])

    def set_direction(self, direction: str) -> None:
        """Set the direction of the fan."""
        if self._direction is None:
            return
        self._send_command([{"code": self._direction.dpcode, "value": direction}])

    def set_percentage(self, percentage: int) -> None:
        """Set the speed of the fan, as a percentage."""
        if self._speed is not None:
            self._send_command(
                [
                    {
                        "code": self._speed.dpcode,
                        "value": int(self._speed.remap_value_from(percentage, 1, 100)),
                    }
                ]
            )
            return

        if self._speeds is not None:
            self._send_command(
                [
                    {
                        "code": self._speeds.dpcode,
                        "value": percentage_to_ordered_list_item(
                            self._speeds.range, percentage
                        ),
                    }
                ]
            )

    def turn_off(self, **kwargs: Any) -> None:
        """Turn the fan off."""
        self._send_command([{"code": self._switch, "value": False}])

    def turn_on(
        self,
        percentage: int | None = None,
        preset_mode: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Turn on the fan."""
        if self._switch is None:
            return

        commands: list[dict[str, str | bool | int]] = [
            {"code": self._switch, "value": True}
        ]

        if percentage is not None and self._speed is not None:
            commands.append(
                {
                    "code": self._speed.dpcode,
                    "value": int(self._speed.remap_value_from(percentage, 1, 100)),
                }
            )

        if percentage is not None and self._speeds is not None:
            commands.append(
                {
                    "code": self._speeds.dpcode,
                    "value": percentage_to_ordered_list_item(
                        self._speeds.range, percentage
                    ),
                }
            )

        if preset_mode is not None and self._presets is not None:
            commands.append({"code": self._presets.dpcode, "value": preset_mode})

        self._send_command(commands)

    def oscillate(self, oscillating: bool) -> None:
        """Oscillate the fan."""
        if self._oscillate is None:
            return
        self._send_command([{"code": self._oscillate, "value": oscillating}])

    @property
    def is_on(self) -> bool | None:
        """Return true if fan is on."""
        if self._switch is None:
            return None
        return self.device.status.get(self._switch)

    @property
    def current_direction(self) -> str | None:
        """Return the current direction of the fan."""
        if (
            self._direction is None
            or (value := self.device.status.get(self._direction.dpcode)) is None
        ):
            return None

        if value.lower() == DIRECTION_FORWARD:
            return DIRECTION_FORWARD

        if value.lower() == DIRECTION_REVERSE:
            return DIRECTION_REVERSE

        return None

    @property
    def oscillating(self) -> bool | None:
        """Return true if the fan is oscillating."""
        if self._oscillate is None:
            return None
        return self.device.status.get(self._oscillate)

    @property
    def preset_mode(self) -> str | None:
        """Return the current preset_mode."""
        if self._presets is None:
            return None
        return self.device.status.get(self._presets.dpcode)

    @property
    def percentage(self) -> int | None:
        """Return the current speed."""
        if self._speed is not None:
            if (value := self.device.status.get(self._speed.dpcode)) is None:
                return None
            return int(self._speed.remap_value_to(value, 1, 100))

        if self._speeds is not None:
            if (value := self.device.status.get(self._speeds.dpcode)) is None:
                return None
            return ordered_list_item_to_percentage(self._speeds.range, value)

        return None

    @property
    def speed_count(self) -> int:
        """Return the number of speeds the fan supports."""
        if self._speeds is not None:
            return len(self._speeds.range)
        return 100
