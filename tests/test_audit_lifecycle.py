"""Equivalent lifecycle guarantees from the existing-service control audit."""
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from rc003_bridge import __main__ as cli
from rc003_bridge import runtime as module


class AuditLifecycleTests(unittest.TestCase):
    def runtime(self):
        return module.BridgeRuntime(config={'dispatchEnabled':True},
            resolver=SimpleNamespace(resolve=lambda _:None),
            dispatcher=SimpleNamespace(send=lambda *_:None),qwen=SimpleNamespace(owned=None))

    def test_ensure_respects_explicit_stop_marker_without_starting_process(self):
        with TemporaryDirectory() as folder:
            Path(folder,'bridge-paused.json').write_text('{"paused":true}')
            with patch.object(module,'DATA',Path(folder)),patch('sys.argv',['bridge','ensure']), \
                 patch.object(cli,'control') as control,patch('subprocess.Popen') as launch,patch('sys.stdout',new_callable=io.StringIO) as output:
                cli.main()
                self.assertTrue(json.loads(output.getvalue())['paused'])
                control.assert_not_called();launch.assert_not_called()

    def test_ensure_existing_paused_service_never_sends_resume(self):
        with TemporaryDirectory() as folder:
            with patch.object(module,'DATA',Path(folder)),patch('sys.argv',['bridge','ensure']), \
                 patch.object(cli,'control',return_value={'pid':123,'paused':True}) as control, \
                 patch('subprocess.Popen') as launch,patch('sys.stdout',new_callable=io.StringIO) as output:
                cli.main()
                self.assertTrue(json.loads(output.getvalue())['paused'])
                self.assertTrue(all(call.args==('status',) for call in control.call_args_list))
                launch.assert_not_called()

    def test_diagnostic_write_failures_do_not_escape_control_runtime(self):
        runtime=self.runtime()
        with TemporaryDirectory() as folder,patch.object(module,'DATA',Path(folder)):
            with patch.object(Path,'open',side_effect=PermissionError('disk denied')):
                runtime.note('test-event')
            self.assertIn('disk denied',runtime.state['eventWriteError'])
            with patch.object(module,'write_json',side_effect=PermissionError('status denied')):
                runtime.publish(phase='ready')
            self.assertEqual(runtime.state['phase'],'ready')
            self.assertIn('status denied',runtime.state['statusWriteError'])

    def test_event_log_rolls_over_instead_of_growing_without_bound(self):
        runtime=self.runtime()
        with TemporaryDirectory() as folder,patch.object(module,'DATA',Path(folder)):
            current=Path(folder,'events.jsonl');current.write_text('x'*(256*1024+1))
            runtime.note('new-event')
            self.assertEqual(json.loads(current.read_text())['event'],'new-event')
            self.assertEqual(Path(folder,'events.previous.jsonl').stat().st_size,256*1024+1)


if __name__=='__main__':unittest.main()
