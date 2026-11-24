export class NativeGate {
  constructor(engagement) { this.engagement=engagement; this.start=null; this.task=null }
  deny(request) {
    if(!request || request.engagement!==this.engagement) return 'Wrong isolated engagement';
    if(['securityStatus','securityReport','securityPreflight'].includes(request.op)) return;
    if(request.op==='securityRuntime' && request.action==='status') return;
    if(request.op!=='securityJoint') return 'Operation not admitted';
    const {action}=request;
    if(action==='plan') return request.mode!==undefined && request.mode!=='deep' ? 'Deep plan only' : undefined;
    if(action==='start') {
      if(request.mode!=='deep' || request.profileRevision!==1 || JSON.stringify(request.steps)!=='["semgrep"]'
          || !Number.isSafeInteger(request.budgetSeconds) || request.budgetSeconds<1 || request.budgetSeconds>360
          || !/^[-a-zA-Z0-9_]{8,100}$/.test(request.requestId??'')) return 'Only the fixed local Semgrep step';
      const key=JSON.stringify([request.requestId,request.mode,request.profileRevision,request.steps,request.budgetSeconds]);
      if(this.start && this.start!==key) return 'A different start is not admitted';
      this.start=key; this.requestId=request.requestId; return;
    }
    if(!['status','wait','report'].includes(action)) return 'Read original task only';
    if(request.id!==undefined && request.id!==this.task) return 'Task identity mismatch';
    if(['wait','report'].includes(action) && (!this.task || request.id!==this.task)) return 'Task identity missing';
    if(request.requestId!==undefined && request.requestId!==this.requestId) return 'Original request identity mismatch';
  }
  remember(request,result) {
    if(request.action!=='start' || !result?.ok) return;
    if(typeof result.task?.id!=='string' || !result.task.id || this.task && this.task!==result.task.id)
      throw Error('Actual task identity changed');
    this.task=result.task.id;
  }
}
