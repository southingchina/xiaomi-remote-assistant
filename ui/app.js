'use strict';

(async () => {
  const STORAGE_KEY = 'rc003-remote-interactive-preview-v1';
  const $ = id => document.getElementById(id);
  const clone = value => JSON.parse(JSON.stringify(value));
  const icons = {
    power:'<path d="M12 2v9m-5-7a9 9 0 1 0 10 0"/>', up:'<path d="m5 15 7-7 7 7"/>', down:'<path d="m5 9 7 7 7-7"/>', left:'<path d="m15 5-7 7 7 7"/>', right:'<path d="m9 5 7 7-7 7"/>', enter:'<path d="M20 5v10H4m5-5-5 5 5 5"/>', back:'<path d="M9 5h12v14H9l-7-7 7-7Zm4 4 6 6m0-6-6 6"/>', home:'<path d="m3 11 9-8 9 8M5 9v12h14V9m-10 12v-8h6v8"/>', menu:'<path d="M4 6h16M4 12h16M4 18h16"/>', voice:'<rect x="8" y="2" width="8" height="13" rx="4"/><path d="M5 10v2a7 7 0 0 0 14 0v-2m-7 9v3m-4 0h8"/>', plus:'<path d="M4 12h16M12 4v16"/>', minus:'<path d="M4 12h16"/>', esc:'<path d="M20 4H6v16h14M6 12h12m-4-4 4 4-4 4"/>'
  };
  const svgIcon = key => `<svg viewBox="0 0 24 24" aria-hidden="true">${icons[key]}</svg>`;
  const KEYS = [
    {id:0,name:'电源键',icon:'power',rect:[19,22,34,34],side:'left',row:0},
    {id:1,name:'方向上',icon:'up',rect:[45,69,56,28],side:'left',row:1},
    {id:2,name:'方向下',icon:'down',rect:[45,161,56,28],side:'right',row:3},
    {id:3,name:'方向左',icon:'left',rect:[13,99,28,60],side:'left',row:2},
    {id:4,name:'方向右',icon:'right',rect:[105,99,28,60],side:'right',row:1},
    {id:5,name:'确认键',icon:'enter',rect:[41,97,64,64],side:'right',row:2},
    {id:6,name:'返回 / 删除',icon:'back',rect:[19,195,48,48],side:'left',row:3},
    {id:7,name:'主页键',icon:'home',rect:[19,250,48,48],side:'left',row:4},
    {id:8,name:'菜单键',icon:'menu',rect:[19,305,48,48],side:'left',row:5},
    {id:9,name:'语音键',icon:'voice',rect:[93,22,34,34],side:'right',row:0},
    {id:10,name:'＋键',icon:'plus',rect:[79,195,48,48],side:'right',row:4},
    {id:11,name:'－键',icon:'minus',rect:[79,250,48,48],side:'right',row:5},
    {id:12,name:'TV 键',icon:'esc',rect:[79,305,48,48],side:'right',row:6}
  ];
  const ACTIONS = {
    keyboard:[['Backspace','退格（Backspace）'],['Delete','删除（Delete）'],['Enter','回车（Enter）'],['Esc','退出 / 取消（Esc）'],['custom','自定义快捷键']],
    mouse:[['move-up','鼠标上移'],['move-down','鼠标下移'],['move-left','鼠标左移'],['move-right','鼠标右移'],['left-click','鼠标左键'],['right-click','鼠标右键'],['middle-click','鼠标中键'],['double-click','鼠标双击'],['wheel-up','滚轮向上'],['wheel-down','滚轮向下']],
    app:[['codex-focus','聚焦 Codex 输入框'],['program','打开程序'],['url','打开网址']],
    voice:[['remote-mic','千问语音 · 遥控器麦克风'],['qwen-generic','通用千问语音']],
    disabled:[['none','不执行动作']]
  };
  const MODE_LABELS = {tap:'点按',hold:'按住保持',repeat:'连续重复'};
  const common = {delay:500,interval:70,speed:6,shortcut:'',target:''};
  const binding = (type,action,mode='tap',extra={}) => ({...common,type,action,mode,...extra});
  const defaults = {
    0:binding('app','codex-focus'),1:binding('mouse','move-up','repeat'),2:binding('mouse','move-down','repeat'),3:binding('mouse','move-left','repeat'),4:binding('mouse','move-right','repeat'),
    5:binding('keyboard','Enter'),6:binding('keyboard','Backspace','repeat',{interval:33}),7:binding('mouse','left-click','hold'),8:binding('mouse','right-click','hold'),
    9:binding('voice','remote-mic','hold'),10:binding('mouse','wheel-up','repeat',{delay:300,interval:70}),11:binding('mouse','wheel-down','repeat',{delay:300,interval:70}),12:binding('keyboard','Esc')
  };
  const originalState = {version:1,current:'daily',profiles:[{id:'daily',name:'日常控制',bindings:clone(defaults)}]};
  let state = clone(originalState), selected = 6, draft, drafts = new Map(), toastTimer;
  const profile = () => state.profiles.find(p => p.id === state.current);
  const draftKey = id => `${state.current}:${id}`;
  function allowedModes(b) {
    if (b.type === 'keyboard') return ['tap','hold','repeat'];
    if (b.type === 'mouse') {
      if (b.action.startsWith('move-')) return ['repeat'];
      if (b.action.startsWith('wheel-')) return ['tap','repeat'];
      if (b.action === 'double-click') return ['tap'];
      return ['tap','hold'];
    }
    if (b.type === 'voice' && b.action === 'remote-mic') return ['hold'];
    return ['tap'];
  }
  function validateBinding(b,id) {
    if (!b || !ACTIONS[b.type]?.some(([value]) => value === b.action)) throw new Error('方案包含不支持的动作。');
    if (b.type === 'voice' && b.action === 'remote-mic' && id !== 9) throw new Error('内置麦克风目前只支持实体语音键。');
    if (!allowedModes(b).includes(b.mode)) throw new Error('该动作不支持所选触发方式。');
    if (b.type === 'keyboard' && b.action === 'custom' && (!b.shortcut || b.shortcut.trim().length > 60)) throw new Error('请填写有效快捷键，例如 Ctrl + Shift + V。');
    if (b.type === 'app' && b.action === 'program' && (!b.target || b.target.trim().length > 500)) throw new Error('请填写程序路径。');
    if (b.type === 'app' && b.action === 'url') {
      let url;try {url = new URL(b.target);}catch {throw new Error('请填写完整网址，例如 https://example.com。');}
      if (!['http:','https:'].includes(url.protocol)) throw new Error('网址须以 http:// 或 https:// 开头。');
    }
    if (b.mode === 'repeat' && (!Number.isInteger(b.delay) || b.delay < 0 || b.delay > 2000 || !Number.isInteger(b.interval) || b.interval < 20 || b.interval > 1000)) throw new Error('起始延迟须为 0–2000 ms，重复间隔须为 20–1000 ms。');
    if (!Number.isFinite(b.speed) || b.speed < 1 || b.speed > 10) throw new Error('速度应为 1–10。');
    return {...common,type:b.type,action:b.action,mode:b.mode,delay:b.delay,interval:b.interval,speed:b.speed,shortcut:String(b.shortcut||'').slice(0,60),target:String(b.target||'').slice(0,500)};
  }
  function validateProfile(p) {
    if (!p || typeof p.name !== 'string' || !p.name.trim() || p.name.length > 40) throw new Error('方案名称应为 1–40 个字符。');
    const result = {id:String(p.id||''),name:p.name.trim(),bindings:{}};
    for (const key of KEYS) result.bindings[key.id] = validateBinding(p.bindings?.[key.id],key.id);
    return result;
  }
  await window.rc003Ready;
  const native=window.rc003Native;
  try { state=await native.call('load'); }
  catch(error){document.body.textContent='配置加载失败：'+error.message;return;}
  let saving=false;
  async function persist() {
    try {const result=await native.call('save',clone(state));state=result.state;return true;}
    catch(error){state=await native.call('load');drawProfiles();selectKey(selected);throw error;}
  }
  const editable=fn=>event=>{if(saving){event.preventDefault();return;}return fn(event);};
  const guarded=fn=>async event=>{
    event.preventDefault();
    if(saving)return;
    saving=true;
    const controls=Array.from(document.querySelectorAll('.workspace button,.workspace input,.workspace select,.workspace textarea'),control=>[control,control.disabled]);
    for(const [control] of controls)control.disabled=true;
    document.querySelector('.workspace').setAttribute('aria-busy','true');
    try{await fn(event);}catch(error){toast('未保存：'+error.message);}
    finally{
      saving=false;
      for(const [control,disabled] of controls)control.disabled=disabled;
      document.querySelector('.workspace').removeAttribute('aria-busy');
    }
  };
  function toast(message) {$('toast').textContent=message;$('toast').classList.add('show');clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('toast').classList.remove('show'),4000);}
  function nameFor(b) {
    if (b.type==='keyboard') return ({Backspace:'退格',Delete:'删除',Enter:'回车',Esc:'退出 / 取消',custom:b.shortcut||'自定义快捷键'})[b.action];
    if (b.type==='app') return ({'codex-focus':'Codex 输入框',program:'打开程序',url:'打开网址'})[b.action];
    if (b.type==='voice') return b.action==='remote-mic'?'千问语音':'通用千问语音';
    return ACTIONS[b.type].find(([v])=>v===b.action)?.[1]||'未配置';
  }
  function subtitle(key,b) {return `${key.name}${b.mode==='repeat'?' · 长按连续':b.mode==='hold'?' · 按住':''}`;}
  function drawProfiles() {
    $('profile-select').replaceChildren(...state.profiles.map(p=>new Option(p.name,p.id,false,p.id===state.current)));
  }
  function drawMap() {
    $('key-cards').replaceChildren();$('key-hotspots').replaceChildren();
    const paths=[];
    for (const key of KEYS) {
      const b=profile().bindings[key.id], left=key.side==='left', x=left?35:705, y=(left?108:64)+key.row*(left?80:81), height=64;
      const card=document.createElement('button');card.type='button';card.className=`key-card${key.id===selected?' is-active':''}`;card.dataset.key=key.id;card.style.cssText=`left:${x/10}%;top:${y/7}%;height:${height/7}%`;
      card.setAttribute('aria-pressed',String(key.id===selected));card.setAttribute('aria-label',`${key.name}：${nameFor(b)}，点击编辑`);
      const icon=document.createElement('span');icon.className='card-icon';icon.innerHTML=svgIcon(key.icon);
      const text=document.createElement('span');text.className='card-text';
      const title=document.createElement('span');title.className='card-title';title.textContent=nameFor(b);title.title=nameFor(b);
      const sub=document.createElement('span');sub.className='card-subtitle';sub.textContent=subtitle(key,b);
      text.append(title,sub);const arrow=document.createElement('span');arrow.className='card-arrow';arrow.textContent='›';card.append(icon,text,arrow);
      if(drafts.has(draftKey(key.id))){const dot=document.createElement('i');dot.className='pending-dot';dot.title='尚未保存';card.append(dot);}
      card.addEventListener('click',editable(()=>selectKey(key.id)));$('key-cards').append(card);
      const [rx,ry,rw,rh]=key.rect, hx=427+rx,hy=60+ry;
      const hotspot=document.createElement('button');hotspot.type='button';hotspot.className=`remote-hotspot${key.id>=1&&key.id<=4?' direction':''}${key.id===selected?' is-active':''}`;
      hotspot.style.cssText=`left:${hx/10}%;top:${hy/7}%;width:${rw/10}%;height:${rh/7}%`;hotspot.setAttribute('aria-label',`选择${key.name}`);hotspot.title=key.name;hotspot.addEventListener('click',editable(()=>selectKey(key.id)));$('key-hotspots').append(hotspot);
      let ax=left?hx:hx+rw,ay=hy+rh/2;
      if (key.id===1||key.id===2) ax=hx+rw/2;
      let prefix='';if(key.id===5){ax=hx+rw*.8;ay=hy+rh*.8;prefix=`L${hx+rw+2},${hy+rh+4} `;}
      const edge=left?295:705, exit=left?424:576, mid=(edge+exit)/2,ey=key.id===5?hy+rh+4:ay,ty=y+32;
      paths.push(`<path class="${key.id===selected?'is-active':''}" d="M${ax},${ay} ${prefix}L${exit},${ey} C${mid},${ey} ${mid},${ty} ${edge},${ty}"/><circle class="${key.id===selected?'is-active':''}" cx="${ax}" cy="${ay}" r="2"/>`);
    }
    document.querySelector('.connection-lines').innerHTML=paths.join('');
  }
  function selectKey(id) {selected=id;draft=clone(drafts.get(draftKey(id))||profile().bindings[id]);drawMap();drawEditor();}
  function setDirty() {
    const dirty=JSON.stringify(draft)!==JSON.stringify(profile().bindings[selected]);
    if(dirty)drafts.set(draftKey(selected),clone(draft));else drafts.delete(draftKey(selected));
    $('dirty-indicator').textContent=dirty?'有未保存更改':'已保存';$('dirty-indicator').classList.toggle('dirty',dirty);
    $('form-error').textContent='';drawMap();
  }
  function formLabel(text,forId) {const label=document.createElement('label');label.className='form-label';label.htmlFor=forId;label.textContent=text;return label;}
  function drawEditor() {
    const key=KEYS.find(k=>k.id===selected);$('selected-icon').innerHTML=svgIcon(key.icon);$('selected-name').textContent=key.name;$('selected-subtitle').textContent=`实体按键 ${String(selected+1).padStart(2,'0')} / 13 · 自定义动作`;$('action-type').value=draft.type;
    const fields=$('action-fields');fields.replaceChildren();
    if (draft.type!=='disabled') {
      fields.append(formLabel(draft.type==='keyboard'?'按键 / 快捷键':'具体动作','specific-action'));
      const select=document.createElement('select');select.id='specific-action';
      for(const [value,label] of ACTIONS[draft.type]){const option=new Option(label,value,false,value===draft.action);if(value==='remote-mic'&&selected!==9){option.disabled=true;option.textContent='遥控器麦克风（仅实体语音键）';}select.append(option);}
      select.addEventListener('change',editable(()=>{draft.action=select.value;const modes=allowedModes(draft);if(!modes.includes(draft.mode))draft.mode=modes[0];setDirty();drawEditor();}));fields.append(select);
      if(draft.type==='keyboard'&&draft.action==='custom') {
        fields.append(formLabel('快捷键','shortcut'));const input=document.createElement('input');input.id='shortcut';input.type='text';input.maxLength=60;input.placeholder='例如 Ctrl + Shift + V';input.value=draft.shortcut;input.autocomplete='off';input.addEventListener('input',editable(()=>{draft.shortcut=input.value;setDirty();}));fields.append(input);
        const hint=document.createElement('p');hint.className='field-hint';hint.textContent='直接输入组合名称，例如 Ctrl + Shift + V。';fields.append(hint);
      }
      if(draft.type==='app'&&draft.action!=='codex-focus'){
        fields.append(formLabel(draft.action==='program'?'程序完整路径':'网址','target'));const input=document.createElement('input');input.id='target';input.type='text';input.maxLength=500;input.value=draft.target;input.placeholder=draft.action==='program'?'C:\\Apps\\app.exe':'https://example.com';input.autocomplete='off';input.addEventListener('input',editable(()=>{draft.target=input.value;setDirty();}));fields.append(input);
      }
    }
    $('mode-section').hidden=draft.type==='disabled';const modes=allowedModes(draft);$('mode-control').replaceChildren();
    for(const [mode,label] of Object.entries(MODE_LABELS)){const btn=document.createElement('button');btn.type='button';btn.className=`mode-btn${draft.mode===mode?' active':''}`;btn.textContent=label;btn.disabled=!modes.includes(mode);btn.setAttribute('aria-pressed',String(draft.mode===mode));btn.addEventListener('click',editable(()=>{draft.mode=mode;setDirty();drawEditor();}));$('mode-control').append(btn);}
    $('mode-hint').textContent=({tap:'按一下执行一次，持续按住不重复。',hold:'按下开始保持，松开立即释放。',repeat:'按住后连续执行，松开立即停止。'})[draft.mode];
    const parameters=$('parameter-fields');parameters.replaceChildren();
    if(draft.mode==='repeat'&&!(draft.type==='mouse'&&draft.action.startsWith('move-'))){
      const grid=document.createElement('div');grid.className='parameter-grid';
      for(const [prop,label,min,max] of [['delay','起始延迟',0,2000],['interval','重复间隔',20,1000]]){const cell=document.createElement('div');cell.append(formLabel(label,prop));const wrap=document.createElement('div');wrap.className='input-unit';const input=document.createElement('input');input.id=prop;input.type='number';input.min=min;input.max=max;input.step=1;input.value=draft[prop];input.addEventListener('input',editable(()=>{draft[prop]=input.value===''?null:Number(input.value);setDirty();}));const unit=document.createElement('span');unit.textContent='ms';wrap.append(input,unit);cell.append(wrap);grid.append(cell);}parameters.append(grid);
    }
    if(draft.type==='mouse'&&draft.action.startsWith('move-')){parameters.append(formLabel('鼠标移动速度','speed'));const row=document.createElement('div');row.className='range-row';const input=document.createElement('input');input.id='speed';input.type='range';input.min=1;input.max=10;input.value=draft.speed;const out=document.createElement('output');out.textContent=`${draft.speed} / 10`;input.addEventListener('input',editable(()=>{draft.speed=Number(input.value);out.textContent=`${draft.speed} / 10`;setDirty();}));row.append(input,out);parameters.append(row);}
    let title='按你的习惯控制',hint='保存后，左侧卡片会显示当前绑定的动作。';
    if(draft.type==='keyboard'&&draft.action==='Backspace'){title=draft.mode==='repeat'?'长按连续退格':'退格（Backspace）';hint=draft.mode==='repeat'?'按住超过起始延迟后，按设定间隔退格。松开即停止。':draft.mode==='hold'?'按住保持 Backspace，松开释放。':'每按一次退格一个字符。';}
    else if(draft.type==='voice'){title=draft.action==='remote-mic'?'遥控器内置麦克风':'沿用千问当前输入设备';hint=draft.action==='remote-mic'?'仅实体语音键支持。按住开始语音，松开结束本次录音。':'作为备用语音按钮；不自动切换到遥控器麦克风。';}
    else if(draft.type==='disabled'){title='此键不执行自定义动作';hint='按键服务就绪后，此键的原始动作也会被抑制。';}
    else if(draft.type==='mouse'&&draft.action.startsWith('move-')){title='直接移动鼠标指针';hint='不使用小键盘模拟，不向输入框发送方向键。按住移动，松开停止。';}
    else if(draft.type==='mouse'&&draft.action.startsWith('wheel-')&&draft.mode==='repeat'){title='长按连续滚动';hint='按住持续滚动，松开即停。单次最多连续 30 秒，松开后重新按下可继续。';}
    $('behavior-note').replaceChildren();const strong=document.createElement('strong');strong.textContent=title;$('behavior-note').append(strong,document.createTextNode(hint));setDirty();
  }
  $('action-type').addEventListener('change',editable(()=>{const type=$('action-type').value;const action=type==='voice'&&selected!==9?'qwen-generic':ACTIONS[type][0][0];draft=binding(type,action);draft.mode=allowedModes(draft)[0];setDirty();drawEditor();}));
  $('key-form').addEventListener('submit',guarded(async event=>{
    event.preventDefault();const clean=validateBinding(draft,selected);profile().bindings[selected]=clean;
    await persist();drafts.delete(draftKey(selected));selectKey(selected);toast('已保存按键配置。');
  }));
  $('reset-key').addEventListener('click',guarded(async()=>{
    profile().bindings[selected]=clone(defaults[selected]);await persist();drafts.delete(draftKey(selected));selectKey(selected);toast('此键已恢复默认。');
  }));
  $('profile-select').addEventListener('change',guarded(async()=>{
    state.current=$('profile-select').value;await persist();selectKey(selected);toast('已切换配置方案。');
  }));
  $('copy-profile').addEventListener('click',guarded(async()=>{
    if(state.profiles.length>=30)throw new Error('最多保存30套方案。');
    let i=1,name;do{name=profile().name.slice(0,25)+' · 副本 '+i++;}while(state.profiles.some(p=>p.name===name));
    const next=clone(profile());next.id='copy-'+Date.now();next.name=name;state.profiles.push(next);state.current=next.id;
    await persist();drawProfiles();selectKey(selected);toast('已复制并切换到新方案。');
  }));
  $('reset-profile').addEventListener('click',guarded(async()=>{
    profile().bindings=clone(defaults);await persist();drafts.clear();selectKey(selected);toast('当前方案已恢复默认。');
  }));
  $('export-profile').addEventListener('click',guarded(async()=>{
    const result=await native.call('export',state);if(result.ok)toast('配置已导出。');
  }));
  $('import-profile').addEventListener('click',guarded(async()=>{
    const result=await native.call('import');if(result.cancelled)return;
    state=result.state;drafts.clear();drawProfiles();selectKey(selected);toast('配置已导入。');
  }));
  drawProfiles();selectKey(selected);
  const phases={stopped:'未启动',starting:'启动中',waiting_for_pairing:'等待配对',connecting:'连接中',negotiating:'连接中',ready:'已连接',retrying:'恢复连接中',device_selection_required:'有多台遥控器，需选择',paused:'已暂停'};
  async function refreshStatus(){
    try {
      const status=await native.call('status');
      const ready=status.phase==='ready';
      document.querySelector('.connected').textContent=(ready?'● ':'○ ')+(phases[status.phase]||status.phase||'未启动');
      document.querySelector('.connected').style.color=ready?'#73d8bd':'#aaa';
      $('battery-value').textContent=Number.isFinite(status.batteryLevel)?status.batteryLevel:'—';
      document.querySelector('.battery-level').setAttribute('width',Number.isFinite(status.batteryLevel)?17*status.batteryLevel/100:0);
      let message=status.cleanupIssue||status.nativeError||status.captureIssue||status.lastError||status.voiceIssue||status.audioIssue;
      if(!status.cleanupIssue&&(status.paused||status.dispatchEnabled===false))message='按键控制已暂停';
      else if(!status.cleanupIssue&&(status.configurationPending||status.awaitingNeutral))message='请松开全部按键，等待新配置生效';
      if(!message&&(status.voiceFinishing||status.voiceReleasePending))message='正在结束语音，其他按键可继续使用';
      if(!message)message=ready?(status.enhancedCaptureReady?'按键服务已就绪':'蓝牙已连接，请启用增强按键'):(phases[status.phase]||'等待设备');
      $('runtime-status').textContent=message;$('runtime-status').title=message;
      document.querySelectorAll('.remote-hotspot').forEach(e=>e.classList.remove('physical-down'));
      if(status.lastKeyDown&&Number.isInteger(status.lastKeyPosition))document.querySelectorAll('.remote-hotspot')[status.lastKeyPosition]?.classList.add('physical-down');
    }catch(error){$('runtime-status').textContent=error.message;}
  }
  await refreshStatus();setInterval(refreshStatus,1500);
})();
