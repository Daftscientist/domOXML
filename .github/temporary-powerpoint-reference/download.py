from __future__ import annotations
from pathlib import Path
from io import BytesIO
from PIL import Image
import requests
import json

out=Path('powerpoint-shell-reference')
out.mkdir(exist_ok=True)
base='https://cdn-dynmedia-1.microsoft.com/is/image/microsoftcorp/MSFT-Windows-apps-panel-4-tabbed-feature-image-3'
urls=[base+'?wid=2400',base+'?wid=1920',base+'?scl=1']
metadata=[]
for i,url in enumerate(urls):
    try:
        resp=requests.get(url,headers={'User-Agent':'Mozilla/5.0'},timeout=30)
        resp.raise_for_status()
        im=Image.open(BytesIO(resp.content))
        name=f'microsoft-official-{i}-{im.width}x{im.height}.png'
        im.convert('RGB').save(out/name)
        metadata.append({'url':url,'name':name,'size':im.size,'status':'OK'})
        print('SUCCESS',name,'bytes',len(resp.content),flush=True)
    except Exception as exc:
        print('FAILED',url,repr(exc),flush=True)
        metadata.append({'url':url,'error':str(exc)})
(out/'sources.json').write_text(json.dumps(metadata,indent=2))
if not any(x.get('status')=='OK' for x in metadata):
    raise SystemExit('Could not retrieve official reference')
