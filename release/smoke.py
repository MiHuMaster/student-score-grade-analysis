"""Validate the frozen application in isolated local storage, without an account."""
from pathlib import Path
import json,os,socket,sqlite3,sys,tempfile,unittest
from contextlib import closing
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from test_desktop_exit import DesktopExitProcessTests

def main():
    temporary=ROOT/'.release-smoke'
    temporary.mkdir(exist_ok=True)
    os.environ.update(TEMP=str(temporary),TMP=str(temporary),PYTHONDONTWRITEBYTECODE='1')
    tempfile.tempdir=str(temporary)
    blocker=socket.socket()
    blocker.setsockopt(socket.SOL_SOCKET,socket.SO_EXCLUSIVEADDRUSE,1)
    for port in range(5050,5100):
        try:
            blocker.bind(('127.0.0.1',port));blocker.listen();break
        except OSError:continue
    else:raise RuntimeError('No free local port for isolated fallback test')
    results=[]
    class FrozenLifecycle(DesktopExitProcessTests):
        executable=ROOT/'dist/StudentScoreAnalysis/StudentScoreAnalysis.exe'
        def on_running(self,attempt):
            import httpx,subprocess
            states=list(temporary.glob('*/StudentScoreAnalysis/desktop/instance.json'))
            self.assertEqual(len(states),1)
            state=json.loads(states[0].read_text(encoding='utf-8'))
            self.assertGreater(state['port'],port)
            url=f"http://127.0.0.1:{state['port']}"
            with httpx.Client(trust_env=False) as client:
                self.assertEqual(client.get(url+'/api/exams').json(),{'items':[]})
                for name in ['index.html','app.js','styles.css','branding/app-icon.png']:
                    resource='/' if name=='index.html' else '/static/'+name
                    self.assertEqual(client.get(url+resource).content,(ROOT/'app/static'/name).read_bytes())
            with closing(sqlite3.connect(states[0].parents[1]/'student_analysis.db')) as db:
                for table in ('students','exams','exam_results','subject_scores','import_batches','base_students','base_school_classes'):
                    self.assertEqual(db.execute(f'SELECT count(*) FROM {table}').fetchone()[0],0)
            sockets=subprocess.check_output(['netstat','-ano','-p','tcp'],text=True)
            listeners=[line.split()[1] for line in sockets.splitlines() if len(line.split())>=5 and line.split()[-1]==str(state['pid']) and line.split()[-2]=='LISTENING']
            self.assertEqual(listeners,[f"127.0.0.1:{state['port']}"])
            results.append({'attempt':attempt+1,'empty_start':True,'loopback_only':True,'static_resources':True,'occupied_port_fallback':True})
    try:
        result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(FrozenLifecycle))
    finally:blocker.close()
    (ROOT/'release/smoke-result.json').write_text(json.dumps({'passed':result.wasSuccessful(),'launches':results},indent=2),encoding='utf-8')
    if not result.wasSuccessful() or result.skipped:raise SystemExit(1)

if __name__=='__main__':main()
