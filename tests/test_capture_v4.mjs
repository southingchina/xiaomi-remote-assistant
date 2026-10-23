import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';

const source = fs.readFileSync(new URL('../enhanced_capture_v4.js', import.meta.url), 'utf8');
const remote = '\\device\\umdfctrldev-11111111-2222-3333-4444-555555555555';
const keyboard = '\\device\\ordinary-keyboard';
const config = {port: 1234, token: 'test-secret', address: 'aa:bb:cc:dd:ee:ff'};
const number = value => ({toUInt32: () => value >>> 0, isNull: () => value === 0});
const report = usages => {
  const bytes = new Uint8Array(9); bytes[0] = 1;
  usages.forEach((u, i) => {bytes[3 + 2 * i] = u & 255; bytes[4 + 2 * i] = u >> 8;});
  return bytes;
};

class Pointer {
  constructor(bytes, offset = 0, state = {}) {this.bytes = bytes; this.offset = offset; this.state = state;}
  add(offset) {return new Pointer(this.bytes, this.offset + offset, this.state);}
  isNull() {return false;}
  readU8() {return this.bytes[this.offset];}
  readU16() {return this.readU8() | this.bytes[this.offset + 1] << 8;}
  readU32() {return new DataView(this.bytes.buffer).getUint32(this.offset, true);}
  writeU16(value) {new DataView(this.bytes.buffer).setUint16(this.offset, value, true);}
  writeU32(value) {new DataView(this.bytes.buffer).setUint32(this.offset, value, true);}
  readPointer() {return this.state.pointers?.get(this.offset) ?? number(0);}
  readUtf16String(length) {return new TextDecoder('utf-16le').decode(this.bytes.slice(this.offset, this.offset + length * 2));}
  readByteArray(length) {this.state.reads=(this.state.reads??0)+1;return this.bytes.slice(this.offset, this.offset + length).buffer;}
  writeByteArray(input) {
    this.state.writes=(this.state.writes??0)+1;
    if (this.state.failWrite) throw Error('report is not writable');
    const bytes = new Uint8Array(input);
    if (this.state.failAfterBytes !== undefined) {
      const length = this.state.failAfterBytes; delete this.state.failAfterBytes;
      this.bytes.set(bytes.slice(0, length), this.offset);
      throw Error('partial report write');
    }
    this.bytes.set(bytes, this.offset);
    if (this.state.afterWrite) this.state.afterWrite(this.bytes);
  }
}

