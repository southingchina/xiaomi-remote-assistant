"""Windows paired-device discovery and ATVV GATT transport, no re-pairing."""
import asyncio
import uuid

SERVICE = 'ab5e0001-5a21-4f05-bc7d-af01f617b664'
TX = 'ab5e0002-5a21-4f05-bc7d-af01f617b664'
AUDIO = 'ab5e0003-5a21-4f05-bc7d-af01f617b664'
CONTROL = 'ab5e0004-5a21-4f05-bc7d-af01f617b664'
BATTERY_SERVICE = '0000180f-0000-1000-8000-00805f9b34fb'
BATTERY_LEVEL = '00002a19-0000-1000-8000-00805f9b34fb'


async def wait_operation(operation, timeout, dispose=None):
    """Bound native WinRT work even when Cancel never completes after radio loss.

    PyWinRT's __await__ waits for the native completion *after* cancellation.
    Wait on our own Future instead; retire late resources without reusing them.
    Coroutine doubles are supported for transport tests, not used by WinRT.
    """
    if not hasattr(type(operation), 'completed'):
        return await asyncio.wait_for(operation, timeout)
    loop = asyncio.get_running_loop()
    future = loop.create_future()

    def complete(op, _status):
        def deliver():
            try:
                value = op.get_results()
            except Exception as error:
                if not future.done(): future.set_exception(error)
            else:
                if not future.done(): future.set_result(value)
                elif dispose:
                    try: dispose(value)
                    except Exception: pass
        try: loop.call_soon_threadsafe(deliver)
        except RuntimeError:
            # Loop is already closed. Release a device returned after shutdown.
            if dispose:
                try: dispose(op.get_results())
                except Exception: pass

    operation.completed = complete
    try:
        return await asyncio.wait_for(future, timeout)
    except (asyncio.CancelledError, TimeoutError):
        try: operation.cancel()
        except Exception: pass
        raise


def close_result(value):
    if value is not None: value.close()


def close_services(result):
    for service in result.services:
        try: service.close()
        except Exception: pass


def battery_level(data):
    return data[0] if isinstance(data,(bytes,bytearray)) and len(data)==1 and data[0]<=100 else None


def buffer_bytes(buffer):
    from winrt.windows.storage.streams import DataReader
    reader = DataReader.from_buffer(buffer)
    data = bytearray(buffer.length); reader.read_bytes(data)
    return bytes(data)


async def paired_devices(names):
    from winrt.windows.devices.bluetooth import BluetoothLEDevice
    from winrt.windows.devices.enumeration import DeviceInformation
    selector = BluetoothLEDevice.get_device_selector_from_pairing_state(True)
    devices = await wait_operation(DeviceInformation.find_all_async_aqs_filter(selector), 8)
    wanted = {n.strip().casefold() for n in names}
    return [{'id': d.id, 'name': d.name} for d in devices if d.name.strip().casefold() in wanted]


