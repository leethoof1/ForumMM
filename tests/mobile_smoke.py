from playwright.sync_api import sync_playwright
import csv, os
from pathlib import Path
base=os.environ.get("FORUM_TEST_URL","http://127.0.0.1:8090")
with Path(os.environ['FORUM_CODES_CSV']).open(encoding='utf-8-sig') as f:
 code=next(row['code'] for row in csv.DictReader(f) if row['task_id']=='t0')
artifacts=Path(os.environ.get("FORUM_ARTIFACTS","/tmp/forummm-test-artifacts"));artifacts.mkdir(parents=True,exist_ok=True)
with sync_playwright() as p:
 browser=p.chromium.launch(headless=True,executable_path='/usr/bin/chromium',args=['--no-sandbox'])
 page=browser.new_page(viewport={'width':390,'height':844},is_mobile=True,has_touch=True)
 errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
 page.goto(base);page.get_by_role('heading',name='Программа дня').wait_for()
 page.locator('#demo').fill('12:15');assert page.locator('.livebadge').count()>=2
 page.locator('[data-task="t0"]').click();page.locator('#word').fill('ошибка');page.get_by_role('button',name='Проверить',exact=True).click();page.locator('.error').filter(has_text='Проверь').wait_for()
 page.locator('#word').fill('  '+code.lower()+'  ');page.get_by_role('button',name='Проверить',exact=True).click();page.locator('dialog').wait_for(state='hidden')
 page.reload();page.get_by_text('✓ Выполнено',exact=True).wait_for();assert page.locator('.balance b').inner_text()=='1'
 page.locator('nav a[href="#shop"]').click();page.locator('[data-product="sticker"]').click();page.get_by_role('button',name='Подтвердить обмен').click();page.locator('dialog').wait_for(state='hidden');assert page.locator('.balance b').inner_text()=='0'
 page.reload();page.locator('.historyrow').wait_for();assert page.locator('.historyrow').count()==1
 page.locator('[data-product="shirt"]').click();page.get_by_role('button',name='Подтвердить обмен').click();page.locator('.error').filter(has_text='Нужно ещё 7').wait_for();page.get_by_role('button',name='Отмена').click()
 page.locator('nav a[href="#program"]').click();page.locator('#demo').fill('12:15');assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
 page.screenshot(path=str(artifacts/'mobile.png'),full_page=True)
 page.locator('#demo').fill('13:30');assert page.locator('.livebadge').count()==1
 page.locator('#demo').fill('17:00');assert 'форум завершён' in page.locator('.next').inner_text().lower()
 page.set_viewport_size({'width':1440,'height':1000});page.screenshot(path=str(artifacts/'desktop.png'),full_page=True)
 assert not errors,errors
 print('PASS: mobile flow, wrong/correct code, reload, exchange history, insufficient balance, parallel events, time boundaries, no overflow or JS errors')
 browser.close()