async function harness(options = {}) {
  let now = 10000;
  const hooks = new Map(), events = [], intervals = [], connections = [];
  const names = new Map([['remote', remote], ['keyboard', keyboard], ['matching', '\\device\\vid&012717_pid&32b8']]);
  const modes = new Map(), modeQueries = new Map();
  function newConnection() {
    const state = {inbox: [], pendingRead: undefined, closed: false};
    state.connection = {
      input: {read: () => state.inbox.length ? Promise.resolve(state.inbox.shift()) : new Promise(resolve => {state.pendingRead = resolve;})},
      output: {writeAll: async bytes => events.push(JSON.parse(new TextDecoder().decode(bytes)))},
      // Deliberately keep a pending input.read unresolved after close. Frida
      // sockets can remain half-open and continue accepting output writes.
      close: async () => {state.closed = true;}
    };
    connections.push(state);
    return state.connection;
  }
  const context = vm.createContext({
    Process: {id: 42, pointerSize: 8, getModuleByName: () => ({getExportByName: name => name})},
    NativeFunction: function (name) {
      if (name === 'NtQueryInformationFile') {
        if (options.noModeApi) throw Error('mode query unavailable');
        return (handle, _, output, length, informationClass) => {
          assert.equal(length, 4); assert.equal(informationClass, 16);
          const key = handle.toString(), mode = modes.get(key) ?? {value: 0x20, status: 0};
          modeQueries.set(key, (modeQueries.get(key) ?? 0) + 1);
          output.writeU32(mode.value);
          return mode.status;
        };
      }
      return (handle, _, output) => {
        const value = names.get(handle.toString()) ?? '';
        const bytes = Uint8Array.from(Buffer.from(value, 'utf16le'));
        output.writeU16(bytes.length);
        output.state.pointers = new Map([[8, new Pointer(bytes)]]);
        return 0;
      };
    },
    Memory: {alloc: size => new Pointer(new Uint8Array(size))},
    Interceptor: {attach: (name, callbacks) => hooks.set(name, callbacks)},
    Socket: {connect: async () => newConnection()},
    setInterval: callback => {intervals.push(callback); return intervals.length;},
    Date: class extends Date {static now() {return now;}},
    Uint8Array, ArrayBuffer, Map, Set, Promise, JSON, Number, Math
  });
  vm.runInContext(source.replace('__CONFIG__', JSON.stringify(config)), context);
  async function settle() {for (let i = 0; i < 30; i++) await Promise.resolve();}
  await settle();
  const api = {
    events,
    async command(command, connectionIndex = connections.length - 1) {
      const bytes = Uint8Array.from(Buffer.from(JSON.stringify({token: config.token, ...command}) + '\n')).buffer;
      const state = connections[connectionIndex];
      if (state.pendingRead) {const resolve = state.pendingRead; state.pendingRead = undefined; resolve(bytes);} else state.inbox.push(bytes);
      await settle();
    },
    async frame(usages, options = {}) {
      const bytes = options.bytes ?? report(usages);
      const output = new Pointer(bytes, 0, options.memory ?? {});
      const input = new Pointer(options.input ?? Uint8Array.from([0, 0, 0, 0, 2, 1, 0, 0]));
      const iosb=new Pointer(new Uint8Array(16));iosb.writeU32(options.iosb??0);
      const args = [
        {toString: () => options.device ?? 'remote'},
        number(options.event ?? 0), number(options.apc ?? 0), number(0),
        iosb, number(options.ioctl ?? 0x80018483),
        input, number(options.inLength ?? 8), output, number(options.outLength ?? bytes.length)
      ];
      const hook = hooks.get('NtDeviceIoControlFile'), invocation = {};
      hook.onEnter.call(invocation, args);
      const submitted = [...bytes];
      if (options.beforeLeave) await options.beforeLeave(bytes);
      hook.onLeave.call(invocation, number(options.retval ?? 0));
      await settle();
      return {submitted, restored: [...bytes]};
    },
    async bind() {
      await api.frame([0x3e]);
      await api.command({kind: 'bind', objectName: remote});
    },
    async enable(generation = 7) {
      await api.command({kind: 'direction-filter', objectName: remote, enabled: true, ttlMs: 1500, generation});
    },
    async arm() {await api.bind(); await api.enable(); await api.frame([]); events.length = 0;},
    clear() {events.length = 0;},
    mode(value, status = 0, device = 'remote') {modes.set(device, {value, status});},
    addSource(device, objectName) {names.set(device,objectName);},
    modeQueries(device = 'remote') {return modeQueries.get(device) ?? 0;},
    connectionCount() {return connections.length;},
    closedConnectionCount() {return connections.filter(state => state.closed).length;},
    closeHandle(device = 'remote') {hooks.get('NtClose').onEnter([{toString: () => device}]);},
    advance(ms) {now += ms;},
    async heartbeat() {intervals[0](); await settle(); return events.findLast(event => event.kind === 'heartbeat');},
    async disconnect() {const state=connections.at(-1);if (state.pendingRead) {const resolve = state.pendingRead; state.pendingRead = undefined; resolve(new ArrayBuffer(0));} await settle();}
  };
  return api;
}

const allUsages = [0x66, 0x52, 0x51, 0x50, 0x4f, 0x28, 0xf1, 0x4a, 0x65, 0x3e, 0x80, 0x81, 0x35];

