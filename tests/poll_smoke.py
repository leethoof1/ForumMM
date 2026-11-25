"""Browser checks for unlisted poll pages. Use a separate loopback test server."""
import json,os
from pathlib import Path
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright
base=os.environ.get('FORUM_TEST_URL','http://127.0.0.1:8101').rstrip('/')
assert urlsplit(base).hostname in ['localhost','127.0.0.1']
links=json.loads((Path(os.environ['FORUM_STATE_DIR'])/'poll-links.json').read_text())
tokens={k:(v.split('#',1)[1] if '#' in v else '') for k,v in links.items()}
with sync_playwright() as p:
 b=p.chromium.launch(executable_path='/usr/bin/chromium',headless=True,args=['--no-sandbox'])
 admin=b.new_page();errors=[];admin.on('pageerror',lambda e:errors.append(str(e)))
 api=lambda action,body:admin.request.post(base+'/api/poll/'+action,headers={'X-Forum-Request':'1'},data=body)
 assert api('manage',{'token':tokens['control'],'action':'reset','confirm':'RESET-POLL'}).ok
 admin.goto(base+'/control#'+tokens['control']);admin.get_by_role('button',name='Открыть голосование',exact=True).wait_for();admin.get_by_role('button',name='Открыть голосование',exact=True).click()
 admin.get_by_text('Голосование открыто',exact=True).wait_for()
 c=b.new_context(viewport={'width':390,'height':844});voter=c.new_page();voter.on('pageerror',lambda e:errors.append(str(e)))
 voter.goto(base+'/vote#'+tokens['vote']);voter.locator('[data-choice=adults]').wait_for();voter.locator('[data-choice=adults]').click();voter.get_by_role('heading',name='Твой голос учтён!').wait_for()
 voter.reload();voter.get_by_role('heading',name='Твой голос учтён!').wait_for();assert voter.locator('[data-choice]').count()==0
 reply=c.request.post(base+'/api/poll/vote',headers={'X-Forum-Request':'1'},data={'token':tokens['vote'],'choice':'youth'});assert reply.status==409
 screen=b.new_page(viewport={'width':1440,'height':900});screen.on('pageerror',lambda e:errors.append(str(e)))
 screen.goto(base+'/results#'+tokens['results']);screen.locator('.poll-total').filter(has_text='1').wait_for();screen.locator('#poll-qr img').wait_for();screen.wait_for_timeout(200)
 assert screen.locator('#poll-qr img').evaluate('(img)=>img.complete&&img.naturalWidth>0')
 assert screen.locator('.poll-comparison').count()==1
 assert screen.locator('.poll-shared-bar').count()==1
 assert screen.locator('[data-count=adults]').inner_text()=='1'
 assert screen.locator('[data-percent=adults]').inner_text()=='100%'
 screen.evaluate("window.originalResults = document.querySelector('.poll-comparison'); window.originalQr = document.querySelector('#poll-qr img')")
 c2=b.new_context();other=c2.new_page();other.goto(base+'/vote')
 other.locator('[data-choice=youth]').click();other.get_by_role('heading',name='Твой голос учтён!').wait_for()
 screen.locator('#poll-total-count').filter(has_text='2').wait_for()
 assert screen.locator('[data-percent=adults]').inner_text()=='50%'
 assert screen.locator('[data-percent=youth]').inner_text()=='50%'
 assert screen.locator('[data-count=youth]').inner_text()=='1'
 assert screen.locator('#poll-red').get_attribute('width')=='500'
 assert screen.locator('#poll-blue').get_attribute('width')=='500'
 assert screen.evaluate("window.originalResults === document.querySelector('.poll-comparison') && window.originalQr === document.querySelector('#poll-qr img')")
 assert screen.locator('.poll-comparison').evaluate('(el)=>el.getAnimations({subtree:true}).length')==0
 blank=b.new_page();blank.goto(base+'/results');blank.get_by_text('Открой полную ссылку',exact=False).wait_for();assert blank.locator('.poll-count').count()==0
 assert not errors,errors
 for _ in range(6):
  extra=b.new_context()
  assert extra.request.post(base+'/api/poll/view',headers={'X-Forum-Request':'1'},data={'token':''}).ok
  assert extra.request.post(base+'/api/poll/vote',headers={'X-Forum-Request':'1'},data={'token':'','choice':'youth'}).ok
  extra.close()
 screen.locator('#poll-total-count').filter(has_text='8').wait_for()
 assert screen.locator('[data-percent=adults]').inner_text()=='12,5%'
 assert screen.locator('[data-percent=youth]').inner_text()=='87,5%'
 assert screen.locator('#poll-red').get_attribute('width')=='125'
 assert screen.locator('#poll-blue').get_attribute('width')=='875'
 screen.locator('.poll-comparison').screenshot(path='/workspace/forummm-artifacts/poll-shared-bar.png')
 screen.screenshot(path='/tmp/forummm-poll-screen.png',full_page=True)
 assert api('manage',{'token':tokens['control'],'action':'reset','confirm':'RESET-POLL'}).ok
 screen.locator('#poll-total-count').filter(has_text='0').wait_for()
 assert screen.locator('[data-percent=adults]').inner_text()=='0%'
 assert screen.locator('#poll-red').get_attribute('width')=='0'
 assert screen.locator('#poll-blue').get_attribute('width')=='0'
 assert screen.evaluate("window.originalResults === document.querySelector('.poll-comparison')")
 admin.get_by_role('button',name='Закрыть голосование',exact=True).click();admin.get_by_text('Голосование закрыто',exact=True).wait_for()
 b.close();print('PASS: control open/close, mobile voting, immutable vote, reload, QR, live results, token-free access denied')
