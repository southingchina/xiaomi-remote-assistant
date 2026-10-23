'use strict';
window.rc003Ready = new Promise((resolve,reject)=>{
  new QWebChannel(qt.webChannelTransport, channel=>{
    const bridge=channel.objects.bridge;
    window.rc003Native={call:(method,payload={})=>new Promise((ok,fail)=>bridge.request(method,JSON.stringify(payload),raw=>{
      let result;try{result=JSON.parse(raw);}catch{fail(new Error('程序返回了无效结果。'));return;}
      if(result.error)fail(new Error(result.error));else ok(result);
    }))};resolve();
  });
});
