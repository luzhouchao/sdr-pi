import { readFile } from 'node:fs/promises';
import { createModels } from '@earendil-works/pi-ai';
import { fauxProvider, fauxAssistantMessage, fauxToolCall } from '@earendil-works/pi-ai/providers/faux';
import { DurablePlanner } from '../src/durable-planner.mjs';
import { openDurableStore } from '../src/durable-store.mjs';
import { RunLease } from '../src/run-lease.mjs';

const [path, stage]=process.argv.slice(2);
const park=async name=>{process.send({stage:name});await new Promise(()=>{});};
if(stage==='lock') {
  await openDurableStore(path);await park('locked');
} else {
  const faux=fauxProvider({provider:'durable-test',models:[{id:'test',contextWindow:32768,maxTokens:512}],tokensPerSecond:100000});
  const models=createModels();models.setProvider(faux.provider);
  faux.setResponses([async()=>{
    if(stage==='model')await park('model');
    return fauxAssistantMessage(fauxToolCall('submit_plan',{action:'hold',reason:'crash verification'}),{stopReason:'toolUse'});
  }]);
  const engine=await DurablePlanner.open({path,models,model:{provider:'durable-test',modelId:'test'},providerIdentity:{provider:'durable-test',model:'test'},runLease:new RunLease(),
    beforeDelivery:async()=>{if(stage==='prepared')await park('prepared');},
    deliver:async()=>{await park('attempted');},
  });
  await engine.attach({appSessionId:'session_a',controllerEpoch:'epoch_a',sessionGeneration:3});
  const request=JSON.parse(await readFile(new URL('../../../../jetson-agx/sdrharness/config/request.json',import.meta.url)));
  await engine.submit('session_a',{...request,request_id:9,session_generation:3},{deadline:Date.now()+120000});
}
