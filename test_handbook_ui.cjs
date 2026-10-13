const {chromium}=require('playwright');
const fs=require('fs');
(async()=>{
 const browser=await chromium.launch({headless:true});
 const page=await browser.newPage({viewport:{width:390,height:844}});
 await page.route('http://handbook.test/**',async route=>{
   const url=route.request().url();
   if(url.endsWith('/chat/stream')) { await new Promise(r=>setTimeout(r,300)); return route.fulfill({body:'## CTE WITH\n\nข้อมูลจากชุดข้อมูล',contentType:'text/plain'}); }
   return route.fulfill({body:fs.readFileSync('templates/index.html','utf8'),contentType:'text/html'});
 });
 await page.goto('http://handbook.test/');
 await page.locator('#input').fill('CTE');
 await page.locator('#sendBtn').click();
 await page.getByRole('status').filter({hasText:'กำลังค้นหา'}).waitFor();
 await page.getByText('ข้อมูลจากชุดข้อมูล',{exact:true}).waitFor();
 await page.reload();
 await page.getByText('ข้อมูลจากชุดข้อมูล',{exact:true}).waitFor();
 if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth)) throw Error('Horizontal overflow');
 await page.screenshot({path:'tmp/chat-mobile.png',fullPage:true});
 await page.setViewportSize({width:1440,height:900});
 await page.screenshot({path:'tmp/chat-desktop.png',fullPage:true});
 console.log('PASS: search status, answer, refresh persistence, mobile overflow');
 await browser.close();
})().catch(e=>{console.error(e);process.exit(1)});
