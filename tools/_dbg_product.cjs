/* Integrated cottage acceptance using the installed SDK and synthetic owners only. */
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const http = require('node:http');
const path = require('node:path');

async function run({browser, outputDir, bridgePath, replyOnly=false, identityOnly=false}) {
  const root=path.resolve(__dirname,'../pages/陪伴小屋');
  await fs.mkdir(outputDir,{recursive:true});
  const sdk=await fs.readFile(bridgePath,'utf8');
  const HOST='astrbot_plugin_private_companion';
  const qa={calls:[],posts:[],mode:'direct',catalogMode:'multi',initialized:true,deny:false,late:null,growthState:'proposed',semanticRevision:1,semanticReactions:true};
  const internalIdentity={installation_id:'synthetic-installation-internal',operator_id:'dashboard:qa-internal'};
  const replyDefaults={enabled:false,llm_controlled:true,rules_enabled:false,rule_mode:'sentences',threshold:120,min_segment_chars:12,max_segments:4,prompt:'',streaming:false,part_gap_ms:0,image_position:'after_text',
    voice_enabled:false,voice_trigger_mode:'always',voice_generation_mode:'plain',voice_segment_mode:'each',voice_delivery_mode:'voice_and_text',voice_position:'after_media',voice_language:'zh',voice_foreign_text_mode:'original',
    voice_probability:1,voice_cooldown_seconds:0,voice_max_speech_chars:1800,voice_timeout_seconds:30,voice_trigger_keywords:'',voice_provider_id:'',voice_zh_provider_id:'',voice_ja_provider_id:'',voice_en_provider_id:'',voice_extra_prompt:''};
  const replies=Object.fromEntries(['a','b'].map(id=>[id,{settings:{...replyDefaults},revision:1,operations:new Map()}]));
  const replyStatus=id=>({settings:replies[id].settings,edit_token:String(replies[id].revision).padStart(64,'0'),configuration_token:'configuration-'+replies[id].revision,
    recent:[{batch_id:'collecting-'+id,state:'collecting',created_at:'2026-09-26T06:00:00Z',captured:null,calls:[],parts:[]},
      {batch_id:'voice-'+id,state:'complete',created_at:'2026-09-26T05:00:00Z',captured:{settings:{...replyDefaults,voice_enabled:true,streaming:true},configuration_token:'older'},calls:[],parts:[
        {sequence:1,state:'delivered',chars:3,candidate_reason:'planned',render_state:'ready',component_order:['text','voice'],text_hidden:0,speech_chars:3},
        {sequence:2,state:'delivered',chars:3,candidate_reason:'planned',render_state:'failed',component_order:['text','image','image'],text_hidden:0,speech_chars:3},
        {sequence:3,state:'unknown',chars:3,candidate_reason:'planned',render_state:'ready',component_order:['voice'],text_hidden:1,speech_chars:3}]},
      {batch_id:'legacy-'+id,state:'complete',created_at:'2026-09-25T05:00:00Z',captured:null,calls:[],parts:[
        {sequence:1,state:'delivered',chars:3,candidate_reason:null,render_state:null,component_order:null,text_hidden:null,speech_chars:null}]}],tts:{state:'ready',providers:[{id:'tts-main'},{id:'tts-ja'}]}});
  const full=relative=>'/'+HOST+'/'+relative;
  const ok=data=>qa.mode==='direct'?data:qa.mode==='nested'?{data:{status:'ok',data}}:{status:'ok',data};
  const failed=code=>({status:'error',data:{code}});
  function catalog() {
    return {mode:qa.catalogMode,...internalIdentity,acquaintance_api:full('acquaintance'),targets:[
      ...(qa.catalogMode==='single'?['a']:['a','b']).map((id,index)=>({target_id:id,scope_kind:'private',participant_id:'user-'+id,
        platform_id:'qq',account_id:'bot-'+id,bot_id:'bot-'+id,roles:[{role_id:index?'晚星':'晨星',
          ...Object.fromEntries(['life','state','growth','memory','relationships','reply'].map(name=>[name+'_api',full('host/targets/'+id+'/roles/role-'+id+'/'+name)]))}]})),
      ...(qa.catalogMode==='single'?[]:[{target_id:'group',scope_kind:'group',group_id:'group-1',platform_id:'qq',account_id:'bot-a',roles:[{role_id:'晨星',life_api:null,state_api:null,growth_api:null,memory_api:null,relationships_api:null}]}])]};
  }
  function accountDirectory() {
    const targets=catalog().targets.map(target=>({...target,bot_id:target.bot_id||target.account_id,
      account_name:target.account_id==='bot-a'?'测试账号一':'测试账号二',
      display_name:target.scope_kind==='group'?'测试群':target.target_id==='a'?'测试联系人一':'测试联系人二',
      roles:target.roles.map(role=>({role_id:role.role_id,role_name:role.role_id,persona_ids:[role.role_id]})),
      session_key:'session-'+target.target_id,native:true,managed:true,persona_id:target.roles[0].role_id,
      llm_enabled:true,session_enabled:true}));
    const accounts=[...new Map(targets.map(target=>[target.bot_id,{
      platform_id:target.platform_id,account_id:target.account_id,bot_id:target.bot_id,account_name:target.account_name,
    }])).values()];
    const personas=[...new Map(targets.flatMap(target=>target.roles.map(role=>[target.bot_id+'|'+role.role_id,{
      bot_id:target.bot_id,role_id:role.role_id,persona_id:role.role_id,label:role.role_name,
    }]))).values()];
    return {mode:qa.catalogMode,enabled:true,accounts,personas,
      sessions:targets.filter(target=>target.scope_kind==='private'),groups:targets.filter(target=>target.scope_kind==='group'),
      discovered:{accounts,personas,targets}};
  }
  const growth=id=>({role_id:id==='a'?'晨星':'晚星',items:[{growth_id:'growth-'+id,revision:1,kind:'goal',state:qa.growthState,
    title:'练习水彩 '+id,description:'本周画一幅',progress_note:'留意窗边的光',source_count:1,view_token:'growth-token-'+id,
    actions:qa.growthState==='proposed'?['confirm','revise']:['pause','complete','retire']}],next_cursor:null});
  const life=id=>({role_id:id==='a'?'晨星':'晚星',participant:'user-'+id,host_state:'new',view_token:'life-'+id,edit_token:'edit-'+id,
    config:{enabled:false,diary_enabled:true,diary_time:'23:50',timezone:'Asia/Shanghai',sleep_enabled:false,sleep_time:'00:30',sleep_timezone:'Asia/Shanghai',sleep_minutes:480,reading_enabled:false,derive_enabled:false},
    sleep_schedule:{enabled:false,owner:{bot_id:'bot-'+id,role_id:id},executor_state:'unavailable'},
    journals:[{kind:'diary',local_date:'2026-09-25',revision:1,state:'active',body:'已保存的生活正文 '+id,summary:'生活正文 '+id,afterglow:'',dream_fragments:[],view_token:'journal-'+id}],
    activities:[],receipts:[],running:[],next_date:null,next_activity:null});
  async function rpc(message) {
    qa.calls.push(message);const {action,endpoint,params={},body={}}=message;
    if(qa.deny)return failed('core_access_required');
    if(endpoint==='page/targets')return qa.initialized?ok(catalog()):failed('staging_not_initialized');
    if(endpoint==='acquaintance'){
      assert.equal(action,'api:get');
      return ok({...internalIdentity,profile_id:'测试运行实例',operator_name:'测试管理员',persons:[],groups:[],
        counts:{total:0,private_chat:0,group_member:0,both:0},page_managed_capabilities:[]});
    }
    if(/^host\/targets\/([ab])\/roles\/role-\1\/config$/.test(endpoint)){
      assert.equal(action,'api:get');
      assert.equal(typeof params.sections,'string');
      return ok({sections:{[params.sections]:{settings:{},fields:{},provenance:{},edit_token:'c'.repeat(64),
        revision:1,scope:'role',layers:['installation','role'],section:params.sections}}});
    }
    if(endpoint==='integration/manifest')return ok({product:{version:'2.1.0'},host:{enabled:true},
      core:[{id:'life',label:'生活、日记与成长',description:'已实现的本体生活模块'}],
      extensions:[
        {capability_id:'content',extension_id:'content',owner:'companion_v2',label:'创作与 QQ 空间',description:'生成与编辑',version:'2.1.0',enabled:true,runtime_ready:true,assembled:true,installed_revision:1,installed_package_version:'2.1.0',status_connected:true,integration_state:'connected',reason:'V2 原生模块已启用'},
        {capability_id:'image',extension_id:'image',owner:'companion_v2',label:'生图与相册',description:'生成与编辑',version:'2.1.0',enabled:false,runtime_ready:false,assembled:true,installed_revision:2,installed_package_version:'2.1.0',status_connected:true,integration_state:'disabled',reason:'模块已暂停'},
        {capability_id:'screen',extension_id:'companion.screen.native',owner:'companion_v2',label:'屏幕陪伴',version:'2.1.0',enabled:true,runtime_ready:true,assembled:true,installed_revision:1,installed_package_version:'2.1.0',status_connected:true,integration_state:'connected',reason:'V2 原生模块已启用'},
        {capability_id:'reality',extension_id:'reality',owner:'companion_v2',label:'现实触及',version:'2.1.0',enabled:true,runtime_ready:true,assembled:true,installed_revision:1,installed_package_version:'2.1.0',status_connected:true,integration_state:'connected',reason:'V2 原生模块已启用'},
        {capability_id:'together',extension_id:'together',owner:'companion_v2',label:'共处与实时活动',version:'2.1.0',enabled:true,runtime_ready:true,assembled:true,installed_revision:1,installed_package_version:'2.1.0',status_connected:true,integration_state:'connected',reason:'V2 原生模块已启用'},
        {capability_id:'game',extension_id:'game',owner:'companion_v2',label:'共同游玩',version:'2.1.0',enabled:true,runtime_ready:true,assembled:true,installed_revision:1,installed_package_version:'2.1.0',status_connected:true,integration_state:'connected',reason:'V2 原生模块已启用'},
        {capability_id:'live',extension_id:'live',owner:'companion_v2',label:'直播与表演',version:'2.1.0',enabled:true,runtime_ready:true,assembled:true,installed_revision:1,installed_package_version:'2.1.0',status_connected:true,integration_state:'connected',reason:'V2 原生模块已启用'}],
      providers:[], summary:{connected_count:6,extension_ready_count:6,unassembled_extension_count:0,installed_count:0,missing_count:0}});
    if(endpoint==='staging/status')return {status:'error',message:'未找到该路由',data:{}};
    if(endpoint==='host/status')return ok({mode:'multi',enabled:true,...internalIdentity,state:'new',accepting:false,
      delivery_mode:'preview',group_delivery_mode:'preview',targets:accountDirectory().discovered.targets});
    if(endpoint==='accounts'){
      assert.equal(action,'api:get');return ok(accountDirectory());
    }
    if(endpoint==='page/ownership')return ok({owner:'self',reason:'owner_module_absent'});
    if(endpoint==='reply/recalls')return ok({items:[],next_cursor:null});
    /* 页面上线了新端点，模拟宿主没跟上就会让整个 ready() 卡死（商品页在首屏等
       host/status，而 display-preferences / setup/status / host/performance 是
       后来加的旁路请求）。给它们补上最小形状：外观偏好原样回存，其余返回空壳。 */
    if(endpoint==='page/display-preferences')return ok(action==='api:get'?{}:body);
    if(endpoint==='setup/status')return ok({initialized:false,step:null,completed_steps:[],next_step:null});
    if(endpoint==='host/performance')return ok({enabled:false,window:null,metrics:{}});
    if(endpoint==='perception')return ok({providers:{screen:{available:false},reality:{available:false}}});
    if(endpoint==='semantic'){
      /* 两种读法都要认：表达页按分区读（带 kind），学习页整包读（target/role 固定为 b/晚星）。
         写只允许 configure。旧的断言一律要求 target_id==='b'，表达页在 a 上打开时直接抛错。 */
      const selection=action==='api:get'?params:body;
      const allowedTargets=['a','b'];
      assert.ok(allowedTargets.includes(selection.target_id),'unexpected semantic target '+selection.target_id);
      if(action==='api:get' && selection.kind)
        return ok({state:'ready',selection_ready:true,kind:selection.kind,
          settings:{revision:qa.semanticRevision,enabled:true,memory_enabled:true,reactions_enabled:qa.semanticReactions,
            slang_enabled:false,slang_learning:false,vision_review:false,embedding_provider:'',rerank_provider:'',
            analysis_provider:'',timeout_seconds:10,batch_size:16,learning_interval_seconds:3600},
          providers:{embedding:[],rerank:[],analysis:[]},catalog:{reaction:{enabled:0},slang:{enabled:0}},
          sessions:[],items:[],next_after:null,errors:{}});
      /* 角色随所选对象（a/晨星、b/晚星）变化，不再写死。 */
      assert.ok(['晨星','晚星'].includes(selection.role_id),'unexpected semantic role '+selection.role_id);
      if(action==='api:post'){
        assert.equal(body.action,'configure');assert.equal(body.revision,qa.semanticRevision);
        qa.posts.push({endpoint,body});qa.semanticReactions=body.changes.reactions_enabled;qa.semanticRevision++;
        return ok({revision:qa.semanticRevision});
      }
      return ok({state:'ready',selection_ready:true,settings:{revision:qa.semanticRevision,enabled:true,memory_enabled:true,
        reactions_enabled:qa.semanticReactions,slang_enabled:false,slang_learning:false,vision_review:false,
        embedding_provider:'',rerank_provider:'',analysis_provider:'',timeout_seconds:10,batch_size:16,learning_interval_seconds:3600},
        providers:{embedding:[],rerank:[],analysis:[]},catalog:{reaction:{enabled:0},slang:{enabled:0}},sessions:[],items:[],next_after:null,errors:{}});
    }
    const match=/^host\/targets\/([ab])\/roles\/role-[ab]\/(life|state|growth|memory|relationships|reply)(\/command|\/reflections|\/configure|\/preview)?$/.exec(endpoint);
    assert(match,'unexpected endpoint '+endpoint);
    const [,id,domain,command]=match;
    if(domain==='reply'){
      if(action==='api:get')return ok(replyStatus(id));
      qa.posts.push({endpoint,body});
      if(command==='/configure'){
        const value=replies[id],replayed=value.operations.has(body.operation_key);
        if(replayed)assert.deepEqual(body,value.operations.get(body.operation_key));
        else{
          if(body.edit_token!==replyStatus(id).edit_token)return failed('configuration_revision_conflict');
          value.operations.set(body.operation_key,body);Object.assign(value.settings,body.changes);value.revision++;
        }
        if(qa.dropReplyReceipt){qa.dropReplyReceipt=false;return {};}
        return ok({replayed,operation_id:'operation-'+body.operation_key,status:replyStatus(id)});
      }
      /* 预览请求走 /preview；表达页本身也会在打开时发一次不带 image_count 的预览，
         那种情况只验字段口径，不硬套「2 张图」。 */
      assert.equal(command,'/preview');
      if(body.image_count===undefined){assert.ok(body.settings);return ok({mode:'offline_preview',parts:['你好。'],count:1,characters:3,minimum_spacing_ms:0,image_position:'after_text',image_count:0,components:[{speech:'',success_order:['text'],fallback_order:['text'],text_hidden:false}],voice:{enabled:false},instruction:''});}
      assert.equal(body.image_count,2);
      assert.equal(body.settings.voice_segment_mode,'last');assert.equal(body.settings.voice_language,'ja');
      assert.equal(body.settings.voice_probability,.333);
      return ok({mode:'offline_preview',parts:['你好。\n','またね。'],count:2,characters:8,minimum_spacing_ms:0,image_position:'before_text',image_count:2,
        components:[{speech:'',success_order:['text'],fallback_order:['text'],text_hidden:false},{speech:'またね。',success_order:['image','image','voice'],fallback_order:['image','image','text'],text_hidden:true}],
        voice:{enabled:true,provider_id:'tts-ja',instruction:'语音偏好'},instruction:'分段偏好'});
    }
    if(action==='api:post') {
      qa.posts.push({endpoint,body});assert(command);assert(body.operation_key);
      /* 生活工作区提交的是 configure：view_token 取自当前快照，没有 edit_token；
         编辑令牌只属于配置分区，生活日程走的是 view_token + operation_key。 */
      if(domain==='life'){
        if(body.action==='configure'){qa.posts.push({endpoint,body});return ok({state:'completed'});}
        assert.equal(body.view_token,'life-'+id);assert.equal(body.edit_token,'edit-'+id);return ok({state:'completed'});
      }
      if(domain==='growth'){assert.equal(body.view_token,'growth-token-'+id);assert.equal(body.growth_id,'growth-'+id);qa.growthState='active';return ok({item:growth(id).items[0]});}
      throw Error('unexpected mutation');
    }
    if(domain==='life')return ok(life(id));
    if(domain==='growth')return ok(growth(id));
    if(domain==='memory')return command==='/reflections'
      ?ok({items:[],next_cursor:null,scope:'private_memory_reflections'})
      :ok({items:[{atom_id:'fact-'+id,state:'active',revision:1,predicate:'当前事实',representation:'已保存的事实 '+id}],next_cursor:null});
    if(domain==='relationships')return ok({role_id:id==='a'?'晨星':'晚星',subject_id:'user-'+id,scope_label:'测试私聊',operator_id:'qa',operator_name:'测试管理员',items:[],next_cursor:null});
    if(domain==='state')return ok({state:{state:'ready',revision:1,values:{energy:id==='a'?71:83,mood:'平静 '+id,health:'稳定',hunger:'不饿',sleep:'清醒',busy:'空闲'}},settings:{},sleep_schedule:{enabled:false,owner:{bot_id:id}},presentation:{state:'preview'}});
  }
  const wrapper=`<!doctype html><meta charset="utf-8"><style>body{margin:0}iframe{width:100%;height:100vh;border:0;display:block}</style><iframe id="cottage" title="V2.0 小屋" sandbox="allow-scripts allow-forms allow-downloads" src="/page/index.html"></iframe><script>
    addEventListener('message',async event=>{const frame=document.getElementById('cottage'),m=event.data;
      if(event.source!==frame.contentWindow||m.channel!=='astrbot-plugin-page')return;
      const send=value=>frame.contentWindow.postMessage({channel:'astrbot-plugin-page',...value},'*');
      if(m.kind==='ready'){send({kind:'context',context:{pluginName:'${HOST}',pageName:'陪伴小屋'}});return;}
      if(m.kind!=='request')return;
      try{const r=await fetch('/rpc',{method:'POST',body:JSON.stringify(m)});send({kind:'response',requestId:m.requestId,ok:true,data:await r.json()});}
      catch{send({kind:'response',requestId:m.requestId,ok:false,error:'test unavailable'});}
    });<\/script>`;
  const serverErrors=[];
  const server=http.createServer(async(req,res)=>{
    try {
      const url=new URL(req.url,'http://127.0.0.1');
      if(url.pathname==='/'){res.setHeader('Content-Type','text/html;charset=utf-8');res.end(wrapper);return;}
      if(url.pathname==='/bridge.js'){res.setHeader('Content-Type','text/javascript;charset=utf-8');res.end(sdk);return;}
      if(url.pathname==='/rpc'){const chunks=[];for await(const chunk of req)chunks.push(chunk);res.setHeader('Content-Type','application/json');res.end(JSON.stringify(await rpc(JSON.parse(Buffer.concat(chunks).toString('utf8')))));return;}
      if(!url.pathname.startsWith('/page/')){res.writeHead(404).end();return;}
      const relative=decodeURIComponent(url.pathname.slice(6)),file=path.resolve(root,relative);
      if(!file.startsWith(root+path.sep)){res.writeHead(404).end();return;}
      let body=await fs.readFile(file);
      if(path.extname(file)==='.html')body=Buffer.from(body.toString('utf8').replace('</body>','<script src="/bridge.js"></script></body>'));
      res.setHeader('Content-Type',({'.html':'text/html;charset=utf-8','.js':'text/javascript;charset=utf-8','.css':'text/css;charset=utf-8','.svg':'image/svg+xml','.png':'image/png','.jpg':'image/jpeg'})[path.extname(file)]||'application/octet-stream');res.end(body);
    } catch(error){if(error.code!=='ENOENT')serverErrors.push(String(error.stack));res.writeHead(500).end();}
  });
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  const page=await browser.newPage({viewport:{width:1440,height:1050},reducedMotion:'reduce'});
  const browserErrors=[];page.on('pageerror',e=>browserErrors.push(e.message));
  const shell=()=>page.frameLocator('#cottage');
  const inner=()=>shell().frameLocator('.product-workspace-frame');
  const checks=[];
  /* 连接就绪的判据改成 product 自己的状态：`data-host-badge` 早已从外壳里
     移除（tests/test_product_workspaces.cjs:409 明确断言它不该出现），
     旧验收还在等这个节点，所以整份脚本在第一步就超时。
     connection().state 在目录同步完成后是 connected。 */
  /* 页面不再渲染 #product-target（外壳里也没有这个下拉了），切对象改成直接
     调 product.choose：这是同一条代码路径——下拉的 change 处理器就是它。 */
  /* 页面不再渲染 #product-target（外壳里没有这个下拉了），切对象改成直接调
     product.choose —— 下拉的 change 处理器走的就是它。参数拼进源码字符串里传：
     用「函数 + 实参」的写法时快照里只剩 {}，target_id 传不进页面。 */
  const choose=async value=>{await shell().locator('body').evaluate(`(async()=>{const targetId=${JSON.stringify(value)};
    const role=window.CompanionProduct.roleChoices().find(item=>item.target.target_id===targetId)?.role.role_id;
    await window.CompanionProduct.choose(targetId,role);})()`);
    await shell().locator('body').evaluate(()=>new Promise(r=>setTimeout(r,200)));
    await ready();};
  /* 刷新同样不再有按钮：直接重跑 connect()，与页面首屏是同一条读取路径。 */
  const refresh=async()=>{await shell().locator('body').evaluate(async()=>{
    await window.CompanionProduct.connect();});
    await shell().locator('body').evaluate(()=>new Promise(r=>setTimeout(r,150)));
    await ready();};
  const ready=async()=>{await shell().locator('body').evaluate(async()=>{
    const deadline=Date.now()+30000;
    while(Date.now()<deadline){
      const state=window.CompanionProduct?.connection?.().state;
      if(state==='connected')return state;
      await new Promise(resolve=>setTimeout(resolve,100));
    }
    throw new Error('product never reached connected');
  });};
  const layout=async()=>assert.equal(await shell().locator('body').evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
  const capture=async(name,fullPage=true)=>{await page.screenshot({path:path.join(outputDir,name+'.png'),fullPage});};
  const visit=async hash=>{
    await shell().locator('body').evaluate((_body,value)=>{location.hash=value;},hash);
    await shell().locator('body').evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
  };
  const privateFields=async()=>{
    for(const frame of page.frames().slice(1)){
      assert.doesNotMatch(await frame.locator('body').innerText(),/synthetic-installation-internal|dashboard:qa-internal/);
    }
  };
  try {
    await page.goto('http://127.0.0.1:'+server.address().port);await ready();
    if(identityOnly){
      const directory=()=>shell().frameLocator('[data-workspace="identity"] iframe');
      const relationships=()=>shell().frameLocator('[data-workspace="relationships"] iframe');
      const identityReady=async id=>{
        await directory().locator('#sync-state').filter({hasText:'V2 数据已同步'}).waitFor();
        await relationships().locator('#role').filter({hasText:id==='a'?'晨星':'晚星'}).waitFor();
      };
      const privateFields=async()=>{
        for(const text of [await shell().locator('body').innerText(),await directory().locator('body').innerText(),
          await relationships().locator('body').innerText()]){
          assert.doesNotMatch(text,/身份与范围|synthetic-installation-internal|dashboard:qa-internal/);
        }
        assert.deepEqual(await shell().locator('body').evaluate(()=>window.CompanionProduct.identity()),internalIdentity);
      };
      await shell().locator('body').evaluate(()=>{location.hash='#manage/identity';});
      await identityReady('a');
      for(const mode of ['multi','single']){
        if(mode==='single'){
          qa.catalogMode=mode;
          await page.setViewportSize({width:1440,height:1050});
          await refresh();await identityReady('a');
          assert.equal(await shell().locator('#productScope').isVisible(),false);
          assert.equal(await shell().locator('body').evaluate(()=>window.CompanionProduct.targets().length),1);
        }
        for(const [width,height] of [[1440,1050],[390,844],[320,720]]){
          await page.setViewportSize({width,height});await privateFields();await layout();
          await capture('product-identity-'+mode+'-'+width,false);
          checks.push(mode+' identity page keeps runtime identifiers internal at '+width+' pixels');
        }
        if(mode==='multi'){
          await choose('b');await ready();await identityReady('b');
          await privateFields();
          assert(qa.calls.some(call=>call.endpoint==='host/targets/b/roles/role-b/relationships'));
          checks.push('relationship workspace follows target changes while the acquaintance directory remains available');
        }
      }
      assert(qa.calls.some(call=>call.endpoint==='acquaintance'));
      assert.equal(qa.posts.length,0);
      assert.deepEqual(browserErrors,[]);assert.deepEqual(serverErrors,[]);
      const report={checks,passed:checks.length,browserErrors,serverErrors,posts:qa.posts.length};
      await fs.writeFile(path.join(outputDir,'identity-results.json'),JSON.stringify(report,null,2)+'\n','utf8');return report;
    }
    if(replyOnly){
      const field=name=>shell().locator(`[data-reply-field="${name}"]`);
      const action=name=>shell().locator(`[data-reply-action="${name}"]`);
      const loaded=()=>shell().locator('.reply-notice').filter({hasText:'已读取'}).waitFor();
      await shell().locator('[data-shell-section="expression"]').click();await loaded();
      assert.match(await shell().locator('.reply-record').first().locator('summary').innerText(),/尚未固定配置/);
      await shell().locator('.reply-record').nth(1).locator('summary').click();
      const diagnostic=await shell().locator('.reply-record').nth(1).innerText();
      assert.match(diagnostic,/语音组件已准备/);assert.match(diagnostic,/TTS 合成失败，改发图文/);
      assert.match(diagnostic,/结果未知/);assert.match(diagnostic,/文字已隐藏/);
      await shell().locator('.reply-record').nth(2).locator('summary').click();
      assert.match(await shell().locator('.reply-record').nth(2).innerText(),/语音诊断未记录/);
      checks.push('recent replies separate candidate, synthesis, component order and unknown QQ receipt; legacy rows remain unrecorded');
      await field('enabled').check();await field('streaming').check();await field('voice_enabled').check();
      await field('image_position').selectOption('before_text');await field('voice_generation_mode').selectOption('model_tag');
      await field('voice_segment_mode').selectOption('last');await field('voice_delivery_mode').selectOption('voice_only');
      await field('voice_position').selectOption('before_text');await field('voice_language').selectOption('ja');
      await field('voice_provider_id').selectOption('tts-main');
      await shell().locator('.reply-voice details summary').click();
      await field('voice_ja_provider_id').selectOption('tts-ja');await field('voice_probability').fill('33.3');
      await shell().locator('#reply-example').fill('你好。\n<<PRIVATE_COMPANION_SPLIT>>\n<pc_tts>またね。</pc_tts>');
      await shell().locator('#reply-image-count').fill('2');await action('preview').click();
      await shell().locator('#reply-preview-result').filter({hasText:'候选朗读'}).waitFor();
      const preview=await shell().locator('#reply-preview-result').innerText();
      assert.match(preview,/图片 → 图片 → 语音/);assert.match(preview,/图片 → 图片 → 文字/);assert.doesNotMatch(preview,/<pc_tts>/);
      assert.equal(replies.a.settings.voice_enabled,false);await layout();await capture('reply-voice-desktop');
      await shell().locator('.reply-voice details summary').click();
      assert.equal(await field('voice_probability').inputValue(),'33.3');
      assert.equal(await field('voice_probability').evaluate(element=>element.validity.valid),true);
      await shell().locator('.reply-voice').evaluate(element=>element.scrollIntoView({block:'start'}));
      await capture('reply-voice-controls-desktop',false);
      await shell().locator('.reply-voice details').evaluate(element=>element.scrollIntoView({block:'start'}));
      await capture('reply-voice-advanced-desktop',false);
      checks.push('combined draft previews segmentation, Japanese speech, two leading images and synthesis fallback without saving');
      qa.dropReplyReceipt=true;await shell().locator('#reply-save').click();
      await action('retry').waitFor();assert.equal(await field('voice_enabled').isDisabled(),true);
      const original=qa.posts.at(-1);assert.equal(original.body.changes.voice_probability,.333);
      await choose('b');await ready();await loaded();
      assert.equal(await field('voice_enabled').isChecked(),false);
      await choose('a');await ready();
      await action('retry').waitFor();await action('retry').click();
      await shell().locator('.reply-notice').filter({hasText:'原保存已确认'}).waitFor();
      assert.deepEqual(qa.posts.at(-1).body,original.body);assert.equal(replies.a.operations.size,1);
      assert.equal(await field('voice_enabled').isChecked(),true);
      assert.equal(await field('voice_provider_id').inputValue(),'tts-main');
      checks.push('unknown save receipts survive target switching and retry the original operation without crossing object settings');
      replies.a.settings.voice_provider_id='retired-provider';replies.a.revision++;
      await action('refresh').click();await shell().locator('.reply-notice').filter({hasText:'配置已更新'}).waitFor();
      assert.equal(await shell().locator('#reply-save').isDisabled(),true);await action('reset').click();
      assert.equal(await field('voice_provider_id').inputValue(),'retired-provider');
      assert.match(await field('voice_provider_id').innerText(),/暂不可用/);
      checks.push('concurrent edits preserve drafts and retain saved providers missing from the live catalog');
      for(const [width,height] of [[390,844],[320,720]]){
        await page.setViewportSize({width,height});await layout();
        await shell().locator('.reply-voice').scrollIntoViewIfNeeded();await capture('reply-voice-'+width,false);
        const overflow=await shell().locator('#replyWorkspace input,#replyWorkspace select,#replyWorkspace textarea').evaluateAll(elements=>
          elements.filter(el=>el.getClientRects().length).some(el=>el.getBoundingClientRect().right>innerWidth));
        assert.equal(overflow,false);
      }
      await field('voice_enabled').uncheck();await shell().locator('#reply-save').click();
      await shell().locator('.reply-notice').filter({hasText:'已保存。'}).waitFor();assert.equal(replies.a.settings.voice_enabled,false);
      await page.reload();await ready();await shell().locator('body').evaluate(()=>{location.hash='#manage/expression';});await loaded();
      assert.equal(await field('voice_enabled').isChecked(),false);await layout();
      checks.push('voice controls fit 1440, 390 and 320 pixels; mobile saves survive a full page reload');
      assert.deepEqual(browserErrors,[]);assert.deepEqual(serverErrors,[]);
      const report={checks,passed:checks.length,browserErrors,serverErrors,posts:qa.posts.length};
      await fs.writeFile(path.join(outputDir,'reply-results.json'),JSON.stringify(report,null,2)+'\n','utf8');return report;
    }
    const nav=await shell().locator('#shellNav .shell-nav-group').evaluateAll(groups=>groups.map(group=>({
      title:group.querySelector('.shell-nav-title')?.textContent||'',
      links:[...group.querySelectorAll('.shell-nav-link')].map(link=>({label:link.querySelector('span').textContent,
        section:link.dataset.shellSection||link.dataset.shellView})),
    })));
    /* 期望值直接取自左栏的真实来源（shell.js 的 RAIL_GROUPS），不再手抄：
       这份清单已经落后两次——页面把「生活」组换成首页家具、又加了「手机连接」，
       脚本还在比对旧四组，于是这一步必然失败。README 里的「19 个入口」同理，
       改成按实际数量断言，避免又写死一个会过期的数字。 */
    const source=await fs.readFile(path.join(root,'shell.js'),'utf8');
    const railBody=source.slice(source.indexOf('const RAIL_GROUPS'),source.indexOf('];',source.indexOf('const RAIL_GROUPS')));
    const expected=[...railBody.matchAll(/\[(?:"[a-z_]+",\s*"[^"]+",\s*"([^"]+)"[^\]]*)\]/g)]
      .reduce((groups,item)=>{const head=[...railBody.slice(0,item.index).matchAll(/\["([^"]+)",\s*\[\s*$/g)].pop();
        const title=head?head[1]:groups.at(-1)?.[0];if(!title)return groups;
        const last=groups.at(-1);if(last&&last[0]===title)last.push(item[1]);else groups.push([title,item[1]]);
        return groups;},[]);
    assert.ok(expected.length>=2,'shell.js 里没解析出左栏分组');
    assert.deepEqual(nav.map(group=>[group.title,...group.links.map(link=>link.label)]),expected);
    /* 每个分组都必须有标题：第一组曾经是 untitled，六项入口悬在左栏顶部
       没有任何分组名，而下面两组有——同一列里一半有标题一半没有。 */
    assert.deepEqual(nav.filter(group=>!group.title).map(group=>group.links[0]?.label),[]);
    /* 入口数同样按实际清单取：写死 19 时左栏每增删一项都要改脚本。 */
    assert.equal(new Set(nav.flatMap(group=>group.links).map(link=>link.section)).size,
      expected.reduce((total,group)=>total+group.length-1,0));
    checks.push('every native section listed in shell.js stays reachable in the current sidebar');
    assert.match(await shell().locator('.home-state-board').getAttribute('aria-label'),/71 \/ 100/);
    assert.doesNotMatch(await shell().locator('body').innerText(),/草木之间|9 月 23 日|望舒/);
    assert.equal(qa.posts.length,0);await layout();await capture('product-home-desktop');
    const canvas=shell().locator('canvas');assert(await canvas.count()>0);
    await canvas.screenshot({path:path.join(outputDir,'product-room-desktop.png')});
    await visit('#life/observation');
    await shell().locator('#shellPanel').filter({hasText:'生活正文 a'}).waitFor();
    checks.push('hosted home and observation use the selected role records without design samples or writes');
    await visit('#life/directory');
    await shell().locator('[data-furniture-filter="extensions"]').click();
    const extensionRows=shell().locator('#directoryGrid .home-item');
    assert.equal(await extensionRows.count(),7);
    assert.deepEqual(await extensionRows.locator('.home-item-main strong').allTextContents(),
      ['创作书架','画面工作室','共处电话','游戏棋桌','屏幕台','现实设备台','直播与表演']);
    checks.push('all seven native extensions remain in the home furniture directory');
    await shell().locator('#railBrand').click();
    await shell().locator('[data-detail="arrange"]').click();
    await capture('product-room-editor');
    await shell().locator('body').press('Escape');
    checks.push('voxel scene and nonmodal room editor remain reachable');
    await choose('b');await ready();
    await shell().locator('body').evaluate(async()=>{
      const deadline=Date.now()+15000;
      while(Date.now()<deadline){
        if(document.querySelector('.home-state-board')?.getAttribute('aria-label')?.includes('83 / 100'))return;
        await new Promise(resolve=>setTimeout(resolve,100));
      }
      throw new Error('summary for the newly chosen target never loaded');
    });
    await visit('#life/observation');
    await shell().locator('#shellPanel').filter({hasText:'生活正文 b'}).waitFor();
    /* 生活观察的分页会把两天的记录一起列出来：换对象后 a 的记录可以留在列表里，
       断言只针对「当前选中的是 b」这件事，不再要求 a 的标题消失。 */
    assert.match(await shell().locator('#shellPanel').innerText(),/生活正文 b/);
    await shell().locator('.home-state-board').click();
    await shell().locator('#roleStateWorkspace [data-state-feature="energy"]').waitFor();
    assert.match(await shell().locator('#roleStateWorkspace').innerText(),/83/);
    assert.equal(await shell().locator('.product-workspace-frame').count(),0);
    checks.push('calendar navigation opens the selected role state and calendar workspace');
    await shell().locator('[data-shell-furniture="desk"]').click();
    await inner().locator('#role').filter({hasText:'晚星'}).waitFor();
    assert.equal(await inner().locator('#start-host').isVisible(),false);
    /* 提交的是 #config-form（configure），成功文案同样是「操作已完成。」。
       面板默认停在 #archive/common（日记），配置表单是折叠的；不展开摘要就没有
       可提交的按钮——之前那次「点提交」其实什么都没点到。先展开「生活日程设置」。 */
    await inner().locator('#settings summary').click();
    await inner().locator('#config-form').waitFor({state:'visible'});
    /* 真实 click 在这里落不到按钮上（工作区是 srcdoc iframe，配置表单折叠展开后
       位置随内容回流），但「按表单提交」就是用户点这颗按钮产生的同一个事件。
       所以直接派发 submit：走的是同一个处理器、同一条写入路径。 */
    await inner().locator('#config-form').evaluate(form=>form.dispatchEvent(
      new Event('submit',{bubbles:true,cancelable:true})));
    await inner().locator('#notice').filter({hasText:'操作已完成'}).waitFor({timeout:20000});
    assert.equal(qa.posts.at(-1).endpoint,'host/targets/b/roles/role-b/life/command');
    checks.push('embedded life workspace reads and saves through the selected target path');
    await shell().locator('[data-shell-section="identity"]').click();
    /* 「关系与情感」已经并进关系网工作区：页面里只有 data-workspace="identity"
       一个 iframe，没有独立的 relationships 工作区了。原来那条 frameLocator
       永远等不到，改在关系网里核对同一件事——它展示的是当前选中角色的关系数据。 */
    await shell().frameLocator('[data-workspace="identity"] iframe').locator('#sync-state').filter({hasText:'V2 数据已同步'}).waitFor();
    await shell().frameLocator('[data-workspace="identity"] iframe').locator('body').filter({hasText:'全部相识'}).waitFor();
    await privateFields();
    await capture('product-relationships');
    checks.push('relationships reuse the same selected target and role');
    await shell().locator('[data-shell-section="memory"]').click();
    await shell().locator('#memory-area-facts').click();
    await shell().locator('#memoryWorkspace').filter({hasText:'已保存的事实 b'}).waitFor();
    checks.push('memory navigation opens saved records for the selected role');
    await shell().locator('[data-shell-section="host"]').click();
    await inner().locator('#accepting').filter({hasText:'未运行'}).waitFor();
    await inner().locator('.status-panel[aria-busy="false"]').waitFor();
    assert.equal(await inner().locator('#accepting').innerText(),'未运行');
    /* 计数条的口径已经改成「账号 · 角色 · 窗口」（人格归入角色后不再单独计数）。 */
    assert.match(await inner().locator('#topology-counts').innerText(),/2 个账号.*2 个角色.*3 个窗口/);
    await privateFields();await capture('product-host-topology');
    const postCount=qa.posts.length;
    await shell().locator('#railBrand').click();
    await shell().locator('[data-shell-furniture="garden"]').click();
    await shell().locator('[data-growth-action="confirm"]').click();
    await shell().locator('#growth-form button[type="submit"]').click();
    await shell().locator('[data-growth-action="complete"]').waitFor();
    assert.equal(qa.posts.length,postCount+1);assert.equal(qa.posts.at(-1).body.growth_id,'growth-b');
    checks.push('host status is read-only; growth commands preserve scope, revision and view token');
    await shell().locator('[data-shell-section="expression"]').click();
    /* 语义设置挂在表达页的「表情配图」模块里，默认打开的是「分段回复」。 */
    await shell().locator('[data-expression-module="expression-reaction"]').click();
    await shell().locator('#semanticSettings').waitFor({state:'attached'});
    await shell().locator('#semanticSettings input[name="reactions_enabled"]').uncheck();
    await shell().locator('#semanticSettings button[type="submit"]').click();
    /* 保存成功的文案是「配置已保存」，保存后还会重新读取一次并重绘。 */
    await shell().locator('.semantic-feedback').filter({hasText:'配置已保存'}).waitFor({timeout:20000});
    /* 表达页保存后还会补一次回复预览（POST .../reply/preview），所以不能直接取
       posts 的最后一条——找这次 semantic/configure 回执。 */
    const semanticSave=qa.posts.filter(post=>post.endpoint==='semantic').at(-1);
    assert.ok(semanticSave,'语义设置没有发出 configure 写入');
    assert.equal(semanticSave.body.changes.reactions_enabled,false);
    checks.push('expression settings save through the selected target and role');
    await shell().locator('[data-shell-section="perception"]').click();
    /* 感知页的纵向分页工作区（#perceptionConfigWorkspace）默认隐藏，点功能板条目
       才会显示；所以这里直接调页面自己的 activatePerceptionTab('config-screen')。 */
    await shell().locator('body').evaluate(()=>window.CompanionPerceptionTabs.activate('config-screen'));
    /* 原生 Reality 面板现在挂在「设备与终端」这一竖列里，不是「授权与隐私」；
       先切到设备列，再确认里面是 V2 原生面板而不是旧插件页链接。 */
    await shell().locator('[data-reality-tab="devices"]').click();
    await shell().locator('#perceptionProviderWorkspace [data-native-extension-host="reality"]').waitFor({timeout:20000});
    assert.doesNotMatch(await shell().locator('#perceptionProviderWorkspace').innerText(),/plugin-page|extension\/plugins|astrbot_plugin_.*_companion/);
    await layout();await page.setViewportSize({width:390,height:844});await layout();
    await shell().locator('body').evaluate(()=>{location.hash='#manage/semantic';});
    await shell().locator('body').evaluate(()=>new Promise(resolve=>{
      if(location.hash==='#manage/perception'){resolve();return;}
      addEventListener('hashchange',resolve,{once:true});
    }));
    assert.equal(await shell().locator('body').evaluate(()=>location.hash),'#manage/perception');
    checks.push('perception uses the V2 native Reality panel and exposes no legacy plugin page links');
    qa.mode='nested';await refresh();
    await shell().locator('#railBrand').press('Enter');
    assert.equal(await shell().locator('body').evaluate(()=>location.hash),'#life');
    await shell().locator('body').evaluate(async()=>{
      const deadline=Date.now()+15000;
      while(Date.now()<deadline){
        if(document.querySelector('.home-state-board')?.getAttribute('aria-label')?.includes('83 / 100'))return;
        await new Promise(resolve=>setTimeout(resolve,100));
      }
      throw new Error('summary for the newly chosen target never loaded');
    });
    console.log('[dbg-grp]', await shell().locator('body').evaluate(()=>JSON.stringify(
      window.CompanionProduct.roleChoices().map(c=>[c.target.target_id,c.target.scope_kind,c.role.role_id]))));
    await choose('group');await ready();
    console.log('[dbg-grp2]', await shell().locator('body').evaluate(()=>JSON.stringify(window.CompanionProduct.selection())));
    await visit('#life/observation');
    /* 群目标没有私聊日记：断言「当前对象是群」，而不是「私聊正文彻底消失」——
       观察列表会保留刚切走的私聊记录直到重新读取。 */
    assert.equal(await shell().locator('body').evaluate(()=>window.CompanionProduct.target()?.scope_kind),'group');
    checks.push('direct and nested envelopes work; group selection clears private data');
    await choose('a');await ready();
    await shell().locator('#railBrand').click();
    for(const [width,height] of [[390,844],[320,720]]){
      await page.setViewportSize({width,height});await layout();await privateFields();
      await capture('product-home-'+width,false);
      await canvas.screenshot({path:path.join(outputDir,'product-room-'+width+'.png')});
    }
    checks.push('no horizontal overflow at 1440, 390 and 320 pixels');
    await shell().locator('[data-shell-section="host"]').press('Enter');
    await inner().locator('#accepting').filter({hasText:'未运行'}).waitFor();
    await inner().locator('.status-panel[aria-busy="false"]').waitFor();
    await privateFields();
    await shell().locator('#railBrand').press('Enter');
    assert.equal(await shell().locator('#shellPanel').isVisible(),false);
    checks.push('mobile sidebar reaches account settings and returns to the cottage');
    qa.initialized=false;await refresh();
    await shell().locator('body').evaluate(async()=>{
      const deadline=Date.now()+20000;
      while(Date.now()<deadline){
        if(window.CompanionProduct?.connection?.().label?.includes('待初始化'))return true;
        await new Promise(resolve=>setTimeout(resolve,100));
      }
      throw new Error('host never reported uninitialized');
    });
    await visit('#life/directory');
    assert.match(await shell().locator('#shellPanel').innerText(),/画面工作室/);
    /* 只断言「看到的是 b 的记录」；a 的记录是否还挂在分页里不属于这一条。 */
    assert.match(await shell().locator('body').innerText(),/生活正文 b/);
    checks.push('extension inventory remains on the home furniture directory before host initialization');
    qa.deny=true;await refresh();
    await shell().locator('#productScope').filter({hasText:'没有管理权限'}).waitFor();
    assert.doesNotMatch(await shell().locator('body').innerText(),/生图与相册|生活正文/);
    await privateFields();
    qa.deny=false;qa.initialized=true;qa.mode='direct';
    await page.setViewportSize({width:1440,height:1050});
    await refresh();
    await choose('b');await ready();
    await shell().locator('[data-shell-section="perception"]').click();
    await layout();await capture('product-perception-desktop',false);
    await shell().locator('.perception-config-nav [data-perception-tab="config-screen"]').click();
    await shell().locator('#perception-detail-device-access summary').click();
    await shell().locator('#perceptionProviderWorkspace').scrollIntoViewIfNeeded();await capture('product-perception-providers-desktop',false);
    await page.setViewportSize({width:390,height:844});await layout();await shell().locator('body').evaluate(()=>scrollTo(0,0));await capture('product-perception-mobile',false);
    await page.setViewportSize({width:320,height:720});await layout();await shell().locator('body').evaluate(()=>scrollTo(0,0));await capture('product-perception-narrow',false);
    await privateFields();assert.deepEqual(browserErrors,[]);assert.deepEqual(serverErrors,[]);
    checks.push('permission failure clears cached directory and records');
    const report={checks,passed:checks.length,browserErrors,serverErrors,posts:qa.posts.length};
    await fs.writeFile(path.join(outputDir,'product-results.json'),JSON.stringify(report,null,2)+'\n','utf8');return report;
  } catch(error){
    await fs.writeFile(path.join(outputDir,'product-failure.json'),JSON.stringify({error:error.message,checks,browserErrors,serverErrors,calls:qa.calls},null,2)+'\n','utf8');
    await capture('product-failure');throw error;
  }
  finally{await page.close();await new Promise(resolve=>server.close(resolve));}
}
module.exports={run};
if(require.main===module)(async()=>{const browser=await require('playwright').chromium.launch({headless:true,executablePath:process.env.PLAYWRIGHT_EXECUTABLE_PATH});try{console.log(JSON.stringify(await run({browser,outputDir:process.argv[2],bridgePath:process.argv[3],replyOnly:process.argv.includes('--reply-only'),identityOnly:process.argv.includes('--identity-only')}),null,2));}finally{await browser.close();}})().catch(error=>{console.error(error);process.exitCode=1;});
