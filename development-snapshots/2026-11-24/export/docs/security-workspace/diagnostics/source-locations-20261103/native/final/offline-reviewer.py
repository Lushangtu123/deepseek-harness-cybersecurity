"""Offline structural observations for namespace-call candidates; never execute source."""
import argparse
import ast
import codecs
from hashlib import sha256
import io
import json
import os
from pathlib import Path
import re
import stat
import sys
import tokenize

# Small reader derived from the accepted batch reader. No runtime package imports
# or sys.path changes: project files and sibling helper modules cannot be imported.
MAX_BYTES=1048576
MAX_CHECKS=MAX_FILES=64
DIGEST=re.compile(r'[0-9a-f]{64}')
RELATIVE_PY=re.compile(r'(?:[A-Za-z0-9_][A-Za-z0-9_.-]{0,63}/){0,12}[A-Za-z0-9_][A-Za-z0-9_.-]{0,63}\.py')

def read_bounded(file,limit):
    fd=os.open(file,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    with os.fdopen(fd,'rb') as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):raise ValueError('input must be an ordinary file')
        raw=stream.read(limit+1)
    if len(raw)>limit:raise ValueError('input exceeds byte limit')
    return raw

def pinned_sources(root,files):
    if not isinstance(files,dict) or not 1<=len(files)<=MAX_FILES:raise ValueError('invalid file inventory')
    if not root.is_dir() or root.resolve()!=root:raise ValueError('source root must be canonical')
    sources={};remaining=8*MAX_BYTES
    for name,digest in files.items():
        if not isinstance(name,str) or not RELATIVE_PY.fullmatch(name) or not isinstance(digest,str) or not DIGEST.fullmatch(digest):raise ValueError('invalid pinned file')
        file=root/name
        if not file.is_file() or file.resolve()!=file:raise ValueError('pinned file is missing or linked')
        raw=read_bounded(file,min(remaining,MAX_BYTES))
        if sha256(raw).hexdigest()!=digest:raise ValueError('source digest mismatch')
        remaining-=len(raw);sources[name]=raw.decode('utf-8')
    return sources

RULE = 'policy.harness.python.dynamic-code-namespace'
ANCHOR_KEYS = {'line','col','endLine','endCol','offset','endOffset'}

def valid_anchor(anchor):
    return (isinstance(anchor,dict) and set(anchor)==ANCHOR_KEYS
            and all(type(v) is int and v>=0 for v in anchor.values())
            and all(anchor[k]>0 for k in ['line','col','endLine','endCol'])
            and anchor['endOffset']>anchor['offset']
            and (anchor['endLine'],anchor['endCol'])>(anchor['line'],anchor['col']))

def position(call,line_offsets):
    return {'line':call.lineno,'col':call.col_offset+1,
            'endLine':call.end_lineno,'endCol':call.end_col_offset+1,
            'offset':line_offsets[call.lineno-1]+call.col_offset,
            'endOffset':line_offsets[call.end_lineno-1]+call.end_col_offset}

def scope_nodes(node):
    """Include definition headers evaluated here, skip nested definition bodies."""
    for child in ast.iter_child_nodes(node):
        yield child
        if isinstance(child,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef,ast.Lambda)):
            for field,value in ast.iter_fields(child):
                if field in {'body','type_params'}:continue
                for header in value if isinstance(value,list) else [value]:
                    if isinstance(header,ast.AST):
                        yield header
                        yield from scope_nodes(header)
        else:
            yield from scope_nodes(child)

def binds(nodes,name):
    for node in nodes:
        if isinstance(node,ast.Name) and isinstance(node.ctx,(ast.Store,ast.Del)) and node.id==name:
            return True
        if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef)) and node.name==name:
            return True
        if isinstance(node,ast.alias) and (node.asname or node.name.split('.')[0]) in {name,'*'}:
            return True
        if isinstance(node,ast.ExceptHandler) and node.name==name:
            return True
        if isinstance(node,(ast.MatchAs,ast.MatchStar)) and node.name==name:
            return True
        if isinstance(node,ast.MatchMapping) and node.rest==name:
            return True
    return False

