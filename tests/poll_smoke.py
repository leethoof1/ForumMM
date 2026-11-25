"""Browser checks for unlisted poll pages. Use a separate loopback test server."""
import json,os
from pathlib import Path
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright
base=os.environ.get('FORUM_TEST_URL','http://127.0.0.1:8101').rstrip('/')
assert urlsplit(base).hostname in ['localhost','127.0.0.1']
links=json.loads((Path(os.environ['FORUM_STATE_DIR'])/'poll-links.json').read_text())
tokens={k:v.split('#')[1] for k,v in links.items()}
with sync_playwright() as p:
 b=p.chromium.launch(executable_path='/usr/bin/chromium',headless=True,args=['--no-sandbox'])
 admin=b.new_page();errors=[];admin.on('pageerror',lambda e:errors.append(str(e)))
 api=lambda action,body:admin.request.post(base+'/api/poll/'+action,headers={'X-Forum-Request':'1'},data=body)
 assert api('manage',{'token':tokens['control'],'action':'reset','confirm':'RESET-POLL'}).ok
 admin.goto(base+'/poll-admin#'+tokens['control']);admin.get_by_role('button',name='Открыть голосование',exact=True).wait_for();admin.get_by_role('button',name='Открыть голосование',exact=True).click()
 admin.get_by_text('Голосование открыто',exact=True).wait_for()
 c=b.new_context(viewport={'width':390,'height':844});voter=c.new_page();voter.on('pageerror',lambda e:errors.append(str(e)))
 voter.goto(base+'/vote#'+tokens['vote']);voter.locator('[data-choice=adults]').wait_for();voter.locator('[data-choice=adults]').click();voter.get_by_role('heading',name='Твой голос учтён!').wait_for()
 voter.reload();voter.get_by_role('heading',name='Твой голос учтён!').wait_for();assert voter.locator('[data-choice]').count()==0
 reply=c.request.post(base+'/api/poll/vote',headers={'X-Forum-Request':'1'},data={'token':tokens['vote'],'choice':'youth'});assert reply.status==409
 screen=b.new_page(viewport={'width':1440,'height':900});screen.on('pageerror',lambda e:errors.append(str(e)))
 screen.goto(base+'/results#'+tokens['results']);screen.locator('.poll-total').filter(has_text='1').wait_for();screen.locator('#poll-qr img').wait_for();screen.wait_for_timeout(200)
 assert screen.locator('#poll-qr img').evaluate('(img)=>img.complete&&img.naturalWidth>0')
 assert len(screen.locator('.poll-results .card').all())==2
 blank=b.new_page();blank.goto(base+'/vote');blank.get_by_text('Открой полную ссылку',exact=False).wait_for();assert blank.locator('[data-choice]').count()==0
 assert not errors,errors
 screen.screenshot(path='/tmp/forummm-poll-screen.png',full_page=True)
 admin.get_by_role('button',name='Закрыть голосование',exact=True).click();admin.get_by_text('Голосование закрыто',exact=True).wait_for()
 b.close();print('PASS: control open/close, mobile voting, immutable vote, reload, QR, live results, token-free access denied')
