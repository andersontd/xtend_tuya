from __future__ import annotations
import copy
import importlib
import os
from typing import Any, Literal, Optional

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from tuya_iot.device import (
    PROTOCOL_DEVICE_REPORT,
    PROTOCOL_OTHER,
)

from ..const import (
    LOGGER,
)

from .shared.import_stub import (
    MultiManager,
    XTConfigEntry,
)

from .shared.device import (
    XTDevice
)

from .shared.shared_classes import (
    DeviceWatcher,
    XTConfigEntry,  # noqa: F811
)

from .shared.multi_source_handler import (
    MultiSourceHandler,
)

from .shared.multi_mq import (
    MultiMQTTQueue,
)

from .shared.multi_device_listener import (
    MultiDeviceListener,
)

from .shared.multi_virtual_state_handler import (
    XTVirtualStateHandler,
)

from .shared.multi_virtual_function_handler import (
    XTVirtualFunctionHandler,
)

from ..util import (
    merge_iterables,
    append_lists,
)

from .shared.interface.device_manager import (
    XTDeviceManagerInterface,
)
    
class MultiManager:  # noqa: F811
    def __init__(self, hass: HomeAssistant) -> None:
        self.virtual_state_handler = XTVirtualStateHandler(self)
        self.virtual_function_handler = XTVirtualFunctionHandler(self)
        self.descriptors_with_virtual_function = {}
        self.multi_mqtt_queue: MultiMQTTQueue = MultiMQTTQueue(self)
        self.multi_device_listener: MultiDeviceListener = MultiDeviceListener(hass, self)
        self.hass = hass
        self.multi_source_handler = MultiSourceHandler(self)
        self.device_watcher = DeviceWatcher()
        self.accounts: dict[str, XTDeviceManagerInterface] = {}

    @property
    def device_map(self):
        return self.get_aggregated_device_map()
    
    @property
    def mq(self):
        return self.multi_mqtt_queue

    def get_account_by_name(self, account_name:str) -> XTDeviceManagerInterface | None:
        if account_name in self.accounts:
            return self.accounts[account_name]
        return None

    async def setup_entry(self, hass: HomeAssistant, config_entry: XTConfigEntry) -> None:
        #Load all the plugins
        subdirs = os.listdir(os.path.dirname(__file__))

        for directory in subdirs:
            if os.path.isdir(os.path.dirname(__file__) + os.sep + directory):
                load_path = f".{directory}.init"
                try:
                    plugin = importlib.import_module(load_path, package=__package__)
                    LOGGER.debug(f"Plugin {load_path} loaded")
                    instance: XTDeviceManagerInterface = plugin.get_plugin_instance()
                    if await instance.setup_from_entry(hass, config_entry, self):
                        self.accounts[instance.get_type_name()] = instance
                except ModuleNotFoundError:
                    pass

        for account in self.accounts.values():
            account.on_post_setup()
    
    def get_domain_identifiers_of_device(self, device_id: str) -> list:
        return_list: list = []
        for account in self.accounts.values():
            return_list = append_lists(return_list, account.get_domain_identifiers_of_device(device_id))
        return return_list
    
    def get_platform_descriptors_to_merge(self, platform: Platform) -> list:
        return_list: list = []
        for account in self.accounts.values():
            if new_descriptors := account.get_platform_descriptors_to_merge(platform):
                return_list.append(new_descriptors)
        return return_list
    
    def update_device_cache(self):
        for manager in self.accounts.values():
            manager.update_device_cache()
        self._merge_devices_from_multiple_sources()
    
    def convert_tuya_devices_to_xt(self, manager):
        for dev_id in manager.device_map:
            manager.device_map[dev_id] = XTDevice.from_compatible_device(manager.device_map[dev_id])

    def _get_available_device_maps(self) -> list[dict[str, XTDevice]]:
        return_list: list[dict[str, XTDevice]] = []
        for manager in self.accounts.values():
            for device_map in manager.get_available_device_maps():
                return_list.append(device_map)
        return return_list

    def _merge_devices_from_multiple_sources(self):
        #Merge the device function, status_range and status between managers
        device_maps = self._get_available_device_maps()
        aggregated_device_list = self.device_map
        for device in aggregated_device_list.values():
            to_be_merged: list[XTDevice] = []
            devices = self.get_devices_from_device_id(device.id)
            for current_device in devices:
                for prev_device in to_be_merged:
                    self._merge_devices(current_device, prev_device)
                to_be_merged.append(current_device)
        for device_map in device_maps:
            merge_iterables(device_map, aggregated_device_list)
        
    def _merge_devices(self, receiving_device: XTDevice, giving_device: XTDevice):
        merge_iterables(receiving_device.status_range, giving_device.status_range)
        merge_iterables(receiving_device.function, giving_device.function)
        merge_iterables(receiving_device.status, giving_device.status)
        if hasattr(receiving_device, "local_strategy") and hasattr(giving_device, "local_strategy"):
            merge_iterables(receiving_device.local_strategy, giving_device.local_strategy)
        if hasattr(receiving_device, "data_model") and hasattr(giving_device, "data_model"):
            if receiving_device.data_model == "" and giving_device.data_model != "":
                receiving_device.data_model = copy.deepcopy(giving_device.data_model)
            if giving_device.data_model == "" and receiving_device.data_model != "":
                giving_device.data_model = copy.deepcopy(receiving_device.data_model)
    
    def get_aggregated_device_map(self) -> dict[str, XTDevice]:
        aggregated_list: dict[str, XTDevice] = {}
        device_maps = self._get_available_device_maps()
        for device_map in device_maps:
            for device_id in device_map:
                if device_id not in aggregated_list:
                    aggregated_list[device_id] = device_map[device_id]
        return aggregated_list
    
    def unload(self):
        for manager in self.accounts.values():
            manager.unload()
    
    def refresh_mq(self):
        for manager in self.accounts.values():
            manager.refresh_mq()

    def register_device_descriptors(self, name: str, descriptors):
        self.virtual_state_handler.register_device_descriptors(name, descriptors)
        self.virtual_function_handler.register_device_descriptors(name, descriptors)
    
    def remove_device_listeners(self) -> None:
        for manager in self.accounts.values():
            manager.remove_device_listeners()
    
    def _read_dpId_from_code(self, code: str, device: XTDevice) -> int | None:
        if not hasattr(device, "local_strategy"):
            return None
        for dpId in device.local_strategy:
            if device.local_strategy[dpId]["status_code"] == code:
                return dpId
        return None
    
    def _read_code_from_dpId(self, dpId: int, device: XTDevice) -> str | None:
        if dp_id_item := device.local_strategy.get(dpId, None):
            return dp_id_item["status_code"]
        return None

    def allow_virtual_devices_not_set_up(self, device: XTDevice):
        if not device.id.startswith("vdevo"):
            return
        if not getattr(device, "set_up", True):
            setattr(device, "set_up", True)
    
    def get_devices_from_device_id(self, device_id: str) -> list[XTDevice] | None:
        return_list = []
        device_maps = self._get_available_device_maps()
        for device_map in device_maps:
            if device_id in device_map:
                return_list.append(device_map[device_id])
        return return_list

    def _read_code_dpid_value_from_state(self, device_id: str, state, fail_if_dpid_not_found = True, fail_if_code_not_found = True):
        devices = self.get_devices_from_device_id(device_id)
        code = None
        dpId = None
        value = None
        if "value" in state:
            value = state["value"]
        for device in devices:
            if code is None and "code" in state:
                code = state["code"]
            if dpId is None and "dpId" in state:
                dpId = state["dpId"]

            if code is None and dpId is not None:
                code = self._read_code_from_dpId(dpId, device)

            if dpId is None and code is not None:
                dpId = self._read_dpId_from_code(code, device)

            if dpId is None and code is None:
                for temp_dpId in state:
                    temp_code = self._read_code_from_dpId(int(temp_dpId), device)
                    if temp_code is not None:
                        dpId = int(temp_dpId)
                        code = temp_code
                        value = state[temp_dpId]

            if code is not None and dpId is not None:
                return code, dpId, value, True
        if code is None and fail_if_code_not_found:
            LOGGER.warning(f"_read_code_value_from_state FAILED => {device.id} <=> {device.name} <=> {state} <=> {device.local_strategy}")
            return None, None, None, False
        if dpId is None and fail_if_dpid_not_found:
            LOGGER.warning(f"_read_code_value_from_state FAILED => {device.id} <=> {device.name} <=> {state} <=> {device.local_strategy}")
            return None, None, None, False
        return code, dpId, value, True

    def convert_device_report_status_list(self, device_id: str, status_in: list) -> list:
        status = copy.deepcopy(status_in)
        for item in status:
            code, dpId, value, result_ok = self._read_code_dpid_value_from_state(device_id, item)
            if result_ok:
                item["code"] = code
                item["dpId"] = dpId
                item["value"] = value
            else:
                LOGGER.warning(f"convert_device_report_status_list code retrieval failed => {item} <=>{device_id}")
        return status

    def on_message(self, source: str, msg: str):
        dev_id = self._get_device_id_from_message(msg)
        if not dev_id:
            LOGGER.warning(f"dev_id {dev_id} not found!")
            return
        
        if self.device_watcher.is_watched(dev_id):
            LOGGER.warning(f"WD: on_message => {msg}")

        new_message = self._convert_message_for_all_accounts(msg)
        if status_list := self._get_status_list_from_message(msg):
            self.multi_source_handler.register_status_list_from_source(dev_id, source, status_list)
            if self.device_watcher.is_watched(dev_id):
                LOGGER.warning(f"WD: on_message status list => {status_list}")
        
        if source in self.accounts:
            self.accounts[source].on_message(new_message)

    def _get_device_id_from_message(self, msg: str) -> str | None:
        protocol = msg.get("protocol", 0)
        data = msg.get("data", {})
        if (dev_id := data.get("devId", None)):
            return dev_id
        if protocol == PROTOCOL_OTHER:
            if bizData := data.get("bizData", None):
                if dev_id := bizData.get("devId", None):
                    return dev_id
        return None
    
    def _get_status_list_from_message(self, msg: str) -> str | None:
        protocol = msg.get("protocol", 0)
        data = msg.get("data", {})
        if protocol == PROTOCOL_DEVICE_REPORT and "status" in data:
            return data["status"]
        return None

    def _convert_message_for_all_accounts(self, msg: str) -> str:
        protocol = msg.get("protocol", 0)
        data = msg.get("data", {})
        if protocol == PROTOCOL_DEVICE_REPORT:
            return msg
        elif protocol == PROTOCOL_OTHER:
            if hasattr(data, "devId"):
                return msg
            else:
                if bizData := data.get("bizData", None):
                    if dev_id := bizData.get("devId", None):
                        data["devId"] = dev_id
        return msg

    def query_scenes(self) -> list:
        return_list = []
        for account in self.accounts.values():
            return_list = append_lists(return_list, account.query_scenes())
        return return_list

    def send_commands(
            self, device_id: str, commands: list[dict[str, Any]]
    ):
        virtual_function_commands: list[dict[str, Any]] = []
        regular_commands: list[dict[str, Any]] = []
        if device := self.device_map.get(device_id, None):
            virtual_function_list = self.virtual_function_handler.get_category_virtual_functions(device.category)
            for command in commands:
                command_code  = command["code"]
                command_value = command["value"]
                LOGGER.debug(f"Base command : {command}")
                vf_found = False
                for virtual_function in virtual_function_list:
                    if (
                        command_code == virtual_function.key or
                        command_code in virtual_function.vf_reset_state
                    ):
                        command_dict = {"code": command_code, "value": command_value, "virtual_function": virtual_function}
                        virtual_function_commands.append(command_dict)
                        vf_found = True
                        break
                if not vf_found:
                    regular_commands.append(command)
        
        if virtual_function_commands:
            self.virtual_function_handler.process_virtual_function(device_id, virtual_function_commands)

        if regular_commands:
            for account in self.accounts.values():
                account.send_commands(device_id, regular_commands)

    def get_device_stream_allocate(
            self, device_id: str, stream_type: Literal["flv", "hls", "rtmp", "rtsp"]
    ) -> Optional[str]:
        for account in self.accounts.values():
            if stream_allocate := account.get_device_stream_allocate(device_id, stream_type):
                return stream_allocate