def binding_hint(tree,owner,call):
    # Deliberately conservative across the file: these operations invalidate a
    # simple static binding inference. Absence does not prove runtime identity.
    for node in ast.walk(tree):
        if getattr(node,'type_params',None):return 'namespace-effects-observed'
        if isinstance(node,ast.Import) and any(a.name=='builtins' for a in node.names):
            return 'namespace-effects-observed'
        if isinstance(node,ast.ImportFrom) and node.level==0 and node.module=='builtins':
            return 'namespace-effects-observed'
        if isinstance(node,(ast.Global,ast.Nonlocal)):
            return 'scope-effects-unresolved'
        if isinstance(node,ast.Name) and isinstance(node.ctx,ast.Load) and node.id in {'globals','locals','vars','setattr','delattr','__import__','__builtins__','builtins'}:
            return 'namespace-effects-observed'
        if isinstance(node,ast.Name) and isinstance(node.ctx,ast.Load) and node.id in {'eval','exec'} and node is not call.func:
            return 'namespace-effects-observed'
        if isinstance(node,ast.Attribute) and isinstance(node.ctx,(ast.Store,ast.Del)) and node.attr in {'eval','exec','__builtins__'}:
            return 'namespace-effects-observed'
        if isinstance(node,ast.Name) and isinstance(node.ctx,(ast.Store,ast.Del)) and node.id=='__builtins__':
            return 'namespace-effects-observed'
    if binds(scope_nodes(tree),call.func.id):
        return 'module-binding-conflict-observed'
    if owner is None:
        return 'unsupported-scope'
    parameters = [*owner.args.posonlyargs,*owner.args.args,*owner.args.kwonlyargs]
    parameters += [p for p in [owner.args.vararg,owner.args.kwarg] if p]
    if any(p.arg==call.func.id for p in parameters) or binds(scope_nodes(owner),call.func.id):
        return 'local-binding-conflict-observed'
    return 'no-direct-conflict-observed'

def inert_literal(node,depth=0):
    if depth>4: return False
    if isinstance(node,ast.Constant): return type(node.value) in {str,int,float,bool,type(None)}
    if isinstance(node,ast.Dict):
        return len(node.keys)<=16 and all(k is not None and inert_literal(k,depth+1) and inert_literal(v,depth+1) for k,v in zip(node.keys,node.values))
    if isinstance(node,(ast.Tuple,ast.List)):
        return len(node.elts)<=16 and all(inert_literal(v,depth+1) for v in node.elts)
    return False

def fixed_guard(statement,variable):
    if not isinstance(statement,ast.If) or statement.orelse or len(statement.body)!=1:
        return None
    test = statement.test
    if not (isinstance(test,ast.Compare) and isinstance(test.left,ast.Name) and test.left.id==variable
            and len(test.ops)==1 and isinstance(test.ops[0],ast.NotIn)
            and len(test.comparators)==1 and isinstance(test.comparators[0],ast.Tuple)):
        return None
    values = test.comparators[0].elts
    if not 1<=len(values)<=16 or any(not isinstance(v,ast.Constant) or type(v.value) is not str or len(v.value)>128 for v in values):
        return None
    exit_statement = statement.body[0]
    if isinstance(exit_statement,ast.Return):
        if exit_statement.value is not None and not inert_literal(exit_statement.value): return None
    elif not isinstance(exit_statement,ast.Raise):
        return None
    literals = sorted({v.value for v in values})
    return {'state':'fixed-set-guard-observed','guardLine':statement.lineno,'literalCount':len(literals),
            'literalSetSha256':sha256(json.dumps(literals,ensure_ascii=True,separators=(',',':')).encode()).hexdigest(),
            'runtimeStringSemantics':'unverified','fixedValuesMayExecuteCode':True}

def direct_statement(statement,call):
    if isinstance(statement,(ast.Return,ast.Expr)): return statement.value is call
    return (isinstance(statement,ast.Assign) and len(statement.targets)==1
            and isinstance(statement.targets[0],ast.Name) and statement.value is call)

