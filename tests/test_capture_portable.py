import json
import tempfile
import unittest
import socket
import threading
import time
from pathlib import Path
from unittest.mock import patch

import enhanced_capture as capture


USAGES = [0x66, 0x52, 0x51, 0x50, 0x4f, 0x28, 0xf1, 0x4a, 0x65, 0x3e, 0x80, 0x81, 0x35]
SCOPE = r'\device\umdfctrldev-11111111-2222-3333-4444-555555555555'


class CapturePortabilityTests(unittest.TestCase):
    def test_every_native_usage_maps_to_one_configurable_position(self):
        for position, usage in enumerate(USAGES):
            self.assertEqual(capture.positions([usage]), {position})
        self.assertEqual(capture.positions([]), set())
        for invalid in [None, [True], [0x04], USAGES, [0x80]*4]:
            with self.assertRaises(ValueError): capture.positions(invalid)

    def test_all_edges_require_filtered_source_and_generation(self):
        requests=[]
        with patch.object(capture,'bridge_request',side_effect=lambda request: requests.append(request) or {'accepted':True}):
            for position in range(13): capture.command(position,True,72)
        for request in requests:
            self.assertEqual(request.get('source'),'filtered-remote')
            self.assertEqual(request.get('generation'),72)

    def test_synthetic_cleanup_is_distinct_from_true_physical_release(self):
        requests=[]
        with patch.object(capture,'bridge_request',side_effect=lambda request: requests.append(request) or {'accepted':True}):
            capture.command(9,False,72,synthetic=True)
        self.assertTrue(requests[0]['synthetic'])
        physical=[];synthetic=[]
        relay=capture.EdgeRelay(lambda *edge:physical.append(edge),lambda *edge:synthetic.append(edge))
        relay.feed({9});relay.clear()
        self.assertEqual(physical,[(9,True)])
        self.assertEqual(synthetic,[(9,False)])

    def test_duplicate_launch_does_not_clear_quit_marker(self):
        import capture_support
        with tempfile.TemporaryDirectory() as folder,patch.object(capture,'DATA',Path(folder)),patch.object(capture.ctypes.windll.shell32,'IsUserAnAdmin',return_value=True),patch.object(capture_support.CaptureInstance,'__enter__',side_effect=RuntimeError('already running')),patch.object(capture,'_run_owned') as owned:
            marker=Path(folder)/'capture-stop.json';marker.write_text('{}')
            with self.assertRaises(RuntimeError):capture.run()
            self.assertTrue(marker.exists());owned.assert_not_called()

    def test_unknown_and_legacy_gadgets_refuse_new_injection(self):
        identity={'pid':42,'instance':'selected','lifetime':'new'}
        previous={'identity':{**identity,'lifetime':'old'},'hostStarted':10,'version':'v3'}
        self.assertEqual(capture.attachment_mode(previous,identity,'v4',10,[]),'restart-required')
        self.assertEqual(capture.attachment_mode({},identity,'v4',10,['unknown-gadget.dll']),'restart-required')
        self.assertEqual(capture.attachment_mode({},identity,'v4',10,[]),'fresh')

    def test_known_current_gadget_reuses_only_exact_host_start_and_instance(self):
        identity={'pid':42,'instance':'selected','lifetime':'new'}
        previous={'identity':{**identity,'lifetime':'old'},'hostStarted':10,'version':'v4'}
        self.assertEqual(capture.attachment_mode(previous,identity,'v4',10,[]),'reuse')
        self.assertEqual(capture.attachment_mode(previous,{**identity,'instance':'other'},'v4',10,[]),'restart-required')
        self.assertEqual(capture.attachment_mode(previous,identity,'v4',11,[]),'fresh')
        self.assertFalse(capture.attachment_reusable({'identity':identity,'version':'v4'},identity,'v4',10))

    def test_capture_uses_user_data_and_package_resource_roots(self):
        from rc003_bridge.paths import DATA, ROOT
        self.assertEqual(getattr(capture,'DATA',None),DATA)
        self.assertEqual(capture.ROOT,ROOT)
        self.assertEqual(capture.CAPTURE_SCRIPT_NAME,'enhanced_capture_v4.js')

    def test_calibration_requires_fresh_device_scoped_voice(self):
        self.assertTrue(capture.voice_proof_matches(10000,[9990],10080))
        for probe, times, now in [(10000,[],10080),(10000,[9500],10080),(10000,[9990],12000),(True,[1],2)]:
            self.assertFalse(capture.voice_proof_matches(probe,times,now))
        self.assertEqual(capture.calibration_scope(SCOPE),SCOPE)
        for name in ['',None,r'\device\ordinary-keyboard']:
            with self.assertRaises(ValueError): capture.calibration_scope(name)

    def test_wire_report_needs_exact_scope_generation_and_full_filter(self):
        decode=getattr(capture,'filtered_positions',None)
        self.assertIsNotNone(decode,'full-filter gate is missing')
        event={'kind':'keys','usages':[0x66,0x3e,0x80],'objectName':SCOPE,'generation':7,'directionFiltered':True,'allKeysFiltered':True}
        self.assertEqual(decode(event,SCOPE,7,True,True,None),{0,9,10})
        for altered in [{**event,'objectName':'other'}, {**event,'generation':8}, {**event,'allKeysFiltered':False}]:
            self.assertIsNone(decode(altered,SCOPE,7,True,True,None))
        self.assertEqual(decode(event,SCOPE,7,False,True,None),set())
        self.assertEqual(decode(event,SCOPE,7,True,False,None),set())
        self.assertEqual(decode(event,SCOPE,7,True,True,{'reason':'native-pending'}),set())

    def test_bridge_outage_retries_release_without_duplicate_down(self):
        sent=[]; available=True
        def deliver(position,down):
            if not available: raise ConnectionRefusedError('bridge restarting')
            sent.append((position,down))
        relay=capture.EdgeRelay(deliver);relay.feed({0,9});relay.feed({0,9})
        available=False;relay.clear();available=True;relay.clear()
        self.assertEqual(sent,[(0,True),(9,True),(0,False),(9,False)])

    def test_shutdown_marker_is_in_user_data(self):
        running=getattr(capture,'capture_running',None)
        self.assertIsNotNone(running,'helper cannot honor desktop quit')
        with tempfile.TemporaryDirectory() as folder, patch.object(capture,'DATA',Path(folder)):
            self.assertTrue(running())
            (Path(folder)/'capture-stop.json').write_text('{}')
            self.assertFalse(running())

    def test_attachment_needs_live_single_device_and_authenticated_bridge_permission(self):
        gate=getattr(capture,'attachment_permitted',None)
        self.assertIsNotNone(gate,'injection is not guarded by live bridge and device')
        self.assertTrue(gate({'allowed':True,'generation':7},1))
        for permit, count in [({'allowed':False,'generation':7},1), ({'allowed':True},1), ({'allowed':True,'generation':True},1), ({'allowed':True,'generation':7},0), ({'allowed':True,'generation':7},2)]:
            self.assertFalse(gate(permit,count))

    def test_bridge_loss_expires_helper_but_temporarily_denies_permission(self):
        guard_type=getattr(capture,'BridgeGuard',None)
        self.assertIsNotNone(guard_type,'missing bridge death guard')
        now=[100.0]
        with patch.object(capture,'capture_running',return_value=True), patch.object(capture.time,'monotonic',side_effect=lambda:now[0]), patch.object(capture,'bridge_request',side_effect=[{'allowed':True,'generation':7},ConnectionRefusedError('gone')]):
            guard=guard_type();self.assertTrue(guard.refresh()['allowed'])
            now[0]=101
            with self.assertRaises(ConnectionRefusedError):guard.refresh()
            self.assertTrue(guard.alive());now[0]=111;self.assertFalse(guard.alive())

    def test_served_all_key_report_is_forwarded_only_after_requested_binding(self):
        identity={'pid':42,'instance':'selected','lifetime':'fresh'}
        stop=threading.Event();sent=[];states=[]
        with tempfile.TemporaryDirectory() as folder, patch.object(capture,'DATA',Path(folder)), patch.object(capture,'same_target',side_effect=lambda _:not stop.is_set()), patch.object(capture,'capture_status',side_effect=lambda phase,**_:states.append(phase)), patch.object(capture,'bridge_request',return_value={'allowed':True,'generation':7}), patch.object(capture,'command',side_effect=lambda *args:sent.append(args)):
            # Fresh proof is still required before an unsolicited bound message.
            with socket.socket() as server:
                server.bind(('127.0.0.1',0));server.listen(1);server.settimeout(.05)
                worker=threading.Thread(target=capture.serve,args=(server,identity,'test-token',[]));worker.start()
                try:
                    with socket.create_connection(server.getsockname()) as client:
                        client.sendall((json.dumps({'kind':'hello','pid':42,'token':'test-token','protocol':3,'build':'remote-filter-v4'})+'\n').encode())
                        client.sendall((json.dumps({'kind':'bound','objectName':SCOPE})+'\n').encode())
                        client.sendall((json.dumps({'kind':'keys','usages':[0x66,0x3e,0x80],'objectName':SCOPE,'generation':7,'directionFiltered':True,'allKeysFiltered':True})+'\n').encode())
                        time.sleep(.06);self.assertEqual(sent,[]);self.assertNotIn('ready',states)
                finally:stop.set();worker.join(2)
                self.assertFalse(worker.is_alive())

    def test_cached_binding_dispatches_real_filtered_edges_for_every_key(self):
        identity={'pid':42,'instance':'selected','lifetime':'fresh'}
        stop=threading.Event();sent=[]
        with tempfile.TemporaryDirectory() as folder, patch.object(capture,'DATA',Path(folder)), patch.object(capture,'same_target',side_effect=lambda _:not stop.is_set()), patch.object(capture,'capture_status'), patch.object(capture,'bridge_request',return_value={'allowed':True,'generation':7}), patch.object(capture,'command',side_effect=lambda *args:sent.append(args)):
            (Path(folder)/'capture-calibration.json').write_text(json.dumps({'identity':identity,'objectName':SCOPE}))
            with socket.socket() as server:
                server.bind(('127.0.0.1',0));server.listen(1);server.settimeout(.05)
                worker=threading.Thread(target=capture.serve,args=(server,identity,'test-token',[]));worker.start()
                try:
                    with socket.create_connection(server.getsockname()) as client:
                        client.sendall((json.dumps({'kind':'hello','pid':42,'token':'test-token','protocol':3,'build':'remote-filter-v4'})+'\n').encode())
                        client.sendall((json.dumps({'kind':'bound','objectName':SCOPE})+'\n').encode())
                        for usage in USAGES:
                            for usages in [[usage],[]]:
                                client.sendall((json.dumps({'kind':'keys','usages':usages,'objectName':SCOPE,'generation':7,'directionFiltered':True,'allKeysFiltered':True})+'\n').encode())
                        deadline=time.monotonic()+1
                        while len(sent)<26 and time.monotonic()<deadline:time.sleep(.01)
                        self.assertEqual(sent,[(position,down,7) for position in range(13) for down in (True,False)])
                finally:stop.set();worker.join(2)
                self.assertFalse(worker.is_alive())


if __name__=='__main__':unittest.main()
