/* Device-scoped RC003 HID tap. All 13 keys require a calibrated object,
   authenticated live bridge lease and a neutral frame before interception. */
'use strict';
const cfg=__CONFIG__;
let channel=null,connecting=false,chain=Promise.resolve();
let directionFilter=null;
let lastCommandAt=null;
let filterRequest=null;
const completionFaults=new Map();
const directionDiagnostic={gate:'not-enabled',scopeHits:0,selectorAccepted:0,neutralSeen:0,clearsVerified:0,completionAccepted:0,lastRet:null,lastIosbStatus:null};
const names=new Map();
const bound=new Map();
const boundNames=new Set();
const nt=Process.getModuleByName('ntdll.dll');
const queryName=new NativeFunction(nt.getExportByName('NtQueryObject'),'int',['pointer','uint','pointer','uint','pointer']);
function requestKey(request){return JSON.stringify([request.objectName,request.generation]);}
function currentFault(){return filterRequest?(completionFaults.get(requestKey(filterRequest))||null):null;}
function failCompletion(request,reason,ret,iosbStatus){
 const fault={objectName:request.objectName,generation:request.generation,reason,ret,iosbStatus};
 completionFaults.set(requestKey(request),fault);
 if(directionFilter&&requestKey(directionFilter)===requestKey(request))directionFilter=null;
 directionDiagnostic.gate=reason;
 emit({kind:'filter-fault',...fault});
}
function isRemote(handle){
 const key=handle.toString();if(names.has(key)){const known=names.get(key);return known.match||boundNames.has(known.objectName);}
 const buf=Memory.alloc(65536),needed=Memory.alloc(4);let match=false,objectName='';
 if(queryName(handle,1,buf,65536,needed)===0){
  const length=buf.readU16(),ptr=buf.add(8).readPointer();
  if(length>0&&length<65520&&!ptr.isNull()){
   const name=ptr.readUtf16String(length/2).toLowerCase();objectName=name;
   // HOGP object names may identify the HID interface by VID/PID rather than
   // including the Bluetooth address. The launcher requires one RC003 instance.
   match=name.includes(cfg.address)||name.includes(cfg.address.replace(/:/g,''))||/vid[&_](?:0*)?(?:01)?2717.*pid[&_](?:0*)?32b8/i.test(name);
  }
 }
 names.set(key,{match,objectName});emit({kind:'source',verified:match,objectName});return match||boundNames.has(objectName);
}
function emit(value){
 if(!channel)return;
 const text=JSON.stringify(value)+'\n';const bytes=new Uint8Array(text.length);
 for(let i=0;i<text.length;i++)bytes[i]=text.charCodeAt(i);
 const current=channel;chain=chain.then(()=>current.output.writeAll(bytes.buffer)).catch(()=>{dropChannel(current);});
}
function dropChannel(current){
 if(channel!==current)return;
 channel=null;directionFilter=null;lastCommandAt=null;bound.clear();boundNames.clear();
}
function receiveWatchdog(){
 if(!channel||lastCommandAt===null)return;
 const age=Date.now()-lastCommandAt;if(age>=0&&age<3000)return;
 const current=channel;dropChannel(current);
 // Frida sockets may neither EOF nor reject writes after the peer dies.
 // Never wait for close to finish before allowing a fresh connection.
 try{Promise.resolve(current.close()).catch(()=>{});}catch(_){}
}
function activeFilter(){
 if(!directionFilter)return null;
 const age=Date.now()-directionFilter.renewedAt;
 if(!channel||age<0||age>directionFilter.ttlMs||!boundNames.has(directionFilter.objectName)){
  directionFilter=null;directionDiagnostic.gate='lease-expired';return null;
 }
 return directionFilter;
}
function applyCommand(cmd){
 if(cmd.token!==cfg.token)return;
 lastCommandAt=Date.now();
 if(cmd.kind==='keepalive')return;
 if(cmd.kind==='bind'&&typeof cmd.objectName==='string'&&/^\\device\\umdfctrldev-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(cmd.objectName)&&Array.from(names.values()).some(v=>v.objectName===cmd.objectName)){
  boundNames.add(cmd.objectName);emit({kind:'bound',objectName:cmd.objectName});
 }
 if(cmd.kind!=='direction-filter')return;
 if(cmd.enabled===false){directionFilter=null;if(!currentFault())directionDiagnostic.gate='disabled';return;}
 if(cmd.enabled!==true||!boundNames.has(cmd.objectName)||!Number.isSafeInteger(cmd.generation)||cmd.generation<=0||!Number.isInteger(cmd.ttlMs)||cmd.ttlMs<=0||cmd.ttlMs>1500)return;
 filterRequest={objectName:cmd.objectName,generation:cmd.generation};
 if(currentFault()){directionFilter=null;directionDiagnostic.gate=currentFault().reason;return;}
 const previous=activeFilter();
 directionFilter={objectName:cmd.objectName,generation:cmd.generation,ttlMs:cmd.ttlMs,renewedAt:Date.now(),
  waitingNeutral:!previous||previous.objectName!==cmd.objectName||previous.generation!==cmd.generation||previous.waitingNeutral};
 if(directionFilter.waitingNeutral)directionDiagnostic.gate='waiting-neutral';
}
async function connect(){
 if(channel||connecting)return;
 connecting=true;
 try{channel=await Socket.connect({host:'127.0.0.1',port:cfg.port});lastCommandAt=Date.now();chain=Promise.resolve();emit({token:cfg.token,pid:Process.id,kind:'hello',protocol:3,build:'remote-filter-v4'});readCommands(channel);}catch(_){}finally{connecting=false;}
}
async function readCommands(current){
 let text='';
 try{while(channel===current){
  const buffer=await current.input.read(4096);if(channel!==current)return;
  const bytes=new Uint8Array(buffer);if(!bytes.length)break;
  for(const b of bytes)text+=String.fromCharCode(b);
  if(text.length>16384)throw Error('oversize command');
  let end;while((end=text.indexOf('\n'))!==-1){
   const cmd=JSON.parse(text.slice(0,end));text=text.slice(end+1);
   applyCommand(cmd);
  }
 }}catch(_){}finally{dropChannel(current);try{await current.close();}catch(_){}}
}
function fingerprint(pointer,length){
 if(pointer.isNull()||length<=0||length>65536)return '';
 const bytes=new Uint8Array(pointer.readByteArray(Math.min(length,96)));
 return length+':'+Array.from(bytes,b=>('0'+b.toString(16)).slice(-2)).join('');
}
const remoteUsages=new Set([0x66,0x52,0x51,0x50,0x4f,0x28,0xf1,0x4a,0x65,0x3e,0x80,0x81,0x35]);
function isRemoteUsage(usage){return remoteUsages.has(usage);}
function isKeyboardReport(bytes){return bytes[0]===1&&bytes[1]===0&&bytes[2]===0;}
function sameReport(a,b){return a.length===b.length&&a.every((value,i)=>value===b[i]);}
function reportUsages(bytes){
 const usages=[];
 for(let i=3;i<9;i+=2){const u=bytes[i]|bytes[i+1]<<8;if(isRemoteUsage(u))usages.push(u);}
 return usages;
}
function writeUsages(pointer,bytes){pointer.add(3).writeByteArray(bytes.slice(3).buffer);}
Interceptor.attach(Process.getModuleByName('ntdll.dll').getExportByName('NtDeviceIoControlFile'),{
 onEnter(args){
  this.ok=false;this.filtered=null;this.patch=null;this.directionAttempt=null;this.diagnosticScope=false;this.selector=false;
  try{
   this.ok=channel!==null&&args[5].toUInt32()===0x80018483&&args[9].toUInt32()===9;
   if(!this.ok)return;
   this.buf=args[8];this.status=args[4];this.file=args[0];this.fp=fingerprint(args[6],args[7].toUInt32());
   if(args[7].toUInt32()===8&&!args[6].isNull()){
    const selector=new Uint8Array(args[6].readByteArray(8));this.selector=selector[4]===2&&selector[5]===1;
   }
   const filter=activeFilter();
   if(!filter)return;
   isRemote(this.file);
   const known=names.get(this.file.toString());
   if(!known||known.objectName!==filter.objectName||!boundNames.has(known.objectName))return;
   this.diagnosticScope=true;directionDiagnostic.scopeHits++;
   if(this.buf.isNull()||args[7].toUInt32()!==8||args[6].isNull()){directionDiagnostic.gate='invalid-buffer';return;}
   const input=new Uint8Array(args[6].readByteArray(8));
   if(input[4]!==2||input[5]!==1){directionDiagnostic.gate='selector-mismatch';return;}
   directionDiagnostic.selectorAccepted++;
   const original=new Uint8Array(this.buf.readByteArray(9));
   if(!isKeyboardReport(original)){directionDiagnostic.gate='report-format';return;}
   const usages=reportUsages(original),directions=usages.length>0;
   if(filter.waitingNeutral){if(directions){directionDiagnostic.gate='waiting-neutral';return;}filter.waitingNeutral=false;directionDiagnostic.neutralSeen++;}
   this.directionAttempt={objectName:filter.objectName,generation:filter.generation};
   if(directions){
    const patched=original.slice();
    for(let i=3;i<9;i+=2){if(isRemoteUsage(original[i]|original[i+1]<<8)){patched[i]=0;patched[i+1]=0;}}
    try{
     writeUsages(this.buf,patched);
     if(!sameReport(new Uint8Array(this.buf.readByteArray(9)),patched))throw Error('direction write verification failed');
    }catch(_){
     // A short/failed write may have cleared only some slots. Roll back only
     // our own byte changes; never overwrite unrelated concurrent changes.
     try{const current=new Uint8Array(this.buf.readByteArray(9));if(current.every((v,i)=>v===original[i]||v===patched[i]))writeUsages(this.buf,original);}catch(_){}
     directionFilter=null;this.directionAttempt=null;directionDiagnostic.gate='write-failed';return;
    }
    this.original=original;this.patch=patched;directionDiagnostic.clearsVerified++;
   }
   this.filtered={kind:'keys',usages,directionFiltered:true,allKeysFiltered:true,generation:filter.generation,objectName:filter.objectName};
  }catch(_){}
 },
 onLeave(ret){
  // All native-buffer work is confined to this invocation. Even if the call
  // pends, restore our temporary bytes now and never chase asynchronous I/O.
  let restoreIssue=null;
  if(this.patch){
   try{
    if(!sameReport(new Uint8Array(this.buf.readByteArray(9)),this.patch))restoreIssue='native-buffer-changed';
    else{
     writeUsages(this.buf,this.original);
     if(!sameReport(new Uint8Array(this.buf.readByteArray(9)),this.original))restoreIssue='native-restore-failed';
    }
   }catch(_){restoreIssue='native-restore-failed';}
  }
  if(this.diagnosticScope){
   const status=ret.toUInt32();let iosbStatus=null;
   try{if(!this.status.isNull())iosbStatus=this.status.readU32();}catch(_){}
   directionDiagnostic.lastRet=status;directionDiagnostic.lastIosbStatus=iosbStatus;
   if(this.directionAttempt&&(restoreIssue||status!==0||iosbStatus!==0)){
    const reason=restoreIssue||(status===0x103?'native-pending':status!==0?'native-failed':iosbStatus===null?'iosb-unreadable':'iosb-not-success');
    failCompletion(this.directionAttempt,reason,status,iosbStatus);return;
   }
  }
  if(!this.ok||ret.toUInt32()!==0)return;try{
  if(this.buf.isNull()||this.status.isNull()||this.status.readU32()!==0)return;
  if(this.filtered){directionDiagnostic.completionAccepted++;directionDiagnostic.gate='filtered';emit(this.filtered);return;}
  const a=new Uint8Array(this.buf.readByteArray(9));if(a[0]!==1||a[1]!==0||a[2]!==0)return;
  // Outside a successfully completed lease we only request calibration. A
  // matching VID/PID or address is never authority to filter or dispatch.
  const key=this.file.toString();isRemote(this.file);
  const objectName=names.get(key).objectName;
  if(this.selector&&filterRequest&&boundNames.has(objectName)&&objectName===filterRequest.objectName&&reportUsages(a).length===0)
   emit({kind:'neutral',objectName,generation:filterRequest.generation});
  for(let i=3;i<9;i+=2){if((a[i]|a[i+1]<<8)===0x3e)emit({kind:'voice-probe',objectName:names.get(key).objectName,at:Date.now()});}
 }catch(_){} }
});
Interceptor.attach(nt.getExportByName('NtClose'),{onEnter(args){const key=args[0].toString();names.delete(key);bound.delete(key);}});
setInterval(()=>{receiveWatchdog();if(!channel)connect();else{const filter=activeFilter();emit({kind:'heartbeat',directionFilterArmed:!!filter&&!filter.waitingNeutral,directionFilterGeneration:filter?filter.generation:null,directionFilterFault:currentFault(),directionFilterDiagnostic:{...directionDiagnostic}});}},1000);connect();
