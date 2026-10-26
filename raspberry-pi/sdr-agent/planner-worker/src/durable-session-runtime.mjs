import { boundedText, makeSessionResponse } from './session-protocol.mjs';
import { formatUpstreamError } from './planner-failure.mjs';

// Protocol v2 is explicit opt-in. The socket is the attachment lifetime; a
// disconnect revokes delivery, clears pending acknowledgements and joins abort.
export class DurableSessionRuntime {
  constructor({ createEngine, plannerMeta, ackTimeoutMs = 5000 }) {
    this.createEngine = createEngine;
    this.plannerMeta = plannerMeta;
    this.ackTimeoutMs = ackTimeoutMs;
    this.pending = new Map();
    this.requests = new Map();
    this.engine = undefined;
    this.identity = undefined;
    this.active = false;
    this.closing = false;
    this.emit = () => {};
    this.monitor = undefined;
    this.revision = 0;
  }

  async dispatch(command, emit) {
    this.emit = emit;
    try {
      if (command.protocol_version !== 2) throw new Error('durable sessions require protocol version 2');
      if (command.type === 'open_session') {
        if (this.engine) throw new Error('a session is already open');
        this.closing = false;
        this.identity = {appSessionId:command.app_session_id,controllerEpoch:command.controller_epoch,sessionGeneration:command.session_generation};
        const created = await this.createEngine({deliver:p=>this.#deliver(p),onProgress:p=>this.#progress(p)});
        this.engine = created.engine;
        this.plannerMeta = created.plannerMeta ?? this.plannerMeta;
        await this.engine.attach(this.identity);
        const prior=await this.engine.state(this.identity.appSessionId);
        for(const request of Object.values(prior.requests).filter(r=>r.proposal && !r.enabled).slice(-16)) {
          this.#event('plan_status_query',{plan_id:request.proposal.planId,hash:request.proposal.hash});
        }
        return makeSessionResponse(command,true,await this.#state());
      }
      if (!this.engine || this.closing) throw new Error('no session is open');
      if (command.session_generation !== this.identity.sessionGeneration) throw new Error('command belongs to a stale session generation');
      switch(command.type) {
        case 'plan_status':
          await this.engine.reconcile(this.identity.appSessionId,command);
          return makeSessionResponse(command,true,{recorded:true});
        case 'plan_ack': {
          const pending=this.pending.get(command.plan_id);
          if (pending) {
            if(pending.hash !== command.hash)throw new Error('conflicting acknowledgement');
            pending.resolve({planId:command.plan_id,hash:command.hash,state:command.state});
          }else await this.engine.acknowledge(this.identity.appSessionId,command);
          return makeSessionResponse(command,true,{recorded:true});
        }
        case 'prompt': case 'steer': case 'follow_up': {
          if(command.type==='prompt' && this.active)throw new Error('Agent is busy; use steer or follow_up');
          if(command.type!=='prompt' && !this.active) throw new Error('queue requires an active Agent run');
          this.revision++;
          const prior=this.requests.get(command.context.request_id);
          this.requests.set(command.context.request_id,command.context);
          let id;
          try {id=await this.engine.submit(this.identity.appSessionId,command.context,{mode:command.type==='prompt'?'prompt':command.type});}
          catch(error){if(prior)this.requests.set(command.context.request_id,prior);else this.requests.delete(command.context.request_id);throw error;}
          this.active=true;
          if(!this.monitor) this.monitor=this.#monitor().finally(()=>{this.monitor=undefined;});
          return makeSessionResponse(command,true,{accepted:true,submission_id:id});
        }
        case 'clear_queue': {
          const cleared=await this.engine.clearQueue(this.identity.appSessionId);
          return makeSessionResponse(command,true,{cleared});
        }
        case 'abort': {
          // Close the delivery fence and unblock tool ACK waits before joining.
          this.closing=true;this.#rejectPending();
          await this.engine.abort(this.identity.appSessionId);
          await this.monitor;
          await this.engine.attach(this.identity);
          this.closing=false;
          this.#event('agent_end');
          return makeSessionResponse(command,true,{abort_requested:true});
        }
        case 'get_state': return makeSessionResponse(command,true,await this.#state());
        case 'close_session': {
          await this.engine.closeSession(this.identity.appSessionId);
          await this.monitor;
          await this.engine.close();this.engine=undefined;
          return makeSessionResponse(command,true,{closed:true});
        }
        default: throw new Error('unsupported durable session command');
      }
    } catch(error) {return makeSessionResponse(command,false,formatUpstreamError(error));}
  }

  #event(event,data) {
    if(!this.closing) this.emit({protocol_version:2,type:'event',session_generation:this.identity.sessionGeneration,event,...(data===undefined?{}:{data})});
  }

  async #deliver(proposal) {
    if(this.closing || !this.identity || proposal.controllerEpoch!==this.identity.controllerEpoch || proposal.sessionGeneration!==this.identity.sessionGeneration) throw new Error('delivery attachment closed');
    const requestId=Number(proposal.key.split(':').at(-1));
    // Requests from a prior attachment cannot regain a delivery context.
    const request=this.requests.get(requestId);
    if(!request) throw new Error('proposal has no current Controller request');
    let timer;
    try {
      return await new Promise((resolve,reject)=>{
        this.pending.set(proposal.planId,{hash:proposal.hash,resolve,reject});
        timer=setTimeout(()=>reject(new Error('Controller acknowledgement deadline exceeded')),this.ackTimeoutMs);
        if(this.closing)throw new Error('delivery attachment closed');
        this.emit({protocol_version:2,type:'event',session_generation:proposal.sessionGeneration,event:'plan_proposed',
          delivery:{plan_id:proposal.planId,hash:proposal.hash,controller_epoch:proposal.controllerEpoch,app_session_id:proposal.appSessionId,request_id:requestId,session_generation:proposal.sessionGeneration,deadline_unix_ms:proposal.deadlineUnixMs},
          data:{protocol_version:1,request_id:requestId,session_generation:proposal.sessionGeneration,status:'ok',planner:this.plannerMeta,action:proposal.action}});
      });
    }finally{clearTimeout(timer);this.pending.delete(proposal.planId);}
  }

  #progress({appSessionId,requestId,event}) {
    if(appSessionId!==this.identity?.appSessionId || this.closing)return;
    if(['web_search_start','web_search_end','web_search_error'].includes(event.type))this.#event(event.type,{...event.data,request_id:requestId});
    if(['thinking_start','thinking_end'].includes(event.type))this.#event(event.type,{request_id:requestId});
    if(event.type==='thinking_delta')this.#event('thinking_delta',{request_id:requestId,delta:boundedText(event.delta,8192,'')});
    if(event.type==='done') {
      const text=event.message.content.filter(b=>b.type==='text').map(b=>b.text).join('');
      if(text)this.#event('assistant_message',{text:boundedText(text,8192,'')});
    }
    if(event.type==='error')this.#event('agent_error',{error:boundedText(event.error.errorMessage,512,'upstream unavailable')});
  }

  async #monitor() {
    try {
      let state;
      while(true){
        const revision=this.revision;
        await this.engine.idle();
        state=await this.engine.state(this.identity.appSessionId);
        if(revision===this.revision)break;
      }
      for(const request of Object.values(state.requests)) {
        if(request.enabled && !request.proposal && !request.reason)this.#event('agent_error',{error:'No valid proposal; request failed or queue was withdrawn. Submit a new request.'});
        if(request.proposal?.state==='unknown')this.#event('agent_error',{error:'Proposal acknowledgement unknown; reconciliation required. It will not be resent.'});
      }
    }catch(error){this.#event('agent_error',{error:formatUpstreamError(error)});}
    finally{this.active=false;this.requests.clear();this.#event('agent_end');}
  }

  async #state() {
    const state=await this.engine.state(this.identity.appSessionId);
    const blocked=await this.engine.blocked(this.identity.appSessionId);
    return {blocked,open:true,active:this.active,durable:true,queued:Object.values(state.requests).filter(r=>r.enabled && !r.reason && !r.proposal && r.modelAttempts===0).length,
      requests:Object.entries(state.requests).slice(-16).map(([key,r])=>({key,reason:r.reason,proposal_state:r.proposal?.state??null,execution_state:r.proposal?.controllerExecution??null}))};
  }

  #rejectPending(){for(const p of this.pending.values())p.reject(new Error('Controller disconnected or aborted'));}

  async dispose() {
    this.closing=true;this.#rejectPending();
    if(!this.engine)return;
    try{await this.engine.abort(this.identity.appSessionId);await this.monitor;}
    finally{await this.engine.close();this.engine=undefined;}
  }
}