class BleTransport:
    def __init__(self, callback, progress=None):
        self.callback = callback
        self.progress = progress or (lambda stage: None)
        self.device = self.service = self.session = self.tx = None
        self.tokens = []
        self.closed = True
        self.battery_service = self.battery_task = None

    async def connect(self, device_id):
        from winrt.windows.devices.bluetooth import BluetoothLEDevice, BluetoothCacheMode
        from winrt.windows.devices.bluetooth.genericattributeprofile import GattClientCharacteristicConfigurationDescriptorValue as CCCD, GattSession
        self.closed = False
        self.progress('opening_device')
        self.device = await wait_operation(BluetoothLEDevice.from_id_async(device_id), 10, close_result)
        if self.device is None: raise RuntimeError('Paired Bluetooth device is unavailable')
        self.progress('discovering_services')
        result = await wait_operation(self.device.get_gatt_services_with_cache_mode_async(BluetoothCacheMode.UNCACHED), 10, close_services)
        if int(result.status) != 0: raise RuntimeError('GATT service discovery failed: '+str(result.status))
        services = list(result.services)
        self.service = next((s for s in services if str(s.uuid).casefold() == SERVICE), None)
        self.battery_service = next((s for s in services if str(s.uuid).casefold() == BATTERY_SERVICE), None)
        for service in services:
            if service is not self.service and service is not self.battery_service: service.close()
        if self.service is None: raise RuntimeError('Paired device has no RC003 ATVV service')
        self.progress('discovering_characteristics')
        result = await wait_operation(self.service.get_characteristics_with_cache_mode_async(BluetoothCacheMode.UNCACHED), 10)
        if int(result.status) != 0: raise RuntimeError('ATVV characteristic discovery failed')
        chars = {str(c.uuid).casefold(): c for c in result.characteristics}
        if not all(key in chars for key in (TX,AUDIO,CONTROL)): raise RuntimeError('ATVV service is incomplete')
        self.tx = chars[TX]
        self.progress('opening_session')
        self.session = await wait_operation(GattSession.from_device_id_async(self.device.bluetooth_device_id), 5, close_result)
        if self.session.can_maintain_connection: self.session.maintain_connection = True
        for key, kind in ((CONTROL,'control'),(AUDIO,'audio')):
            self.progress('subscribing_'+kind)
            char = chars[key]
            def changed(sender, args, channel=kind):
                if not self.closed:
                    try: self.callback(channel, buffer_bytes(args.characteristic_value))
                    except Exception as error: self.callback('transport_error',str(error))
            token = char.add_value_changed(changed)
            self.tokens.append((char,token))
            status = await wait_operation(char.write_client_characteristic_configuration_descriptor_async(CCCD.NOTIFY), 5)
            if int(status) != 0: raise RuntimeError('Cannot subscribe ATVV '+kind)
        def connection_changed(sender, args):
            if not self.closed and int(sender.connection_status) == 0: self.callback('disconnected',None)
        token = self.device.add_connection_status_changed(connection_changed)
        self.connection_token = token
        # Optional telemetry never delays ATVV setup or propagates a voice error.
        self.battery_task = asyncio.create_task(self.monitor_battery())
        return {'name': self.device.name, 'transport':'winrt-ble-gatt'}

    async def monitor_battery(self):
        from winrt.windows.devices.bluetooth import BluetoothCacheMode
        from winrt.windows.devices.bluetooth.genericattributeprofile import GattClientCharacteristicConfigurationDescriptorValue as CCCD, GattCharacteristicProperties as Props
        try:
            if self.battery_service is None:
                self.callback('battery_issue','Battery Service is unavailable'); return
            result = await wait_operation(self.battery_service.get_characteristics_for_uuid_with_cache_mode_async(uuid.UUID(BATTERY_LEVEL),BluetoothCacheMode.UNCACHED),4)
            if int(result.status)!=0 or not result.characteristics:
                raise RuntimeError('Battery Level characteristic is unavailable')
            char = result.characteristics[0]
            subscribed = False
            if char.characteristic_properties & Props.NOTIFY:
                def changed(sender,args):
                    if not self.closed:
                        try: self.callback('battery',(buffer_bytes(args.characteristic_value),'gatt-notify'))
                        except Exception as error: self.callback('battery_issue',str(error))
                token=char.add_value_changed(changed)
                self.tokens.append((char,token))
                try:
                    status=await wait_operation(char.write_client_characteristic_configuration_descriptor_async(CCCD.NOTIFY),3)
                    subscribed=int(status)==0
                except Exception: pass
                if not subscribed:
                    char.remove_value_changed(token);self.tokens.remove((char,token))
            while not self.closed:
                if char.characteristic_properties & Props.READ:
                    try:
                        reading=await wait_operation(char.read_value_with_cache_mode_async(BluetoothCacheMode.UNCACHED),3)
                        if int(reading.status)!=0: raise RuntimeError('Battery Level read failed')
                        if not self.closed: self.callback('battery',(buffer_bytes(reading.value),'gatt-read'))
                    except Exception as error:
                        # A failed initial read must not erase a valid notify.
                        if not subscribed and not self.closed: self.callback('battery_issue',str(error))
                if subscribed: return
                if not char.characteristic_properties & Props.READ:
                    raise RuntimeError('Battery Level cannot be read or subscribed')
                await asyncio.sleep(60)
        except asyncio.CancelledError: raise
        except Exception as error:
            if not self.closed: self.callback('battery_issue',str(error))

    async def write(self, data):
        from winrt.windows.storage.streams import DataWriter
        from winrt.windows.devices.bluetooth.genericattributeprofile import GattWriteOption, GattCharacteristicProperties
        if self.tx is None: raise RuntimeError('No active ATVV command channel')
        writer = DataWriter(); writer.write_bytes(bytes(data)); buffer = writer.detach_buffer()
        option = GattWriteOption.WRITE_WITHOUT_RESPONSE if self.tx.characteristic_properties & GattCharacteristicProperties.WRITE_WITHOUT_RESPONSE else GattWriteOption.WRITE_WITH_RESPONSE
        status = await wait_operation(self.tx.write_value_with_option_async(buffer,option), 3)
        if int(status) != 0: raise RuntimeError('ATVV write failed: '+str(status))

    async def close(self):
        self.closed = True
        if self.battery_task:
            self.battery_task.cancel()
            try: await self.battery_task
            except asyncio.CancelledError: pass
            self.battery_task = None
        for char, token in self.tokens:
            try: char.remove_value_changed(token)
            except Exception: pass
        self.tokens.clear()
        if self.device and hasattr(self,'connection_token'):
            try: self.device.remove_connection_status_changed(self.connection_token)
            except Exception: pass
        for value in (self.session,self.service,self.battery_service,self.device):
            if value:
                try: value.close()
                except Exception: pass
        self.device = self.service = self.session = self.tx = None
        self.battery_service = None
