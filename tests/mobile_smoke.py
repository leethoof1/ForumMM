from playwright.sync_api import sync_playwright
from pathlib import Path
import csv, os
base=os.environ.get("FORUM_TEST_URL","http://127.0.0.1:8090").rstrip("/")
state_dir=Path(os.environ.get("FORUM_STATE_DIR",str(Path.home()/".local/share/forummm")))
artifacts=Path(os.environ.get("FORUM_ARTIFACTS","/tmp/forummm-test-artifacts"));artifacts.mkdir(parents=True,exist_ok=True)
with Path(os.environ['FORUM_CODES_CSV']).open(encoding='utf-8-sig') as f:codes=[r['code'] for r in csv.DictReader(f)][:6]
code=codes[0]
with sync_playwright() as p:
 b=p.chromium.launch(executable_path='/usr/bin/chromium',headless=True,args=['--no-sandbox'])
 c=b.new_context(viewport={'width':390,'height':844},is_mobile=True,has_touch=True);page=c.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
 page.goto(base+'/');page.locator('.schedule').wait_for();assert page.locator('[data-filter]').count()==6
 assert page.locator('[data-filter="main"]').get_attribute('aria-pressed')=='true'
 assert page.locator('[data-filter="all"]').count()==0
 assert page.locator('[data-task]').count()==0
 assert page.locator('.hero').bounding_box()['y']<page.locator('.filters').bounding_box()['y']<page.locator('.next').bounding_box()['y']
 assert page.locator('#demo').count()==0
 assert 'Демоверсия' not in page.locator('body').inner_text()
 page.locator('[data-filter="unity"]').click();assert page.locator('.event').count()==2
 assert 'Росмолодёжь' in page.locator('.next').inner_text()
 page.locator('[data-filter="volunteer"]').click();assert 'Кабинет 202' in page.locator('.schedule').inner_text()
 assert 'Банкетный зал' not in page.locator('.schedule').inner_text()
 page.locator('[data-filter="main"]').click();assert page.locator('.event').count()==8

 assert page.locator('.point').count()==0
 assert page.locator('.note').count()==0
 page.screenshot(path=str(artifacts/'updated-program.png'),animations='disabled',full_page=True)
 page.locator('nav a[href="#tasks"]').click();page.locator('#redeemCode').click();page.locator('#poolword').fill('wrong');page.get_by_role('button',name='Получить балл').click();page.locator('.error').filter(has_text='не найден').wait_for()
 page.locator('#poolword').fill(code);page.get_by_role('button',name='Получить балл').click();page.locator('dialog').wait_for(state='hidden');assert page.locator('.balance b').inner_text()=='1'
 page.reload();page.locator('#redeemCode').wait_for();assert page.locator('.balance b').inner_text()=='1'
 for extra in codes[1:]:
  page.locator('#redeemCode').click();page.locator('#poolword').fill(extra);page.get_by_role('button',name='Получить балл').click();page.locator('dialog').wait_for(state='hidden')
 assert page.locator('.balance b').inner_text()=='6'
 page.locator('nav a[href="#shop"]').click();page.locator('[data-product="kit"]').click();page.locator('#confirm').click();page.locator('dialog').wait_for(state='hidden');page.locator('.historyrow').wait_for();assert 'зону регистрации' in page.locator('.historyrow').inner_text()
 receipt=c.request.get(base+'/api/state').json()['history'][0]['receipt']
 page.locator('[data-deliver]').click();page.locator('#deliverykey').fill('wrong');page.get_by_role('button',name='Мерч выдан',exact=True).click();page.locator('.error').filter(has_text='Неверный').wait_for()
 page.locator('#deliverykey').fill((state_dir/'delivery-code.txt').read_text());page.get_by_role('button',name='Мерч выдан',exact=True).click();page.locator('dialog').wait_for(state='hidden')
 assert page.locator('[data-deliver]').count()==0
 assert page.locator('[data-product="kit"]').is_disabled()
 page.reload();page.get_by_text('✓ Мерч получен',exact=False).wait_for();assert page.locator('.balance b').inner_text()=='0'
 page.screenshot(path=str(artifacts/'updated-receipt.png'),animations='disabled',full_page=True)
 assert page.evaluate('document.documentElement.scrollWidth<=innerWidth');assert not errors,errors
 b.close();print('PASS: six visible filters, default main program, six codes, kit purchase, delivery, repeat purchase blocked')