def constraint_hint(owner,statement,call,binding):
    unknown = lambda reason:{'state':'unresolved','reason':reason}
    if binding!='no-direct-conflict-observed' or owner is None:
        return unknown('callee-or-scope-unresolved')
    if owner.decorator_list or owner.returns is not None or any(a.annotation is not None for a in ast.walk(owner.args) if isinstance(a,ast.arg)):
        return unknown('definition-effects-unresolved')
    defaults = [*owner.args.defaults,*[d for d in owner.args.kw_defaults if d is not None]]
    if any(not inert_literal(d) for d in defaults): return unknown('definition-effects-unresolved')
    if not direct_statement(statement,call) or statement not in owner.body: return unknown('execution-statement-not-direct')
    if not isinstance(call.args[0],ast.Name): return unknown('source-is-not-simple-name')
    variable = call.args[0].id
    parameters = [*owner.args.posonlyargs,*owner.args.args,*owner.args.kwonlyargs]
    if not any(a.arg==variable for a in parameters): return unknown('source-origin-unresolved')
    before = owner.body[:owner.body.index(statement)]
    if len(before)>16: return unknown('prefix-limit')
    known_literals = set()
    evidence = None
    for part in before:
        if isinstance(part,ast.Pass): continue
        if isinstance(part,ast.Expr) and isinstance(part.value,ast.Constant) and type(part.value.value) is str: continue
        observed = fixed_guard(part,variable)
        if observed:
            if evidence is not None: return unknown('multiple-guards')
            evidence = observed
            continue
        if isinstance(part,ast.Assign) and len(part.targets)==1 and isinstance(part.targets[0],ast.Name):
            target = part.targets[0].id
            if target in {variable,'eval','exec'}: return unknown('source-or-callee-reassigned')
            if not inert_literal(part.value): return unknown('intervening-effects-unresolved')
            known_literals.add(target)
            continue
        return unknown('control-flow-or-effects-unresolved')
    for namespace in call.args[1:]:
        if inert_literal(namespace): continue
        if isinstance(namespace,ast.Name) and namespace.id in known_literals: continue
        return unknown('namespace-evaluation-unresolved')
    return evidence or unknown('no-supported-guard')

def review_namespace_call(source,anchor):
    if not isinstance(source,str) or not valid_anchor(anchor): return None
    try:
        raw=source.encode('utf-8')
        if len(raw)>MAX_BYTES or re.search(rb'\r(?!\n)',raw): return None
        encoding,_=tokenize.detect_encoding(io.BytesIO(raw).readline)
        if codecs.lookup(encoding).name!='utf-8':return None
        line_offsets=[0]+[i+1 for i,b in enumerate(raw) if b==10]
        tree = ast.parse(source)
        nodes = list(ast.walk(tree))
        if len(nodes)>50000: return None
        matches = [n for n in nodes if isinstance(n,ast.Call) and position(n,line_offsets)==anchor
                   and isinstance(n.func,ast.Name) and n.func.id in {'eval','exec'}
                   and len(n.args) in {2,3} and not n.keywords and not any(isinstance(a,ast.Starred) for a in n.args)]
        if len(matches)!=1: return None
        call = matches[0]
        parents = {child:parent for parent in nodes for child in ast.iter_child_nodes(parent)}
        current = call
        while current in parents and not isinstance(parents[current],(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef)):
            current = parents[current]
        owner = parents.get(current)
        statement = current
        if not isinstance(owner,ast.FunctionDef) or owner not in tree.body or statement not in owner.body:
            owner = None
        binding = binding_hint(tree,owner,call)
        argument = call.args[0]
        kind = 'expression-unresolved'
        writes = []
        if isinstance(argument,ast.Constant): kind = 'literal-expression-observed'
        elif isinstance(argument,ast.Name) and owner is not None and direct_statement(statement,call):
            parameters = [*owner.args.posonlyargs,*owner.args.args,*owner.args.kwonlyargs]
            kind = 'parameter-name-observed' if any(a.arg==argument.id for a in parameters) else 'local-name-unresolved'
            prefix = ast.Module(body=owner.body[:owner.body.index(statement)],type_ignores=[])
            writes = sorted({n.lineno for n in scope_nodes(prefix) if isinstance(n,ast.Name)
                             and isinstance(n.ctx,(ast.Store,ast.Del)) and n.id==argument.id})
            if writes: kind = 'local-reassignment-observed'
            elif binds(scope_nodes(prefix),argument.id):kind='local-binding-observed'
        constraint = constraint_hint(owner,statement,call,binding)
        return {'version':2,'observation':'namespace-call-structure-observed','anchor':dict(anchor),
                'sink':call.func.id,'argumentCount':len(call.args),'disposition':'unverified',
                'callee':{'staticBinding':binding,'builtinIdentity':'unverified'},
                'source':{'kind':kind,'assignmentLines':writes,'externalControl':'unverified'},
                'constraint':constraint}
    except (SyntaxError,ValueError,RecursionError,UnicodeError,LookupError):
        return None

