import test from 'node:test';import assert from 'node:assert/strict';import {absenceReply} from './container-absence.mjs';
const id='a'.repeat(64);
test('Docker absent-object messages accept ASCII case variants with exact identity',()=>{for(const stderr of ['Error: No such object: '+id+'\n','error: no such object: '+id+'\n'])assert.equal(absenceReply({status:1,stdout:'[]\n',stderr},id),true)});
test('Daemon, permission, wrong identity and successful inspect are not absence',()=>{for(const r of [{status:1,stdout:'[]',stderr:'cannot connect'},{status:1,stdout:'[]',stderr:'error: no such object: other'},{status:0,stdout:'[]',stderr:'error: no such object: '+id},{status:1,stdout:'[{"Id":"x"}]',stderr:'error: no such object: '+id}])assert.equal(absenceReply(r,id),false)});
