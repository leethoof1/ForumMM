"""Run with playwright installed and a built Pages site served over HTTP."""
import os
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
 browser=p.chromium.launch(headless=True,executable_path='/usr/bin/chromium',args=['--no-sandbox'])
 page=browser.new_page(viewport={'width':390,'height':844},is_mobile=True,has_touch=True)
 errors=[];api_requests=[]
 page.on('pageerror',lambda e:errors.append(str(e)))
 page.on('request',lambda r:api_requests.append(r.url) if '/api/' in r.url else None)
 page.goto(os.environ.get('FORUM_TEST_URL','http://127.0.0.1:8020/dist/'))
 page.get_by_role('heading',name='Программа дня').wait_for()
 page.locator('#demo').fill('12:15');assert page.locator('.livebadge').count()>=2
 page.locator('[data-task="t0"]').click()
 page.locator('#word').fill('неверно');page.get_by_role('button',name='Проверить',exact=True).click()
 page.locator('.error').filter(has_text='Проверь').wait_for()
 page.locator('#word').fill('  мост  ');page.get_by_role('button',name='Проверить',exact=True).click()
 page.locator('dialog').wait_for(state='hidden');assert page.locator('.balance b').inner_text()=='1'
 assert page.locator('[data-task="t0"]').count()==0
 page.locator('[data-task="t1"]').click();page.locator('#word').fill('культура');page.get_by_role('button',name='Проверить',exact=True).click();page.locator('dialog').wait_for(state='hidden')
 assert page.locator('.balance b').inner_text()=='2'
 page.locator('nav a[href="#shop"]').click();page.locator('[data-product="sticker"]').click();page.get_by_role('button',name='Подтвердить обмен').dblclick();page.locator('dialog').wait_for(state='hidden')
 assert page.locator('.balance b').inner_text()=='1';assert page.locator('.historyrow').count()==1
 page.locator('[data-product="shirt"]').click();page.get_by_role('button',name='Подтвердить обмен').click();page.locator('.error').filter(has_text='Нужно ещё 6').wait_for();page.get_by_role('button',name='Отмена').click()
 page.reload();page.get_by_role('heading',name='Магазин мерча').wait_for();assert page.locator('.balance b').inner_text()=='0';assert page.locator('.historyrow').count()==0
 page.locator('nav a[href="#tasks"]').click();page.get_by_role('heading',name='Впечатления в баллах').wait_for();assert page.locator('.done').count()==0;assert page.locator('[data-task]').count()==17
 assert not page.context.cookies();assert not api_requests;assert not errors,errors
 assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
 page.screenshot(path='/tmp/forum-pages-mobile.png',full_page=True)
 browser.close()
 print('PASS: mobile browser demo, parallel events, invalid/valid codes, rewards, exchange, double click, insufficient balance, reload reset, no cookies or API requests')
