from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
from pathlib import Path
import json,time,threading,argparse,shutil
parser=argparse.ArgumentParser(description='Isolated UI fixtures; no hardware or upstream API forwarding')
parser.add_argument('--root',type=Path,required=True)
parser.add_argument('--listen',default='127.0.0.1')
parser.add_argument('--port',type=int,default=8798)
args=parser.parse_args()
ROOT=args.root
if not ROOT.is_absolute() or ROOT.parent!=Path('/var/tmp/sdrharness-dev') or ROOT.resolve()!=ROOT:
 parser.error('root must be a canonical direct child of /var/tmp/sdrharness-dev')
PUBLIC=ROOT/'preview'
PUBLIC.mkdir(parents=True,exist_ok=True)
source=Path(__file__).resolve().parent.parent/'public'
for filename in ('index.html','app.js','styles.css'):shutil.copy2(source/filename,PUBLIC/filename)
shutil.copy2(Path(__file__).parent/'preview-controls.js',PUBLIC/'preview-controls.js')
stamp=1788780000000
def event(kind,text,i=0):return dict(kind=kind,text=text,timestamp_ms=stamp+i*1000)
def session(id,title,status='connected'):
 return dict(id=id,title=title,status=status,created_at_ms=stamp,last_used_at_ms=stamp,generation=3,initial_survey_status='complete',compaction_count=0,events=[event('system','控制器状态：空闲，可以接收新任务；运行模式：逐步人工批准。'),event('operator','请查看 2.4 GHz 频段的接收情况。',1),event('qwen','已完成频段扫描。功率曲线中有 2 个候选，请查看历史结果中的频率和信噪比。当前识别能力不可用，不能判断调制类别。',2),event('sweep','扫描完成 · 41 个频点 · 2 个候选 · 射频状态已恢复',3)],observation={'recognizer_available':False},decision_basis='预览固定数据：接收计划已通过边界校验；硬件执行仍由 Controller 批准。')
