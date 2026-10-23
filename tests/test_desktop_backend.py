import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

class DesktopBackendTests(unittest.TestCase):
    def backend_type(self):
        self.assertIsNotNone(importlib.util.find_spec('desktop_backend'), 'desktop backend must exist')
        from desktop_backend import DesktopBackend
        return DesktopBackend

    def test_stopped_save_writes_only_own_profile_file(self):
        cls=self.backend_type()
        with tempfile.TemporaryDirectory() as folder:
            backend=cls(Path(folder), control=lambda command, **kw: {'running':False})
            state=backend.load_state()
            state['profiles'][0]['bindings']['6']['action']='Delete'
            result=backend.save_state(state)
            self.assertTrue(result['ok'])
            self.assertEqual(backend.load_state()['profiles'][0]['bindings']['6']['action'],'Delete')

    def test_live_save_failure_does_not_claim_persisted(self):
        cls=self.backend_type()
        def control(command, **kw):
            return {'pid':123} if command=='status' else {'error':'device busy'}
        with tempfile.TemporaryDirectory() as folder:
            backend=cls(Path(folder), control=control)
            before=backend.load_state()
            result=backend.save_state(before)
            self.assertFalse(result['ok'])
            self.assertIn('device busy',result['error'])

    def test_frontend_status_has_no_control_token(self):
        cls=self.backend_type()
        with tempfile.TemporaryDirectory() as folder:
            backend=cls(Path(folder), control=lambda command, **kw:{'pid':1,'phase':'ready','token':'secret','batteryLevel':90})
            state=backend.status()
            self.assertNotIn('token',state)
            self.assertEqual(state['batteryLevel'],90)

    def test_frontend_keeps_paused_and_service_failure(self):
        cls=self.backend_type()
        with tempfile.TemporaryDirectory() as folder:
            backend=cls(Path(folder),control=lambda command,**kw:{'pid':1,'phase':'ready','dispatchEnabled':False,'paused':True,'actionService':'paused','nativeError':'input failed'})
            status=backend.status()
            self.assertTrue(status.get('paused'))
            self.assertEqual(status.get('actionService'),'paused')
            self.assertEqual(status.get('nativeError'),'input failed')

    def test_status_does_not_treat_stale_file_as_connected(self):
        cls=self.backend_type()
        with tempfile.TemporaryDirectory() as folder:
            Path(folder,'status.json').write_text(json.dumps({'phase':'ready','batteryLevel':90}))
            backend=cls(Path(folder),control=lambda command, **kw:{'running':False})
            self.assertEqual(backend.status()['phase'],'stopped')
            self.assertIsNone(backend.status()['batteryLevel'])

    def test_voice_finalization_progress_reaches_ui(self):
        cls=self.backend_type()
        with tempfile.TemporaryDirectory() as folder:
            backend=cls(Path(folder),control=lambda command,**kw:{'pid':1,'phase':'ready',
                'voiceFinishing':True,'voiceReleasePending':True,'audioPendingSeconds':0.405})
            value=backend.status()
            self.assertTrue(value.get('voiceFinishing'))
            self.assertTrue(value.get('voiceReleasePending'))
            self.assertEqual(value.get('audioPendingSeconds'),0.405)

    def test_stopped_cleanup_warning_survives_endpoint_removal(self):
        cls=self.backend_type()
        with tempfile.TemporaryDirectory() as folder:
            Path(folder,'status.json').write_text(json.dumps({'phase':'stopped','pid':999,'batteryLevel':90,
                'cleanupPending':True,'cleanupIssue':'release failed','token':'secret'}))
            backend=cls(Path(folder),control=lambda command,**kw:{'running':False})
            value=backend.status()
            self.assertEqual(value['phase'],'stopped')
            self.assertIsNone(value['batteryLevel'])
            self.assertTrue(value.get('cleanupPending'))
            self.assertEqual(value.get('cleanupIssue'),'release failed')
            self.assertNotIn('token',value)
            self.assertNotIn('pid',value)

if __name__=='__main__': unittest.main()