test('all 13 physical keys are cleared before submission and emitted with scope and generation', async () => {
  for (const usage of allUsages) {
    const h = await harness(); await h.arm();
    const result = await h.frame([usage]);
    assert.deepEqual(result.submitted, [...report([])], `usage ${usage.toString(16)} leaked`);
    assert.deepEqual(result.restored, [...report([usage])]);
    assert.deepEqual(h.events.filter(e => e.kind === 'keys'), [{kind: 'keys', usages: [usage], directionFiltered: true, allKeysFiltered: true, generation: 7, objectName: remote}]);
    h.clear(); await h.frame([]);
    assert.deepEqual(h.events.find(e => e.kind === 'keys')?.usages, []);
  }
});

test('hello distinguishes the all-key protocol from legacy direction-only capture', async () => {
  const h = await harness(); const hello = h.events.find(e => e.kind === 'hello');
  assert.equal(hello.protocol, 3); assert.equal(hello.build, 'remote-filter-v4');
});

test('three slots preserve unknown usages while clearing only supported remote keys', async () => {
  const h = await harness(); await h.arm();
  const result = await h.frame([0x66, 0x04, 0x3e]);
  assert.deepEqual(result.submitted, [...report([0, 0x04, 0])]);
  assert.deepEqual(result.restored, [...report([0x66, 0x04, 0x3e])]);
  assert.deepEqual(h.events.find(e => e.kind === 'keys').usages, [0x66, 0x3e]);
});

test('ordinary and VID/PID matching devices never get filtered or forwarded without exact calibration', async () => {
  const h = await harness(); await h.arm();
  for (const device of ['keyboard', 'matching']) for (const usage of allUsages) {
    h.clear(); const result = await h.frame([usage], {device});
    assert.deepEqual(result.submitted, [...report([usage])]);
    assert.equal(h.events.filter(e => e.kind === 'keys').length, 0);
  }
});

test('uncalibrated Voice generates a proof request but never suppresses or dispatches', async () => {
  const h = await harness(); h.clear(); const result = await h.frame([0x3e]);
  assert.deepEqual(result.submitted, [...report([0x3e])]);
  assert.equal(h.events.find(e => e.kind === 'voice-probe')?.objectName, remote);
  assert.equal(h.events.filter(e => e.kind === 'keys').length, 0);
});

test('calibration alone never filters or emits keys, including the previously dead usages', async () => {
  const h = await harness(); await h.bind(); h.clear();
  for (const usage of allUsages) assert.deepEqual((await h.frame([usage])).submitted, [...report([usage])]);
  assert.equal(h.events.filter(e => e.kind === 'keys').length, 0);
});

test('each physical key held during arming requires a neutral frame before filtering', async () => {
  for (const usage of allUsages) {
    const h = await harness(); await h.bind(); await h.enable(); h.clear();
    assert.deepEqual((await h.frame([usage])).submitted, [...report([usage])]);
    assert.equal(h.events.filter(e => e.kind === 'keys').length, 0);
    await h.frame([]);
    assert.deepEqual((await h.frame([usage])).submitted, [...report([])]);
  }
});

test('expired, disabled, disconnected and backwards-clock leases fail open for all keys', async () => {
  for (const stop of [h => h.advance(1501), h => h.advance(-1), h => h.command({kind:'direction-filter',enabled:false}), h => h.disconnect()]) {
    const h = await harness(); await h.arm(); await stop(h); h.clear();
    for (const usage of allUsages) assert.deepEqual((await h.frame([usage])).submitted, [...report([usage])]);
    assert.equal(h.events.filter(e => e.kind === 'keys').length, 0);
  }
});

test('bad tokens, wrong scope, invalid generations and TTL never extend a lease', async () => {
  for (const invalid of [{token:'bad'}, {objectName:keyboard}, {generation:0}, {generation:'7'}, {ttlMs:1501}, {enabled:'true'}]) {
    const h = await harness(); await h.arm(); h.advance(1000);
    await h.command({kind:'direction-filter',objectName:remote,enabled:true,ttlMs:1500,generation:7,...invalid});
    h.advance(501); assert.deepEqual((await h.frame([0x66])).submitted, [...report([0x66])]);
  }
});

