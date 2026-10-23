"""Private stdio RPC for the native Bluetooth owner. Never dispatches input."""
import asyncio
import json
import sys
import winrt.runtime
from .bluetooth import BleTransport


async def run():
    loop = asyncio.get_running_loop()

    def emit(message):
        print(json.dumps(message),flush=True)

    def event(kind, data):
        if kind in ('audio','control'): data=bytes(data).hex()
        elif kind == 'battery': data=[bytes(data[0]).hex(),data[1]]
        loop.call_soon_threadsafe(emit,{'kind':kind,'data':data})

    async def heartbeat():
        while True:
            emit({'kind':'heartbeat'})
            await asyncio.sleep(1)

    transport = BleTransport(event,progress=lambda stage:emit({'kind':'stage','data':stage}))
    beat = asyncio.create_task(heartbeat())
    try:
        while line := await asyncio.to_thread(sys.stdin.buffer.readline):
            request = json.loads(line)
            command = request['command']
            try:
                if command == 'connect': result=await transport.connect(request['deviceId'])
                elif command == 'write': result=await transport.write(bytes.fromhex(request['data']))
                elif command == 'close':
                    await transport.close()
                    emit({'id':request['id'],'result':None})
                    return
                else: raise ValueError('Unknown Bluetooth worker command')
                emit({'id':request['id'],'result':result})
            except Exception as error:
                emit({'id':request['id'],'error':str(error) or type(error).__name__})
    finally:
        beat.cancel()
        try: await beat
        except asyncio.CancelledError: pass
        await transport.close()


if __name__ == '__main__':
    winrt.runtime.init_apartment(winrt.runtime.ApartmentType.MULTI_THREADED)
    try: asyncio.run(run())
    finally: winrt.runtime.uninit_apartment()
