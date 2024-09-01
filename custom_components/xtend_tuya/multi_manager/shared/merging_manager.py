from __future__ import annotations

import json

from .device import (
    XTDevice
)

class XTMergingManager:
    def merge_devices(device1: XTDevice, device2: XTDevice):
        XTMergingManager._merge_status(device1, device2)
        XTMergingManager._merge_function(device1, device2)
        XTMergingManager._merge_status_range(device1, device2)
        XTMergingManager._merge_local_strategy(device1, device2)

        #Now link the references so that they point to the same structure in memory
        device2.status_range = device1.status_range
        device2.function = device1.function
        device2.status = device1.status
        device2.local_strategy = device1.local_strategy

    def _merge_status(device1: XTDevice, device2: XTDevice):
        XTMergingManager._merge_dict(device1.status, device2.status)

    def _merge_function(device1: XTDevice, device2: XTDevice):
        for function_key in device1.function:
            if function_key in device2.function:
                XTMergingManager._merge_dict(device1.function[function_key].values, device2.function[function_key].values)
            else:
                device2.function[function_key] = device1.function[function_key]
        for function_key in device2.function:
            if function_key not in device1.function:
                device1.function[function_key] = device2.function[function_key]

    def _merge_status_range(device1: XTDevice, device2: XTDevice):
        XTMergingManager._merge_dict(device1.status_range, device2.status_range)
    
    def _merge_local_strategy(device1: XTDevice, device2: XTDevice):
        for dpId in device1.local_strategy:
            if dpId in device2.local_strategy:
                strategy1 = device1.local_strategy[dpId]
                strategy2 = device2.local_strategy[dpId]

                #Favor as the "main" strategy the one that doesn't use openAPI or Property Update
                st1_prop = strategy1.get("property_update", False)
                st2_prop = strategy2.get("property_update", False)
                st1_oapi = strategy1.get("use_open_api", False)
                st2_oapi = strategy2.get("use_open_api", False)
                if st1_oapi != st2_oapi:
                    if not st2_oapi:
                        strategy1 = device2.local_strategy[dpId]
                        strategy2 = device1.local_strategy[dpId]
                elif st1_prop != st2_prop:
                    if not st2_prop:
                        strategy1 = device2.local_strategy[dpId]
                        strategy2 = device1.local_strategy[dpId]


                XTMergingManager._copy_if_different(strategy1, strategy2, "value_convert")
                XTMergingManager._copy_if_different(strategy1, strategy2, "status_code", "status_code_alias")
                if "config_item" in strategy1 and "config_item" in strategy2:
                    XTMergingManager._merge_config_item(strategy1["config_item"], strategy2["config_item"])
                elif "config_item" in strategy1:
                    strategy2["config_item"] = strategy1["config_item"]
                else:
                    strategy1["config_item"] = strategy2["config_item"]
                if "property_update" in strategy1:
                    strategy2["property_update"] = strategy1["property_update"]
                else:
                    strategy1["property_update"] = False
                    strategy2["property_update"] = strategy1["property_update"]
                if "use_open_api" in strategy1:
                    strategy2["use_open_api"] = strategy1["use_open_api"]
                else:
                    strategy1["use_open_api"] = False
                    strategy2["use_open_api"] = strategy1["use_open_api"]
            else:
                device2.local_strategy[dpId] = device1.local_strategy[dpId]

    def _merge_config_item(conf1: dict, conf2: dict):
        XTMergingManager._merge_json_dict(conf2, conf1, "statusFormat")
        XTMergingManager._merge_json_dict(conf2, conf1, "valueDesc")
        XTMergingManager._copy_if_different(conf1, conf2, "valueType")
        if "enumMappingMap" in conf1 and "enumMappingMap" in conf2:
            XTMergingManager._merge_dict(conf1["enumMappingMap"], conf2["enumMappingMap"])
        elif "enumMappingMap" in conf1:
            conf2["enumMappingMap"] = conf1["enumMappingMap"]
        elif "enumMappingMap" in conf2:
            conf1["enumMappingMap"] = conf2["enumMappingMap"]
        XTMergingManager._copy_if_different(conf1, conf2, "pid")

    def _copy_if_different(dict1: dict, dict2: dict, key: any, alias_key: any = None):
        is_same, val1, val2 = XTMergingManager._is_dict_entry_the_same(dict1, dict2, key)
        if alias_key is not None:
            if alias_key not in dict1:
                dict1[alias_key] = list()
            if alias_key not in dict2:
                dict2[alias_key] = dict1[alias_key]
        if not is_same:
            dict2[key] = dict1[key]
            if alias_key is not None and val2 is not None:
                dict1[alias_key].append(val2)

    def _merge_json_dict(dict1: dict, dict2: dict, key: any):
        if key not in dict1 or key not in dict2:
            if key in dict1:
                dict2[key] = dict1[key]
            elif key in dict2:
                dict1[key] = dict2[key]
            else:
                dict1[key] = "{}"
                dict2[key] = dict1[key]
            return
        json_dict1 = json.loads(dict1[key])
        json_dict2 = json.loads(dict2[key])
        XTMergingManager._merge_dict(json_dict1, json_dict2)
        dict1[key] = json.dumps(json_dict1)
        dict2[key] = dict1[key]

    def _is_dict_entry_the_same(dict1: dict, dict2: dict, key: any):
        val1 = None
        if key in dict1:
            val1 = dict1[key]
        val2 = None
        if key in dict2:
            val2 = dict2[key]
        
        if val1 == val2:
            return True, val1, val2
        else:
            return False, val1, val2
        

    def _merge_dict(dict1: dict, dict2: dict):
        for key in dict1:
            if key not in dict2:
                dict2[key] = dict1[key]
        for key in dict2:
            if key not in dict1:
                dict1[key] = dict2[key]
    
    