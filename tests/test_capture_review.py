import json
import socket
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import enhanced_capture as capture

SCOPE = r'\device\umdfctrldev-11111111-2222-3333-4444-555555555555'
OTHER = r'\device\umdfctrldev-aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'


class CaptureReviewTests(unittest.TestCase):
    def test_ready_requires_actual_armed_filter_and_no_fault(self):
        phase=getattr(capture,'filter_phase',None)
        self.assertIsNotNone(phase)
        self.assertEqual(phase(True,True,True,None,None,None,{}),'ready')
        self.assertEqual(phase(True,True,False,None,None,None,{'gate':'waiting-neutral'}),'waiting_neutral')
        self.assertEqual(phase(True,True,False,None,None,None,{}),'standby')
        self.assertEqual(phase(True,False,False,None,None,None,{}),'standby')
        self.assertEqual(phase(True,True,True,{'reason':'native-pending'},None,None,{}),'filter_fault')
        self.assertEqual(phase(True,True,True,None,'bridge gone',None,{}),'waiting_bridge')
        self.assertEqual(phase(True,True,True,None,None,'edge rejected',{}),'waiting_bridge')
        self.assertEqual(phase(False,True,True,None,None,None,{}),'calibrating')

    def test_filter_fault_does_not_publish_ready(self):
        identity={'pid':42,'instance':'selected','lifetime':'fresh'}
        stop=threading.Event();states=[]
        with tempfile.TemporaryDirectory() as folder,patch.object(capture,'DATA',Path(folder)),patch.object(capture,'same_target',side_effect=lambda _:not stop.is_set()),patch.object(capture,'capture_status',side_effect=lambda phase,**details:states.append({'phase':phase,**details})),patch.object(capture,'bridge_request',return_value={'allowed':True,'generation':7}):
            (Path(folder)/'capture-calibration.json').write_text(json.dumps({'identity':identity,'objectName':SCOPE}))
            with socket.socket() as server:
                server.bind(('127.0.0.1',0));server.listen(1);server.settimeout(.05)
                worker=threading.Thread(target=capture.serve,args=(server,identity,'test-token',[]));worker.start()
                try:
                    with socket.create_connection(server.getsockname()) as client:
                        events=[{'kind':'hello','pid':42,'token':'test-token','protocol':3,'build':'remote-filter-v4'},
                                {'kind':'bound','objectName':SCOPE},
                                {'kind':'heartbeat','directionFilterArmed':True,'directionFilterGeneration':7},
                                {'kind':'filter-fault','objectName':SCOPE,'generation':7,'reason':'native-pending','ret':259,'iosbStatus':259}]
                        for event in events:client.sendall((json.dumps(event)+'\n').encode())
                        deadline=time.monotonic()+1
                        while not any(state.get('nativeIssue') for state in states) and time.monotonic()<deadline:time.sleep(.01)
                        faulted=[state for state in states if state.get('nativeIssue')]
                        self.assertTrue(faulted)
                        self.assertTrue(any(state['phase']=='ready' for state in states))
                        self.assertEqual(faulted[-1]['phase'],'filter_fault')
                        self.assertEqual(faulted[-1]['nativeIssue']['reason'],'native-pending')
                        bound_states=[state for state in states if state.get('calibrated') and state.get('directionFilter')=='standby']
                        self.assertTrue(all(state['phase']!='ready' for state in bound_states))
                finally:stop.set();worker.join(2)

    def calibration(self):
        factory=getattr(capture,'VoiceCalibration',None)
        self.assertIsNotNone(factory,'calibration must aggregate a full proof window')
        return factory()

    def test_two_correlated_objects_are_rejected_before_any_bind(self):
        proof=self.calibration()
        proof.add(SCOPE,10000,10010)
        self.assertIsNone(proof.choose([10000],10100))
        proof.add(OTHER,10100,10120)
        self.assertIsNone(proof.choose([10000],11260))
        self.assertEqual(proof.issue,'ambiguous-voice-proof')
        self.assertIsNone(proof.choose([10000],12000),'ambiguous raw proof cannot be reused')

    def test_unique_fresh_proof_binds_only_after_full_window_closes(self):
        proof=self.calibration();proof.add(SCOPE,10000,10010)
        self.assertIsNone(proof.choose([10000],11000))
        self.assertEqual(proof.choose([10000],11260),SCOPE)
        self.assertIsNone(proof.choose([10000],11300))

    def test_fresh_attempt_after_ambiguity_can_calibrate(self):
        proof=self.calibration();proof.add(SCOPE,10000,10010);proof.add(OTHER,10100,10120)
        self.assertIsNone(proof.choose([10000],11260))
        proof.add(SCOPE,12000,12010)
        self.assertEqual(proof.choose([10000,12000],13260),SCOPE)

    def test_delayed_competing_probe_still_invalidates_the_uncommitted_window(self):
        proof=self.calibration();proof.add(SCOPE,10000,10010)
        proof.add(OTHER,10100,11260)
        self.assertIsNone(proof.choose([10000],11270))
        self.assertEqual(proof.issue,'ambiguous-voice-proof')

    def test_verified_scope_cannot_be_replaced_by_time_correlated_object(self):
        proof=self.calibration();proof.add(OTHER,10000,10010)
        self.assertIsNone(proof.choose([10000],11260,current_scope=SCOPE))
        self.assertEqual(proof.issue,'existing-calibration-retained')

    def test_delayed_raw_input_can_join_but_stale_or_unmatched_probes_cannot(self):
        proof=self.calibration();proof.add(SCOPE,10000,10010)
        self.assertIsNone(proof.choose([],10020))
        self.assertEqual(proof.choose([10040],11300),SCOPE)
        stale=self.calibration();stale.add(SCOPE,10000,12000)
        self.assertIsNone(stale.choose([10000],12200))
        unmatched=self.calibration();unmatched.add(SCOPE,10000,10010)
        self.assertIsNone(unmatched.choose([10500],11800))

    def test_null_or_invalid_bluetooth_identity_has_actionable_error(self):
        validate=getattr(capture,'configured_address',None)
        self.assertIsNotNone(validate)
        for value in [None,0,[],{},'', 'broken']:
            with self.assertRaisesRegex(RuntimeError,'Bluetooth identity'):validate({'bluetoothDeviceId':value})
        self.assertEqual(validate({'bluetoothDeviceId':'BluetoothLE#BluetoothLE00:11:22:33:44:55-aa:bb:cc:dd:ee:ff'}),'aa:bb:cc:dd:ee:ff')

    def test_early_startup_error_is_persisted_even_when_process_has_no_console(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(capture,'DATA',Path(folder)),patch.object(capture.ctypes.windll.shell32,'IsUserAnAdmin',return_value=True),patch('capture_support.CaptureInstance') as singleton,patch.object(capture,'_run_owned',side_effect=RuntimeError('Remote Bluetooth identity unavailable')):
            with self.assertRaises(RuntimeError):capture.run()
            status=Path(folder)/'capture-status.json'
            self.assertTrue(status.exists(),'hidden startup failure has no persisted status')
            result=json.loads(status.read_text())
            self.assertEqual(result['phase'],'error')
            self.assertIn('Bluetooth identity',result['lastError'])
            self.assertEqual(result['directionFilter'],'standby')

    def test_missing_identity_fails_before_any_privileged_startup_action(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(capture,'DATA',Path(folder)),patch('capture_support.enable_debug_privilege') as privilege:
            (Path(folder)/'config.json').write_text('{"bluetoothDeviceId":null}')
            with self.assertRaisesRegex(RuntimeError,'Bluetooth identity'):capture._run_owned()
            privilege.assert_not_called()

    def test_singleton_access_error_is_visible_but_duplicate_keeps_live_status(self):
        import capture_support
        duplicate=getattr(capture_support,'CaptureAlreadyRunningError',None)
        self.assertIsNotNone(duplicate)
        with tempfile.TemporaryDirectory() as folder,patch.object(capture,'DATA',Path(folder)):
            status=Path(folder)/'capture-status.json'
            with patch.object(capture_support.CaptureInstance,'__enter__',side_effect=OSError('mutex unavailable')):
                with self.assertRaises(OSError):capture.run()
            self.assertIn('mutex unavailable',json.loads(status.read_text())['lastError'])
            status.write_text('{"phase":"ready"}')
            with patch.object(capture_support.CaptureInstance,'__enter__',side_effect=duplicate('already running')):
                with self.assertRaises(duplicate):capture.run()
            self.assertEqual(json.loads(status.read_text()),{'phase':'ready'})

    def test_startup_denied_by_unready_bridge_has_actionable_error(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(capture,'DATA',Path(folder)),patch('capture_support.enable_debug_privilege') as privilege,patch.object(capture,'bridge_request',return_value={'allowed':False,'generation':7}),patch('rc003_bridge.rawinput.RawInputListener'),patch.object(capture.BridgeGuard,'alive',return_value=False):
            (Path(folder)/'config.json').write_text('{"bluetoothDeviceId":"test-aa:bb:cc:dd:ee:ff"}')
            with self.assertRaisesRegex(RuntimeError,'bridge is not ready'):capture._run_owned()
            privilege.assert_not_called()

    def test_ambiguous_socket_probes_cannot_send_bind_command(self):
        identity={'pid':42,'instance':'selected','lifetime':'fresh'}
        stop=threading.Event();now=[10.1];states=[]
        with tempfile.TemporaryDirectory() as folder,patch.object(capture,'DATA',Path(folder)),patch.object(capture,'same_target',side_effect=lambda _:not stop.is_set()),patch.object(capture.time,'time',side_effect=lambda:now[0]),patch.object(capture,'capture_status',side_effect=lambda phase,**details:states.append(details)):
            with socket.socket() as server:
                server.bind(('127.0.0.1',0));server.listen(1);server.settimeout(.05)
                worker=threading.Thread(target=capture.serve,args=(server,identity,'test-token',[10000]));worker.start()
                try:
                    with socket.create_connection(server.getsockname()) as client:
                        client.settimeout(.7)
                        messages=[{'kind':'hello','pid':42,'token':'test-token','protocol':3,'build':'remote-filter-v4'},
                                  {'kind':'voice-probe','objectName':SCOPE,'at':10000},
                                  {'kind':'voice-probe','objectName':OTHER,'at':10050}]
                        client.sendall((''.join(json.dumps(event)+'\n' for event in messages)).encode())
                        time.sleep(.05);now[0]=11.3
                        with self.assertRaises(socket.timeout):client.recv(8192)
                        self.assertTrue(any(state.get('calibrationIssue')=='ambiguous-voice-proof' for state in states))
                finally:stop.set();worker.join(2)


if __name__=='__main__':unittest.main()