def review_namespace_batch(root,manifest,scan):
    if not isinstance(manifest,dict) or not isinstance(scan,dict): raise ValueError('invalid input objects')
    sources = pinned_sources(root,manifest.get('files'))
    hits = scan.get('results')
    if not isinstance(hits,list) or len(hits)>2000: raise ValueError('invalid findings')
    seen = set();observations = [];unmatched = []
    ignored={'different-rule':0,'unsupported-rule-prefix':0,'unpinned-path':0}
    for hit in hits:
        if not isinstance(hit,dict): raise ValueError('invalid finding')
        if hit.get('check_id')!=RULE:
            rule=hit.get('check_id')
            ignored['unsupported-rule-prefix' if isinstance(rule,str) and rule.endswith('harness.python.dynamic-code-namespace') else 'different-rule']+=1
            continue
        path = hit.get('path')
        if not isinstance(path,str): raise ValueError('invalid finding path')
        path = path.removeprefix('/src/')
        if path not in sources:ignored['unpinned-path']+=1;continue
        start,end = hit.get('start'),hit.get('end')
        if not isinstance(start,dict) or not isinstance(end,dict): raise ValueError('missing full anchor')
        anchor = {'line':start.get('line'),'col':start.get('col'),'endLine':end.get('line'),'endCol':end.get('col'),
                  'offset':start.get('offset'),'endOffset':end.get('offset')}
        if not valid_anchor(anchor): raise ValueError('invalid full anchor')
        key = (path,*[anchor[k] for k in ['line','col','endLine','endCol','offset','endOffset']])
        if key in seen: continue
        seen.add(key)
        if len(seen)>MAX_CHECKS: raise ValueError('namespace check limit')
        row = review_namespace_call(sources[path],anchor)
        metadata = {'file':path,'rule':RULE,'sourceSha256':manifest['files'][path]}
        if row: observations.append({**metadata,**row})
        else: unmatched.append({**metadata,'anchor':anchor,'reason':'no-exact-supported-call'})
    partial=bool(unmatched or ignored['unsupported-rule-prefix'] or ignored['unpinned-path'] or hits and not seen)
    return {'version':2,'state':'partial' if partial else 'completed','checks':len(seen),'ignoredHits':ignored,
            'observations':observations,'unmatchedAnchors':unmatched,
            'changesFindingDisposition':False,'r3Qualified':False}

if __name__=='__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root',type=Path);parser.add_argument('manifest',type=Path);parser.add_argument('scan',type=Path)
    args = parser.parse_args()
    try:
        if not sys.flags.isolated or not sys.dont_write_bytecode:raise ValueError('run with python3 -I -B')
        root=args.root.absolute()
        if any(root==Path(p).resolve() or root in Path(p).resolve().parents for p in sys.path if p):raise ValueError('source root overlaps import path')
        manifest = json.loads(read_bounded(args.manifest,MAX_BYTES))
        raw = read_bounded(args.scan,8*MAX_BYTES)
        if not isinstance(manifest,dict) or manifest.get('scanSha256')!=sha256(raw).hexdigest(): raise ValueError('scan digest mismatch')
        report = review_namespace_batch(root,manifest,json.loads(raw))
    except (ValueError,OSError,RecursionError,UnicodeError) as error:
        parser.exit(1,'Review rejected: '+str(error)+'\n')
    print(json.dumps(report))
