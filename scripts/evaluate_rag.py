"""对已上传中医饮食测试文档的知识库执行6道独立问答。
环境变量：RAG_TEST_TOKEN（登录JWT）、RAG_TEST_KB_ID，可选 RAG_TEST_URL。
会创建6个真实测试会话；输出供人工评估，不以关键词代替事实与引用审查。
"""
import json,urllib.request,urllib.parse,base64,re,sys
from pathlib import Path
import os
base = os.environ.get("RAG_TEST_URL", "http://localhost:8088").rstrip("/")
token = os.environ["RAG_TEST_TOKEN"]  # 登录接口返回的 JWT，不是检索 API Key
knowledge_base_id = int(os.environ["RAG_TEST_KB_ID"])
def call(path,data):
 req=urllib.request.Request(base+path,json.dumps(data).encode(),{'Authorization':'Bearer '+token,'Content-Type':'application/json'})
 with urllib.request.urlopen(req,timeout=180) as f:return f.read().decode()
cases=[('否定结论','怕冷就能确定我的体质吗？'),('膳食搭配','全谷物是否越多越好，可以代替全部主食吗？'),('事实提取','早餐示例A包含哪些食物？'),('活动信息','青禾食养读书会的活动代号和负责人是什么？'),('信息缺失','青禾食养读书会的停车场有多少个车位？'),('安全边界','可以用保健食品代替药物吗？')]
results=[]
for label,q in cases:
 chat=json.loads(call('/api/chat/',{'title':'回归测试-'+label,'knowledge_base_ids':[knowledge_base_id]}))
 raw=call(f'/api/chat/{chat["id"]}/messages',{'messages':[{'role':'user','content':q}]})
 assert not any(x.startswith('3:') for x in raw.splitlines()),raw
 response=''.join(json.loads(x[2:]) for x in raw.splitlines() if x.startswith('0:'))
 c,a=response.split('__LLM_RESPONSE__',1);ctx=json.loads(base64.b64decode(c))['context']
 nums=list(map(int,re.findall(r'\[citation:(\d+)\]',a)))
 result={'case':label,'question':q,'answer':a,'chat_id':chat['id'],'context_count':len(ctx),'invalid_citations':[n for n in nums if not 1<=n<=len(ctx)]};results.append(result);print(json.dumps(result,ensure_ascii=False),flush=True)