points=[[2400000000+i*1000000,round(-72+(i%5)*.8+(27 if 9<=i<=12 else 35 if 27<=i<=29 else 0),1)] for i in range(41)]
plot=dict(schema_version=1,sweep_id='预览 · 2.4 GHz 频段扫描',kind='planned',elapsed_ms=12400,gain_db=20,noise_floor_dbfs=-71,points=points,candidates=[dict(id='C01',center_hz=2410000000,bandwidth_hz=4000000,peak_dbfs=-42,snr_db=29,point_count=4),dict(id='C02',center_hz=2428000000,bandwidth_hz=3000000,peak_dbfs=-34,snr_db=37,point_count=3)])
summary=dict(id=9001,session_id='preview-a',sweep_id=plot['sweep_id'],kind='planned',created_at_ms=stamp,point_count=41,candidate_count=2,iq_bytes=0)
provider=dict(configured=True,api='openai-completions',provider='preview-provider',model='preview-model',base_url='https://example.invalid/v1',context_window=32768,compression_threshold_percent=90,initial_survey=dict(mode='disabled',start_hz=70000000,stop_hz=6000000000,step_hz=8000000,dwell_ms=5,gain_db=20),result_storage=dict(save_iq=False))
state=dict(active_session_id='preview-a',sessions=[session('preview-a','2.4 GHz 接收检查'),session('preview-b','上一次接收记录','stored')])
state['sessions'][0]['sweep_plot']=plot
scenario='complete'
results=[dict(summary=summary,sweep_plot=plot)]
writes=[]
class Handler(BaseHTTPRequestHandler):
 def log_message(self,*args):pass
 def reply(self,value,status=200,kind='application/json'):
  body=json.dumps(value,ensure_ascii=False).encode() if kind=='application/json' else value
  self.send_response(status);self.send_header('Content-Type',kind);self.send_header('Cache-Control','no-store')
  self.send_header('Content-Length',str(len(body)))
  self.send_header('Content-Security-Policy',"default-src 'self'; connect-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; form-action 'self'; base-uri 'none'")
  self.end_headers();self.wfile.write(body)
 def do_GET(self):
  global scenario
  path=self.path.split('?')[0]
  if path=='/api/events':
   if scenario=='disconnected':return self.reply(dict(error='预览断连'),503)
   self.send_response(200);self.send_header('Content-Type','text/event-stream');self.send_header('Cache-Control','no-store');self.end_headers()
   try:
    for i in range(60):
     if scenario=='disconnected':break
     self.wfile.write(b'data: {}\n\n');self.wfile.flush();time.sleep(2)
   except (BrokenPipeError,ConnectionResetError):pass
   return
  if path=='/api/state':
   if scenario=='disconnected':return self.reply(dict(error='预览：连接已中断'),503)
   if scenario=='loading':time.sleep(3)
   return self.reply(state)
  if path=='/api/health':return self.reply(dict(ready=True,recognizer_available=False))
  if path=='/api/provider':return self.reply(provider)
  if path=='/api/results':return self.reply([r['summary'] for r in results])
  if path.startswith('/api/results/'):
   if scenario=='error':return self.reply(dict(error='预览：结果暂时无法读取，请重试'),500)
   item=next((r for r in results if str(r['summary']['id'])==path.rsplit('/',1)[1]),None)
   if scenario=='late':time.sleep(2 if path.endswith('9001') else .1)
   return self.reply(item if item else dict(error='未找到记录'),200 if item else 404)
  if path in ('/api/corpus','/api/recognition-results'):return self.reply([])
  if path=='/preview/audit':return self.reply(writes)
  if path in ('/','/index.html','/app.js','/styles.css','/preview-controls.js'):
   name='index.html' if path=='/' else path[1:]
   file=PUBLIC/name
   if not file.exists():return self.reply(dict(error='not found'),404)
   data=file.read_bytes()
   if name=='index.html':data=data.replace(b'</body>',b'<script src="/preview-controls.js"></script></body>')
   return self.reply(data,kind='text/html; charset=utf-8' if name.endswith('html') else 'text/css' if name.endswith('css') else 'text/javascript')
  return self.reply(dict(error='Preview route blocked'),404)
 def do_POST(self):
  global scenario,state,results
  data=json.loads(self.rfile.read(int(self.headers.get('Content-Length','0'))) or '{}')
  path=self.path
  writes.append(dict(path=path,method='POST',body={k:v for k,v in data.items() if k!='api_key'}))
  if path=='/preview/scenario':
   scenario=data['scenario']
   state=dict(active_session_id='preview-a',sessions=[session('preview-a','2.4 GHz 接收检查'),session('preview-b','上一次接收记录','stored')])
   state['sessions'][0]['sweep_plot']=plot
   results=[dict(summary=summary.copy(),sweep_plot=plot)]
   active=state['sessions'][0]
   if scenario=='streaming':
    active['events'].append(event('qwen','正在整理',4))
    def stream():
     target=active
     for text in ['正在整理已接收的频点。','正在整理已接收的频点。功率与噪声曲线已保存。','正在整理已接收的频点。功率与噪声曲线已保存。识别能力不可用。']:
      time.sleep(1.5)
      if scenario!='streaming':return
      target['events'][-1]['text']=text
    threading.Thread(target=stream,daemon=True).start()
   if scenario=='empty':state=dict(active_session_id=None,sessions=[]);results=[]
   if scenario=='approval':active['events'].append(event('plan','待人工批准：2.400–2.440 GHz，41 点，单路 RX，20 dB，最多 671744 字节。输入 /approve 执行或 /reject 拒绝。',4))
   if scenario=='running':active['initial_survey_status']='running';active.pop('sweep_plot');active['events'].append(event('sweep','扫频进行中：18 / 41 点，2.417 GHz',4))
   if scenario=='error':active['events'].append(event('error','接收请求失败，已停止执行。请展开诊断查看原因。',4))
   if scenario=='late':
    other=dict(summary={**summary,'id':9002,'sweep_id':'预览 · 第二条记录'},sweep_plot={**plot,'sweep_id':'预览 · 第二条记录'})
    results.append(other)
   return self.reply(dict(ok=True))
  if path=='/api/sessions':
   id='preview-'+str(len(writes));state['sessions']=[session(id,'预览新会话'),*state['sessions'][:1]]
   for s in state['sessions']:s['status']='connected' if s['id']==id else 'stored';s['initial_survey_status']='skipped'
   state['active_session_id']=id;return self.reply(state)
  if path.endswith('/activate'):
   id=path.split('/')[3];state['active_session_id']=id
   for s in state['sessions']:s['status']='connected' if s['id']==id else 'stored'
   return self.reply(dict(ok=True))
  if path.endswith('/command'):
   id=path.split('/')[3]
   if id!=state['active_session_id']:return self.reply(dict(error='inactive session'),409)
   active=next(s for s in state['sessions'] if s['id']==id)
   command=data['command'];active['events'].append(event('operator','Operator> '+command,5))
   active['events'].append(event('system','会话已停止；旧计划已失效。' if command=='/stop' else '预览：操作已收到，仅更新固定数据。',6))
   if command=='/stop':active['initial_survey_status']='failed'
   return self.reply(dict(ok=True))
  if path=='/api/provider/models':return self.reply(dict(models=[dict(id='preview-model',context_window=32768),dict(id='preview-large',context_window=65536)]))
  return self.reply(dict(error='Preview write blocked'),403)
 def do_PUT(self):
  if self.path!='/api/provider':return self.reply(dict(error='blocked'),403)
  data=json.loads(self.rfile.read(int(self.headers.get('Content-Length','0'))))
  data.pop('api_key',None);provider.update(data);provider['configured']=True
  writes.append(dict(method='PUT',path=self.path,body=data))
  return self.reply(provider)
 def do_DELETE(self):
  global results
  if not self.path.startswith('/api/results/'):return self.reply(dict(error='Preview delete blocked'),403)
  id=self.path.rsplit('/',1)[1];results=[r for r in results if str(r['summary']['id'])!=id]
  writes.append(dict(method='DELETE',path=self.path))
  return self.reply(dict(ok=True))
ThreadingHTTPServer((args.listen,args.port),Handler).serve_forever()