test('selector, report format and IOCTL mismatches never filter', async () => {
  for (const options of [{input:Uint8Array.from([0,0,0,0,3,1,0,0])}, {inLength:7}, {ioctl:0}, {bytes:Uint8Array.from([2,0,0,0x66,0,0,0,0,0])}]) {
    const h = await harness(); await h.arm(); const original = [...(options.bytes ?? report([0x66]))];
    assert.deepEqual((await h.frame([0x66],options)).submitted, original);
    assert.equal(h.events.filter(e => e.kind === 'keys').length, 0);
  }
});

test('failed clearing rolls back partial writes and emits no captured edge', async () => {
  const h = await harness(); await h.arm(); const result = await h.frame([0x66,0x3e,0x80],{memory:{failAfterBytes:2}});
  assert.deepEqual(result.submitted,[...report([0x66,0x3e,0x80])]);
  assert.equal(h.events.filter(e => e.kind === 'keys').length,0);
});

test('pending or failed completion restores immediately and faults this generation', async () => {
  for (const options of [{retval:0x103,iosb:0x103},{retval:0xc0000001,iosb:0xc0000001},{iosb:0xc0000001}]) {
    const h = await harness(); await h.arm(); const memory={};
    const result = await h.frame([0x66,0x3e,0x80],{...options,memory});
    assert.deepEqual(result.submitted,[...report([])]); assert.deepEqual(result.restored,[...report([0x66,0x3e,0x80])]);
    assert.equal(h.events.filter(e => e.kind === 'keys').length,0);
    assert.equal(h.events.find(e => e.kind === 'filter-fault')?.generation,7);
    const writes=memory.writes; await h.enable(); await h.heartbeat();
    assert.deepEqual((await h.frame([0x66])).submitted,[...report([0x66])]); assert.equal(memory.writes,writes);
    await h.enable(8); await h.frame([]); assert.deepEqual((await h.frame([0x66])).submitted,[...report([])]);
  }
});

test('a failed restoration faults the generation without forwarding', async () => {
  const h=await harness(); await h.arm(); const memory={afterWrite:()=>{memory.failWrite=true;}};
  await h.frame([0x3e],{memory});
  assert.equal(h.events.find(e => e.kind==='filter-fault')?.reason,'native-restore-failed');
  assert.equal(h.events.filter(e => e.kind === 'keys').length,0);
});

test('stalled socket fails open then reconnects; stale commands cannot alter new generation', async () => {
  const h=await harness(); await h.arm(); h.advance(1501);
  assert.deepEqual((await h.frame([0x3e])).submitted,[...report([0x3e])]);
  h.advance(1500); await h.heartbeat(); await h.heartbeat(); assert.equal(h.connectionCount(),2);
  await h.bind(); await h.enable(8); await h.frame([]); h.clear();
  await h.command({kind:'direction-filter',enabled:false},0);
  assert.deepEqual((await h.frame([0x3e])).submitted,[...report([])]);
  assert.equal(h.events.find(e => e.kind==='keys')?.generation,8);
});

test('closed/recycled handles lose the cached device identity', async () => {
  const h=await harness(); await h.arm(); h.closeHandle(); h.addSource('remote',keyboard); h.clear();
  assert.deepEqual((await h.frame([0x3e])).submitted,[...report([0x3e])]);
  assert.equal(h.events.filter(e => e.kind==='keys').length,0);
});

test('actual neutral after lease revocation is reported for the exact calibrated generation', async () => {
  const h=await harness(); await h.arm(); await h.frame([0x3e]);
  await h.command({kind:'direction-filter',enabled:false}); h.clear(); await h.frame([]);
  assert.deepEqual(h.events.filter(e=>e.kind==='neutral'),[{kind:'neutral',objectName:remote,generation:7}]);
  for(const options of [{device:'keyboard'},{device:'matching'},{input:Uint8Array.from([0,0,0,0,3,1,0,0])}]) {
    h.clear();await h.frame([],options);assert.equal(h.events.filter(e=>e.kind==='neutral').length,0);
  }
});

