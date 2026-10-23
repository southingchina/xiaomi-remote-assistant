"""Frozen role router; no hardware work occurs until an explicit Start."""
import os
import runpy
import sys
from pathlib import Path

def main():
    args=sys.argv[1:]
    if '--data-dir' in args:
        pos=args.index('--data-dir')
        os.environ['RC003_DATA_DIR']=str(Path(args[pos+1]).resolve())
        del args[pos:pos+2]
    if args[:1]==['--module']:
        module=args[1]
        if module not in {'rc003_bridge','rc003_bridge.transport_worker','rc003_bridge.mouse_worker','enhanced_capture'}:
            raise ValueError('Unsupported application role')
        sys.argv=[module,*args[2:]]
        runpy.run_module(module,run_name='__main__')
        return
    if args[:1]==['--self-test']:
        import json
        from self_check import run
        result=run()
        output=json.dumps(result,ensure_ascii=False,indent=2)
        if len(args)>1:Path(args[1]).write_text(output,encoding='utf8')
        print(output)
        return
    if args[:1]==['--stop']:
        from PySide6.QtWidgets import QApplication
        from desktop import send_existing
        app=QApplication.instance() or QApplication([sys.argv[0]])
        send_existing('quit')
        from desktop_backend import DesktopBackend
        DesktopBackend().stop()
        return
    from desktop import main as desktop_main
    desktop_main(args)

if __name__=='__main__':main()
