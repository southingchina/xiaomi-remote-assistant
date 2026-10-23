import struct
import unittest

from rc003_bridge import qwen


def state(value=0, session='10:1', time=1):
    return {'state': value, 'session': session, 'time': time}


class QwenTests(unittest.TestCase):
    def test_packet_roundtrip_and_reject_malformed_response(self):
        packet = qwen.encode_packet(50, 'ok=1\nhandled=1\n', 123)
        self.assertEqual(qwen.decode_packet(packet), {'command':50, 'id':123, 'fields':{'ok':'1','handled':'1'}})
        for bad in (packet[:-1], b'FAIL'+packet[4:], packet+b'extra'):
            with self.assertRaises(ValueError): qwen.decode_packet(bad)

    def test_surface_parser_handles_start_handoff_commit_and_terminal(self):
        begin = 'voice_shortcut_txn component=utility stage=begin session=7 pid=10 monotonic_ms=100'
        accepted = 'component=voice_runtime event=runtime_handoff_complete reason=accepted status=0 pid=10 monotonic_ms=200'
        unrelated = 'voice_shortcut_txn component=utility stage=finished session=6 pid=10 monotonic_ms=250'
        self.assertEqual(qwen.parse_surface_state('\n'.join((begin, accepted, unrelated))), state(2,'10:7',200))
        self.assertEqual(qwen.parse_surface_state(begin)['state'], 1)
        self.assertEqual(qwen.parse_surface_state(begin+'\nvoice_shortcut_txn component=utility stage=abort session=7 pid=10 monotonic_ms=300')['state'],0)
        self.assertEqual(qwen.parse_surface_state('event=surface_state state=3 overlay_session=9 epoch_ms=444'), state(3,'9',444))

    def test_hold_never_adopts_unrelated_recording(self):
        calls=[]
        voice=qwen.QwenState(read_state=lambda:state(2), send_toggle=lambda:calls.append(1), timeout=0)
        with self.assertRaisesRegex(RuntimeError,'already recording'): voice.start()
        voice.stop_owned()
        self.assertEqual(calls,[])
        self.assertIsNone(voice.owned)

    def test_owned_hold_start_stop_and_duplicate_edges(self):
        current=state();calls=[]
        def toggle():
            calls.append(1)
            current.update(state(2 if len(calls)==1 else 0,'10:2',len(calls)+1))
        voice=qwen.QwenState(read_state=lambda:dict(current),send_toggle=toggle,timeout=0)
        voice.start();voice.start();voice.stop_owned();voice.stop_owned()
        self.assertEqual(calls,[1,1]);self.assertIsNone(voice.owned)

    def test_stop_timeout_is_not_retried_as_a_toggle(self):
        current=state();calls=[]
        def toggle():
            calls.append(1)
            if len(calls)==1:current.update(state(2,'10:2',2))
        voice=qwen.QwenState(read_state=lambda:dict(current),send_toggle=toggle,timeout=0)
        voice.start()
        for _ in range(2):
            with self.assertRaises(TimeoutError):voice.stop_owned()
        self.assertEqual(calls,[1,1])
        current.update(state(0,'10:2',3));voice.stop_owned()
        self.assertIsNone(voice.owned)

    def test_timeout_after_accepted_start_retains_cleanup_ownership(self):
        current=state();calls=[]
        def toggle():
            calls.append(1)
            current.update(state(2 if len(calls)==1 else 0,'10:2',len(calls)+1))
            if len(calls)==1:raise TimeoutError('response lost')
        voice=qwen.QwenState(read_state=lambda:dict(current),send_toggle=toggle,timeout=0)
        with self.assertRaises(TimeoutError):voice.start()
        self.assertEqual(voice.owned,'10:2')
        voice.stop_owned();self.assertEqual(calls,[1,1])

    def test_starting_and_processing_states_are_not_toggled(self):
        for value in (1,3):
            calls=[]
            voice=qwen.QwenState(read_state=lambda:state(value),send_toggle=lambda:calls.append(1),timeout=0)
            with self.assertRaises(RuntimeError):voice.start()
            self.assertEqual(calls,[])

    def test_changed_session_is_not_stopped(self):
        voice=qwen.QwenState(read_state=lambda:state(2,'20:2',3),send_toggle=lambda:self.fail('unowned session toggled'),timeout=0)
        voice.owned='10:2';voice.stop_owned();self.assertIsNone(voice.owned)

    def test_generic_toggle_can_explicitly_stop_current_recording(self):
        current=state(2);calls=[]
        def toggle():calls.append(1);current.update(state())
        voice=qwen.QwenState(read_state=lambda:dict(current),send_toggle=toggle,timeout=0)
        voice.toggle();self.assertEqual(calls,[1]);self.assertIsNone(voice.owned)

    def test_definite_unsent_failure_cannot_adopt_later_unrelated_recording(self):
        current=state();calls=[]
        def unavailable():calls.append(1);raise FileNotFoundError('pipe absent')
        voice=qwen.QwenState(read_state=lambda:dict(current),send_toggle=unavailable,timeout=0)
        with self.assertRaises(FileNotFoundError):voice.start()
        self.assertIsNone(voice.pending_start)
        current.update(state(2,'99:77',500));voice.stop_owned()
        self.assertEqual(calls,[1]);self.assertIsNone(voice.owned)

    def test_ambiguous_start_cannot_adopt_an_uncorrelated_later_recording(self):
        current=state();calls=[]
        def lost():calls.append(1);raise TimeoutError('response lost')
        voice=qwen.QwenState(read_state=lambda:dict(current),send_toggle=lost,timeout=0)
        with self.assertRaises(TimeoutError):voice.start()
        current.update(state(2,'99:77',500))
        with self.assertRaises(RuntimeError):voice.stop_owned()
        self.assertEqual(calls,[1]);self.assertIsNone(voice.owned)

    def test_observed_begin_after_issued_start_can_be_cleaned_up_when_it_commits(self):
        current=state();calls=[]
        def toggle():
            calls.append(1)
            current.update(state(1 if len(calls)==1 else 0,'10:2',len(calls)+1))
        voice=qwen.QwenState(read_state=lambda:dict(current),send_toggle=toggle,timeout=0)
        with self.assertRaises(TimeoutError):voice.start()
        current.update(state(2,'10:2',3));voice.stop_owned()
        self.assertEqual(calls,[1,1]);self.assertIsNone(voice.owned)

    def test_definite_unsent_stop_can_retry_owned_session(self):
        for error in (FileNotFoundError('pipe temporarily absent'),qwen.QwenIpcError('not sent',sent=False)):
            with self.subTest(error=type(error).__name__):
                current=state();calls=[]
                def toggle():
                    calls.append(1)
                    if len(calls)==1:current.update(state(2,'10:2',2))
                    elif len(calls)==2:raise error
                    else:current.update(state(0,'10:2',3))
                voice=qwen.QwenState(read_state=lambda:dict(current),send_toggle=toggle,timeout=0)
                voice.start()
                with self.assertRaises(type(error)):voice.stop_owned()
                self.assertEqual(voice.owned,'10:2');self.assertFalse(voice.stop_pending)
                voice.stop_owned()
                self.assertEqual(calls,[1,1,1]);self.assertIsNone(voice.owned)


if __name__ == '__main__':unittest.main()
